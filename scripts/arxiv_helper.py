"""arXiv helper: L2 Freshness Sentinel.

Architecture (v2.0): arXiv unique value is the T-0~T-4 window (OpenAlex indexing
lags 4-5 days). Beyond that, all arXiv papers also appear in OpenAlex
(SA-V2 实测: 39/40 = 98% arXiv "unique" 都在 OpenAlex 全局可查).

Use cases:
1. search_freshness_window(query, days=4) — get recent preprints OA hasn't indexed
2. normalize_arxiv_doi(doi) — handle the lowercase/uppercase X chaos
3. search_recent(query, ...) — general arXiv search for Audit-tier
4. get_by_arxiv_id(id) — single paper lookup

Rate limit: arXiv enforces 1 req per 3 seconds. arxiv SDK + delay_seconds=4 handles this.
Category filter: cs.* / math.* / q-bio.* / q-fin.* / econ.* / stat.* — pick conservatively
to avoid noise like reactor experiments when searching social science queries (Q4 实测).

Reference: Round-2 §3.2 "arXiv = Freshness Sentinel"; SA-V2 实测 24_v2_l2_booster_test.md §4.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import arxiv

from .types import Author, Config, UnifiedPaperEntity


# =============================================================================
# Category whitelists
# =============================================================================
# DEFAULT_CATEGORIES: safe CS / math / stats / quant-bio / quant-fin / econ.
# SA-V2 §3.4 实测: Q4 "prospect theory" without cat filter returns reactor
# experiments named "PROSPECT" — the cat filter is the only defense.
DEFAULT_CATEGORIES: List[str] = [
    "cs.*",
    "math.*",
    "stat.*",
    "q-bio.*",
    "q-fin.*",
    "econ.*",
]

# ALL_CATEGORIES: include physics / astro / cond-mat / hep when user explicitly
# searches physics. Caller must opt in — DEFAULT excludes physics on purpose.
ALL_CATEGORIES: List[str] = DEFAULT_CATEGORIES + [
    "physics.*",
    "astro-ph.*",
    "cond-mat.*",
    "hep-th",
    "hep-ph",
    "hep-ex",
    "hep-lat",
    "gr-qc",
    "nlin.*",
    "nucl-th",
    "nucl-ex",
    "quant-ph",
    "eess.*",
]


# =============================================================================
# SDK client (configurable delay_seconds — arXiv ToU requires >= 3s)
# =============================================================================

_DELAY_SECONDS: float = 4.0  # 1s buffer above arXiv's 3s minimum
_PAGE_SIZE: int = 100        # SA-V2: page_size=100 + 4s delay lets 30 results finish in 5-13s


def init(config: Optional[Config] = None) -> None:
    """arXiv requires no API key. Provided for interface symmetry with other helpers.

    Optionally read `arxiv_delay_seconds` from Config if present (not in v2.0 schema yet,
    but reserved for future tightening).
    """
    global _DELAY_SECONDS
    if config is not None:
        # Reserved: config.arxiv_delay_seconds (not currently in types.Config)
        custom_delay = getattr(config, "arxiv_delay_seconds", None)
        if custom_delay and float(custom_delay) >= 3.0:
            _DELAY_SECONDS = float(custom_delay)


def _client() -> arxiv.Client:
    """Build a fresh arxiv.Client with our rate-limit defaults."""
    return arxiv.Client(page_size=_PAGE_SIZE, delay_seconds=_DELAY_SECONDS, num_retries=3)


# =============================================================================
# DOI / ID normalization
# =============================================================================

# Matches '10.48550/arxiv.<id>' (case-insensitive on the 'arXiv' literal) optionally
# followed by a vN suffix. Group 1 captures the bare arxiv_id.
_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.([\w\.\-/]+?)(?:v\d+)?$", re.IGNORECASE)

# Matches a bare arxiv id (with optional vN). Accepts both new style (YYMM.NNNNN)
# and legacy (hep-th/9707234).
_ARXIV_ID_RE = re.compile(r"^([\w\.\-/]+?)(?:v\d+)?$")


def normalize_arxiv_doi(doi: str) -> str:
    """Convert any arXiv DOI variant to canonical lowercase form (no version suffix).

    Examples:
        '10.48550/arXiv.1706.03762v5' -> '10.48550/arxiv.1706.03762'
        '10.48550/ARXIV.1706.03762'   -> '10.48550/arxiv.1706.03762'
        '10.48550/arxiv.hep-th/9707234v2' -> '10.48550/arxiv.hep-th/9707234'

    For non-arXiv DOIs, returns lowercase original (no other normalization).
    """
    if not doi:
        return doi
    m = _ARXIV_DOI_RE.match(doi.strip())
    if m:
        return f"10.48550/arxiv.{m.group(1).lower()}"
    return doi.strip().lower()


def extract_arxiv_id(arxiv_url_or_id: str) -> Optional[str]:
    """Extract canonical arxiv_id (without version) from URL, raw ID, or entry_id.

    Examples:
        'http://arxiv.org/abs/1706.03762v5' -> '1706.03762'
        'https://arxiv.org/abs/2605.21489'  -> '2605.21489'
        '1706.03762v7'                       -> '1706.03762'
        'hep-th/9707234v2'                   -> 'hep-th/9707234'  (legacy form)
    """
    if not arxiv_url_or_id:
        return None
    s = arxiv_url_or_id.strip()
    # Strip URL prefix if present
    if "arxiv.org/abs/" in s:
        s = s.split("arxiv.org/abs/", 1)[1]
    elif "arxiv.org/pdf/" in s:
        s = s.split("arxiv.org/pdf/", 1)[1]
        # PDF URLs may end in .pdf
        s = s.rsplit(".pdf", 1)[0]
    m = _ARXIV_ID_RE.match(s)
    return m.group(1) if m else None


# =============================================================================
# Conversion: arxiv.Result -> UnifiedPaperEntity
# =============================================================================


def _to_entity(r: arxiv.Result) -> UnifiedPaperEntity:
    """Translate a single arxiv.Result into the unified entity schema."""
    arxiv_id = extract_arxiv_id(r.entry_id)
    # Construct canonical lowercase arXiv DOI (since the SDK r.doi field is often None)
    doi = normalize_arxiv_doi(f"10.48550/arxiv.{arxiv_id}") if arxiv_id else None

    authors = [Author(name=str(a.name)) for a in (r.authors or [])]

    return UnifiedPaperEntity(
        doi=doi,
        arxiv_id=arxiv_id,
        title=(r.title or "").strip(),
        abstract=r.summary or None,
        authors=authors,
        year=r.published.year if r.published else None,
        venue="arXiv",
        type="preprint",
        arxiv_categories=list(r.categories or []),
        arxiv_comment=r.comment,
        pdf_url=r.pdf_url,
        sources=["arxiv"],
        discovery_path="arxiv:freshness",
    )


def _to_dict(entity: UnifiedPaperEntity) -> dict:
    """Serialize entity to a JSON-safe dict (same as openalex_helper)."""
    d = {}
    for f, v in entity.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        else:
            d[f] = v
    return d


def _build_query(query: str, categories: Optional[List[str]]) -> str:
    """Wrap a raw user query with a category filter clause."""
    cats = categories or DEFAULT_CATEGORIES
    cat_clause = " OR ".join(f"cat:{c}" for c in cats)
    return f"({query}) AND ({cat_clause})"


# =============================================================================
# Public search functions
# =============================================================================


def search_freshness_window(
    query: str,
    days: int = 4,
    limit: int = 30,
    categories: Optional[List[str]] = None,
) -> List[UnifiedPaperEntity]:
    """Get arXiv preprints submitted in the last N days.

    This is arXiv's killer feature in the v2.0 architecture: OpenAlex indexing
    lags 4-5 days (SA-V2 §4 实测), so T-0~T-4 arXiv papers are unreachable
    via OpenAlex.

    Args:
        query: user search terms (will be ANDed with category filter)
        days: window in days back from now. Default 4 = OpenAlex lag.
        limit: max papers to return after date filtering
        categories: defaults to DEFAULT_CATEGORIES (cs/math/stat/q-bio/q-fin/econ)

    Returns:
        UnifiedPaperEntity list, newest first, all with published >= now - days.
    """
    full_query = _build_query(query, categories)

    # Over-fetch by 2x to give the date filter room. arXiv returns by SubmittedDate
    # desc, so anything beyond `limit` after filtering is truncated anyway.
    search = arxiv.Search(
        query=full_query,
        max_results=max(limit * 2, 10),
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    results: List[arxiv.Result] = []
    for r in _client().results(search):
        if r.published and r.published >= cutoff:
            results.append(r)
            if len(results) >= limit:
                break
        elif r.published and r.published < cutoff:
            # arXiv returns by date desc — once we drop below cutoff we're done.
            break

    return [_to_entity(r) for r in results]


def search_recent(
    query: str,
    max_results: int = 30,
    categories: Optional[List[str]] = None,
    sort_by: str = "submitted",
) -> List[UnifiedPaperEntity]:
    """General arXiv search (Audit-tier or explicit user-enable).

    Unlike search_freshness_window, no date cutoff — caller controls window via
    arXiv query syntax if needed.

    Args:
        sort_by: 'submitted' (default, newest first) | 'relevance' | 'lastUpdated'
                 NOTE: SA-V2 §1.5 G "Relevance ranking is weak on arXiv — top-5 for
                 'attention is all you need' did not contain 1706.03762 itself.
                 Prefer 'submitted' or use OpenAlex for relevance ranking."

    Returns:
        UnifiedPaperEntity list. Empty list if no results.
    """
    full_query = _build_query(query, categories)
    sort_map = {
        "submitted": arxiv.SortCriterion.SubmittedDate,
        "relevance": arxiv.SortCriterion.Relevance,
        "lastUpdated": arxiv.SortCriterion.LastUpdatedDate,
    }
    search = arxiv.Search(
        query=full_query,
        max_results=max_results,
        sort_by=sort_map.get(sort_by, arxiv.SortCriterion.SubmittedDate),
        sort_order=arxiv.SortOrder.Descending,
    )
    return [_to_entity(r) for r in _client().results(search)]


def get_by_arxiv_id(arxiv_id: str) -> Optional[UnifiedPaperEntity]:
    """Single paper lookup by arxiv_id. Strips version suffix and URL prefix.

    Returns None if invalid id or no result found.
    """
    canonical = extract_arxiv_id(arxiv_id)
    if not canonical:
        return None
    search = arxiv.Search(id_list=[canonical])
    results = list(_client().results(search))
    return _to_entity(results[0]) if results else None


# =============================================================================
# CLI entry point
# =============================================================================


def _entity_list_to_json(entities: List[UnifiedPaperEntity]) -> List[dict]:
    return [_to_dict(e) for e in entities]


def _main_cli() -> None:
    import argparse
    import json
    import sys

    try:
        from .config import load_config
    except ImportError:
        from scripts.config import load_config  # type: ignore

    parser = argparse.ArgumentParser(
        prog="arxiv_helper",
        description="arXiv L2 Freshness Sentinel CLI (paper-search-pro Skill).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # freshness — T-0~T-N window, primary use case
    p_fresh = sub.add_parser("freshness", help="Recent preprints in last N days (default 4)")
    p_fresh.add_argument("query")
    p_fresh.add_argument("--days", type=int, default=4)
    p_fresh.add_argument("--limit", type=int, default=30)
    p_fresh.add_argument("--all-cats", action="store_true", help="Include physics/astro/cond-mat")

    # search — general purpose
    p_search = sub.add_parser("search", help="General arXiv search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=30)
    p_search.add_argument("--sort", default="submitted",
                          choices=["submitted", "relevance", "lastUpdated"])
    p_search.add_argument("--all-cats", action="store_true")

    # get — single paper by id
    p_get = sub.add_parser("get", help="Lookup single paper by arxiv_id")
    p_get.add_argument("arxiv_id")

    args = parser.parse_args()
    init(load_config())

    if args.cmd == "freshness":
        cats = ALL_CATEGORIES if args.all_cats else None
        results = search_freshness_window(args.query, days=args.days, limit=args.limit, categories=cats)
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "search":
        cats = ALL_CATEGORIES if args.all_cats else None
        results = search_recent(args.query, max_results=args.limit, categories=cats, sort_by=args.sort)
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "get":
        result = get_by_arxiv_id(args.arxiv_id)
        json.dump(_to_dict(result) if result else None, sys.stdout, default=str, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    _main_cli()
