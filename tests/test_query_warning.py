"""Offline tests: the long-bare-word query warning and the narrow-pool hint.

2026-10-01: agents listed synonyms as bare words, which OpenAlex requires one and
all. "short-form video use college university students attention attentional
control sustained attention concentration" matched a single paper by title and
abstract across 2021-2026. The helpers now say so; the query still runs as written.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys

import pytest

import scripts.openalex_helper as oah
from scripts.types import Config


@pytest.mark.parametrize("query", [
    "short-form video use college university students attention attentional control sustained attention concentration",
    "curiosity interest epistemic emotions development children",
    '"short video" addiction college students procrastination burnout',
])
def test_long_bare_word_queries_are_warned(query):
    w = oah.query_warning(query)
    assert w and "requires every one" in w and "OR" in w


@pytest.mark.parametrize("query", [
    "working memory training older adults",                        # 5 terms: fine
    "emotion regulation adolescents",
    '("short video" OR TikTok OR Douyin) AND (attention OR concentration) AND (students OR undergraduates)',
    '"OR gate" logic',                                               # OR inside quotes is a word
])
def test_structured_or_short_queries_are_not_warned(query):
    assert oah.query_warning(query) is None


def _cli(monkeypatch, argv, **stubs):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr("scripts.config.load_config", lambda: Config())
    for name, fn in stubs.items():
        monkeypatch.setattr(oah, name, fn)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        oah._main_cli()
    return out.getvalue(), err.getvalue()


def test_cli_prints_the_warning_and_still_runs_the_query(monkeypatch):
    q = "curiosity interest epistemic emotions development children"
    seen = []
    out, err = _cli(monkeypatch, ["double-sort", q, "--n", "5"],
                    double_sort_search=lambda query, **k: seen.append(query) or [])
    assert seen == [q]                      # unchanged query
    assert json.loads(out) == []            # stdout stays pure JSON
    assert "requires every one" in err


def test_count_hints_at_a_narrow_query(monkeypatch):
    _, err = _cli(monkeypatch, ["count", "a b"],
                  count_title_abstract_matches=lambda q, year_min=None, year_max=None: (1, 2025, 2026))
    assert "only 1 works" in err and "too narrow" in err


def test_count_says_nothing_for_a_healthy_pool(monkeypatch):
    _, err = _cli(monkeypatch, ["count", "a b"],
                  count_title_abstract_matches=lambda q, year_min=None, year_max=None: (906, 2025, 2026))
    assert "too narrow" not in err


def test_agent_path_carries_the_warning(monkeypatch):
    from scripts import agent_search
    monkeypatch.setattr(agent_search.openalex_helper, "run_leg", lambda *a, **k: [])
    _r, warnings, _fb = agent_search._retrieve(
        "curiosity interest epistemic emotions development children", "openalex",
        year_min=None, year_max=None, per_strategy=5)
    assert any("requires every one" in w for w in warnings)
