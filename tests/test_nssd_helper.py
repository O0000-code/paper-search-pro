"""Tests for scripts/nssd_helper.py.

Field-mapping / native-id / 集刊-ISBN-discrimination / author-parsing / error-
handling tests run against FIXTURE HTTP responses (a fake requests-like session)
— no network. One optional live smoke test hits the real ncpssd.cn endpoint and
SKIPS (never fails) on any network error, so the suite is green offline.

Fixtures are trimmed copies of REAL rows returned by the live endpoint on
2026-07-12 (verified during the build), so the mappings under test reflect the
production response shape.

Run from skill root:
    cd <skill> && python3 -m pytest tests/test_nssd_helper.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import nssd_helper  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Fake requests-like session (no network)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    """Mimics ``requests`` for ``.post(url, data=, headers=, timeout=)``.

    ``pages`` is a list of payloads returned in order, one per POST. A payload
    may be:
      * a dict                 -> returned as a 200 JSON body
      * a (dict, status) tuple -> returned with that status code
      * an Exception instance  -> the ``.json()`` call raises it
    If ``raise_on_post`` is set, ``.post`` itself raises (network error).
    """

    def __init__(self, pages=None, raise_on_post=None):
        self._pages = list(pages or [])
        self._raise = raise_on_post
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        if self._raise is not None:
            raise self._raise
        if self._pages:
            item = self._pages.pop(0)
        else:
            item = _ok([])
        if isinstance(item, tuple):
            body, status = item
            return _FakeResponse(body, status)
        return _FakeResponse(item)


def _ok(rows, total=None):
    return {
        "result": True,
        "code": 200,
        "data": {
            "total": total if total is not None else len(rows),
            "rows": rows,
        },
    }


# ---------------------------------------------------------------------------
# Fixture rows (trimmed real rows, 2026-07-12)
# ---------------------------------------------------------------------------

ROW_JOURNAL = {
    "id": "XLKXJZ2026001008",
    "data_id": "XLKXJZ2026001008",
    "title": "情绪调节的认知神经机制",
    "creator": "高可翔[1];汤煜尧[1];张岳瑶[1];张丹丹[1]",
    "creator_first": None,
    "cbw_name": "心理科学进展",
    "issn": "1671-3710",
    "isbn": None,
    "remark": "本文综述了情绪调节的认知神经机制及其研究进展。",
    "remark_en": "This paper reviews ...",
    "years": "2026",
    "range": "3; BDHX2008; CSSCI2021_2022; NSSD; PUBMED",
    "doi": None,
    "type": "中文期刊文章",
}

# 集刊文章 — the ISSN slot actually holds an ISBN (must NOT become entity.issn).
ROW_JIKAN_ISBN = {
    "id": "1002321027",
    "title": "海派经济学的理论贡献",
    "creator": " ",  # 集刊 rows frequently have a whitespace-only creator
    "cbw_name": "海派经济学",
    "issn": "978-7-5642-1400-5",  # ISBN-13 sitting in the issn field
    "isbn": None,
    "remark": "……",
    "years": "2012",
    "range": "1;CSSCI_C2012_2013;CSSCI_C2014_2016;CSSCI_C2017_2018;NSSD;RWSKHX;",
    "doi": None,
    "type": "集刊文章",
}

# 集刊文章 — ISBN-10 with hyphens in the issn slot.
ROW_JIKAN_ISBN10 = {
    "id": "1002321709",
    "title": "海派经济学早期文献",
    "creator": " ",
    "cbw_name": "海派经济学",
    "issn": "7-81049-896-7",  # ISBN-10 — must be rejected
    "isbn": None,
    "remark": "……",
    "years": "2003",
    "range": "1;CSSCI_C2017_2018;NSSD;RWSKHX;",
    "doi": None,
    "type": "集刊文章",
}

# Whitespace-separated CJK author names (a real minority form).
ROW_SPACE_AUTHORS = {
    "id": "36188261",
    "title": "情绪调节策略研究",
    "creator": "李艳杰 许远理 白鹭",
    "cbw_name": "濮阳职业技术学院学报",
    "issn": "1672-9161",
    "remark": "……",
    "years": "2010",
    "range": "普通刊",
    "doi": None,
    "type": "中文期刊文章",
}

# Two authors separated by ';' with no affiliation markers, and a real DOI.
ROW_WITH_DOI = {
    "id": "CASS1034347637",
    "title": "Emotion regulation review",
    "creator": "孙漫丽;张颖",
    "cbw_name": "Advances in Psychology",
    "issn": "2160-7273",
    "remark": "abstract text here",
    "years": "2021",
    "range": None,
    "doi": "10.12677/AP.2021.114099",
    "type": "外文期刊文章",
}

# ISSN with a check-digit X — must be accepted.
ROW_ISSN_X = {
    "id": "HBDESFXYXB2009010034",
    "title": "情绪与教育",
    "creator": "郑容[1]",
    "cbw_name": "湖北第二师范学院学报",
    "issn": "1674-344X",
    "remark": "……",
    "years": "2009",
    "range": "0; NSSD",
    "doi": None,
    "type": "中文期刊文章",
}


# ---------------------------------------------------------------------------
# _row_to_entity — field mapping
# ---------------------------------------------------------------------------


def test_journal_field_mapping():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)
    assert e.title == "情绪调节的认知神经机制"
    assert e.venue == "心理科学进展"
    assert e.issn == "1671-3710"
    assert e.year == 2026
    assert e.abstract == "本文综述了情绪调节的认知神经机制及其研究进展。"
    assert e.source_native_id == "nssd:XLKXJZ2026001008"
    assert e.sources == ["nssd"]
    assert e.type == "article"
    assert e.doi is None


def test_author_affiliation_markers_stripped():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)
    names = [a.name for a in e.authors]
    assert names == ["高可翔", "汤煜尧", "张岳瑶", "张丹丹"]
    # No affiliation bracket leaked into any name.
    assert all("[" not in n and "]" not in n for n in names)


def test_semicolon_authors_no_markers():
    e = nssd_helper._row_to_entity(ROW_WITH_DOI)
    assert [a.name for a in e.authors] == ["孙漫丽", "张颖"]


def test_space_separated_cjk_authors_split():
    e = nssd_helper._row_to_entity(ROW_SPACE_AUTHORS)
    assert [a.name for a in e.authors] == ["李艳杰", "许远理", "白鹭"]


def test_whitespace_only_creator_yields_no_authors():
    e = nssd_helper._row_to_entity(ROW_JIKAN_ISBN)
    assert e.authors == []


def test_foreign_name_with_space_stays_single_author():
    # Guard: a single non-CJK name containing a space must NOT be over-split.
    authors = nssd_helper._parse_authors("John Smith")
    assert [a.name for a in authors] == ["John Smith"]


# ---------------------------------------------------------------------------
# ISSN / ISBN discrimination
# ---------------------------------------------------------------------------


def test_jikan_isbn13_not_treated_as_issn():
    e = nssd_helper._row_to_entity(ROW_JIKAN_ISBN)
    assert e.issn is None  # "978-7-5642-1400-5" is an ISBN, not an ISSN
    assert e.source_native_id == "nssd:1002321027"


def test_jikan_isbn10_not_treated_as_issn():
    e = nssd_helper._row_to_entity(ROW_JIKAN_ISBN10)
    assert e.issn is None  # "7-81049-896-7"


def test_valid_issn_with_check_digit_x_accepted():
    e = nssd_helper._row_to_entity(ROW_ISSN_X)
    assert e.issn == "1674-344X"


def test_clean_issn_helper():
    assert nssd_helper._clean_issn("1671-3710") == "1671-3710"
    assert nssd_helper._clean_issn("1674-344X") == "1674-344X"
    assert nssd_helper._clean_issn("978-7-5642-1400-5") is None
    assert nssd_helper._clean_issn("7-81049-896-7") is None
    assert nssd_helper._clean_issn(None) is None
    assert nssd_helper._clean_issn("") is None


# ---------------------------------------------------------------------------
# native-id / paper_id / doi
# ---------------------------------------------------------------------------


def test_native_id_drives_paper_id_when_no_doi():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)
    assert e.doi is None
    assert e.paper_id == "nssd:XLKXJZ2026001008"


def test_doi_populated_and_lifts_paper_id():
    e = nssd_helper._row_to_entity(ROW_WITH_DOI)
    assert e.doi == "10.12677/ap.2021.114099"  # lowercased
    assert e.doi_url == "https://doi.org/10.12677/ap.2021.114099"
    assert e.paper_id == "10.12677/ap.2021.114099"  # DOI outranks native id
    assert "nssd" in e.sources


# ---------------------------------------------------------------------------
# range -> keywords quality signal
# ---------------------------------------------------------------------------


def test_range_stored_as_namespaced_keyword():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)
    tokens = [k for k in e.keywords if k.startswith("nssd_range:")]
    assert tokens == ["nssd_range:3; BDHX2008; CSSCI2021_2022; NSSD; PUBMED"]


def test_missing_range_yields_no_keyword():
    e = nssd_helper._row_to_entity(ROW_WITH_DOI)  # range is None
    # No range signal -> no nssd_range: token. (The record may still carry a
    # nssd_type: annotation, asserted separately.)
    assert not any(k.startswith("nssd_range:") for k in e.keywords)


# ---------------------------------------------------------------------------
# year parsing
# ---------------------------------------------------------------------------


def test_parse_year():
    assert nssd_helper._parse_year("2021") == 2021
    assert nssd_helper._parse_year("2026") == 2026
    assert nssd_helper._parse_year("") is None
    assert nssd_helper._parse_year(None) is None
    assert nssd_helper._parse_year("n/a") is None


# ---------------------------------------------------------------------------
# search() — full path over a fake session
# ---------------------------------------------------------------------------


def test_search_returns_entities():
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL, ROW_WITH_DOI, ROW_ISSN_X])])
    out = nssd_helper.search("情绪调节", n=10, session=sess)
    assert len(out) == 3
    assert all(isinstance(e, UnifiedPaperEntity) for e in out)
    assert out[0].source_native_id == "nssd:XLKXJZ2026001008"
    # The PQ was built and posted to the right endpoint.
    assert sess.calls and sess.calls[0]["url"] == nssd_helper.SEARCH_URL
    assert "IKTE" in sess.calls[0]["data"]


def test_search_respects_n():
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL, ROW_WITH_DOI, ROW_ISSN_X])])
    out = nssd_helper.search("情绪调节", n=2, session=sess)
    assert len(out) == 2


def test_search_dedups_repeated_native_id():
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL, ROW_JOURNAL, ROW_WITH_DOI])])
    out = nssd_helper.search("x", n=10, session=sess)
    ids = [e.source_native_id for e in out]
    assert ids.count("nssd:XLKXJZ2026001008") == 1
    assert len(out) == 2


def test_search_year_min_filter():
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL, ROW_WITH_DOI, ROW_ISSN_X])])
    # ROW_JOURNAL=2026, ROW_WITH_DOI=2021, ROW_ISSN_X=2009
    out = nssd_helper.search("x", n=10, year_min=2020, session=sess)
    years = sorted(e.year for e in out)
    assert years == [2021, 2026]


def test_search_empty_rows():
    sess = _FakeSession(pages=[_ok([])])
    assert nssd_helper.search("nothing", n=5, session=sess) == []


def test_search_empty_query():
    # No network call should even be attempted for an empty query.
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    assert nssd_helper.search("   ", n=5, session=sess) == []
    assert sess.calls == []


# ---------------------------------------------------------------------------
# graceful degradation
# ---------------------------------------------------------------------------


def test_search_network_error_returns_empty():
    sess = _FakeSession(raise_on_post=ConnectionError("boom"))
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_http_error_returns_empty():
    sess = _FakeSession(pages=[(_ok([ROW_JOURNAL]), 500)])
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_bad_json_returns_empty():
    sess = _FakeSession(pages=[ValueError("not json")])
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_result_false_returns_empty():
    sess = _FakeSession(pages=[{"result": False, "code": 500, "data": {}}])
    assert nssd_helper.search("x", n=5, session=sess) == []


# ---------------------------------------------------------------------------
# output shape parity with ss_helper --search
# ---------------------------------------------------------------------------


def test_to_dict_shape():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)
    d = nssd_helper._to_dict(e)
    # authors flattened to list-of-dicts (same as openalex/ss serialization)
    assert isinstance(d["authors"], list)
    assert d["authors"][0]["name"] == "高可翔"
    # the identifiers / provenance federated fusion keys on are present
    for key in ("doi", "source_native_id", "title", "venue", "issn", "year", "sources", "keywords"):
        assert key in d
    assert d["sources"] == ["nssd"]
    assert d["source_native_id"] == "nssd:XLKXJZ2026001008"


# ---------------------------------------------------------------------------
# subject -> keywords (#16)
# ---------------------------------------------------------------------------

ROW_WITH_SUBJECT_SEMI = {
    "id": "SUBJ1",
    "title": "乡村振兴研究",
    "creator": "王五[1]",
    "cbw_name": "农业经济",
    "issn": "1000-0000",
    "years": "2023",
    "subject": "乡村振兴;乡村振兴战略",  # ';'-delimited (verified live form)
    "range": None,
    "doi": None,
    "type": "中文期刊文章",
}

ROW_WITH_SUBJECT_SPACE = {
    "id": "SUBJ2",
    "title": "情绪调节教学",
    "creator": "赵六[1]",
    "cbw_name": "体育学刊",
    "issn": "1006-7116",
    "years": "2024",
    "subject": "情绪调节 情绪调节教学模式 体育教学",  # whitespace-delimited (verified live)
    "range": None,
    "doi": None,
    "type": "中文期刊文章",
}


def test_parse_subject_helper():
    f = nssd_helper._parse_subject
    assert f("乡村振兴;乡村振兴战略") == ["乡村振兴", "乡村振兴战略"]
    assert f("依恋；情绪调节；模型整合") == ["依恋", "情绪调节", "模型整合"]  # full-width ；
    assert f("情绪调节 体育教学模式 体育教学") == ["情绪调节", "体育教学模式", "体育教学"]
    assert f("单一主题") == ["单一主题"]
    assert f("a;a;b") == ["a", "b"]  # de-duped, order-preserved
    assert f("") == []
    assert f(None) == []


def test_subject_semicolon_merged_into_keywords():
    e = nssd_helper._row_to_entity(ROW_WITH_SUBJECT_SEMI)
    assert "乡村振兴" in e.keywords
    assert "乡村振兴战略" in e.keywords


def test_subject_space_delimited_merged_into_keywords():
    e = nssd_helper._row_to_entity(ROW_WITH_SUBJECT_SPACE)
    assert "情绪调节" in e.keywords
    assert "情绪调节教学模式" in e.keywords
    assert "体育教学" in e.keywords


# ---------------------------------------------------------------------------
# type mapping + raw-type annotation (#16)
# ---------------------------------------------------------------------------


def test_type_is_article_and_raw_type_annotated():
    e = nssd_helper._row_to_entity(ROW_JOURNAL)  # type "中文期刊文章"
    assert e.type == "article"
    assert "nssd_type:中文期刊文章" in e.keywords


def test_foreign_type_annotated_not_dropped():
    # A 外文期刊文章 row is annotated (so a zh-space router can filter it) but the
    # entity is still produced — live data shows Chinese-content 外文期刊文章, so we
    # never hard-drop it here.
    e = nssd_helper._row_to_entity(ROW_WITH_DOI)  # type "外文期刊文章"
    assert e.type == "article"
    assert "nssd_type:外文期刊文章" in e.keywords


def test_missing_type_yields_no_type_annotation():
    row = dict(ROW_JOURNAL)
    row.pop("type", None)
    e = nssd_helper._row_to_entity(row)
    assert not any(k.startswith("nssd_type:") for k in e.keywords)


# ---------------------------------------------------------------------------
# DOI URL-prefix strip (#15) — align with yiigle _normalize_doi
# ---------------------------------------------------------------------------

ROW_DOI_URL = {
    "id": "DOIURL1",
    "title": "带URL前缀的DOI",
    "creator": "钱七",
    "cbw_name": "某刊",
    "issn": "1234-5678",
    "years": "2022",
    "doi": "https://doi.org/10.1234/ABC.2022",
    "type": "中文期刊文章",
}


def test_normalize_doi_helper():
    f = nssd_helper._normalize_doi
    assert f("10.1234/ABC") == "10.1234/abc"
    assert f("https://doi.org/10.1/x") == "10.1/x"
    assert f("http://doi.org/10.1/x") == "10.1/x"
    assert f("doi:10.1/x") == "10.1/x"
    assert f("DOI.ORG/10.1/X") == "10.1/x"
    assert f(None) is None
    assert f("") is None


def test_doi_url_prefix_stripped():
    e = nssd_helper._row_to_entity(ROW_DOI_URL)
    assert e.doi == "10.1234/abc.2022"  # URL prefix stripped + lowercased
    assert e.doi_url == "https://doi.org/10.1234/abc.2022"
    assert e.paper_id == "10.1234/abc.2022"  # DOI outranks native id


# ---------------------------------------------------------------------------
# year filter BEFORE seen-marking (#15)
# ---------------------------------------------------------------------------

# Two id-less / doi-less rows sharing a title fallback key; one below year_min,
# one above. Exercises the "filter year, THEN mark seen" ordering.
ROW_NOID_OLD = {
    "title": "同题记录",
    "creator": "甲",
    "cbw_name": "某刊",
    "years": "2018",
    "doi": None,
}
ROW_NOID_NEW = {
    "title": "同题记录",
    "creator": "乙",
    "cbw_name": "某刊",
    "years": "2022",
    "doi": None,
}


def test_year_filter_runs_before_seen_marking():
    sess = _FakeSession(pages=[_ok([ROW_NOID_OLD, ROW_NOID_NEW])])
    out = nssd_helper.search("x", n=10, year_min=2020, session=sess)
    # The 2018 copy is year-filtered; it must NOT have marked the shared title key
    # as seen, so the valid 2022 copy still comes through.
    assert [e.year for e in out] == [2022]


# ---------------------------------------------------------------------------
# legal-JSON wrong-shape guards (#5) — never raise, degrade to empty
# ---------------------------------------------------------------------------


def test_search_data_is_list_does_not_crash():
    # Legal JSON, but `data` is a non-empty list instead of the {"rows":[...]} object.
    sess = _FakeSession(pages=[{"result": True, "code": 200, "data": [{"x": 1}]}])
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_payload_is_list_does_not_crash():
    # Legal JSON, but the whole payload is a list.
    sess = _FakeSession(pages=[[{"x": 1}]])
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_rows_is_dict_does_not_crash():
    # `data.rows` arrives as a dict instead of a list.
    sess = _FakeSession(
        pages=[{"result": True, "code": 200, "data": {"rows": {"k": "v"}, "total": 1}}]
    )
    assert nssd_helper.search("x", n=5, session=sess) == []


def test_search_non_dict_row_skipped():
    # A bare-string row must be skipped, not crash the run.
    sess = _FakeSession(pages=[_ok(["oops", ROW_JOURNAL])])
    out = nssd_helper.search("x", n=5, session=sess)
    assert [e.source_native_id for e in out] == ["nssd:XLKXJZ2026001008"]


# ---------------------------------------------------------------------------
# optional live smoke test (skips on any network failure — never fails offline)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_smoke():
    try:
        results = nssd_helper.search("乡村振兴", n=3)
    except Exception as exc:  # pragma: no cover - defensive; search shouldn't raise
        pytest.skip(f"NSSD live search raised: {exc}")
    if not results:
        pytest.skip("NSSD live search returned no results (offline / endpoint down)")
    assert isinstance(results, list)
    e = results[0]
    assert isinstance(e, UnifiedPaperEntity)
    assert e.title
    assert e.source_native_id and e.source_native_id.startswith("nssd:")
    assert e.sources == ["nssd"]


# ===========================================================================
# P2-5: multi-concept block PQ + whitespace fallback + R-19 byte identity
# (design: A3_nssd_verification.md — 数字经济 × 共同富裕 recovers 519 vs 222)
# ===========================================================================

from urllib.parse import parse_qs  # noqa: E402


def _legacy_build_pq(query: str) -> str:
    """The EXACT pre-v2.4 single-string ``_build_pq`` — frozen here as the
    byte-for-byte oracle the new whitespace-fallback path MUST reproduce for
    single-token queries (R-19 zero regression)."""
    term = (query or "").strip().replace('"', "").replace("“", "").replace("”", "")
    return f'(IKTE="{term}" OR IKST="{term}" OR IKSE="{term}")'


# The live-verified two-concept target (A3 D-row, total≈519). This is the exact
# string the reproducible curl in A3_nssd_verification.md §附 posts.
_D_STRING = (
    '(IKTE="数字经济" OR IKST="数字经济" OR IKSE="数字经济") '
    'AND (IKTE="共同富裕" OR IKST="共同富裕" OR IKSE="共同富裕")'
)


# ---- R-19: single-token PQ is byte-identical to the frozen legacy formula ----
# Byte-identity is SCOPED TO SINGLE-TOKEN queries only. A multi-word query is an
# AUTHORIZED behaviour change (whitespace-split into ANDed blocks — the P2-5 recall
# fix), asserted by the P2-5 section below. This is the Gate-2 D-c honesty split:
# single-token stays byte-identical, multi-word deliberately DIFFERS (not a regression).


@pytest.mark.parametrize(
    "q",
    [
        "数字经济",
        "情绪调节",
        "乡村振兴",
        "x",
        "  数字经济  ",   # leading/trailing whitespace, still ONE token
        '数字"经济',       # embedded half-width quote -> stripped both ways
        "数字“经济”",      # embedded full-width quotes -> stripped both ways
    ],
)
def test_build_pq_single_token_byte_identical_to_legacy(q):
    assert nssd_helper._build_pq(q) == _legacy_build_pq(q)


# ---- P2-5: whitespace fallback + explicit blocks both reach the multiblock PQ ----


def test_build_pq_whitespace_fallback_recovers_multiblock():
    # AUTHORIZED behaviour change (P2-5 recall fix, NOT byte-identical to v2.3): a
    # two-word query is whitespace-split into two ANDed blocks — the exact string A3
    # live-verified to recover ~519 hits (vs 222 for the old single-phrase form).
    assert nssd_helper._build_pq("数字经济 共同富裕") == _D_STRING


def test_build_pq_multiword_differs_from_legacy_by_design():
    """Gate-2 D-c honesty pin: for a MULTI-WORD query the new PQ deliberately
    DIFFERS from the frozen pre-v2.4 single-phrase formula — this is the authorized
    P2-5 recall fix (A3: 222→519), not a regression. Byte-identity claims are scoped
    to single-token queries only (the parametrized family above)."""
    q = "数字经济 共同富裕"
    assert nssd_helper._build_pq(q) != _legacy_build_pq(q)   # the authorized DIFF
    assert nssd_helper._build_pq(q) == _D_STRING              # ...to the live-verified form


def test_build_pq_blocks_two_concepts_equals_live_D_string():
    assert nssd_helper._build_pq(blocks=[["数字经济"], ["共同富裕"]]) == _D_STRING


def test_build_pq_blocks_with_synonyms_or_within_and_across():
    pq = nssd_helper._build_pq(blocks=[["数字经济", "数据要素"], ["共同富裕"]])
    assert pq == (
        '(IKTE="数字经济" OR IKST="数字经济" OR IKSE="数字经济" '
        'OR IKTE="数据要素" OR IKST="数据要素" OR IKSE="数据要素") '
        'AND (IKTE="共同富裕" OR IKST="共同富裕" OR IKSE="共同富裕")'
    )


def test_build_pq_blocks_take_precedence_over_query():
    # When blocks are supplied, the flat query is ignored (caller already split).
    assert nssd_helper._build_pq("忽略我", blocks=[["数字经济"]]) == _legacy_build_pq("数字经济")


def test_build_pq_strips_quotes_inside_block_synonyms():
    assert nssd_helper._build_pq(blocks=[['数字"经济']]) == _legacy_build_pq("数字经济")


def test_build_pq_drops_empty_synonyms_and_empty_blocks():
    assert nssd_helper._build_pq(blocks=[["数字经济", "", "  "]]) == _legacy_build_pq("数字经济")
    assert nssd_helper._build_pq(blocks=[]) == ""
    assert nssd_helper._build_pq(blocks=[[""], ["  "]]) == ""


def test_build_pq_empty_query_is_empty_string():
    assert nssd_helper._build_pq("") == ""
    assert nssd_helper._build_pq("   ") == ""
    assert nssd_helper._build_pq(None) == ""


def test_block_clause_helper():
    assert nssd_helper._block_clause(["A"]) == '(IKTE="A" OR IKST="A" OR IKSE="A")'
    assert nssd_helper._block_clause([]) == ""
    assert nssd_helper._block_clause(["", "  "]) == ""
    assert nssd_helper._block_clause(["A", "", "B"]) == (
        '(IKTE="A" OR IKST="A" OR IKSE="A" OR IKTE="B" OR IKST="B" OR IKSE="B")'
    )


# ---- CLI flag resolution (--block / --blocks) ----


def test_cli_resolve_blocks_json():
    assert nssd_helper._cli_resolve_blocks(
        '[["数字经济","数据要素"],["共同富裕"]]', None
    ) == [["数字经济", "数据要素"], ["共同富裕"]]


def test_cli_resolve_blocks_repeated_flag_pipe_delimited():
    assert nssd_helper._cli_resolve_blocks(
        None, ["数字经济|数据要素", "共同富裕"]
    ) == [["数字经济", "数据要素"], ["共同富裕"]]


def test_cli_resolve_blocks_json_wins_over_flag():
    assert nssd_helper._cli_resolve_blocks('[["A"]]', ["B|C"]) == [["A"]]


def test_cli_resolve_blocks_bad_json_degrades_to_none():
    assert nssd_helper._cli_resolve_blocks("{not json", None) is None


def test_cli_resolve_blocks_wrong_shape_degrades_to_none():
    assert nssd_helper._cli_resolve_blocks('["A","B"]', None) is None  # flat list
    assert nssd_helper._cli_resolve_blocks("[]", None) is None          # empty list


def test_cli_resolve_blocks_coerces_inner_values_to_str():
    assert nssd_helper._cli_resolve_blocks("[[1, 2]]", None) == [["1", "2"]]


def test_cli_resolve_blocks_none_when_neither_given():
    assert nssd_helper._cli_resolve_blocks(None, None) is None


# ---- search() end-to-end: the PQ actually posted (urlencoded body) ----


def _posted_pq(sess) -> str:
    """Decode the ``search=`` PQ the helper actually posted."""
    return parse_qs(sess.calls[0]["data"])["search"][0]


def test_search_single_token_posts_legacy_byte_identical_body():
    # End-to-end R-19: the posted body for a single-token query is byte-identical
    # to the frozen legacy PQ.
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    nssd_helper.search("情绪调节", n=5, session=sess)
    assert _posted_pq(sess) == _legacy_build_pq("情绪调节")


def test_search_multiword_query_posts_multiblock_body():
    # End-to-end P2-5: a multi-word query posts the MULTIBLOCK body — NOT byte-identical
    # to the pre-v2.4 single-phrase body (the authorized recall fix; D-c honesty split).
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    nssd_helper.search("数字经济 共同富裕", n=5, session=sess)
    assert _posted_pq(sess) == _D_STRING


def test_search_blocks_posts_multiblock_body():
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    nssd_helper.search("", n=5, blocks=[["数字经济"], ["共同富裕"]], session=sess)
    assert _posted_pq(sess) == _D_STRING


def test_search_blocks_only_empty_query_still_fires():
    # A blocks-only call with an empty query must NOT bail — it has terms to search.
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    out = nssd_helper.search("", n=5, blocks=[["数字经济"]], session=sess)
    assert len(out) == 1
    assert sess.calls  # a request WAS made


def test_search_no_terms_bails_without_request():
    # Empty query AND no usable block terms -> no network call (nothing to do).
    sess = _FakeSession(pages=[_ok([ROW_JOURNAL])])
    assert nssd_helper.search("", n=5, blocks=[[""]], session=sess) == []
    assert sess.calls == []
