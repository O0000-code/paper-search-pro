"""Export materialized papers to BibTeX, RIS, CSV, and JSON formats.

These exports are the primary downstream-facing artifacts: BibTeX for LaTeX,
RIS for Zotero/EndNote, CSV for Excel/Sheets, JSON for programmatic use.

v2.0 refactor: SearchState removed. `generate_exports` now accepts a classified
KG (Dict[str, UnifiedPaperEntity]) directly. Eligibility filter: RCS >= 5.
"""

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .types import UnifiedPaperEntity


# =============================================================================
# Public entry
# =============================================================================

def generate_exports(
    kg: Dict[str, UnifiedPaperEntity],
    output_dir: Path,
    *,
    min_rcs: int = 5,
) -> Dict[str, Path]:
    """Write four export files. Returns a dict of artifact -> path.

    Args:
        kg: classified knowledge graph (canonical_key -> paper).
        output_dir: directory where papers.bib / papers.ris / papers.csv /
            papers.json will be written.
        min_rcs: minimum RCS to include in exports (default: 5 = closely related).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    papers = list(kg.values())
    # Eligible for export: classified at or above min_rcs.
    exportable = [p for p in papers if (p.rcs or 0) >= min_rcs]
    # Stable display order — highest RCS first.
    exportable.sort(key=lambda p: (-(p.rcs or 0), -(p.citation_count or 0)))

    bib_path = output_dir / "papers.bib"
    ris_path = output_dir / "papers.ris"
    csv_path = output_dir / "papers.csv"
    json_path = output_dir / "papers.json"

    bib_path.write_text(_render_bibtex(exportable), encoding="utf-8")
    ris_path.write_text(_render_ris(exportable), encoding="utf-8")
    _render_csv(exportable, csv_path)
    json_path.write_text(
        json.dumps(_render_json(exportable), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "bibtex": bib_path,
        "ris": ris_path,
        "csv": csv_path,
        "json": json_path,
    }


# =============================================================================
# BibTeX
# =============================================================================

_BIBTEX_ESCAPE = {
    "{": r"\{",
    "}": r"\}",
    "\\": r"\\",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
}


def _bibtex_escape(text: str) -> str:
    if not text:
        return ""
    out = []
    for ch in text:
        out.append(_BIBTEX_ESCAPE.get(ch, ch))
    return "".join(out)


def _bibtex_key(p: UnifiedPaperEntity) -> str:
    """Generate a citation key: FirstAuthorLastNameYear (no spaces, ASCII letters only)."""
    last = "Anon"
    if p.authors:
        name = p.authors[0].name or ""
        # Try "Lastname, F." or "F. Lastname"
        if "," in name:
            last = name.split(",", 1)[0].strip()
        else:
            parts = name.strip().split()
            if parts:
                last = parts[-1]
    last_clean = re.sub(r"[^A-Za-z0-9]", "", last) or "Anon"
    year = p.year or "n.d."
    return f"{last_clean}{year}"


def _format_authors_bibtex(p: UnifiedPaperEntity) -> str:
    if not p.authors:
        return ""
    return " and ".join(a.name for a in p.authors if a.name)


def _render_bibtex(papers: List[UnifiedPaperEntity]) -> str:
    """One entry per paper. We pick the closest BibTeX type from p.type."""
    seen_keys: Dict[str, int] = {}
    entries: List[str] = []
    for p in papers:
        key = _bibtex_key(p)
        if key in seen_keys:
            seen_keys[key] += 1
            key = f"{key}{chr(ord('a') + seen_keys[key])}"
        else:
            seen_keys[key] = 0
        entry_type = _bibtex_type_for(p.type)
        fields: List[str] = []
        if p.title:
            fields.append(f"  title = {{{_bibtex_escape(p.title)}}}")
        authors = _format_authors_bibtex(p)
        if authors:
            fields.append(f"  author = {{{_bibtex_escape(authors)}}}")
        if p.year:
            fields.append(f"  year = {{{p.year}}}")
        if p.venue:
            fields.append(f"  journal = {{{_bibtex_escape(p.venue)}}}")
        if p.doi:
            fields.append(f"  doi = {{{p.doi}}}")
        if p.doi_url or p.doi:
            url = p.doi_url or f"https://doi.org/{p.doi}"
            fields.append(f"  url = {{{url}}}")
        if p.abstract:
            fields.append(f"  abstract = {{{_bibtex_escape(p.abstract)}}}")
        if p.rcs is not None:
            fields.append(f"  note = {{RCS={p.rcs}; discovery_path={p.discovery_path or 'n/a'}}}")
        entries.append("@" + entry_type + "{" + key + ",\n" + ",\n".join(fields) + "\n}\n")
    return "\n".join(entries)


def _bibtex_type_for(record_type: str) -> str:
    if not record_type:
        return "article"
    rt = record_type.lower()
    if "book" in rt:
        return "book"
    if "preprint" in rt or "arxiv" in rt:
        return "misc"
    if "dataset" in rt:
        return "misc"
    if "review" in rt:
        return "article"
    return "article"


# =============================================================================
# RIS
# =============================================================================

def _render_ris(papers: List[UnifiedPaperEntity]) -> str:
    """RIS tagged-line format. Two-letter tag followed by ' - ' then value."""
    lines: List[str] = []
    for p in papers:
        ty = _ris_type_for(p.type)
        lines.append(f"TY  - {ty}")
        if p.title:
            lines.append(f"TI  - {p.title}")
        for a in (p.authors or []):
            if a.name:
                lines.append(f"AU  - {a.name}")
        if p.year:
            lines.append(f"PY  - {p.year}")
        if p.venue:
            lines.append(f"JO  - {p.venue}")
        if p.doi:
            lines.append(f"DO  - {p.doi}")
        if p.doi_url or p.doi:
            lines.append(f"UR  - {p.doi_url or f'https://doi.org/{p.doi}'}")
        if p.abstract:
            # RIS abstracts must be single-line; replace newlines.
            abstract_clean = re.sub(r"\s+", " ", p.abstract).strip()
            lines.append(f"AB  - {abstract_clean}")
        if p.rcs is not None:
            lines.append(f"N1  - RCS={p.rcs}; discovery_path={p.discovery_path or 'n/a'}")
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


def _ris_type_for(record_type: str) -> str:
    if not record_type:
        return "JOUR"
    rt = record_type.lower()
    if "book" in rt:
        return "BOOK"
    if "preprint" in rt or "arxiv" in rt:
        return "UNPD"
    if "dataset" in rt:
        return "DATA"
    return "JOUR"


# =============================================================================
# CSV
# =============================================================================

def _render_csv(papers: List[UnifiedPaperEntity], output_path: Path) -> None:
    """Excel/Sheets-compatible CSV with UTF-8 BOM for Excel auto-detection."""
    fields = [
        "paper_id",
        "title",
        "authors",
        "year",
        "venue",
        "doi",
        "doi_url",
        "rcs",
        "rcs_reasoning",
        "rcs_flag",
        "citation_count",
        "influential_citation_count",
        "tldr",
        "abstract",
        "discovery_path",
        "sources",
        "is_oa",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for p in papers:
            row = {
                "paper_id": p.paper_id,
                "title": p.title or "",
                "authors": "; ".join(a.name for a in (p.authors or []) if a.name),
                "year": p.year or "",
                "venue": p.venue or "",
                "doi": p.doi or "",
                "doi_url": p.doi_url or (f"https://doi.org/{p.doi}" if p.doi else ""),
                "rcs": p.rcs if p.rcs is not None else "",
                "rcs_reasoning": p.rcs_reasoning or "",
                "rcs_flag": p.rcs_flag or "",
                "citation_count": p.citation_count or 0,
                "influential_citation_count": p.influential_citation_count or "",
                "tldr": p.tldr or "",
                "abstract": p.abstract or "",
                "discovery_path": p.discovery_path or "",
                "sources": ";".join(p.sources or []),
                "is_oa": p.is_oa if p.is_oa is not None else "",
            }
            writer.writerow(row)


# =============================================================================
# JSON
# =============================================================================

def _render_json(papers: List[UnifiedPaperEntity]) -> List[Dict[str, Any]]:
    return [
        {
            "paper_id": p.paper_id,
            "doi": p.doi,
            "arxiv_id": p.arxiv_id,
            "openalex_id": p.openalex_id,
            "ss_paper_id": p.ss_paper_id,
            "title": p.title,
            "abstract": p.abstract,
            "authors": [
                {
                    "name": a.name,
                    "orcid": a.orcid,
                    "affiliation": a.affiliation,
                    "country": a.country,
                    "is_first": a.is_first,
                    "is_corresponding": a.is_corresponding,
                }
                for a in (p.authors or [])
            ],
            "year": p.year,
            "venue": p.venue,
            "type": p.type,
            "citation_count": p.citation_count or 0,
            "fwci": p.fwci,
            "topics": p.topics,
            "keywords": p.keywords,
            "tldr": p.tldr,
            "influential_citation_count": p.influential_citation_count,
            "doi_url": p.doi_url,
            "rcs": p.rcs,
            "rcs_reasoning": p.rcs_reasoning,
            "rcs_flag": p.rcs_flag,
            "sources": p.sources,
            "discovery_path": p.discovery_path,
            "is_oa": p.is_oa,
        }
        for p in papers
    ]


# =============================================================================
# CLI
# =============================================================================

def _kg_from_json(payload) -> Dict[str, UnifiedPaperEntity]:
    """Decode kg.json into Dict[str, UnifiedPaperEntity]."""
    from .types import Author

    def _paper(d: Dict) -> UnifiedPaperEntity:
        authors = [
            Author(
                name=a.get("name", "") if isinstance(a, dict) else str(a),
                orcid=a.get("orcid") if isinstance(a, dict) else None,
                affiliation=a.get("affiliation") if isinstance(a, dict) else None,
                country=a.get("country") if isinstance(a, dict) else None,
                is_first=bool(a.get("is_first")) if isinstance(a, dict) else False,
                is_corresponding=bool(a.get("is_corresponding")) if isinstance(a, dict) else False,
            )
            for a in (d.get("authors") or [])
        ]
        return UnifiedPaperEntity(
            doi=d.get("doi"),
            arxiv_id=d.get("arxiv_id"),
            openalex_id=d.get("openalex_id"),
            ss_paper_id=d.get("ss_paper_id"),
            pmid=d.get("pmid"),
            pmcid=d.get("pmcid"),
            title=d.get("title", "") or "",
            abstract=d.get("abstract"),
            authors=authors,
            year=d.get("year"),
            venue=d.get("venue"),
            type=d.get("type"),
            citation_count=int(d.get("citation_count") or 0),
            fwci=d.get("fwci"),
            topics=list(d.get("topics") or []),
            keywords=list(d.get("keywords") or []),
            influential_citation_count=d.get("influential_citation_count"),
            tldr=d.get("tldr"),
            doi_url=d.get("doi_url"),
            rcs=d.get("rcs"),
            rcs_reasoning=d.get("rcs_reasoning"),
            rcs_flag=d.get("rcs_flag"),
            sources=list(d.get("sources") or []),
            discovery_path=d.get("discovery_path"),
            is_oa=d.get("is_oa"),
        )

    kg: Dict[str, UnifiedPaperEntity] = {}
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, dict):
                kg[str(k)] = _paper(v)
    elif isinstance(payload, list):
        for d in payload:
            if not isinstance(d, dict):
                continue
            paper = _paper(d)
            kg[paper.paper_id] = paper
    return kg


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Generate BibTeX / RIS / CSV / JSON exports from a classified KG. "
            "Exports papers with RCS >= --min-rcs (default 5)."
        )
    )
    parser.add_argument(
        "--kg",
        required=True,
        type=Path,
        help="Path to kg_classified.json.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory to write papers.bib / papers.ris / papers.csv / papers.json.",
    )
    parser.add_argument(
        "--min-rcs",
        type=int,
        default=5,
        help="Minimum RCS to include (default 5 = closely related).",
    )
    args = parser.parse_args()

    if not args.kg.exists():
        sys.exit(f"generate_exports: KG not found at {args.kg}")

    kg = _kg_from_json(json.loads(args.kg.read_text(encoding="utf-8")))
    if not kg:
        sys.exit(f"generate_exports: empty KG loaded from {args.kg}")
    artifacts = generate_exports(kg, args.output_dir, min_rcs=args.min_rcs)
    for name, path in artifacts.items():
        print(f"generate_exports: {name} -> {path}")
