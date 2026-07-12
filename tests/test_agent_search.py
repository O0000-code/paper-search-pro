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
        # Pin journal_rank.load to None so the multi-platform rank layer is inert
        # here regardless of machine cache state (these tests pre-date Wave A-2;
        # dedicated rank tests live below + in test_rank_intent / test_rank_filter).
        (agent_search.journal_rank, "load", lambda **kw: None),
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
    # Every paper carries the heuristic relevance + the SINGLE journal_rank slot
    # (None here: no ISSN, no cached rank data). The legacy per-paper journal_metric
    # key is retired (v2.2 single-layer collapse).
    for p in env["data"]:
        assert p["relevance"]["method"] == "heuristic_v1"
        assert p["relevance"]["is_llm_rcs"] is False
        assert "journal_metric" not in p
        assert "journal_rank" in p and p["journal_rank"] is None
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
        (agent_search.journal_rank, "load", lambda **kw: None),
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
    jm = env["meta"]["enrichment"]
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
    jm = env["meta"]["enrichment"]
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


# ===========================================================================
# Language axis (三轴模型 axis 2): --lang / --with-nssd / --with-yiigle + meta.language
# ===========================================================================


def _cfg_lang(search_language="auto", **kw):
    c = _cfg(**kw)
    c.search_language = search_language
    return c


# --- pure resolver: _query_has_cjk + _resolve_language --------------------------


def test_query_has_cjk_detection():
    assert agent_search._query_has_cjk("情绪调节 青少年") is True
    assert agent_search._query_has_cjk("emotion regulation") is False
    assert agent_search._query_has_cjk("mixed 中文 english") is True
    assert agent_search._query_has_cjk("") is False
    print("OK  query_has_cjk_detection")


def test_resolve_language_flag_wins_over_config():
    # Explicit --lang beats a persisted config value; not ambiguous; engaged.
    plan = agent_search._resolve_language(
        "情绪调节", _cfg_lang("en"), lang_flag="zh", with_nssd=False, with_yiigle=False
    )
    assert plan.scope_used == "zh"
    assert plan.scope_source == "flags"
    assert plan.ambiguous is False
    assert plan.engaged is True
    assert plan.query_lang == "zh"
    print("OK  resolve_language_flag_wins_over_config")


def test_resolve_language_config_adopted_silently():
    plan = agent_search._resolve_language(
        "alpha topic", _cfg_lang("both"), lang_flag=None, with_nssd=False, with_yiigle=False
    )
    assert plan.scope_used == "both"
    assert plan.scope_source == "config"
    assert plan.ambiguous is False
    assert plan.engaged is True  # config non-auto engages the feature
    print("OK  resolve_language_config_adopted_silently")


def test_resolve_language_auto_english_not_engaged():
    """The R-19 gate: English query + auto config + no flags => feature OFF."""
    plan = agent_search._resolve_language(
        "emotion regulation", _cfg_lang("auto"), lang_flag=None, with_nssd=False, with_yiigle=False
    )
    assert plan.scope_used == "en"
    assert plan.scope_source == "query_passthrough"
    assert plan.ambiguous is False
    assert plan.engaged is False  # <- no meta.language emitted on this path
    print("OK  resolve_language_auto_english_not_engaged")


def test_resolve_language_auto_chinese_is_ambiguous():
    """Chinese query + auto + no signal => zh passthrough, flagged ambiguous."""
    plan = agent_search._resolve_language(
        "情绪调节 青少年", _cfg_lang("auto"), lang_flag=None, with_nssd=False, with_yiigle=False
    )
    assert plan.query_lang == "zh"
    assert plan.scope_used == "zh"
    assert plan.scope_source == "query_passthrough"
    assert plan.ambiguous is True   # the agent version of "问一句"
    assert plan.engaged is True
    print("OK  resolve_language_auto_chinese_is_ambiguous")


def test_resolve_language_with_flag_upgrades_en_to_both():
    """--with-nssd on an en scope upgrades to 'both' so the query reaches NSSD (§6.6)."""
    plan = agent_search._resolve_language(
        "alpha topic", _cfg_lang("auto"), lang_flag=None, with_nssd=True, with_yiigle=False
    )
    assert plan.scope_used == "both"
    assert plan.upgraded_en_to_both is True
    assert plan.chinese_sources == ["nssd"]
    assert plan.engaged is True
    print("OK  resolve_language_with_flag_upgrades_en_to_both")


# --- full pipeline: meta.language emission + Chinese-source merge ----------------


