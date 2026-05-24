"""Double-layer retry decorator with provider-aware RPS limits and exception classification.

Adapted from paper-qa (Apache 2.0).
Upstream references:
  - src/paperqa/utils.py:453-516 — `is_retryable()` + `_get_with_retrying()`
  - src/paperqa/clients/semantic_scholar.py:118-135 — provider-specific S2 retry wrapper

Modifications from upstream (see README-vendored.md, change #4):
  - Synchronous, stdlib-only (no tenacity third-party dep) for Skill portability.
  - Provider-specific RPS bucket (OpenAlex 10 RPS, Semantic Scholar 1 RPS).
  - Exponential backoff (10s → 30s → 90s, 3 attempts) instead of
    `wait_incrementing(0.1, 0.1)` — needed because we may be called from
    parallel SubAgents and need thundering-herd protection.
  - Exception classification: 429 / 5xx / network errors retry; 4xx don't.
"""

from __future__ import annotations

import functools
import logging
import random
import threading
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Provider RPS limits (per V2 §4 federated_kg_resolver design)
# =============================================================================

PROVIDER_RPS: Dict[str, float] = {
    "openalex": 10.0,          # OpenAlex polite pool: 10 req/sec
    "semantic_scholar": 1.0,    # SS: 1 req/sec (without API key); higher with key
    "crossref": 10.0,           # Crossref polite pool similar
    "arxiv": 1.0,
    "pubmed": 3.0,
    "default": 5.0,
}

# Retry policy
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SCHEDULE = (10.0, 30.0, 90.0)  # seconds per attempt


# =============================================================================
# Exception classification
# =============================================================================

class RetryableError(Exception):
    """Marker: caller may retry."""


class NonRetryableError(Exception):
    """Marker: caller should not retry."""


def classify_exception(exc: BaseException) -> str:
    """Classify exception into 'retry' / 'no_retry' based on type and HTTP status if present.

    Heuristics (in priority order):
      1. Explicit marker classes -> obvious decision.
      2. HTTP-status-bearing exception (httpx, requests, urllib) -> inspect status code.
      3. Network errors (ConnectionError, TimeoutError, socket.gaierror) -> retry.
      4. Default -> no_retry (safer to surface unknown errors).
    """
    if isinstance(exc, NonRetryableError):
        return "no_retry"
    if isinstance(exc, RetryableError):
        return "retry"

    # Try to extract an HTTP status code from common exception shapes
    status = _extract_status_code(exc)
    if status is not None:
        if status == 429:
            return "retry"        # Rate limited — backoff and try again
        if 500 <= status < 600:
            return "retry"        # Server error
        if 400 <= status < 500:
            return "no_retry"     # Client error (auth, bad request, not found)
        return "no_retry"

    # Network-level errors
    network_exception_names = (
        "ConnectionError", "ConnectError", "ReadError", "ReadTimeout",
        "TimeoutError", "RemoteDisconnected", "gaierror", "ClientConnectionResetError",
        "ClientResponseError",
    )
    name = type(exc).__name__
    if name in network_exception_names:
        return "retry"
    # httpx exposes a `httpx.ConnectError`; requests exposes `requests.exceptions.ConnectionError`.
    # The name match above catches both.

    return "no_retry"


def _extract_status_code(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of HTTP status from common exception shapes."""
    # httpx HTTPStatusError has .response.status_code
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int):
            return code
    # requests HTTPError stores .response.status_code similarly
    # urllib HTTPError has .code
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status
    return None


# =============================================================================
# Token bucket per provider for RPS pacing
# =============================================================================

class _TokenBucket:
    """Simple per-provider token bucket. Thread-safe.

    Each provider gets one bucket. We refill at rps tokens/sec, capped at burst=rps.
    """

    def __init__(self, rps: float):
        self.rps = rps
        self.capacity = max(1.0, rps)
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` are available."""
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rps)
                self.last_refill = now
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                wait_s = (tokens - self.tokens) / self.rps
            # Sleep outside the lock so we don't block other consumers updating tokens
            time.sleep(min(wait_s, 1.0))


_BUCKETS: Dict[str, _TokenBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def _get_bucket(provider: str) -> _TokenBucket:
    with _BUCKETS_LOCK:
        if provider not in _BUCKETS:
            rps = PROVIDER_RPS.get(provider, PROVIDER_RPS["default"])
            _BUCKETS[provider] = _TokenBucket(rps=rps)
        return _BUCKETS[provider]


def reset_buckets() -> None:
    """Clear all token buckets. Test-only utility."""
    with _BUCKETS_LOCK:
        _BUCKETS.clear()


# =============================================================================
# Decorator: outer exception-classifying retry around inner backoff
# =============================================================================

def retryable_api_call(
    provider: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_schedule: Optional[tuple] = None,
    jitter: bool = True,
) -> Callable:
    """Decorator: per-provider RPS pacing + exponential-backoff retry.

    Usage:
        @retryable_api_call(provider="openalex")
        def fetch_work(work_id: str) -> dict:
            return httpx.get(f"https://api.openalex.org/works/{work_id}").raise_for_status().json()

    Two layers:
      - Outer: classify_exception decides retry vs raise.
      - Inner: exponential backoff using backoff_schedule (default 10s/30s/90s).

    `provider` selects RPS budget from PROVIDER_RPS. Token bucket is shared
    across all decorated functions for the same provider.
    """
    schedule = backoff_schedule or DEFAULT_BACKOFF_SCHEDULE

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bucket = _get_bucket(provider)
            last_exc: Optional[BaseException] = None
            for attempt in range(max_attempts):
                bucket.acquire(1.0)
                try:
                    return func(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 — classify, then re-raise
                    last_exc = exc
                    decision = classify_exception(exc)
                    if decision == "no_retry":
                        logger.debug(
                            "retryable_api_call: non-retryable on %s (%s): %s",
                            provider, type(exc).__name__, exc,
                        )
                        raise
                    if attempt == max_attempts - 1:
                        logger.warning(
                            "retryable_api_call: exhausted %d attempts on %s: %s",
                            max_attempts, provider, exc,
                        )
                        raise
                    base_wait = schedule[min(attempt, len(schedule) - 1)]
                    if jitter:
                        # Random jitter ±25% to break herds
                        wait = base_wait * (0.75 + 0.5 * random.random())
                    else:
                        wait = base_wait
                    logger.info(
                        "retryable_api_call: retry %d/%d on %s in %.1fs (%s)",
                        attempt + 1, max_attempts, provider, wait, exc,
                    )
                    time.sleep(wait)
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("retryable_api_call: completed without return or exception")

        return wrapper

    return decorator


__all__ = [
    "retryable_api_call",
    "classify_exception",
    "RetryableError",
    "NonRetryableError",
    "PROVIDER_RPS",
    "reset_buckets",
]
