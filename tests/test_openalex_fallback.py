"""Offline tests: an OpenAlex call that cannot be served switches source instead
of stopping the run.

Covers the 429/5xx classification (openalex_guard), partial-result retention,
the CLI fallback chain Semantic Scholar -> CrossRef, the Semantic Scholar
refused-key and throttling paths, the CrossRef record mapping, and the headless
agent_search switch. No network: pyalex's HTTP session and the fallback
backends are stubbed.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys

import pytest
import requests

import scripts.openalex_helper as oah
from scripts import agent_search, crossref_helper, openalex_guard, source_fallback, ss_helper
from scripts.openalex_guard import OpenAlexUnavailable
from scripts.types import Config, UnifiedPaperEntity

EXHAUSTED_HEADERS = {
    # Shape of a spent daily budget (OpenAlex docs + official CLI's test).
    "X-RateLimit-Limit": "10000",
    "X-RateLimit-Remaining": "0",
    "X-RateLimit-Credits-Required": "1",
    "X-RateLimit-Remaining-USD": "0",
    "X-RateLimit-Reset": "24765",
}
THROTTLED_HEADERS = {
    "X-RateLimit-Remaining": "9500",
    "X-RateLimit-Remaining-USD": "0.95",
    "Retry-After": "1",
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(openalex_guard, "_sleep", lambda _s: None)
    monkeypatch.setattr(ss_helper, "_sleep", lambda _s: None)
    monkeypatch.setattr(ss_helper.time, "sleep", lambda _s: None)
    monkeypatch.setattr(crossref_helper.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ss_helper, "_key_rejected", False)


def _response(status, headers=None, body=b'{"error": "Rate limit exceeded"}'):
    res = requests.models.Response()
    res.status_code = status
    res.headers.update(headers or {})
    res._content = body
    res.url = "https://api.openalex.org/works?search=x"
    res.reason = "Too Many Requests" if status == 429 else "Error"
    return res


def _http_error(status, headers=None):
    return requests.HTTPError(response=_response(status, headers))


def _raiser(*errors, result="ok"):
    """fn() that raises the given errors in turn, then returns ``result``."""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] <= len(errors):
            raise errors[calls["n"] - 1]
        return result

    return fn, calls


def _paper(doi, source="semantic_scholar", cites=1):
    return UnifiedPaperEntity(doi=doi, title=f"T {doi}", year=2020,
                              citation_count=cites, sources=[source])


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_budget_exhausted_is_not_retried():
    fn, calls = _raiser(_http_error(429, EXHAUSTED_HEADERS))
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.BUDGET_EXHAUSTED
    assert ei.value.reset_seconds == 24765
    assert "resets in 6h52m" in ei.value.describe()
    assert calls["n"] == 1


def test_usd_zero_alone_counts_as_exhausted():
    fn, _ = _raiser(_http_error(429, {"X-RateLimit-Remaining-USD": "0"}))
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.BUDGET_EXHAUSTED


def test_throttling_is_retried_then_succeeds():
    fn, calls = _raiser(_http_error(429, THROTTLED_HEADERS), _http_error(429, THROTTLED_HEADERS))
    assert openalex_guard.call(fn) == "ok"
    assert calls["n"] == 3


def test_persistent_throttling_becomes_unavailable():
    errors = [_http_error(429, THROTTLED_HEADERS)] * 4
    fn, calls = _raiser(*errors)
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.RATE_LIMITED
    assert calls["n"] == 4


def test_429_without_headers_is_treated_as_throttling():
    fn, calls = _raiser(_http_error(429, {}))
    assert openalex_guard.call(fn) == "ok"
    assert calls["n"] == 2


def test_server_error_gets_one_retry():
    fn, calls = _raiser(_http_error(503), _http_error(503))
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.SERVER_ERROR
    assert calls["n"] == 2


def test_connection_error_becomes_unavailable():
    fn, _ = _raiser(requests.ConnectionError("down"), requests.ConnectionError("down"))
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.NETWORK_ERROR


def test_bad_request_and_not_found_are_not_hidden():
    for status in (400, 404):
        fn, _ = _raiser(_http_error(status))
        with pytest.raises(requests.HTTPError):
            openalex_guard.call(fn)


def test_rejected_key_query_error_becomes_unavailable():
    from pyalex.api import QueryError

    fn, _ = _raiser(QueryError("Invalid API key. Did you configure a valid API key?"))
    with pytest.raises(OpenAlexUnavailable) as ei:
        openalex_guard.call(fn)
    assert ei.value.reason == openalex_guard.AUTH_REJECTED
    fn, _ = _raiser(QueryError("Invalid query parameters"))
    with pytest.raises(QueryError):
        openalex_guard.call(fn)


def test_real_pyalex_request_path_raises_unavailable(monkeypatch):
    """The 429 travels through pyalex's own _get_from_url/raise_for_status."""
    import pyalex.api as pyalex_api

    class _Session:
        def get(self, url, **kw):
            return _response(429, EXHAUSTED_HEADERS)

    monkeypatch.setattr(pyalex_api, "_get_requests_session", lambda: _Session())
    with pytest.raises(OpenAlexUnavailable) as ei:
        oah.search_works("working memory", limit=5)
    assert ei.value.reason == openalex_guard.BUDGET_EXHAUSTED


