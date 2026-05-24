"""OpenAlex helper: pyalex SDK wrapper producing clean UnifiedPaperEntity objects.

Architecture (v2.0): L1 primary source, called by main Claude Code agent through
Bash CLI. NO LLM inside, NO state. Pure deterministic Python.

Key implementation decisions (from SA-Y2 / SA-Z2 empirical testing):
- per_page <= 20 (per_page > 20 triggers ~25k token responses)
- Abstract MUST be reconstructed via pyalex.invert_abstract() (no .abstract attr)
- OpenAlex W-IDs drift; use DOI lookups when ID drift suspected
- F21 journal filter: must resolve source IDs first (display_name str is unreliable)
- F6 Attention paper: cited_by 6543 is an OpenAlex data merger bug, not pyalex bug
- ID prefix stripping required (raw IDs come as "https://openalex.org/W123...")
"""

from typing import Dict, List, Optional, Tuple
import sys

import pyalex
from pyalex import (
    Authors,
    Sources,
    Works,
    config as pyalex_config,
    invert_abstract,
)

from .types import Author, Config, UnifiedPaperEntity


# =============================================================================
# Journal whitelists (hard-coded; replaces MCP preset list)
# =============================================================================
# Names are human-readable display_names. They are RESOLVED to OpenAlex source IDs
# at runtime via Sources().search() because filter-by-display-name is unreliable
# (SA-Z2 §4: Approach A fails, Approach B with source ID works).

JOURNAL_PRESETS: Dict[str, List[str]] = {
    # UTD Top-24 Business Journals (academic standard, business school rankings)
    "UTD24": [
        # Accounting (3)
        "The Accounting Review",
        "Journal of Accounting and Economics",
        "Journal of Accounting Research",
        # Finance (3)
        "Journal of Finance",
        "Journal of Financial Economics",
        "Review of Financial Studies",
        # Management (3)
        "Academy of Management Journal",
        "Academy of Management Review",
        "Strategic Management Journal",
        # Marketing (3)
        "Journal of Marketing",
        "Journal of Marketing Research",
        "Marketing Science",
        # Information Systems (3)
        "Information Systems Research",
        "MIS Quarterly",
        "INFORMS Journal on Computing",
        # Operations (3)
        "Operations Research",
        "Management Science",
        "Manufacturing & Service Operations Management",
        # Economics (3)
        "American Economic Review",
        "Econometrica",
        "Journal of Political Economy",
        # Behavioral / OB (3)
        "Administrative Science Quarterly",
        "Journal of International Business Studies",
        "Organization Science",
    ],
    # Financial Times Top-50 (broader business research, FT methodology)
    "FT50": [
        # Accounting (7)
        "The Accounting Review",
        "Journal of Accounting and Economics",
        "Journal of Accounting Research",
        "Contemporary Accounting Research",
        "Review of Accounting Studies",
        "Accounting Organizations and Society",
        "Auditing: A Journal of Practice & Theory",
        # Finance (7)
        "Journal of Finance",
        "Journal of Financial Economics",
        "Review of Financial Studies",
        "Journal of Financial and Quantitative Analysis",
        "Review of Finance",
        "Journal of Money Credit and Banking",
        "Mathematical Finance",
        # Management (10)
        "Academy of Management Journal",
        "Academy of Management Review",
        "Administrative Science Quarterly",
        "Strategic Management Journal",
        "Journal of International Business Studies",
        "Organization Science",
        "Organization Studies",
        "Journal of Management",
        "Journal of Management Studies",
        "Human Resource Management",
        # Marketing (5)
        "Journal of Marketing",
        "Journal of Marketing Research",
        "Marketing Science",
        "Journal of Consumer Research",
        "Journal of the Academy of Marketing Science",
        # Information Systems (3)
        "Information Systems Research",
        "MIS Quarterly",
        "Journal of Management Information Systems",
        # Operations / OR (5)
        "Operations Research",
        "Management Science",
        "Manufacturing & Service Operations Management",
        "Production and Operations Management",
        "Journal of Operations Management",
        # Economics (6)
        "American Economic Review",
        "Econometrica",
        "Journal of Political Economy",
        "Quarterly Journal of Economics",
        "Review of Economic Studies",
        "Journal of Business Ethics",
        # Other (7)
        "Entrepreneurship Theory and Practice",
        "Journal of Business Venturing",
        "Research Policy",
        "Journal of Consumer Psychology",
        "Journal of Applied Psychology",
        "Organizational Behavior and Human Decision Processes",
        "Harvard Business Review",
    ],
    # Top general science venues
    "nature_science": [
        "Nature",
        "Science",
        "Cell",
        "Proceedings of the National Academy of Sciences",
    ],
    # Top ML / AI venues (conferences are tracked as venues in OpenAlex)
    "ml_top_venues": [
        "Neural Information Processing Systems",
        "International Conference on Machine Learning",
        "International Conference on Learning Representations",
        "Journal of Machine Learning Research",
        "Conference on Computer Vision and Pattern Recognition",
        "Association for Computational Linguistics",
    ],
    # Top medical journals
    "medical_top": [
        "The New England Journal of Medicine",
        "The Lancet",
        "JAMA",
        "BMJ",
        "Nature Medicine",
        "Cell",
    ],
    # Cochrane reviews
    "Cochrane": [
        "Cochrane Database of Systematic Reviews",
    ],
}


