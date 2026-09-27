"""Serve an OpenAlex call from the fallback sources when OpenAlex cannot.

``openalex_helper`` raises :class:`OpenAlexUnavailable` when OpenAlex cannot
serve a call (daily budget spent, persistent throttling, outage, rejected key).
This module turns that into a result in the SAME shape the OpenAlex command
would have produced, so the run continues without the main agent or the user
having to intervene.

Tier order for retrieval: Semantic Scholar (configured key; keyless if the key
is refused) -> CrossRef (keyless polite pool). SS keeps abstracts and citation
signals; CrossRef is the tier that still works when SS's shared pool throttles.
Records OpenAlex already returned before the cutoff (``exc.partial``) are kept
and listed first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import crossref_helper, ss_helper
from .openalex_guard import OpenAlexUnavailable
from .types import UnifiedPaperEntity

# Subcommands that return a paper list and therefore have a retrieval fallback.
LIST_COMMANDS = {"search", "deep", "double-sort", "seminal", "reviews", "journal-list"}

_MISSING_FIELDS = "institutions, funders, topics, FWCI, open impact"

# `search --type` (OpenAlex work types) in each fallback source's vocabulary. A
# type missing from a map means that source cannot honour the filter, and it is
# skipped rather than asked without it (which would return other types).
_SS_TYPES = {
    "review": "Review",
    "article": "JournalArticle,Conference",
    "book": "Book",
    "book-chapter": "BookSection",
    "dataset": "Dataset",
    "editorial": "Editorial",
    "letter": "LettersAndComments",
}
_CROSSREF_TYPES = {  # https://api.crossref.org/types
    "article": ("journal-article", "proceedings-article"),
    "preprint": ("posted-content",),
    "book": ("book", "monograph", "edited-book"),
    "book-chapter": ("book-chapter",),
    "dataset": ("dataset",),
    "dissertation": ("dissertation",),
    "report": ("report",),
    "standard": ("standard",),
    "peer-review": ("peer-review",),
}


@dataclass
class FallbackResult:
    """Outcome of a fallback attempt.

    ``papers`` is set for list commands, ``payload`` for get/citation-network.
    ``served`` is False when no tier could serve the call; the caller then
    prints the empty shape and a skip instruction.
    """

    served: bool
    served_by: List[str] = field(default_factory=list)
    papers: Optional[List[UnifiedPaperEntity]] = None
    payload: Any = None
    kept_partial: int = 0
    why_not: str = ""


def init(config) -> None:
    """Initialise the fallback clients (SS key, CrossRef polite-pool email)."""
    ss_helper.init(config)
    crossref_helper.init(config)


def _dedup_extend(base: List[UnifiedPaperEntity], extra: List[UnifiedPaperEntity]) -> None:
    seen = {p.paper_id for p in base}
    for p in extra:
        if p.paper_id not in seen:
            seen.add(p.paper_id)
            base.append(p)


def _ss_list(cmd: str, a: Dict[str, Any]) -> List[UnifiedPaperEntity]:
    q = a.get("query") or a.get("topic") or ""
    if cmd == "search":
        work_type = a.get("work_type")
        if work_type and work_type not in _SS_TYPES:
            return []
        filters = {"publicationTypes": _SS_TYPES[work_type]} if work_type else None
        return ss_helper.search(q, year_min=a.get("year_min"), year_max=a.get("year_max"),
                                total_per_strategy=a["limit"], filters=filters)
    if cmd == "deep":
        sort = (a.get("sort") or "").split(":")[0]
        strategies = {
            "cited_by_count": ("citationCount:desc",),
            "publication_date": ("publicationDate:desc",),
        }.get(sort)  # relevance_score has no SS equivalent: use both strategies
        return ss_helper.search(q, year_min=a.get("year_min"), year_max=a.get("year_max"),
                                total_per_strategy=a["n"], strategies=strategies)
    if cmd == "double-sort":
        return ss_helper.search(q, year_min=a.get("year_min"), year_max=a.get("year_max"),
                                total_per_strategy=a["n"])
    if cmd == "seminal":
        return ss_helper.search(q, year_max=a.get("year_max"), total_per_strategy=a["limit"],
                                strategies=("citationCount:desc",))
    if cmd == "reviews":
        return ss_helper.search(q, year_min=a.get("year_min"), year_max=a.get("year_max"),
                                total_per_strategy=a["limit"],
                                filters={"publicationTypes": "Review"})
    if cmd == "journal-list":
        return ss_helper.search(q, total_per_strategy=a["limit"],
                                filters={"venue": ",".join(a["journals"])})
    return []


def _crossref_list(cmd: str, a: Dict[str, Any]) -> List[UnifiedPaperEntity]:
    """CrossRef can only rank by relevance and cannot filter reviews or a venue
    whitelist reliably, so those two commands get no CrossRef tier."""
    q = a.get("query") or a.get("topic") or ""
    if cmd == "search":
        work_type = a.get("work_type")
        if work_type and work_type not in _CROSSREF_TYPES:
            return []
        return crossref_helper.search_works(q, year_min=a.get("year_min"),
                                            year_max=a.get("year_max"), limit=a["limit"],
                                            types=_CROSSREF_TYPES.get(work_type))
    if cmd in ("deep", "double-sort"):
        return crossref_helper.search_works(q, year_min=a.get("year_min"),
                                            year_max=a.get("year_max"), limit=a["n"])
    if cmd == "seminal":
        # Relevance-ranked pool, then citation order locally (CrossRef's own
        # citation sort ranks off-topic blockbusters first).
        pool = crossref_helper.search_works(q, year_max=a.get("year_max"),
                                            limit=max(a["limit"] * 5, 50))
        return sorted(pool, key=lambda p: -(p.citation_count or 0))[: a["limit"]]
    return []


def serve_list(cmd: str, a: Dict[str, Any], exc: OpenAlexUnavailable) -> FallbackResult:
    """Fallback for a list-returning command. ``a`` carries the command's
    arguments (query/topic, limit or n, year_min, year_max, sort, journals)."""
    papers: List[UnifiedPaperEntity] = list(exc.partial or [])
    kept = len(papers)
    served_by: List[str] = []
    ss = _ss_list(cmd, a)
    if ss:
        served_by.append("semantic_scholar")
        _dedup_extend(papers, ss)
    else:
        cr = _crossref_list(cmd, a)
        if cr:
            served_by.append("crossref")
            _dedup_extend(papers, cr)
    cap = a.get("limit") or (a.get("n") if cmd == "deep" else None)
    if cap:
        papers = papers[:cap]
    if not served_by:
        why = "Semantic Scholar returned nothing"
        if cmd == "search" and a.get("work_type"):
            why += f" and --type {a['work_type']} limits which fallback sources can be used"
        elif cmd in ("reviews", "journal-list"):
            why += " and CrossRef cannot filter this command's scope"
        else:
            why += " and CrossRef returned nothing"
        return FallbackResult(served=bool(kept), papers=papers, kept_partial=kept,
                              served_by=["openalex (partial)"] if kept else [], why_not=why)
    return FallbackResult(served=True, served_by=served_by, papers=papers, kept_partial=kept)


def _as_doi(identifier: str) -> Optional[str]:
    s = (identifier or "").strip()
    low = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if low.startswith(prefix):
            s = s[len(prefix):]
            break
    return s if s.startswith("10.") else None


def serve_get(identifier: str) -> FallbackResult:
    doi = _as_doi(identifier)
    if not doi:
        return FallbackResult(served=False, why_not="an OpenAlex W-ID cannot be resolved "
                              "elsewhere; pass the paper's DOI instead")
    paper = ss_helper.get_paper(doi)
    if paper is not None:
        return FallbackResult(served=True, served_by=["semantic_scholar"], payload=paper)
    paper = crossref_helper.get_entity(doi)
    if paper is not None:
        return FallbackResult(served=True, served_by=["crossref"], payload=paper)
    return FallbackResult(served=False, why_not="neither Semantic Scholar nor CrossRef "
                          "returned this DOI")


def serve_citation_network(
    identifier: str, refs_limit: int, cited_by_limit: int, exc: OpenAlexUnavailable
) -> FallbackResult:
    partial = exc.partial if isinstance(exc.partial, dict) else {}
    refs: List[UnifiedPaperEntity] = list(partial.get("references") or [])
    cited: List[UnifiedPaperEntity] = list(partial.get("cited_by") or [])
    doi = _as_doi(identifier) or partial.get("doi")
    if not doi:
        return FallbackResult(
            served=False,
            payload={"references": refs, "cited_by": cited},
            why_not="an OpenAlex W-ID cannot be resolved elsewhere; pass the seed's DOI instead",
        )
    net = ss_helper.citation_network(doi, refs_limit=refs_limit, cited_by_limit=cited_by_limit)
    got = bool(net["references"] or net["cited_by"])
    _dedup_extend(refs, net["references"])
    _dedup_extend(cited, net["cited_by"])
    payload = {"references": refs[:refs_limit], "cited_by": cited[:cited_by_limit]}
    if got:
        return FallbackResult(served=True, served_by=["semantic_scholar"], payload=payload)
    kept = len(payload["references"]) + len(payload["cited_by"])
    why = "Semantic Scholar returned no citation links for this DOI"
    if kept:
        # OpenAlex links fetched before the cutoff are real results: report them
        # as such instead of calling the output empty.
        return FallbackResult(served=True, served_by=["openalex (partial)"], payload=payload,
                              kept_partial=kept, why_not=why)
    return FallbackResult(served=False, payload=payload, why_not=why)


def notice(cmd: str, exc: OpenAlexUnavailable, result: FallbackResult, size: str) -> str:
    """The one stderr line the main agent relays to the user. ``size`` describes
    what was returned, e.g. '40 records'."""
    head = f"[paper-search-pro] OpenAlex unavailable ({exc.describe()})."
    if result.served and result.served_by and result.served_by != ["openalex (partial)"]:
        tiers = " + ".join(t.replace("_", " ").title() for t in result.served_by)
        kept = (f"; {result.kept_partial} OpenAlex records fetched before the cutoff were kept"
                if result.kept_partial else "")
        return (f"{head} Served `{cmd}` from {tiers} instead ({size}{kept}). Fallback records "
                f"lack OpenAlex-only fields ({_MISSING_FIELDS}). No action needed; continue the run.")
    if result.served:
        return (f"{head} `{cmd}` kept the {result.kept_partial} OpenAlex records fetched before "
                f"the cutoff; {result.why_not}. Continue the run with what was returned.")
    reason = f": {result.why_not}" if result.why_not else ""
    return (f"{head} `{cmd}` could not be served by a fallback source{reason}. "
            f"Printed an empty result; skip this step and continue the run.")
