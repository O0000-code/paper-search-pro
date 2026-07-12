"""tests/test_federated_kg_resolver.py — 14+ tests covering SA-V4 E1-E6 edge
cases (9/9) + field-priority merge cases (26/26).

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python -m pytest tests/test_federated_kg_resolver.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.types import Author, UnifiedPaperEntity  # noqa: E402
from scripts.federated_kg_resolver import (  # noqa: E402
    _paper_to_dict,
    _papers_from_payload,
    canonical_key,
    federated_dedup,
    is_same_physical_paper,
    kg_to_list,
    merge_paper_fields,
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
)


# ============================================================================
# Normalization primitives (3 tests)
# ============================================================================

def test_e1_arxiv_doi_case_normalize():
    """E1: arXiv DOI 'arXiv' vs 'arxiv' case must normalize to lowercase."""
    assert normalize_doi("10.48550/arXiv.1706.03762") == "10.48550/arxiv.1706.03762"
    assert normalize_doi("10.48550/ARXIV.1706.03762") == "10.48550/arxiv.1706.03762"
    # URL prefix should be stripped
    assert normalize_doi("https://doi.org/10.1038/X") == "10.1038/x"
    # None / empty round-trip safely
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_e2_arxiv_version_stripping():
    """E2: arXiv version suffix vN must be stripped."""
    assert normalize_arxiv_id("1706.03762v5") == "1706.03762"
    assert normalize_arxiv_id("1706.03762") == "1706.03762"
    # Also strip from arXiv DOI form
    assert normalize_doi("10.48550/arxiv.1706.03762v5") == "10.48550/arxiv.1706.03762"
    # URL prefix
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v2") == "2401.12345"
    assert normalize_arxiv_id(None) is None


def test_e4_title_fuzzy_normalize():
    """E4: title normalize handles case, punctuation, trailing parenthetical."""
    assert normalize_title("Attention Is All You Need") == normalize_title(
        "attention is all you need"
    )
    assert normalize_title("Attention Is All You Need!") == normalize_title(
        "AttentionIsAllYouNeed"
    )
    # Trailing parenthetical attribution stripped
    assert normalize_title(
        "Attention is all you need (Vaswani 2017)"
    ) == normalize_title("Attention is all you need")
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


# ============================================================================
# canonical_key fallback chain (1 test)
# ============================================================================

def test_e3_no_doi_uses_arxiv_fallback():
    """E3: paper without DOI uses arxiv_id as canonical key (with version stripped)."""
    p = UnifiedPaperEntity(arxiv_id="2401.12345v2", title="Foo")
    key = canonical_key(p)
    assert key == ("arxiv", "2401.12345")

    # No DOI, no arxiv -> pmid fallback
    p_pm = UnifiedPaperEntity(pmid="99999", title="Bar")
    assert canonical_key(p_pm) == ("pmid", "99999")

    # Title-year fallback when no IDs at all
    p_t = UnifiedPaperEntity(title="Some Paper", year=2020)
    assert canonical_key(p_t)[0] == "title"
    assert canonical_key(p_t)[2] == 2020


# ============================================================================
# Cross-source merge: same paper across sources (1 test)
# ============================================================================

def test_e5_same_paper_merges():
    """E5: same DOI across OA and SS — must collapse to one entry with combined fields."""
    p_oa = UnifiedPaperEntity(
        doi="10.1038/foo",
        title="Foo",
        year=2020,
        citation_count=100,
        sources=["openalex"],
    )
    p_ss = UnifiedPaperEntity(
        doi="10.1038/FOO",  # different case — must still merge
        title="Foo",
        year=2020,
        influential_citation_count=15,
        sources=["semantic_scholar"],
    )
    kg = federated_dedup([p_oa], [p_ss])
    assert len(kg) == 1
    merged = list(kg.values())[0]
    assert merged.citation_count == 100
    assert merged.influential_citation_count == 15
    assert set(merged.sources) == {"openalex", "semantic_scholar"}


# ============================================================================
# E5b GUARD — the critical non-negotiable test (1 test)
# ============================================================================

def test_e5b_different_doi_same_titleyear_no_merge():
    """E5b GUARD: same title+year but DIFFERENT DOIs MUST NOT merge.

    Real-world case: Kahneman & Tversky 1979 Econometrica vs Cambridge
    handbook chapter — same title, same year, distinct DOIs, distinct papers.
    """
    p1 = UnifiedPaperEntity(
        doi="10.2307/1914185",
        title="Prospect Theory",
        year=1979,
        sources=["openalex"],
    )
    p2 = UnifiedPaperEntity(
        doi="10.1017/cbo9780511609220.014",
        title="Prospect Theory",
        year=1979,
        sources=["crossref"],
    )
    kg = federated_dedup([p1], [p2])
    assert len(kg) == 2, "E5b VIOLATION: different DOIs collapsed into one entry"

    dois = sorted(p.doi for p in kg.values())
    assert dois == ["10.1017/cbo9780511609220.014", "10.2307/1914185"]


def test_e5b_is_same_physical_paper_helper():
    """E5b guard helper: is_same_physical_paper must reject DOI conflicts."""
    a = UnifiedPaperEntity(doi="10.1/x", title="T", year=2020)
    b = UnifiedPaperEntity(doi="10.1/y", title="T", year=2020)
    assert is_same_physical_paper(a, b) is False

    # Same DOI -> same paper
    c = UnifiedPaperEntity(doi="10.1/x", title="T")
    assert is_same_physical_paper(a, c) is True

    # One has DOI, other doesn't -> treated as same (DOI fills in)
    d = UnifiedPaperEntity(title="T", year=2020)
    assert is_same_physical_paper(a, d) is True

    # Conflicting arxiv_id -> reject
    e = UnifiedPaperEntity(arxiv_id="1706.03762")
    f = UnifiedPaperEntity(arxiv_id="2401.12345")
    assert is_same_physical_paper(e, f) is False


# ============================================================================
# E6: title-bridge across sources (1 test)
# ============================================================================

def test_e6_ss_title_fallback():
    """E6: SS missing DOI but matching title+year — two distinct canonical keys.

    Note: resolver does NOT auto-bridge across different ID types. The main
    agent is expected to title-search SS first to recover the DOI, then feed
    matched DOIs to the resolver. Resolver's job is to deterministically
    merge when keys actually match.
    """
    p_oa = UnifiedPaperEntity(
        doi="10.1038/bar",
        title="Attention is all you need",
        year=2017,
        sources=["openalex"],
    )
    p_ss = UnifiedPaperEntity(
        ss_paper_id="abc123",
        title="Attention is all you need",
        year=2017,
        tldr="best attention!",
        sources=["semantic_scholar"],
    )
    kg = federated_dedup([p_oa], [p_ss])
    # DOI key != ss_paper_id key (intentional: main agent handles bridging)
    assert len(kg) == 2


# ============================================================================
# Field priority merge (per §4 table) (4 tests)
# ============================================================================

def test_field_citation_count_oa_wins():
    """citation_count: OpenAlex wins (typically higher than SS)."""
    p_oa = UnifiedPaperEntity(doi="10.1/x", citation_count=46625, sources=["openalex"])
    p_ss = UnifiedPaperEntity(
        doi="10.1/x", citation_count=36684, sources=["semantic_scholar"]
    )
    kg = federated_dedup([p_oa], [p_ss])
    merged = list(kg.values())[0]
    assert merged.citation_count == 46625, "OpenAlex citation_count should win"


def test_field_influential_ss_only():
    """influential_citation_count: SS-only signal, must propagate."""
    p_oa = UnifiedPaperEntity(
        doi="10.1/y", citation_count=1000, sources=["openalex"]
    )
    p_ss = UnifiedPaperEntity(
        doi="10.1/y", influential_citation_count=42, sources=["semantic_scholar"]
    )
    kg = federated_dedup([p_oa], [p_ss])
    merged = list(kg.values())[0]
    assert merged.influential_citation_count == 42


def test_field_funder_crossref_only():
    """funder: CrossRef-only field, must merge into entity."""
    p_oa = UnifiedPaperEntity(doi="10.1/z", sources=["openalex"])
    p_cr = UnifiedPaperEntity(
        doi="10.1/z",
        funders=[{"name": "NIH", "doi": "10.13039/100000002"}],
        sources=["crossref"],
    )
    kg = federated_dedup([p_oa], [p_cr])
    merged = list(kg.values())[0]
    assert merged.funders[0]["name"] == "NIH"
    assert merged.funders[0]["doi"] == "10.13039/100000002"


def test_field_mesh_pubmed_only():
    """mesh_terms + pmid: PubMed-only, must merge into entity."""
    p_oa = UnifiedPaperEntity(doi="10.1/m", sources=["openalex"])
    p_pm = UnifiedPaperEntity(
        doi="10.1/m",
        pmid="12345",
        mesh_terms=["Diabetes Mellitus", "Metformin"],
        sources=["pubmed"],
    )
    kg = federated_dedup([p_oa], [p_pm])
    merged = list(kg.values())[0]
    assert "Diabetes Mellitus" in merged.mesh_terms
    assert merged.pmid == "12345"


# ============================================================================
# 4-source merge sanity (1 test)
# ============================================================================

def test_4_source_merge():
    """4-source merge: OA + SS + CrossRef + PubMed all on same DOI."""
    p_oa = UnifiedPaperEntity(
        doi="10.1/abc",
        title="Foo",
        year=2020,
        citation_count=100,
        sources=["openalex"],
    )
    p_ss = UnifiedPaperEntity(
        doi="10.1/abc",
        influential_citation_count=15,
        tldr="Tldr",
        sources=["semantic_scholar"],
    )
    p_cr = UnifiedPaperEntity(
        doi="10.1/abc", funders=[{"name": "NIH"}], sources=["crossref"]
    )
    p_pm = UnifiedPaperEntity(
        doi="10.1/abc",
        pmid="999",
        mesh_terms=["Test"],
        sources=["pubmed"],
    )
    kg = federated_dedup([p_oa], [p_ss], [p_cr], [p_pm])
    assert len(kg) == 1
    merged = list(kg.values())[0]
    assert merged.citation_count == 100
    assert merged.influential_citation_count == 15
    assert merged.tldr == "Tldr"
    assert merged.funders[0]["name"] == "NIH"
    assert merged.mesh_terms == ["Test"]
    assert merged.pmid == "999"
    assert set(merged.sources) == {
        "openalex",
        "semantic_scholar",
        "crossref",
        "pubmed",
    }


# ============================================================================
# kg_to_list sorting (1 test)
# ============================================================================

def test_kg_to_list_sort():
    """kg_to_list: sort by citation_count descending."""
    kg = {
        ("doi", "1"): UnifiedPaperEntity(doi="1", citation_count=10),
        ("doi", "2"): UnifiedPaperEntity(doi="2", citation_count=100),
        ("doi", "3"): UnifiedPaperEntity(doi="3", citation_count=50),
    }
    sorted_list = kg_to_list(kg, sort_by="citation_count")
    assert sorted_list[0].citation_count == 100
    assert sorted_list[1].citation_count == 50
    assert sorted_list[-1].citation_count == 10

    # year sort
    kg2 = {
        ("doi", "1"): UnifiedPaperEntity(doi="1", year=2020),
        ("doi", "2"): UnifiedPaperEntity(doi="2", year=2024),
        ("doi", "3"): UnifiedPaperEntity(doi="3", year=2018),
    }
    sorted_by_year = kg_to_list(kg2, sort_by="year")
    assert sorted_by_year[0].year == 2024
    assert sorted_by_year[-1].year == 2018


# ============================================================================
# Edge: empty input + dedup of sources list (2 tests)
# ============================================================================

def test_empty_input():
    """Empty input lists return empty KG (must not crash)."""
    assert federated_dedup([], [], []) == {}
    assert federated_dedup() == {}
    # Single empty list also fine
    assert federated_dedup([]) == {}


def test_sources_list_dedup():
    """Sources list must dedup when same source appears twice."""
    p1 = UnifiedPaperEntity(doi="10.1/a", sources=["openalex"])
    p2 = UnifiedPaperEntity(doi="10.1/a", sources=["openalex"])
    kg = federated_dedup([p1, p2])
    merged = list(kg.values())[0]
    assert merged.sources == ["openalex"], "Sources list must dedup"


# ============================================================================
# Bonus: merge_paper_fields direct + author preservation (1 test)
# ============================================================================

def test_merge_paper_fields_preserves_oa_authors():
    """When OpenAlex source arrives second, its richer author list should win."""
    p_ss_first = UnifiedPaperEntity(
        doi="10.1/auth",
        title="Foo",
        authors=[Author(name="J. Smith")],
        sources=["semantic_scholar"],
    )
    p_oa_second = UnifiedPaperEntity(
        doi="10.1/auth",
        title="Foo",
        authors=[
            Author(name="Jane Smith", orcid="0000-0001", is_first=True),
            Author(name="Bob Jones"),
        ],
        sources=["openalex"],
    )
    merged = merge_paper_fields(p_ss_first, p_oa_second)
    # OA authors should replace SS authors (OA preferred for authors)
    assert len(merged.authors) == 2
    assert merged.authors[0].orcid == "0000-0001"


# ============================================================================
# v2.2.1 Phase 0 — 0.1 CJK title normalization (bug: DOI-less zh titles collapse)
# ============================================================================

import re as _re  # noqa: E402


def _old_normalize_title(title):
    """The pre-0.1 normalize_title (strips ALL non-a-z0-9, i.e. every CJK char).

    Kept here purely so the R-19 byte-identity assertion below compares against
    the exact prior behavior for Latin/English input."""
    if not title:
        return ""
    s = title.lower()
    s = _re.compile(r"\([^)]*\)\s*$").sub("", s)
    return _re.compile(r"[^a-z0-9]").sub("", s)


def test_0_1_normalize_title_english_byte_identical():
    """0.1 R-19: for every non-CJK title the CJK-additive regex must be
    byte-identical to the old strip-everything regex (accented Latin, Cyrillic,
    Greek, punctuation are all still removed exactly as before)."""
    samples = [
        "Attention Is All You Need",
        "Attention is all you need (Vaswani 2017)",
        "Deep Residual Learning for Image Recognition!",
        "Naïve Bayes and the café problem",
        "BERT: Pre-training of Deep Bidirectional Transformers",
        "Über die Quantentheorie (Einstein, 1917)",
        "Мир и война",            # Cyrillic — must still be stripped (not CJK)
        "Ω-theory of α-particles",  # Greek — must still be stripped
        "",
        None,
    ]
    for s in samples:
        assert normalize_title(s) == _old_normalize_title(s), f"byte drift on {s!r}"


def test_0_1_cjk_titles_preserved_and_distinct():
    """0.1: three DISTINCT Chinese titles must yield three distinct, non-empty
    normalized forms (previously all collapsed to "")."""
    zh = ["数字经济与收入差距", "深度学习在图像识别中的应用", "中国农村金融发展研究"]
    norms = [normalize_title(t) for t in zh]
    assert all(norms), "a Chinese title collapsed to empty (0.1 regression)"
    assert len(set(norms)) == 3, "distinct Chinese titles collided (0.1 regression)"
    # Japanese kana + Korean hangul are also preserved.
    assert normalize_title("ディープラーニング") == "ディープラーニング"
    assert normalize_title("딥러닝 연구") == "딥러닝연구"


def test_0_1_three_chinese_papers_dedup_to_three():
    """0.1 end-to-end: three DOI-less Chinese papers (same year) must NOT merge.

    Before the fix all three shared the ("title", "", year) key and silently
    collapsed to one entry (real case: 《经济研究》 2024 merged with an unrelated
    《燕山大学学报》 2024 paper)."""
    p1 = UnifiedPaperEntity(title="数字经济与收入差距", year=2024, sources=["nssd"])
    p2 = UnifiedPaperEntity(title="人工智能与就业结构", year=2024, sources=["nssd"])
    p3 = UnifiedPaperEntity(title="乡村振兴与共同富裕", year=2024, sources=["nssd"])
    kg = federated_dedup([p1, p2, p3])
    assert len(kg) == 3, "distinct Chinese papers collapsed (0.1 regression)"


# ============================================================================
# v2.2.1 Phase 0 — 0.2 source_native_id in canonical_key / paper_id
# ============================================================================

def test_0_2_native_id_key_active():
    """0.2: a DOI-less record with a source_native_id keys off ('native', id),
    sitting above the (title, year) fallback."""
    p = UnifiedPaperEntity(
        title="数字经济与收入差距",
        year=2024,
        source_native_id="nssd:JJYJ2024005009",
        sources=["nssd"],
    )
    assert canonical_key(p) == ("native", "nssd:JJYJ2024005009")
    assert p.paper_id == "nssd:JJYJ2024005009"


def test_0_2_same_title_different_native_id_no_merge():
    """0.2: two DOI-less records with the SAME title+year but different native
    IDs must remain distinct (native id resolves the would-be title collision)."""
    a = UnifiedPaperEntity(title="研究", year=2024, source_native_id="nssd:A", sources=["nssd"])
    b = UnifiedPaperEntity(title="研究", year=2024, source_native_id="nssd:B", sources=["nssd"])
    kg = federated_dedup([a, b])
    assert len(kg) == 2


def test_0_2_absent_native_id_preserves_old_behavior():
    """0.2 R-19: with no source_native_id, canonical_key / paper_id are exactly
    the prior values — DOI, arXiv, and title-year fallbacks all unchanged."""
    doi_p = UnifiedPaperEntity(doi="10.1/x", title="Attention Is All You Need", year=2017)
    assert canonical_key(doi_p) == ("doi", "10.1/x")
    assert doi_p.paper_id == "10.1/x"

    title_p = UnifiedPaperEntity(title="Some Paper", year=2020)
    key = canonical_key(title_p)
    assert key[0] == "title" and key[2] == 2020

    # Same native id merges (fills across sources) — sanity for the merge line.
    n1 = UnifiedPaperEntity(title="X", year=2024, source_native_id="nssd:Q", sources=["nssd"])
    n2 = UnifiedPaperEntity(
        title="X", year=2024, source_native_id="nssd:Q", tldr="t", sources=["semantic_scholar"]
    )
    kg = federated_dedup([n1], [n2])
    assert len(kg) == 1


# ============================================================================
# v2.2.1 Phase 0 — 0.4 venue backfill (OA missing venue → SS venue) regression
# ============================================================================

def test_0_4_venue_backfilled_from_ss_when_openalex_missing():
    """0.4: when the OpenAlex record has no venue (common for CS conference
    papers) but a Semantic Scholar record carries it, the merged paper keeps the
    SS venue — regardless of merge order. This locks the behavior the resolver's
    non-empty backfill already provides."""
    oa = UnifiedPaperEntity(
        doi="10.1/resnet", title="Deep Residual Learning", year=2016,
        venue=None, sources=["openalex"],
    )
    ss = UnifiedPaperEntity(
        doi="10.1/resnet", title="Deep Residual Learning", year=2016,
        venue="CVPR", sources=["semantic_scholar"],
    )
    assert list(federated_dedup([oa], [ss]).values())[0].venue == "CVPR"  # OA first
    assert list(federated_dedup([ss], [oa]).values())[0].venue == "CVPR"  # SS first
    # Empty-string venue on OA is treated as missing too.
    oa_empty = UnifiedPaperEntity(doi="10.1/r2", title="X", year=2016, venue="", sources=["openalex"])
    ss2 = UnifiedPaperEntity(doi="10.1/r2", title="X", year=2016, venue="CVPR", sources=["semantic_scholar"])
    assert list(federated_dedup([oa_empty], [ss2]).values())[0].venue == "CVPR"


def test_0_4_existing_venue_not_overridden():
    """0.4: a paper that already has a venue is never clobbered by another
    source's venue (non-CS / venue-present papers are unaffected)."""
    oa = UnifiedPaperEntity(doi="10.1/j", title="Y", year=2020, venue="Nature", sources=["openalex"])
    ss = UnifiedPaperEntity(doi="10.1/j", title="Y", year=2020, venue="Nature Portfolio", sources=["semantic_scholar"])
    assert list(federated_dedup([oa], [ss]).values())[0].venue == "Nature"


