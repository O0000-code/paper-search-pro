"""Markdown report renderer.

v2.0 refactor: SearchState + LLM caller removed. The executive summary is
supplied by the main agent (which is itself an LLM running in Claude Code) as
plain markdown text. If no summary is supplied we generate a deterministic stub
from the metadata so the rendered report is still usable.

Public entry: render_md(kg, materialized_data_dir, output_path, *, summary, ...)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import UnifiedPaperEntity


def render_md(
    materialized_data_dir: Path,
    output_path: Path,
    *,
    summary: str = "",
    user_query: str = "",
    tier: str = "standard",
    skill_root: Optional[Path] = None,
) -> Path:
    """Render report.md from materialized JSON files.

    Args:
        materialized_data_dir: directory containing chart_data.json /
            paper_list.json / metadata.json (produced by data_materialization).
        output_path: where to write the markdown file.
        summary: optional executive summary text written by the main agent. If
            empty, a deterministic stub is generated from metadata.
        user_query: original natural-language query (used when metadata lacks
            it).
        tier: tier name (used when metadata lacks it).
        skill_root: optional override for skill installation root.
    """
    from jinja2 import Environment, FileSystemLoader

    materialized_data_dir = Path(materialized_data_dir)
    output_path = Path(output_path)
    skill_root = Path(skill_root) if skill_root else Path(__file__).resolve().parent.parent
    template_dir = skill_root / "assets"

    metadata = _read_json(materialized_data_dir / "metadata.json")
    paper_list = _read_json(materialized_data_dir / "paper_list.json")
    chart_data = _read_json(materialized_data_dir / "chart_data.json")

    # Inject query/tier into metadata only when missing so CLI overrides do not
    # clobber materialized values.
    metadata.setdefault("query", user_query)
    metadata.setdefault("tier", tier)

    executive_summary = (summary or "").strip()
    if not executive_summary:
        executive_summary = _fallback_summary(metadata, chart_data, paper_list)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,  # markdown output — autoescape would corrupt content
    )
    env.filters["short_authors"] = _short_authors_filter
    template = env.get_template("md_template.md.jinja")
    md_text = template.render(
        metadata=metadata,
        paper_list=paper_list,
        chart_data=chart_data,
        executive_summary=executive_summary,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md_text, encoding="utf-8")
    return output_path


def _fallback_summary(
    metadata: Dict[str, Any],
    chart_data: Dict[str, Any],
    paper_list: list,
) -> str:
    """Deterministic stub summary used when no `summary` is supplied."""
    themes = (chart_data or {}).get("theme_treemap", {}).get("themes", [])
    themes_brief = [{"name": t.get("name"), "size": t.get("value")} for t in themes[:6]]
    top_papers_brief: List[Dict[str, Any]] = []
    for p in paper_list[:5]:
        top_papers_brief.append(
            {
                "title": (p.get("title") or "")[:160],
                "authors_short": p.get("authors_short", ""),
                "year": p.get("year"),
                "rcs": p.get("rcs"),
                "venue": p.get("venue"),
            }
        )

    coverage = metadata.get("coverage_estimate")
    coverage_pct = f"{coverage * 100:.0f}%" if coverage is not None else "n/a"
    bullets: List[str] = []
    for p in top_papers_brief:
        title = (p.get("title") or "").strip()
        if title:
            bullets.append(
                f"- {p.get('authors_short', 'unknown')} ({p.get('year', 'n.d.')}) — _{title}_ "
                f"[RCS {p.get('rcs', '?')}]"
            )
    themes_line = (
        ", ".join(f"{t['name']} ({t['size']})" for t in themes_brief if t.get("name"))
        or "themes were not extracted"
    )

    parts = [
        f"This search addressed the query: _{metadata.get('query', '')}_.",
        f"In **{metadata.get('tier', 'standard')}** tier, "
        f"{metadata.get('papers_evaluated', 0)} records were screened, "
        f"of which **{metadata.get('highly_relevant_count', 0)}** scored highly relevant (RCS >= 7). "
        f"Saturation analysis estimates **{coverage_pct} coverage** of the relevant set "
        f"(95% CI {_pct(metadata.get('coverage_ci', [None, None])[0])}-"
        f"{_pct(metadata.get('coverage_ci', [None, None])[1])}).",
        f"Topic breakdown: {themes_line}.",
        "Top highly relevant papers:",
        "\n".join(bullets) if bullets else "_no highly relevant papers found_",
        "Coverage is a heuristic recall estimate, not a PRISMA-validated value. "
        "Treat results as a candidate corpus for a downstream systematic review.",
    ]
    return "\n\n".join(parts)


def _pct(x) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _short_authors_filter(authors) -> str:
    if isinstance(authors, str):
        return authors
    if isinstance(authors, list):
        if not authors:
            return ""
        if len(authors) > 4:
            return f"{authors[0]} et al."
        return ", ".join(authors)
    return ""


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# =============================================================================
# Public alias kept for callers that import `generate_md_report`.
# =============================================================================

def generate_md_report(
    materialized_data_dir: Path,
    output_path: Path,
    *,
    summary: str = "",
    user_query: str = "",
    tier: str = "standard",
    skill_root: Optional[Path] = None,
) -> Path:
    """Backwards-compatible alias for `render_md` — emphasises the public name."""
    return render_md(
        materialized_data_dir=materialized_data_dir,
        output_path=output_path,
        summary=summary,
        user_query=user_query,
        tier=tier,
        skill_root=skill_root,
    )


# =============================================================================
# CLI
# =============================================================================

def _kg_from_json(payload) -> Dict[str, UnifiedPaperEntity]:
    """Decode kg.json into Dict[str, UnifiedPaperEntity]."""
    from .types import Author

    def _paper(d: Dict) -> UnifiedPaperEntity:
        authors = [
            Author(name=a.get("name", "")) if isinstance(a, dict) else Author(name=str(a))
            for a in (d.get("authors") or [])
        ]
        return UnifiedPaperEntity(
            doi=d.get("doi"),
            arxiv_id=d.get("arxiv_id"),
            title=d.get("title", "") or "",
            abstract=d.get("abstract"),
            authors=authors,
            year=d.get("year"),
            venue=d.get("venue"),
            citation_count=int(d.get("citation_count") or 0),
            tldr=d.get("tldr"),
            rcs=d.get("rcs"),
            rcs_reasoning=d.get("rcs_reasoning"),
            sources=list(d.get("sources") or []),
            discovery_path=d.get("discovery_path"),
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
    import tempfile

    parser = argparse.ArgumentParser(
        description=(
            "Render the markdown report from a classified KG + summary. "
            "Materialises the KG to a temp directory on the fly if "
            "--materialized-dir is not supplied."
        )
    )
    parser.add_argument(
        "--kg",
        type=Path,
        help="Path to kg_classified.json (required unless --materialized-dir is given).",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="Path to executive summary markdown (written by the main agent).",
    )
    parser.add_argument(
        "--materialized-dir",
        type=Path,
        help=(
            "Directory containing chart_data/paper_list/metadata JSON files. "
            "Skip --kg when supplied."
        ),
    )
    parser.add_argument(
        "--query",
        default="",
        help="User query string (used when metadata lacks it).",
    )
    parser.add_argument(
        "--tier",
        default="standard",
        help="Tier name (used when metadata lacks it).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Where to write report.md.",
    )
    args = parser.parse_args()

    summary_text = ""
    if args.summary and args.summary.exists():
        summary_text = args.summary.read_text(encoding="utf-8")

    materialized_dir: Path
    tmp_dir_obj: Optional[tempfile.TemporaryDirectory] = None

    if args.materialized_dir:
        if not args.materialized_dir.exists():
            sys.exit(
                f"md_report: --materialized-dir not found: {args.materialized_dir}"
            )
        materialized_dir = args.materialized_dir
    else:
        if not args.kg or not args.kg.exists():
            sys.exit("md_report: provide --kg or --materialized-dir")
        from .data_materialization import materialize  # lazy

        kg = _kg_from_json(json.loads(args.kg.read_text(encoding="utf-8")))
        if not kg:
            sys.exit(f"md_report: empty KG loaded from {args.kg}")
        tmp_dir_obj = tempfile.TemporaryDirectory(prefix="md_report_")
        materialized_dir = Path(tmp_dir_obj.name)
        materialize(
            kg,
            materialized_dir,
            user_query=args.query,
            tier=args.tier,
            summary=summary_text,
        )

    try:
        out = render_md(
            materialized_data_dir=materialized_dir,
            output_path=args.output,
            summary=summary_text,
            user_query=args.query,
            tier=args.tier,
        )
        print(f"md_report: wrote {out}")
    finally:
        if tmp_dir_obj is not None:
            tmp_dir_obj.cleanup()
