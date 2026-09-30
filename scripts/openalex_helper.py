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
import datetime
import re
import sys

import pyalex
from pyalex import (
    Authors,
    Sources,
    Works,
    config as pyalex_config,
    invert_abstract,
)

from . import openalex_guard
from .openalex_guard import OpenAlexUnavailable
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

    # ISSN (v2.2 Feature A, additive — used downstream for the SJR quartile join).
    # OpenAlex source carries issn_l (linking ISSN, most stable) + issn[] (all).
    # Prefer issn_l; fall back to the first of issn[]. None for sources w/o ISSN.
    issn = source.get("issn_l")
    issn_list = source.get("issn") or []
    if not isinstance(issn_list, list):
        issn_list = []
    if not issn and issn_list:
        issn = issn_list[0]
    # Keep the full list too: the rank join tries these when issn_l misses.
    issns = [s for s in dict.fromkeys([issn, *issn_list]) if s]

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

    # 0.3 (additive): collect ALL open-access copy URLs across locations[], not
    # just the single best open_access.oa_url below. A paper (e.g. AlphaFold2)
    # often has several OA copies — publisher OA + PMC + a repository. We keep the
    # single best URL in pdf_url (unchanged) and the fuller de-duplicated list in
    # oa_locations. Empty list for papers with no OA copies (R-19: non-OA papers
    # unchanged). Prefer each location's pdf_url, else its landing_page_url.
    oa_locations: List[str] = []
    _seen_oa: set = set()
    for loc in w.get("locations") or []:
        if not (loc.get("is_oa") or loc.get("oa_url")):
            continue
        url = loc.get("pdf_url") or loc.get("landing_page_url") or loc.get("oa_url")
        if url and url not in _seen_oa:
            _seen_oa.add(url)
            oa_locations.append(url)

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
        issn=issn,
        issns=issns,
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
        oa_locations=oa_locations,
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


def _year_filter(year_min: Optional[int], year_max: Optional[int]) -> Optional[str]:
    """One ``publication_year`` filter value, both ends inclusive.

    Both bounds must go in a single range value: two separate ``filter()``
    calls on the same key are joined by pyalex as ``>A+<B``, which OpenAlex
    rejects ("Value for param publication_year must be a number").
    """
    if year_min is not None and year_max is not None:
        return f"{year_min}-{year_max}"
    if year_min is not None:
        return f">{year_min - 1}"
    if year_max is not None:
        return f"<{year_max + 1}"
    return None


def _collect_pages(q, limit: int, per_page: int) -> List[UnifiedPaperEntity]:
    """Page through query ``q`` until ``limit`` entities or an empty page.

    Every request goes through :func:`openalex_guard.call`. When OpenAlex
    becomes unavailable mid-crawl, the entities already collected ride along on
    the exception (``exc.partial``) so the fallback can keep them.
    """
    pages = (limit + per_page - 1) // per_page
    entities: List[UnifiedPaperEntity] = []
    try:
        for page in range(1, pages + 1):
            batch = openalex_guard.call(lambda page=page: q.get(per_page=per_page, page=page))
            if not batch:
                break
            entities.extend(_to_entity(w) for w in batch)
            if len(entities) >= limit:
                break
    except OpenAlexUnavailable as exc:
        exc.partial = entities[:limit]
        raise
    return entities[:limit]


def _today() -> datetime.date:
    """Today's date. A function so tests can pin it."""
    return datetime.date.today()


def _default_year_max(year_max: Optional[int]) -> int:
    """No upper bound given → cap at the current year.

    OpenAlex holds records dated years ahead (2027, 2028, even 2050 — issue
    dates, data errors); one uncapped run pulled in 81 of them, all off-topic.
    """
    return year_max if year_max is not None else _today().year


# A query with this many bare words and no OR gets a warning (see query_warning).
_BARE_WORD_WARN_AT = 6
# A title-and-abstract match count below this gets a "too narrow?" hint.
_NARROW_POOL_BELOW = 30


def query_warning(query: str) -> Optional[str]:
    """A one-line warning when the query is a long run of bare words, else None.

    OpenAlex requires every bare word. Agents tend to list synonyms as words —
    "short-form video use college university students attention attentional
    control sustained attention concentration" — which silently demands all of
    them: that query matched a single paper by title and abstract across
    2021–2026, and four of six on-topic papers OpenAlex held never came back
    (2026-10-01). Advisory only; the query runs as written.
    """
    unquoted = re.sub(r'"[^"]*"', " ", query)
    if re.search(r"\bOR\b", unquoted):
        return None
    words = [w for w in re.findall(r"[^\s()]+", unquoted) if w not in ("AND", "NOT")]
    n = len(words) + len(re.findall(r'"[^"]*"', query))
    if n < _BARE_WORD_WARN_AT:
        return None
    return (
        f"[paper-search-pro] this query has {n} terms and OpenAlex requires every one, "
        "so a paper using a synonym for any of them is excluded. Group synonyms with OR "
        "in 2-3 concept blocks, e.g. (\"short video\" OR TikTok) AND (attention OR concentration) "
        "- see references/query_planner.md \"How OpenAlex reads a query\"."
    )