def _cn_stub(source_attr, papers):
    """(obj, attr, stub) that fakes nssd_helper/yiigle_helper.search -> papers."""
    return (
        getattr(agent_search, source_attr),
        "search",
        lambda q, n=25, year_min=None, **kw: list(papers),
    )


def test_default_english_run_has_no_language_key():
    """R-19 at the envelope level: default English run emits NO meta.language key."""
    p = _paper(doi="10.1/x", title="alpha topic", abstract="alpha topic", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg_lang("auto"), per_strategy=5, now_year=2026)
    assert env["ok"] is True
    assert "language" not in env["meta"]
    print("OK  default_english_run_has_no_language_key")


def test_lang_zh_flag_emits_language_meta_without_chinese_sources():
    """--lang zh sets the space + emits meta.language, but adds NO supplemental
    source (those are --with-* only, §8). NSSD/yiigle must NOT be called."""
    p = _paper(doi="10.1/x", title="alpha topic", abstract="alpha topic", year=2024, cites=5)
    called = {"nssd": 0, "yiigle": 0}

    def spy_nssd(q, n=25, year_min=None, **kw):
        called["nssd"] += 1
        return []

    def spy_yiigle(q, n=25, year_min=None, **kw):
        called["yiigle"] += 1
        return []

    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    targets += [
        (agent_search.nssd_helper, "search", spy_nssd),
        (agent_search.yiigle_helper, "search", spy_yiigle),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg_lang("auto"), per_strategy=5, lang="zh", now_year=2026)
    lang = env["meta"]["language"]
    assert lang["scope_used"] == "zh"
    assert lang["scope_source"] == "flags"
    assert lang["ambiguous"] is False
    assert lang["chinese_sources_used"] == []
    assert called == {"nssd": 0, "yiigle": 0}  # supplemental sources are explicit-only
    print("OK  lang_zh_flag_emits_language_meta_without_chinese_sources")


def test_with_nssd_merges_results_and_reports():
    """--with-nssd queries NSSD and folds its distinct paper into the candidate
    pool (federated dedup); it appears in data + chinese_sources_used reports it."""
    oa = _paper(doi="10.1/oa", title="alpha topic", abstract="alpha topic", year=2024, cites=100)
    nssd_p = _paper(doi="10.1/nssd", title="alpha topic beta", abstract="alpha topic beta",
                    year=2023, cites=3, sources=["nssd"])
    targets = _oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("nssd_helper", [nssd_p]))
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg_lang("auto"), per_strategy=5, with_nssd=True, now_year=2026
        )
    assert env["ok"] is True
    dois = {p["doi"] for p in env["data"]}
    assert dois == {"10.1/oa", "10.1/nssd"}   # NSSD paper merged in
    assert env["meta"]["counts"]["after_dedup"] == 2
    lang = env["meta"]["language"]
    assert lang["chinese_sources_used"] == ["nssd"]
    assert lang["scope_used"] == "both"       # en upgraded to both
    assert any("upgraded to 'both'" in w for w in env["meta"]["warnings"])
    print("OK  with_nssd_merges_results_and_reports")


def test_with_yiigle_on_chinese_query_merges():
    """A Chinese query + --with-yiigle: scope stays zh, yiigle paper merges, and
    meta.language reports it (no en->both upgrade needed)."""
    oa = _paper(doi="10.1/oa", title="深度学习 医学", year=2024, cites=50)
    yi = _paper(doi="10.1/yi", title="深度学习 影像", year=2023, cites=8, sources=["yiigle"])
    targets = _oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("yiigle_helper", [yi]))
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "深度学习 医学", _cfg_lang("auto"), per_strategy=5, with_yiigle=True, now_year=2026
        )
    assert env["ok"] is True
    assert {p["doi"] for p in env["data"]} == {"10.1/oa", "10.1/yi"}
    lang = env["meta"]["language"]
    assert lang["scope_used"] == "zh"          # Chinese query -> zh, no upgrade
    assert lang["query_lang"] == "zh"
    assert lang["chinese_sources_used"] == ["yiigle"]
    print("OK  with_yiigle_on_chinese_query_merges")


def test_config_search_language_zh_adopted_in_pipeline():
    """config.search_language='zh' with no --lang => scope_source 'config'."""
    p = _paper(doi="10.1/x", title="alpha topic", abstract="alpha topic", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg_lang("zh"), per_strategy=5, now_year=2026)
    lang = env["meta"]["language"]
    assert lang["scope_used"] == "zh"
    assert lang["scope_source"] == "config"
    assert lang["ambiguous"] is False
    print("OK  config_search_language_zh_adopted_in_pipeline")