# ============================================================================
# #4 — Chinese-native original text wins over English on a DOI collision
# ============================================================================

def _zh_paper(**kw):
    kw.setdefault("sources", ["nssd"])
    return UnifiedPaperEntity(**kw)


def _oa_paper(**kw):
    kw.setdefault("sources", ["openalex"])
    return UnifiedPaperEntity(**kw)


def test_4_chinese_title_survives_english_openalex_collision():
    """#4: OA (English-translated) + NSSD (Chinese original) share a DOI. The
    Chinese title / abstract / authors / venue must win — in BOTH merge orders."""
    def make_pair():
        oa = _oa_paper(
            doi="10.1000/econ.2024",
            title="Digital Economy and Income Gap",
            abstract="An English abstract from OpenAlex.",
            authors=[Author(name="Zhang San")],
            venue="Economic Research Journal",
            year=2024,
            citation_count=12,
        )
        zh = _zh_paper(
            doi="10.1000/econ.2024",
            title="数字经济与收入差距",
            abstract="中文摘要原文。",
            authors=[Author(name="张三")],
            venue="经济研究",
            year=2024,
            source_native_id="nssd:JJYJ2024005009",
        )
        return oa, zh

    # OA first (English is `existing`, Chinese arrives as `new` → must override)
    oa, zh = make_pair()
    merged = list(federated_dedup([oa], [zh]).values())[0]
    assert merged.title == "数字经济与收入差距"
    assert merged.abstract == "中文摘要原文。"
    assert merged.authors[0].name == "张三"
    assert merged.venue == "经济研究"
    # English-only fields still merge (OA citation_count preserved).
    assert merged.citation_count == 12
    assert set(merged.sources) == {"openalex", "nssd"}

    # NSSD first (Chinese is `existing`, English arrives as `new` → must NOT clobber)
    oa, zh = make_pair()
    merged = list(federated_dedup([zh], [oa]).values())[0]
    assert merged.title == "数字经济与收入差距"
    assert merged.abstract == "中文摘要原文。"
    assert merged.authors[0].name == "张三"
    assert merged.venue == "经济研究"


