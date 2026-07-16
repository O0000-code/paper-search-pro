"""Tests for scripts/search_export/deeplink.py — A-tier deep-link constructor.

Fully network-free: construction is pure stdlib URL encoding; the optional
``live_verify`` is exercised with an injected fake ``requests.Session`` — the real
network (NCBI / CT.gov / ERIC) is NEVER touched.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_search_export_deeplink
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_search_export_deeplink.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.search_export import deeplink as dl  # noqa: E402


# ---------------------------------------------------------------------------
# Fake injectable session (no network)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status=200, text="", json_obj=None):
        self.status_code = status
        self.text = text
        self._json = json_obj

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeSession:
    """Records the URL it was asked to GET; returns a preset response or raises."""

    def __init__(self, resp=None, raise_exc=None):
        self.headers = {}
        self._resp = resp
        self._raise = raise_exc
        self.last_url = None

    def get(self, url, timeout=None):
        self.last_url = url
        if self._raise is not None:
            raise self._raise
        return self._resp


# ---------------------------------------------------------------------------
# 1. encode_query — brackets / quotes / parens / space / chinese / percent
# ---------------------------------------------------------------------------


def test_encode_query_pubmed_brackets_and_parens():
    enc = dl.encode_query('("Mindfulness"[Mesh] OR mindfulness[tiab])')
    # square brackets -> %5B %5D ; double quote -> %22 ; parens -> %28 %29 ; space -> +
    assert "%5B" in enc and "%5D" in enc, f"brackets not encoded: {enc}"
    assert "%22" in enc, f"quotes not encoded: {enc}"
    assert enc.startswith("%28") and enc.endswith("%29"), f"parens not encoded: {enc}"
    assert "+" in enc and " " not in enc, f"space not '+': {enc}"
    # exact match to the spec §1.2 encoding
    assert enc == "%28%22Mindfulness%22%5BMesh%5D+OR+mindfulness%5Btiab%5D%29"
    print(f"OK  encode_query PubMed term -> {enc}")


def test_encode_query_chinese_utf8():
    assert dl.encode_query("正念") == "%E6%AD%A3%E5%BF%B5"
    # CNKI-ish string: percent -> %25, single quote -> %27
    enc = dl.encode_query("SU %= '正念'")
    assert "%25" in enc, f"percent not encoded: {enc}"
    assert "%27" in enc, f"single-quote not encoded: {enc}"
    print(f"OK  encode_query Chinese + CNKI symbols -> {enc}")


# ---------------------------------------------------------------------------
# 2. PubMed (A) — web ?term= + E-utilities esearch template
# ---------------------------------------------------------------------------


def test_build_pubmed_a_tier():
    r = dl.build_deep_link("PubMed", '"Mindfulness"[Mesh] AND anxiety[tiab]')
    assert r["tier"] == "A" and r["url_kind"] == "prefill"
    assert r["url"].startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")
    assert "%5B" in r["url"], "MeSH brackets must be encoded in the web URL"
    assert "esearch.fcgi?db=pubmed&term=" in r["api_url"]
    # verified_date slot present (None until a live check) + pattern provenance set
    assert "verified_date" in r and r["verified_date"] is None
    assert r["pattern_verified_date"] == dl.PATTERN_VERIFIED_DATE
    print(f"OK  PubMed A-tier: url + esearch api_url built, verified_date slot present")


# ---------------------------------------------------------------------------
# 3. ERIC (A) — ?q=
# ---------------------------------------------------------------------------


def test_build_eric_a_tier():
    r = dl.build_deep_link("eric", "mindfulness AND anxiety")
    assert r["tier"] == "A" and r["url_kind"] == "prefill"
    assert r["url"].startswith("https://eric.ed.gov/?q=")
    assert r["api_url"] is None
    assert "verified_date" in r
    print(f"OK  ERIC A-tier: {r['url']}")


# ---------------------------------------------------------------------------
# 4. ClinicalTrials.gov (A) — API v2 machine endpoint + human expert-search
# ---------------------------------------------------------------------------


def test_build_ctgov_with_query_fields():
    r = dl.build_deep_link(
        "clinicaltrials.gov", None,
        query_fields={"cond": "anxiety", "intr": "mindfulness"},
    )
    assert r["tier"] == "A" and r["url_kind"] == "api"
    assert "query.cond=anxiety" in r["api_url"]
    assert "query.intr=mindfulness" in r["api_url"]
    assert r["api_url"].endswith("countTotal=true")
    # honest annotation: the API URL is the machine-verifiable one, not the SPA page
    assert r["machine_verifiable_endpoint"] == "api_url"
    assert r["ui_render"] == "client-SPA"
    assert r["url"].startswith("https://clinicaltrials.gov/expert-search?term=")
    print(f"OK  CT.gov A-tier: api_url machine-verifiable, human ui separate")


def test_build_ctgov_with_plain_strategy_string():
    r = dl.build_deep_link("ctgov", "mindfulness AND anxiety")
    assert "query.term=" in r["api_url"]
    assert "mindfulness" in r["api_url"] and "%20" not in r["api_url"]  # + not %20
    print("OK  CT.gov plain strategy string -> query.term=")


# ---------------------------------------------------------------------------
# 5. B / C tier — NEVER construct a filled URL (C-14)
# ---------------------------------------------------------------------------


def test_build_b_tier_browser_only_no_filled_url():
    r = dl.build_deep_link(
        "ieee", "test", url_template="https://ieeexplore.ieee.org/search/...{q}",
    )
    assert r["tier"] == "B" and r["url_kind"] == "browser"
    assert r["url"] is None, "B tier must NOT return a constructed filled URL"
    assert r["url_template"] == "https://ieeexplore.ieee.org/search/...{q}"
    print("OK  B tier (IEEE): url None, card template surfaced verbatim")


def test_build_c_tier_cnki_paste_only_compliance():
    """CNKI is a captcha wall — C-14: never construct a wall-bypassing URL."""
    r = dl.build_deep_link("CNKI", "(SU %= '正念') AND (SU %= '焦虑')")
    assert r["tier"] == "C" and r["url_kind"] == "paste_only"
    assert r["url"] is None, "CNKI captcha wall: url MUST be None"
    assert "验证码" in r["note"] or "登录" in r["note"]
    print("OK  C tier (CNKI): paste-only, url None, compliance note present")


def test_build_explicit_tier_overrides_hint():
    # Even an unknown platform, forced to B, still refuses to fill a URL.
    r = dl.build_deep_link("some_unknown_db", "x", tier="B")
    assert r["tier"] == "B" and r["url"] is None
    print("OK  explicit tier honored, unknown platform still url None")


def test_build_unknown_platform_defaults_to_c():
    r = dl.build_deep_link("mystery_platform", "x")
    assert r["tier"] == "C" and r["url"] is None
    print("OK  unknown platform defaults to safest C, url None")


# ---------------------------------------------------------------------------
# 6. live_verify — fresh observation via injected fake session
# ---------------------------------------------------------------------------


def test_live_verify_pubmed_parses_count():
    built = dl.build_deep_link("pubmed", "mindfulness[tiab]")
    fake = _FakeSession(resp=_FakeResp(status=200, text="<eSearchResult><Count>5213</Count></eSearchResult>"))
    out = dl.live_verify(built, session=fake)
    assert out["verified_http"] == 200
    assert out["count"] == 5213
    assert out["verified_date"] == date.today().isoformat()
    # the endpoint hit is the esearch API, not the human page
    assert "esearch.fcgi" in fake.last_url
    # input not mutated
    assert built["verified_http"] is None
    print(f"OK  live_verify PubMed -> http 200, Count 5213, date stamped")


def test_live_verify_ctgov_parses_total_count():
    built = dl.build_deep_link("ctgov", "mindfulness AND anxiety")
    fake = _FakeSession(resp=_FakeResp(status=200, json_obj={"totalCount": 2764}))
    out = dl.live_verify(built, session=fake)
    assert out["verified_http"] == 200 and out["total_count"] == 2764
    assert "pageSize=1" in fake.last_url  # minimal payload for the count check
    print("OK  live_verify CT.gov -> http 200, totalCount 2764")


def test_live_verify_network_failure_is_graceful():
    built = dl.build_deep_link("pubmed", "x[tiab]")
    fake = _FakeSession(raise_exc=ConnectionError("boom"))
    out = dl.live_verify(built, session=fake)
    assert out["verified_http"] is None
    assert "verify_error" in out and "ConnectionError" in out["verify_error"]
    print("OK  live_verify network failure -> graceful (verified_http None, error noted)")


def test_live_verify_bc_tier_unchanged():
    built = dl.build_deep_link("cnki", "x")
    out = dl.live_verify(built, session=_FakeSession(raise_exc=AssertionError("must not be called")))
    assert out == built  # B/C has nothing to verify — returned unchanged, no network
    print("OK  live_verify on C tier -> unchanged, no network call")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_encode_query_pubmed_brackets_and_parens,
    test_encode_query_chinese_utf8,
    test_build_pubmed_a_tier,
    test_build_eric_a_tier,
    test_build_ctgov_with_query_fields,
    test_build_ctgov_with_plain_strategy_string,
    test_build_b_tier_browser_only_no_filled_url,
    test_build_c_tier_cnki_paste_only_compliance,
    test_build_explicit_tier_overrides_hint,
    test_build_unknown_platform_defaults_to_c,
    test_live_verify_pubmed_parses_count,
    test_live_verify_ctgov_parses_total_count,
    test_live_verify_network_failure_is_graceful,
    test_live_verify_bc_tier_unchanged,
]


def main() -> int:
    passed, failed = 0, 0
    for fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{len(ALL_TESTS)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
