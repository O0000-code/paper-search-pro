"""OpenAlex call guard: tell "OpenAlex cannot serve this call" apart from a bad query.

Why this module exists
----------------------
pyalex 0.21 ships ``max_retries=0`` and ends every request with
``raise_for_status()``, so a spent daily budget surfaced as a bare
``requests.HTTPError`` traceback and the whole run stopped there. Every OpenAlex
call in ``openalex_helper`` now goes through :func:`call`, which either returns
the result or raises :class:`OpenAlexUnavailable` — the one signal callers use
to switch the run to the fallback source instead of stopping.

Classification (OpenAlex docs: help.openalex.org/api/errors + /api/authentication)
------------------------------------------------------------------------------
* 429 is returned both for a spent daily budget and for >100 requests/second.
  The official OpenAlex CLI (``openalex-official`` 0.3.3, ``api_client.py``)
  separates them by ``X-RateLimit-Remaining < X-RateLimit-Credits-Required``
  (the latter defaulting to 1). We apply the same test, plus
  ``X-RateLimit-Remaining-USD <= 0``: budget exhausted -> no retry (retrying is
  pointless until the midnight-UTC reset). Otherwise it is throttling -> honour
  ``Retry-After`` (capped) and retry a few times.
* 5xx / connection errors / timeouts -> one retry, then unavailable.
* A rejected API key (401) -> unavailable: the run cannot use OpenAlex at all.
* 400 / 404 / other 4xx are NOT converted: they mean the query or the ID is
  wrong, and switching source would only hide that bug.

Error responses cost no OpenAlex credits, so the extra attempt made before a
switch is free.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Callable, List, Optional

import requests

try:  # pyalex raises QueryError (a ValueError) for 400 and a rejected key.
    from pyalex.api import QueryError as _PyalexQueryError
except Exception:  # pragma: no cover - pyalex is a hard dependency
    _PyalexQueryError = ValueError  # type: ignore

from .quota_guard import parse_quota_headers

# Reason codes carried by OpenAlexUnavailable.reason
BUDGET_EXHAUSTED = "budget_exhausted"
RATE_LIMITED = "rate_limited"
SERVER_ERROR = "server_error"
NETWORK_ERROR = "network_error"
AUTH_REJECTED = "auth_rejected"

_RATE_LIMIT_RETRIES = 3
_MAX_RETRY_AFTER_S = 10.0
_TRANSIENT_RETRIES = 1
_TRANSIENT_WAIT_S = 2.0

# Indirection so tests can run the retry paths without real sleeping.
_sleep: Callable[[float], None] = time.sleep


class OpenAlexUnavailable(Exception):
    """OpenAlex cannot serve this call; the caller should switch source.

    ``partial`` holds whatever results were collected before the failure (e.g.
    the first pages of a paged crawl), so a fallback can keep them instead of
    starting from nothing. ``reset_seconds`` is OpenAlex's own countdown to the
    daily budget reset when the response carried it.
    """

    def __init__(
        self,
        reason: str,
        *,
        status: Optional[int] = None,
        reset_seconds: Optional[int] = None,
        detail: str = "",
    ) -> None:
        self.reason = reason
        self.status = status
        self.reset_seconds = reset_seconds
        self.detail = detail
        self.partial: List[Any] = []
        super().__init__(self.describe())

    def describe(self) -> str:
        """One human-readable clause, e.g. 'daily credit budget exhausted,
        resets in 6h52m'."""
        if self.reason == BUDGET_EXHAUSTED:
            text = "daily credit budget exhausted"
            if self.reset_seconds:
                at = (datetime.now() + timedelta(seconds=self.reset_seconds)).strftime("%H:%M")
                text += f", resets in {format_duration(self.reset_seconds)} (about {at} local time)"
            return text
        return {
            RATE_LIMITED: "still rate-limited after retries",
            SERVER_ERROR: f"server error, HTTP {self.status}",
            NETWORK_ERROR: "unreachable",
            AUTH_REJECTED: "API key rejected",
        }.get(self.reason, self.reason)


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def is_budget_exhausted(headers) -> bool:
    """Official-CLI test on a 429's headers: remaining < credits required, or
    no USD left. Missing headers never count as exhaustion."""
    status = parse_quota_headers(headers)
    if status.remaining_usd is not None and status.remaining_usd <= 0:
        return True
    if status.remaining is not None:
        try:
            required = int(float(headers.get("X-RateLimit-Credits-Required") or 1))
        except (TypeError, ValueError):
            required = 1
        return status.remaining < required
    return False


def call(fn: Callable[[], Any]) -> Any:
    """Run one OpenAlex request ``fn()`` under the retry/classification policy.

    Returns ``fn()``'s result, re-raises errors that mean the request itself is
    wrong, and raises :class:`OpenAlexUnavailable` when OpenAlex cannot serve it.
    """
    rate_retries = 0
    transient_retries = 0
    while True:
        try:
            return fn()
        except requests.HTTPError as exc:
            res = exc.response
            code = getattr(res, "status_code", None)
            headers = getattr(res, "headers", None) or {}
            if code == 429:
                quota = parse_quota_headers(headers)
                if is_budget_exhausted(headers):
                    raise OpenAlexUnavailable(
                        BUDGET_EXHAUSTED, status=429, reset_seconds=quota.reset_seconds
                    ) from exc
                if rate_retries < _RATE_LIMIT_RETRIES:
                    rate_retries += 1
                    wait = quota.retry_after if quota.retry_after else 2 ** rate_retries
                    _sleep(min(float(wait), _MAX_RETRY_AFTER_S))
                    continue
                raise OpenAlexUnavailable(
                    RATE_LIMITED, status=429, reset_seconds=quota.reset_seconds
                ) from exc
            if code == 401:
                raise OpenAlexUnavailable(AUTH_REJECTED, status=401) from exc
            if code is not None and code >= 500:
                if transient_retries < _TRANSIENT_RETRIES:
                    transient_retries += 1
                    _sleep(_TRANSIENT_WAIT_S)
                    continue
                raise OpenAlexUnavailable(SERVER_ERROR, status=code) from exc
            raise
        except (requests.ConnectionError, requests.Timeout) as exc:
            if transient_retries < _TRANSIENT_RETRIES:
                transient_retries += 1
                _sleep(_TRANSIENT_WAIT_S)
                continue
            raise OpenAlexUnavailable(NETWORK_ERROR, detail=str(exc)) from exc
        except _PyalexQueryError as exc:
            # pyalex turns a 401 whose body mentions the key into QueryError
            # ("... Did you configure a valid API key?"); other QueryErrors are
            # malformed queries and must surface unchanged.
            if "api key" in str(exc).lower():
                raise OpenAlexUnavailable(AUTH_REJECTED, status=401, detail=str(exc)) from exc
            raise
