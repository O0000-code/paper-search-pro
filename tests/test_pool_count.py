"""Offline tests: the pool count behind the report's year-chart note.

2026-10-01, recency-retrieval: the year chart counts what a search retrieved, and
a user read a thin 2025–2026 bar as an unstudied topic. STEP 3 now records how
many OpenAlex works match the query in title and abstract; the report adds one
sentence when (and only when) that figure exists.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import sys
from pathlib import Path

import scripts.data_materialization as dm
import scripts.openalex_helper as oah
from scripts import openalex_guard
from scripts.openalex_guard import OpenAlexUnavailable
from scripts.types import UnifiedPaperEntity


class _CountingWorks:
    filters: list = []

    def __init__(self):
        type(self).filters = []

    def filter(self, **kw):
        type(self).filters.append(kw)
        return self

    def count(self):
        return 2664


def test_count_defaults_to_the_last_two_years(monkeypatch):
    monkeypatch.setattr(oah, "_today", lambda: datetime.date(2026, 10, 1))
    monkeypatch.setattr(oah, "Works", _CountingWorks)
    assert oah.count_title_abstract_matches("emotion regulation") == (2664, 2025, 2026)
    assert {"title_and_abstract": {"search": "emotion regulation"}} in _CountingWorks.filters
    assert {"publication_year": "2025-2026"} in _CountingWorks.filters


def test_count_uses_the_given_range(monkeypatch):
    monkeypatch.setattr(oah, "_today", lambda: datetime.date(2026, 10, 1))
    monkeypatch.setattr(oah, "Works", _CountingWorks)
    assert oah.count_title_abstract_matches("q", year_min=2020)[1:] == (2020, 2026)
    assert oah.count_title_abstract_matches("q", 2010, 2015)[1:] == (2010, 2015)


def _run(monkeypatch, argv, count):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr(oah, "count_title_abstract_matches", count)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        oah._main_cli()
    return json.loads(out.getvalue())


def test_cli_count(monkeypatch):
    out = _run(monkeypatch, ["count", "q"], lambda q, year_min=None, year_max=None: (24, 2025, 2026))
    assert out == {"count": 24, "year_min": 2025, "year_max": 2026,
                   "matched_in": "title_and_abstract", "query": "q"}


def test_cli_count_when_openalex_is_down_is_null_not_a_fallback(monkeypatch):
    def down(*_a, **_k):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    out = _run(monkeypatch, ["count", "q"], down)
    assert out["count"] is None and "error" in out


def _paper(doi, year):
    return UnifiedPaperEntity(doi=doi, title=doi, year=year, rcs=6, sources=["openalex"])


def _materialise(run_dir: Path):
    (run_dir / "kg.json").write_text("{}")
    kg = {p.paper_id: p for p in (_paper("10.1/a", 2025), _paper("10.1/b", 2026))}
    arts = dm.materialize(kg, run_dir / "out", user_query="q", tier="standard", search_id="sid",
                          summary="ES", kg_source_path=run_dir / "kg.json")
    return json.loads(arts["chart_data"].read_text())["publication_year"]


def test_materialize_carries_the_pool(tmp_path):
    (tmp_path / "pool_count.json").write_text(json.dumps(
        {"count": 2664, "year_min": 2025, "year_max": 2026, "matched_in": "title_and_abstract"}))
    assert _materialise(tmp_path)["pool"] == {"count": 2664, "year_min": 2025, "year_max": 2026}


def test_materialize_without_pool_file_is_unchanged(tmp_path):
    assert "pool" not in _materialise(tmp_path)


def test_materialize_ignores_a_null_count(tmp_path):
    (tmp_path / "pool_count.json").write_text(json.dumps({"count": None, "error": "budget"}))
    assert "pool" not in _materialise(tmp_path)