def _empty_range(year_min: Optional[int], year_max: Optional[int]) -> bool:
    """A range that holds no year (e.g. --year-min 2027 capped at 2026).

    Sent to OpenAlex it becomes publication_year:2027-2026, which the API rejects;
    the right answer is simply nothing.
    """
    return year_min is not None and year_max is not None and year_min > year_max


# How far back the recent leg looks. Rolling, not "this calendar year": in
# January a calendar-year window would hold almost nothing.
RECENT_WINDOW_DAYS = 365


def recent_window(
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    days: int = RECENT_WINDOW_DAYS,
) -> Optional[Tuple[str, str]]:
    """Publication-date window (ISO from, ISO to) for the recent leg.

    The newest ``days`` days, clipped to the user's year range: when that range
    ends before today, the newest ``days`` days inside it. None when the range
    lies wholly in the future (nothing can be published there yet).
    """
    today = _today()
    end = today
    if year_max is not None and year_max < today.year:
        end = datetime.date(year_max, 12, 31)
    start = end - datetime.timedelta(days=days)
    if year_min is not None:
        floor = datetime.date(year_min, 1, 1)
        if floor > end:
            return None
        start = max(start, floor)
    return start.isoformat(), end.isoformat()


# The recent leg's second window: the two years before the first one.
MID_WINDOW_DAYS = 730


def mid_window(
    recent: Tuple[str, str],
    year_min: Optional[int] = None,
    days: int = MID_WINDOW_DAYS,
) -> Optional[Tuple[str, str]]:
    """The ``days`` days just before the ``recent`` window, clipped to year_min.

    Relevance ranking leans on citations, so the relevance leg favours papers
    several years old, and the last-year window stops a year back. Between them
    the one-to-three-year band came back nearly empty on established topics
    (2026-10-01, four psychology queries: 1–5 on-topic papers a year for
    2023–2024 against 10–18 for 2018–2021).
    """
    end = datetime.date.fromisoformat(recent[0]) - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days)
    if year_min is not None:
        start = max(start, datetime.date(year_min, 1, 1))
    if start > end:
        return None
    return start.isoformat(), end.isoformat()


def _title_abstract_filter_value(query: str) -> str:
    """The query as a ``title_and_abstract.search`` filter value.

    Commas separate filters, so they become spaces (they carry no meaning in a
    search query). ``|`` is OR inside a filter value; it is written out as OR so
    "a|b" keeps meaning a or b instead of silently becoming a and b.
    """
    return " ".join(query.replace(",", " ").replace("|", " OR ").split())


def search_works(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 25,
    work_type: Optional[str] = None,
) -> List[UnifiedPaperEntity]:
    """Keyword search with optional year + type filter. Default top-25 by relevance."""
    year_max = _default_year_max(year_max)
    if _empty_range(year_min, year_max):
        return []
    q = Works().search(query)
    year_filter = _year_filter(year_min, year_max)
    if year_filter is not None:
        q = q.filter(publication_year=year_filter)
    if work_type:
        q = q.filter(type=work_type)
    return _collect_pages(q, limit, min(limit, _PER_PAGE))


def search_top_n_pages(
    query: str,
    total_papers: int = 100,
    sort: str = "cited_by_count:desc",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    title_abstract_only: bool = False,
) -> List[UnifiedPaperEntity]:
    """Deep crawl. Default top-100. Sort options:
    cited_by_count:desc / publication_date:desc / relevance_score:desc.

    Per SA-V2 §6.3: deeper OpenAlex (top-100) beats L2 booster recall illusion.

    Any sort other than relevance matches the query in title and abstract only.
    OpenAlex's ``search=`` also matches full text; ranked by relevance that is
    harmless, but ranked by citations or date it puts papers that merely mention
    the words in their body first (measured 2026-09-30: 0–8 of 50 on-topic by
    citations, 0–24 by date, across 8 topics; title-and-abstract matching lifts
    the citation leg to 9–47). ``date_from`` / ``date_to`` (ISO dates) narrow the
    publication date further, e.g. the recent leg's window.
    """
    if _empty_range(year_min, year_max):
        return []
    if ":" not in sort:
        sort_field, sort_dir = sort, "desc"
    else:
        sort_field, sort_dir = sort.split(":", 1)

    if sort_field == "relevance_score" and not title_abstract_only:
        q = Works().search(query)
    else:
        q = Works().filter(title_and_abstract={"search": _title_abstract_filter_value(query)})
    q = q.sort(**{sort_field: sort_dir})
    year_filter = _year_filter(year_min, year_max)
    if year_filter is not None:
        q = q.filter(publication_year=year_filter)
    if date_from:
        q = q.filter(from_publication_date=date_from)
    if date_to:
        q = q.filter(to_publication_date=date_to)
    return _collect_pages(q, total_papers, _PER_PAGE)


