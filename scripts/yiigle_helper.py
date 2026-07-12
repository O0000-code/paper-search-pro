"""yiigle helper: independent Chinese-medical primary search (中华医学期刊全文数据库).

Source: yiigle.com — 中华医学期刊全文数据库 (Chinese Medical Journals Full-text
Database, 中华医学会). This is the A-tier native-Chinese medical source found in the
v2.3.0 source-expansion audit (E1_stem_open_sources.md §2 A-1): a plain-HTTP,
no-login, no-signature, no-captcha JSON search API that returns native-Chinese
titles + full Chinese abstracts + real DOIs — a large body of 中华医学会 literature
that is mostly ABSENT from OpenAlex / CrossRef / PubMed, so it is genuine增量 for
Chinese medical queries.

Architecture parity: like ss_helper's `--search` path, this is an INDEPENDENT
primary source. It emits the SAME UnifiedPaperEntity shape openalex_helper /
ss_helper emit, so federated_kg_resolver ingests yiigle.json exactly like
openalex.json. Pure `requests` (zero new dependencies — requests>=2.32 is already
a declared runtime dep). No LLM, no state, deterministic.

Endpoint discipline (verified live 2026-07-12, no login / no signature):
    POST https://www.yiigle.com/apiVue/search/searchList
    headers: Content-Type: application/json;charset=UTF-8 + Accept: application/json + UA
    body:    {"searchType":"pt","page":P,"pageSize":N,
              "queryString":Q,"searchText":Q,"isAggregations":"N"}
KEY TRAP: ``isAggregations`` MUST be "N" — with "Y" the API returns only aggregation
facets and an EMPTY ``infos`` list (this is what earlier misread as "records need
login"). We always send "N".

Response shape:
    {"code":200,"data":{"result":{"searchTotal":N,"infos":[ <record>, ... ]}}}

Compliance (hard requirement): we take ONLY 题录 + 摘要 (title / abstract / metadata)
via the open search endpoint. Full text at rs.yiigle.com/cmaid/<artId> is a paid
subscription — this helper NEVER downloads or caches full text, and never emits a
full-text/PDF URL. Attribution: 中华医学期刊全文数据库 (yiigle.com), printed on
stderr on each search so any consuming pipeline can surface the source credit.
Fetched data is not persisted to git.

Field mapping (per live records 2026-07-12):
    artTitle           -> title
    artAbstract        -> abstract
    artDoi (if present) -> doi (lowercased, no URL prefix) + doi_url
    authorNames        -> authors[].name  (clean names; falls back to parsing
                          the "name|CAID..." forms in ``authors`` when absent)
    journalCn          -> venue  (native-Chinese journal name)
    artPubYear         -> year   (int; falls back to leading year of artPubDate)
    artId              -> source_native_id = "yiigle:<artId>"  (ALWAYS set; when a
                          DOI is present the DOI is still the primary key and the
                          native-id is only the DOI-less fallback — see
                          UnifiedPaperEntity.paper_id priority)
    artificialKeywords -> keywords  (additive; native-Chinese author/keyword terms)
    (constant)         -> type = "article"  (yiigle indexes 中华医学会 journal
                          articles; a stable category, never left None — #23)
    sources            -> ["yiigle"]
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

from .types import Author, UnifiedPaperEntity

# ---------------------------------------------------------------------------
# Endpoint constants
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://www.yiigle.com/apiVue/search/searchList"

_HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
}

# Records requested per HTTP page. Kept modest; search() paginates up to
# _MAX_PAGES to honour the caller's requested count (esp. when a year filter
# drops some records).
_PAGE_SIZE = 50
_MAX_PAGES = 10
# Politeness sleep between successive network pages (yiigle publishes no rate
# limit; this keeps us gentle). Only slept when another page will be fetched.
_PAGE_SLEEP = 0.2
_TIMEOUT = 30

# Human-readable source attribution (compliance — printed to stderr per search).
ATTRIBUTION = "数据来源：中华医学期刊全文数据库 (yiigle.com)｜仅题录+摘要，全文订阅，未下载/缓存全文"


# ---------------------------------------------------------------------------
# Record -> entity conversion (pure)
# ---------------------------------------------------------------------------


def _normalize_doi(doi: Optional[str]) -> Optional[str]:
    """Lowercase + strip any URL prefix so the DOI is bare '10.x/y' form.

    Matches the DOI convention openalex_helper / ss_helper emit, so cross-source
    dedup keys line up (federated_kg_resolver keys on the lowercase DOI)."""
    if not doi:
        return None
    d = str(doi).strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
            break
    d = d.lower().strip()
    return d or None


def _extract_year(record: dict) -> Optional[int]:
    """Publication year. Prefer the int ``artPubYear``; fall back to the leading
    four digits of ``artPubDate`` (ISO-ish string)."""
    y = record.get("artPubYear")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.strip().isdigit():
        return int(y.strip())
    d = record.get("artPubDate")
    if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


def _extract_authors(record: dict) -> List[Author]:
    """Clean author list. Prefer ``authorNames`` (already de-coded names); fall
    back to the ``authors`` list whose entries look like 'name|CAID9087...' —
    split on '|' and keep the name half."""
    names = record.get("authorNames")
    out: List[Author] = []
    if isinstance(names, list):
        for n in names:
            if n and isinstance(n, str):
                out.append(Author(name=n.strip()))
        if out:
            return out
    raw = record.get("authors")
    if isinstance(raw, list):
        for a in raw:
            if not a or not isinstance(a, str):
                continue
            name = a.split("|", 1)[0].strip()
            if name:
                out.append(Author(name=name))
    return out


def _extract_keywords(record: dict) -> List[str]:
    """Native-Chinese keywords. ``keywords`` is often null; ``artificialKeywords``
    carries the indexed term list. Additive / best-effort."""
    for key in ("keywords", "artificialKeywords"):
        kw = record.get(key)
        if isinstance(kw, list):
            vals = [str(k).strip() for k in kw if k and str(k).strip()]
            if vals:
                return vals
    return []


def _record_to_entity(record: dict) -> UnifiedPaperEntity:
    """Convert one yiigle ``infos[]`` record into a UnifiedPaperEntity.

    Always sets ``source_native_id = "yiigle:<artId>"``. When ``artDoi`` is
    present the DOI is also set and remains the primary key (paper_id priority
    DOI > ... > source_native_id); DOI-less records fall back to the native id.
    Never emits a full-text / PDF URL (compliance)."""
    art_id = record.get("artId")
    native_id = f"yiigle:{art_id}" if art_id is not None else None

    doi = _normalize_doi(record.get("artDoi"))

    return UnifiedPaperEntity(
        doi=doi,
        source_native_id=native_id,
        title=(record.get("artTitle") or "").strip(),
        abstract=(record.get("artAbstract") or None),
        authors=_extract_authors(record),
        year=_extract_year(record),
        venue=(record.get("journalCn") or None),
        # yiigle indexes 中华医学会 journal articles; emit a stable "article"
        # category (was previously left None) so type is consistent across
        # sources (#23).
        type="article",
        keywords=_extract_keywords(record),
        doi_url=(f"https://doi.org/{doi}" if doi else None),
        sources=["yiigle"],
    )


# ---------------------------------------------------------------------------
# Search (independent primary source)
# ---------------------------------------------------------------------------


def _fetch_page(
    query: str, page: int, page_size: int, *, session=None
) -> List[dict]:
    """Fetch one search page; return its ``infos`` list ([] on any failure).

    Never raises — a network / HTTP / JSON error degrades to an empty page so a
    flaky request cannot kill the run (graceful degradation)."""
    import requests  # local import: no new module-top dependency footprint

    body = {
        "searchType": "pt",
        "page": page,
        "pageSize": page_size,
        "queryString": query,
        "searchText": query,
        "isAggregations": "N",  # CRITICAL: "N" returns records; "Y" returns only facets
    }
    sess = session or requests
    try:
        res = sess.post(
            _SEARCH_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
    except Exception:
        return []
    if getattr(res, "status_code", None) != 200:
        return []
    try:
        data = res.json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("code") != 200:
        return []
    # Shape guard: `data.data` / `.result` may legally arrive as a list (e.g.
    # {"code":200,"data":[...]}) — calling `.get(...)` on that would raise.
    # Degrade to an empty page instead (never-raise contract).
    data_obj = data.get("data")
    if not isinstance(data_obj, dict):
        return []
    result = data_obj.get("result")
    if not isinstance(result, dict):
        return []
    infos = result.get("infos")
    return infos if isinstance(infos, list) else []


def search(
    query: str,
    n: int = 25,
    year_min: Optional[int] = None,
    session=None,
) -> List[UnifiedPaperEntity]:
    """Independent yiigle primary search — returns up to ``n`` UnifiedPaperEntity.

    Results come back in the endpoint's own relevance order (its ``score``). When
    ``year_min`` is given we filter client-side (the API exposes no reliable year
    param) — records with year < year_min OR unknown year are dropped — and
    paginate up to ``_MAX_PAGES`` to still return close to ``n`` records.

    Degrades to [] on any failure (no records, network down, HTTP error). Never
    raises."""
    if not query or not query.strip():
        return []
    query = query.strip()

    entities: List[UnifiedPaperEntity] = []
    seen: set = set()
    for page in range(1, _MAX_PAGES + 1):
        infos = _fetch_page(query, page, _PAGE_SIZE, session=session)
        if not infos:
            break
        for rec in infos:
            if not isinstance(rec, dict):
                continue  # shape guard: skip a non-dict record (never-raise)
            try:
                ent = _record_to_entity(rec)
            except Exception:
                continue
            # Filter by year FIRST, THEN mark `seen`, so a year-dropped record
            # never poisons the dedup set.
            if year_min is not None and (ent.year is None or ent.year < year_min):
                continue
            # De-dup by artId (repeats occur intra-page and across pages): the
            # source_native_id is "yiigle:<artId>"; fall back to doi/title for the
            # rare id-less record.
            key = ent.source_native_id or ent.doi or ent.title
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)
            if len(entities) >= n:
                return entities[:n]
        # Last page reached (partial page) -> stop.
        if len(infos) < _PAGE_SIZE:
            break
        if page < _MAX_PAGES:
            time.sleep(_PAGE_SLEEP)
    return entities[:n]


# ---------------------------------------------------------------------------
# Serialisation (matches ss_helper._search_entity_to_dict — full entity shape)
# ---------------------------------------------------------------------------


def _entity_to_dict(p: UnifiedPaperEntity) -> dict:
    """Full serialisation of a search-produced entity — the SAME broad field set
    openalex_helper / ss_helper emit (entity.__dict__ with Author flattening), so
    federated_kg_resolver ingests yiigle output exactly like openalex.json."""
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


def _main_cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="yiigle_helper",
        description=(
            "yiigle helper — independent Chinese-medical primary search "
            "(中华医学期刊全文数据库). Outputs UnifiedPaperEntity[] like ss_helper --search."
        ),
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        required=True,
        help="Native-Chinese medical query (e.g. 深度学习 / 基因编辑 / 治疗).",
    )
    parser.add_argument(
        "--n", type=int, default=25, help="Number of records to return (default 25)."
    )
    parser.add_argument(
        "--year-min",
        type=int,
        default=None,
        help="Minimum publication year (inclusive). Records with unknown year are dropped.",
    )
    parser.add_argument(
        "--output-file", help="Where to write the JSON output (defaults to stdout)."
    )
    args = parser.parse_args()

    results = search(args.search, n=args.n, year_min=args.year_min)
    output = [_entity_to_dict(p) for p in results]
    payload = json.dumps(output, indent=2, ensure_ascii=False)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        sys.stdout.write(payload)
        sys.stdout.write("\n")

    # Compliance attribution — stderr only, so stdout stays a pure JSON document.
    print(ATTRIBUTION, file=sys.stderr)


if __name__ == "__main__":
    _main_cli()
