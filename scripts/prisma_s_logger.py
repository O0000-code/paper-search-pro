"""PRISMA-S checklist log + full execution log serialization.

PRISMA-S is the 16-item search reporting standard from Rethlefsen et al. (2021).
We build the checklist from a classified KG + (optional) auxiliary inputs:
discovery snapshots, query plan, errors. Missing values are kept as null with a
"note" describing why, so the report stays transparent.

v2.0 refactor: SearchState removed. Inputs are primitive collections (dict /
list / str) that the main agent persists to disk between steps.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import UnifiedPaperEntity


# =============================================================================
# PRISMA-S 16 items
# =============================================================================

def build_prisma_s_log(
    kg: Dict[str, UnifiedPaperEntity],
    *,
    user_query: str = "",
    tier: str = "standard",
    search_id: str = "",
    query_plan: Optional[List[Dict]] = None,
    discovery_curve_snapshots: Optional[List[Dict]] = None,
    output_paths: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict]] = None,
    last_event_ts: Optional[str] = None,
    started_at: Optional[str] = None,
    wall_clock_seconds: Optional[float] = None,
    max_hops: int = 0,
    max_citation_seeds: int = 0,
) -> Dict[str, Any]:
    """Return a dict keyed by PRISMA-S item numbers 1-16.

    The classified KG is the primary source. Optional fields fill in items that
    cannot be reconstructed from the KG alone (e.g. wall-clock timing).
    """
    query_plan = query_plan or []
    discovery_curve_snapshots = discovery_curve_snapshots or []
    output_paths = output_paths or {}

    sources_used = _databases_used(kg, query_plan)
    query_texts = [q.get("text", "") for q in query_plan if isinstance(q, dict)]
    query_filters = [q.get("filters", []) for q in query_plan if isinstance(q, dict)]
    classified_count = sum(1 for p in kg.values() if p.rcs is not None)
    highly_relevant = sum(
        1 for p in kg.values() if p.rcs is not None and p.rcs >= 7
    )
    coverage = _estimate_coverage_from_snapshots(discovery_curve_snapshots)

    return {
        "1_database_information": {
            "databases": sources_used,
            "primary": "OpenAlex"
            if "openalex" in sources_used
            else (sources_used[0] if sources_used else None),
            "note": "OpenAlex polite pool + Semantic Scholar (supplement). Audit may add PubMed/arXiv.",
        },
        "2_multi_database_searching": {
            "performed": len(sources_used) >= 2,
            "rationale": "Multi-database search reduces single-source bias (Bramer 2018: 98.3% recall achievable with >=2 databases).",
        },
        "3_study_registries": {
            "queried": False,
            "note": "Not queried by default. Available via audit tier add-ons if user enables Cochrane/ClinicalTrials.",
        },
        "4_online_resources_browsing": {
            "performed": False,
            "note": "Out of scope for this skill; pre-supplied via user citation seeds when relevant.",
        },
        "5_citation_searching": {
            "performed": _used_citation_expansion(kg),
            "method": "OpenAlex forward+backward citation chase up to configured max_hops.",
            "max_hops": max_hops,
            "seeds_count": min(max_citation_seeds, _citation_seeds_used(kg))
            if max_citation_seeds
            else _citation_seeds_used(kg),
        },
        "6_contacts": {
            "performed": False,
            "note": "Skill does not contact authors; relies on published records only.",
        },
        "7_other_methods": {
            "performed": False,
            "methods": [],
        },
        "8_full_search_strategies": {
            "queries": query_texts,
            "boolean_expressions": [
                {
                    "text": q.get("text"),
                    "openalex": q.get("boolean_openalex"),
                    "semantic_scholar": q.get("boolean_ss"),
                    "type": q.get("type"),
                }
                for q in query_plan
                if isinstance(q, dict)
            ],
            "note": "Strategy reproducible; same boolean expressions executed against each database.",
        },
        "9_limits_and_restrictions": {
            "filters_applied": query_filters,
            "language": None,
            "publication_type": None,
            "note": "No restrictive filters by default; tier budget bounds the number of records returned.",
        },
        "10_search_filters": {
            "validated_filters_used": [],
            "note": "No pre-validated hedges used; query plan uses LLM-decomposed terms.",
        },
        "11_prior_work": {
            "force_includes": [],
            "note": "User-supplied force_include DOIs (config force_include) are merged into the result set.",
        },
        "12_updates": {
            "incremental_search": False,
            "note": "Not incremental within a single run; checkpoint enables manual re-run on demand.",
        },
        "13_dates_of_searches": {
            "search_started_at": started_at,
            "search_ended_at": last_event_ts,
            "wall_clock_seconds": (
                round(wall_clock_seconds, 1)
                if isinstance(wall_clock_seconds, (int, float))
                else None
            ),
        },
        "14_total_records": {
            "records_screened": classified_count,
            "papers_in_kg": len(kg),
            "highly_relevant_count": highly_relevant,
            "coverage_estimate": coverage,
        },
        "15_deduplication": {
            "performed": True,
            "method": (
                "FederatedKG dedup: DOI (Level 1) -> arXiv ID (Level 2) -> "
                "PMID/OpenAlex/SS fallback -> (normalized_title, year) (last "
                "resort). E5b guard prevents same-title-different-DOI collapse."
            ),
            "note": "Provenance preserved per paper in sources[].",
        },
        "16_record_management": {
            "tool": "paper-search-pro/2.0",
            "format": "JSONL append-only checkpoint + materialized JSON outputs",
            "outputs_produced": list(output_paths.keys()),
        },
        "_meta": {
            "search_id": search_id,
            "user_query": user_query,
            "tier": tier,
        },
    }


# =============================================================================
# Helpers
# =============================================================================

def _databases_used(
    kg: Dict[str, UnifiedPaperEntity],
    query_plan: List[Dict],
) -> List[str]:
    sources: set = set()
    for p in kg.values():
        for s in (p.sources or []):
            sources.add(s)
    if not sources:
        # Fallback to plan-stated sources
        for q in query_plan:
            if isinstance(q, dict):
                src = q.get("source")
                if src:
                    if src == "both":
                        sources.update(["openalex", "semantic_scholar"])
                    else:
                        sources.add(src)
    # Stable ordering with OpenAlex first when present
    ordered: List[str] = []
    if "openalex" in sources:
        ordered.append("openalex")
    if "semantic_scholar" in sources:
        ordered.append("semantic_scholar")
    for s in sorted(sources):
        if s not in ordered:
            ordered.append(s)
    return ordered


def _used_citation_expansion(kg: Dict[str, UnifiedPaperEntity]) -> bool:
    for p in kg.values():
        if p.discovery_path and ("ref of" in p.discovery_path or "cites" in p.discovery_path):
            return True
    return False


def _citation_seeds_used(kg: Dict[str, UnifiedPaperEntity]) -> int:
    seeds: set = set()
    for p in kg.values():
        dp = p.discovery_path or ""
        if dp.startswith("ref of ") or dp.startswith("cites "):
            parts = dp.split(" ", 2)
            if len(parts) >= 3:
                seeds.add(parts[-1].strip())
    return len(seeds)


def _estimate_coverage_from_snapshots(snapshots: List[Dict]) -> float:
    """Best-effort recall estimate from saturation snapshots."""
    if not snapshots:
        return 0.0
    last = snapshots[-1]
    if not isinstance(last, dict):
        return 0.0
    return float(last.get("coverage_estimate") or 0.0)


# =============================================================================
# Execution log writer
# =============================================================================

def write_execution_log(
    output_path: Path,
    *,
    kg: Dict[str, UnifiedPaperEntity],
    user_query: str = "",
    tier: str = "standard",
    search_id: str = "",
    query_plan: Optional[List[Dict]] = None,
    discovery_curve_snapshots: Optional[List[Dict]] = None,
    output_paths: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict]] = None,
    last_event_ts: Optional[str] = None,
    started_at: Optional[str] = None,
    wall_clock_seconds: Optional[float] = None,
    max_hops: int = 0,
    max_citation_seeds: int = 0,
    max_papers: Optional[int] = None,
    max_rounds: Optional[int] = None,
    max_wallclock_s: Optional[float] = None,
    papers_evaluated: Optional[int] = None,
    rounds_completed: Optional[int] = None,
) -> Path:
    """Compose the full execution log (PRISMA-S + snapshots + errors + stop)."""
    output_path = Path(output_path)
    prisma = build_prisma_s_log(
        kg,
        user_query=user_query,
        tier=tier,
        search_id=search_id,
        query_plan=query_plan,
        discovery_curve_snapshots=discovery_curve_snapshots,
        output_paths=output_paths,
        errors=errors,
        last_event_ts=last_event_ts,
        started_at=started_at,
        wall_clock_seconds=wall_clock_seconds,
        max_hops=max_hops,
        max_citation_seeds=max_citation_seeds,
    )
    log = {
        "prisma_s": prisma,
        "discovery_curve_snapshots": list(discovery_curve_snapshots or []),
        "agent_invocations": [],
        "errors": list(errors or []),
        "stop_reason": _final_stop_reason(
            errors=errors,
            papers_evaluated=papers_evaluated,
            max_papers=max_papers,
            rounds_completed=rounds_completed,
            max_rounds=max_rounds,
            wall_clock_seconds=wall_clock_seconds,
            max_wallclock_s=max_wallclock_s,
        ),
        "search_id": search_id,
        "user_query": user_query,
        "tier": tier,
        "generated_at": datetime.now().isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _final_stop_reason(
    *,
    errors: Optional[List[Dict]] = None,
    papers_evaluated: Optional[int] = None,
    max_papers: Optional[int] = None,
    rounds_completed: Optional[int] = None,
    max_rounds: Optional[int] = None,
    wall_clock_seconds: Optional[float] = None,
    max_wallclock_s: Optional[float] = None,
) -> str:
    if errors:
        last = errors[-1]
        if isinstance(last, dict) and "stop_reason" in last:
            return str(last["stop_reason"])
    if isinstance(papers_evaluated, int) and isinstance(max_papers, int) and max_papers > 0:
        if papers_evaluated >= max_papers:
            return f"budget_max_papers ({max_papers})"
    if isinstance(rounds_completed, int) and isinstance(max_rounds, int) and max_rounds > 0:
        if rounds_completed >= max_rounds:
            return f"budget_max_rounds ({max_rounds})"
    if (
        isinstance(wall_clock_seconds, (int, float))
        and isinstance(max_wallclock_s, (int, float))
        and max_wallclock_s > 0
        and wall_clock_seconds >= max_wallclock_s
    ):
        return "budget_max_wallclock"
    return "complete"


# =============================================================================
# CLI
# =============================================================================

def _kg_from_json(payload) -> Dict[str, UnifiedPaperEntity]:
    """Shared loader: see discovery_curve._kg_from_json for the canonical shape."""
    from .types import Author

    def _paper(d: Dict) -> UnifiedPaperEntity:
        authors = [
            Author(name=a.get("name", "")) if isinstance(a, dict) else Author(name=str(a))
            for a in (d.get("authors") or [])
        ]
        return UnifiedPaperEntity(
            doi=d.get("doi"),
            arxiv_id=d.get("arxiv_id"),
            openalex_id=d.get("openalex_id"),
            ss_paper_id=d.get("ss_paper_id"),
            pmid=d.get("pmid"),
            title=d.get("title", "") or "",
            abstract=d.get("abstract"),
            authors=authors,
            year=d.get("year"),
            venue=d.get("venue"),
            citation_count=int(d.get("citation_count") or 0),
            influential_citation_count=d.get("influential_citation_count"),
            tldr=d.get("tldr"),
            rcs=d.get("rcs"),
            rcs_reasoning=d.get("rcs_reasoning"),
            rcs_flag=d.get("rcs_flag"),
            sources=list(d.get("sources") or []),
            discovery_path=d.get("discovery_path"),
            is_oa=d.get("is_oa"),
            keywords=list(d.get("keywords") or []),
            topics=list(d.get("topics") or []),
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


def _read_json(path: Optional[Path]):
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Write the PRISMA-S 16-item execution log. Required: --search-id "
            "and --output. KG path defaults to ./paper-search-results/"
            "<search_id>/kg_classified.json (Standard+ tiers) and falls back "
            "to kg.json (Quick tier, which skips RCS classification)."
        )
    )
    parser.add_argument("--search-id", required=True, help="Search ID for this run.")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Where to write execution_log.json.",
    )
    parser.add_argument(
        "--kg",
        type=Path,
        help=(
            "Path to KG JSON. Default: ./paper-search-results/<search_id>/"
            "kg_classified.json → ./paper-search-results/<search_id>/kg.json "
            "(Quick tier fallback). Explicit --kg overrides the search."
        ),
    )
    parser.add_argument("--user-query", default="", help="Original user query string.")
    parser.add_argument("--tier", default="standard", help="Tier name.")
    parser.add_argument(
        "--query-plan",
        type=Path,
        help="Optional path to query_plan.json (list of query dicts).",
    )
    parser.add_argument(
        "--snapshots",
        type=Path,
        help="Optional path to discovery_curve_snapshots.json (list).",
    )
    parser.add_argument(
        "--output-paths",
        type=Path,
        help="Optional path to output_paths.json (dict of artifact -> path).",
    )
    parser.add_argument(
        "--errors",
        type=Path,
        help="Optional path to errors.json (list of error dicts).",
    )
    args = parser.parse_args()

    # KG path resolution: explicit --kg wins; otherwise search for kg_classified.json
    # (Standard/Deep/Audit have it after STEP 9 rcs_parser), then fall back to kg.json
    # (Quick tier writes this directly from STEP 5 federate). Helpful default so Quick
    # users don't need to remember the --kg flag.
    if args.kg:
        kg_path = args.kg
        if not kg_path.exists():
            sys.exit(f"prisma_s_logger: KG not found at {kg_path}")
    else:
        base = Path("./paper-search-results") / args.search_id
        kg_classified = base / "kg_classified.json"
        kg_fallback = base / "kg.json"
        if kg_classified.exists():
            kg_path = kg_classified
        elif kg_fallback.exists():
            kg_path = kg_fallback
            print(
                f"prisma_s_logger: kg_classified.json not found, falling back to "
                f"{kg_fallback} (Quick tier without RCS classification).",
                file=sys.stderr,
            )
        else:
            sys.exit(
                f"prisma_s_logger: neither {kg_classified} nor {kg_fallback} exists. "
                f"Pass --kg <path> explicitly or run STEP 5 federate first."
            )

    kg = _kg_from_json(json.loads(kg_path.read_text(encoding="utf-8")))
    query_plan = _read_json(args.query_plan) or []
    snapshots = _read_json(args.snapshots) or []
    output_paths = _read_json(args.output_paths) or {}
    errors = _read_json(args.errors) or []

    last_ts = None
    if snapshots and isinstance(snapshots[-1], dict):
        last_ts = snapshots[-1].get("timestamp")

    write_execution_log(
        args.output,
        kg=kg,
        user_query=args.user_query,
        tier=args.tier,
        search_id=args.search_id,
        query_plan=query_plan if isinstance(query_plan, list) else [],
        discovery_curve_snapshots=snapshots if isinstance(snapshots, list) else [],
        output_paths=output_paths if isinstance(output_paths, dict) else {},
        errors=errors if isinstance(errors, list) else [],
        last_event_ts=last_ts,
    )
    print(f"prisma_s_logger: wrote execution log to {args.output}")