def _windowed_relevance(
    query: str,
    n: int,
    year_min: Optional[int],
    year_max: Optional[int],
    window: Tuple[str, str],
) -> List[UnifiedPaperEntity]:
    """The ``n`` most relevant works in a publication-date window.

    Title-and-abstract matches first, then full-text matches to fill up to ``n``.
    Matching title and abstract only is the more precise ranking (2026-10-01,
    last-year window, 8 topics: on-topic 30→39, 20→37, 27→44 of 50, none worse by
    more than one) but it amplifies the query: a long run of bare words, every one
    of them required, can leave a handful of matches (one query matched a single
    paper). Filling from the full-text ranking keeps that case no worse than
    before, and costs a call only when the precise set runs short.
    """
    precise = search_top_n_pages(query, total_papers=n, sort="relevance_score:desc",
                                 year_min=year_min, year_max=year_max,
                                 date_from=window[0], date_to=window[1],
                                 title_abstract_only=True)
    if len(precise) >= n:
        return precise[:n]
    try:
        broad = search_top_n_pages(query, total_papers=n, sort="relevance_score:desc",
                                   year_min=year_min, year_max=year_max,
                                   date_from=window[0], date_to=window[1])
    except OpenAlexUnavailable as exc:
        exc.partial = precise + list(exc.partial or [])
        raise
    have = {p.paper_id for p in precise}
    return (precise + [p for p in broad if p.paper_id not in have])[:n]


# The three legs of double-sort, in run order. The order is part of the
# agent-path contract (per_strategy_new_papers is reported in this order).
#   cited     — the topic's most-cited work (title-and-abstract match)
#   recent    — the most relevant work of the last RECENT_WINDOW_DAYS days (n),
#               then of the MID_WINDOW_DAYS before that (n // 2); title-and-abstract
#               matches first, topped up from full text (see _windowed_relevance)
#   relevance — the most relevant work overall
# The recent leg used to be "newest first" over a full-text match, which
# returned whatever mentioned the words most recently: of 52 records dated
# 2026 for "diffusion language model", about one was on topic.
DOUBLE_SORT_LEGS: Tuple[str, ...] = ("cited", "recent", "relevance")