# --------------------------------------------------------------------------
# Partial results survive the cutoff
# --------------------------------------------------------------------------


class _PagedQuery:
    """First page returns one work, the second hits a spent budget."""

    def get(self, per_page, page):
        if page == 1:
            return [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/a",
                     "title": "Kept", "display_name": "Kept", "publication_year": 2020}]
        raise _http_error(429, EXHAUSTED_HEADERS)


def test_collect_pages_attaches_partial():
    with pytest.raises(OpenAlexUnavailable) as ei:
        oah._collect_pages(_PagedQuery(), limit=40, per_page=20)
    assert [p.doi for p in ei.value.partial] == ["10.1/a"]


def test_double_sort_keeps_finished_strategies(monkeypatch):
    def fake(query, total_papers, sort, year_min=None, year_max=None, date_from=None, date_to=None, title_abstract_only=False):
        if sort == "cited_by_count:desc":
            return [_paper("10.1/cited", "openalex")]
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_paper("10.1/recent", "openalex")]
        raise exc

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    with pytest.raises(OpenAlexUnavailable) as ei:
        oah.double_sort_search("q")
    assert {p.doi for p in ei.value.partial} == {"10.1/cited", "10.1/recent"}


# --------------------------------------------------------------------------
# CLI: the run continues on the fallback source
# --------------------------------------------------------------------------


def _run_cli(monkeypatch, argv, *, config=None):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    monkeypatch.setattr("scripts.config.load_config", lambda: config or Config())
    monkeypatch.setattr(source_fallback, "init", lambda cfg: None)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            oah._main_cli()
        except SystemExit as exc:
            code = exc.code
    return out.getvalue(), err.getvalue(), code


def _exhausted(*_a, **_k):
    raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED, reset_seconds=3600)


def test_cli_double_sort_switches_to_semantic_scholar(monkeypatch):
    monkeypatch.setattr(oah, "double_sort_search", _exhausted)
    seen = {}

    def fake_ss(q, **kw):
        seen.update(kw, q=q)
        return [_paper("10.2/ss")]

    monkeypatch.setattr(ss_helper, "search", fake_ss)
    out, err, code = _run_cli(
        monkeypatch, ["double-sort", "trust in robots", "--n", "30", "--year-min", "2018"]
    )
    assert code == 0
    assert [p["doi"] for p in json.loads(out)] == ["10.2/ss"]
    assert seen["q"] == "trust in robots" and seen["total_per_strategy"] == 30
    assert seen["year_min"] == 2018
    assert "OpenAlex unavailable (daily credit budget exhausted, resets in 1h00m (about" in err
    assert "Semantic Scholar" in err and "No action needed" in err


def test_cli_has_no_crossref_retrieval_tier(monkeypatch):
    monkeypatch.setattr(oah, "search_works", _exhausted)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [])
    monkeypatch.setattr(crossref_helper, "search_works",
                        lambda *a, **k: pytest.fail("CrossRef must not serve retrieval"))
    out, err, code = _run_cli(monkeypatch, ["--json-envelope", "search", "q", "--limit", "10"])
    env = json.loads(out)
    assert code == oah.EXIT_SOURCE_UNAVAILABLE and env["ok"] is False and env["data"] == []
    assert env["meta"]["fallback"]["served_by"] == []