def test_4_english_only_collision_unchanged_r19():
    """#4 R-19: with no Chinese source, the OpenAlex-preferred overwrite behavior
    is exactly as before — English `new` OpenAlex title/authors replace a
    non-OpenAlex `existing`."""
    ss = UnifiedPaperEntity(
        doi="10.1/x", title="Foo (SS variant)", authors=[Author(name="J. Smith")],
        venue="ArXiv preprint", sources=["semantic_scholar"],
    )
    oa = UnifiedPaperEntity(
        doi="10.1/x", title="Foo", authors=[Author(name="Jane Smith", is_first=True)],
        venue="Nature", sources=["openalex"],
    )
    merged = list(federated_dedup([ss], [oa]).values())[0]
    # OpenAlex preferred for title/authors (unchanged behavior).
    assert merged.title == "Foo"
    assert merged.authors[0].name == "Jane Smith"
    # venue: first-non-empty wins (SS was first) — unchanged.
    assert merged.venue == "ArXiv preprint"


def test_4_chinese_venue_does_not_backfill_english_only_pool():
    """#4 R-19 boundary: a purely English merge never sees the zh branches, so a
    missing venue still backfills from whichever source has it (0.4 behavior)."""
    oa = UnifiedPaperEntity(doi="10.1/r", title="X", venue=None, sources=["openalex"])
    ss = UnifiedPaperEntity(doi="10.1/r", title="X", venue="CVPR", sources=["semantic_scholar"])
    assert list(federated_dedup([oa], [ss]).values())[0].venue == "CVPR"