def test_chinese_source_empty_degrades_gracefully():
    """When NSSD returns nothing, the run still succeeds; chinese_sources_used still
    reports it (it was queried) and a warning notes the empty return."""
    oa = _paper(doi="10.1/oa", title="alpha topic", abstract="alpha topic", year=2024, cites=100)
    targets = _oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("nssd_helper", []))  # NSSD returns nothing
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg_lang("auto"), per_strategy=5, with_nssd=True, now_year=2026
        )
    assert env["ok"] is True
    assert {p["doi"] for p in env["data"]} == {"10.1/oa"}
    assert env["meta"]["language"]["chinese_sources_used"] == ["nssd"]
    assert any("nssd returned 0 papers" in w for w in env["meta"]["warnings"])
    print("OK  chinese_source_empty_degrades_gracefully")


def test_chinese_source_only_results_when_primary_empty():
    """If the primary source returns nothing but --with-nssd yields papers, the run
    still succeeds on the Chinese source alone (no false E_NO_RESULTS)."""
    nssd_p = _paper(doi="10.1/nssd", title="alpha topic", abstract="alpha topic",
                    year=2023, cites=3, sources=["nssd"])
    targets = _oa_targets({"cited_by_count:desc": [], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("nssd_helper", [nssd_p]))
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg_lang("zh"), per_strategy=5, with_nssd=True, now_year=2026
        )
    assert env["ok"] is True
    assert {p["doi"] for p in env["data"]} == {"10.1/nssd"}
    assert env["meta"]["counts"]["after_dedup"] == 1
    print("OK  chinese_source_only_results_when_primary_empty")


# ===========================================================================
# v2.3.0 G3 review fixes: #1 warn / #6 year_max / #8 --primary-source /
# #9 CJK floor scoring / #10 saturation rebase / #11 counts split / #17 paper_id
# ===========================================================================


# --- #9: CJK-aware tokenisation + coverage (English path byte-identical) ---------


def test_cjk_tokenize_and_coverage():
    """#9: a CJK query gets character 2-gram terms (query-grounded); the English
    path is unchanged; CJK coverage is substring-based."""
    assert agent_search._tokenize_query("情绪调节") == ["情绪", "绪调", "调节"]
    # single-char CJK run yields the char itself.
    assert agent_search._tokenize_query("茶") == ["茶"]
    # English path: no CJK grams added -> byte-identical to the latin-only behaviour.
    assert agent_search._tokenize_query("emotion regulation") == ["emotion", "regulation"]
    # mixed latin + CJK.
    mixed = agent_search._tokenize_query("深度学习 cnn")
    assert "cnn" in mixed and "深度" in mixed and "学习" in mixed
    # coverage: CJK bigram substring match.
    assert agent_search._coverage(["情绪", "调节"], "青少年情绪与调节策略") == 1.0
    assert agent_search._coverage(["情绪"], "认知负荷研究") == 0.0
    # English coverage unchanged (token membership, not substring).
    assert agent_search._coverage(["cat"], "this is a category of things") == 0.0
    print("OK  cjk_tokenize_and_coverage")


def test_relevance_cjk_query_is_grounded():
    """#9: a Chinese query now scores ABOVE the old citation+recency-only 0.25 floor
    when the paper's title/abstract carry the query characters."""
    terms = agent_search._tokenize_query("情绪调节 青少年")
    on = _paper(title="青少年情绪调节的神经机制", abstract="情绪调节 青少年",
                year=2026, cites=100)
    rel = agent_search.compute_relevance(on, terms, now_year=2026)
    assert rel["components"]["title_coverage"] > 0
    assert rel["components"]["abstract_coverage"] > 0
    assert rel["score"] > 0.25  # would be <=0.25 under the latin-only tokeniser
    # An off-topic Chinese paper stays low (no false grounding).
    off = _paper(title="市场经济与货币政策", abstract="通货膨胀", year=2026, cites=100)
    rel_off = agent_search.compute_relevance(off, terms, now_year=2026)
    assert rel_off["components"]["title_coverage"] == 0.0
    print("OK  relevance_cjk_query_is_grounded")


