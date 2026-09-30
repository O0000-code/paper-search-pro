"""Offline tests: edge cases found by the Codex review of the recency branch (2026-10-01).

Each test reproduces one finding in ../recency-retrieval/70_codex_review.md:
the current-year cap on every entry point, a year range lying in the future,
Quick's recent layer surviving a mid-run fallback, '|' kept as OR, the
OpenReview title merge refusing ambiguous matches, and arXiv's term rewrite
being quote-aware.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import sys

import pytest

import scripts.arxiv_helper as axh
import scripts.openalex_helper as oah
from scripts import openalex_guard, source_fallback, ss_helper
from scripts.federated_kg_resolver import federated_dedup
from scripts.openalex_guard import OpenAlexUnavailable
from scripts.types import Config, UnifiedPaperEntity


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(oah, "_today", lambda: datetime.date(2026, 10, 1))


def _p(doi, cites=0, year=2026):
    return UnifiedPaperEntity(doi=doi, title=doi, year=year, citation_count=cites,
                              sources=["openalex"])


def _cli(monkeypatch, argv, **stubs):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr("scripts.config.load_config", lambda: Config())
    monkeypatch.setattr(source_fallback, "init", lambda cfg: None)
    for name, fn in stubs.items():
        monkeypatch.setattr(oah, name, fn)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            oah._main_cli()
        except SystemExit:
            pass
    return json.loads(out.getvalue())


# ---------------------------------------------------------------------------
# 1. Every retrieval entry point is capped at the current year
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv,stub", [
    (["deep", "q", "--n", "5"], "search_top_n_pages"),
    (["reviews", "q", "--limit", "5"], "find_review_articles"),
    (["search", "q", "--limit", "5"], "search_works"),
])
def test_cli_entry_points_cap_year_max(monkeypatch, today, argv, stub):
    seen = {}

    def fake(*_a, **k):
        seen.update(year_max=k.get("year_max"))
        return []

    _cli(monkeypatch, argv, **{stub: fake})
    assert seen["year_max"] == 2026


def test_fallback_gets_the_year_cap(monkeypatch, today):
    seen = {}

    def down(*_a, **_k):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    def fake_ss(q, **k):
        seen.update(k)
        return []

    monkeypatch.setattr(ss_helper, "search", fake_ss)
    _cli(monkeypatch, ["double-sort", "q", "--n", "5"], double_sort_search=down)
    assert seen.get("year_max") == 2026


def test_agent_path_caps_year_max(monkeypatch, today):
    from scripts import agent_search
    seen = []
    monkeypatch.setattr(agent_search.openalex_helper, "run_leg",
                        lambda leg, q, n, year_min=None, year_max=None: seen.append(year_max) or [])
    agent_search._retrieve("q", "openalex", year_min=None, year_max=None, per_strategy=5)
    assert seen and all(y == 2026 for y in seen)


# ---------------------------------------------------------------------------
# 2. A year range in the future is empty, not an invalid request
# ---------------------------------------------------------------------------


def test_future_year_min_returns_empty_without_querying(monkeypatch, today):
    monkeypatch.setattr(oah, "Works", lambda: pytest.fail("no request for an empty range"))
    assert oah.double_sort_search("q", year_min=2027) == []
    assert oah.search_works("q", year_min=2027) == []
    assert oah.search_top_n_pages("q", total_papers=5, year_min=2027, year_max=2026) == []
    assert oah.count_title_abstract_matches("q", year_min=2027) == (0, 2027, 2026)


# ---------------------------------------------------------------------------
# 3. Quick's recent layer survives a fallback in the middle of the call
# ---------------------------------------------------------------------------


def test_search_recent_fallback_keeps_partials_and_fallback_records(monkeypatch, today):
    def leg(name, q, n, year_min=None, year_max=None):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_p(f"10.1/recent{i}") for i in range(5)]   # cut off after 5 of 20
        raise exc

    monkeypatch.setattr(ss_helper, "search", lambda q, **k: [_p(f"10.2/ss{i}") for i in range(5)])
    out = _cli(monkeypatch, ["search", "q", "--limit", "30", "--recent", "20"],
               search_works=lambda q, **k: [_p(f"10.1/rel{i}") for i in range(30)],
               run_leg=leg)
    dois = [p["doi"] for p in out]
    assert sum(d.startswith("10.1/rel") for d in dois) == 30
    assert sum(d.startswith("10.1/recent") for d in dois) == 5
    assert any(d.startswith("10.2/ss") for d in dois)


# ---------------------------------------------------------------------------
# 4. '|' in a query stays an OR in the title+abstract filter
# ---------------------------------------------------------------------------


def test_pipe_becomes_or_not_and():
    assert oah._title_abstract_filter_value("diffusion|language, model") == "diffusion OR language model"


# ---------------------------------------------------------------------------
# 5. The OpenReview merge refuses ambiguous matches
# ---------------------------------------------------------------------------


def _or(title, year=2026):
    return UnifiedPaperEntity(source_native_id="openreview:x1", title=title, year=year,
                              venue="ICLR 2026 Oral", type="article", sources=["openreview"])


def _oa(doi, title, year=2025, venue="arXiv (Cornell University)"):
    return UnifiedPaperEntity(doi=doi, title=title, year=year, venue=venue, type="preprint",
                              sources=["openalex"])


def test_missing_year_does_not_merge():
    kg = federated_dedup([_oa("10.1/a", "Diffusion Models Know the Answer Early", year=None)],
                         [_or("Diffusion Models Know the Answer Early")])
    assert len(kg) == 2


def test_short_generic_title_does_not_merge():
    kg = federated_dedup([_oa("10.1/a", "Introduction")], [_or("Introduction")])
    assert len(kg) == 2


def test_several_candidates_label_the_preprint():
    title = "Simple and Effective Masked Diffusion Language Models"
    published = _oa("10.52202/1", title, venue="Advances in Neural Information Processing Systems")
    published.type = "article"
    kg = federated_dedup([published, _oa("10.48550/arxiv.2406.07524", title)], [_or(title, 2025)])
    assert len(kg) == 2
    venues = {p.doi: p.venue for p in kg.values()}
    assert venues["10.48550/arxiv.2406.07524"] == "ICLR 2026 Oral"
    assert venues["10.52202/1"] == "Advances in Neural Information Processing Systems"


# ---------------------------------------------------------------------------
# 6. arXiv's required-terms rewrite is quote-aware
# ---------------------------------------------------------------------------


def test_or_inside_quotes_is_not_an_operator():
    assert axh._require_terms('"OR gate" neural network') == 'all:"OR gate" AND all:neural AND all:network'


def test_unmatched_quote_does_not_produce_broken_syntax():
    assert axh._require_terms('"working memory training') == "all:working AND all:memory AND all:training"


# ===========================================================================
# Second Codex review (../recency-retrieval/71_codex_review_round2.md)
# ===========================================================================


def test_search_recent_fallback_cap_counts_the_earlier_window(monkeypatch, today):
    # recent 20 → up to 20 + 10 (earlier window); main 30; OpenAlex fails before
    # the earlier window, Semantic Scholar supplies 10: all 60 fit.
    def leg(name, q, n, year_min=None, year_max=None):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_p(f"10.1/recent{i}") for i in range(20)]
        raise exc

    monkeypatch.setattr(ss_helper, "search", lambda q, **k: [_p(f"10.2/ss{i}") for i in range(10)])
    out = _cli(monkeypatch, ["search", "q", "--limit", "30", "--recent", "20"],
               search_works=lambda q, **k: [_p(f"10.1/rel{i}") for i in range(30)],
               run_leg=leg)
    assert sum(p["doi"].startswith("10.2/ss") for p in out) == 10


def test_short_distinctive_title_merges():
    kg = federated_dedup([_oa("10.48550/arxiv.2505.1", "FlashDLM")], [_or("FlashDLM")])
    assert len(kg) == 1 and next(iter(kg.values())).venue == "ICLR 2026 Oral"


@pytest.mark.parametrize("title", ["Introduction", "Editorial", "Erratum", "Preface"])
def test_generic_titles_do_not_merge(title):
    assert len(federated_dedup([_oa("10.1/a", title)], [_or(title)])) == 2


def test_openreview_plain_terms_is_quote_aware():
    from scripts import openreview_helper as orh
    assert orh.plain_terms('"OR gate" neural network') == "OR gate neural network"
    assert orh.plain_terms('"OR"') == "OR"


def test_arxiv_stray_quote_never_exposes_an_operator():
    q = axh._require_terms('"OR gate neural network')
    assert not q.startswith(" ") and not q.lstrip().startswith("OR ")
    assert "all:gate" in q and "all:network" in q


def test_query_warning_ignores_stopwords_but_still_flags_six_content_words():
    # 'of', 'on' are not terms; the six content words are all required, and on
    # 2026-10-01 this query matched 749 works (2025-26) against 3,934 for the
    # same concepts in OR groups — the warning is right to fire.
    assert oah.query_warning("effects of social media on adolescent mental health")
    # four content words: no warning
    assert oah.query_warning("the role of peers in the lives of adolescents") is None


def test_count_hint_is_silent_for_an_empty_range(monkeypatch):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr("scripts.config.load_config", lambda: Config())
    monkeypatch.setattr(oah, "count_title_abstract_matches",
                        lambda q, year_min=None, year_max=None: (0, 2027, 2026))
    monkeypatch.setattr(sys, "argv", ["openalex_helper", "count", "q", "--year-min", "2027"])
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        oah._main_cli()
    assert "too narrow" not in err.getvalue()
