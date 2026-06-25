"""Quota guard: read OpenAlex rate-limit headers and expose a quota snapshot.

Why this module exists
----------------------
pyalex (the SDK openalex_helper uses) calls ``res.json()`` inside
``BaseOpenAlex._get_from_url`` and returns ONLY the parsed body — the
underlying ``requests.Response`` (and therefore its headers) is discarded
(verified 2026-06-25 against pyalex 0.21 ``api.py``). So pyalex does not, and
cannot, hand us the rate-limit headers. To learn how much OpenAlex budget is
left we issue our own lightweight ``GET /works?per_page=1`` using the same auth
the polite/authenticated pool expects, and read the response headers.

Empirically (verified 2026-06-25, authenticated key) OpenAlex returns:

    X-RateLimit-Cost-USD: 0.0001
    X-RateLimit-Credits-Used: 1
    X-RateLimit-Limit: 10000
    X-RateLimit-Limit-USD: 1
    X-RateLimit-Remaining: 9999
    X-RateLimit-Remaining-USD: 0.9999
    X-RateLimit-Reset: 69351            (seconds until the daily window resets)
    Retry-After: <present only when throttled>

``requests`` headers are case-insensitive, so the lowercase spellings used in
some OpenAlex docs (``x-ratelimit-remaining-usd``) resolve fine.

Design contract (R-12 — share the read, NOT the policy)
-------------------------------------------------------
Different consumers want different *decisions* from the same *reading*:

* Feature C (run-level source switching) wants a sticky verdict: "is OpenAlex
  budget low enough that I should switch this whole run to Semantic Scholar?"
* Feature B (headless single probe) wants only a *snapshot* — the raw numbers
  to embed in a JSON envelope's ``meta.ratelimit`` — and must NEVER receive a
  switch directive.

Therefore the decision function takes a ``mode`` parameter:

* ``mode="run"``   -> may return ``should_switch=True`` when remaining_usd is at
                      or below the threshold (the C policy).
* ``mode="probe"`` -> ``should_switch`` is ALWAYS False; callers just read the
                      snapshot (the B policy).

Header reading is shared; switching policy is not. This module is pure: it makes
at most one tiny HTTP call and never mutates global SDK state, so it is safe to
call from ss_helper / agent_search / the human path without side effects.

This module never raises on a network/quota failure — it returns a
``QuotaStatus`` with ``ok=False`` and an ``error`` string so callers can decide
what to do (a quota probe failing must not crash a search).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Literal, Optional

import requests

from .types import Config

# OpenAlex works endpoint. per_page=1 keeps the probe cheap (1 credit, ~$0.0001
# observed) while still returning the full X-RateLimit-* header set.
_PROBE_URL = "https://api.openalex.org/works?per_page=1"
_PROBE_TIMEOUT = 15  # seconds — a probe must fail fast, never hang a search.

# User-Agent used for the probe. Mirrors pyalex's polite-pool intent.
_PROBE_USER_AGENT = "paper-search-pro-quota-guard"

Mode = Literal["run", "probe"]


# ---------------------------------------------------------------------------
# Data type
# ---------------------------------------------------------------------------


@dataclass
class QuotaStatus:
    """Structured snapshot of OpenAlex remaining quota.

    All numeric fields are Optional because (a) a no-key/polite-pool request may
    omit some headers and (b) a failed probe leaves them None. ``ok`` tells the
    caller whether the snapshot is trustworthy; ``should_switch`` is the
    (mode-dependent) policy verdict — always False in ``probe`` mode.
    """

    ok: bool = False
    # Core USD-budget signals (the load-bearing ones for fallback).
    remaining_usd: Optional[float] = None
    limit_usd: Optional[float] = None
    # Request-count signals.
    remaining: Optional[int] = None
    limit: Optional[int] = None
    # Seconds until the daily window resets (X-RateLimit-Reset), and the
    # throttle backoff hint (Retry-After) when present.
    reset_seconds: Optional[int] = None
    retry_after: Optional[int] = None
    # Policy verdict — see module docstring. Mode-dependent.
    should_switch: bool = False
    # The mode that produced this status, for traceability.
    mode: str = "probe"
    # Populated only when ok is False.
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Header parsing (pure)
# ---------------------------------------------------------------------------


def _to_float(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        # Some servers send float-looking ints (e.g. "9999.0").
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_quota_headers(headers) -> QuotaStatus:
    """Parse a ``requests``-style (case-insensitive) headers mapping into a
    QuotaStatus snapshot. Pure — no I/O. ``should_switch``/``mode`` are left at
    their defaults here; the policy layer (:func:`evaluate`) fills those in.

    Accepts any mapping with ``.get``; tests pass a plain dict.
    """
    get = headers.get
    status = QuotaStatus(
        ok=True,
        remaining_usd=_to_float(get("X-RateLimit-Remaining-USD")),
        limit_usd=_to_float(get("X-RateLimit-Limit-USD")),
        remaining=_to_int(get("X-RateLimit-Remaining")),
        limit=_to_int(get("X-RateLimit-Limit")),
        reset_seconds=_to_int(get("X-RateLimit-Reset")),
        retry_after=_to_int(get("Retry-After")),
    )
    return status


# ---------------------------------------------------------------------------
# Probe (one tiny HTTP GET — the only I/O in this module)
# ---------------------------------------------------------------------------


def _build_auth_headers(config: Config) -> Dict[str, str]:
    """Reproduce pyalex's OpenAlexAuth header set so the probe lands in the same
    (authenticated / polite) pool the real searches use.

    Mirrors pyalex.OpenAlexAuth.__call__: Bearer api_key, From email, UA.
    """
    headers: Dict[str, str] = {"User-Agent": _PROBE_USER_AGENT}
    api_key = (getattr(config, "openalex_api_key", "") or "").strip()
    email = (getattr(config, "openalex_email", "") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if email:
        headers["From"] = email
    return headers


def get_quota_status(
    config: Config,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = _PROBE_TIMEOUT,
) -> QuotaStatus:
    """Issue one lightweight probe and return the parsed quota snapshot.

    Never raises: on any network/HTTP error returns ``QuotaStatus(ok=False,
    error=...)`` so a failed probe cannot crash a search. ``should_switch`` is
    left False here; apply policy via :func:`evaluate` (or call it directly,
    which probes then evaluates).
    """
    headers = _build_auth_headers(config)
    try:
        get = (session or requests).get
        res = get(_PROBE_URL, headers=headers, timeout=timeout)
    except Exception as exc:  # network down, DNS, timeout, etc.
        return QuotaStatus(ok=False, error=f"probe request failed: {exc}")

    status = parse_quota_headers(res.headers)
    # A non-200 still often carries rate-limit headers (e.g. 429 with
    # Retry-After), so we keep the parsed values but note the failure when the
    # USD signal is missing AND the call did not succeed.
    if res.status_code != 200:
        status.error = f"probe HTTP {res.status_code}"
        # If we got no usable quota signal at all, mark not-ok.
        if status.remaining_usd is None and status.retry_after is None:
            status.ok = False
    return status


# ---------------------------------------------------------------------------
# Policy layer (mode-aware) — shares the reading, not the strategy (R-12)
# ---------------------------------------------------------------------------


def apply_policy(status: QuotaStatus, *, mode: Mode, threshold_usd: float) -> QuotaStatus:
    """Apply the mode-specific switching policy to an already-read snapshot.

    Pure: mutates and returns the passed status (convenient for chaining) but
    performs no I/O.

    * mode="probe": never sets should_switch (single health snapshot — Feature B).
    * mode="run":   sets should_switch=True iff remaining_usd is known AND
                    <= threshold_usd (sticky run-level fallback — Feature C).
                    A failed probe (ok=False, remaining_usd=None) does NOT force a
                    switch — absence of evidence is not evidence of exhaustion;
                    callers treat ok=False as "stay on current source".
    """
    status.mode = mode
    if mode == "run" and status.ok and status.remaining_usd is not None:
        status.should_switch = status.remaining_usd <= threshold_usd
    else:
        status.should_switch = False
    return status


def evaluate(
    config: Config,
    *,
    mode: Mode = "probe",
    threshold_usd: Optional[float] = None,
    session: Optional[requests.Session] = None,
    timeout: int = _PROBE_TIMEOUT,
) -> QuotaStatus:
    """Convenience: probe OpenAlex then apply the mode's policy in one call.

    ``threshold_usd`` defaults to ``config.quota_fallback_threshold_usd`` when
    not supplied. For ``mode="probe"`` the threshold is irrelevant (no switch is
    ever emitted), so a missing config field is harmless.
    """
    if threshold_usd is None:
        threshold_usd = getattr(config, "quota_fallback_threshold_usd", 0.05)
    status = get_quota_status(config, session=session, timeout=timeout)
    return apply_policy(status, mode=mode, threshold_usd=threshold_usd)


# ---------------------------------------------------------------------------
# CLI — ad-hoc health check / debugging.
# ---------------------------------------------------------------------------


def _main_cli() -> None:
    import argparse
    import json
    import sys

    try:
        from .config import load_config
    except ImportError:  # standalone invocation
        from scripts.config import load_config  # type: ignore

    parser = argparse.ArgumentParser(
        prog="quota_guard",
        description="Probe OpenAlex remaining quota (reads X-RateLimit-* headers).",
    )
    parser.add_argument(
        "--mode",
        choices=["run", "probe"],
        default="probe",
        help="run = emit sticky should_switch verdict (Feature C); "
        "probe = snapshot only, never switches (Feature B). Default: probe.",
    )
    parser.add_argument(
        "--threshold-usd",
        type=float,
        default=None,
        help="Override the USD threshold (default: config.quota_fallback_threshold_usd).",
    )
    args = parser.parse_args()

    config = load_config()
    status = evaluate(config, mode=args.mode, threshold_usd=args.threshold_usd)
    json.dump(status.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Non-zero exit when the probe itself failed, so scripts can branch on it.
    sys.exit(0 if status.ok else 2)


if __name__ == "__main__":
    _main_cli()
