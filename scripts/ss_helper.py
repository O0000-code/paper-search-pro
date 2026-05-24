"""Semantic Scholar helper: enrichment-only (NO independent search).

Architecture (v2.0): L3 enricher. On top of OpenAlex base entities, adds:
- influentialCitationCount   (unique signal, OpenAlex has nothing like it)
- abstract fallback           (when OpenAlex inverted_index reconstruct is null)
- TLDR auxiliary metadata     (display-only — DO NOT pass into AI classifier;
                               see 22_ss_research.md §4.3 and 25_round2 §4)
- cross-source citation_count validation (Audit-tier data quality check)

NOT included: independent search, recommendations (SS backend off-target —
see 20_ss_sdk_test.md §4), DOI-only lookup for arXiv DOIs (SS 100% 404 —
see 24_v1_l3_enrichment_test.md §1).

Rate limit: 1 RPS strict (SS has no paid tier; key only buys auth-tier shape
not higher throughput). batch get_papers IS a single HTTP request (verified
2026-05-21: 2 DOIs in 528ms), so we use it whenever possible and only fall
back to per-paper get_paper() — which DOES need 1.1s sleep between calls —
when batch fails.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from semanticscholar import SemanticScholar

from .types import Config, UnifiedPaperEntity

# SS 1 RPS sustained; this margin avoids 429 in per-paper fallback loops.
_RATE_LIMIT_SLEEP = 1.1

# Minimal field set for enrichment — saves payload size and stays well below
# the 500-field SS limit. Fields not requested return None on the Paper obj.
_ENRICHMENT_FIELDS = [
    "paperId",
    "externalIds",
    "title",
    "year",
    "abstract",
    "tldr",
    "citationCount",
    "influentialCitationCount",
    "openAccessPdf",
]

_CITATION_FIELDS = ["paperId", "externalIds", "citationCount"]

# Citation_count delta above which we flag a cross-source conflict (per
# 24_v1_l3_enrichment_test.md §3.1: 7/20 papers exceeded 30% in real data;
# threshold catches arXiv-fallback DOI artefacts and old-paper coverage gaps).
_CITATION_CONFLICT_THRESHOLD_PCT = 30.0

# Module-level singleton client (avoid SDK re-init per call).
_sch: Optional[SemanticScholar] = None


# ---------------------------------------------------------------------------
# Init & client management
# ---------------------------------------------------------------------------


def init(config: Config) -> None:
    """Initialise the module-level SS client from Config.

    Idempotent: safe to call multiple times.
    """
    global _sch
    api_key = (config.semantic_scholar_api_key or "").strip() or None
    _sch = SemanticScholar(api_key=api_key)


def _get_client() -> SemanticScholar:
    """Return the lazily-initialised SS client. Falls back to no-key if init
    was never called (useful in tests; SS still works without a key, just
    slower)."""
    global _sch
    if _sch is None:
        _sch = SemanticScholar(api_key=None)
    return _sch


# ---------------------------------------------------------------------------
# DOI preparation
# ---------------------------------------------------------------------------


def _doi_for_ss(doi: Optional[str]) -> Optional[str]:
    """Convert an OpenAlex-format DOI into the form SS accepts.

    Returns None for inputs SS cannot resolve, so the caller can skip:
    - empty / None DOI
    - arXiv DOIs (10.48550/arXiv.* — verified 2026-05-21: 100% 404 in SS;
      cf. 24_v1_l3_enrichment_test.md §1 #2)

    For valid DOIs, returns "DOI:<lowercase-doi>" — the SS-required prefix.
    """
    if not doi:
        return None
    doi_lower = doi.strip().lower()
    # Strip a possible "https://doi.org/" prefix defensively
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if doi_lower.startswith(prefix):
            doi_lower = doi_lower[len(prefix):]
            break
    if "arxiv" in doi_lower:
        # SS does not index arXiv DOIs reliably (see 20_ss_sdk_test.md F5/F7).
        return None
    return f"DOI:{doi_lower}"


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------


def _normalize_doi_for_lookup(doi: Optional[str]) -> Optional[str]:
    """Strip URL prefixes and lowercase — for dict-key matching against SS externalIds.DOI."""
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break
    return d or None


def _ss_paper_doi(sp: object) -> Optional[str]:
    """Extract DOI from an SS Paper object's externalIds, normalised for matching."""
    if sp is None:
        return None
    ext = getattr(sp, "externalIds", None)
    if not ext:
        return None
    if isinstance(ext, dict):
        doi = ext.get("DOI") or ext.get("doi")
    else:
        # Some SDK paths return an object with attribute access
        doi = getattr(ext, "DOI", None) or getattr(ext, "doi", None)
    return _normalize_doi_for_lookup(doi) if doi else None


def enrich_with_metadata(
    papers: List[UnifiedPaperEntity],
) -> List[UnifiedPaperEntity]:
    """Batch-enrich a list of UnifiedPaperEntity with SS-only fields.

    Mutates entities in place AND returns the same list (so callers can
    one-line `papers = ss_helper.enrich_with_metadata(papers)`).

    Per entity, when SS has data we add:
    - p.influential_citation_count   (the unique L3 signal)
    - p.ss_paper_id                  (SS hex paperId)
    - p.abstract                     (only if OpenAlex left it None)
    - p.tldr                         (display-only auxiliary metadata)
    - p.sources                      (appends "semantic_scholar")

    Entities whose DOI is empty, missing, or arXiv-form are silently skipped
    — they remain unchanged in the returned list.

    CRITICAL — DOI-based matching (not positional zip):
    The SS SDK's batch get_papers() can silently drop DOIs that are not found
    (verified 2026-05-21: 3-DOI input with K&T 1979 elided returns 2-element
    list). Positional zip would then mis-attach BNT162b2 abstract to K&T 1979.
    We index returned papers by DOI from their externalIds and match
    explicitly — papers not found stay unchanged.
    """
    eligible = [p for p in papers if _doi_for_ss(p.doi)]
    if not eligible:
        return papers

    sch = _get_client()
    ids = [_doi_for_ss(p.doi) for p in eligible]
    ss_papers: List[Optional[object]] = []

    # SS batch get_papers IS a single HTTP request (one rate-limit slot, no
    # internal sleep needed). Fall back to per-paper get_paper() only if
    # the whole batch fails — and there we DO need 1.1s sleep per call.
    try:
        # The SDK returns a list[Optional[Paper]]; not guaranteed aligned with
        # input ids — SS silently drops not-found DOIs (publisher takedown,
        # not indexed). See test_ss_helper for K&T 1979 evidence.
        ss_papers = list(sch.get_papers(ids, fields=_ENRICHMENT_FIELDS))
    except Exception:
        for sid in ids:
            try:
                ss_papers.append(sch.get_paper(sid, fields=_ENRICHMENT_FIELDS))
            except Exception:
                ss_papers.append(None)
            time.sleep(_RATE_LIMIT_SLEEP)

    # Sanity assertion: batch must never return MORE than requested (would
    # indicate SDK contract break). Returning FEWER is the documented case.
    if len(ss_papers) > len(ids):
        import logging
        logging.getLogger(__name__).warning(
            "SS get_papers returned %d papers for %d ids (unexpected — SDK should"
            " return <= input). Falling back to no enrichment to avoid misattribution.",
            len(ss_papers), len(ids),
        )
        return papers
    if len(ss_papers) < len(ids):
        import logging
        logging.getLogger(__name__).info(
            "SS get_papers returned %d papers for %d ids (%d DOIs not indexed). "
            "Using DOI-based matching to attribute correctly.",
            len(ss_papers), len(ids), len(ids) - len(ss_papers),
        )

    # Build DOI -> SS paper dict. We try the externalIds.DOI first; some SDK
    # variants only populate a .DOI top-level field, so we fall back to that.
    ss_by_doi: Dict[str, object] = {}
    for sp in ss_papers:
        if sp is None:
            continue
        sp_doi = _ss_paper_doi(sp)
        if sp_doi:
            ss_by_doi[sp_doi] = sp

    for p in eligible:
        # Lookup by p.doi (normalized) — only inject if SS actually returned
        # this paper's DOI. If not found, K&T 1979 stays UNCHANGED rather
        # than getting the next-in-list paper's data attached.
        lookup_doi = _normalize_doi_for_lookup(p.doi)
        if not lookup_doi:
            continue
        sp = ss_by_doi.get(lookup_doi)
        if sp is None:
            # Paper-not-found in SS (publisher takedown, not indexed, etc.).
            # Log at info level — this is expected for K&T 1979 etc.
            import logging
            logging.getLogger(__name__).info(
                "SS lookup returned no paper for DOI %s — leaving entity unchanged",
                lookup_doi,
            )
            continue
        try:
            # influentialCitationCount — the SS-unique signal (OpenAlex has
            # nothing comparable; cf. 22_ss_research.md §3, §4.3).
            ic = getattr(sp, "influentialCitationCount", None)
            if ic is not None:
                p.influential_citation_count = int(ic)

            # SS paperId — keep for cross-reference debugging.
            sp_id = getattr(sp, "paperId", None)
            if sp_id:
                p.ss_paper_id = sp_id

            # Abstract fallback — only fill if OA left it None. Empty strings
            # (which SS sometimes returns on takedown) are treated as falsy.
            ss_abstract = getattr(sp, "abstract", None)
            if not p.abstract and ss_abstract:
                p.abstract = ss_abstract

            # TLDR — display-only auxiliary metadata. p.tldr stores the text
            # only (Tldr SDK object's .text). Per user directive (22 §4.3,
            # 25 §4): TLDR is for HTML display, NOT for the RCS classifier.
            tldr_obj = getattr(sp, "tldr", None)
            if tldr_obj is not None:
                tldr_text = getattr(tldr_obj, "text", None)
                if tldr_text:
                    p.tldr = tldr_text

            # Mark provenance.
            if "semantic_scholar" not in p.sources:
                p.sources.append("semantic_scholar")
        except (AttributeError, TypeError):
            # Any SDK-quirk attribute miss → leave the entity alone and move
            # on; never let one bad paper kill the batch.
            continue

    return papers


def abstract_fallback(paper: UnifiedPaperEntity) -> Optional[str]:
    """Single-paper abstract fallback. Useful for ad-hoc re-tries.

    Returns:
    - existing paper.abstract if already set
    - SS abstract if found
    - SS tldr.text if SS abstract is None but a TLDR exists
    - None otherwise (publisher takedown / not indexed / arXiv DOI)
    """
    if paper.abstract:
        return paper.abstract
    sid = _doi_for_ss(paper.doi)
    if not sid:
        return None
    sch = _get_client()
    try:
        sp = sch.get_paper(sid, fields=["abstract", "tldr"])
    except Exception:
        return None
    ss_abstract = getattr(sp, "abstract", None)
    if ss_abstract:
        return ss_abstract
    tldr_obj = getattr(sp, "tldr", None)
    if tldr_obj is not None:
        return getattr(tldr_obj, "text", None) or None
    return None


def cross_validate_citation(
    papers: List[UnifiedPaperEntity],
) -> List[Dict]:
    """Cross-source citation_count validation.

    Compares the OpenAlex citation_count (already on the entity) against the
    SS citationCount fetched live. Returns the list of conflicts where the
    relative delta exceeds 30% — typically surfaces arXiv-fallback DOI
    artefacts (OA fallback record severely under-counted), old papers with
    SS coverage gaps, or possible OA double-counting.

    Each conflict dict has the keys:
        paper_id, title (truncated to 80 chars), oa_count, ss_count, delta_pct.
    """
    eligible = [
        p
        for p in papers
        if _doi_for_ss(p.doi) and (p.citation_count or 0) > 0
    ]
    if not eligible:
        return []

    sch = _get_client()
    ids = [_doi_for_ss(p.doi) for p in eligible]
    try:
        ss_papers = list(sch.get_papers(ids, fields=_CITATION_FIELDS))
    except Exception:
        return []

    # Same DOI-key matching as enrich_with_metadata — guard against SS silently
    # dropping not-found DOIs and zip mis-attribution.
    ss_by_doi: Dict[str, object] = {}
    for sp in ss_papers:
        if sp is None:
            continue
        sp_doi = _ss_paper_doi(sp)
        if sp_doi:
            ss_by_doi[sp_doi] = sp

    conflicts: List[Dict] = []
    for p in eligible:
        lookup_doi = _normalize_doi_for_lookup(p.doi)
        sp = ss_by_doi.get(lookup_doi) if lookup_doi else None
        if sp is None:
            continue
        ss_count = getattr(sp, "citationCount", None)
        if ss_count is None:
            continue
        oa_count = p.citation_count or 0
        if oa_count == 0:
            continue
        delta_pct = abs(oa_count - ss_count) / oa_count * 100
        if delta_pct > _CITATION_CONFLICT_THRESHOLD_PCT:
            conflicts.append(
                {
                    "paper_id": p.paper_id,
                    "title": (p.title or "")[:80],
                    "oa_count": oa_count,
                    "ss_count": int(ss_count),
                    "delta_pct": round(delta_pct, 1),
                }
            )
    return conflicts


# ---------------------------------------------------------------------------
# CLI entry point — light glue for ad-hoc invocation.
# ---------------------------------------------------------------------------


def _entity_from_dict(d: Dict) -> UnifiedPaperEntity:
    """Reconstruct a UnifiedPaperEntity from a JSON dict.

    Only the fields ss_helper actually reads/writes are required: doi,
    title, citation_count. Everything else is best-effort.
    """
    return UnifiedPaperEntity(
        doi=d.get("doi"),
        arxiv_id=d.get("arxiv_id"),
        openalex_id=d.get("openalex_id"),
        ss_paper_id=d.get("ss_paper_id"),
        title=d.get("title", "") or "",
        abstract=d.get("abstract"),
        year=d.get("year"),
        citation_count=int(d.get("citation_count") or 0),
        influential_citation_count=d.get("influential_citation_count"),
        tldr=d.get("tldr"),
        sources=list(d.get("sources") or []),
    )


def _entity_to_dict(p: UnifiedPaperEntity) -> Dict:
    """Serialise only the fields ss_helper might have touched."""
    return {
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "openalex_id": p.openalex_id,
        "ss_paper_id": p.ss_paper_id,
        "title": p.title,
        "abstract": p.abstract,
        "year": p.year,
        "citation_count": p.citation_count,
        "influential_citation_count": p.influential_citation_count,
        "tldr": p.tldr,
        "sources": p.sources,
    }


if __name__ == "__main__":
    import argparse
    import json
    import sys

    from .config import load_config

    parser = argparse.ArgumentParser(
        description="SS enrichment helper — L3 enricher, not an independent search."
    )
    parser.add_argument(
        "--input-file",
        required=True,
        help="JSON file with a list of UnifiedPaperEntity-like dicts (must "
        "include at least doi, title, citation_count).",
    )
    parser.add_argument(
        "--mode",
        choices=["enrich", "validate"],
        default="enrich",
        help="enrich = add influCit/abstract/tldr; validate = list citation conflicts.",
    )
    parser.add_argument(
        "--output-file",
        help="Where to write the JSON output (defaults to stdout).",
    )
    args = parser.parse_args()

    init(load_config())

    with open(args.input_file, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        sys.exit("input-file must contain a JSON list of paper dicts")

    entities = [_entity_from_dict(d) for d in raw]

    if args.mode == "enrich":
        enrich_with_metadata(entities)
        output = [_entity_to_dict(p) for p in entities]
    else:  # validate
        output = cross_validate_citation(entities)

    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        print(payload)
