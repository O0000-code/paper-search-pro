"""Tests for scripts/quota_guard.py.

Header parsing + mode-aware policy are pure and tested deterministically with a
fake session (no network). The one optional live probe tolerates an unreachable
network so the suite stays green offline.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_quota_guard
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_quota_guard.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import quota_guard  # noqa: E402
from scripts.quota_guard import QuotaStatus  # noqa: E402
from scripts.types import Config  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes — a minimal stand-in for requests.Session.get() returning chosen headers.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, headers: dict, status_code: int = 200):
        # requests headers are case-insensitive; a plain dict is fine because
        # parse_quota_headers reads the exact capitalised keys OpenAlex sends.
        self.headers = headers
        self.status_code = status_code


class _FakeSession:
    """Records the call and returns a preset response (or raises)."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.last_url = None
        self.last_headers = None
        self.last_timeout = None

    def get(self, url, headers=None, timeout=None, **kw):
        self.last_url = url
        self.last_headers = headers
        self.last_timeout = timeout
        if self._exc is not None:
            raise self._exc
        return self._response


# The real OpenAlex header set observed 2026-06-25 (authenticated key).
_LIVE_HEADERS = {
    "X-RateLimit-Cost-USD": "0.0001",
    "X-RateLimit-Credits-Used": "1",
    "X-RateLimit-Limit": "10000",
    "X-RateLimit-Limit-USD": "1",
    "X-RateLimit-Remaining": "9999",
    "X-RateLimit-Remaining-USD": "0.9999",
    "X-RateLimit-Reset": "69351",
}


def _cfg(threshold=0.05, api_key="k", email="e@x.com") -> Config:
    c = Config()
    c.openalex_api_key = api_key
    c.openalex_email = email
    c.quota_fallback_threshold_usd = threshold
    return c


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


def test_parse_quota_headers_full():
    st = quota_guard.parse_quota_headers(_LIVE_HEADERS)
    assert st.ok is True
    assert st.remaining_usd == 0.9999
    assert st.limit_usd == 1.0
    assert st.remaining == 9999
    assert st.limit == 10000
    assert st.reset_seconds == 69351
    assert st.retry_after is None
    # No policy applied yet.
    assert st.should_switch is False
    print("OK  parse_quota_headers_full")


def test_parse_quota_headers_missing_fields():
    """A sparse / polite-pool header set must not crash; missing -> None."""
    st = quota_guard.parse_quota_headers({"X-RateLimit-Reset": "100"})
    assert st.ok is True
    assert st.remaining_usd is None
    assert st.limit_usd is None
    assert st.reset_seconds == 100
    print("OK  parse_quota_headers_missing_fields")


def test_parse_handles_floaty_ints_and_garbage():
    st = quota_guard.parse_quota_headers(
        {"X-RateLimit-Remaining": "9999.0", "X-RateLimit-Remaining-USD": "oops"}
    )
    assert st.remaining == 9999
    assert st.remaining_usd is None  # unparsable -> None, not a crash
    print("OK  parse_handles_floaty_ints_and_garbage")


# ---------------------------------------------------------------------------
# Mode-aware policy (R-12: probe never switches; run switches under threshold)
# ---------------------------------------------------------------------------


def test_apply_policy_probe_never_switches():
    """Even at zero budget, probe mode must NOT emit a switch directive."""
    st = QuotaStatus(ok=True, remaining_usd=0.0)
    quota_guard.apply_policy(st, mode="probe", threshold_usd=0.05)
    assert st.should_switch is False
    assert st.mode == "probe"
    print("OK  apply_policy_probe_never_switches")


def test_apply_policy_run_switches_below_threshold():
    st = QuotaStatus(ok=True, remaining_usd=0.04)
    quota_guard.apply_policy(st, mode="run", threshold_usd=0.05)
    assert st.should_switch is True
    assert st.mode == "run"
    print("OK  apply_policy_run_switches_below_threshold")


def test_apply_policy_run_no_switch_above_threshold():
    st = QuotaStatus(ok=True, remaining_usd=0.9999)
    quota_guard.apply_policy(st, mode="run", threshold_usd=0.05)
    assert st.should_switch is False
    print("OK  apply_policy_run_no_switch_above_threshold")


def test_apply_policy_run_boundary_is_inclusive():
    """remaining_usd == threshold should switch (<= comparison)."""
    st = QuotaStatus(ok=True, remaining_usd=0.05)
    quota_guard.apply_policy(st, mode="run", threshold_usd=0.05)
    assert st.should_switch is True
    print("OK  apply_policy_run_boundary_is_inclusive")


def test_apply_policy_run_failed_probe_does_not_switch():
    """A failed probe (ok=False, remaining unknown) must NOT force a switch —
    absence of evidence is not evidence of exhaustion."""
    st = QuotaStatus(ok=False, remaining_usd=None, error="boom")
    quota_guard.apply_policy(st, mode="run", threshold_usd=0.05)
    assert st.should_switch is False
    print("OK  apply_policy_run_failed_probe_does_not_switch")


