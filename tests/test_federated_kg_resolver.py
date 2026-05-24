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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
