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

from .types import Author, Config, UnifiedPaperEntity

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

# Module-level cache of the SS api key, captured at init() time. The v2.2 search
# path needs the raw key for its own HTTP requests to the bulk endpoint (the SDK
# does not reliably expose the configured key as a public attribute), so we
# stash it here rather than reaching into SDK internals. None = no key (search
# will 429 on the shared pool; R-06).
_api_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Init & client management
# ---------------------------------------------------------------------------


def init(config: Config) -> None:
    """Initialise the module-level SS client from Config.

    Idempotent: safe to call multiple times.
    """
    global _sch, _api_key
    api_key = (config.semantic_scholar_api_key or "").strip() or None
    _sch = SemanticScholar(api_key=api_key)
    _api_key = api_key  # cache for the v2.2 search path's own HTTP requests


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
# Independent search (v2.2) — SS as a PRIMARY source.
#
# This is the ONLY independent-search path in ss_helper. It is fully additive:
# enrich_with_metadata / abstract_fallback / cross_validate_citation above are
# byte-for-byte unchanged and remain the default L3-enrichment behavior.
#
# Endpoint discipline (R-07): we use ONLY /paper/search/bulk + citation sorting.
# The relevance endpoint (paper/search) is BANNED as a primary path — it is
# low-quality across disciplines and rate-limit fragile. The bulk endpoint
# returns up to 1000 records/page sorted server-side and is the only SS path
# good enough to act as a primary source (verified 2026-06-25: query "prospect
# theory" sort=citationCount:desc -> K&T 1979 ranked #1, total 24358).
#
# Multi-strategy double-sort: mirrors openalex_helper.double_sort_search so the
# two primary sources behave consistently. SS bulk supports a small set of sort
# keys; we use:
#   - citationCount:desc   (impact — the R-07-mandated primary ordering)
#   - publicationDate:desc (recency — analogue of OA publication_date:desc)
#   - <no sort>            (SS bulk's own text-match ordering — analogue of OA
#                           relevance; we do NOT touch the relevance ENDPOINT,
#                           only the default ordering of the bulk endpoint).
# Papers appearing in >=2 strategies get an appearance-count boost, identical in
# spirit to the OpenAlex cross-strategy boost.
#
# Rate limit: SS is 1 RPS even with a key, and 429s immediately with NO key on
# the shared pool (R-06). Each bulk page is one HTTP request; we sleep
# _RATE_LIMIT_SLEEP between requests to stay polite across strategies/pages.
# ---------------------------------------------------------------------------

import os as _os  # noqa: E402  (local alias; avoid touching module top imports)

_SS_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"

# Fields requested from the bulk endpoint. publicationVenue is requested as the
# nested object so we get .issn (R-08: SS ISSN lives ONLY in
# publicationVenue.issn, ~2/3 coverage; externalIds has no ISSN). authors.name +
# authors.authorId give us a usable author list.
# NOTE (verified 2026-06-25): the bulk endpoint REJECTS `tldr` ("Unrecognized or
# unsupported fields: [tldr]" -> HTTP 400). TLDR is only available via the
# per-paper / batch graph endpoints, so search records carry no tldr; the
# enrich path (which DOES support tldr) backfills it later if needed.
_SEARCH_FIELDS = (
    "paperId,externalIds,title,abstract,year,venue,publicationVenue,"
    "citationCount,influentialCitationCount,openAccessPdf,authors.name,authors.authorId"
)

# SS bulk supported sort keys we use. None = the endpoint's default ordering.
_SEARCH_STRATEGIES = ("citationCount:desc", "publicationDate:desc", None)

# Hard cap on pages fetched per strategy, so a huge result set can't run away.
_MAX_PAGES_PER_STRATEGY = 5
# SS bulk returns up to 1000/page; we request this many and slice to the caller's
# limit. (The API ignores values >1000.)
_BULK_PAGE_SIZE = 1000


def _api_key_from_config() -> Optional[str]:
    """The SS api key the module was initialised with, if any.

    Reads the key cached by init() (see module-level _api_key), falling back to
    the SEMANTIC_SCHOLAR_API_KEY env var when init() ran without one. This keeps
    search() using the SAME credential as enrich/validate (R-06: SS as a primary
    source MUST have a key or it 429s on the shared pool)."""
    key = _api_key or _os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    return (key or "").strip() or None


def _ss_doi_from_external_ids(ext: object) -> Optional[str]:
    """Extract a bare lowercase DOI from a bulk record's externalIds dict."""
    if not ext:
        return None
    if isinstance(ext, dict):
        doi = ext.get("DOI") or ext.get("doi")
    else:
        doi = getattr(ext, "DOI", None) or getattr(ext, "doi", None)
    return _normalize_doi_for_lookup(doi) if doi else None