# =============================================================================
# Initialization
# =============================================================================


def init_pyalex(config: Config) -> None:
    """Configure pyalex global state from Config (email/api_key for polite pool).

    Sets both attributes when provided. Email alone is sufficient for polite pool.
    """
    if config.openalex_email:
        pyalex_config.email = config.openalex_email
    if config.openalex_api_key:
        pyalex_config.api_key = config.openalex_api_key


# =============================================================================
# Internal helpers (raw dict -> UnifiedPaperEntity)
# =============================================================================


def _strip_oa_prefix(s: Optional[str], prefix: str = "https://openalex.org/") -> Optional[str]:
    """Strip the OpenAlex URL prefix so IDs are bare W123 / A123 / S123."""
    if not s:
        return None
    return s.replace(prefix, "")


def _strip_doi_prefix(doi: Optional[str]) -> Optional[str]:
    """Lowercase + strip URL prefix so DOI is bare '10.x/y' form."""
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").replace("http://doi.org/", "").lower() or None


def _extract_arxiv_id(work: dict) -> Optional[str]:
    """Look for arXiv ID in locations[].landing_page_url (SA-Z2 finding).

    Returns the arxiv ID stripped of version suffix (1706.03762 not 1706.03762v5).
    """
    for loc in work.get("locations") or []:
        source = loc.get("source") or {}
        landing_url = (loc.get("landing_page_url") or "").lower()
        source_name = (source.get("display_name") or "").lower()

        is_arxiv = "arxiv" in source_name or "arxiv.org" in landing_url
        if is_arxiv and "/abs/" in landing_url:
            tail = landing_url.split("/abs/")[-1].strip("/")
            # Strip version suffix (e.g. 1706.03762v5 -> 1706.03762)
            arxiv_id = tail.split("v")[0] if "v" in tail else tail
            return arxiv_id
    return None


def _extract_pmid(work: dict) -> Optional[str]:
    """Pull bare PMID number from ids.pmid URL form."""
    ids = work.get("ids") or {}
    pmid_url = ids.get("pmid") or ""
    if not pmid_url:
        return None
    # Bare ID or URL: https://pubmed.ncbi.nlm.nih.gov/12345
    return pmid_url.rsplit("/", 1)[-1] or None


def _extract_pmcid(work: dict) -> Optional[str]:
    """Pull PMC ID from ids.pmcid (URL form). May return None for non-PMC papers."""
    ids = work.get("ids") or {}
    pmcid_url = ids.get("pmcid") or ""
    if not pmcid_url:
        return None
    # Bare PMC ID, e.g. "PMC1234567"
    return pmcid_url.rsplit("/", 1)[-1] or None