def test_cli_nothing_serves_prints_empty_and_exit_3(monkeypatch):
    monkeypatch.setattr(oah, "search_works", _exhausted)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [])
    out, err, code = _run_cli(monkeypatch, ["search", "q"])
    assert code == oah.EXIT_SOURCE_UNAVAILABLE  # as before: an OpenAlex error
    assert json.loads(out) == []
    assert "tell the user what happened and when OpenAlex resets" in err


def test_cli_partial_openalex_results_are_kept_first(monkeypatch):
    def partial_then_down(*_a, **_k):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_paper("10.1/oa", "openalex")]
        raise exc

    monkeypatch.setattr(oah, "search_top_n_pages", partial_then_down)
    monkeypatch.setattr(ss_helper, "search",
                        lambda *a, **k: [_paper("10.1/oa"), _paper("10.2/ss")])
    out, err, code = _run_cli(monkeypatch, ["deep", "q", "--n", "5"])
    assert code == 0
    assert [p["doi"] for p in json.loads(out)] == ["10.1/oa", "10.2/ss"]
    assert "1 OpenAlex records fetched before the cutoff were kept" in err


def test_cli_fallback_off_restores_hard_stop(monkeypatch):
    monkeypatch.setattr(oah, "search_works", _exhausted)
    cfg = Config()
    cfg.quota_fallback = False
    out, err, code = _run_cli(monkeypatch, ["search", "q"], config=cfg)
    assert code == oah.EXIT_SOURCE_UNAVAILABLE
    assert "quota_fallback: false" in err
    assert json.loads(out) == []  # a `> file` redirect still gets valid JSON


def test_cli_get_with_w_id_cannot_fall_back(monkeypatch):
    monkeypatch.setattr(oah, "get_work", _exhausted)
    out, err, code = _run_cli(monkeypatch, ["get", "W3011865677"])
    assert code == oah.EXIT_SOURCE_UNAVAILABLE
    assert json.loads(out) == {}
    assert "pass the paper's DOI instead" in err


def test_cli_get_by_doi_uses_semantic_scholar(monkeypatch):
    monkeypatch.setattr(oah, "get_work", _exhausted)
    monkeypatch.setattr(ss_helper, "get_paper", lambda doi: _paper(doi))
    out, err, code = _run_cli(monkeypatch, ["get", "https://doi.org/10.5/x"])
    assert code == 0 and json.loads(out)["doi"] == "10.5/x"


def test_cli_citation_network_uses_seed_doi_from_partial(monkeypatch):
    def down(*_a, **_k):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = {"doi": "10.9/seed", "references": [_paper("10.9/r0", "openalex")],
                       "cited_by": []}
        raise exc

    got = {}

    def fake_net(doi, refs_limit, cited_by_limit):
        got["doi"] = doi
        return {"references": [_paper("10.9/r1")], "cited_by": [_paper("10.9/c1")]}

    monkeypatch.setattr(oah, "get_citation_network", down)
    monkeypatch.setattr(ss_helper, "citation_network", fake_net)
    out, err, code = _run_cli(monkeypatch, ["citation-network", "W123"])
    net = json.loads(out)
    assert code == 0 and got["doi"] == "10.9/seed"
    assert [p["doi"] for p in net["references"]] == ["10.9/r0", "10.9/r1"]
    assert [p["doi"] for p in net["cited_by"]] == ["10.9/c1"]


def test_cli_trends_has_no_fallback(monkeypatch):
    monkeypatch.setattr(oah, "analyze_topic_trends", _exhausted)
    out, err, code = _run_cli(monkeypatch, ["trends", "q"])
    assert code == oah.EXIT_SOURCE_UNAVAILABLE and json.loads(out) == {}


def test_cli_normal_path_is_unchanged(monkeypatch):
    monkeypatch.setattr(oah, "search_works", lambda *a, **k: [_paper("10.1/ok", "openalex")])
    out, err, code = _run_cli(monkeypatch, ["search", "q"])
    assert code == 0 and [p["doi"] for p in json.loads(out)] == ["10.1/ok"]
    assert "OpenAlex unavailable" not in err


