"""Unit tests for pubmed_helper (live NCBI E-utilities calls).

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 tests/test_pubmed_helper.py

Requires:
    - Biopython installed
    - ~/.paper-search-pro/config.yaml with valid ncbi_email (key optional but recommended)

Tests touch live NCBI; rate limited internally to ~5 req/s (key) or 3 req/s (no key).
"""

import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from Bio import Entrez  # noqa: E402

from scripts.config import load_config  # noqa: E402
from scripts.pubmed_helper import (  # noqa: E402
    enrich_with_mesh,
    get_paper_by_pmid,
    init,
    search_by_mesh,
    search_keyword,
)
from scripts.types import Config, UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: init() wires Entrez globals from Config
# ---------------------------------------------------------------------------

def test_init_sets_entrez_globals():
    fake_cfg = Config(ncbi_email="test@example.com", ncbi_api_key="abc123fakekey")
    init(fake_cfg)
    assert Entrez.email == "test@example.com"
    assert Entrez.api_key == "abc123fakekey"
    assert Entrez.tool == "paper-search-pro"
    # Re-init with the real config so subsequent tests have working creds.
    init(load_config())
    print("OK  init sets Entrez globals (email/api_key/tool)")


# ---------------------------------------------------------------------------
# Test 2: search_by_mesh respects limit, returns dicts with mesh_terms
# ---------------------------------------------------------------------------

def test_search_by_mesh_metformin_with_year_min():
    results = search_by_mesh("Metformin", year_min=2020, limit=10)
    assert isinstance(results, list)
    assert len(results) <= 10, f"limit=10 honored, got {len(results)}"
    assert len(results) > 0, "Metformin since 2020 must return >0 papers"
    first = results[0]
    assert "mesh_terms" in first and isinstance(first["mesh_terms"], list)
    assert "Metformin" in first["mesh_terms"], (
        f"MeSH descriptor 'Metformin' must appear in mesh_terms; got {first['mesh_terms'][:6]}"
    )
    # year filter sanity
    assert first["year"] is None or first["year"] >= 2020
    print(f"OK  search_by_mesh Metformin year_min=2020 limit=10 -> {len(results)} hits, "
          f"first has {len(first['mesh_terms'])} MeSH terms")


# ---------------------------------------------------------------------------
# Test 3: publication_types filter actually filters to RCT/Clinical Trial
# ---------------------------------------------------------------------------

def test_search_by_mesh_clinical_trial_filter():
    """PubMed's '[Publication Type]' filter walks the MeSH tree, so
    'Clinical Trial' matches its subtypes too (Randomized Controlled Trial,
    Clinical Trial Phase III, etc.). The returned publication_types may carry
    only the more specific child label, so we accept any clinical-trial family
    descriptor.
    """
    results = search_by_mesh(
        "Diabetes Mellitus, Type 2",
        publication_types=["Clinical Trial"],
        limit=5,
    )
    assert isinstance(results, list)
    assert len(results) > 0, "T2D + Clinical Trial filter must return hits"
    # The PubMed Clinical Trial family — any of these descriptors counts.
    trial_family = (
        "Clinical Trial",                  # umbrella
        "Randomized Controlled Trial",     # most common child
        "Controlled Clinical Trial",
        "Pragmatic Clinical Trial",
        "Adaptive Clinical Trial",
        "Equivalence Trial",
    )
    matches = [
        r for r in results
        if any(any(fam in pt for fam in trial_family)
               for pt in r.get("publication_types", []))
    ]
    assert len(matches) == len(results), (
        f"All filtered results should carry a Clinical-Trial-family pub_type; "
        f"got {len(matches)}/{len(results)}; first result types={results[0]['publication_types']}"
    )
    sample_types = results[0]["publication_types"]
    print(f"OK  Clinical Trial filter: {len(results)} hits all carry a trial-family "
          f"pub_type (sample: {sample_types[:3]})")


# ---------------------------------------------------------------------------
# Test 4: enrich_with_mesh skips papers without pmid (Kahneman 1979 case)
# ---------------------------------------------------------------------------

def test_enrich_skips_papers_without_pmid():
    # P1 Kahneman 1979 Econometrica — confirmed NOT in PubMed (SA-W3 T3)
    kahneman = UnifiedPaperEntity(
        doi="10.2307/1914185",
        title="Prospect Theory: An Analysis of Decision under Risk",
        year=1979,
        pmid=None,
    )
    other = UnifiedPaperEntity(doi="10.0/fake", pmid=None)
    papers = [kahneman, other]
    out = enrich_with_mesh(papers)
    assert out is papers, "enrich_with_mesh should return the same list (in-place mutation)"
    assert kahneman.mesh_terms == []
    assert kahneman.publication_types == []
    assert "pubmed" not in kahneman.sources
    print("OK  enrich_with_mesh skips papers without pmid (Kahneman 1979 untouched)")


# ---------------------------------------------------------------------------
# Test 5: enrich_with_mesh on real PMID adds mesh_terms + sources
# ---------------------------------------------------------------------------