def test_min_relevance_guard_when_no_terms():
    """#9: a query that tokenises to NOTHING (no groundable terms) must not be
    filtered to empty by --min-relevance; saturation marks the distribution N/A."""
    assert agent_search._tokenize_query("of the") == []  # all stopwords/short
    p = _paper(doi="10.1/x", title="anything", abstract="x", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("of the", _cfg(), per_strategy=5,
                                            min_relevance=0.9, now_year=2026)
    assert env["ok"] is True
    assert len(env["data"]) == 1  # NOT filtered out despite min_relevance=0.9
    sat = env["meta"]["saturation"]
    assert sat["score_distribution"] is None
    assert "not applicable" in sat["score_distribution_note"]
    print("OK  min_relevance_guard_when_no_terms")


# --- #6: year_max honoured for Chinese sources ----------------------------------


def test_year_max_filters_chinese_sources():
    """#6: year_max is applied client-side to Chinese-source results (their helpers
    only take year_min). Unknown-year records are kept (not provably over ceiling)."""
    old = _paper(doi="10.1/old", title="alpha topic", year=2010, cites=3, sources=["nssd"])
    new = _paper(doi="10.1/new", title="alpha topic", year=2024, cites=3, sources=["nssd"])
    unk = _paper(doi="10.1/unk", title="alpha topic", year=None, cites=1, sources=["nssd"])
    oa = _paper(doi="10.1/oa", title="alpha topic", abstract="alpha topic", year=2020, cites=100)
    targets = _oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("nssd_helper", [old, new, unk]))
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "alpha topic", _cfg_lang("auto"), per_strategy=5, with_nssd=True,
            year_max=2015, now_year=2026,
        )
    dois = {p["doi"] for p in env["data"]}
    assert "10.1/new" not in dois   # 2024 > 2015 -> dropped
    assert "10.1/old" in dois       # 2010 <= 2015 -> kept
    assert "10.1/unk" in dois       # unknown year -> kept
    print("OK  year_max_filters_chinese_sources")


# --- #8: --primary-source transient override ------------------------------------


def test_primary_source_flag_overrides_config_to_ss():
    """#8: --primary-source semantic_scholar transiently routes to SS even when
    config.primary_source is openalex; config is NOT mutated (single-use)."""
    ss_paper = _paper(doi="10.1/ss", title="alpha topic", abstract="alpha topic",
                      year=2024, cites=42, sources=["semantic_scholar"])
    cfg = _cfg(primary="openalex", ss_key="KEY")
    with _patched(*_ss_primary_targets([ss_paper])):
        env = agent_search.run_agent_search(
            "alpha topic", cfg, per_strategy=5, primary_source="semantic_scholar",
            issn_backfill=False, now_year=2026,
        )
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "semantic_scholar"
    assert env["data"][0]["doi"] == "10.1/ss"
    assert cfg.primary_source == "openalex"  # transient: config untouched
    print("OK  primary_source_flag_overrides_config_to_ss")


def test_primary_source_flag_overrides_config_to_openalex():
    """#8 reverse: override openalex wins over config semantic_scholar — and rescues
    a keyless SS config for this run (no E_CONFIG, since SS is never selected)."""
    p = _paper(doi="10.1/oa", title="alpha topic", abstract="alpha topic", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    cfg = _cfg(primary="semantic_scholar", ss_key="")  # no SS key
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", cfg, per_strategy=5,
                                            primary_source="openalex", now_year=2026)
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "openalex"
    assert cfg.primary_source == "semantic_scholar"  # transient: config untouched
    print("OK  primary_source_flag_overrides_config_to_openalex")


# --- #1: CJK query under en scope warns (no headless translation) ---------------


def test_cjk_query_under_en_scope_warns():
    """#1: a Chinese query forced to en scope (--lang en) warns that the agent path
    does not translate; a zh scope does NOT warn."""
    p = _paper(doi="10.1/x", title="alpha", abstract="alpha", year=2024, cites=5)
    targets = _oa_targets({"cited_by_count:desc": [p], "publication_date:desc": [], "relevance_score:desc": []})
    with _patched(*targets):
        env = agent_search.run_agent_search("情绪调节", _cfg_lang("auto"), per_strategy=5,
                                            lang="en", now_year=2026)
    assert env["meta"]["language"]["scope_used"] == "en"
    assert env["meta"]["language"]["query_lang"] == "zh"
    assert any("does not translate" in w for w in env["meta"]["warnings"])
    with _patched(*targets):
        env2 = agent_search.run_agent_search("情绪调节", _cfg_lang("auto"), per_strategy=5,
                                             lang="zh", now_year=2026)
    assert not any("does not translate" in w for w in env2["meta"]["warnings"])
    print("OK  cjk_query_under_en_scope_warns")


# --- #17: paper_id join key emitted on engaged path, absent on default (R-19) ----