# --------------------------------------------------------------------------
# Fallback tiers
# --------------------------------------------------------------------------


def test_reviews_and_journal_list_send_ss_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(ss_helper, "search", lambda q, **k: calls.append(k) or [_paper("10.1/x")])
    exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
    source_fallback.serve_list("reviews", {"topic": "t", "limit": 5}, exc)
    source_fallback.serve_list("journal-list",
                               {"query": "q", "limit": 5, "journals": ["A", "B"]}, exc)
    assert calls[0]["filters"] == {"publicationTypes": "Review"}
    assert calls[1]["filters"] == {"venue": "A,B"}


class _SSResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class _SSSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(headers or {}))
        return self.responses.pop(0)


def test_ss_refused_key_retries_keyless_and_says_so(capsys):
    sess = _SSSession([_SSResp(403), _SSResp(200, {"data": []}), _SSResp(200, {"data": []})])
    res = ss_helper._ss_get("u", {}, api_key="dead-key", session=sess)
    assert res.status_code == 200
    assert sess.calls[0] == {"x-api-key": "dead-key"} and sess.calls[1] == {}
    assert "rejected the configured API key" in capsys.readouterr().err
    ss_helper._ss_get("u", {}, api_key="dead-key", session=sess)
    assert sess.calls[2] == {}  # sticky: no second refusal round-trip


def test_ss_throttling_is_retried():
    sess = _SSSession([_SSResp(429), _SSResp(429, headers={"Retry-After": "1"}),
                       _SSResp(200, {"data": []})])
    assert ss_helper._ss_get("u", {}, api_key=None, session=sess).status_code == 200
    assert len(sess.calls) == 3


def test_ss_citation_network_maps_both_directions():
    rec = {"paperId": "p", "title": "Ref", "externalIds": {"DOI": "10.7/R"}}
    sess = _SSSession([
        _SSResp(200, {"data": [{"citedPaper": rec}, {"citedPaper": {"paperId": "x"}}]}),
        _SSResp(200, {"data": [{"citingPaper": dict(rec, title="Citing")}]}),
    ])
    net = ss_helper.citation_network("10.7/seed", session=sess)
    assert [p.title for p in net["references"]] == ["Ref"]
    assert [p.title for p in net["cited_by"]] == ["Citing"]


def test_crossref_record_mapping():
    rec = {
        "DOI": "10.1016/J.X.2020.1",
        "title": ["Trust &amp; robots"],
        "author": [{"given": "Ana", "family": "Li"}, {"name": "Consortium"}],
        "container-title": ["Child Development"],
        "ISSN": ["0009-3920"],
        "issued": {"date-parts": [[2021, 5]]},
        "abstract": "<jats:p>Children <jats:italic>trust</jats:italic> robots.</jats:p>",
        "is-referenced-by-count": 12,
        "type": "journal-article",
    }
    p = crossref_helper.record_to_entity(rec)
    assert p.doi == "10.1016/j.x.2020.1" and p.title == "Trust & robots"
    assert [a.name for a in p.authors] == ["Ana Li", "Consortium"]
    assert (p.year, p.venue, p.issn, p.type) == (2021, "Child Development", "0009-3920", "article")
    assert p.abstract == "Children trust robots."
    assert p.citation_count == 12 and p.sources == ["crossref"]


# --------------------------------------------------------------------------
# Headless agent path
# --------------------------------------------------------------------------


def test_agent_retrieve_switches_mid_run(monkeypatch):
    def fake(query, total_papers, sort, year_min=None, year_max=None, date_from=None, date_to=None, title_abstract_only=False):
        if sort == "cited_by_count:desc":
            return [_paper("10.1/a", "openalex")]
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED, reset_seconds=60)
        exc.partial = [_paper("10.1/b", "openalex")]
        raise exc

    monkeypatch.setattr(agent_search.openalex_helper, "search_top_n_pages", fake)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [_paper("10.2/ss")])
    results, warnings, fallback = agent_search._retrieve(
        "q", "openalex", year_min=None, year_max=None, per_strategy=10)
    assert [[p.doi for p in r] for r in results] == [["10.1/a"], ["10.1/b"], ["10.2/ss"]]
    assert fallback == {"reason": "budget_exhausted", "reset_seconds": 60,
                        "served_by": ["semantic_scholar"]}
    assert any("switched to semantic_scholar" in w for w in warnings)