def test_enrich_with_mesh_on_real_paper():
    # PMID 33301246 = BNT162b2 NEJM 2020 — known to have 19 MeSH terms (SA-W3 T8)
    paper = UnifiedPaperEntity(
        doi="10.1056/nejmoa2034577",
        title="Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
        year=2020,
        pmid="33301246",
    )
    out = enrich_with_mesh([paper])
    assert out[0] is paper
    assert len(paper.mesh_terms) >= 10, (
        f"BNT162b2 paper has 19 MeSH terms upstream; got {len(paper.mesh_terms)}: "
        f"{paper.mesh_terms[:5]}"
    )
    assert "COVID-19" in paper.mesh_terms or "BNT162 Vaccine" in paper.mesh_terms
    assert "pubmed" in paper.sources, "sources must record 'pubmed' after enrichment"
    print(f"OK  enrich on PMID 33301246 -> {len(paper.mesh_terms)} MeSH terms "
          f"(sample: {paper.mesh_terms[:3]}), sources={paper.sources}")


# ---------------------------------------------------------------------------
# Test 6: PMC URL format + pmcid normalization
# ---------------------------------------------------------------------------

def test_pmc_url_format():
    paper = UnifiedPaperEntity(
        doi="10.1056/nejmoa2034577",
        pmid="33301246",
    )
    enrich_with_mesh([paper])
    # PMC7745181 per SA-W3 T7
    assert paper.pmcid == "PMC7745181", f"Expected PMC7745181, got {paper.pmcid}"
    assert paper.pmc_url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7745181/", (
        f"Unexpected PMC URL: {paper.pmc_url}"
    )
    print(f"OK  PMC URL: {paper.pmc_url}")


# ---------------------------------------------------------------------------
# Test 7: enrich does not duplicate 'pubmed' in sources if called twice
# ---------------------------------------------------------------------------

def test_enrich_sources_no_duplicate():
    paper = UnifiedPaperEntity(
        doi="10.1056/nejmoa2034577",
        pmid="33301246",
        sources=["openalex"],
    )
    enrich_with_mesh([paper])
    enrich_with_mesh([paper])
    assert paper.sources.count("pubmed") == 1
    assert "openalex" in paper.sources
    print(f"OK  sources idempotent across repeated enrichment: {paper.sources}")


# ---------------------------------------------------------------------------
# Test 8: keyword search Count > MeSH search Count (SA-W3 T5: 35K vs 21K)
# ---------------------------------------------------------------------------

def test_keyword_count_greater_than_mesh_count():
    """Keyword 'metformin' (Title/Abstract/synonyms) > MeSH 'Metformin' (precise).

    Per SA-W3 T5: keyword metformin ~35K vs MeSH Metformin ~21K hits.
    We call Entrez.esearch directly with retmax=0 to get the Count without fetching.
    """
    # ensure init from real config
    init(load_config())

    time.sleep(0.2)
    h = Entrez.esearch(db="pubmed", term="metformin", retmax=0)
    rec_kw = Entrez.read(h)
    h.close()

    time.sleep(0.2)
    h = Entrez.esearch(db="pubmed", term='"Metformin"[MeSH Terms]', retmax=0)
    rec_mesh = Entrez.read(h)
    h.close()

    kw_count = int(rec_kw["Count"])
    mesh_count = int(rec_mesh["Count"])
    assert kw_count > mesh_count, (
        f"keyword metformin ({kw_count}) should exceed MeSH Metformin ({mesh_count})"
    )
    # rough sanity bounds (SA-W3: 35K vs 21K; allow growth over time)
    assert kw_count > 30_000
    assert mesh_count > 18_000
    print(f"OK  keyword metformin={kw_count:,} > MeSH Metformin={mesh_count:,} "
          f"(SA-W3 baseline 35K vs 21K)")


# ---------------------------------------------------------------------------
# Test 9: get_paper_by_pmid returns parsed dict with expected fields
# ---------------------------------------------------------------------------

def test_get_paper_by_pmid_smoke():
    rec = get_paper_by_pmid("33301246")
    assert rec is not None
    assert rec["pmid"] == "33301246"
    assert rec["doi"] == "10.1056/nejmoa2034577"
    assert rec["year"] == 2020
    assert "BNT162b2" in rec["title"]
    assert rec["pmcid"] == "PMC7745181"
    assert rec["pmc_url"].endswith("/PMC7745181/")
    assert isinstance(rec["mesh_terms"], list) and len(rec["mesh_terms"]) >= 10
    print(f"OK  get_paper_by_pmid(33301246): doi={rec['doi']} pmcid={rec['pmcid']} "
          f"mesh={len(rec['mesh_terms'])}")


# ---------------------------------------------------------------------------
# Test 10: search_keyword returns parsed dicts (smoke test)
# ---------------------------------------------------------------------------

def test_search_keyword_smoke():
    results = search_keyword("metformin AND diabetes", year_min=2024, limit=3)
    assert isinstance(results, list)
    assert 0 < len(results) <= 3
    assert all(isinstance(r.get("pmid"), str) and r["pmid"] for r in results)
    print(f"OK  search_keyword('metformin AND diabetes', 2024+, 3) -> "
          f"{len(results)} results, PMIDs: {[r['pmid'] for r in results]}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_init_sets_entrez_globals,
    test_search_by_mesh_metformin_with_year_min,
    test_search_by_mesh_clinical_trial_filter,
    test_enrich_skips_papers_without_pmid,
    test_enrich_with_mesh_on_real_paper,
    test_pmc_url_format,
    test_enrich_sources_no_duplicate,
    test_keyword_count_greater_than_mesh_count,
    test_get_paper_by_pmid_smoke,
    test_search_keyword_smoke,
]


def main() -> int:
    # bootstrap creds once before the suite runs
    init(load_config())
    passed, failed = 0, 0
    for fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{len(ALL_TESTS)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
