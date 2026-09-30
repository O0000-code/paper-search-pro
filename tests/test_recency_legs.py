"""Offline tests: the recent layer, title-and-abstract matching, merge order.

Background (2026-09-30/10-01, recency-retrieval): double-sort's recent leg was
"newest first" over OpenAlex's full-text ``search=``, and returned whatever
mentioned the query words most recently — about 1 on-topic paper in 52 records
dated 2026. Its citation leg had the same flaw. These tests pin the fix: which
query each leg sends, the date windows, the year cap, and the merge order that
keeps the recent layer when an agent cuts the candidate list.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import sys

import pytest

import scripts.openalex_helper as oah
from scripts import openalex_guard
from scripts.openalex_guard import OpenAlexUnavailable
from scripts.types import UnifiedPaperEntity


class _RecordingWorks:
    """Stands in for pyalex.Works: records search/filter/sort calls, returns nothing."""

    calls: list = []

    def __init__(self):
        type(self).calls = []

    def search(self, q, **_k):
        type(self).calls.append(("search", q))
        return self

    def sort(self, **kw):
        type(self).calls.append(("sort", kw))
        return self

    def filter(self, **kw):
        type(self).calls.append(("filter", kw))
        return self

    def get(self, **_k):
        return []


@pytest.fixture
def today(monkeypatch):
    """Pin 'today' to 2026-10-01."""
    monkeypatch.setattr(oah, "_today", lambda: datetime.date(2026, 10, 1))


def _p(doi, cites=0, year=2020):
    return UnifiedPaperEntity(doi=doi, title=doi, year=year, citation_count=cites,
                              sources=["openalex"])


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


def test_recent_window_is_the_last_year(today):
    assert oah.recent_window() == ("2025-10-01", "2026-10-01")


def test_recent_window_is_clipped_to_year_min(today):
    assert oah.recent_window(year_min=2026) == ("2026-01-01", "2026-10-01")


def test_recent_window_for_a_past_range_is_its_last_year(today):
    assert oah.recent_window(2010, 2020) == ("2020-01-01", "2020-12-31")


def test_recent_window_for_a_future_range_is_none(today):
    assert oah.recent_window(year_min=2027) is None


def test_mid_window_is_the_two_years_before(today):
    recent = oah.recent_window()
    assert oah.mid_window(recent) == ("2023-10-01", "2025-09-30")


def test_mid_window_is_clipped_or_dropped_by_year_min(today):
    assert oah.mid_window(oah.recent_window(2025), 2025) == ("2025-01-01", "2025-09-30")
    assert oah.mid_window(oah.recent_window(2026), 2026) is None


# ---------------------------------------------------------------------------
# Which query each sort sends
# ---------------------------------------------------------------------------


def _filters():
    return [c[1] for c in _RecordingWorks.calls if c[0] == "filter"]


def test_relevance_sort_uses_full_search(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_top_n_pages("emotion regulation", total_papers=5, sort="relevance_score:desc")
    assert ("search", "emotion regulation") in _RecordingWorks.calls
    assert not any("title_and_abstract" in f for f in _filters())


@pytest.mark.parametrize("sort", ["cited_by_count:desc", "publication_date:desc"])
def test_other_sorts_match_title_and_abstract_only(monkeypatch, sort):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_top_n_pages("emotion regulation, teens | kids", total_papers=5, sort=sort)
    assert not any(c[0] == "search" for c in _RecordingWorks.calls)
    # comma dropped (it separates filters); "|" kept as OR
    assert {"title_and_abstract": {"search": "emotion regulation teens OR kids"}} in _filters()


def test_seminal_matches_title_and_abstract_only(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.find_seminal_papers("prospect theory", year_max=2015, limit=5)
    assert not any(c[0] == "search" for c in _RecordingWorks.calls)
    assert {"title_and_abstract": {"search": "prospect theory"}} in _filters()


def test_date_window_becomes_publication_date_filters(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_top_n_pages("q", total_papers=5, sort="relevance_score:desc",
                           date_from="2025-10-01", date_to="2026-10-01")
    assert {"from_publication_date": "2025-10-01"} in _filters()
    assert {"to_publication_date": "2026-10-01"} in _filters()


# ---------------------------------------------------------------------------
# Year cap
# ---------------------------------------------------------------------------


def test_search_without_year_max_is_capped_at_this_year(monkeypatch, today):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_works("q", limit=5)
    assert {"publication_year": "<2027"} in _filters()


def test_legs_without_year_max_are_capped_at_this_year(monkeypatch, today):
    seen = []

    def fake(query, total_papers=100, sort="", year_min=None, year_max=None,
             date_from=None, date_to=None, title_abstract_only=False):
        seen.append(year_max)
        return []

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    oah.double_sort_search("q", year_min=2018, total_per_strategy=6)
    assert seen and all(y == 2026 for y in seen)


def test_given_year_max_is_kept(monkeypatch, today):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_works("q", year_min=2015, year_max=2020, limit=5)
    assert {"publication_year": "2015-2020"} in _filters()


# ---------------------------------------------------------------------------
# The recent leg
# ---------------------------------------------------------------------------


def test_recent_leg_runs_last_year_then_two_years_before(monkeypatch, today):
    calls = []

    def fake(query, total_papers=100, sort="", year_min=None, year_max=None,
             date_from=None, date_to=None, title_abstract_only=False):
        calls.append((total_papers, sort, date_from, date_to, title_abstract_only))
        tag = "ta" if title_abstract_only else "ft"
        return [_p(f"10.1/{date_from}-{tag}-{i}") for i in range(2)] + [_p("10.1/both")]

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    out = oah.run_leg("recent", "q", 50)
    # Each window: title+abstract first; 3 < n, so topped up from full text.
    assert calls == [
        (50, "relevance_score:desc", "2025-10-01", "2026-10-01", True),
        (50, "relevance_score:desc", "2025-10-01", "2026-10-01", False),
        (25, "relevance_score:desc", "2023-10-01", "2025-09-30", True),
        (25, "relevance_score:desc", "2023-10-01", "2025-09-30", False),
    ]
    # Precise matches first, full-text fill next, repeats dropped; then the earlier window.
    assert [p.doi for p in out] == [
        "10.1/2025-10-01-ta-0", "10.1/2025-10-01-ta-1", "10.1/both",
        "10.1/2025-10-01-ft-0", "10.1/2025-10-01-ft-1",
        "10.1/2023-10-01-ta-0", "10.1/2023-10-01-ta-1",
        "10.1/2023-10-01-ft-0", "10.1/2023-10-01-ft-1",
    ]


def test_full_precise_window_is_not_topped_up(monkeypatch, today):
    calls = []

    def fake(query, total_papers=100, sort="", year_min=None, year_max=None,
             date_from=None, date_to=None, title_abstract_only=False):
        calls.append(title_abstract_only)
        return [_p(f"10.1/{date_from}-{i}") for i in range(total_papers)]

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    out = oah.run_leg("recent", "q", 4)
    assert calls == [True, True]      # both windows filled by title+abstract alone
    assert len(out) == 4 + 2


def test_top_up_keeps_precise_results_when_openalex_drops_out(monkeypatch, today):
    def fake(query, total_papers=100, sort="", year_min=None, year_max=None,
             date_from=None, date_to=None, title_abstract_only=False):
        if title_abstract_only:
            return [_p("10.1/precise")]
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_p("10.1/partial")]
        raise exc

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    with pytest.raises(OpenAlexUnavailable) as ei:
        oah.run_leg("recent", "q", 5)
    assert [p.doi for p in ei.value.partial] == ["10.1/precise", "10.1/partial"]


def test_title_abstract_only_switches_relevance_to_the_filter(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_top_n_pages("emotion regulation", total_papers=5, sort="relevance_score:desc",
                           title_abstract_only=True)
    assert not any(c[0] == "search" for c in _RecordingWorks.calls)
    assert {"title_and_abstract": {"search": "emotion regulation"}} in _filters()
    assert ("sort", {"relevance_score": "desc"}) in _RecordingWorks.calls


def test_recent_leg_is_empty_for_a_future_range(monkeypatch, today):
    monkeypatch.setattr(oah, "search_top_n_pages",
                        lambda *a, **k: pytest.fail("no query for a future range"))
    assert oah.run_leg("recent", "q", 50, year_min=2027) == []


def test_unknown_leg_is_an_error():
    with pytest.raises(ValueError):
        oah.run_leg("newest", "q", 5)


# ---------------------------------------------------------------------------
# Merge order
# ---------------------------------------------------------------------------


def test_merge_puts_shared_first_then_takes_turns():
    cited = [_p("c1", 900), _p("shared", 500), _p("c2", 800)]
    recent = [_p("r1", 0), _p("r2", 1), _p("shared", 500)]
    relevance = [_p("v1", 50), _p("v2", 40)]
    out = [p.doi for p in oah._merge_strategies([cited, recent, relevance])]
    # Shared first; then relevance, recent, cited in turn, each in its own order.
    assert out == ["shared", "v1", "r1", "c1", "v2", "r2", "c2"]


def test_merge_no_longer_sinks_new_papers_to_the_end():
    # Old behaviour sorted the single-strategy tail by citations, so all the
    # zero-citation recent papers came last and a head cut removed them.
    cited = [_p(f"c{i}", 1000 - i) for i in range(10)]
    recent = [_p(f"r{i}", 0) for i in range(10)]
    relevance = [_p(f"v{i}", 100 - i) for i in range(10)]
    head = oah._merge_strategies([cited, recent, relevance])[:9]
    assert sum(p.doi.startswith("r") for p in head) == 3


# ---------------------------------------------------------------------------
# CLI: search --recent (Quick tier's recent layer)
# ---------------------------------------------------------------------------


def _run_search_cli(monkeypatch, argv, search_works, run_leg):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr(oah, "search_works", search_works)
    monkeypatch.setattr(oah, "run_leg", run_leg)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        oah._main_cli()
    return json.loads(out.getvalue())


def test_search_without_recent_does_not_run_the_recent_leg(monkeypatch):
    out = _run_search_cli(
        monkeypatch, ["search", "q", "--limit", "2"],
        search_works=lambda q, **k: [_p("10.1/a"), _p("10.1/b")],
        run_leg=lambda *a, **k: pytest.fail("recent leg ran"),
    )
    assert [p["doi"] for p in out] == ["10.1/a", "10.1/b"]


def test_search_with_recent_merges_the_recent_leg(monkeypatch, today):
    seen = {}

    def leg(name, query, n, year_min=None, year_max=None):
        seen.update(name=name, n=n, year_min=year_min, year_max=year_max)
        return [_p("10.1/new", 0), _p("10.1/a")]

    out = _run_search_cli(
        monkeypatch, ["search", "q", "--limit", "2", "--recent", "20", "--year-min", "2018"],
        search_works=lambda q, **k: [_p("10.1/a", 90), _p("10.1/b", 80)],
        run_leg=leg,
    )
    assert seen == {"name": "recent", "n": 20, "year_min": 2018, "year_max": 2026}   # capped at this year
    assert [p["doi"] for p in out] == ["10.1/a", "10.1/b", "10.1/new"]
