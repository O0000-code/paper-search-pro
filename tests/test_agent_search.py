"""Tests for scripts/agent_search.py.

Everything here is deterministic and network-free: the retrieval backends
(openalex_helper / ss_helper.search) and the quota probe are monkeypatched with
fakes, so the full pipeline (route -> retrieve -> dedup -> score -> saturation ->
verify -> envelope) is exercised without touching the network. The relevance
scoring, tokenisation, saturation, and verify helpers are pure and tested
directly.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_agent_search
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_agent_search.py -q
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import agent_search  # noqa: E402
from scripts.types import Author, Config, UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Patching helper — saves and RESTORES the original attributes so global module
# state is never permanently mutated. This matters because pytest collects test
# files alphabetically (test_agent_search before test_openalex_helper /
# test_quota_guard), so a leaked patch of openalex_helper.search_top_n_pages or
# quota_guard.evaluate would corrupt those later, live tests. Used as a context
# manager so cleanup happens even when an assertion fails.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched(*targets):
    """Each target is (obj, attr_name, new_value). Restores originals on exit."""
    saved = [(obj, attr, getattr(obj, attr)) for (obj, attr, _new) in targets]
    try:
        for obj, attr, new in targets:
            setattr(obj, attr, new)
        yield
    finally:
        for obj, attr, old in saved:
            setattr(obj, attr, old)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _paper(
    doi=None,
    title="X",
    abstract=None,
    year=2020,
    cites=10,
    openalex_id=None,
    ss_id=None,
    sources=None,
    authors=("A. One",),
):
    return UnifiedPaperEntity(
        doi=doi,
        openalex_id=openalex_id,
        ss_paper_id=ss_id,
        title=title,
        abstract=abstract,
        authors=[Author(name=n) for n in authors],
        year=year,
        citation_count=cites,
        sources=list(sources or ["openalex"]),
    )


def _cfg(primary="openalex", ss_key="", oa_key="k", oa_email="e@x.com") -> Config:
    c = Config()
    c.primary_source = primary
    c.semantic_scholar_api_key = ss_key
    c.openalex_api_key = oa_key
    c.openalex_email = oa_email
    return c


# A QuotaStatus-like stub for the probe.
class _FakeQuota:
    def __init__(self, ok=True, should_switch=False, remaining_usd=0.9):
        self.ok = ok
        self.should_switch = should_switch
        self.remaining_usd = remaining_usd

    def to_dict(self):
        return {
            "ok": self.ok,
            "remaining_usd": self.remaining_usd,
            "should_switch": self.should_switch,
            "mode": "probe",
        }


# ===========================================================================
# Tokenisation
# ===========================================================================


def test_tokenize_drops_stopwords_and_boolean_punct():
    terms = agent_search._tokenize_query("(machine learning) + (the role of healthcare)")
    # stopwords (the, of, role) dropped; boolean +/parens stripped.
    assert "machine" in terms and "learning" in terms and "healthcare" in terms
    assert "the" not in terms and "role" not in terms and "of" not in terms
    print("OK  tokenize_drops_stopwords_and_boolean_punct")


def test_tokenize_dedupes_repeated_terms():
    terms = agent_search._tokenize_query("memory memory memory")
    assert terms == ["memory"]
    print("OK  tokenize_dedupes_repeated_terms")


def test_coverage_token_membership_not_substring():
    # 'cat' must NOT match 'category' (token membership, not substring).
    assert agent_search._coverage(["cat"], "this is a category of things") == 0.0
    assert agent_search._coverage(["cat"], "the cat sat") == 1.0
    assert agent_search._coverage(["a", "b"], "a only") == 0.5
    print("OK  coverage_token_membership_not_substring")


# ===========================================================================
# Relevance scoring (B-2): components, weights, always-computed, not RCS
# ===========================================================================


def test_relevance_components_and_band():
    terms = agent_search._tokenize_query("prospect theory")
    p = _paper(
        title="Prospect Theory: An Analysis",
        abstract="prospect theory explains decision under risk",
        year=2026,
        cites=5000,
    )
    rel = agent_search.compute_relevance(p, terms, now_year=2026)
    assert rel["method"] == "heuristic_v1"
    assert rel["is_llm_rcs"] is False
    c = rel["components"]
    assert c["title_coverage"] == 1.0
    assert c["abstract_coverage"] == 1.0
    assert c["citation_signal"] == 1.0  # >2000 cites saturates
    assert c["recency_signal"] == 1.0  # this year
    # Full marks on all four -> score == sum of weights == 1.0, band high.
    assert rel["score"] == 1.0
    assert rel["label"] == "high"
    print("OK  relevance_components_and_band")


def test_relevance_weights_sum_and_title_dominates():
    """Title coverage must carry more weight than abstract coverage: a paper with
    the query in its title but not abstract beats one with it only in abstract."""
    terms = agent_search._tokenize_query("graph neural network")
    in_title = _paper(title="graph neural network survey", abstract="unrelated text", year=2010, cites=0)
    in_abstract = _paper(title="unrelated", abstract="graph neural network method", year=2010, cites=0)
    rt = agent_search.compute_relevance(in_title, terms, now_year=2026)["score"]
    ra = agent_search.compute_relevance(in_abstract, terms, now_year=2026)["score"]
    assert rt > ra, (rt, ra)
    # Weight invariant the module relies on.
    assert (
        agent_search._W_TITLE
        + agent_search._W_ABSTRACT
        + agent_search._W_CITATION
        + agent_search._W_RECENCY
    ) == 1.0
    print("OK  relevance_weights_sum_and_title_dominates")


def test_citation_signal_saturates_and_recency_clamps():
    assert agent_search._citation_signal(0) == 0.0
    assert agent_search._citation_signal(10**9) == 1.0  # clamped to 1
    assert agent_search._recency_signal(2026, now_year=2026) == 1.0
    assert agent_search._recency_signal(1980, now_year=2026) == 0.0  # >25y window
    assert agent_search._recency_signal(None) == 0.0
    print("OK  citation_signal_saturates_and_recency_clamps")


def test_relevance_zero_terms_off_topic():
    """A paper with none of the query terms scores only on citation+recency,
    never on coverage — so an off-topic mega-cited paper cannot top a query
    on coverage alone."""
    terms = agent_search._tokenize_query("quantum gravity")
    off = _paper(title="cooking recipes", abstract="how to bake", year=2026, cites=10**6)
    rel = agent_search.compute_relevance(off, terms, now_year=2026)
    assert rel["components"]["title_coverage"] == 0.0
    assert rel["components"]["abstract_coverage"] == 0.0
    # Max possible without coverage = W_CITATION + W_RECENCY = 0.25.
    assert rel["score"] <= agent_search._W_CITATION + agent_search._W_RECENCY + 1e-9
    print("OK  relevance_zero_terms_off_topic")


# ===========================================================================
# Saturation signal
# ===========================================================================


def test_saturation_flags_when_last_strategy_adds_little():
    # 20 unique, last strategy added only 1 new (5% < 15% threshold) -> saturated.
    sig = agent_search._saturation_signal([15, 4, 1], total_unique=20, scores=[0.9] * 20)
    assert sig["looks_saturated"] is True
    assert sig["advisory"] is True
    assert sig["per_strategy_new_papers"] == [15, 4, 1]
    print("OK  saturation_flags_when_last_strategy_adds_little")


def test_saturation_not_flagged_when_too_few_or_still_yielding():
    # too few unique
    assert agent_search._saturation_signal([3, 2], 5, [0.5] * 5)["looks_saturated"] is False
    # still yielding a lot in the last strategy
    sig = agent_search._saturation_signal([10, 10, 10], 30, [0.5] * 30)
    assert sig["looks_saturated"] is False
    assert sig["score_distribution"]["medium"] == 30
    print("OK  saturation_not_flagged_when_too_few_or_still_yielding")


# ===========================================================================
# Verify markers
# ===========================================================================


def test_verify_paper_flags():
    full = _paper(doi="10.1/x", title="T", abstract="abs", year=2020, sources=["openalex", "semantic_scholar"])
    v = agent_search._verify_paper(full)
    assert v["exists"] is True and v["has_doi"] is True and v["has_abstract"] is True
    assert v["multi_source"] is True and v["title_year_present"] is True
    assert v["flags"] == []

    bare = _paper(doi=None, title="", abstract=None, year=None, openalex_id="W1", sources=["openalex"])
    v2 = agent_search._verify_paper(bare)
    assert v2["exists"] is True  # has an OpenAlex id
    assert set(["no_doi", "no_abstract", "no_title", "no_year", "single_source"]).issubset(set(v2["flags"]))
    print("OK  verify_paper_flags")


# ===========================================================================
# Dedup + per-strategy yield
# ===========================================================================


def test_dedup_with_yield_counts_new_per_strategy():
    s1 = [_paper(doi="10.1/a"), _paper(doi="10.1/b")]
    s2 = [_paper(doi="10.1/a"), _paper(doi="10.1/c")]  # a is dup, c is new
    unique, per_new, raw = agent_search._dedup_with_yield([s1, s2])
    assert raw == 4
    assert per_new == [2, 1]  # s1 added 2 new, s2 added 1 new (c)
    assert len(unique) == 3
    print("OK  dedup_with_yield_counts_new_per_strategy")


# ===========================================================================
# Full pipeline via run_agent_search (monkeypatched backends)
# ===========================================================================


def _oa_targets(results_by_sort):
    """Build the (obj, attr, new) target tuples that stub the OpenAlex retrieval
    backend + quota probe, for use with the restoring `_patched` context manager.

    agent_search holds the SAME module objects (from . import openalex_helper,
    quota_guard), so patching the module objects is what agent_search will call.
    """
    def fake_search_top_n_pages(query, total_papers=100, sort="cited_by_count:desc", year_min=None, year_max=None):
        return list(results_by_sort.get(sort, []))

    return [
        (agent_search.openalex_helper, "search_top_n_pages", fake_search_top_n_pages),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
    ]


def test_run_agent_search_full_envelope_openalex():
    kt = _paper(doi="10.2307/1914185", title="prospect theory analysis",
                abstract="prospect theory under risk", year=2024, cites=5000)
    other = _paper(doi="10.1/y", title="prospect markets", abstract="markets", year=2024, cites=10)
    targets = _oa_targets({
        "cited_by_count:desc": [kt, other],
        "publication_date:desc": [kt],
        "relevance_score:desc": [kt, other],
    })
    with _patched(*targets):
        env = agent_search.run_agent_search("prospect theory", _cfg(), per_strategy=10, now_year=2026)
    assert env["ok"] is True
    assert env["schema_version"] == "1.0"
    assert isinstance(env["data"], list) and len(env["data"]) == 2
    # Sorted by relevance: KT (full coverage + cites) ranks first.
    assert env["data"][0]["doi"] == "10.2307/1914185"
    # Every paper carries the heuristic relevance + reserved journal_metric slot.
    for p in env["data"]:
        assert p["relevance"]["method"] == "heuristic_v1"
        assert p["relevance"]["is_llm_rcs"] is False
        assert "journal_metric" in p and p["journal_metric"] is None
    m = env["meta"]
    assert m["source_used"] == "openalex"
    assert m["counts"]["retrieved_raw"] == 5
    assert m["counts"]["after_dedup"] == 2
    assert m["counts"]["returned"] == 2
    assert m["relevance"]["is_llm_rcs"] is False
    assert "saturation" in m and "ratelimit" in m
    assert m["ratelimit"]["switched_source"] is False
    print("OK  run_agent_search_full_envelope_openalex")


def test_run_agent_search_min_relevance_filters_but_scores_all():
    hi = _paper(doi="10.1/hi", title="alpha beta gamma", abstract="alpha beta gamma", year=2026, cites=3000)
    lo = _paper(doi="10.1/lo", title="unrelated", abstract="nothing here", year=1990, cites=0)
    targets = _oa_targets({
        "cited_by_count:desc": [hi, lo],
        "publication_date:desc": [],
        "relevance_score:desc": [],
    })
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha beta gamma", _cfg(), per_strategy=10, min_relevance=0.5, now_year=2026)
    assert env["ok"] is True
    # Only the high-scoring paper is returned, but BOTH were scored (after_dedup=2).
    assert env["meta"]["counts"]["after_dedup"] == 2
    assert env["meta"]["counts"]["after_relevance_filter"] == 1
    assert len(env["data"]) == 1 and env["data"][0]["doi"] == "10.1/hi"
    print("OK  run_agent_search_min_relevance_filters_but_scores_all")


def test_run_agent_search_verify_attaches_blocks_and_summary():
    p = _paper(doi="10.1/x", title="alpha", abstract="alpha", year=2024, cites=5,
               sources=["openalex", "semantic_scholar"])
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha", _cfg(), per_strategy=5, verify=True, now_year=2026)
    assert "verify" in env["data"][0]
    assert env["data"][0]["verify"]["multi_source"] is True
    assert env["meta"]["verify_summary"]["total"] == 1
    assert env["meta"]["verify_summary"]["multi_source"] == 1
    print("OK  run_agent_search_verify_attaches_blocks_and_summary")


def test_run_agent_search_empty_query_is_e_config():
    env = agent_search.run_agent_search("   ", _cfg())
    assert env["ok"] is False
    assert env["error"]["code"] == "E_CONFIG"
    assert env["error"]["retryable"] is False
    print("OK  run_agent_search_empty_query_is_e_config")


def test_run_agent_search_no_results_is_e_no_results():
    targets = _oa_targets({"cited_by_count:desc": [], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("nothing matches", _cfg(), per_strategy=5)
    assert env["ok"] is False
    assert env["error"]["code"] == "E_NO_RESULTS"
    assert env["meta"]["counts"]["after_dedup"] == 0
    print("OK  run_agent_search_no_results_is_e_no_results")


def test_run_agent_search_ss_primary_without_key_is_e_config():
    """SS as primary with no key must fail fast with E_CONFIG (R-06), not silently
    return [] from a 429."""
    targets = [
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "_api_key_from_config", lambda: None),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search("anything", _cfg(primary="semantic_scholar", ss_key=""))
    assert env["ok"] is False
    assert env["error"]["code"] == "E_CONFIG"
    assert "semantic_scholar" in env["error"]["message"]
    print("OK  run_agent_search_ss_primary_without_key_is_e_config")


def test_run_agent_search_auto_mode_sticky_switch_to_ss():
    """auto + quota run-mode says should_switch -> source flips to SS; then with a
    key, SS search (stubbed) returns papers and the envelope marks switched."""

    # run-mode evaluate => should_switch True (low budget); probe-mode => snapshot.
    def fake_eval(config, mode="probe", **kw):
        if mode == "run":
            return _FakeQuota(ok=True, should_switch=True, remaining_usd=0.0)
        return _FakeQuota(ok=True, should_switch=False)

    ss_paper = _paper(doi="10.1/ss", title="alpha topic", abstract="alpha topic", year=2024,
                      cites=42, sources=["semantic_scholar"])
    targets = [
        (agent_search.quota_guard, "evaluate", fake_eval),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "_api_key_from_config", lambda: "KEY"),
        (agent_search.ss_helper, "search", lambda q, **kw: [ss_paper]),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg(primary="auto", ss_key="KEY"),
                                            per_strategy=5, now_year=2026)
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "semantic_scholar"
    assert env["meta"]["ratelimit"]["switched_source"] is True
    assert env["data"][0]["doi"] == "10.1/ss"
    print("OK  run_agent_search_auto_mode_sticky_switch_to_ss")


def test_envelope_is_json_safe():
    import json
    p = _paper(doi="10.1/x", title="alpha", abstract="alpha", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha", _cfg(), per_strategy=5, verify=True, now_year=2026)
    json.dumps(env)  # must not raise
    print("OK  envelope_is_json_safe")


# ===========================================================================
# --no-issn-backfill (opt-in opt-out of SS-primary ISSN recovery, P2)
# ===========================================================================


def _ss_primary_targets(ss_papers, *, get_work=None):
    """Stub the SS-primary path: route to SS, return ss_papers, with OA get_work /
    impact / quota all faked so nothing touches the network."""
    def fake_eval(config, mode="probe", **kw):
        return _FakeQuota(ok=True, should_switch=False)

    targets = [
        (agent_search.quota_guard, "evaluate", fake_eval),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "_api_key_from_config", lambda: "KEY"),
        (agent_search.ss_helper, "search", lambda q, **kw: list(ss_papers)),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.openalex_helper, "get_source_impact", lambda issn: None),
    ]
    if get_work is not None:
        targets.append((agent_search.openalex_helper, "get_work", get_work))
    return targets


def test_no_issn_backfill_skips_oa_lookups_on_ss_primary():
    """With issn_backfill=False, the SS-primary path must NOT attempt OA DOI
    lookups for ISSN recovery; the audit counts stay 0 and the gate is reported."""
    # SS paper lacks ISSN but has a DOI — exactly the backfill candidate.
    ss_p = _paper(doi="10.1/ss", title="alpha topic", abstract="alpha topic",
                  year=2024, cites=5, sources=["semantic_scholar"])
    ss_p.issn = None

    calls = {"get_work": 0}

    def spy_get_work(doi):
        calls["get_work"] += 1
        raise AssertionError("get_work must not be called when issn_backfill=False")

    targets = _ss_primary_targets([ss_p], get_work=spy_get_work)
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg(primary="semantic_scholar", ss_key="KEY"),
            per_strategy=5, issn_backfill=False, now_year=2026,
        )
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "semantic_scholar"
    jm = env["meta"]["journal_metric"]
    assert jm["issn_backfill_enabled"] is False
    assert jm["issn_backfill_attempted"] == 0
    assert jm["issn_backfilled"] == 0
    assert calls["get_work"] == 0
    print("OK  no_issn_backfill_skips_oa_lookups_on_ss_primary")


def test_issn_backfill_default_on_attempts_oa_lookup():
    """Default (issn_backfill=True): an SS paper with a DOI but no ISSN triggers a
    free OA get_work lookup that recovers the ISSN; audit counts reflect it."""
    ss_p = _paper(doi="10.1/ss", title="alpha topic", abstract="alpha topic",
                  year=2024, cites=5, sources=["semantic_scholar"])
    ss_p.issn = None

    recovered = _paper(doi="10.1/ss", title="alpha topic", year=2024, cites=5)
    recovered.issn = "00223514"

    calls = {"get_work": 0}

    def fake_get_work(doi):
        calls["get_work"] += 1
        return recovered

    targets = _ss_primary_targets([ss_p], get_work=fake_get_work)
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg(primary="semantic_scholar", ss_key="KEY"),
            per_strategy=5, issn_backfill=True, now_year=2026,
        )
    assert env["ok"] is True
    jm = env["meta"]["journal_metric"]
    assert jm["issn_backfill_enabled"] is True
    assert jm["issn_backfill_attempted"] == 1
    assert jm["issn_backfilled"] == 1
    assert calls["get_work"] == 1
    print("OK  issn_backfill_default_on_attempts_oa_lookup")


# ===========================================================================
# verify_references (--verify-refs): direct anti-hallucination existence check
# ===========================================================================


def _verify_refs_targets(*, get_work=None, fetch_doi=None, ss_get_paper=None,
                         search_works=None):
    """Stub the three resolvers used by verify_references. Anything left None is
    stubbed to a no-op / not-found so nothing touches the network."""
    class _FakeSSClient:
        def get_paper(self, sid, fields=None):
            return ss_get_paper(sid) if ss_get_paper else None

    targets = [
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.crossref_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.openalex_helper, "get_work",
         get_work if get_work else (lambda doi: (_ for _ in ()).throw(Exception("not found")))),
        (agent_search.crossref_helper, "_fetch_doi",
         fetch_doi if fetch_doi else (lambda doi: None)),
        (agent_search.ss_helper, "_get_client", lambda: _FakeSSClient()),
        (agent_search.openalex_helper, "search_works",
         search_works if search_works else (lambda title, limit=5: [])),
    ]
    return targets


def test_verify_refs_doi_resolves_in_openalex():
    canon = _paper(doi="10.2307/1914185", title="Prospect Theory", year=1979, cites=50000)
    canon.venue = "Econometrica"

    def fake_get_work(doi):
        assert "1914185" in doi
        return canon

    with _patched(*_verify_refs_targets(get_work=fake_get_work)):
        env = agent_search.verify_references(
            [{"doi": "10.2307/1914185", "title": "Prospect Theory"}], _cfg()
        )
    assert env["ok"] is True
    r = env["data"][0]
    assert r["exists"] is True
    assert r["matched_source"] == "openalex"
    assert r["canonical"]["doi"] == "10.2307/1914185"
    assert r["canonical"]["venue"] == "Econometrica"
    assert env["meta"]["summary"]["verified"] == 1
    assert env["meta"]["summary"]["by_source"]["openalex"] == 1
    print("OK  verify_refs_doi_resolves_in_openalex")


def test_verify_refs_doi_falls_back_to_crossref():
    """OpenAlex misses the DOI but CrossRef (the DOI registry) resolves it."""
    cr_msg = {
        "DOI": "10.1/realpaper",
        "title": ["A Real Paper"],
        "issued": {"date-parts": [[2021, 5]]},
        "container-title": ["Journal of Real Things"],
    }
    with _patched(*_verify_refs_targets(fetch_doi=lambda doi: cr_msg)):
        env = agent_search.verify_references([{"doi": "10.1/realpaper"}], _cfg())
    r = env["data"][0]
    assert r["exists"] is True
    assert r["matched_source"] == "crossref"
    assert r["canonical"]["title"] == "A Real Paper"
    assert r["canonical"]["year"] == 2021
    assert r["canonical"]["venue"] == "Journal of Real Things"
    print("OK  verify_refs_doi_falls_back_to_crossref")


def test_verify_refs_hallucinated_doi_not_found():
    """A DOI that resolves nowhere -> exists False (the anti-hallucination case)."""
    with _patched(*_verify_refs_targets()):  # all resolvers report not-found
        env = agent_search.verify_references([{"doi": "10.9999/fabricated"}], _cfg())
    r = env["data"][0]
    assert r["exists"] is False
    assert r["matched_source"] is None
    assert r["canonical"] is None
    assert "fabricated" in r["note"] or "did not resolve" in r["note"]
    assert env["meta"]["summary"]["not_found"] == 1
    print("OK  verify_refs_hallucinated_doi_not_found")


def test_verify_refs_title_only_match_threshold():
    """Title-only: a close OpenAlex title match verifies; a weak one does NOT."""
    good = _paper(title="Attention Is All You Need", year=2017, cites=80000)
    good.doi = "10.48550/arxiv.1706.03762"

    def fake_search_close(title, limit=5):
        return [good]

    with _patched(*_verify_refs_targets(search_works=fake_search_close)):
        env = agent_search.verify_references(
            [{"title": "Attention Is All You Need"}], _cfg()
        )
    r = env["data"][0]
    assert r["exists"] is True
    assert r["matched_source"] == "openalex"
    assert r["canonical"]["doi"] == "10.48550/arxiv.1706.03762"

    # A weak match must be rejected (anti false-positive).
    unrelated = _paper(title="Completely Different Topic About Cooking", year=2010)

    def fake_search_far(title, limit=5):
        return [unrelated]

    with _patched(*_verify_refs_targets(search_works=fake_search_far)):
        env2 = agent_search.verify_references(
            [{"title": "Attention Is All You Need"}], _cfg()
        )
    r2 = env2["data"][0]
    assert r2["exists"] is False
    assert "NOT verified" in r2["note"] or "No confident" in r2["note"]
    print("OK  verify_refs_title_only_match_threshold")


def test_verify_refs_wrong_doi_but_title_resolves_flags_doi():
    """DOI fails to resolve but the title does -> verified via title, with a note
    that the supplied DOI is probably wrong + the canonical DOI to use instead."""
    canon = _paper(title="Prospect Theory An Analysis of Decision Under Risk",
                   year=1979, cites=50000)
    canon.doi = "10.2307/1914185"

    def fake_search(title, limit=5):
        return [canon]

    # get_work / crossref / ss all miss the wrong DOI; search_works finds the title.
    with _patched(*_verify_refs_targets(search_works=fake_search)):
        env = agent_search.verify_references(
            [{"doi": "10.0000/wrong",
              "title": "Prospect Theory An Analysis of Decision Under Risk"}],
            _cfg(),
        )
    r = env["data"][0]
    assert r["exists"] is True
    assert r["matched_source"] == "openalex"
    assert r["canonical"]["doi"] == "10.2307/1914185"
    assert "DOI" in r["note"] and "wrong" in r["note"].lower()
    print("OK  verify_refs_wrong_doi_but_title_resolves_flags_doi")


def test_verify_refs_empty_and_bad_input():
    env_empty = agent_search.verify_references([], _cfg())
    assert env_empty["ok"] is False
    assert env_empty["error"]["code"] == "E_NO_RESULTS"

    env_bad = agent_search.verify_references({"not": "a list"}, _cfg())  # type: ignore
    assert env_bad["ok"] is False
    assert env_bad["error"]["code"] == "E_CONFIG"

    # A ref with neither doi nor title -> not verified, with a clear note.
    with _patched(*_verify_refs_targets()):
        env_none = agent_search.verify_references([{"author": "X"}], _cfg())
    assert env_none["ok"] is True
    assert env_none["data"][0]["exists"] is False
    assert "nothing to verify" in env_none["data"][0]["note"]
    print("OK  verify_refs_empty_and_bad_input")


def test_verify_refs_source_init_failure_degrades():
    """If OpenAlex init fails, DOI refs can still verify via CrossRef; the summary
    reports OpenAlex unavailable rather than crashing."""
    def boom_init(cfg):
        raise RuntimeError("no key")

    cr_msg = {"DOI": "10.1/x", "title": ["T"], "issued": {"date-parts": [[2020]]}}
    targets = [
        (agent_search.openalex_helper, "init_pyalex", boom_init),
        (agent_search.crossref_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.crossref_helper, "_fetch_doi", lambda doi: cr_msg),
    ]
    with _patched(*targets):
        env = agent_search.verify_references([{"doi": "10.1/x"}], _cfg())
    assert env["ok"] is True
    assert env["meta"]["sources_available"]["openalex"] is False
    assert env["data"][0]["exists"] is True
    assert env["data"][0]["matched_source"] == "crossref"
    print("OK  verify_refs_source_init_failure_degrades")


def test_load_refs_file_shapes(tmp_path=None):
    """_load_refs_file accepts a bare list, {references:[...]}, and bare strings."""
    import json
    import tempfile
    import os

    def _write(obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    p1 = _write([{"doi": "10.1/a"}, "A bare title"])
    refs1 = agent_search._load_refs_file(p1)
    assert refs1 == [{"doi": "10.1/a"}, {"title": "A bare title"}]
    os.unlink(p1)

    p2 = _write({"references": [{"title": "T"}]})
    refs2 = agent_search._load_refs_file(p2)
    assert refs2 == [{"title": "T"}]
    os.unlink(p2)

    p3 = _write({"refs": [{"doi": "10.2/b"}]})
    refs3 = agent_search._load_refs_file(p3)
    assert refs3 == [{"doi": "10.2/b"}]
    os.unlink(p3)
    print("OK  load_refs_file_shapes")


# ---------------------------------------------------------------------------
# Runner (mirrors the other test modules' `python3 -m` style).
# ---------------------------------------------------------------------------


def main() -> int:
    tests = [
        test_tokenize_drops_stopwords_and_boolean_punct,
        test_tokenize_dedupes_repeated_terms,
        test_coverage_token_membership_not_substring,
        test_relevance_components_and_band,
        test_relevance_weights_sum_and_title_dominates,
        test_citation_signal_saturates_and_recency_clamps,
        test_relevance_zero_terms_off_topic,
        test_saturation_flags_when_last_strategy_adds_little,
        test_saturation_not_flagged_when_too_few_or_still_yielding,
        test_verify_paper_flags,
        test_dedup_with_yield_counts_new_per_strategy,
        test_run_agent_search_full_envelope_openalex,
        test_run_agent_search_min_relevance_filters_but_scores_all,
        test_run_agent_search_verify_attaches_blocks_and_summary,
        test_run_agent_search_empty_query_is_e_config,
        test_run_agent_search_no_results_is_e_no_results,
        test_run_agent_search_ss_primary_without_key_is_e_config,
        test_run_agent_search_auto_mode_sticky_switch_to_ss,
        test_envelope_is_json_safe,
        test_no_issn_backfill_skips_oa_lookups_on_ss_primary,
        test_issn_backfill_default_on_attempts_oa_lookup,
        test_verify_refs_doi_resolves_in_openalex,
        test_verify_refs_doi_falls_back_to_crossref,
        test_verify_refs_hallucinated_doi_not_found,
        test_verify_refs_title_only_match_threshold,
        test_verify_refs_wrong_doi_but_title_resolves_flags_doi,
        test_verify_refs_empty_and_bad_input,
        test_verify_refs_source_init_failure_degrades,
        test_load_refs_file_shapes,
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
