"""NSSD helper — independent primary search for Chinese social-sciences &
humanities (SSH) literature (国家哲学社会科学文献中心 / ncpssd.cn).

Role (v2.3.0 Phase 3): an A-tier, fully self-contained Chinese source that emits
``UnifiedPaperEntity`` in the SAME shape as ``ss_helper --search`` /
``openalex_helper`` so STEP 4/5 federated fusion ingests NSSD JSON exactly like
openalex.json. It is a discipline-scoped supplemental source for the ``zh``
search space (social sciences & humanities), alongside OpenAlex (baseline) and
yiigle (medicine). Pure ``requests`` (already a dependency) — zero new deps.

Endpoint (verified live 2026-07-12, no login / no signature / no WAF cookie):
    POST https://www.ncpssd.cn/searchHandler/search
    headers: Content-Type: application/x-www-form-urlencoded; charset=UTF-8
             X-Requested-With: XMLHttpRequest
             (ordinary browser User-Agent)
    body:    search=<PQ>&pageNum=1&pageSize=N&sort=
    PQ (keyword-style, OR over 3 field codes — title / subject / abstract):
             (IKTE="<term>" OR IKST="<term>" OR IKSE="<term>")
    response {"result": bool, "code": 200, "data": {"total": int, "rows": [...]}}

Field mapping (row -> UnifiedPaperEntity), all verified against live rows:
    title      -> title
    creator    -> authors      (split on ';' / '；'; strip '[1]' / '[1,2]'
                                affiliation markers; a minority of records use
                                whitespace-separated CJK names — handled
                                conservatively so foreign names like "John
                                Smith" stay one author)
    cbw_name   -> venue        (journal / 集刊 title)
    issn       -> issn         ONLY when it matches the ISSN pattern. For 集刊文章
                                (serial-book articles) this slot carries an ISBN
                                instead (e.g. "978-7-5642-1400-5",
                                "7-81049-896-7" — verified live); those are
                                rejected so an ISBN never masquerades as an ISSN.
    remark     -> abstract
    years      -> year (int)
    id         -> source_native_id = "nssd:<id>"
    subject    -> keywords      real controlled subject terms, e.g.
                                "乡村振兴;乡村振兴战略" (';'-delimited) or the
                                whitespace-delimited variant "情绪调节 体育教学",
                                split into individual keywords.
    range      -> keywords      inclusion/quality signal (e.g.
                                "1;CSSCI_C2017_2018;NSSD;RWSKHX") stored as a
                                single namespaced token "nssd_range:<raw>" so it
                                is not lost; B2 wires it into 分区 later.
    type       -> type          mapped to the unified vocab — "article" for the
                                journal / 集刊 articles NSSD indexes. The RAW NSSD
                                type is ALSO kept as a namespaced
                                "nssd_type:<raw>" keyword so a downstream zh-space
                                router can identify / filter foreign-journal rows
                                ("外文期刊文章") without this helper hard-coding that
                                policy. NB "外文期刊文章" is a JOURNAL classification,
                                not a promise the record is English — live rows
                                show Chinese-titled 外文期刊文章 — so we annotate,
                                never hard-drop.
    doi        -> doi           lowercased + URL-prefix stripped to the bare
                                "10.x/y" form (matches yiigle / openalex so the
                                cross-source dedup key lines up). Usually empty;
                                a free dedup win when present, lifts paper_id to
                                the DOI.
    (constant) -> sources = ["nssd"].

Compliance (hard requirements):
    * Metadata + abstract ONLY. NEVER download or cache subscription full text
      (NSSD full text needs a free login — deliberately not touched here).
    * Nothing is written to disk / git — this module only fetches and returns.
    * Source attribution string for downstream display:
      "国家哲学社会科学文献中心(NSSD)" (see ``ATTRIBUTION``), printed to stderr on each
      CLI search so a consuming pipeline can surface the source credit (parity
      with yiigle_helper). Provenance also travels on ``sources=["nssd"]``.

Robustness: every network / HTTP / JSON failure degrades gracefully — the run
returns whatever was collected (empty on total failure) and prints a short note
to stderr; it never raises.
"""

from __future__ import annotations

import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urlencode

from .types import Author, UnifiedPaperEntity

# ---------------------------------------------------------------------------
# Endpoint / request constants
# ---------------------------------------------------------------------------