# ---------------------------------------------------------------------------
# get_quota_status — auth header construction + non-200 + exception handling
# ---------------------------------------------------------------------------


def test_get_quota_status_builds_auth_headers():
    sess = _FakeSession(_FakeResponse(_LIVE_HEADERS, 200))
    st = quota_guard.get_quota_status(_cfg(api_key="SECRET", email="me@x.com"), session=sess)
    assert st.ok is True
    assert st.remaining_usd == 0.9999
    # Auth headers mirror pyalex.OpenAlexAuth.
    assert sess.last_headers.get("Authorization") == "Bearer SECRET"
    assert sess.last_headers.get("From") == "me@x.com"
    assert "User-Agent" in sess.last_headers
    print("OK  get_quota_status_builds_auth_headers")


def test_get_quota_status_no_key_omits_authorization():
    sess = _FakeSession(_FakeResponse(_LIVE_HEADERS, 200))
    st = quota_guard.get_quota_status(_cfg(api_key="", email=""), session=sess)
    assert st.ok is True
    assert "Authorization" not in sess.last_headers
    assert "From" not in sess.last_headers
    print("OK  get_quota_status_no_key_omits_authorization")


def test_get_quota_status_network_error_is_not_ok_no_raise():
    sess = _FakeSession(exc=RuntimeError("dns down"))
    st = quota_guard.get_quota_status(_cfg(), session=sess)
    assert st.ok is False
    assert st.error and "dns down" in st.error
    assert st.remaining_usd is None
    print("OK  get_quota_status_network_error_is_not_ok_no_raise")


def test_get_quota_status_429_keeps_retry_after():
    """A 429 still carries Retry-After; we keep it and report the HTTP error."""
    sess = _FakeSession(_FakeResponse({"Retry-After": "30"}, 429))
    st = quota_guard.get_quota_status(_cfg(), session=sess)
    assert st.retry_after == 30
    assert st.error and "429" in st.error
    print("OK  get_quota_status_429_keeps_retry_after")


# ---------------------------------------------------------------------------
# evaluate — one-shot probe + policy, threshold defaulting from config
# ---------------------------------------------------------------------------


def test_evaluate_run_uses_config_threshold():
    """evaluate should default threshold to config.quota_fallback_threshold_usd."""
    sess = _FakeSession(_FakeResponse({"X-RateLimit-Remaining-USD": "0.10"}, 200))
    # threshold 0.2 -> 0.10 <= 0.2 -> switch
    st = quota_guard.evaluate(_cfg(threshold=0.2), mode="run", session=sess)
    assert st.should_switch is True
    # threshold 0.05 -> 0.10 > 0.05 -> no switch
    sess2 = _FakeSession(_FakeResponse({"X-RateLimit-Remaining-USD": "0.10"}, 200))
    st2 = quota_guard.evaluate(_cfg(threshold=0.05), mode="run", session=sess2)
    assert st2.should_switch is False
    print("OK  evaluate_run_uses_config_threshold")


def test_evaluate_probe_snapshot_only():
    sess = _FakeSession(_FakeResponse({"X-RateLimit-Remaining-USD": "0.0"}, 200))
    st = quota_guard.evaluate(_cfg(), mode="probe", session=sess)
    assert st.ok is True
    assert st.remaining_usd == 0.0
    assert st.should_switch is False  # probe never switches, even at zero
    print("OK  evaluate_probe_snapshot_only")


def test_to_dict_is_json_safe():
    st = quota_guard.parse_quota_headers(_LIVE_HEADERS)
    d = st.to_dict()
    import json

    json.dumps(d)  # must not raise
    assert d["remaining_usd"] == 0.9999
    print("OK  to_dict_is_json_safe")


# ---------------------------------------------------------------------------
# Runner (mirrors the other test modules' style for `python3 -m`).
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [
        test_parse_quota_headers_full,
        test_parse_quota_headers_missing_fields,
        test_parse_handles_floaty_ints_and_garbage,
        test_apply_policy_probe_never_switches,
        test_apply_policy_run_switches_below_threshold,
        test_apply_policy_run_no_switch_above_threshold,
        test_apply_policy_run_boundary_is_inclusive,
        test_apply_policy_run_failed_probe_does_not_switch,
        test_get_quota_status_builds_auth_headers,
        test_get_quota_status_no_key_omits_authorization,
        test_get_quota_status_network_error_is_not_ok_no_raise,
        test_get_quota_status_429_keeps_retry_after,
        test_evaluate_run_uses_config_threshold,
        test_evaluate_probe_snapshot_only,
        test_to_dict_is_json_safe,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            import traceback

            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed.append(t.__name__)
    print()
    print(f"Ran {len(tests)} tests — {len(tests) - len(failed)} pass / {len(failed)} fail")
    if failed:
        print("Failures:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
