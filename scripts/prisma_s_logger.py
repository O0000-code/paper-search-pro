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
    query_plan: Any = None,
    discovery_curve_snapshots: Optional[List[Dict]] = None,
    output_paths: Optional[Dict[str, Any]] = None,
    errors: Optional[List[Dict]] = None,
    last_event_ts: Optional[str] = None,
    started_at: Optional[str] = None,
    wall_clock_seconds: Optional[float] = None,
    max_hops: int = 0,
    max_citation_seeds: int = 0,
    search_strategies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a dict keyed by PRISMA-S item numbers 1-16.

    The classified KG is the primary source. Optional fields fill in items that
    cannot be reconstructed from the KG alone (e.g. wall-clock timing).

    ``search_strategies`` (v2.4 STEP 11.5, spec §2.2): the parsed
    ``search_strategies.json`` record. When given, items 8/1/9/10 are ENRICHED with
    the per-platform export strategies (paste-ready boolean expressions + databases
    + limits + filters). This is purely ADDITIVE (R-19): when None — the default,
    and the only state Quick/Standard ever reach — every item is byte-identical to
    the pre-v2.4 log.
    """
    query_plan = normalize_query_plan(query_plan)
    discovery_curve_snapshots = discovery_curve_snapshots or []
    output_paths = output_paths or {}

    sources_used = _databases_used(kg, query_plan)
    query_texts = [q.get("text", "") for q in query_plan if isinstance(q, dict)]
    query_filters = [q.get("filters", []) for q in query_plan if isinstance(q, dict)]
    # One flat, de-duplicated list: a plan-level filter applies to every strategy.
    filters_flat = list(dict.fromkeys(
        str(f) for fs in query_filters for f in (fs if isinstance(fs, list) else [fs]) if f
    ))
    classified_count = sum(1 for p in kg.values() if p.rcs is not None)
    highly_relevant = sum(
        1 for p in kg.values() if p.rcs is not None and p.rcs >= 7
    )
    coverage = _estimate_coverage_from_snapshots(discovery_curve_snapshots)

    log: Dict[str, Any] = {
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
            "filters_applied": filters_flat if filters_flat else query_filters,
            "language": None,
            "publication_type": None,
            # The report shows the note when there is one, else the filters.
            "note": (
                None
                if filters_flat
                else "No restrictive filters by default; tier budget bounds the number of records returned."
            ),
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
            **_coverage_method(discovery_curve_snapshots),
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

    # v2.4 STEP 11.5 (additive, R-19): enrich items 8/1/9/10 with the per-platform
    # export strategies ONLY when an export ran. Untouched otherwise -> byte-identical.
    if search_strategies is not None:
        _enrich_with_search_strategies(log, search_strategies)
    return log


def _enrich_with_search_strategies(
    log: Dict[str, Any], search_strategies: Dict[str, Any]
) -> None:
    """Fold the STEP 11.5 export's per-platform strategies into items 8/1/9/10.

    Mutates ``log`` in place, appending only. Each strategy's ``prisma_s`` block
    (item8_boolean_expression / item1_database / item9_limits / item10_filter) is
    surfaced so the PRISMA-S log reproduces the exact paste-ready per-database
    strategies (item 8 is where reviewers expect the full search). A strategy whose
    boolean expression was WITHHELD by the linter (None) contributes no expression
    but is still listed as an attempted platform (honest)."""
    strategies = search_strategies.get("strategies") or []
    if not strategies:
        return

    item8 = log["8_full_search_strategies"]
    item1 = log["1_database_information"]
    item9 = log["9_limits_and_restrictions"]
    item10 = log["10_search_filters"]

    export_platforms: List[str] = []
    export_limits: List[Dict[str, Any]] = []
    export_filters: List[Any] = []
    for s in strategies:
        if not isinstance(s, dict):
            continue
        prisma = s.get("prisma_s") or {}
        platform = s.get("platform")
        expr = prisma.get("item8_boolean_expression")
        # item 8: append the paste-ready per-database boolean expression.
        item8.setdefault("boolean_expressions", []).append({
            "text": expr,
            "platform": platform,
            "host": prisma.get("item1_database"),
            "source": "search_export",
            "type": "platform_search_strategy",
            "vocab_verification_status": s.get("vocab_verification_status"),
            "withheld": expr is None,
        })
        export_platforms.append(prisma.get("item1_database") or platform)
        export_limits.append({"platform": platform, "limits": prisma.get("item9_limits")})
        filt = prisma.get("item10_filter")
        if filt:
            export_filters.append({"platform": platform, "filter": filt})

    # item 8 marker so consumers can find the export-sourced strategies.
    item8["search_export"] = {
        "generated_at": search_strategies.get("generated_at"),
        "register": search_strategies.get("register"),
        "quality_claim": search_strategies.get("quality_claim"),
        "platforms": [s.get("platform") for s in strategies if isinstance(s, dict)],
        "ref": search_strategies.get("prisma_s_item8_ref"),
    }
    # items 1 / 9 / 10: additive sub-keys (never overwrite the existing fields).
    item1["export_platforms"] = export_platforms
    item9["export_limits"] = export_limits
    if export_filters:
        item10["export_filters"] = export_filters
        item10.setdefault("validated_filters_used", []).extend(
            f["filter"] for f in export_filters
        )


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


def normalize_query_plan(plan: Any) -> List[Dict]:
    """The list-of-strategies form this log is built from.

    Accepts the documented list (``[{text, type, source, filters, ...}]``) or the
    object form a query plan is often written in: ``{strategies|queries: [...],
    year_min, year_max | year_range, rank_filter, work_type_filter, ...}``. Plan-
    level filters are recorded on every strategy, so item 9 no longer reports
    "no filters" for a run that had them.
    """
    if isinstance(plan, list):
        return [q for q in plan if isinstance(q, dict)]
    if not isinstance(plan, dict):
        return []

    plan_filters: List[str] = []
    years = plan.get("year_range") if isinstance(plan.get("year_range"), dict) else {}
    y_min = plan.get("year_min", years.get("min"))
    y_max = plan.get("year_max", years.get("max"))
    if y_min is not None or y_max is not None:
        plan_filters.append(
            f"publication_year {y_min if y_min is not None else ''}-{y_max if y_max is not None else ''}"
        )
    rank = plan.get("rank_filter")
    if isinstance(rank, dict) and rank.get("platform"):
        bands = rank.get("tiers") or rank.get("quartiles") or []
        top = " top" if rank.get("top") else ""
        plan_filters.append(
            f"journal rank: {str(rank['platform']).upper()}{top} " + ",".join(str(b) for b in bands)
        )
    work_type = plan.get("work_type_filter")
    if isinstance(work_type, str) and work_type.strip():
        plan_filters.append(f"work type: {work_type.strip()}")

    strategies = [
        q for q in (plan.get("strategies") or plan.get("queries") or []) if isinstance(q, dict)
    ]
    normalized: List[Dict] = []
    for q in strategies:
        normalized.append({
            "text": q.get("text") or q.get("query") or "",
            "type": q.get("type") or q.get("subcommand") or q.get("sort"),
            "source": q.get("source") or q.get("engine"),
            "filters": [*(q.get("filters") or []), *plan_filters],
            "boolean_openalex": q.get("boolean_openalex"),
            "boolean_ss": q.get("boolean_ss"),
        })
    if not normalized and plan_filters:
        normalized.append({"text": plan.get("search_topic") or "", "filters": plan_filters})
    return normalized


def _coverage_method(snapshots: List[Dict]) -> Dict[str, Any]:
    """How the coverage estimate was obtained, when the snapshot says so."""
    last = snapshots[-1] if snapshots else None
    if isinstance(last, dict) and last.get("method"):
        return {"coverage_method": last["method"]}
    return {}


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
    search_strategies: Optional[Dict[str, Any]] = None,
) -> Path:
    """Compose the full execution log (PRISMA-S + snapshots + errors + stop).

    ``search_strategies`` (v2.4 STEP 11.5): parsed search_strategies.json, threaded
    to ``build_prisma_s_log`` to enrich items 8/1/9/10. Additive / None-default (R-19).
    """
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
        search_strategies=search_strategies,
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
            source_native_id=d.get("source_native_id"),
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
        help="Optional path to query_plan.json (list of strategies, or an object with a strategies list).",
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
    parser.add_argument(
        "--search-strategies",
        type=Path,
        help=(
            "Optional path to a v2.4 STEP 11.5 search_strategies.json. When given, "
            "PRISMA-S items 8/1/9/10 are enriched with the per-platform export "
            "strategies (paste-ready boolean expressions). Additive; omit to keep "
            "the log byte-identical to the pre-v2.4 output (R-19)."
        ),
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
    # discovery_curve.py writes a single snapshot dict (not a list). Normalize to
    # a list so the [-1] access below and the list-only checks downstream work —
    # otherwise a dict payload raises KeyError: -1 and coverage_estimate is dropped.
    if isinstance(snapshots, dict):
        snapshots = [snapshots]
    output_paths = _read_json(args.output_paths) or {}
    errors = _read_json(args.errors) or []

    last_ts = None
    if snapshots and isinstance(snapshots[-1], dict):
        last_ts = snapshots[-1].get("timestamp")

    search_strategies = None
    if getattr(args, "search_strategies", None):
        if args.search_strategies.exists():
            search_strategies = _read_json(args.search_strategies)
        else:
            print(
                f"prisma_s_logger: --search-strategies not found at "
                f"{args.search_strategies}; skipping export enrichment.",
                file=sys.stderr,
            )

    write_execution_log(
        args.output,
        kg=kg,
        user_query=args.user_query,
        tier=args.tier,
        search_id=args.search_id,
        query_plan=query_plan,
        discovery_curve_snapshots=snapshots if isinstance(snapshots, list) else [],
        output_paths=output_paths if isinstance(output_paths, dict) else {},
        errors=errors if isinstance(errors, list) else [],
        last_event_ts=last_ts,
        search_strategies=search_strategies if isinstance(search_strategies, dict) else None,
    )
    print(f"prisma_s_logger: wrote execution log to {args.output}")
