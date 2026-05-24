"""PubMed helper: L2 MeSH enricher (primary use case) + Audit-tier search_by_mesh.

Architecture (v2.0): For typical use, NO independent search — only enriches
existing UnifiedPaperEntity (those with pmid from OpenAlex) with MeSH terms,
publication types, and PMC URL.

For Audit-tier with explicit MeSH query, supports independent search_by_mesh.

Rate limit: NCBI API key gets 10 req/s (vs 3 without). We use 5 req/s safe rate.

Background (per 24_v2_l2_booster_test.md and 25_round2_synthesis.md):
- PubMed "unique" papers vs OpenAlex sample: 30/30 already in OpenAlex globally.
- PubMed's true value = MeSH terms / publication_types / PMC link enrichment,
  NOT independent recall.
- search_by_mesh kept only for Audit tier (PRISMA workflow requirement).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from Bio import Entrez

from .types import Config, UnifiedPaperEntity

# 5 req/s safe rate with key (key allows 10). Each helper call sleeps before request.
_RATE_LIMIT_SLEEP = 0.2

_initialized = False


def init(config: Config) -> None:
    """Configure biopython Entrez globals from Config. Idempotent.

    NCBI policy requires email + tool identifiers even without an API key.
    """
    global _initialized
    Entrez.email = config.ncbi_email or "anonymous@example.com"
    if config.ncbi_api_key:
        Entrez.api_key = config.ncbi_api_key
    Entrez.tool = "paper-search-pro"
    _initialized = True


def _ensure_init() -> None:
    if not _initialized:
        raise RuntimeError("Call pubmed_helper.init(config) first")


# ---------------------------------------------------------------------------
# Internal: XML record parsing
# ---------------------------------------------------------------------------

def _xml_str(value) -> str:
    """Convert a Biopython Entrez XML node to plain str, handling StringElement / dicts."""
    if value is None:
        return ""
    if hasattr(value, "title"):  # StringElement
        return str(value)
    if isinstance(value, dict):
        return value.get("#text") or value.get("@UI", "") or ""
    return str(value)


def _parse_mesh_terms(medline_citation: dict) -> List[str]:
    """Extract MeSH descriptor names from a PubMed MedlineCitation dict."""
    mesh_terms: List[str] = []
    mh_list = medline_citation.get("MeshHeadingList", []) or []
    for mh in mh_list:
        desc = mh.get("DescriptorName")
        term = _xml_str(desc)
        if term:
            mesh_terms.append(term)
    return mesh_terms


def _parse_publication_types(article: dict) -> List[str]:
    """Extract publication types (e.g. 'Clinical Trial', 'Review')."""
    types: List[str] = []
    pub_types = article.get("PublicationTypeList", []) or []
    for pt in pub_types:
        t = _xml_str(pt)
        if t:
            types.append(t)
    return types


def _parse_article_ids(rec: dict) -> Dict[str, Optional[str]]:
    """Extract doi/pmcid from PubmedData.ArticleIdList."""
    doi: Optional[str] = None
    pmcid: Optional[str] = None
    article_ids = (rec.get("PubmedData") or {}).get("ArticleIdList") or []
    for aid in article_ids:
        idtype = None
        if hasattr(aid, "attributes"):
            idtype = aid.attributes.get("IdType")
        value = _xml_str(aid)
        if idtype == "doi":
            doi = value.lower()
        elif idtype == "pmc":
            pmcid = value
    return {"doi": doi, "pmcid": pmcid}


def _parse_pmid_record(rec: dict) -> Dict:
    """Convert one PubmedArticle XML record into a structured dict."""
    medline = rec.get("MedlineCitation", {}) or {}
    article = medline.get("Article", {}) or {}

    pmid = _xml_str(medline.get("PMID", ""))
    title = _xml_str(article.get("ArticleTitle", "") or "")

    abstract_parts = (article.get("Abstract") or {}).get("AbstractText") or []
    if isinstance(abstract_parts, list):
        abstract = " ".join(_xml_str(a) for a in abstract_parts).strip()
    else:
        abstract = _xml_str(abstract_parts)

    ids = _parse_article_ids(rec)
    doi = ids["doi"]
    pmcid = ids["pmcid"]

    year: Optional[int] = None
    pub_date = ((article.get("Journal") or {}).get("JournalIssue") or {}).get("PubDate") or {}
    if "Year" in pub_date:
        try:
            year = int(_xml_str(pub_date["Year"]))
        except (ValueError, TypeError):
            year = None

    return {
        "pmid": pmid,
        "doi": doi,
        "pmcid": pmcid,
        "pmc_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None,
        "title": title,
        "abstract": abstract,
        "year": year,
        "mesh_terms": _parse_mesh_terms(medline),
        "publication_types": _parse_publication_types(article),
        # P0-6 fix: stamp provenance so downstream entity-builders
        # (federated_kg_resolver._papers_from_payload) preserve "pubmed" in
        # UnifiedPaperEntity.sources. Without this, search_by_mesh /
        # search_keyword outputs convert to entities with sources=[], which
        # makes PRISMA logs under-report the databases actually queried.
        "sources": ["pubmed"],
    }


# ---------------------------------------------------------------------------
# L2 Primary use: Enrichment (no independent search)
# ---------------------------------------------------------------------------

def enrich_with_mesh(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """Add MeSH terms + publication_types + PMC URL to papers that have a pmid.

    Primary use case (per SA-V2): PubMed's value is enrichment, not recall.
    Mutates the input list in place; papers without pmid are skipped (those need
    to be in OpenAlex's medical subset to acquire a pmid first).

    Bulk efetch uses a single comma-separated id list — one network call for the
    full eligible set, regardless of size (NCBI accepts up to ~200 per request).
    """
    _ensure_init()
    eligible = [(i, p) for i, p in enumerate(papers) if p.pmid]
    if not eligible:
        return papers

    pmid_list = ",".join(p.pmid for _, p in eligible)
    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid_list, rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception:
        return papers

    articles = records.get("PubmedArticle", []) or []
    pmid_to_data: Dict[str, Dict] = {}
    for art in articles:
        parsed = _parse_pmid_record(art)
        if parsed["pmid"]:
            pmid_to_data[parsed["pmid"]] = parsed

    for _, p in eligible:
        data = pmid_to_data.get(p.pmid)
        if not data:
            continue
        # mesh + pub types are always overwritten with authoritative PubMed data
        p.mesh_terms = data["mesh_terms"]
        p.publication_types = data["publication_types"]
        # pmcid / pmc_url only filled if missing
        if not p.pmcid and data["pmcid"]:
            p.pmcid = data["pmcid"]
        if not p.pmc_url and data["pmc_url"]:
            p.pmc_url = data["pmc_url"]
        # abstract only filled if missing (OpenAlex reconstruction has priority)
        if not p.abstract and data["abstract"]:
            p.abstract = data["abstract"]
        if "pubmed" not in p.sources:
            p.sources.append("pubmed")

    return papers


def get_paper_by_pmid(pmid: str) -> Optional[Dict]:
    """Single-paper lookup by PMID. Returns parsed dict (helper boundary stays clean).

    The caller decides whether to materialize a UnifiedPaperEntity from this dict.
    """
    _ensure_init()
    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception:
        return None
    articles = records.get("PubmedArticle", []) or []
    if not articles:
        return None
    return _parse_pmid_record(articles[0])


# ---------------------------------------------------------------------------
# L2 Audit-tier: Independent search by MeSH (PRISMA workflow only)
# ---------------------------------------------------------------------------

def search_by_mesh(
    mesh_term: str,
    year_min: Optional[int] = None,
    publication_types: Optional[List[str]] = None,
    limit: int = 25,
) -> List[Dict]:
    """Independent PubMed search using MeSH precision.

    Used by Audit tier (PRISMA workflow requires MeSH). Returns parsed dicts.
    Filter by publication_types (e.g. ["Clinical Trial", "Meta-Analysis"]).
    """
    _ensure_init()
    term = f'"{mesh_term}"[MeSH Terms]'
    if year_min:
        term += f" AND ({year_min}:3000[dp])"
    if publication_types:
        type_filter = " OR ".join(f'"{pt}"[Publication Type]' for pt in publication_types)
        term += f" AND ({type_filter})"

    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.esearch(db="pubmed", term=term, retmax=limit)
        record = Entrez.read(handle)
        handle.close()
    except Exception:
        return []

    pmids = record.get("IdList", []) or []
    if not pmids:
        return []

    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.efetch(db="pubmed", id=",".join(pmids), rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception:
        return []

    articles = records.get("PubmedArticle", []) or []
    return [_parse_pmid_record(art) for art in articles]


def search_keyword(query: str, year_min: Optional[int] = None, limit: int = 25) -> List[Dict]:
    """Generic PubMed keyword search (auto-expands to MeSH internally). Audit-tier
    secondary path when no explicit MeSH term is known.
    """
    _ensure_init()
    term = query
    if year_min:
        term += f" AND ({year_min}:3000[dp])"

    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.esearch(db="pubmed", term=term, retmax=limit)
        record = Entrez.read(handle)
        handle.close()
    except Exception:
        return []

    pmids = record.get("IdList", []) or []
    if not pmids:
        return []

    time.sleep(_RATE_LIMIT_SLEEP)
    try:
        handle = Entrez.efetch(db="pubmed", id=",".join(pmids), rettype="xml", retmode="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception:
        return []

    articles = records.get("PubmedArticle", []) or []
    return [_parse_pmid_record(art) for art in articles]


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    # Allow direct invocation: `python scripts/pubmed_helper.py ...`
    SKILL_ROOT = Path(__file__).resolve().parent.parent
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))

    from scripts.config import load_config  # noqa: E402

    parser = argparse.ArgumentParser(description="PubMed L2 helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_enrich = sub.add_parser("enrich", help="Enrich a JSON-list of papers (need pmid) with MeSH/PMC")
    p_enrich.add_argument("--input-file", required=True)
    p_enrich.add_argument("--output-file", default=None)

    p_mesh = sub.add_parser("search-mesh", help="Audit-tier MeSH search")
    p_mesh.add_argument("mesh_term")
    p_mesh.add_argument("--year-min", type=int, default=None)
    p_mesh.add_argument("--pub-type", action="append", default=None,
                        help='Repeat to add filters, e.g. --pub-type "Clinical Trial"')
    p_mesh.add_argument("--limit", type=int, default=25)

    p_kw = sub.add_parser("search", help="Generic keyword search")
    p_kw.add_argument("query")
    p_kw.add_argument("--year-min", type=int, default=None)
    p_kw.add_argument("--limit", type=int, default=25)

    p_pmid = sub.add_parser("by-pmid", help="Fetch one record by PMID")
    p_pmid.add_argument("pmid")

    args = parser.parse_args()
    init(load_config())

    if args.cmd == "enrich":
        raw = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
        papers = [UnifiedPaperEntity(**rec) for rec in raw]
        enriched = enrich_with_mesh(papers)
        out = [p.__dict__ for p in enriched]
        out_text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
        if args.output_file:
            Path(args.output_file).write_text(out_text, encoding="utf-8")
        else:
            print(out_text)
    elif args.cmd == "search-mesh":
        results = search_by_mesh(args.mesh_term, year_min=args.year_min,
                                 publication_types=args.pub_type, limit=args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "search":
        results = search_keyword(args.query, year_min=args.year_min, limit=args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif args.cmd == "by-pmid":
        result = get_paper_by_pmid(args.pmid)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
