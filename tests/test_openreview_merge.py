"""Offline tests: OpenReview records fold into the same paper's other record.

OpenReview notes carry no DOI or arXiv id, so canonical_key cannot join them to
the arXiv / OpenAlex record of the same paper (2026-10-01, recency-retrieval).
"""

from __future__ import annotations

from scripts.federated_kg_resolver import federated_dedup
from scripts.types import UnifiedPaperEntity


def _arxiv(title="Simple Denoising Diffusion Language Models", year=2025):
    return UnifiedPaperEntity(doi="10.48550/arxiv.2510.12345", arxiv_id="2510.12345",
                              title=title, year=year, venue="arXiv (Cornell University)",
                              type="preprint", citation_count=12, sources=["openalex"])


def _or(title="Simple Denoising Diffusion Language Models", year=2026, venue="ICML 2026 Poster"):
    return UnifiedPaperEntity(source_native_id="openreview:abc123", title=title, year=year,
                              venue=venue, type="article", tldr="short summary",
                              sources=["openreview"])


def test_openreview_record_folds_into_the_preprint_and_labels_it():
    kg = federated_dedup([_arxiv()], [_or()])
    assert len(kg) == 1
    (p,) = kg.values()
    assert p.venue == "ICML 2026 Poster"
    assert p.type == "article"
    assert p.doi == "10.48550/arxiv.2510.12345" and p.year == 2025
    assert "openreview" in p.sources and p.tldr == "short summary"
    assert p.source_native_id is None


def test_input_order_does_not_matter():
    kg = federated_dedup([_or()], [_arxiv()])
    assert len(kg) == 1
    assert next(iter(kg.values())).venue == "ICML 2026 Poster"


def test_journal_venue_is_not_overwritten():
    journal = _arxiv()
    journal.venue, journal.type = "Nature Machine Intelligence", "article"
    kg = federated_dedup([journal], [_or()])
    assert len(kg) == 1
    assert next(iter(kg.values())).venue == "Nature Machine Intelligence"


def test_years_more_than_one_apart_do_not_merge():
    kg = federated_dedup([_arxiv(year=2022)], [_or(year=2026)])
    assert len(kg) == 2


def test_unmatched_openreview_record_stays():
    kg = federated_dedup([_arxiv()], [_or(title="A Different Paper Entirely")])
    assert len(kg) == 2
    assert any(p.venue == "ICML 2026 Poster" and p.source_native_id == "openreview:abc123"
               for p in kg.values())


def test_kg_without_openreview_is_untouched():
    a, b = _arxiv(), _arxiv(title="Another Paper")
    b.doi, b.arxiv_id = "10.48550/arxiv.2510.99999", "2510.99999"
    kg = federated_dedup([a, b])
    assert [p.venue for p in kg.values()] == ["arXiv (Cornell University)"] * 2