# --------------------------------------------------------------------------
# Follow-ups from the Codex review
# --------------------------------------------------------------------------


def test_search_type_filter_is_never_dropped(monkeypatch):
    calls = []
    monkeypatch.setattr(ss_helper, "search", lambda q, **k: calls.append(k) or [])
    exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
    source_fallback.serve_list("search", {"query": "q", "limit": 5, "work_type": "review"}, exc)
    source_fallback.serve_list("search", {"query": "q", "limit": 5, "work_type": "article"}, exc)
    assert calls[0]["filters"] == {"publicationTypes": "Review"}
    assert calls[1]["filters"] == {"publicationTypes": "JournalArticle,Conference"}
    calls.clear()
    res = source_fallback.serve_list(
        "search", {"query": "q", "limit": 5, "work_type": "paratext"}, exc)
    assert calls == [] and not res.served and "no Semantic Scholar equivalent" in res.why_not


def test_citation_partial_is_reported_as_kept(monkeypatch):
    def down(*_a, **_k):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = {"doi": "10.9/s", "references": [_paper("10.9/r0", "openalex")],
                       "cited_by": []}
        raise exc

    monkeypatch.setattr(oah, "get_citation_network", down)
    monkeypatch.setattr(ss_helper, "citation_network",
                        lambda doi, **k: {"references": [], "cited_by": []})
    out, err, code = _run_cli(monkeypatch, ["citation-network", "W1"])
    assert code == 0 and len(json.loads(out)["references"]) == 1
    assert "kept the 1 OpenAlex records" in err and "empty result" not in err


def test_agent_retrieve_respects_fallback_off(monkeypatch):
    def down(query, total_papers, sort, year_min=None, year_max=None, date_from=None, date_to=None, title_abstract_only=False):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    monkeypatch.setattr(agent_search.openalex_helper, "search_top_n_pages", down)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: pytest.fail("fallback ran"))
    _r, warnings, fb = agent_search._retrieve("q", "openalex", year_min=None, year_max=None,
                                              per_strategy=5, allow_fallback=False)
    assert fb["served_by"] == [] and any("quota_fallback: false" in w for w in warnings)


def _agent_targets(monkeypatch, *, search_top_n_pages, impact):
    monkeypatch.setattr(agent_search.openalex_helper, "search_top_n_pages", search_top_n_pages)
    monkeypatch.setattr(agent_search.openalex_helper, "init_pyalex", lambda c: None)
    monkeypatch.setattr(agent_search.openalex_helper, "get_source_impact", impact)
    monkeypatch.setattr(agent_search.quota_guard, "evaluate",
                        lambda c, mode="probe", **k: type("Q", (), {
                            "ok": True, "should_switch": False,
                            "to_dict": lambda self: {"ok": True}})())
    monkeypatch.setattr(agent_search.journal_rank, "load", lambda **k: None)
    monkeypatch.setattr(source_fallback, "init", lambda c: None)


def _journal_paper(doi):
    p = _paper(doi, "openalex", cites=50)
    p.title = p.abstract = "alpha beta"
    p.issn = "1234-5678"
    return p


def test_agent_min_impact_is_skipped_not_emptying_when_openalex_is_down(monkeypatch):
    def impact(issn, raise_unavailable=False):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    _agent_targets(monkeypatch, impact=impact,
                   search_top_n_pages=lambda q, **k: [_journal_paper("10.1/a")])
    env = agent_search.run_agent_search("alpha beta", Config(), per_strategy=5,
                                        min_impact=1.0, now_year=2026)
    assert env["ok"] is True and len(env["data"]) == 1
    assert any("--min-impact not applied" in w for w in env["meta"]["warnings"])


