"""openreview helper: AI-topic supplementary search that knows ACCEPTANCE STATUS.

Source: OpenReview (openreview.net), the non-profit peer-review platform that
ICLR, NeurIPS, ICML, COLM, CoRL, TMLR and others review on. Its value to PSP is
narrow and specific: OpenAlex and Semantic Scholar list the current year's ICLR /
ICML / COLM papers as arXiv preprints; only OpenReview knows the paper is
"ICLR 2026 Oral". It is an optional booster for AI topics only — psychology /
medicine / social-science queries return copies of literature OpenAlex already
has (see the standing report, recency-retrieval/50_openreview_standing.md).

Architecture parity with yiigle_helper: an INDEPENDENT source that emits the same
UnifiedPaperEntity shape, so federated_kg_resolver can ingest openreview.json
like any other raw file. Pure `requests` (already a declared runtime dep), no
LLM, no state beyond ``last_search_stats``, deterministic.

Endpoint discipline (anonymous, live-verified 2026-10-01):
    GET https://api2.openreview.net/notes/search
        ?term=<q>&type=terms&content=all&group=all&source=forum&limit=25&offset=<k>
The listing endpoint ``GET /notes?content.venueid=...`` answers anonymous
clients with HTTP 403 ``ChallengeRequiredError`` (a human-verification wall) and
is NEVER used. The search endpoint may get the same wall one day, so every
failure — 403 challenge, other non-200, timeout, bad JSON — stops paging and
returns what was already collected (possibly []). ``search()`` never raises.
The response ``count`` is always 10000 (a cap), so it says nothing about the
real hit total and is ignored.

ACCEPTANCE WHITELIST (the one rule this module exists to enforce in code):
    only ~17% of search hits are main-conference accepted papers; the rest are
    workshops, rejected ("Submitted to ICLR 2026"), withdrawn, under review
    (incl. anonymous ACL ARR drafts), and author-profile imports of papers
    published elsewhere (dblp.org/..., OpenReview.net/Public_Article). The
    human-readable ``content.venue`` string is set freely by each venue and a
    rejected paper's reads "Submitted to ICLR 2026", so it NEVER decides status.
    ``content.venueid`` does (OpenReview docs: accepted submissions keep the
    venue's own id). A note is kept only when its venueid is exactly
        <org>[/<more>]/<YYYY>/Conference     e.g. ICLR.cc/2026/Conference,
                                                 colmweb.org/COLM/2026/Conference
    or exactly ``TMLR``, or NeurIPS's Datasets & Benchmarks track
        NeurIPS.cc/<YYYY>/Datasets_and_Benchmarks_Track, NeurIPS.cc/<YYYY>/Track/Datasets_and_Benchmarks
    (labelled "NeurIPS 2025 Datasets & Benchmarks Poster"). Everything else is dropped. Whitelist, not blacklist:
    status suffixes differ per venue (…/Rejected_Submission vs TMLR/Rejected),
    so a blacklist would silently admit the next new form.

Field mapping (per live notes; API v2 wraps every content value as {"value": x}):
    forum (or id)          -> source_native_id = "openreview:<forum>"
    content.title          -> title
    content.abstract       -> abstract
    content.authors        -> authors[].name (strings; {fullname} objects tolerated)
    content.keywords       -> keywords
    content.TLDR           -> tldr
    venueid year           -> year (conferences); TMLR: pdate, else cdate (ms epoch, UTC)
    venue + venueid        -> venue = "<Name> <YYYY>[ <Tier>]", e.g. "ICLR 2026 Oral",
                              "NeurIPS 2025 Poster", "COLM 2026", "EMNLP 2023 Findings";
                              TMLR -> "TMLR". Never the bare word "OpenReview".
    id                     -> pdf_url = "https://openreview.net/pdf?id=<id>" (only when
                              the note has a pdf — a small venue's paper may not)
    forum                  -> oa_locations = ["https://openreview.net/forum?id=<forum>"]
    (constant)             -> type = "article", sources = ["openreview"]
    discovery_path is left None on purpose (downstream gives it another meaning).
    Venue submissions carry no DOI and no arXiv id; the resolver merges by title.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .types import Author, UnifiedPaperEntity

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://api2.openreview.net/notes/search"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "paper-search-pro (literature search; openreview helper)",
}

# The endpoint serves 25 notes per page; a shorter page is the last one.
_PAGE_SIZE = 25
# Politeness sleep between pages. OpenReview publishes no rate limit and has been
# tightening automated access since late 2025, so keep it at a second or more.
_PAGE_SLEEP = 1.0
_TIMEOUT = 20

# Indirection so tests can replace the sleep without patching the time module.
_sleep = time.sleep

ATTRIBUTION = (
    "Data: OpenReview (openreview.net), metadata CC0 | kept only papers accepted "
    "by a main conference track or TMLR (workshop / rejected / withdrawn / under "
    "review / imported records dropped)"
)

# Diagnostics of the most recent search() call, reset in place at each call. Lets a caller
# (the CLI, a PRISMA-S log) tell "OpenReview blocked us" from "OpenReview had no
# accepted paper on this topic" without changing search()'s return type.
#   pages_fetched  pages that returned a usable notes list
#   records_seen   notes on those pages
#   accepted_seen  notes whose venueid passed the whitelist
#   kept           entities returned (after year filter, de-dup and the n cap)
#   stopped        why paging ended: n_reached | end_of_results | max_pages |
#                  challenge | http_<code> | timeout | network_error |
#                  bad_json | bad_shape | not_run | error
last_search_stats: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Acceptance whitelist (code-enforced; venue strings never decide status)
# ---------------------------------------------------------------------------

_CONFERENCE_VENUEID = re.compile(r"[^/]+(?:/[^/]+)*/(\d{4})/Conference")
_TMLR_VENUEID = "TMLR"
# NeurIPS Datasets & Benchmarks: a peer-reviewed track published in the NeurIPS
# proceedings, under its own venueid (two spellings seen live, 2023 vs 2024+).
# Its rejected papers carry the same id plus "/Rejected_Submission", so the
# exact match below keeps them out. Other venues' data tracks stay excluded.
_NEURIPS_DB_VENUEID = re.compile(
    r"NeurIPS\.cc/(\d{4})/(?:Datasets_and_Benchmarks_Track|Track/Datasets_and_Benchmarks)"
)


def _accepted_kind(venueid: Any) -> Optional[Tuple[str, Optional[int]]]:
    """Classify a venueid. Returns ("conference", year) or ("tmlr", None) for an
    accepted paper, None for everything else (workshop, rejected, withdrawn,
    under review, anonymous preprint, dblp / profile imports, TMLR/Rejected …)."""
    if not isinstance(venueid, str):
        return None
    if venueid == _TMLR_VENUEID:
        return ("tmlr", None)
    m = _NEURIPS_DB_VENUEID.fullmatch(venueid)
    if m:
        return ("neurips_db", int(m.group(1)))
    m = _CONFERENCE_VENUEID.fullmatch(venueid)
    if m:
        return ("conference", int(m.group(1)))
    return None


# ---------------------------------------------------------------------------
# Venue label: "<Name> <YYYY>[ <Tier>]"
# ---------------------------------------------------------------------------

# Tier words, matched as WHOLE lower-cased tokens: "KSMI 2026 ShortOralPoster" is
# one token and must not read as "Oral". ICML writes "spotlightposter" for a
# spotlight. "Findings" (EMNLP/ACL) is kept because a Findings paper shown as
# plain "EMNLP 2023" would overstate its status. ICML's "regular" and ICLR's
# older "notable top 5%" carry no tier word and get no tier.
_TIER_TOKENS = {
    "findings": "Findings",
    "oral": "Oral",
    "spotlight": "Spotlight",
    "spotlightposter": "Spotlight",
    "poster": "Poster",
}
# When a string carries several, the least flattering publication-track word wins
# (Findings), then the presentation level from highest to lowest.
_TIER_PRIORITY = ("Findings", "Oral", "Spotlight", "Poster")

# "<Name> <YYYY>" at the start of the venue string, e.g. "NeurIPS 2025 poster".
_VENUE_LEAD = re.compile(r"\s*([A-Za-z][A-Za-z0-9&+\-]*)\s+(\d{4})\b")


def _tier(venue: Optional[str]) -> Optional[str]:
    if not venue:
        return None
    found = {_TIER_TOKENS[t] for t in re.findall(r"[a-z]+", venue.lower()) if t in _TIER_TOKENS}
    for tier in _TIER_PRIORITY:
        if tier in found:
            return tier
    return None


def _venue_name(venue: Optional[str], venueid: str, year: int) -> str:
    """Conference short name. Prefer the venue string's lead word when it is
    followed by the venueid's year ("ICLR 2026 Oral" -> "ICLR"); otherwise use
    the venueid segment just before the year with a domain suffix stripped
    ("ICLR.cc" -> "ICLR", "colmweb.org/COLM/2026/…" -> "COLM")."""
    m = _VENUE_LEAD.match(venue or "")
    if m and int(m.group(2)) == year:
        return m.group(1)
    parts = venueid.split("/")
    seg = parts[-3] if len(parts) >= 3 else parts[0]
    return re.sub(r"\.[A-Za-z]{2,6}$", "", seg) or seg


def _venue_label(kind: str, year: Optional[int], venue: Optional[str], venueid: str) -> str:
    if kind == "tmlr":
        return "TMLR"
    if kind == "neurips_db":
        label = f"NeurIPS {year} Datasets & Benchmarks"
        tier = _tier(venue)
        return f"{label} {tier}" if tier else label
    label = f"{_venue_name(venue, venueid, year)} {year}"
    tier = _tier(venue)
    return f"{label} {tier}" if tier else label


# ---------------------------------------------------------------------------
# Note -> entity conversion (pure)
# ---------------------------------------------------------------------------


def _val(content: dict, key: str) -> Any:
    """A content value. API v2 wraps values as {"value": x}; a bare value (API v1
    shape) is accepted as-is."""
    v = content.get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _ms_to_year(ms: Any) -> Optional[int]:
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).year
    except (OverflowError, OSError, ValueError):
        return None


def _extract_authors(content: dict) -> List[Author]:
    """Venue submissions list author names as strings; imported records use
    {fullname, username} objects. Both are read; anything else is skipped."""
    raw = _val(content, "authors")
    out: List[Author] = []
    if not isinstance(raw, list):
        return out
    for a in raw:
        name = a if isinstance(a, str) else (a.get("fullname") if isinstance(a, dict) else None)
        if isinstance(name, str) and name.strip():
            out.append(Author(name=name.strip()))
    return out


def _extract_keywords(content: dict) -> List[str]:
    kw = _val(content, "keywords")
    if isinstance(kw, list):
        return [k.strip() for k in kw if isinstance(k, str) and k.strip()]
    return []


def _clean_text(v: Any) -> Optional[str]:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _note_to_entity(note: dict) -> Optional[UnifiedPaperEntity]:
    """Convert one search note into a UnifiedPaperEntity, or None when the note
    is not an accepted paper (whitelist) or lacks an id / title."""
    content = note.get("content")
    if not isinstance(content, dict):
        return None
    venueid = _val(content, "venueid")
    kind_year = _accepted_kind(venueid)
    if kind_year is None:
        return None
    kind, year = kind_year
    if kind == "tmlr":
        year = _ms_to_year(note.get("pdate"))
        if year is None:
            year = _ms_to_year(note.get("cdate"))

    note_id = note.get("id")
    forum = note.get("forum") or note_id
    title = _clean_text(_val(content, "title"))
    if not isinstance(forum, str) or not forum or not title:
        return None

    pdf = _val(content, "pdf")
    pdf_url = (
        f"https://openreview.net/pdf?id={note_id if isinstance(note_id, str) and note_id else forum}"
        if pdf else None
    )
    return UnifiedPaperEntity(
        source_native_id=f"openreview:{forum}",
        title=title,
        abstract=_clean_text(_val(content, "abstract")),
        authors=_extract_authors(content),
        year=year,
        venue=_venue_label(kind, year, _clean_text(_val(content, "venue")), venueid),
        type="article",
        keywords=_extract_keywords(content),
        tldr=_clean_text(_val(content, "TLDR")),
        pdf_url=pdf_url,
        oa_locations=[f"https://openreview.net/forum?id={forum}"],
        sources=["openreview"],
    )


def _title_key(title: str) -> str:
    """Case- and punctuation-insensitive title key (Unicode-aware, so a title
    with no Latin letters still gets a non-empty key)."""
    return re.sub(r"[\W_]+", " ", title.casefold()).strip() or title


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


_BOOLEAN_TOKENS = {"AND", "OR", "NOT"}


def plain_terms(query: str) -> str:
    """The query as plain words for OpenReview's term search.

    PSP's OpenAlex queries may be Boolean — ("short video" OR TikTok) AND
    (attention OR concentration). OpenReview does not parse that: quotes and
    parentheses came back with dynamic-pricing and min-cost-flow papers for a
    diffusion-model query (2026-10-01), while the same words without the syntax
    ranked on-topic papers first. So quotes, brackets and upper-case AND / OR /
    NOT are dropped, words kept once each, in order. A plain query is unchanged.
    """
    if not re.search(r'["()]|\b(?:AND|OR|NOT)\b', query):
        return query
    words, seen = [], set()
    # Quoted phrases are literal: an OR inside quotes is a word ("OR gate").
    for phrase, bare in re.findall(r'"([^"]*)"|([^\s"()]+)', query):
        if phrase:
            tokens = phrase.split()
        elif bare in _BOOLEAN_TOKENS:
            continue
        else:
            tokens = [bare]
        for w in tokens:
            if w.lower() not in seen:
                seen.add(w.lower())
                words.append(w)
    return " ".join(words) or re.sub(r'["()]', " ", query).strip()


def _fetch_page(query: str, offset: int, *, session=None) -> Tuple[Optional[list], str]:
    """Fetch one page. Returns (notes, "ok") or (None, <stop reason>). Never raises."""
    params = {
        "term": query,
        "type": "terms",
        "content": "all",
        "group": "all",
        "source": "forum",
        "limit": _PAGE_SIZE,
        "offset": offset,
    }
    try:
        if session is None:
            import requests  # local import: no module-top dependency footprint

            session = requests
        res = session.get(_SEARCH_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    except Exception as exc:
        return None, ("timeout" if "timeout" in type(exc).__name__.lower() else "network_error")

    status = getattr(res, "status_code", None)
    if status != 200:
        if status == 403:
            try:
                body = res.json()
            except Exception:
                body = None
            if isinstance(body, dict) and "Challenge" in str(body.get("name", "")):
                return None, "challenge"
        return None, f"http_{status}"
    try:
        data = res.json()
    except Exception:
        return None, "bad_json"
    if not isinstance(data, dict):
        return None, "bad_shape"
    notes = data.get("notes")
    if not isinstance(notes, list):
        if "Challenge" in str(data.get("name", "")):
            return None, "challenge"
        return None, "bad_shape"
    return notes, "ok"


def search(
    query: str,
    n: int = 30,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    max_pages: int = 8,
    session=None,
) -> List[UnifiedPaperEntity]:
    """Search OpenReview and return up to ``n`` ACCEPTED papers (main conference
    track or TMLR), in the endpoint's relevance order.

    Pages of 25 until ``n`` qualifying records are collected or ``max_pages``
    pages were read, sleeping >= 1 s between pages. ``year_min`` / ``year_max``
    filter client-side (inclusive); a record with no year is dropped when either
    bound is set. De-duplicates by forum id and by normalised title.

    任何失败返回 []，从不抛异常 — a failure after some pages returns what was
    already collected. See ``last_search_stats`` for why paging stopped."""
    stats = last_search_stats  # mutated in place, so imported references stay live
    stats.clear()
    stats.update({
        "query": query,
        "pages_fetched": 0,
        "records_seen": 0,
        "accepted_seen": 0,
        "kept": 0,
        "stopped": "not_run",
    })
    entities: List[UnifiedPaperEntity] = []
    try:
        if not isinstance(query, str) or not query.strip() or n <= 0 or max_pages <= 0:
            return []
        if year_min is not None and year_max is not None and year_min > year_max:
            return []
        query = plain_terms(query.strip())
        stats["query"] = query
        seen_ids: set = set()
        seen_titles: set = set()
        stats["stopped"] = "max_pages"
        for page in range(max_pages):
            if page > 0:
                _sleep(_PAGE_SLEEP)
            notes, reason = _fetch_page(query, page * _PAGE_SIZE, session=session)
            if notes is None:
                stats["stopped"] = reason
                break
            stats["pages_fetched"] += 1
            stats["records_seen"] += len(notes)
            for note in notes:
                if not isinstance(note, dict):
                    continue
                try:
                    ent = _note_to_entity(note)
                except Exception:
                    continue
                if ent is None:
                    continue
                stats["accepted_seen"] += 1
                if year_min is not None or year_max is not None:
                    if ent.year is None:
                        continue
                    if year_min is not None and ent.year < year_min:
                        continue
                    if year_max is not None and ent.year > year_max:
                        continue
                tkey = _title_key(ent.title)
                if ent.source_native_id in seen_ids or tkey in seen_titles:
                    continue
                seen_ids.add(ent.source_native_id)
                seen_titles.add(tkey)
                entities.append(ent)
                if len(entities) >= n:
                    stats["stopped"] = "n_reached"
                    stats["kept"] = len(entities)
                    return entities
            if len(notes) < _PAGE_SIZE:
                stats["stopped"] = "end_of_results"
                break
    except Exception:
        stats["stopped"] = "error"
    stats["kept"] = len(entities)
    return entities


# ---------------------------------------------------------------------------
# Serialisation (same full entity shape as yiigle_helper / ss_helper)
# ---------------------------------------------------------------------------


def _entity_to_dict(p: UnifiedPaperEntity) -> dict:
    d: dict = {}
    for f, v in p.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        else:
            d[f] = v
    return d


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main_cli(argv: Optional[List[str]] = None) -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="openreview_helper",
        description=(
            "openreview helper — AI-topic supplementary search on OpenReview; keeps "
            "only papers accepted by a main conference track or TMLR. Outputs "
            "UnifiedPaperEntity[] like yiigle_helper --search."
        ),
    )
    parser.add_argument("--search", metavar="QUERY", required=True,
                        help="English AI / ML query (e.g. 'diffusion language model').")
    parser.add_argument("--n", type=int, default=30,
                        help="Maximum accepted papers to return (default 30).")
    parser.add_argument("--year-min", type=int, default=None,
                        help="Minimum year (inclusive). Records with unknown year are dropped.")
    parser.add_argument("--year-max", type=int, default=None,
                        help="Maximum year (inclusive). Records with unknown year are dropped.")
    parser.add_argument("--max-pages", type=int, default=8,
                        help="Maximum 25-record pages to read (default 8).")
    parser.add_argument("--output-file", help="Where to write the JSON output (defaults to stdout).")
    args = parser.parse_args(argv)

    results = search(args.search, n=args.n, year_min=args.year_min,
                     year_max=args.year_max, max_pages=args.max_pages)
    payload = json.dumps([_entity_to_dict(p) for p in results], indent=2, ensure_ascii=False)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        sys.stdout.write(payload)
        sys.stdout.write("\n")

    # Attribution and diagnostics go to stderr so stdout stays one JSON document.
    s = last_search_stats
    print(ATTRIBUTION, file=sys.stderr)
    print(
        f"openreview: {s.get('pages_fetched', 0)} page(s), {s.get('records_seen', 0)} records seen, "
        f"{s.get('accepted_seen', 0)} accepted, {s.get('kept', 0)} kept; stopped: {s.get('stopped')}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    _main_cli()