SEARCH_URL = "https://www.ncpssd.cn/searchHandler/search"

# Human-readable source attribution (compliance). Printed to stderr on each CLI
# search (parity with yiigle_helper); provenance also travels on sources=["nssd"].
ATTRIBUTION = "国家哲学社会科学文献中心(NSSD)"

_SOURCE = "nssd"

_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_DEFAULT_TIMEOUT = 30
# The endpoint honours the requested pageSize; cap per request to stay polite.
_MAX_PAGE_SIZE = 100
# Hard cap on paged requests so a huge result set can never run away.
_MAX_PAGES = 5

# ISSN form "XXXX-XXXX" with an optional trailing check-digit X (e.g.
# "1674-344X"). An ISBN-10/13 (with or without hyphens) never matches this, so
# 集刊 rows whose ``issn`` slot actually holds an ISBN are rejected.
_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dXx]$")

# Affiliation markers appended to author names: "[1]", "[1,2]" (half-width) and
# the full-width variant "［1］".
_AFFIL_RE = re.compile(r"[\[［][^\]］]*[\]］]")

# A pure-CJK author token (allows the interpunct used in transliterated names).
_CJK_NAME_RE = re.compile(r"^[一-鿿㐀-䶿·・]+$")


# ---------------------------------------------------------------------------
# Field parsing (pure functions — unit-testable without network)
# ---------------------------------------------------------------------------


def _build_pq(query: str) -> str:
    """Build the NSSD keyword PQ (OR over title / subject / abstract codes).

    Embedded double quotes are stripped so they cannot break the PQ delimiters.
    """
    term = (query or "").strip().replace('"', "").replace("“", "").replace("”", "")
    return f'(IKTE="{term}" OR IKST="{term}" OR IKSE="{term}")'


