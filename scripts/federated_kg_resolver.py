"""Federated KG Resolver: dedup + merge papers from 5 sources.

Architecture (v2.0): Pure deterministic Python. Main Claude Code agent feeds a
list of UnifiedPaperEntity objects from all 5 helpers (OpenAlex / Semantic
Scholar / CrossRef / PubMed / arXiv); this module returns a deduped KG (dict
keyed by canonical_key) with fields merged per the priority table in
01_working/25_round2_synthesis.md §4.

Primary key strategy (in order, SA-V4 9/9 boundary cases verified):
  1. DOI (lowercase, normalized) — covers >80% of papers
  2. arXiv ID (without version) — for arXiv-only preprints
  3. PMID — for PubMed-only
  4. OpenAlex W-ID — fallback
  5. SS paperId — fallback
  6. (normalized_title, year) — for truly ID-less papers

E5b guard (CRITICAL, non-negotiable): two papers with same (title, year) but
DIFFERENT DOIs MUST NOT merge. Real-world cases: Kahneman & Tversky 1979
Econometrica vs Cambridge handbook chapter (same title, same year, different
DOIs — they are distinct artifacts that must not be collapsed).
"""

from __future__ import annotations

import hashlib
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .types import UnifiedPaperEntity


# ============================================================================
# Normalization
# ============================================================================