def _to_entity(w: dict) -> UnifiedPaperEntity:
    """Convert raw pyalex Work dict to UnifiedPaperEntity.

    Handles: abstract reconstruction (invert_abstract), nested authors,
    venue extraction, ID prefix stripping, arxiv_id + pmid + pmcid extraction.
    """
    # Abstract (must reconstruct from inverted index)
    abstract = None
    abs_inv = w.get("abstract_inverted_index")
    if abs_inv:
        try:
            abstract = invert_abstract(abs_inv)
        except Exception:
            abstract = None

    # Authors
    authors: List[Author] = []
    for a in w.get("authorships") or []:
        author_obj = a.get("author") or {}
        institutions = a.get("institutions") or []
        primary_inst = institutions[0] if institutions else {}
        authors.append(
            Author(
                name=author_obj.get("display_name", ""),
                orcid=author_obj.get("orcid"),
                affiliation=primary_inst.get("display_name"),
                country=primary_inst.get("country_code"),
                is_first=a.get("author_position") == "first",
                is_corresponding=a.get("is_corresponding", False),
            )
        )

    # Venue
    primary_loc = w.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    venue = source.get("display_name")

    # Citations percentile (nested dict, take max)
    cbpy = w.get("cited_by_percentile_year") or {}
    cbpy_max = cbpy.get("max") if isinstance(cbpy, dict) else None

    # Topics top 5
    topics_raw = (w.get("topics") or [])[:5]
    topics = [
        {
            "id": _strip_oa_prefix(t.get("id"), "https://openalex.org/"),
            "name": t.get("display_name"),
            "score": t.get("score"),
        }
        for t in topics_raw
    ]

    # Keywords top 10
    keywords_raw = (w.get("keywords") or [])[:10]
    keywords = [
        k.get("display_name") or k.get("keyword")
        for k in keywords_raw
        if (k.get("display_name") or k.get("keyword"))
    ]

    # Open access
    oa = w.get("open_access") or {}

    return UnifiedPaperEntity(
        doi=_strip_doi_prefix(w.get("doi")),
        arxiv_id=_extract_arxiv_id(w),
        openalex_id=_strip_oa_prefix(w.get("id")),
        pmid=_extract_pmid(w),
        pmcid=_extract_pmcid(w),
        title=w.get("title") or w.get("display_name") or "",
        abstract=abstract,
        authors=authors,
        year=w.get("publication_year"),
        venue=venue,
        type=w.get("type"),
        citation_count=w.get("cited_by_count", 0) or 0,
        referenced_works_count=w.get("referenced_works_count"),
        fwci=w.get("fwci"),
        cited_by_percentile_year=cbpy_max,
        topics=topics,
        keywords=keywords,
        sdgs=w.get("sustainable_development_goals") or [],
        is_oa=oa.get("is_oa"),
        doi_url=w.get("doi"),
        openalex_url=w.get("id"),
        pdf_url=oa.get("oa_url"),
        sources=["openalex"],
    )


def _to_dict(entity: UnifiedPaperEntity) -> dict:
    """Serialize entity to a JSON-safe dict (Author -> dict, drop empty optionals)."""
    d = {}
    for f, v in entity.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        else:
            d[f] = v
    return d


# =============================================================================
# Per-page constants
# =============================================================================

# SA-Z1/SA-Z2 finding: per_page > 20 triggers ~25k token responses; cap at 20.
_PER_PAGE = 20


# =============================================================================
# Core 11 helper functions
# =============================================================================


def search_works(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 25,
    work_type: Optional[str] = None,
) -> List[UnifiedPaperEntity]:
    """Keyword search with optional year + type filter. Default top-25 by relevance."""
    q = Works().search(query)
    if year_min is not None:
        q = q.filter(publication_year=f">{year_min - 1}")
    if year_max is not None:
        q = q.filter(publication_year=f"<{year_max + 1}")
    if work_type:
        q = q.filter(type=work_type)
    per_page = min(limit, _PER_PAGE)
    pages = (limit + per_page - 1) // per_page
    entities: List[UnifiedPaperEntity] = []
    for page in range(1, pages + 1):
        batch = q.get(per_page=per_page, page=page)
        if not batch:
            break
        entities.extend(_to_entity(w) for w in batch)
        if len(entities) >= limit:
            break
    return entities[:limit]