# ============================================================================
# #3 — issn merged + round-tripped through serialization
# ============================================================================

def test_3_issn_merged_from_any_source():
    """#3: issn must merge (first non-empty) so a source that carries it fills a
    record whose first-seen source lacked it."""
    ss = UnifiedPaperEntity(doi="10.1/j", title="X", issn=None, sources=["semantic_scholar"])
    oa = UnifiedPaperEntity(doi="10.1/j", title="X", issn="0033-2909", sources=["openalex"])
    merged = list(federated_dedup([ss], [oa]).values())[0]
    assert merged.issn == "0033-2909"
    # Existing issn is never clobbered by a later empty one.
    oa2 = UnifiedPaperEntity(doi="10.1/k", title="Y", issn="1939-1471", sources=["openalex"])
    cr = UnifiedPaperEntity(doi="10.1/k", title="Y", issn=None, sources=["crossref"])
    assert list(federated_dedup([oa2], [cr]).values())[0].issn == "1939-1471"


def test_3_issn_round_trips_through_serialization():
    """#3: _paper_to_dict must emit issn (when set) and _papers_from_payload must
    read it back — the resolver previously dropped it, breaking the human-path
    journal_rank ISSN join end to end."""
    p = UnifiedPaperEntity(doi="10.1/j", title="X", issn="0033-2909", sources=["openalex"])
    d = _paper_to_dict(p)
    assert d["issn"] == "0033-2909"
    restored = _papers_from_payload([d])[0]
    assert restored.issn == "0033-2909"


def test_3_issn_absent_stays_byte_identical_r19():
    """#3 R-19: an issn-less record must NOT gain an "issn" key in kg.json (the
    conditional emit keeps arXiv/PubMed-only records byte-identical)."""
    p = UnifiedPaperEntity(arxiv_id="2401.12345", title="X", sources=["arxiv"])
    d = _paper_to_dict(p)
    assert "issn" not in d
    # And a payload with no issn key decodes to issn=None (no crash).
    assert _papers_from_payload([{"doi": "10.1/z", "title": "Z"}])[0].issn is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
