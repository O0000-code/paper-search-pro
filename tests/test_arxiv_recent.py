"""Offline tests: arXiv recent layer (date window), required terms, timeout, failure.

2026-10-01, recency-retrieval: the arXiv freshness sentinel only looked back 4
days, bare words were OR-ed ("diffusion language model" returned Yiddish and
Romansh language-model papers), and requests had no timeout (one run hung 100 s).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys

import pytest

import scripts.arxiv_helper as axh


@pytest.mark.parametrize("query,expected", [
    ("diffusion language model", "all:diffusion AND all:language AND all:model"),
    ('"working memory" training of older adults',
     'all:"working memory" AND all:training AND all:older AND all:adults'),
    ("LLM AND hallucination", "LLM AND hallucination"),       # user operators kept
    ("ti:transformer attention", "ti:transformer attention"),  # field prefix kept
    ("transformer", "transformer"),                            # one word: unchanged
])
def test_plain_words_become_required_terms(query, expected):
    assert axh._require_terms(query) == expected


def test_submitted_clause():
    assert axh._submitted_clause(None, None) is None
    assert axh._submitted_clause("2025-10-01", "2026-10-01") == \
        "submittedDate:[202510010000 TO 202610012359]"


class _Search:
    def __init__(self, query, max_results, sort_by, sort_order):
        self.query = query


class _Client:
    last = None

    def results(self, search):
        type(self).last = search
        return iter(())


def test_search_recent_adds_the_date_window(monkeypatch):
    monkeypatch.setattr(axh.arxiv, "Search", _Search)
    monkeypatch.setattr(axh, "_client", lambda: _Client())
    axh.search_recent("diffusion language model", max_results=5, sort_by="relevance",
                      date_from="2025-10-01", date_to="2026-10-01")
    q = _Client.last.query
    assert q.startswith("(all:diffusion AND all:language AND all:model) AND (cat:cs.*")
    assert q.endswith("AND submittedDate:[202510010000 TO 202610012359]")


def test_search_recent_without_window_is_unchanged(monkeypatch):
    monkeypatch.setattr(axh.arxiv, "Search", _Search)
    monkeypatch.setattr(axh, "_client", lambda: _Client())
    axh.search_recent("transformer", max_results=5)
    assert "submittedDate" not in _Client.last.query


def test_client_requests_carry_a_timeout(monkeypatch):
    seen = {}

    class _Session:
        def get(self, url, **kw):
            seen.update(kw)
            return None

    class _ArxivClient:
        def __init__(self, **_k):
            self._session = _Session()

    monkeypatch.setattr(axh.arxiv, "Client", _ArxivClient)
    axh._client()._session.get("http://x", headers={})
    assert seen["timeout"] == axh._REQUEST_TIMEOUT_S


@pytest.mark.parametrize("argv", [
    ["search", "q", "--sort", "relevance", "--since-days", "365"],
    ["freshness", "q"],
])
def test_cli_failure_is_an_empty_source(monkeypatch, argv):
    def boom(*_a, **_k):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(axh, "search_recent", boom)
    monkeypatch.setattr(axh, "search_freshness_window", boom)
    monkeypatch.setattr("scripts.config.load_config", lambda: None)
    monkeypatch.setattr(sys, "argv", ["arxiv_helper", *argv])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        axh._main_cli()
    assert json.loads(out.getvalue()) == []
    assert "returning no arXiv records" in err.getvalue()