def test_agent_switch_is_sticky_even_when_fallback_found_nothing(monkeypatch):
    calls = {"impact": 0}

    def fetch(query, total_papers, sort, year_min=None, year_max=None, date_from=None, date_to=None, title_abstract_only=False):
        if sort == "cited_by_count:desc":
            return [_journal_paper("10.1/a")]
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    def impact(issn, raise_unavailable=False):
        calls["impact"] += 1
        return {"two_year_mean_citedness": 3.0}

    _agent_targets(monkeypatch, search_top_n_pages=fetch, impact=impact)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [])
    monkeypatch.setattr(crossref_helper, "search_works", lambda *a, **k: [])
    env = agent_search.run_agent_search("alpha beta", Config(), per_strategy=5, now_year=2026)
    rl = env["meta"]["ratelimit"]
    assert env["ok"] is True and calls["impact"] == 0  # no OpenAlex call after the outage
    assert rl["fallback"]["reason"] == "budget_exhausted" and rl["switched_source"] is False


def test_agent_auto_without_ss_key_starts_on_openalex(monkeypatch):
    _agent_targets(monkeypatch, impact=lambda issn, **k: None,
                   search_top_n_pages=lambda q, **k: [_journal_paper("10.1/a")])
    monkeypatch.setattr(agent_search.quota_guard, "evaluate",
                        lambda c, mode="probe", **k: type("Q", (), {
                            "ok": True, "should_switch": True,
                            "to_dict": lambda self: {"ok": True}})())
    monkeypatch.setattr(ss_helper, "_api_key_from_config", lambda: None)
    cfg = Config()
    cfg.primary_source = "auto"
    env = agent_search.run_agent_search("alpha beta", cfg, per_strategy=5, now_year=2026)
    assert env["ok"] is True and env["meta"]["source_used"] == "openalex"
    assert any("no Semantic Scholar key" in w for w in env["meta"]["warnings"])


def test_verify_title_falls_back_to_crossref_or_says_unchecked(monkeypatch):
    def down(*_a, **_k):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    monkeypatch.setattr(agent_search.openalex_helper, "search_works", down)
    ref = {"title": "Training and plasticity of working memory"}
    hit = _paper("10.1016/j.tics.2010.05.002", "crossref")
    hit.title = "Training and plasticity of working memory"
    monkeypatch.setattr(crossref_helper, "search_works", lambda *a, **k: [hit])
    r = agent_search._verify_one_ref(ref, oa_ready=True, cr_ready=True, ss_ready=False)
    assert r["exists"] is True and r["matched_source"] == "crossref"

    monkeypatch.setattr(crossref_helper, "search_works", lambda *a, **k: [])
    r = agent_search._verify_one_ref(ref, oa_ready=True, cr_ready=True, ss_ready=False)
    assert r["exists"] is False and r["unchecked"] is True
    assert "NOT checked" in r["note"]


def test_malformed_crossref_record_is_skipped_not_fatal(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"message": {"items": [
                {"title": ["Bad"], "is-referenced-by-count": "n/a", "issued": "oops"},
                {"title": ["Good"], "DOI": "10.1/g"},
            ]}}

    class _Sess:
        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(crossref_helper, "_get_session", lambda: _Sess())
    got = crossref_helper.search_works("q", limit=5)
    assert [p.title for p in got] == ["Bad", "Good"] and got[0].citation_count == 0


def test_verify_crossref_failure_is_unchecked(monkeypatch):
    def down(*_a, **_k):
        raise OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)

    def broken(*_a, **_k):
        raise ValueError("parser blew up")

    monkeypatch.setattr(agent_search.openalex_helper, "search_works", down)
    monkeypatch.setattr(crossref_helper, "search_works", broken)
    r = agent_search._verify_one_ref({"title": "Some title"}, oa_ready=True, cr_ready=True,
                                     ss_ready=False)
    assert r["unchecked"] is True and r["exists"] is False


def test_fallback_off_envelope_reports_kept_partial(monkeypatch):
    def partial_then_down(*_a, **_k):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_paper("10.1/oa", "openalex")]
        raise exc

    monkeypatch.setattr(oah, "search_works", partial_then_down)
    cfg = Config()
    cfg.quota_fallback = False
    out, err, code = _run_cli(monkeypatch, ["--json-envelope", "search", "q"], config=cfg)
    env = json.loads(out)
    assert code == oah.EXIT_SOURCE_UNAVAILABLE and env["meta"]["count"] == 1
    assert env["meta"]["source"] == "openalex (partial)"
    assert env["meta"]["fallback"]["kept_openalex_partial"] == 1