def test_paper_id_emitted_only_when_engaged():
    """#17: paper_id (a @property) is serialised into data[] ONLY on an engaged
    (Chinese/lang) envelope; the default English envelope omits it (R-19)."""
    oa = _paper(doi="10.1/oa", title="alpha topic", abstract="alpha topic", year=2024, cites=100)
    nssd_p = _paper(title="alpha topic beta", abstract="alpha topic beta", year=2023,
                    cites=3, sources=["nssd"])
    nssd_p.source_native_id = "NSSD-42"  # the non-obvious paper_id fallback #17 targets
    targets = _oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})
    targets.append(_cn_stub("nssd_helper", [nssd_p]))
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg_lang("auto"), per_strategy=5,
                                            with_nssd=True, now_year=2026)
    assert all("paper_id" in p for p in env["data"])
    by_doi = {p.get("doi"): p for p in env["data"]}
    assert by_doi["10.1/oa"]["paper_id"] == "10.1/oa"           # doi is top priority
    nssd_out = [p for p in env["data"] if p.get("doi") is None][0]
    assert nssd_out["paper_id"] == "NSSD-42"                    # source_native_id fallback

    # Default English envelope: NO paper_id key (byte-identical default, R-19).
    with _patched(*_oa_targets({"cited_by_count:desc": [oa], "publication_date:desc": [], "relevance_score:desc": []})):
        env_def = agent_search.run_agent_search("alpha topic", _cfg(), per_strategy=5, now_year=2026)
    assert all("paper_id" not in p for p in env_def["data"])
    print("OK  paper_id_emitted_only_when_engaged")


# --- #10 + #11: saturation rebased to primary strategies + Chinese count split ---


def test_saturation_excludes_chinese_and_counts_split():
    """#10: the marginal-yield saturation is computed on the PRIMARY strategies only
    (a Chinese source appended last does not become per_strategy_new[-1]). #11: the
    raw count is split into primary vs Chinese."""
    oa1 = [_paper(doi=f"10.1/oa{i}", title="alpha topic", abstract="alpha topic",
                  year=2024, cites=100 - i) for i in range(12)]
    targets = _oa_targets({
        "cited_by_count:desc": oa1,
        "publication_date:desc": oa1,   # all dups -> last PRIMARY strategy adds 0 new
        "relevance_score:desc": oa1,
    })
    nssd_ps = [_paper(doi=f"10.1/nssd{i}", title="alpha topic", year=2023, cites=1,
                      sources=["nssd"]) for i in range(5)]
    targets.append(_cn_stub("nssd_helper", nssd_ps))
    with _patched(*targets):
        env = agent_search.run_agent_search("alpha topic", _cfg_lang("auto"),
                                            per_strategy=12, with_nssd=True, now_year=2026)
    sat = env["meta"]["saturation"]
    # per_strategy_new is PRIMARY-only (3 entries) — NOT 4 with the NSSD list.
    assert len(sat["per_strategy_new_papers"]) == 3
    # marginal yield reads the primary last strategy (0), not the NSSD 5-new tail.
    assert sat["last_strategy_marginal_yield"] == 0.0
    assert sat["excludes_chinese_sources"] is True
    assert "chinese_sources_note" in sat
    counts = env["meta"]["counts"]
    assert counts["retrieved_raw_chinese"] == 5
    assert counts["retrieved_raw_primary"] == counts["retrieved_raw"] - 5
    print("OK  saturation_excludes_chinese_and_counts_split")


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
        test_query_has_cjk_detection,
        test_resolve_language_flag_wins_over_config,
        test_resolve_language_config_adopted_silently,
        test_resolve_language_auto_english_not_engaged,
        test_resolve_language_auto_chinese_is_ambiguous,
        test_resolve_language_with_flag_upgrades_en_to_both,
        test_default_english_run_has_no_language_key,
        test_lang_zh_flag_emits_language_meta_without_chinese_sources,
        test_with_nssd_merges_results_and_reports,
        test_with_yiigle_on_chinese_query_merges,
        test_config_search_language_zh_adopted_in_pipeline,
        test_chinese_source_empty_degrades_gracefully,
        test_chinese_source_only_results_when_primary_empty,
        test_cjk_tokenize_and_coverage,
        test_relevance_cjk_query_is_grounded,
        test_min_relevance_guard_when_no_terms,
        test_year_max_filters_chinese_sources,
        test_primary_source_flag_overrides_config_to_ss,
        test_primary_source_flag_overrides_config_to_openalex,
        test_cjk_query_under_en_scope_warns,
        test_paper_id_emitted_only_when_engaged,
        test_saturation_excludes_chinese_and_counts_split,
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
