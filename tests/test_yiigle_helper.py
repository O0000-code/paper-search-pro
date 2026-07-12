"""Tests for scripts/yiigle_helper.py.

Core tests use MOCKED HTTP responses (fixture ``infos`` records) — they do NOT
hit the network, so the suite stays green offline / in CI. A single optional live
smoke test hits the real yiigle endpoint and SKIPS gracefully on any network
failure.

Field-mapping fixtures mirror the live record shape verified 2026-07-12:
artId / artTitle / artAbstract / artDoi / authorNames / journalCn / artPubYear.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m pytest tests/test_yiigle_helper.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import yiigle_helper  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — fake HTTP session + record builders
# ---------------------------------------------------------------------------


def _record(
    art_id=1530251,
    title="深度学习在医学中的应用进展",
    abstract="近年来，随着大数据的可用性提升……",
    doi="10.3760/cma.j.cn114452-20240626-00330",
    author_names=("施意", "史浩男", "叶翰嘉"),
    journal_cn="中华检验医学杂志",
    year=2025,
    keywords=("深度学习", "神经网络"),
    authors_raw=None,
):
    """Build one yiigle ``infos[]`` record with the live field names."""
    rec = {
        "artId": art_id,
        "artTitle": title,
        "artDropTitle": title,
        "artAbstract": abstract,
        "artDoi": doi,
        "authorNames": list(author_names) if author_names is not None else None,
        "authors": authors_raw,
        "journalCn": journal_cn,
        "journalEn": None,
        "artPubYear": year,
        "artPubDate": f"{year}-02-19T11:04:25.000+00:00" if year else None,
        "artificialKeywords": list(keywords) if keywords is not None else None,
        "keywords": None,
        "artUrl": f"https://rs.yiigle.com/cmaid/{art_id}",
    }
    return rec


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    """Fake yiigle endpoint. Serves preset pages; records every request so tests
    can assert the request body (isAggregations, query, page)."""

    def __init__(self, pages, code=200, status_code=200):
        # pages: list of infos-lists, one per page (1-indexed). code/status_code
        # let us simulate API-level and HTTP-level errors.
        self.pages = pages
        self.code = code
        self.status_code = status_code
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None, **kw):
        body = json.loads(data.decode("utf-8")) if isinstance(data, (bytes, bytearray)) else json.loads(data)
        self.calls.append({"url": url, "body": body, "headers": dict(headers or {})})
        page = int(body.get("page", 1))
        infos = self.pages[page - 1] if 1 <= page <= len(self.pages) else []
        payload = {"code": self.code, "message": "ok", "data": {"result": {"searchTotal": 999, "infos": infos}}}
        return _FakeResp(payload, self.status_code)


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def test_record_to_entity_full_mapping():
    """A fully-populated record maps every documented field correctly."""
    e = yiigle_helper._record_to_entity(_record())
    assert e.title == "深度学习在医学中的应用进展"
    assert e.abstract.startswith("近年来")
    assert e.doi == "10.3760/cma.j.cn114452-20240626-00330"  # lowercased, no prefix
    assert e.doi_url == "https://doi.org/10.3760/cma.j.cn114452-20240626-00330"
    assert [a.name for a in e.authors] == ["施意", "史浩男", "叶翰嘉"]
    assert e.venue == "中华检验医学杂志"
    assert e.year == 2025
    assert e.source_native_id == "yiigle:1530251"
    assert e.keywords == ["深度学习", "神经网络"]
    assert e.sources == ["yiigle"]
    # Compliance: no full-text / PDF URL emitted.
    assert e.pdf_url is None and e.is_oa is None


def test_doi_present_paper_id_is_doi():
    """When artDoi is present, DOI stays the primary key (paper_id == doi) and the
    native id is set as the fallback."""
    e = yiigle_helper._record_to_entity(_record(doi="10.3760/cma.J.CN114-XYZ"))
    assert e.doi == "10.3760/cma.j.cn114-xyz"  # normalised
    assert e.source_native_id == "yiigle:1530251"
    assert e.paper_id == "10.3760/cma.j.cn114-xyz"  # DOI wins over native id


def test_doi_absent_paper_id_is_native_id():
    """DOI-less record -> doi None, paper_id falls back to yiigle:<artId>."""
    e = yiigle_helper._record_to_entity(_record(art_id=1684441, doi=None))
    assert e.doi is None
    assert e.source_native_id == "yiigle:1684441"
    assert e.paper_id == "yiigle:1684441"


def test_authors_fallback_to_pipe_form():
    """When authorNames is absent, parse the 'name|CAID...' entries in authors."""
    rec = _record(author_names=None, authors_raw=["施意|CAID90876567", "史浩男|CAID90876568"])
    e = yiigle_helper._record_to_entity(rec)
    assert [a.name for a in e.authors] == ["施意", "史浩男"]


def test_year_fallback_to_pubdate():
    """artPubYear missing -> year parsed from the leading digits of artPubDate."""
    rec = _record(year=None)
    rec["artPubYear"] = None
    rec["artPubDate"] = "2023-08-01T00:00:00.000+00:00"
    e = yiigle_helper._record_to_entity(rec)
    assert e.year == 2023


# ---------------------------------------------------------------------------
# search() — request contract + pagination + filtering + degradation
# ---------------------------------------------------------------------------


def test_search_sends_is_aggregations_N_and_query():
    """Every request body must carry isAggregations == 'N' (the key trap) and the
    query in both queryString and searchText."""
    sess = _FakeSession(pages=[[_record()]])
    yiigle_helper.search("深度学习", n=5, session=sess)
    assert sess.calls, "no HTTP calls made"
    for c in sess.calls:
        assert c["body"]["isAggregations"] == "N", c["body"]
        assert c["body"]["queryString"] == "深度学习"
        assert c["body"]["searchText"] == "深度学习"
        assert c["body"]["searchType"] == "pt"
    # Content-Type header carries the charset the live endpoint expects.
    assert "charset=UTF-8" in sess.calls[0]["headers"].get("Content-Type", "")


def test_search_returns_entities_and_respects_n():
    """search() maps records to entities and never returns more than n."""
    page = [_record(art_id=i, doi=f"10.3760/x{i}") for i in range(10)]
    sess = _FakeSession(pages=[page])
    results = yiigle_helper.search("治疗", n=3, session=sess)
    assert len(results) == 3
    assert all(isinstance(r, UnifiedPaperEntity) for r in results)
    assert all(r.sources == ["yiigle"] for r in results)


def test_search_year_min_filters_and_drops_unknown():
    """year_min drops records below the threshold AND records with unknown year."""
    recs = [
        _record(art_id=1, doi="10.3760/a", year=2020),
        _record(art_id=2, doi="10.3760/b", year=2024),
        _record(art_id=3, doi="10.3760/c", year=2025),
    ]
    # add an unknown-year record
    unk = _record(art_id=4, doi="10.3760/d", year=None)
    unk["artPubYear"] = None
    unk["artPubDate"] = None
    recs.append(unk)
    sess = _FakeSession(pages=[recs])
    results = yiigle_helper.search("q", n=20, year_min=2024, session=sess)
    years = sorted(r.year for r in results)
    assert years == [2024, 2025]
    assert all(r.year is not None for r in results)


def test_search_paginates_across_pages():
    """When page 1 is full (== _PAGE_SIZE), search() fetches page 2 to reach n."""
    full = [_record(art_id=i, doi=f"10.3760/p1_{i}") for i in range(yiigle_helper._PAGE_SIZE)]
    page2 = [_record(art_id=1000 + i, doi=f"10.3760/p2_{i}") for i in range(5)]
    sess = _FakeSession(pages=[full, page2])
    results = yiigle_helper.search("q", n=yiigle_helper._PAGE_SIZE + 3, session=sess)
    assert len(results) == yiigle_helper._PAGE_SIZE + 3
    # Two pages requested.
    pages_requested = sorted(c["body"]["page"] for c in sess.calls)
    assert pages_requested == [1, 2]


def test_search_empty_result_returns_empty():
    """Empty infos -> [] (no crash)."""
    sess = _FakeSession(pages=[[]])
    assert yiigle_helper.search("nonsense", n=10, session=sess) == []


def test_search_http_error_degrades_to_empty():
    """Non-200 HTTP -> [] rather than raising."""
    sess = _FakeSession(pages=[[_record()]], status_code=500)
    assert yiigle_helper.search("q", n=10, session=sess) == []


def test_search_api_error_code_degrades_to_empty():
    """API-level code != 200 -> [] rather than raising."""
    sess = _FakeSession(pages=[[_record()]], code=400)
    assert yiigle_helper.search("q", n=10, session=sess) == []


def test_search_network_exception_degrades_to_empty():
    """A raising session must not crash search()."""

    class _Boom:
        def post(self, *a, **kw):
            raise RuntimeError("network down")

    assert yiigle_helper.search("q", n=10, session=_Boom()) == []


def test_search_blank_query_returns_empty_without_network():
    """Blank query short-circuits — no HTTP call at all."""
    sess = _FakeSession(pages=[[_record()]])
    assert yiigle_helper.search("   ", n=5, session=sess) == []
    assert sess.calls == []


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_entity_to_dict_is_full_and_json_safe():
    """The serialiser emits the broad OpenAlex/SS-compatible field set with authors
    flattened, and is JSON-safe (ensure it round-trips)."""
    e = yiigle_helper._record_to_entity(_record())
    d = yiigle_helper._entity_to_dict(e)
    json.dumps(d, ensure_ascii=False)  # must not raise
    assert d["sources"] == ["yiigle"]
    assert d["source_native_id"] == "yiigle:1530251"
    assert isinstance(d["authors"], list) and d["authors"][0]["name"] == "施意"
    # Broad field set present (same shape as openalex/ss output).
    assert "venue" in d and "issn" in d and "is_oa" in d and "keywords" in d and "doi_url" in d


# ---------------------------------------------------------------------------
# type consistency (#23)
# ---------------------------------------------------------------------------


def test_type_is_article():
    """type is a stable 'article' (was previously left None)."""
    e = yiigle_helper._record_to_entity(_record())
    assert e.type == "article"


# ---------------------------------------------------------------------------
# de-dup by artId (#15) — intra-page and cross-page repeats collapse to one
# ---------------------------------------------------------------------------


def test_search_dedup_by_art_id_intra_page():
    dup = _record(art_id=555, doi="10.3760/dup")
    dup2 = _record(art_id=555, doi="10.3760/dup")  # same artId -> dropped
    other = _record(art_id=556, doi="10.3760/other")
    sess = _FakeSession(pages=[[dup, dup2, other]])
    out = yiigle_helper.search("q", n=10, session=sess)
    assert [e.source_native_id for e in out] == ["yiigle:555", "yiigle:556"]


def test_search_dedup_by_art_id_cross_page():
    page1 = [_record(art_id=i, doi=f"10.3760/p1_{i}") for i in range(yiigle_helper._PAGE_SIZE)]
    # page2 repeats artId 5 (a cross-page dup) plus a fresh artId 9999.
    page2 = [_record(art_id=5, doi="10.3760/p1_5"), _record(art_id=9999, doi="10.3760/new")]
    sess = _FakeSession(pages=[page1, page2])
    out = yiigle_helper.search("q", n=yiigle_helper._PAGE_SIZE + 5, session=sess)
    ids = [e.source_native_id for e in out]
    assert ids.count("yiigle:5") == 1          # cross-page repeat dropped
    assert "yiigle:9999" in ids                # fresh record still added
    assert len(out) == yiigle_helper._PAGE_SIZE + 1


# ---------------------------------------------------------------------------
# legal-JSON wrong-shape guards (#5) — never raise, degrade to empty
# ---------------------------------------------------------------------------


def _resp_session(payload):
    """A minimal session whose single response body is exactly ``payload``."""

    class _S:
        def post(self, url, data=None, headers=None, timeout=None, **kw):
            return _FakeResp(payload)

    return _S()


def test_search_data_is_list_does_not_crash():
    # {"code":200,"data":[...]} — `data` is a list; .get() would raise pre-fix.
    sess = _resp_session({"code": 200, "data": [{"x": 1}]})
    assert yiigle_helper.search("q", n=5, session=sess) == []


def test_search_result_is_list_does_not_crash():
    sess = _resp_session({"code": 200, "data": {"result": [{"x": 1}]}})
    assert yiigle_helper.search("q", n=5, session=sess) == []


def test_search_infos_is_dict_does_not_crash():
    sess = _resp_session({"code": 200, "data": {"result": {"infos": {"k": "v"}}}})
    assert yiigle_helper.search("q", n=5, session=sess) == []


def test_search_non_dict_record_skipped():
    sess = _FakeSession(pages=[["oops", _record(art_id=7, doi="10.3760/ok")]])
    out = yiigle_helper.search("q", n=5, session=sess)
    assert [e.source_native_id for e in out] == ["yiigle:7"]


# ---------------------------------------------------------------------------
# Optional live smoke — skips on any network failure.
# ---------------------------------------------------------------------------


def test_search_live_smoke():
    """Real yiigle search for a high-signal Chinese medical query. Tolerant: if the
    endpoint is unreachable / rate-limited (-> []), skip content assertions so the
    suite stays green offline."""
    try:
        results = yiigle_helper.search("基因编辑", n=3)
    except Exception as exc:  # never let a live flake fail the gate
        print(f"SKIP live_smoke (live error: {type(exc).__name__})")
        return
    if not results:
        print("SKIP live_smoke (no results — likely offline / rate-limited)")
        return
    top = results[0]
    assert top.title, "top result has no title"
    assert top.sources == ["yiigle"]
    # yiigle records are native-Chinese: title should contain CJK.
    assert any("一" <= ch <= "鿿" for ch in top.title), top.title
    # native id is always present; DOI is present for most 中华医学会 records.
    assert top.source_native_id and top.source_native_id.startswith("yiigle:")
    print(f"OK  live_smoke — {len(results)} records, top='{top.title[:30]}' doi={top.doi}")


if __name__ == "__main__":
    import subprocess

    raise SystemExit(
        subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"])
    )