# --------------------------------------------------------------------------
# Both OpenAlex and Semantic Scholar unavailable: behave as before the fallback
# --------------------------------------------------------------------------


def test_journal_list_still_continues_with_an_empty_list(monkeypatch):
    """Before the fallback, journal-list swallowed an OpenAlex failure and
    returned [] with exit 0; it must not start blocking runs."""
    monkeypatch.setattr(oah, "search_in_journal_list", _exhausted)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [])
    out, err, code = _run_cli(monkeypatch, ["journal-list", "q", "--preset", "UTD24"])
    assert code == 0 and json.loads(out) == []
    assert "as it did before" in err


def test_cut_off_crawl_is_not_passed_off_as_complete(monkeypatch):
    def partial_then_down(*_a, **_k):
        exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
        exc.partial = [_paper("10.1/oa", "openalex")]
        raise exc

    monkeypatch.setattr(oah, "search_top_n_pages", partial_then_down)
    monkeypatch.setattr(ss_helper, "search", lambda *a, **k: [])
    out, err, code = _run_cli(monkeypatch, ["deep", "q", "--n", "5"])
    assert code == oah.EXIT_SOURCE_UNAVAILABLE
    assert [p["doi"] for p in json.loads(out)] == ["10.1/oa"]
    assert "Printed only the 1 records OpenAlex returned before the cutoff" in err


def test_ss_failure_is_described(monkeypatch):
    monkeypatch.setattr(ss_helper, "_api_key", "dead-key")
    sess = _SSSession([_SSResp(403)] + [_SSResp(429)] * 8)
    ss_helper.search("q", total_per_strategy=5, session=sess)
    assert ss_helper.describe_failure() == (
        "configured key rejected; keyless requests throttled (HTTP 429)")


def test_reset_time_is_given_in_local_clock_time():
    text = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED, reset_seconds=3600).describe()
    assert "resets in 1h00m (about " in text and "local time)" in text


def test_deepening_outage_keeps_the_previous_complete_round():
    from tests.test_agent_rank import (
        CASRank, JournalRank, _FakeLookup, _FakeQuota, _cfg, _patched,
    )
    from tests.test_agent_rank import _paper as rank_paper

    table = {}
    for i in range(1, 9):
        issn = f"{i:04d}-000X"
        tier = 1 if i <= 2 else 3
        table[issn] = JournalRank(title=f"J{i}", issns=[issn],
                                  cas=CASRank(tier=tier, top=False, source_year=2025),
                                  matched_platforms=["cas"])
    lookup = _FakeLookup(table, loaded=("cas",))
    papers = [rank_paper(f"10.x/{i}", f"memory {i}", f"{i:04d}-000X", 100 - i) for i in range(1, 9)]

    def fake_search(query, total_papers=50, sort="cited_by_count:desc", year_min=None, year_max=None, date_from=None, date_to=None, title_abstract_only=False):
        if total_papers > 4:  # the deeper round hits the spent budget mid-crawl
            exc = OpenAlexUnavailable(openalex_guard.BUDGET_EXHAUSTED)
            exc.partial = papers[:1]
            raise exc
        return papers[:total_papers] if sort == "cited_by_count:desc" else []

    targets = [
        (agent_search.openalex_helper, "search_top_n_pages", fake_search),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.openalex_helper, "get_source_impact", lambda issn, **kw: None),
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (agent_search.journal_rank, "load", lambda **kw: lookup),
        (ss_helper, "search", lambda *a, **k: pytest.fail("no SS mixing mid-deepening")),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search("memory", _cfg(), per_strategy=4, rank_platform="cas",
                                            keep_tiers=["1"], deepen_target=5, now_year=2026)
    assert env["ok"] is True
    assert sorted(d["doi"] for d in env["data"]) == ["10.x/1", "10.x/2"]  # round 1 intact
    assert env["meta"]["ratelimit"]["deepening_stopped"] == "budget_exhausted"
    assert any("deepening stopped" in w for w in env["meta"]["warnings"])