_ARXIV_DOI_VER_RE = re.compile(r"(10\.48550/arxiv\.[\w\.\-]+?)v\d+$", re.IGNORECASE)
_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]")
_TITLE_TRAILING_PAREN_RE = re.compile(r"\([^)]*\)\s*$")


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Lowercase, strip URL prefixes, normalize arXiv DOI case and version.

    Examples:
        "https://doi.org/10.1038/X" -> "10.1038/x"
        "10.48550/arXiv.1706.03762"  -> "10.48550/arxiv.1706.03762"
        "10.48550/ARXIV.1706.03762v5" -> "10.48550/arxiv.1706.03762"
    """
    if not doi:
        return None
    d = doi.strip().lower()
    d = (
        d.replace("https://doi.org/", "")
        .replace("http://doi.org/", "")
        .replace("https://dx.doi.org/", "")
        .replace("http://dx.doi.org/", "")
        .replace("doi:", "")
    )
    # arXiv DOI: strip version suffix (.lower() already normalized case)
    if "10.48550/arxiv." in d:
        d = _ARXIV_DOI_VER_RE.sub(r"\1", d)
    return d or None


def normalize_arxiv_id(arxiv_id: Optional[str]) -> Optional[str]:
    """Strip URL prefix and version suffix (vN).

    Examples:
        "1706.03762v5"                 -> "1706.03762"
        "https://arxiv.org/abs/2401.12345v2" -> "2401.12345"
    """
    if not arxiv_id:
        return None
    s = arxiv_id.strip()
    s = re.sub(r"^(https?://)?arxiv\.org/(abs|pdf)/", "", s)
    s = re.sub(r"\.pdf$", "", s)
    s = re.sub(r"v\d+$", "", s)
    return s or None


def normalize_title(title: Optional[str]) -> str:
    """Lowercase, strip trailing parenthetical, strip all non-alphanumeric.

    Examples:
        "Attention Is All You Need"          -> "attentionisallyouneed"
        "Attention is all you need (Vaswani 2017)" -> "attentionisallyouneed"
    """
    if not title:
        return ""
    s = title.lower()
    s = _TITLE_TRAILING_PAREN_RE.sub("", s)
    return _TITLE_NORMALIZE_RE.sub("", s)


# ============================================================================
# Canonical key generation
# ============================================================================

CanonicalKey = Tuple[str, ...]  # e.g. ("doi", "10.1038/...") or ("title", "norm", 2020)


def canonical_key(paper: UnifiedPaperEntity) -> CanonicalKey:
    """Generate canonical_key for a paper. Priority order matches SA-V4 spec."""
    doi = normalize_doi(paper.doi)
    if doi:
        return ("doi", doi)
    aid = normalize_arxiv_id(paper.arxiv_id)
    if aid:
        return ("arxiv", aid)
    if paper.pmid:
        return ("pmid", str(paper.pmid))
    if paper.openalex_id:
        oid = paper.openalex_id.replace("https://openalex.org/", "")
        return ("openalex", oid)
    if paper.ss_paper_id:
        return ("ss", paper.ss_paper_id)
    if paper.title and paper.year:
        return ("title", normalize_title(paper.title), paper.year)
    # Last resort: title hash (papers with no usable ID + no year)
    return ("hash", hashlib.md5((paper.title or "").encode()).hexdigest()[:16])


# ============================================================================
# E5b guard: same (title, year), different DOIs => NOT the same paper
# ============================================================================

def is_same_physical_paper(a: UnifiedPaperEntity, b: UnifiedPaperEntity) -> bool:
    """Decide if two entities represent the same physical paper.

    Returns False (i.e. reject merge) when both have DOI/arxiv_id but they differ.
    Used as a guard against false-positive merges in title-fuzzy fallback path.
    """
    da, db = normalize_doi(a.doi), normalize_doi(b.doi)
    if da and db and da != db:
        return False
    aa, ab = normalize_arxiv_id(a.arxiv_id), normalize_arxiv_id(b.arxiv_id)
    if aa and ab and aa != ab:
        return False
    return True


# ============================================================================
# Field merge (per 25_round2_synthesis.md §4 priority table)
# ============================================================================

def _pick_non_empty(*values):
    """Return first non-empty value, else None."""
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


# Sanity bound: anything past this year is treated as upstream data corruption
# (OpenAlex has been observed returning year=2025+ for older papers; we refuse
# to overwrite a sane existing year with such values).
_MAX_PLAUSIBLE_YEAR = 2026


def merge_paper_fields(
    existing: UnifiedPaperEntity, new: UnifiedPaperEntity
) -> UnifiedPaperEntity:
    """Merge `new` into `existing` per field priority. Mutates and returns existing.

    Priority guidelines (§4 table):
      - title/authors/year: OpenAlex preferred, else any non-empty
      - abstract: OpenAlex primary, SS fallback (first non-empty wins)
      - citation_count: OpenAlex wins (typically higher than SS)
      - influentialCitationCount: SS-only signal
      - funder/license: CrossRef-only
      - mesh_terms/pmcid: PubMed-only
      - arxiv_categories/comment: arXiv-only

    Sanity guards (added per R1 / Fix #6):
      - `new.year > _MAX_PLAUSIBLE_YEAR` is treated as upstream junk; we keep
        the existing year rather than overwrite with a clearly wrong value.
      - Empty `new.title` / `new.authors` never override a non-empty existing.
        (The original "first non-empty wins" stays in place for the other
        direction.)
    """
    # ---- IDs: take any non-empty ----
    existing.doi = _pick_non_empty(existing.doi, normalize_doi(new.doi))
    existing.arxiv_id = _pick_non_empty(
        existing.arxiv_id, normalize_arxiv_id(new.arxiv_id)
    )
    existing.openalex_id = _pick_non_empty(existing.openalex_id, new.openalex_id)
    existing.ss_paper_id = _pick_non_empty(existing.ss_paper_id, new.ss_paper_id)
    existing.pmid = _pick_non_empty(existing.pmid, new.pmid)
    existing.pmcid = _pick_non_empty(existing.pmcid, new.pmcid)

    # ---- title: OpenAlex preferred, else any non-empty ----
    # Sanity: empty new.title never overrides an existing non-empty title.
    new_title_clean = (new.title or "").strip()
    if not existing.title and new_title_clean:
        existing.title = new.title
    elif (
        "openalex" not in existing.sources
        and "openalex" in new.sources
        and new_title_clean
    ):
        existing.title = new.title

    # ---- abstract: OA primary, SS fallback; first non-empty wins ----
    if not existing.abstract and new.abstract:
        existing.abstract = new.abstract

    # ---- authors: OpenAlex preferred ----
    # Sanity: empty new.authors never overrides existing non-empty authors.
    if not existing.authors and new.authors:
        existing.authors = new.authors
    elif (
        "openalex" not in existing.sources
        and "openalex" in new.sources
        and new.authors
    ):
        existing.authors = new.authors

    # ---- year: any non-empty + plausibility guard ----
    # OpenAlex has been observed returning years past the current date (e.g.
    # `year=2025` for a 2017 paper). Reject such values rather than overwrite.
    if (
        not existing.year
        and isinstance(new.year, int)
        and 0 < new.year <= _MAX_PLAUSIBLE_YEAR
    ):
        existing.year = new.year

    # ---- venue / type: any non-empty ----
    existing.venue = _pick_non_empty(existing.venue, new.venue)
    existing.type = _pick_non_empty(existing.type, new.type)

    # ---- citation_count: OA wins; else max ----
    if "openalex" in new.sources and new.citation_count > 0:
        existing.citation_count = new.citation_count
    elif not existing.citation_count and new.citation_count:
        existing.citation_count = new.citation_count

    # ---- referenced_works_count: max ----
    existing.referenced_works_count = (
        max(existing.referenced_works_count or 0, new.referenced_works_count or 0)
        or None
    )

    # ---- OA-specific ----
    existing.fwci = _pick_non_empty(existing.fwci, new.fwci)
    existing.cited_by_percentile_year = _pick_non_empty(
        existing.cited_by_percentile_year, new.cited_by_percentile_year
    )
    if not existing.topics and new.topics:
        existing.topics = new.topics
    if not existing.keywords and new.keywords:
        existing.keywords = new.keywords
    if not existing.sdgs and new.sdgs:
        existing.sdgs = new.sdgs
    if existing.is_oa is None and new.is_oa is not None:
        existing.is_oa = new.is_oa

    # ---- SS-only ----
    existing.tldr = _pick_non_empty(existing.tldr, new.tldr)
    existing.influential_citation_count = _pick_non_empty(
        existing.influential_citation_count, new.influential_citation_count
    )

    # ---- CrossRef-only ----
    if not existing.funders and new.funders:
        existing.funders = new.funders
    if not existing.license and new.license:
        existing.license = new.license
    existing.clinical_trial_number = _pick_non_empty(
        existing.clinical_trial_number, new.clinical_trial_number
    )

    # ---- PubMed-only ----
    if not existing.mesh_terms and new.mesh_terms:
        existing.mesh_terms = new.mesh_terms
    if not existing.publication_types and new.publication_types:
        existing.publication_types = new.publication_types

    # ---- arXiv-only ----
    if not existing.arxiv_categories and new.arxiv_categories:
        existing.arxiv_categories = new.arxiv_categories
    existing.arxiv_comment = _pick_non_empty(
        existing.arxiv_comment, new.arxiv_comment
    )

    # ---- URLs: any non-empty ----
    existing.doi_url = _pick_non_empty(existing.doi_url, new.doi_url)
    existing.openalex_url = _pick_non_empty(existing.openalex_url, new.openalex_url)
    existing.pdf_url = _pick_non_empty(existing.pdf_url, new.pdf_url)
    existing.pmc_url = _pick_non_empty(existing.pmc_url, new.pmc_url)

    # ---- Skill-internal: keep existing RCS if set, else take new ----
    if existing.rcs is None and new.rcs is not None:
        existing.rcs = new.rcs
        existing.rcs_reasoning = new.rcs_reasoning
        existing.rcs_flag = new.rcs_flag

    # ---- sources list: append non-duplicates (preserve order) ----
    for s in new.sources:
        if s not in existing.sources:
            existing.sources.append(s)

    return existing


# ============================================================================
# Federated dedup
# ============================================================================

def federated_dedup(
    *paper_lists: Iterable[UnifiedPaperEntity],
) -> Dict[CanonicalKey, UnifiedPaperEntity]:
    """Merge papers from N sources into a single KG, deduped by canonical_key.

    E5b guard: if a candidate has same canonical_key as existing but
    `is_same_physical_paper` returns False (DOI/arxiv_id conflict), append as a
    NEW entry with a suffixed key — preserving both as distinct papers.
    """
    kg: Dict[CanonicalKey, UnifiedPaperEntity] = {}
    for lst in paper_lists:
        for p in lst:
            key = canonical_key(p)
            if key not in kg:
                kg[key] = p
            elif is_same_physical_paper(kg[key], p):
                merge_paper_fields(kg[key], p)
            else:
                # E5b: same canonical_key but different DOIs — keep both.
                # Append discriminator to the key.
                suffix = 2
                while (key + (f"v{suffix}",)) in kg:
                    suffix += 1
                kg[key + (f"v{suffix}",)] = p
    return kg


def kg_to_list(
    kg: Dict[CanonicalKey, UnifiedPaperEntity], sort_by: str = "citation_count"
) -> List[UnifiedPaperEntity]:
    """Flatten KG dict to a sorted list. Sort keys: citation_count / year / influential."""
    papers = list(kg.values())
    if sort_by == "citation_count":
        papers.sort(key=lambda p: p.citation_count, reverse=True)
    elif sort_by == "year":
        papers.sort(key=lambda p: p.year or 0, reverse=True)
    elif sort_by == "influential":
        papers.sort(key=lambda p: p.influential_citation_count or 0, reverse=True)
    return papers


# ============================================================================
# CLI
# ============================================================================

def _papers_from_payload(payload) -> List[UnifiedPaperEntity]:
    """Decode a JSON payload into a list of UnifiedPaperEntity.

    Accepts either:
      - a list of paper dicts
      - a dict keyed by canonical_key (or any string) -> paper dict
    """
    from .types import Author

    def _paper(d: Dict) -> UnifiedPaperEntity:
        authors = [
            Author(
                name=a.get("name", "") if isinstance(a, dict) else str(a),
                orcid=a.get("orcid") if isinstance(a, dict) else None,
                affiliation=a.get("affiliation") if isinstance(a, dict) else None,
                country=a.get("country") if isinstance(a, dict) else None,
                is_first=bool(a.get("is_first")) if isinstance(a, dict) else False,
                is_corresponding=bool(a.get("is_corresponding")) if isinstance(a, dict) else False,
            )
            for a in (d.get("authors") or [])
        ]
        return UnifiedPaperEntity(
            doi=d.get("doi"),
            arxiv_id=d.get("arxiv_id"),
            openalex_id=d.get("openalex_id"),
            ss_paper_id=d.get("ss_paper_id"),
            pmid=d.get("pmid"),
            pmcid=d.get("pmcid"),
            title=d.get("title", "") or "",
            abstract=d.get("abstract"),
            authors=authors,
            year=d.get("year"),
            venue=d.get("venue"),
            type=d.get("type"),
            citation_count=int(d.get("citation_count") or 0),
            fwci=d.get("fwci"),
            topics=list(d.get("topics") or []),
            keywords=list(d.get("keywords") or []),
            influential_citation_count=d.get("influential_citation_count"),
            tldr=d.get("tldr"),
            doi_url=d.get("doi_url"),
            sources=list(d.get("sources") or []),
            discovery_path=d.get("discovery_path"),
            is_oa=d.get("is_oa"),
            mesh_terms=list(d.get("mesh_terms") or []),
            publication_types=list(d.get("publication_types") or []),
            arxiv_categories=list(d.get("arxiv_categories") or []),
            arxiv_comment=d.get("arxiv_comment"),
            funders=list(d.get("funders") or []),
            license=list(d.get("license") or []),
            clinical_trial_number=d.get("clinical_trial_number"),
        )

    if isinstance(payload, dict):
        return [_paper(v) for v in payload.values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [_paper(d) for d in payload if isinstance(d, dict)]
    return []


def _paper_to_dict(p: UnifiedPaperEntity) -> Dict:
    return {
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "openalex_id": p.openalex_id,
        "ss_paper_id": p.ss_paper_id,
        "pmid": p.pmid,
        "pmcid": p.pmcid,
        "title": p.title,
        "abstract": p.abstract,
        "authors": [
            {
                "name": a.name,
                "orcid": a.orcid,
                "affiliation": a.affiliation,
                "country": a.country,
                "is_first": a.is_first,
                "is_corresponding": a.is_corresponding,
            }
            for a in (p.authors or [])
        ],
        "year": p.year,
        "venue": p.venue,
        "type": p.type,
        "citation_count": p.citation_count,
        "referenced_works_count": p.referenced_works_count,
        "fwci": p.fwci,
        "cited_by_percentile_year": p.cited_by_percentile_year,
        "topics": p.topics,
        "keywords": p.keywords,
        "sdgs": p.sdgs,
        "is_oa": p.is_oa,
        "tldr": p.tldr,
        "influential_citation_count": p.influential_citation_count,
        "funders": p.funders,
        "license": p.license,
        "clinical_trial_number": p.clinical_trial_number,
        "mesh_terms": p.mesh_terms,
        "publication_types": p.publication_types,
        "arxiv_categories": p.arxiv_categories,
        "arxiv_comment": p.arxiv_comment,
        "doi_url": p.doi_url,
        "openalex_url": p.openalex_url,
        "pdf_url": p.pdf_url,
        "pmc_url": p.pmc_url,
        "rcs": p.rcs,
        "rcs_reasoning": p.rcs_reasoning,
        "rcs_flag": p.rcs_flag,
        "sources": p.sources,
        "discovery_path": p.discovery_path,
    }


def _canonical_key_str(key: CanonicalKey) -> str:
    """Render a canonical_key tuple as a stable string for JSON dict keys."""
    return "|".join(str(part) for part in key)


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Federated KG dedup + merge across N source JSON files. Each input "
            "file may contain a list of papers or a dict keyed by canonical_key."
        )
    )
    parser.add_argument(
        "--input-files",
        required=True,
        nargs="+",
        help="One or more JSON files from openalex_helper / ss_helper / "
        "crossref_helper / pubmed_helper / arxiv_helper.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Where to write kg.json (dict keyed by canonical_key string).",
    )
    parser.add_argument(
        "--as-list",
        action="store_true",
        help="Emit a sorted list (by citation_count) instead of a keyed dict.",
    )
    args = parser.parse_args()

    paper_lists: List[List[UnifiedPaperEntity]] = []
    for path in args.input_files:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        papers = _papers_from_payload(payload)
        if not papers:
            print(
                f"federated_kg_resolver: WARNING {path} produced 0 papers; skipping.",
                file=sys.stderr,
            )
            continue
        paper_lists.append(papers)

    if not paper_lists:
        sys.exit("federated_kg_resolver: no usable papers loaded from --input-files")

    kg = federated_dedup(*paper_lists)

    if args.as_list:
        out_payload = [_paper_to_dict(p) for p in kg_to_list(kg)]
    else:
        out_payload = {
            _canonical_key_str(key): _paper_to_dict(paper)
            for key, paper in kg.items()
        }

    from pathlib import Path

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"federated_kg_resolver: merged {sum(len(l) for l in paper_lists)} papers "
        f"from {len(paper_lists)} source(s) -> {len(kg)} unique -> {out_path}"
    )
