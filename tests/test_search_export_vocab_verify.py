"""Tests for scripts/search_export/vocab_verify.py — controlled-vocab verification.

Fully network-free: MeSH is exercised via an injected ``esearch_fn`` (never touches
biopython/NCBI); ERIC / CMeSH are exercised via an injected fake ``requests.Session``.
The real network is NEVER touched.

Covers the three MeSH paths (hit / miss / network-failure), the 68->D descriptor_ui
derivation, ERIC subject-field existence (hit/miss/error/failure), the hard
"pending_manual, never fake-verify" rule for Emtree/CINAHL/APA, and the CMeSH
soft cross-check that must NOT upgrade the status.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_search_export_vocab_verify
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_search_export_vocab_verify.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.search_export import vocab_verify as vv  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes (no network)
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
# 1. MeSH — hit / miss / network failure
# ---------------------------------------------------------------------------


def test_mesh_hit_returns_verified_with_descriptor_ui():
    r = vv.verify_mesh("Mindfulness", esearch_fn=lambda t: (1, ["68064866"]))
    assert r["status"] == "verified"
    assert r["descriptor_ui"] == "D064866"       # 68->D derivation
    assert r["vocab"] == "MeSH" and r["explode"] is True
    assert r["verification_method"] == "free_api"
    # required §2.1 shape keys present
    for k in ("term", "vocab", "status", "descriptor_ui", "explode"):
        assert k in r
    print(f"OK  MeSH hit: Mindfulness -> verified, descriptor_ui={r['descriptor_ui']}")


def test_mesh_miss_recommends_downgrade():
    r = vv.verify_mesh("Hallucinated Nonexistent Descriptor", esearch_fn=lambda t: (0, []))
    assert r["status"] == "not_found"
    assert r["descriptor_ui"] is None
    assert "降级" in r["review_point"] and "tiab" in r["review_point"]
    print("OK  MeSH miss (Count=0) -> not_found + downgrade recommendation")


def test_mesh_network_failure_is_unverified_not_crash():
    def boom(_t):
        raise TimeoutError("network down")

    r = vv.verify_mesh("Anxiety", esearch_fn=boom)
    assert r["status"] == "unverified"       # honest gap, NOT a hallucination verdict
    assert r["descriptor_ui"] is None
    assert r["review_point"] is not None
    print("OK  MeSH network failure -> unverified (graceful, no crash)")


def test_descriptor_ui_derivation():
    assert vv._derive_descriptor_ui("68064866") == "D064866"
    assert vv._derive_descriptor_ui("68001007") == "D001007"
    assert vv._derive_descriptor_ui("68013334") == "D013334"
    assert vv._derive_descriptor_ui("abc") is None       # non-numeric -> None
    assert vv._derive_descriptor_ui(None) is None
    print("OK  descriptor_ui 68->D derivation (D064866/D001007/D013334) + None guards")


# ---------------------------------------------------------------------------
# 2. ERIC — subject-field existence via fake session
# ---------------------------------------------------------------------------


def test_eric_hit_verified():
    fake = _FakeSession(resp=_FakeResp(200, json_obj={"response": {"numFound": 37595}}))
    r = vv.verify_eric("Early Childhood Education", session=fake)
    assert r["status"] == "verified" and r["vocab"] == "ERIC"
    assert 'subject%3A' in fake.last_url or "subject" in fake.last_url
    print("OK  ERIC hit: numFound 37595 -> verified")


def test_eric_miss_downgrade():
    fake = _FakeSession(resp=_FakeResp(200, json_obj={"response": {"numFound": 0}}))
    r = vv.verify_eric("Zzz Fake Descriptor", session=fake)
    assert r["status"] == "not_found"
    assert r["review_point"] is not None
    print("OK  ERIC miss: numFound 0 -> not_found + downgrade")


def test_eric_error_payload_is_unverified():
    # Solr error json (undefined field etc.) -> no response.numFound -> unverified
    fake = _FakeSession(resp=_FakeResp(200, json_obj={"error": {"msg": "undefined field"}}))
    r = vv.verify_eric("X", session=fake)
    assert r["status"] == "unverified"
    print("OK  ERIC error payload -> unverified (honest gap)")


def test_eric_network_failure_is_unverified():
    fake = _FakeSession(raise_exc=ConnectionError("boom"))
    r = vv.verify_eric("X", session=fake)
    assert r["status"] == "unverified"
    print("OK  ERIC network failure -> unverified (graceful)")


# ---------------------------------------------------------------------------
# 3. Emtree / CINAHL / APA — pending_manual, NEVER fake-verify
# ---------------------------------------------------------------------------


def test_llm_only_vocabs_are_pending_manual():
    for vocab, display in [("emtree", "Emtree"), ("cinahl", "CINAHL"),
                           ("apa", "APA"), ("psycinfo", "APA")]:
        r = vv.verify_term("Some Term", vocab)
        assert r["status"] == "pending_manual", f"{vocab} must be pending_manual"
        assert r["status"] != "verified", f"{vocab} must NEVER be fake-verified"
        assert r["verification_method"] == "llm_suggest_only"
        assert r["vocab"] == display
        assert r["review_point"] is not None
    print("OK  Emtree/CINAHL/APA/PsycINFO -> pending_manual, never fake-verified")


# ---------------------------------------------------------------------------
# 4. CMeSH — soft cross-check must NOT upgrade status
# ---------------------------------------------------------------------------


def test_cmesh_soft_hit_stays_pending_manual():
    fake = _FakeSession(resp=_FakeResp(200, text='"糖尿病, 实验性"\n"糖尿病, 1型"\n'))
    r = vv.verify_cmesh("糖尿病", session=fake)
    assert r["status"] == "pending_manual", "soft hit must NOT upgrade status"
    assert r["soft_crosscheck"] == "hit"
    assert "置信提升" in (r["note"] or "")
    print("OK  CMeSH soft-check HIT -> soft_crosscheck=hit, status stays pending_manual")


def test_cmesh_soft_empty_flags_suspected_hallucination():
    fake = _FakeSession(resp=_FakeResp(200, text=""))
    r = vv.verify_cmesh("阿斯顿乱码幻觉词", session=fake)
    assert r["status"] == "pending_manual"
    assert r["soft_crosscheck"] == "empty"
    assert "幻觉" in r["review_point"]
    print("OK  CMeSH soft-check EMPTY -> flags suspected hallucination, still pending_manual")


def test_cmesh_soft_check_disabled_no_network():
    fake = _FakeSession(raise_exc=AssertionError("must not be called when soft off"))
    r = vv.verify_cmesh("正念", session=fake, soft_crosscheck=False)
    assert r["status"] == "pending_manual" and r["soft_crosscheck"] == "off"
    print("OK  CMeSH soft-check disabled -> no network, pending_manual")


def test_cmesh_soft_network_failure_graceful():
    fake = _FakeSession(raise_exc=ConnectionError("boom"))
    r = vv.verify_cmesh("正念", session=fake)
    assert r["status"] == "pending_manual" and r["soft_crosscheck"] == "unavailable"
    print("OK  CMeSH soft-check network failure -> unavailable, still pending_manual")


# ---------------------------------------------------------------------------
# 5. Dispatcher + batch + rollup
# ---------------------------------------------------------------------------


def test_verify_term_routes_by_vocab():
    mesh = vv.verify_term("Mindfulness", "MeSH", esearch_fn=lambda t: (1, ["68064866"]))
    assert mesh["status"] == "verified" and mesh["descriptor_ui"] == "D064866"
    emtree = vv.verify_term("student", "Emtree")
    assert emtree["status"] == "pending_manual"
    print("OK  verify_term dispatch: MeSH->verified, Emtree->pending_manual")


def test_verify_terms_batch_preserves_order():
    items = [
        {"term": "Mindfulness", "vocab": "MeSH"},
        {"term": "student", "vocab": "Emtree"},
    ]
    out = vv.verify_terms(items, esearch_fn=lambda t: (1, ["68064866"]))
    assert [r["term"] for r in out] == ["Mindfulness", "student"]
    assert out[0]["status"] == "verified" and out[1]["status"] == "pending_manual"
    print("OK  verify_terms batch preserves order + routes each")


def test_summarize_vocab_status_rollup():
    all_ok = [{"status": "verified"}, {"status": "verified"}]
    assert vv.summarize_vocab_status(all_ok) == "机械已验"
    # not_found must NEVER roll up to a bare 机械已验 (Gate2 FG1 #2 / 26b P1-1):
    # the term was culled from the CV clause and downgraded to free text.
    with_not_found = [{"status": "verified"}, {"status": "not_found"}]
    assert vv.summarize_vocab_status(with_not_found) == "机械已验·含降级"
    with_pending = [{"status": "verified"}, {"status": "pending_manual"}]
    assert vv.summarize_vocab_status(with_pending) == "语法已验·词表待核"
    assert vv.summarize_vocab_status([]) is None
    print("OK  summarize_vocab_status: 机械已验 / 含降级 / 词表待核 / None")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_mesh_hit_returns_verified_with_descriptor_ui,
    test_mesh_miss_recommends_downgrade,
    test_mesh_network_failure_is_unverified_not_crash,
    test_descriptor_ui_derivation,
    test_eric_hit_verified,
    test_eric_miss_downgrade,
    test_eric_error_payload_is_unverified,
    test_eric_network_failure_is_unverified,
    test_llm_only_vocabs_are_pending_manual,
    test_cmesh_soft_hit_stays_pending_manual,
    test_cmesh_soft_empty_flags_suspected_hallucination,
    test_cmesh_soft_check_disabled_no_network,
    test_cmesh_soft_network_failure_graceful,
    test_verify_term_routes_by_vocab,
    test_verify_terms_batch_preserves_order,
    test_summarize_vocab_status_rollup,
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