def _ss_arxiv_from_external_ids(ext: object) -> Optional[str]:
    """Extract a bare arXiv id (no version suffix) from externalIds.ArXiv."""
    if not isinstance(ext, dict):
        return None
    ax = ext.get("ArXiv") or ext.get("arXiv") or ext.get("arxiv")
    if not ax:
        return None
    ax = str(ax).strip()
    return ax.split("v")[0] if "v" in ax else ax


def _ss_pmid_from_external_ids(ext: object) -> Optional[str]:
    if not isinstance(ext, dict):
        return None
    pmid = ext.get("PubMed") or ext.get("pubmed")
    return str(pmid).strip() if pmid else None


def _ss_issn(record: Dict) -> Optional[str]:
    """Pull the journal ISSN from a bulk record's publicationVenue (R-08).

    SS exposes ISSN ONLY under publicationVenue.issn (present ~2/3 of the time);
    externalIds never carries it. Returns the primary issn, ignoring
    alternate_issns (kept simple — the downstream SJR join keys on one ISSN)."""
    pv = record.get("publicationVenue")
    if isinstance(pv, dict):
        issn = pv.get("issn")
        if issn:
            return str(issn).strip() or None
    return None


def _ss_record_to_entity(record: Dict) -> UnifiedPaperEntity:
    """Convert one SS bulk-search record into a UnifiedPaperEntity.

    Produces the SAME entity shape openalex_helper emits, so the federated KG
    resolver ingests SS-search JSON exactly like openalex.json. Reuses the
    module's existing DOI/externalIds conventions. sources=["semantic_scholar"]
    marks provenance (this entity ORIGINATED from SS, vs being SS-enriched)."""
    ext = record.get("externalIds") or {}

    authors: List[Author] = []
    for a in record.get("authors") or []:
        if isinstance(a, dict):
            name = a.get("name") or ""
        else:
            name = str(a)
        if name:
            authors.append(Author(name=name))

    # Venue: prefer the structured publicationVenue.name, fall back to the flat
    # venue string the bulk endpoint also returns.
    venue = None
    pv = record.get("publicationVenue")
    if isinstance(pv, dict):
        venue = pv.get("name")
    if not venue:
        venue = record.get("venue") or None

    # Open access pdf -> is_oa + pdf_url, matching the OA entity convention.
    oa_pdf = record.get("openAccessPdf") or {}
    pdf_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None

    # TLDR text (auxiliary, display-only — same handling as enrich path).
    tldr_text = None
    tldr_obj = record.get("tldr")
    if isinstance(tldr_obj, dict):
        tldr_text = tldr_obj.get("text") or None

    ic = record.get("influentialCitationCount")

    return UnifiedPaperEntity(
        doi=_ss_doi_from_external_ids(ext),
        arxiv_id=_ss_arxiv_from_external_ids(ext),
        ss_paper_id=record.get("paperId"),
        pmid=_ss_pmid_from_external_ids(ext),
        title=record.get("title") or "",
        abstract=record.get("abstract") or None,
        authors=authors,
        year=record.get("year"),
        venue=venue,
        issn=_ss_issn(record),
        citation_count=int(record.get("citationCount") or 0),
        influential_citation_count=int(ic) if ic is not None else None,
        tldr=tldr_text,
        is_oa=bool(pdf_url) if pdf_url else None,
        pdf_url=pdf_url,
        doi_url=(f"https://doi.org/{_ss_doi_from_external_ids(ext)}"
                 if _ss_doi_from_external_ids(ext) else None),
        sources=["semantic_scholar"],
    )


def _bulk_search_one_strategy(
    query: str,
    sort: Optional[str],
    *,
    api_key: Optional[str],
    year_min: Optional[int],
    year_max: Optional[int],
    limit: int,
    session=None,
) -> List[UnifiedPaperEntity]:
    """Run a single bulk-search strategy (one sort key) and return entities.

    Paginates via the bulk endpoint's continuation `token` up to limit /
    _MAX_PAGES_PER_STRATEGY. Network/HTTP errors degrade to whatever was
    collected so far (never raises) — a flaky strategy must not kill the run."""
    import requests  # local import: keeps module top imports byte-identical

    headers = {"x-api-key": api_key} if api_key else {}
    params: Dict[str, object] = {
        "query": query,
        "fields": _SEARCH_FIELDS,
    }
    if sort:
        params["sort"] = sort
    # SS bulk year filter is a single "year" param accepting ranges like
    # "2015-2020", "2015-", or "-2020".
    if year_min is not None or year_max is not None:
        lo = str(year_min) if year_min is not None else ""
        hi = str(year_max) if year_max is not None else ""
        params["year"] = f"{lo}-{hi}"

    sess = session or requests
    entities: List[UnifiedPaperEntity] = []
    token: Optional[str] = None
    for page in range(_MAX_PAGES_PER_STRATEGY):
        if token:
            params["token"] = token
        try:
            res = sess.get(_SS_BULK_URL, params=params, headers=headers, timeout=60)
        except Exception:
            break
        if res.status_code != 200:
            # 429 (no key / over rate) or transient — stop this strategy.
            break
        try:
            data = res.json()
        except Exception:
            break
        for rec in data.get("data") or []:
            entities.append(_ss_record_to_entity(rec))
            if len(entities) >= limit:
                return entities[:limit]
        token = data.get("token")
        if not token:
            break
        # Politeness between paged requests (SS 1 RPS).
        time.sleep(_RATE_LIMIT_SLEEP)
    return entities[:limit]