def run_leg(
    leg: str,
    query: str,
    n: int,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> List[UnifiedPaperEntity]:
    """Run one double-sort leg (see DOUBLE_SORT_LEGS)."""
    year_max = _default_year_max(year_max)
    if _empty_range(year_min, year_max):
        return []
    if leg == "cited":
        return search_top_n_pages(query, total_papers=n, sort="cited_by_count:desc",
                                  year_min=year_min, year_max=year_max)
    if leg == "recent":
        window = recent_window(year_min, year_max)
        if window is None:
            return []
        papers = _windowed_relevance(query, n, year_min, year_max, window)
        earlier = mid_window(window, year_min)
        if earlier is not None and n // 2 > 0:
            try:
                older = _windowed_relevance(query, n // 2, year_min, year_max, earlier)
            except OpenAlexUnavailable as exc:
                exc.partial = papers + list(exc.partial or [])
                raise
            have = {p.paper_id for p in papers}
            papers += [p for p in older if p.paper_id not in have]
        return papers
    if leg == "relevance":
        return search_top_n_pages(query, total_papers=n, sort="relevance_score:desc",
                                  year_min=year_min, year_max=year_max)
    raise ValueError(f"unknown double-sort leg: {leg!r}")


def double_sort_search(
    query: str,
    year_min: Optional[int] = None,
    total_per_strategy: int = 50,
    year_max: Optional[int] = None,
) -> List[UnifiedPaperEntity]:
    """Multi-strategy combine: cited + recent + relevance. Boost rank when paper
    appears in >=2 strategies (cross-strategy boost).

    Per SA-V2: multi-strategy OpenAlex deep crawl > L2 booster pseudo-recall.
    Order: see :func:`_merge_strategies`.
    """
    strategies: List[List[UnifiedPaperEntity]] = []
    try:
        for leg in DOUBLE_SORT_LEGS:
            strategies.append(
                run_leg(leg, query, total_per_strategy,
                        year_min=year_min, year_max=year_max)
            )
    except OpenAlexUnavailable as exc:
        # Keep the finished strategies plus the interrupted one's first pages.
        strategies.append(exc.partial)
        exc.partial = _merge_strategies(strategies)
        raise
    return _merge_strategies(strategies)


def count_title_abstract_matches(
    query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> Tuple[int, int, int]:
    """How many works have every query word in title or abstract, in a year range.

    Returns ``(count, year_min, year_max)``. No range given → the last two years.
    Feeds one line under the report's year chart: the bars count what the search
    retrieved, and without this figure a thin recent bar read as a thin field
    (a user concluded a 2025–2026 topic was unstudied). An upper bound — not all
    matches are on topic — which the report says.
    """
    y_max = year_max if year_max is not None else _today().year
    y_min = year_min if year_min is not None else y_max - 1
    if _empty_range(y_min, y_max):
        return 0, y_min, y_max
    q = (
        Works()
        .filter(title_and_abstract={"search": _title_abstract_filter_value(query)})
        .filter(publication_year=_year_filter(y_min, y_max))
    )
    return int(openalex_guard.call(lambda: q.count()) or 0), y_min, y_max


def _merge_strategies(strategies: List[List[UnifiedPaperEntity]]) -> List[UnifiedPaperEntity]:
    """Dedup across strategies. Papers several strategies found come first (more
    strategies first, then more citations). Papers only one strategy found follow,
    taken from the strategies in turn — relevance, recent, cited when the list is
    double-sort's — each in its own order.

    Taking turns matters because an agent that has more candidates than its
    classification budget keeps the head of this list. Ranked by citations, the
    single-strategy tail put every new paper last, and cutting the list removed
    exactly the recent layer.
    """
    seen: Dict[str, Tuple[UnifiedPaperEntity, int]] = {}
    first_leg: Dict[str, Tuple[int, int]] = {}
    for leg_index, strategy_papers in enumerate(strategies):
        for rank, p in enumerate(strategy_papers):
            pid = p.paper_id
            if pid in seen:
                prev_paper, count = seen[pid]
                seen[pid] = (prev_paper, count + 1)
            else:
                seen[pid] = (p, 1)
                first_leg[pid] = (leg_index, rank)

    shared = sorted(
        (x for x in seen.values() if x[1] > 1),
        key=lambda x: (-x[1], -x[0].citation_count),
    )

    # Round-robin over the single-strategy papers, last strategy first:
    # double-sort runs cited, recent, relevance, so relevance leads each turn.
    queues: List[List[UnifiedPaperEntity]] = [[] for _ in strategies]
    for p, count in seen.values():
        if count == 1:
            queues[first_leg[p.paper_id][0]].append(p)
    for q in queues:
        q.sort(key=lambda p: first_leg[p.paper_id][1])
    order = list(reversed(range(len(queues))))
    single: List[UnifiedPaperEntity] = []
    depth = 0
    while any(depth < len(queues[i]) for i in order):
        for i in order:
            if depth < len(queues[i]):
                single.append(queues[i][depth])
        depth += 1

    return [p for p, _ in shared] + single


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
    raw = openalex_guard.call(lambda: Works()[s])
    # pyalex returns Work objects (dict-like); ensure we have a dict
    if hasattr(raw, "items"):
        return _to_entity(dict(raw))
    return _to_entity(raw)


def find_seminal_papers(
    topic: str, year_max: int = 2015, limit: int = 10
) -> List[UnifiedPaperEntity]:
    """High-cited early papers (year<=year_max, sort cited desc).

    SA-Z2 F19 verified: K&T 1979 (cites=46625) returned as #1 for 'prospect theory'.
    Matches title and abstract only, for the reason in :func:`search_top_n_pages`
    (pre-2016, 10 per topic, 2026-10-01: on-topic 5/0/0/0 → 10/8/5/1).
    """
    q = (
        Works()
        .filter(title_and_abstract={"search": _title_abstract_filter_value(topic)})
        .filter(publication_year=f"<{year_max + 1}")
        .sort(cited_by_count="desc")
    )
    return _collect_pages(q, limit, min(limit, _PER_PAGE))


def find_review_articles(
    topic: str,
    limit: int = 10,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> List[UnifiedPaperEntity]:
    """Filter type='review' with optional year_min / year_max (inclusive)."""
    if _empty_range(year_min, year_max):
        return []
    q = Works().filter(type="review").search(topic)
    year_filter = _year_filter(year_min, year_max)
    if year_filter is not None:
        q = q.filter(publication_year=year_filter)
    return _collect_pages(q, limit, min(limit, _PER_PAGE))


def _resolve_source_ids(journal_names: List[str], max_per_name: int = 1) -> List[str]:
    """Resolve journal display names to OpenAlex source IDs.

    SA-Z2 §4 finding: direct display_name filter unreliable; must look up source IDs.
    Returns IDs without the openalex.org/ prefix.
    """
    ids: List[str] = []
    for name in journal_names:
        try:
            results = openalex_guard.call(
                lambda name=name: Sources().search(name).get(per_page=max_per_name)
            )
        except OpenAlexUnavailable:
            raise
        except Exception:
            continue
        for s in results:
            sid = _strip_oa_prefix(s.get("id"))
            if sid:
                ids.append(sid)
    return ids


def get_source_impact(
    issn: str, *, raise_unavailable: bool = False
) -> Optional[Dict[str, Optional[float]]]:
    """Look up a journal's OPEN impact figures from its OpenAlex source (v2.2).

    Returns ``{"two_year_mean_citedness": float|None, "h_index": int|None,
    "i10_index": int|None, "openalex_source_id": str|None}`` for the journal with
    the given ISSN, or None when no source is found / lookup fails.

    Data is OpenAlex ``summary_stats`` (CC0, zero-dependency). R-09: the
    ``two_year_mean_citedness`` is an OPEN journal-impact figure, NOT the official
    Clarivate JIF — callers must label it as such and use it for relative
    ranking/filtering only. Never raises (a flaky lookup just degrades to None),
    except that ``raise_unavailable=True`` lets OpenAlexUnavailable through so a
    caller can tell "OpenAlex is down" from "this journal has no figure"."""
    if not issn:
        return None
    try:
        # OpenAlex Sources can be filtered by issn (accepts hyphenated form).
        results = openalex_guard.call(lambda: Sources().filter(issn=issn).get(per_page=1))
    except OpenAlexUnavailable:
        if raise_unavailable:
            raise
        return None
    except Exception:
        return None
    if not results:
        return None
    src = results[0]
    src = dict(src) if hasattr(src, "items") else src
    stats = src.get("summary_stats") or {}
    return {
        "two_year_mean_citedness": stats.get("2yr_mean_citedness"),
        "h_index": stats.get("h_index"),
        "i10_index": stats.get("i10_index"),
        "openalex_source_id": _strip_oa_prefix(src.get("id")),
    }


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
    return _collect_pages(q, limit, min(limit, _PER_PAGE))


def get_citation_network(
    openalex_id: str, refs_limit: int = 50, cited_by_limit: int = 100
) -> Dict[str, List[UnifiedPaperEntity]]:
    """Bidirectional citation: backward refs + forward cited_by in one call.

    Per SA-Z2 F22: refs in already-fetched paper; cited_by = filter(cites=W...).
    """
    s = openalex_id.strip()
    if s.startswith("10."):
        s = f"https://doi.org/{s}"
    raw_work = openalex_guard.call(lambda: Works()[s])
    work = dict(raw_work) if hasattr(raw_work, "items") else raw_work
    # The raw OA W-ID for forward citation
    bare_id = _strip_oa_prefix(work.get("id")) or openalex_id

    refs: List[UnifiedPaperEntity] = []
    cited_by: List[UnifiedPaperEntity] = []
    try:
        # Backward refs (referenced_works is a list of W-IDs)
        referenced_ids = (work.get("referenced_works") or [])[:refs_limit]
        if referenced_ids:
            bare_refs = [_strip_oa_prefix(r) for r in referenced_ids if r]
            ref_pipe = "|".join([r for r in bare_refs if r])
            if ref_pipe:
                try:
                    batch_per_page = min(len(bare_refs), _PER_PAGE)
                    pages = (len(bare_refs) + batch_per_page - 1) // batch_per_page
                    for page in range(1, pages + 1):
                        batch = openalex_guard.call(
                            lambda page=page: Works()
                            .filter(openalex_id=ref_pipe)
                            .get(per_page=batch_per_page, page=page)
                        )
                        if not batch:
                            break
                        refs.extend(_to_entity(w) for w in batch)
                        if len(refs) >= refs_limit:
                            break
                except OpenAlexUnavailable:
                    raise
                except Exception:
                    refs = []

        # Forward cited_by
        try:
            cited_q = Works().filter(cites=bare_id)
            per_page = _PER_PAGE
            pages = (cited_by_limit + per_page - 1) // per_page
            for page in range(1, pages + 1):
                batch = openalex_guard.call(
                    lambda page=page: cited_q.get(per_page=per_page, page=page)
                )
                if not batch:
                    break
                cited_by.extend(_to_entity(w) for w in batch)
                if len(cited_by) >= cited_by_limit:
                    break
        except OpenAlexUnavailable:
            raise
        except Exception:
            cited_by = []
    except OpenAlexUnavailable as exc:
        # The seed itself resolved, so its DOI lets the fallback redo the network.
        exc.partial = {
            "doi": _strip_doi_prefix(work.get("doi")),
            "references": refs[:refs_limit],
            "cited_by": cited_by[:cited_by_limit],
        }
        raise

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
            raw_author = openalex_guard.call(lambda: Authors()[s])
        except OpenAlexUnavailable:
            raise
        except Exception:
            raw_author = None

    if raw_author is None:
        results = openalex_guard.call(lambda: Authors().search(s).get(per_page=1))
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
    result = openalex_guard.call(
        lambda: Works()
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


# =============================================================================
# v2.2 additive: --json-envelope + stderr discoverability nudge (R-14)
# =============================================================================
# R-14: forensics showed agents drive THIS helper directly (even when told to
# load the Skill), so the agent path must be discoverable from here, not only
# from the new agent_search entry point. Two purely-additive hooks:
#
#   1. --json-envelope wraps the SAME command output in the ai-native-cli-spec
#      envelope (ok/schema_version/data/meta) so an agent gets a structured,
#      self-describing payload. Without the flag, stdout is byte-for-byte
#      unchanged (R-11/R-19).
#   2. a one-line stderr nudge pointing at `python3 -m scripts.agent_search`
#      (the full agent pipeline). stderr ONLY — stdout is never touched, so it
#      cannot alter any existing output or break a stdout-capturing test.
#
# The envelope here is deliberately THIN: it wraps whatever the chosen subcommand
# already produces (a list, or get/author/trends/etc.). It does NOT add the
# dedup/relevance/saturation discipline — that is agent_search's job. The nudge
# tells the agent where to get the full pipeline.

_ENVELOPE_SCHEMA_VERSION = "1.0"

_AGENT_SEARCH_NUDGE = (
    "[paper-search-pro] tip: for the full agent pipeline (multi-strategy retrieve "
    "+ dedup + heuristic relevance score + saturation + quota), run "
    "`python3 -m scripts.agent_search \"<query>\"` (one JSON envelope, no HTML)."
)

# Subcommands that are SEARCH-INITIATION entry points — the moment an agent
# starts a topic search is exactly when it should learn about the full
# agent_search pipeline (R-14: agents drive this helper directly even when told
# to load the Skill, and the bare `search` / `double-sort` calls are where they
# begin). The nudge prints once on stderr for these, regardless of
# --json-envelope. It is deliberately NOT printed for citation-network / get /
# author / trends / seminal / reviews / journal-list / deep / presets — those
# are mid-pipeline or lookup calls (e.g. STEP 9 citation-network would spam the
# nudge on every seed). stderr ONLY — stdout is never touched (R-11/R-19).
_NUDGE_ON_SUBCOMMANDS = {"search", "double-sort"}

# Subcommands whose query gets query_warning().
_QUERY_COMMANDS = {"search", "deep", "double-sort", "count"}

# Retrieval subcommands whose missing --year-max defaults to the current year.
_CAPPED_COMMANDS = {"search", "deep", "double-sort", "reviews"}


def _wrap_envelope(
    data,
    *,
    command: str,
    count: Optional[int] = None,
    fallback: Optional[dict] = None,
    ok: bool = True,
) -> dict:
    """Wrap any command result in the ai-native-cli-spec success envelope.

    ``data`` is passed through as-is (a list for search-like commands, a dict for
    get/author/trends). ``meta`` carries the command name and a count when the
    result is a list, so an agent can tell how much it got without re-counting.
    When OpenAlex was unavailable, ``meta.fallback`` says why and which source
    served the call, and ``meta.source`` names that source.
    """
    source = "openalex"
    if fallback:
        source = "+".join(fallback.get("served_by") or []) or "none"
    meta = {"command": command, "source": source}
    if count is not None:
        meta["count"] = count
    if fallback:
        meta["fallback"] = fallback
    return {
        "ok": ok,
        "schema_version": _ENVELOPE_SCHEMA_VERSION,
        "data": data,
        "meta": meta,
    }


# Exit status when OpenAlex was unavailable and no fallback could serve the call:
# stdout still carries a valid empty result, so a `> file` redirect never leaves
# unparseable JSON behind.
EXIT_SOURCE_UNAVAILABLE = 3


def _empty_payload(cmd: str, exc: OpenAlexUnavailable):
    """The command's result shape with nothing (or only what OpenAlex returned
    before the cutoff) in it, so stdout stays one valid JSON document.
    Returns ``(payload, count, kept_openalex_records)``."""
    from . import source_fallback

    if cmd in source_fallback.LIST_COMMANDS:
        kept = list(exc.partial or []) if isinstance(exc.partial, list) else []
        return _entity_list_to_json(kept), len(kept), len(kept)
    if cmd == "citation-network":
        part = exc.partial if isinstance(exc.partial, dict) else {}
        refs, cited = part.get("references") or [], part.get("cited_by") or []
        return {
            "references": _entity_list_to_json(refs),
            "cited_by": _entity_list_to_json(cited),
        }, None, len(refs) + len(cited)
    return {}, None, 0


def _fallback_args(args) -> dict:
    """The command arguments source_fallback needs, as a plain dict."""
    a = {k: getattr(args, k, None) for k in
         ("query", "topic", "limit", "year_min", "year_max", "sort", "work_type")}
    a["n"] = getattr(args, "n", None) or getattr(args, "total_per_strategy", None)
    if args.cmd == "search" and getattr(args, "recent", 0) and a.get("limit"):
        # `search --recent N` returns up to limit + N records; capping the fallback
        # at --limit cut off the recent layer and the fallback's own records.
        a["limit"] = a["limit"] + args.recent
    if args.cmd == "journal-list":
        a["journals"] = JOURNAL_PRESETS.get(args.preset) or []
    return a


def _serve_fallback(args, exc: OpenAlexUnavailable, config: Config):
    """Serve ``args.cmd`` from the fallback sources.

    Returns ``(payload, count, fallback_meta, served, note)``; ``payload`` always
    has the shape the OpenAlex command would have printed.
    """
    from . import source_fallback

    source_fallback.init(config)
    count: Optional[int] = None
    size = "nothing"
    if args.cmd in source_fallback.LIST_COMMANDS:
        res = source_fallback.serve_list(args.cmd, _fallback_args(args), exc)
        payload = _entity_list_to_json(res.papers or [])
        count = len(res.papers or [])
        size = f"{count} records"
    elif args.cmd == "get":
        res = source_fallback.serve_get(args.id)
        payload = _to_dict(res.payload) if res.payload is not None else {}
        size = "1 record" if res.payload is not None else size
    elif args.cmd == "citation-network":
        res = source_fallback.serve_citation_network(
            args.openalex_id, args.refs_limit, args.cited_by_limit, exc
        )
        net = res.payload or {"references": [], "cited_by": []}
        payload = {
            "references": _entity_list_to_json(net["references"]),
            "cited_by": _entity_list_to_json(net["cited_by"]),
        }
        size = f"{len(net['references'])} references, {len(net['cited_by'])} citing papers"
    else:  # author / trends: OpenAlex-only analytics
        res = source_fallback.FallbackResult(
            served=False, why_not="this is OpenAlex-only analytics with no equivalent elsewhere"
        )
        payload = {}
    fallback_meta = {
        "reason": exc.reason,
        "reset_seconds": exc.reset_seconds,
        "served_by": res.served_by,
        "kept_openalex_partial": res.kept_partial,
    }
    exit_ok = res.served or res.continues_as_before
    return payload, count, fallback_meta, exit_ok, source_fallback.notice(
        args.cmd, exc, res, size
    )


def _run_command(args):
    """Run one CLI subcommand against OpenAlex; returns ``(payload, count)``."""
    payload = None
    count: Optional[int] = None

    if args.cmd == "search":
        results = search_works(
            args.query,
            year_min=args.year_min,
            year_max=args.year_max,
            limit=args.limit,
            work_type=args.work_type,
        )
        if getattr(args, "recent", 0):
            # Quick tier's recent layer: relevance-ranked work of the last year,
            # merged into the same file so raw/ still holds one file per search.
            try:
                recent = run_leg("recent", args.query, args.recent,
                                 year_min=args.year_min, year_max=args.year_max)
            except OpenAlexUnavailable as exc:
                exc.partial = _merge_strategies([exc.partial or [], results])
                raise
            results = _merge_strategies([recent, results])
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "get":
        payload = _to_dict(get_work(args.id))
    elif args.cmd == "deep":
        results = search_top_n_pages(
            args.query, total_papers=args.n, sort=args.sort,
            year_min=args.year_min, year_max=args.year_max,
        )
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "double-sort":
        results = double_sort_search(
            args.query, year_min=args.year_min, year_max=args.year_max,
            total_per_strategy=args.total_per_strategy,
        )
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "count":
        # No fallback source: another index's total is not the same figure.
        try:
            n, y_min, y_max = count_title_abstract_matches(
                args.query, year_min=args.year_min, year_max=args.year_max)
            payload = {"count": n, "year_min": y_min, "year_max": y_max,
                       "matched_in": "title_and_abstract", "query": args.query}
        except OpenAlexUnavailable as exc:
            payload = {"count": None, "error": exc.describe(), "query": args.query}
    elif args.cmd == "seminal":
        results = find_seminal_papers(args.topic, year_max=args.year_max, limit=args.limit)
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "reviews":
        results = find_review_articles(
            args.topic, limit=args.limit,
            year_min=args.year_min, year_max=args.year_max,
        )
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "journal-list":
        results = search_in_journal_list(args.query, preset_name=args.preset, limit=args.limit)
        payload = _entity_list_to_json(results)
        count = len(results)
    elif args.cmd == "citation-network":
        result = get_citation_network(
            args.openalex_id, refs_limit=args.refs_limit, cited_by_limit=args.cited_by_limit
        )
        payload = {
            "references": _entity_list_to_json(result["references"]),
            "cited_by": _entity_list_to_json(result["cited_by"]),
        }
    elif args.cmd == "author":
        payload = get_author_profile(args.author)
    elif args.cmd == "trends":
        payload = analyze_topic_trends(args.topic, year_range=(args.year_min, args.year_max))
    elif args.cmd == "presets":
        payload = {name: len(journals) for name, journals in JOURNAL_PRESETS.items()}
    return payload, count


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
    # v2.2 additive (R-14): wrap output in the ai-native-cli-spec envelope for
    # agent callers. Default OFF -> stdout byte-for-byte unchanged (R-11/R-19).
    parser.add_argument(
        "--json-envelope",
        action="store_true",
        help="Wrap output in {ok, schema_version, data, meta} for agent callers. "
        "Without this flag the raw output is byte-for-byte unchanged.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # search
    p_search = sub.add_parser("search", help="Keyword search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=25)
    p_search.add_argument("--year-min", type=int)
    p_search.add_argument("--year-max", type=int)
    p_search.add_argument("--type", dest="work_type")
    p_search.add_argument(
        "--recent", type=int, default=0,
        help="Also fetch N relevance-ranked papers from the last 12 months "
             "(clipped to the year range) and merge them in. 0 = off.",
    )

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
    p_deep.add_argument("--year-max", type=int)

    # double-sort
    p_double = sub.add_parser("double-sort", help="Multi-strategy combine + boost")
    p_double.add_argument("query")
    p_double.add_argument("--n", type=int, default=50, dest="total_per_strategy")
    p_double.add_argument("--year-min", type=int)
    p_double.add_argument("--year-max", type=int)

    # seminal
    p_count = sub.add_parser(
        "count", help="Works with every query word in title/abstract, in a year range "
                      "(default: the last two years). Feeds the report's year-chart note.")
    p_count.add_argument("query")
    p_count.add_argument("--year-min", type=int)
    p_count.add_argument("--year-max", type=int)

    p_seminal = sub.add_parser("seminal", help="High-cited classic papers")
    p_seminal.add_argument("topic")
    p_seminal.add_argument("--year-max", type=int, default=2015)
    p_seminal.add_argument("--limit", type=int, default=10)

    # reviews
    p_reviews = sub.add_parser("reviews", help="Review-type articles")
    p_reviews.add_argument("topic")
    p_reviews.add_argument("--limit", type=int, default=10)
    p_reviews.add_argument("--year-min", type=int)
    p_reviews.add_argument("--year-max", type=int)

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
    # No end year given → this year, for every retrieval entry point and so also
    # for the fallback source, which reads its arguments from here.
    if args.cmd in _CAPPED_COMMANDS and getattr(args, "year_max", None) is None:
        args.year_max = _today().year
    config = load_config()
    init_pyalex(config)

    # Compute the command result as `payload` (+ `count` for list-like results).
    # We serialise ONCE at the end so the --json-envelope branch is the only
    # difference; the default (no-flag) path is byte-for-byte identical to before.
    fallback_meta = None
    served = True
    notice = None
    try:
        payload, count = _run_command(args)
    except OpenAlexUnavailable as exc:
        if not getattr(config, "quota_fallback", True):
            payload, count, kept = _empty_payload(args.cmd, exc)
            fallback_meta = {"reason": exc.reason, "reset_seconds": exc.reset_seconds,
                             "served_by": ["openalex (partial)"] if kept else [],
                             "kept_openalex_partial": kept}
            served = False
            notice = (
                f"[paper-search-pro] OpenAlex unavailable ({exc.describe()}). Automatic "
                "fallback is off (quota_fallback: false in ~/.paper-search-pro/config.yaml)."
            )
        else:
            payload, count, fallback_meta, served, notice = _serve_fallback(args, exc, config)

    if getattr(args, "json_envelope", False):
        # Agent path: wrap in the structured envelope. stdout stays a single JSON doc.
        envelope = _wrap_envelope(
            payload, command=args.cmd, count=count, fallback=fallback_meta, ok=served
        )
        json.dump(envelope, sys.stdout, default=str, indent=2)
    else:
        # Default path: byte-for-byte identical to pre-v2.2 output.
        json.dump(payload, sys.stdout, default=str, indent=2)
    sys.stdout.write("\n")

    # Discoverability nudge (R-14): print ONCE on stderr when the invocation is a
    # search-initiation subcommand (`search` / `double-sort`) OR when the agent
    # opted into the structured envelope. stderr ONLY — stdout above is already
    # flushed unchanged, so this can never alter output or break a stdout test.
    # Not printed for mid-pipeline subcommands (citation-network, get, ...) so
    # human STEP 9 citation expansion does not get spammed.
    if getattr(args, "json_envelope", False) or args.cmd in _NUDGE_ON_SUBCOMMANDS:
        print(_AGENT_SEARCH_NUDGE, file=sys.stderr)
    if args.cmd in _QUERY_COMMANDS:
        warning = query_warning(args.query)
        if warning:
            print(warning, file=sys.stderr)
    if args.cmd == "count" and isinstance(payload, dict) and payload.get("count") is not None \
            and payload["count"] < _NARROW_POOL_BELOW:
        print(
            f"[paper-search-pro] only {payload['count']} works have every query word in title "
            f"or abstract for {payload['year_min']}-{payload['year_max']}. Unless the topic is "
            "genuinely niche, the query is too narrow: group synonyms with OR, drop the "
            "population block, and rerun retrieval before classifying.",
            file=sys.stderr,
        )
    if notice:
        print(notice, file=sys.stderr)
    if not served:
        sys.exit(EXIT_SOURCE_UNAVAILABLE)


if __name__ == "__main__":
    _main_cli()