def search_top_n_pages(
    query: str,
    total_papers: int = 100,
    sort: str = "cited_by_count:desc",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> List[UnifiedPaperEntity]:
    """Deep crawl. Default top-100. Sort options:
    cited_by_count:desc / publication_date:desc / relevance_score:desc.

    Per SA-V2 §6.3: deeper OpenAlex (top-100) beats L2 booster recall illusion.
    """
    if ":" not in sort:
        sort_field, sort_dir = sort, "desc"
    else:
        sort_field, sort_dir = sort.split(":", 1)

    q = Works().search(query).sort(**{sort_field: sort_dir})
    if year_min is not None:
        q = q.filter(publication_year=f">{year_min - 1}")
    if year_max is not None:
        q = q.filter(publication_year=f"<{year_max + 1}")

    per_page = _PER_PAGE
    pages_needed = (total_papers + per_page - 1) // per_page

    entities: List[UnifiedPaperEntity] = []
    for page in range(1, pages_needed + 1):
        batch = q.get(per_page=per_page, page=page)
        if not batch:
            break
        entities.extend(_to_entity(w) for w in batch)
        if len(entities) >= total_papers:
            break
    return entities[:total_papers]


def double_sort_search(
    query: str,
    year_min: Optional[int] = None,
    total_per_strategy: int = 50,
) -> List[UnifiedPaperEntity]:
    """Multi-strategy combine: cited + recent + relevance. Boost rank when paper
    appears in >=2 strategies (cross-strategy boost).

    Per SA-V2: multi-strategy OpenAlex deep crawl > L2 booster pseudo-recall.
    Returns papers sorted by (appearance_count desc, citation_count desc).
    """
    s1 = search_top_n_pages(query, total_per_strategy, "cited_by_count:desc", year_min=year_min)
    s2 = search_top_n_pages(query, total_per_strategy, "publication_date:desc", year_min=year_min)
    s3 = search_top_n_pages(query, total_per_strategy, "relevance_score:desc", year_min=year_min)

    seen: Dict[str, Tuple[UnifiedPaperEntity, int]] = {}
    for strategy_papers in (s1, s2, s3):
        for p in strategy_papers:
            pid = p.paper_id
            if pid in seen:
                prev_paper, count = seen[pid]
                seen[pid] = (prev_paper, count + 1)
            else:
                seen[pid] = (p, 1)

    return [p for p, _ in sorted(seen.values(), key=lambda x: (-x[1], -x[0].citation_count))]


def get_work(openalex_id_or_doi: str) -> UnifiedPaperEntity:
    """Single paper lookup by OpenAlex W-ID or DOI.

    Accepts:
    - "W3011865677"
    - "https://openalex.org/W3011865677"
    - "10.2307/1914185"
    - "https://doi.org/10.2307/1914185"
    """
    s = openalex_id_or_doi.strip()
    # DOI must be passed as full URL form to pyalex
    if s.startswith("10."):
        s = f"https://doi.org/{s}"
    raw = Works()[s]
    # pyalex returns Work objects (dict-like); ensure we have a dict
    if hasattr(raw, "items"):
        return _to_entity(dict(raw))
    return _to_entity(raw)


def find_seminal_papers(
    topic: str, year_max: int = 2015, limit: int = 10
) -> List[UnifiedPaperEntity]:
    """High-cited early papers (year<=year_max, sort cited desc).

    SA-Z2 F19 verified: K&T 1979 (cites=46625) returned as #1 for 'prospect theory'.
    """
    q = (
        Works()
        .search(topic)
        .filter(publication_year=f"<{year_max + 1}")
        .sort(cited_by_count="desc")
    )
    per_page = min(limit, _PER_PAGE)
    pages = (limit + per_page - 1) // per_page
    entities: List[UnifiedPaperEntity] = []
    for page in range(1, pages + 1):
        batch = q.get(per_page=per_page, page=page)
        if not batch:
            break
        entities.extend(_to_entity(w) for w in batch)
        if len(entities) >= limit:
            break
    return entities[:limit]


def find_review_articles(
    topic: str, limit: int = 10, year_min: Optional[int] = None
) -> List[UnifiedPaperEntity]:
    """Filter type='review' with optional year_min."""
    q = Works().filter(type="review").search(topic)
    if year_min is not None:
        q = q.filter(publication_year=f">{year_min - 1}")
    per_page = min(limit, _PER_PAGE)
    pages = (limit + per_page - 1) // per_page
    entities: List[UnifiedPaperEntity] = []
    for page in range(1, pages + 1):
        batch = q.get(per_page=per_page, page=page)
        if not batch:
            break
        entities.extend(_to_entity(w) for w in batch)
        if len(entities) >= limit:
            break
    return entities[:limit]


def _resolve_source_ids(journal_names: List[str], max_per_name: int = 1) -> List[str]:
    """Resolve journal display names to OpenAlex source IDs.

    SA-Z2 §4 finding: direct display_name filter unreliable; must look up source IDs.
    Returns IDs without the openalex.org/ prefix.
    """
    ids: List[str] = []
    for name in journal_names:
        try:
            results = Sources().search(name).get(per_page=max_per_name)
        except Exception:
            continue
        for s in results:
            sid = _strip_oa_prefix(s.get("id"))
            if sid:
                ids.append(sid)
    return ids


def search_in_journal_list(
    query: str, preset_name: str = "UTD24", limit: int = 25
) -> List[UnifiedPaperEntity]:
    """Search query restricted to a hard-coded journal whitelist (replaces MCP preset).

    Implementation per SA-Z2 §4 Approach B: resolve display names to source IDs,
    then filter Works by primary_location.source.id with OR (pipe) syntax.
    """
    journals = JOURNAL_PRESETS.get(preset_name)
    if not journals:
        raise ValueError(
            f"Unknown preset: {preset_name!r}. Available: {sorted(JOURNAL_PRESETS.keys())}"
        )
    source_ids = _resolve_source_ids(journals)
    if not source_ids:
        return []
    pipe = "|".join(source_ids)
    q = Works().search(query).filter(primary_location={"source": {"id": pipe}})
    per_page = min(limit, _PER_PAGE)
    pages = (limit + per_page - 1) // per_page
    entities: List[UnifiedPaperEntity] = []
    for page in range(1, pages + 1):
        batch = q.get(per_page=per_page, page=page)
        if not batch:
            break
        entities.extend(_to_entity(w) for w in batch)
        if len(entities) >= limit:
            break
    return entities[:limit]


def get_citation_network(
    openalex_id: str, refs_limit: int = 50, cited_by_limit: int = 100
) -> Dict[str, List[UnifiedPaperEntity]]:
    """Bidirectional citation: backward refs + forward cited_by in one call.

    Per SA-Z2 F22: refs in already-fetched paper; cited_by = filter(cites=W...).
    """
    s = openalex_id.strip()
    if s.startswith("10."):
        s = f"https://doi.org/{s}"
    raw_work = Works()[s]
    work = dict(raw_work) if hasattr(raw_work, "items") else raw_work
    # The raw OA W-ID for forward citation
    bare_id = _strip_oa_prefix(work.get("id")) or openalex_id

    # Backward refs (referenced_works is a list of W-IDs)
    referenced_ids = (work.get("referenced_works") or [])[:refs_limit]
    refs: List[UnifiedPaperEntity] = []
    if referenced_ids:
        bare_refs = [_strip_oa_prefix(r) for r in referenced_ids if r]
        ref_pipe = "|".join([r for r in bare_refs if r])
        if ref_pipe:
            try:
                batch_per_page = min(len(bare_refs), _PER_PAGE)
                pages = (len(bare_refs) + batch_per_page - 1) // batch_per_page
                for page in range(1, pages + 1):
                    batch = (
                        Works()
                        .filter(openalex_id=ref_pipe)
                        .get(per_page=batch_per_page, page=page)
                    )
                    if not batch:
                        break
                    refs.extend(_to_entity(w) for w in batch)
                    if len(refs) >= refs_limit:
                        break
            except Exception:
                refs = []

    # Forward cited_by
    cited_by: List[UnifiedPaperEntity] = []
    try:
        cited_q = Works().filter(cites=bare_id)
        per_page = _PER_PAGE
        pages = (cited_by_limit + per_page - 1) // per_page
        for page in range(1, pages + 1):
            batch = cited_q.get(per_page=per_page, page=page)
            if not batch:
                break
            cited_by.extend(_to_entity(w) for w in batch)
            if len(cited_by) >= cited_by_limit:
                break
    except Exception:
        cited_by = []

    return {"references": refs[:refs_limit], "cited_by": cited_by[:cited_by_limit]}


def get_author_profile(author_id_or_name: str) -> dict:
    """Author profile (OpenAlex A-ID lookup OR name search fallback).

    Returns dict with: id, name, h_index, i10_index, total_citations,
    works_count, top_affiliations, top_topics.
    """
    s = author_id_or_name.strip()
    is_id = s.startswith("A") and len(s) >= 10 and s[1:].isdigit()
    is_id = is_id or s.startswith("https://openalex.org/A")

    raw_author = None
    if is_id:
        try:
            raw_author = Authors()[s]
        except Exception:
            raw_author = None

    if raw_author is None:
        results = Authors().search(s).get(per_page=1)
        if not results:
            raise ValueError(f"Author not found: {author_id_or_name!r}")
        raw_author = results[0]

    a = dict(raw_author) if hasattr(raw_author, "items") else raw_author

    summary = a.get("summary_stats") or {}
    affiliations = (a.get("affiliations") or [])[:3]
    topics = (a.get("topics") or [])[:5]

    return {
        "id": _strip_oa_prefix(a.get("id")),
        "name": a.get("display_name"),
        "h_index": summary.get("h_index"),
        "i10_index": summary.get("i10_index"),
        "two_year_mean_citedness": summary.get("2yr_mean_citedness"),
        "total_citations": a.get("cited_by_count"),
        "works_count": a.get("works_count"),
        "top_affiliations": [
            {
                "name": (af.get("institution") or {}).get("display_name"),
                "country": (af.get("institution") or {}).get("country_code"),
                "ror": (af.get("institution") or {}).get("ror"),
            }
            for af in affiliations
        ],
        "top_topics": [
            {
                "id": _strip_oa_prefix(t.get("id")),
                "name": t.get("display_name"),
            }
            for t in topics
        ],
        "orcid": a.get("orcid"),
    }


def analyze_topic_trends(
    topic: str, year_range: Tuple[int, int] = (2010, 2026)
) -> Dict[int, int]:
    """Year distribution histogram via group_by('publication_year').

    Returns {year: count} dict. Per SA-Z2 F23 verified.
    """
    yr_low, yr_high = year_range
    result = (
        Works()
        .search(topic)
        .filter(publication_year=f"{yr_low}-{yr_high}")
        .group_by("publication_year")
        .get()
    )
    out: Dict[int, int] = {}
    for item in result:
        key = item.get("key")
        count = item.get("count")
        if key is None:
            continue
        try:
            out[int(key)] = int(count) if count is not None else 0
        except (ValueError, TypeError):
            continue
    return dict(sorted(out.items()))


# =============================================================================
# CLI dispatch
# =============================================================================


def _entity_list_to_json(entities: List[UnifiedPaperEntity]) -> List[dict]:
    return [_to_dict(e) for e in entities]


def _main_cli() -> None:
    import argparse
    import json

    try:
        # Try relative import first (when invoked as `python -m scripts.openalex_helper`)
        from .config import load_config
    except ImportError:
        # Fallback when invoked as a standalone script
        from scripts.config import load_config  # type: ignore

    parser = argparse.ArgumentParser(
        prog="openalex_helper",
        description="OpenAlex SDK helper CLI (paper-search-pro Skill).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # search
    p_search = sub.add_parser("search", help="Keyword search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=25)
    p_search.add_argument("--year-min", type=int)
    p_search.add_argument("--year-max", type=int)
    p_search.add_argument("--type", dest="work_type")

    # get
    p_get = sub.add_parser("get", help="Single paper lookup by OA-ID or DOI")
    p_get.add_argument("id")

    # deep
    p_deep = sub.add_parser("deep", help="Deep top-N crawl")
    p_deep.add_argument("query")
    p_deep.add_argument("--n", type=int, default=100)
    p_deep.add_argument(
        "--sort",
        default="cited_by_count:desc",
        help="cited_by_count:desc | publication_date:desc | relevance_score:desc",
    )
    p_deep.add_argument("--year-min", type=int)

    # double-sort
    p_double = sub.add_parser("double-sort", help="Multi-strategy combine + boost")
    p_double.add_argument("query")
    p_double.add_argument("--n", type=int, default=50, dest="total_per_strategy")
    p_double.add_argument("--year-min", type=int)

    # seminal
    p_seminal = sub.add_parser("seminal", help="High-cited classic papers")
    p_seminal.add_argument("topic")
    p_seminal.add_argument("--year-max", type=int, default=2015)
    p_seminal.add_argument("--limit", type=int, default=10)

    # reviews
    p_reviews = sub.add_parser("reviews", help="Review-type articles")
    p_reviews.add_argument("topic")
    p_reviews.add_argument("--limit", type=int, default=10)
    p_reviews.add_argument("--year-min", type=int)

    # journal-list
    p_journal = sub.add_parser("journal-list", help="Search within journal whitelist preset")
    p_journal.add_argument("query")
    p_journal.add_argument("--preset", default="UTD24")
    p_journal.add_argument("--limit", type=int, default=25)

    # citation-network
    p_cite = sub.add_parser("citation-network", help="refs + cited_by for one paper")
    p_cite.add_argument("openalex_id")
    p_cite.add_argument("--refs-limit", type=int, default=50)
    p_cite.add_argument("--cited-by-limit", type=int, default=100)

    # author
    p_author = sub.add_parser("author", help="Author profile by A-ID or name")
    p_author.add_argument("author")

    # trends
    p_trends = sub.add_parser("trends", help="Topic year distribution")
    p_trends.add_argument("topic")
    p_trends.add_argument("--year-min", type=int, default=2010)
    p_trends.add_argument("--year-max", type=int, default=2026)

    # presets (utility)
    p_presets = sub.add_parser("presets", help="List available journal presets")

    args = parser.parse_args()
    init_pyalex(load_config())

    if args.cmd == "search":
        results = search_works(
            args.query,
            year_min=args.year_min,
            year_max=args.year_max,
            limit=args.limit,
            work_type=args.work_type,
        )
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "get":
        result = get_work(args.id)
        json.dump(_to_dict(result), sys.stdout, default=str, indent=2)
    elif args.cmd == "deep":
        results = search_top_n_pages(
            args.query, total_papers=args.n, sort=args.sort, year_min=args.year_min
        )
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "double-sort":
        results = double_sort_search(
            args.query, year_min=args.year_min, total_per_strategy=args.total_per_strategy
        )
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "seminal":
        results = find_seminal_papers(args.topic, year_max=args.year_max, limit=args.limit)
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "reviews":
        results = find_review_articles(args.topic, limit=args.limit, year_min=args.year_min)
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "journal-list":
        results = search_in_journal_list(args.query, preset_name=args.preset, limit=args.limit)
        json.dump(_entity_list_to_json(results), sys.stdout, default=str, indent=2)
    elif args.cmd == "citation-network":
        result = get_citation_network(
            args.openalex_id, refs_limit=args.refs_limit, cited_by_limit=args.cited_by_limit
        )
        out = {
            "references": _entity_list_to_json(result["references"]),
            "cited_by": _entity_list_to_json(result["cited_by"]),
        }
        json.dump(out, sys.stdout, default=str, indent=2)
    elif args.cmd == "author":
        result = get_author_profile(args.author)
        json.dump(result, sys.stdout, default=str, indent=2)
    elif args.cmd == "trends":
        result = analyze_topic_trends(args.topic, year_range=(args.year_min, args.year_max))
        json.dump(result, sys.stdout, default=str, indent=2)
    elif args.cmd == "presets":
        json.dump(
            {name: len(journals) for name, journals in JOURNAL_PRESETS.items()},
            sys.stdout,
            indent=2,
        )
    sys.stdout.write("\n")


if __name__ == "__main__":
    _main_cli()