def search(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    total_per_strategy: int = 50,
    session=None,
) -> List[UnifiedPaperEntity]:
    """Independent SS primary search (multi-strategy double-sort, bulk endpoint).

    Mirrors openalex_helper.double_sort_search: runs each strategy, merges by
    canonical paper id, and boosts rank for papers appearing in >=2 strategies.
    Returns papers sorted by (appearance_count desc, citation_count desc) — the
    same ordering contract as OpenAlex double-sort, so downstream code can treat
    the two primary sources interchangeably.

    No key -> SS 429s on the shared pool (R-06); strategies then return empty and
    this returns []. Callers should ensure init(config) ran with a key for SS as
    a primary source.
    """
    api_key = _api_key_from_config()

    seen: Dict[str, "tuple[UnifiedPaperEntity, int]"] = {}
    for i, sort in enumerate(_SEARCH_STRATEGIES):
        strat = _bulk_search_one_strategy(
            query,
            sort,
            api_key=api_key,
            year_min=year_min,
            year_max=year_max,
            limit=total_per_strategy,
            session=session,
        )
        for p in strat:
            pid = p.paper_id
            if pid in seen:
                prev_paper, count = seen[pid]
                seen[pid] = (prev_paper, count + 1)
            else:
                seen[pid] = (p, 1)
        # Sleep between strategies (each strategy already slept between its own
        # pages; this guards the strategy boundary). Skip after the last.
        if i < len(_SEARCH_STRATEGIES) - 1:
            time.sleep(_RATE_LIMIT_SLEEP)

    return [
        p
        for p, _ in sorted(
            seen.values(), key=lambda x: (-x[1], -(x[0].citation_count or 0))
        )
    ]


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


def _search_entity_to_dict(p: UnifiedPaperEntity) -> Dict:
    """Full serialisation of a search-produced entity.

    Unlike _entity_to_dict (which only emits the few enrich-touched fields), the
    search path is a PRIMARY source, so it emits the same broad field set as
    openalex_helper's output (authors, venue, issn, is_oa, pdf_url, ...). This
    lets federated_kg_resolver ingest SS-search JSON exactly like openalex.json.
    Mirrors openalex_helper._to_dict (entity.__dict__ with Author flattening)."""
    d: Dict = {}
    for f, v in p.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        else:
            d[f] = v
    return d


if __name__ == "__main__":
    import argparse
    import json
    import sys

    from .config import load_config

    parser = argparse.ArgumentParser(
        description="SS helper — L3 enricher (enrich/validate) + v2.2 primary search."
    )
    # --search makes this an INDEPENDENT primary-source search. When absent, the
    # CLI behaves exactly as before (enrich/validate on --input-file), so all
    # existing invocations are byte-for-byte unchanged.
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Run an independent SS primary search (bulk endpoint, multi-strategy "
        "citation double-sort). Outputs UnifiedPaperEntity[] like openalex_helper.",
    )
    parser.add_argument(
        "--input-file",
        help="JSON file with a list of UnifiedPaperEntity-like dicts (must "
        "include at least doi, title, citation_count). Required for enrich/validate.",
    )
    parser.add_argument(
        "--mode",
        choices=["enrich", "validate"],
        default="enrich",
        help="enrich = add influCit/abstract/tldr; validate = list citation conflicts. "
        "(Ignored when --search is used.)",
    )
    parser.add_argument(
        "--year-min", type=int, help="search: minimum publication year (inclusive)."
    )
    parser.add_argument(
        "--year-max", type=int, help="search: maximum publication year (inclusive)."
    )
    parser.add_argument(
        "--n",
        type=int,
        default=50,
        dest="total_per_strategy",
        help="search: papers per strategy before cross-strategy merge (default 50).",
    )
    parser.add_argument(
        "--output-file",
        help="Where to write the JSON output (defaults to stdout).",
    )
    args = parser.parse_args()

    init(load_config())

    if args.search:
        # Independent primary search path (v2.2).
        results = search(
            args.search,
            year_min=args.year_min,
            year_max=args.year_max,
            total_per_strategy=args.total_per_strategy,
        )
        output = [_search_entity_to_dict(p) for p in results]
    else:
        # Existing enrich/validate path — unchanged.
        if not args.input_file:
            parser.error("--input-file is required for enrich/validate (or use --search).")
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