def _clean_str(v: object) -> Optional[str]:
    """Trim to a non-empty string, or None. Guards the rare literal 'None'."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() == "none":
        return None
    return s


def _clean_issn(raw: object) -> Optional[str]:
    """Return the value only if it is a real ISSN; else None.

    This is the ISBN discriminator: 集刊文章 rows put an ISBN (e.g.
    "978-7-5642-1400-5") in the ``issn`` slot, which must not surface as an ISSN.
    """
    s = _clean_str(raw)
    if s is None:
        return None
    return s if _ISSN_RE.match(s) else None


def _normalize_doi(raw: object) -> Optional[str]:
    """Bare, lowercased DOI ("10.x/y") — strips any URL / "doi:" prefix.

    Mirrors ``yiigle_helper._normalize_doi`` and the OpenAlex / SS convention so
    the cross-source dedup key (federated_kg_resolver keys on the lowercase DOI)
    lines up. Previously NSSD only lowercased, so a "https://doi.org/10.x" row
    would not collide with the bare "10.x" form emitted by the other sources.
    """
    s = _clean_str(raw)
    if s is None:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.lower().strip()
    return s or None


# Subject-term separators: half/full-width ';' ',' and the CJK enumeration '、'.
_SUBJECT_SEP_RE = re.compile(r"[;；,，、]")


def _parse_subject(raw: object) -> List[str]:
    """Split the NSSD ``subject`` slot into individual controlled subject terms.

    NSSD delimits subjects inconsistently (verified live): usually ';' (e.g.
    "乡村振兴;乡村振兴战略"), occasionally whitespace (e.g.
    "情绪调节 体育教学模式 体育教学"). Split on ';' ',' '、' first; if that yields a
    single whitespace-containing token, fall back to a whitespace split (same
    conservative heuristic as ``_parse_authors``) so multi-word terms are not
    over-fragmented in the common delimited case. De-duplicated, order-preserved.
    """
    s = _clean_str(raw)
    if s is None:
        return []
    parts = [p.strip() for p in _SUBJECT_SEP_RE.split(s)]
    parts = [p for p in parts if p]
    if len(parts) == 1 and re.search(r"\s", parts[0]):
        parts = parts[0].split()
    out: List[str] = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return out


def _parse_year(raw: object) -> Optional[int]:
    """Extract a 4-digit year as int, or None."""
    s = _clean_str(raw)
    if s is None:
        return None
    m = re.search(r"\d{4}", s)
    return int(m.group()) if m else None


def _parse_authors(creator: object) -> List[Author]:
    """Parse the NSSD ``creator`` string into a list of ``Author``.

    - Primary separator is ';' (also the full-width '；').
    - Each name may carry a trailing affiliation marker ("[1]", "[1,2]") — stripped.
    - A minority of records separate CJK author names by whitespace instead of
      ';'. We split on whitespace ONLY when the ';' split yielded a single name
      AND every whitespace token is pure-CJK — so multi-token foreign names
      ("John Smith") are preserved as one author.
    """
    s = _clean_str(creator)
    if s is None:
        return []
    s = s.replace("；", ";")  # full-width semicolon -> half-width
    names: List[str] = []
    for part in s.split(";"):
        name = _AFFIL_RE.sub("", part).strip()
        if name:
            names.append(name)

    if len(names) == 1 and re.search(r"\s", names[0]):
        tokens = names[0].split()
        if len(tokens) > 1 and all(_CJK_NAME_RE.match(t) for t in tokens):
            names = tokens

    return [Author(name=n) for n in names]


def _row_to_entity(row: Dict) -> UnifiedPaperEntity:
    """Convert one NSSD ``data.rows[i]`` record into a ``UnifiedPaperEntity``.

    Produces the same entity shape openalex_helper / ss_helper emit, so the
    federated resolver ingests NSSD JSON identically.
    """
    rid = _clean_str(row.get("id")) or _clean_str(row.get("data_id"))

    doi = _normalize_doi(row.get("doi"))

    keywords: List[str] = []
    # Real controlled subject terms first — these are genuine keywords.
    keywords.extend(_parse_subject(row.get("subject")))
    rng = _clean_str(row.get("range"))
    if rng:
        # Interim home for the CSSCI/CSCD/NSSD inclusion signal (B2 relocates it
        # into 分区). Namespaced so it is unambiguously distinguishable and easy
        # to strip: any consumer filters `kw.startswith("nssd_range:")`.
        keywords.append(f"nssd_range:{rng}")
    raw_type = _clean_str(row.get("type"))
    if raw_type:
        # Surface the RAW NSSD document/journal class (e.g. "外文期刊文章") as a
        # namespaced, filterable signal so a downstream zh-space router can drop
        # foreign-journal rows WITHOUT this helper hard-coding that policy. Same
        # escape-hatch pattern as nssd_range:; any consumer filters
        # `kw.startswith("nssd_type:")`.
        keywords.append(f"nssd_type:{raw_type}")

    return UnifiedPaperEntity(
        doi=doi,
        source_native_id=(f"nssd:{rid}" if rid else None),
        title=_clean_str(row.get("title")) or "",
        abstract=_clean_str(row.get("remark")),
        authors=_parse_authors(row.get("creator")),
        year=_parse_year(row.get("years")),
        venue=_clean_str(row.get("cbw_name")),
        issn=_clean_issn(row.get("issn")),
        # Every NSSD record ingested here is a journal / 集刊 article, so the
        # unified category is "article"; the Chinese-vs-foreign distinction is a
        # journal classification (not a document type) and rides on the
        # nssd_type:<raw> keyword above, never on this field.
        type="article",
        keywords=keywords,
        doi_url=(f"https://doi.org/{doi}" if doi else None),
        sources=[_SOURCE],
    )


# ---------------------------------------------------------------------------
# HTTP + search
# ---------------------------------------------------------------------------


def _fetch_page(
    query: str,
    page_num: int,
    page_size: int,
    session=None,
) -> Optional["tuple[List[Dict], int]"]:
    """Fetch one page. Returns (rows, total), or None on any failure.

    ``session`` (a requests-like object with ``.post``) is injected by tests so
    no network is touched; production passes None and uses ``requests``.
    """
    if session is not None:
        sess = session
    else:
        import requests  # local import: only when a real network call is needed

        sess = requests

    body = urlencode(
        {
            "search": _build_pq(query),
            "pageNum": page_num,
            "pageSize": page_size,
            "sort": "",
        }
    )
    try:
        res = sess.post(SEARCH_URL, data=body, headers=_HEADERS, timeout=_DEFAULT_TIMEOUT)
    except Exception as exc:  # network error, DNS, timeout, ...
        print(f"[nssd_helper] request failed: {exc}", file=sys.stderr)
        return None

    if getattr(res, "status_code", None) != 200:
        print(
            f"[nssd_helper] NSSD returned HTTP {getattr(res, 'status_code', '?')}",
            file=sys.stderr,
        )
        return None

    try:
        payload = res.json()
    except Exception as exc:
        print(f"[nssd_helper] could not parse NSSD JSON: {exc}", file=sys.stderr)
        return None

    # Shape guard: a legal-JSON body of an unexpected shape (a top-level list, or
    # a `data` slot carrying a list instead of the {"rows": [...]} object) must
    # NOT raise on `.get(...)` — degrade to an empty page (never-raise contract).
    if not isinstance(payload, dict):
        print(
            f"[nssd_helper] unexpected NSSD JSON shape: {type(payload).__name__}",
            file=sys.stderr,
        )
        return None

    if not payload.get("result"):
        print(
            f"[nssd_helper] NSSD result=false (code={payload.get('code')})",
            file=sys.stderr,
        )
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    rows = data.get("rows")
    if not isinstance(rows, list):
        rows = []
    try:
        total = int(data.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    return rows, total


def search(
    query: str,
    n: int = 25,
    year_min: Optional[int] = None,
    session=None,
) -> List[UnifiedPaperEntity]:
    """Independent NSSD primary search — returns UnifiedPaperEntity[].

    ``n``        : max number of results to return.
    ``year_min`` : keep only papers with year >= this (client-side; the NSSD
                   form exposes no verified year param, so we over-fetch and
                   filter). Records with an unparseable year are dropped when a
                   ``year_min`` is set.
    ``session``  : injected requests-like object (tests); None uses ``requests``.

    Any failure degrades gracefully to whatever was collected (empty on total
    failure); never raises.
    """
    if not query or not query.strip():
        return []

    target = max(1, int(n))
    # Over-fetch when year-filtering client-side so we can still return ~target.
    fetch_target = target * 4 if year_min is not None else target
    page_size = min(max(fetch_target, 1), _MAX_PAGE_SIZE)

    entities: List[UnifiedPaperEntity] = []
    seen: set = set()

    for page in range(1, _MAX_PAGES + 1):
        result = _fetch_page(query, page, page_size, session=session)
        if result is None:
            break
        rows, total = result
        if not rows:
            break

        for row in rows:
            if not isinstance(row, dict):
                continue  # shape guard: skip a non-dict row (never-raise)
            ent = _row_to_entity(row)
            # Filter by year FIRST, THEN mark `seen`: a year-dropped record must
            # not poison the dedup set and hide a later same-key record whose year
            # IS valid (e.g. two id-less rows that share a title fallback key).
            if year_min is not None and (ent.year is None or ent.year < year_min):
                continue
            key = ent.source_native_id or ent.doi or ent.title
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)
            if len(entities) >= target:
                return entities[:target]

        if len(rows) < page_size:
            break
        if page * page_size >= total:
            break

    return entities[:target]


# ---------------------------------------------------------------------------
# Serialization + CLI
# ---------------------------------------------------------------------------


def _to_dict(entity: UnifiedPaperEntity) -> Dict:
    """Serialise a UnifiedPaperEntity to a plain dict, flattening authors —
    identical in shape to openalex_helper._to_dict / ss_helper's search
    serializer, so downstream ingests NSSD JSON like openalex.json."""
    out: Dict = {}
    for field_name, value in entity.__dict__.items():
        if field_name == "authors":
            out[field_name] = [a.__dict__ for a in value]
        else:
            out[field_name] = value
    return out


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "NSSD helper — independent primary search for Chinese social-"
            "sciences & humanities literature (ncpssd.cn). Outputs "
            "UnifiedPaperEntity[] like `ss_helper --search`."
        )
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        required=True,
        help="keyword query (Chinese) — searched over title / subject / abstract.",
    )
    parser.add_argument(
        "--n", type=int, default=25, help="max results to return (default 25)."
    )
    parser.add_argument(
        "--year-min",
        type=int,
        help="minimum publication year, inclusive (client-side filter).",
    )
    parser.add_argument(
        "--output-file", help="write JSON here (defaults to stdout)."
    )
    args = parser.parse_args()

    results = search(args.search, n=args.n, year_min=args.year_min)
    output = [_to_dict(p) for p in results]
    payload = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        print(payload)

    # Compliance attribution — stderr only (parity with yiigle_helper), so stdout
    # stays a pure JSON document.
    print(ATTRIBUTION, file=sys.stderr)
