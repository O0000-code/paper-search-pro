"""Serve an OpenAlex call from the fallback sources when OpenAlex cannot.

``openalex_helper`` raises :class:`OpenAlexUnavailable` when OpenAlex cannot
serve a call (daily budget spent, persistent throttling, outage, rejected key).
This module serves the same call from Semantic Scholar (the configured key;
keyless if the key is refused), in the SAME shape the OpenAlex command would
have produced, so the run continues without anyone intervening.

Semantic Scholar is the only retrieval fallback. CrossRef is not one: it matches
metadata rather than content, often lacks abstracts and mixes in non-article
types, so a corpus built from it would look like a normal result while being a
weaker one. CrossRef keeps its auxiliary role: DOI metadata lookups (``get``).

When Semantic Scholar cannot serve the call either, the command behaves as it
did before the fallback existed, so nothing that used to work stops working: a
call that used to fail still fails (non-zero exit; the agent reports it), and
the calls that used to carry on with an empty or partial result (``journal-list``
and a ``citation-network`` that already fetched some links) still do. The only
difference is a stderr line saying what happened. Records OpenAlex returned
before the cutoff (``exc.partial``) are kept and listed first.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import crossref_helper, ss_helper
from .openalex_guard import OpenAlexUnavailable
from .types import UnifiedPaperEntity

# Subcommands that return a paper list and therefore have a retrieval fallback.
LIST_COMMANDS = {"search", "deep", "double-sort", "seminal", "reviews", "journal-list"}

# Commands that, before the fallback existed, swallowed an OpenAlex failure and
# returned an empty list with exit 0. They keep doing so when SS cannot serve.
_CONTINUED_BEFORE = {"journal-list"}

_MISSING_FIELDS = "institutions, funders, topics, FWCI, open impact"

# `search --type` (OpenAlex work types) in Semantic Scholar's vocabulary. A type
# missing from the map cannot be honoured, so SS is not asked without it (which
# would return other types) and the call is reported as not served.
_SS_TYPES = {
    "review": "Review",
    "article": "JournalArticle,Conference",
    "book": "Book",
    "book-chapter": "BookSection",
    "dataset": "Dataset",
    "editorial": "Editorial",
    "letter": "LettersAndComments",
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
    # Not served, but this command used to carry on (exit 0) in this situation.
    continues_as_before: bool = False
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


def serve_list(cmd: str, a: Dict[str, Any], exc: OpenAlexUnavailable) -> FallbackResult:
    """Fallback for a list-returning (retrieval) command. ``a`` carries the
    command's arguments (query/topic, limit or n, year_min, year_max, sort,
    journals). Served only when Semantic Scholar returned records."""
    papers: List[UnifiedPaperEntity] = list(exc.partial or [])
    kept = len(papers)
    ss = _ss_list(cmd, a)
    if ss:
        _dedup_extend(papers, ss)
    cap = a.get("limit") or (a.get("n") if cmd == "deep" else None)
    if cap:
        papers = papers[:cap]
    if ss:
        return FallbackResult(served=True, served_by=["semantic_scholar"], papers=papers,
                              kept_partial=kept)
    work_type = a.get("work_type")
    if cmd == "search" and work_type and work_type not in _SS_TYPES:
        why = f"--type {work_type} has no Semantic Scholar equivalent"
    else:
        failure = ss_helper.describe_failure()
        why = (f"Semantic Scholar could not serve it either ({failure})" if failure
               else "Semantic Scholar returned no records for this query")
    return FallbackResult(served=False, papers=papers, kept_partial=kept, why_not=why,
                          continues_as_before=cmd in _CONTINUED_BEFORE)


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
    if result.served:  # citation-network with OpenAlex links kept
        return (f"{head} `{cmd}` kept the {result.kept_partial} OpenAlex records fetched before "
                f"the cutoff; {result.why_not}. Tell the user this step is incomplete and continue.")
    reason = f": {result.why_not}" if result.why_not else ""
    if result.continues_as_before:
        return (f"{head} `{cmd}` could not be served{reason}, so it returned nothing, as it "
                f"did before in this situation. Tell the user this step came back empty and continue.")
    kept = (f" Printed only the {result.kept_partial} records OpenAlex returned before the "
            f"cutoff." if result.kept_partial else " Printed an empty result.")
    return (f"{head} `{cmd}` could not be served{reason}.{kept} Treat this like any OpenAlex "
            f"error: tell the user what happened and when OpenAlex resets.")
