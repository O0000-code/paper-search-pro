"""Offline tests: an end year given by the caller reaches every retrieval call.

Covers the OpenAlex CLI entry points used by the human path (``deep``,
``double-sort``, ``reviews``) and the PubMed search helpers. No network: the
backends are stubbed and the query objects are recorded instead of executed.
"""

from __future__ import annotations

import contextlib
import io
import sys

import scripts.openalex_helper as oah
import scripts.pubmed_helper as pmh


class _RecordingWorks:
    """Stands in for pyalex.Works: records filters, returns no results."""

    filters: list = []

    def __init__(self):
        type(self).filters = []

    def search(self, *_a, **_k):
        return self

    def sort(self, **_k):
        return self

    def filter(self, **kw):
        type(self).filters.append(kw)
        return self

    def get(self, **_k):
        return []


def _run_cli(monkeypatch, argv, **stubs):
    monkeypatch.setattr(oah, "init_pyalex", lambda cfg: None)
    for name, fn in stubs.items():
        monkeypatch.setattr(oah, name, fn)
    monkeypatch.setattr(sys, "argv", ["openalex_helper", *argv])
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        oah._main_cli()


def test_double_sort_search_passes_year_bounds_to_every_strategy(monkeypatch):
    calls = []

    def fake(query, total_papers=100, sort="", year_min=None, year_max=None):
        calls.append((sort, year_min, year_max))
        return []

    monkeypatch.setattr(oah, "search_top_n_pages", fake)
    oah.double_sort_search("q", year_min=2015, year_max=2020, total_per_strategy=5)

    assert len(calls) == 3
    assert all(c[1:] == (2015, 2020) for c in calls)


def _year_filters():
    return [f["publication_year"] for f in _RecordingWorks.filters if "publication_year" in f]


def test_year_filter_values():
    assert oah._year_filter(2015, 2020) == "2015-2020"
    assert oah._year_filter(2015, None) == ">2014"
    assert oah._year_filter(None, 2020) == "<2021"
    assert oah._year_filter(None, None) is None


def test_both_bounds_become_one_range_filter(monkeypatch):
    # Two filter() calls on the same key are sent as ">2014+<2021", which the
    # OpenAlex API rejects. Every entry point must send a single range value.
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    for call in (
        lambda: oah.search_works("q", year_min=2015, year_max=2020, limit=5),
        lambda: oah.search_top_n_pages("q", total_papers=5, year_min=2015, year_max=2020),
        lambda: oah.find_review_articles("q", limit=5, year_min=2015, year_max=2020),
    ):
        call()
        assert _year_filters() == ["2015-2020"]


def test_single_bound_filters_unchanged(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.search_top_n_pages("q", total_papers=5, year_min=2015)
    assert _year_filters() == [">2014"]
    oah.find_review_articles("q", limit=5, year_max=2020)
    assert _year_filters() == ["<2021"]


def test_find_review_articles_without_bounds_adds_no_year_filter(monkeypatch):
    monkeypatch.setattr(oah, "Works", _RecordingWorks)
    oah.find_review_articles("q", limit=5)

    assert all("publication_year" not in f for f in _RecordingWorks.filters)


def test_cli_deep_forwards_year_max(monkeypatch):
    seen = {}

    def fake(query, total_papers=100, sort="", year_min=None, year_max=None):
        seen.update(year_min=year_min, year_max=year_max)
        return []

    _run_cli(monkeypatch, ["deep", "q", "--year-min", "2015", "--year-max", "2020"],
             search_top_n_pages=fake)
    assert seen == {"year_min": 2015, "year_max": 2020}


def test_cli_double_sort_forwards_year_max(monkeypatch):
    seen = {}

    def fake(query, year_min=None, total_per_strategy=50, year_max=None):
        seen.update(year_min=year_min, year_max=year_max)
        return []

    _run_cli(monkeypatch, ["double-sort", "q", "--year-min", "2015", "--year-max", "2020"],
             double_sort_search=fake)
    assert seen == {"year_min": 2015, "year_max": 2020}


def test_cli_reviews_forwards_year_max(monkeypatch):
    seen = {}

    def fake(topic, limit=10, year_min=None, year_max=None):
        seen.update(year_min=year_min, year_max=year_max)
        return []

    _run_cli(monkeypatch, ["reviews", "q", "--year-max", "2020"],
             find_review_articles=fake)
    assert seen == {"year_min": None, "year_max": 2020}


def test_pubmed_date_clause():
    # A start year alone keeps the exact pre-existing clause.
    assert pmh._pdat_clause(2020, None) == " AND (2020:3000[dp])"
    assert pmh._pdat_clause(None, 2019) == " AND (1000:2019[dp])"
    assert pmh._pdat_clause(2015, 2020) == " AND (2015:2020[dp])"
    assert pmh._pdat_clause(None, None) == ""


retmaxes: list = []


def _capture_pubmed_terms(monkeypatch):
    terms = []
    retmaxes.clear()

    def fake_esearch(db, term, retmax):
        terms.append(term)
        retmaxes.append(retmax)
        return io.StringIO()

    monkeypatch.setattr(pmh, "_initialized", True)
    monkeypatch.setattr(pmh.time, "sleep", lambda _s: None)
    monkeypatch.setattr(pmh.Entrez, "esearch", fake_esearch)
    monkeypatch.setattr(pmh.Entrez, "read", lambda _h: {"IdList": []})
    return terms


def test_pubmed_search_keyword_applies_end_year(monkeypatch):
    terms = _capture_pubmed_terms(monkeypatch)
    pmh.search_keyword("metformin", year_min=2015, year_max=2020, limit=3)
    pmh.search_keyword("metformin", year_min=2015, limit=3)

    assert terms == [
        "metformin AND (2015:2020[dp])",
        "metformin AND (2015:3000[dp])",
    ]
    # Over-fetch only when an end year may drop boundary records.
    assert retmaxes == [6, 3]


def test_pubmed_search_by_mesh_applies_end_year(monkeypatch):
    terms = _capture_pubmed_terms(monkeypatch)
    pmh.search_by_mesh("Metformin", year_max=2019, limit=3)

    assert terms == ['"Metformin"[MeSH Terms] AND (1000:2019[dp])']


def test_pubmed_drops_records_printed_after_end_year():
    records = [{"year": 2016}, {"year": 2017}, {"year": None}]
    assert pmh._drop_after(records, 2016) == [{"year": 2016}, {"year": None}]
    assert pmh._drop_after(records, None) == records


def _record_with_pub_date(pub_date):
    return {
        "MedlineCitation": {
            "PMID": "1",
            "Article": {"ArticleTitle": "t", "Journal": {"JournalIssue": {"PubDate": pub_date}}},
        },
        "PubmedData": {"ArticleIdList": []},
    }


def test_pubmed_year_parsed_from_medline_date():
    # Without a parsed year these records slipped past the end-year filter.
    parse = pmh._parse_pmid_record
    assert parse(_record_with_pub_date({"MedlineDate": "2021 Jan-Feb"}))["year"] == 2021
    assert parse(_record_with_pub_date({"MedlineDate": "1998 Dec-1999 Jan"}))["year"] == 1998
    assert parse(_record_with_pub_date({"Year": "2016", "Month": "Mar"}))["year"] == 2016
    assert parse(_record_with_pub_date({"MedlineDate": "Spring"}))["year"] is None
