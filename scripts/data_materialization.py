"""Materialize a classified KG into the JSON bundle consumed by renderers.

Produces a single `report_data.json` (consumed by html_renderer_webartifacts /
md_report) plus four sibling JSON files for tools that
expect the per-section schema:

- chart_data.json    : 5 chart datasets (year hist / RCS dist / discovery /
                       network / themes)
- paper_list.json    : per-paper render data (doi_url, authors_short, rcs, tldr,
                       ...)
- metadata.json      : report identity, tier, wall_clock, papers_evaluated,
                       coverage_estimate, ...
- prisma_log.json    : PRISMA-S 16-item checklist (built by prisma_s_logger)

v2.0 refactor: SearchState removed. `materialize` accepts the classified KG +
summary text + report identity + tier directly. Optional execution metadata
(wall_clock_seconds, discovery_curve_snapshots, search_id) lets the main agent
fill PRISMA-S item 13 / 16 when it knows the values.
"""

import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .report_identity import build_report_identity, warn_about_title
from .types import UnifiedPaperEntity


def _dump(path: Path, obj: Any) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_search_strategies(
    output_dir: Path, explicit_path: Optional[Path]
) -> Optional[Any]:
    """Load a v2.4 STEP 11.5 ``search_strategies.json`` if one exists (spec §2.2).
    (Also used for ``query_plan.json``: same read-if-present rule.)

    Reads ``explicit_path`` when given, else auto-discovers
    ``output_dir/search_strategies.json`` ("存在才读"). Returns None when absent or
    unreadable — the fold is skipped and ``report_data.json`` stays byte-identical
    to the pre-v2.4 output (R-19). Never raises."""
    path = (
        Path(explicit_path)
        if explicit_path is not None
        else Path(output_dir) / "search_strategies.json"
    )
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resolve_wall_clock(
    *,
    wall_clock_seconds: Optional[float],
    started_at: Optional[str],
    kg_source_path: Optional[Path],
) -> Optional[float]:
    """P0-7 fix: produce a non-zero wall_clock when caller didn't pass it.

    Priority:
      1. Explicit ``wall_clock_seconds`` (preserved as-is, including 0.0 if
         truly meant — see clamp note below).
      2. ``started_at`` ISO timestamp → ``now - started_at``.
      3. ``kg_source_path`` mtime → ``now - kg.mtime`` (loosest fallback).

    Returns None only when all paths fail, in which case _build_metadata writes
    0.0 (the prior behavior). Negative deltas (clock skew / stale files) are
    clamped to 0.
    """
    if wall_clock_seconds is not None:
        return wall_clock_seconds
    if started_at:
        try:
            # Accept both naive and TZ-aware ISO strings; strip a trailing 'Z'.
            iso = started_at.rstrip("Z") if started_at.endswith("Z") else started_at
            t0 = datetime.fromisoformat(iso)
            delta = (datetime.now() - t0).total_seconds()
            return max(0.0, delta)
        except (ValueError, TypeError):
            pass
    if kg_source_path is not None:
        try:
            mtime = Path(kg_source_path).stat().st_mtime
            return max(0.0, time.time() - mtime)
        except OSError:
            pass
    return None


def materialize(
    kg: Dict[str, UnifiedPaperEntity],
    output_dir: Path,
    *,
    user_query: str = "",
    search_topic: str = "",
    display_title: str = "",
    language: Optional[str] = None,
    tier: str = "standard",
    search_id: str = "",
    summary: str = "",
    discovery_curve_snapshots: Optional[List[Dict]] = None,
    wall_clock_seconds: Optional[float] = None,
    stop_reason: Optional[str] = None,
    started_at: Optional[str] = None,
    kg_source_path: Optional[Path] = None,
    search_strategies_path: Optional[Path] = None,
) -> Dict[str, Path]:
    """Write chart_data / paper_list / metadata / prisma_log + report_data.

    Args:
        kg: classified knowledge graph (canonical_key -> paper).
        output_dir: directory where the JSON files will land.
        user_query: original natural-language request, preserved verbatim for
            audit. It is never used as the report H1.
        search_topic: normalized semantic retrieval topic, without operational
            instructions or eligibility filters.
        display_title: scholarly, evidence-bounded title authored for the final
            report. A localized generic title is used when omitted.
        language: report UI language (``en`` or ``zh``). When omitted, the
            existing deterministic language detector is applied to user_query.
        tier: tier name (quick / standard / deep / audit).
        search_id: optional search ID for PRISMA-S item 16.
        summary: executive summary text (markdown, written by main agent).
        discovery_curve_snapshots: optional list of snapshot dicts produced by
            discovery_curve.make_snapshot — feeds the saturation curve panel.
        wall_clock_seconds: optional wall-clock elapsed time. Preferred direct path.
        stop_reason: optional final stop reason string.
        started_at: optional ISO timestamp marking when the main agent's STEP 1
            began. When provided and `wall_clock_seconds` is None, the elapsed
            time is computed from (now - started_at). P0-7 fix.
        kg_source_path: optional path to the kg.json that fed this run; used as
            a graceful fallback for wall_clock when neither
            `wall_clock_seconds` nor `started_at` is provided (uses
            now - kg.json mtime). P0-7 graceful fallback.
        search_strategies_path: optional path to a v2.4 STEP 11.5
            ``search_strategies.json``. When None, ``output_dir /
            search_strategies.json`` is auto-discovered ("存在才读", spec §2.2).
            When the file exists it is folded VERBATIM into ``report_data.json``
            under a NEW top-level ``search_strategies`` key. This is purely
            ADDITIVE (R-19): when no export ran — the Quick/Standard default — the
            key is absent and ``report_data.json`` is byte-identical to before.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    discovery_curve_snapshots = discovery_curve_snapshots or []

    # P0-7 fix: derive wall_clock when caller didn't pass it directly.
    wall_clock_seconds = _resolve_wall_clock(
        wall_clock_seconds=wall_clock_seconds,
        started_at=started_at,
        kg_source_path=kg_source_path,
    )

    # The run directory (where STEP 1-5 wrote raw/ and query_plan.json).
    run_dir = Path(kg_source_path).parent if kg_source_path else output_dir

    classified = [p for p in kg.values() if p.rcs is not None]
    if not classified:
        # Allow callers to materialise an unclassified KG (degraded but useful).
        classified = list(kg.values())

    year_histogram = _build_year_histogram(classified)
    pool = _read_pool_count(run_dir / "pool_count.json")
    if pool is not None and year_histogram["bins"]:
        # Additive: only runs that wrote pool_count.json (STEP 3) carry it.
        year_histogram["pool"] = pool

    chart_data = {
        "publication_year": year_histogram,
        "relevance_score": _build_rcs_distribution(classified),
        "discovery_curve": _build_discovery_curve(
            discovery_curve_snapshots,
            classified,
            kg=kg,
            raw_dir=run_dir / "raw",
        ),
        # max_nodes 50 → 150 (2026-05-23). React CitationScatter handles 150+
        # log-scale dots comfortably; previous cap was a payload-size guess
        # from when the hydrated bundle was capped at 1.5 MB. With 5 MB now
        # acceptable, the broader citation-graph view is worth +25 KB.
        "citation_network": _build_citation_network(classified, max_nodes=150),
        "theme_treemap": _build_themes(classified),
    }
    paper_list = [_render_paper(p) for p in _sorted_for_display(classified)]
    metadata = _build_metadata(
        kg=kg,
        classified=classified,
        discovery_curve=chart_data["discovery_curve"],
        user_query=user_query,
        search_topic=search_topic,
        display_title=display_title,
        language=language,
        tier=tier,
        search_id=search_id,
        wall_clock_seconds=wall_clock_seconds,
        stop_reason=stop_reason,
    )

    from .prisma_s_logger import build_prisma_s_log  # lazy; sibling module
    prisma_log = build_prisma_s_log(
        kg,
        user_query=user_query,
        tier=tier,
        search_id=search_id,
        # The run's query plan, when STEP 1 wrote one: without it the report's
        # audit tab said "no filters" for runs that had year / rank filters.
        query_plan=_load_search_strategies(run_dir, run_dir / "query_plan.json"),
        # The same estimate the chart and metadata show (one number per report).
        discovery_curve_snapshots=[{
            "coverage_estimate": chart_data["discovery_curve"]["coverage_estimate"],
            "method": chart_data["discovery_curve"]["method"],
        }],
        wall_clock_seconds=wall_clock_seconds,
    )

    report_data = {
        "metadata": metadata,
        "chart_data": chart_data,
        "paper_list": paper_list,
        "prisma_log": prisma_log,
        "summary": summary or "",
    }

    # v2.4 STEP 11.5 (additive, R-19): fold a search_strategies.json into
    # report_data under a NEW top-level key when one exists. Appended AFTER the
    # five original keys, so when no export ran the dict — and therefore the
    # serialized report_data.json — is byte-identical to the pre-v2.4 output.
    search_strategies = _load_search_strategies(output_dir, search_strategies_path)
    if search_strategies is not None:
        report_data["search_strategies"] = search_strategies

    return {
        "chart_data": _dump(output_dir / "chart_data.json", chart_data),
        "paper_list": _dump(output_dir / "paper_list.json", paper_list),
        "metadata": _dump(output_dir / "metadata.json", metadata),
        "prisma_log": _dump(output_dir / "prisma_log.json", prisma_log),
        "report_data": _dump(output_dir / "report_data.json", report_data),
    }


# ---------- Chart builders ----------

def _read_pool_count(path: Path) -> Optional[Dict[str, int]]:
    """``{count, year_min, year_max}`` from STEP 3's pool_count.json, or None.

    None when the file is missing, unreadable, or OpenAlex could not count
    (``count`` null) — the report then shows no pool sentence.
    """
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        out = {k: int(d[k]) for k in ("count", "year_min", "year_max")}
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return out


def _build_year_histogram(papers: List[UnifiedPaperEntity]) -> Dict[str, Any]:
    """Per-year bar chart with highly_relevant overlay. Empty years are omitted."""
    by_year_total: Counter = Counter()
    by_year_highly: Counter = Counter()
    for p in papers:
        if not p.year:
            continue
        by_year_total[p.year] += 1
        if (p.rcs or 0) >= 7:
            by_year_highly[p.year] += 1
    if not by_year_total:
        return {"bins": [], "year_min": None, "year_max": None}
    year_min = min(by_year_total)
    year_max = max(by_year_total)
    bins = [
        {
            "year": y,
            "total": by_year_total.get(y, 0),
            "highly_relevant": by_year_highly.get(y, 0),
        }
        for y in range(year_min, year_max + 1)
    ]
    return {"bins": bins, "year_min": year_min, "year_max": year_max}


def _build_rcs_distribution(papers: List[UnifiedPaperEntity]) -> Dict[str, Any]:
    """Histogram of RCS 0-10 with mean and 95% CI (binomial). Counts only RCS-set papers."""
    scored = [p for p in papers if p.rcs is not None]
    counts = [0] * 11
    for p in scored:
        if 0 <= int(p.rcs) <= 10:
            counts[int(p.rcs)] += 1
    n = sum(counts)
    if n == 0:
        return {"bins": [], "mean": None, "ci_low": None, "ci_high": None, "n": 0}
    weighted = sum(i * counts[i] for i in range(11))
    mean = weighted / n
    # 95% CI on the mean assuming sample standard deviation; falls back to 0 when n<=1.
    if n > 1:
        var = sum(counts[i] * (i - mean) ** 2 for i in range(11)) / (n - 1)
        stderr = math.sqrt(var) / math.sqrt(n)
    else:
        stderr = 0.0
    ci_low = max(0.0, mean - 1.96 * stderr)
    ci_high = min(10.0, mean + 1.96 * stderr)
    return {
        "bins": [{"rcs": i, "count": counts[i]} for i in range(11)],
        "mean": round(mean, 2),
        "ci_low": round(ci_low, 2),
        "ci_high": round(ci_high, 2),
        "n": n,
    }


def _build_discovery_curve(
    snapshots: List[Dict],
    papers: List[UnifiedPaperEntity],
    *,
    kg: Optional[Dict[str, UnifiedPaperEntity]] = None,
    raw_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Coverage panel data: the ``discovery_curve`` estimate, rendered.

    One estimator for the whole report: the latest STEP 7 snapshot's coverage
    when one was passed, otherwise the same estimate computed here from the KG
    and the run's retrieval files. ``tau`` and ``estimated_total_relevant``
    describe the saturation curve that passes through that estimate at the
    number of papers screened, so the chart agrees with the number.
    """
    from . import discovery_curve as dcurve

    points: List[Dict[str, Any]] = []
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        n = snap.get("n_evaluated") or snap.get("papers_evaluated") or 0
        y = snap.get("n_highly_relevant") or snap.get("highly_relevant_count") or 0
        points.append({"n": int(n), "y": int(y)})

    screened = len(papers)
    found = sum(1 for p in papers if (p.rcs or 0) >= dcurve.HIGHLY_RELEVANT_RCS)
    if not points and papers:
        points = [{"n": 0, "y": 0}, {"n": screened, "y": found}]

    # Only snapshots that say how they were estimated: older curve.json files
    # carry a 0.667 failure placeholder with no `method`, which is not an estimate.
    estimate = next(
        (
            s for s in reversed(snapshots)
            if isinstance(s, dict) and s.get("method") and s.get("coverage_estimate") is not None
        ),
        None,
    )
    if estimate is None:
        source = kg if kg is not None else {p.paper_id: p for p in papers}
        occasions = (
            dcurve.retrieval_occasions(raw_dir, source)
            if raw_dir is not None and Path(raw_dir).is_dir()
            else []
        )
        estimate = dcurve.make_snapshot(source, papers_evaluated=screened, occasions=occasions)

    coverage = max(0.0, min(1.0, float(estimate["coverage_estimate"])))
    ci_low = max(0.0, min(coverage, float(estimate.get("ci_lower", coverage))))
    ci_high = min(1.0, max(coverage, float(estimate.get("ci_upper", coverage))))

    total = found / coverage if coverage > 0 else float(found)
    if screened <= 0:
        tau = dcurve.UNDERMIND_MEDIAN_TAU
    elif coverage >= 0.999:
        tau = screened / 7.0
    elif coverage <= 0.0:
        tau = screened * 10.0
    else:
        tau = -screened / math.log(1.0 - coverage)

    summary = (
        f"Estimated to have found about {found} relevant papers, "
        f"approximately {coverage*100:.0f}% of the relevant set "
        f"(95% CI: {ci_low*100:.0f}-{ci_high*100:.0f}%)."
    )
    return {
        "points": points,
        "tau": round(tau, 2),
        "coverage_estimate": round(coverage, 3),
        "ci_low": round(ci_low, 3),
        "ci_high": round(ci_high, 3),
        "estimated_total_relevant": round(total, 1) if total else None,
        "method": estimate.get("method", "prior"),
        "summary": summary,
    }


def _build_citation_network(
    papers: List[UnifiedPaperEntity], max_nodes: int = 50
) -> Dict[str, Any]:
    """Force-directed graph nodes (top relevance) + edges derived from discovery_path."""
    sorted_papers = sorted(
        papers,
        key=lambda p: (-(p.rcs or 0), -(p.citation_count or 0)),
    )[:max_nodes]
    id_to_node: Dict[str, Dict[str, Any]] = {}
    for p in sorted_papers:
        node_id = p.paper_id
        id_to_node[node_id] = {
            "id": node_id,
            "title": p.title or "(untitled)",
            "authors_short": _authors_short(p),
            "year": p.year,
            "venue": p.venue,
            "rcs": p.rcs,
            "citation_count": p.citation_count or 0,
            "doi_url": p.doi_url or (f"https://doi.org/{p.doi}" if p.doi else None),
            "is_seed": (p.discovery_path or "").startswith("query:"),
        }

    edges: List[Dict[str, str]] = []
    seen_pairs: set = set()
    for p in sorted_papers:
        dp = p.discovery_path or ""
        # discovery_path examples: "ref of W12345", "cites W23456", "query: prospect theory"
        if dp.startswith("ref of ") or dp.startswith("cites "):
            target = dp.split(" ", 2)[-1].strip()
            # Only connect if target exists in graph
            if target in id_to_node and target != p.paper_id:
                key = tuple(sorted([p.paper_id, target]))
                if key not in seen_pairs:
                    edges.append({"source": p.paper_id, "target": target})
                    seen_pairs.add(key)

    return {
        "nodes": list(id_to_node.values()),
        "edges": edges,
        "node_count": len(id_to_node),
        "edge_count": len(edges),
    }


def _build_themes(papers: List[UnifiedPaperEntity]) -> Dict[str, Any]:
    """Frequency-based clustering of keywords/topics into theme buckets.

    No LLM call here — that keeps materialization deterministic and cheap. The
    write_report tool can optionally enrich this later via theme_extraction.
    """
    keyword_counts: Counter = Counter()
    keyword_to_papers: Dict[str, List[str]] = defaultdict(list)
    for p in papers:
        kw_sources: List[str] = []
        for kw in (p.keywords or []):
            if isinstance(kw, str):
                kw_sources.append(kw.lower().strip())
        for topic in (p.topics or []):
            if isinstance(topic, dict):
                name = topic.get("display_name") or topic.get("name")
                if name:
                    kw_sources.append(str(name).lower().strip())
        for kw in set(kw_sources):
            if not kw or len(kw) > 60:
                continue
            keyword_counts[kw] += 1
            keyword_to_papers[kw].append(p.paper_id)
    # Top 8 themes with at least 2 papers each
    top = [(k, c) for k, c in keyword_counts.most_common(20) if c >= 2][:8]
    themes = [
        {
            "name": kw.title(),
            "value": count,
            "paper_ids": keyword_to_papers[kw][:20],
        }
        for kw, count in top
    ]
    if not themes:
        themes = [
            {
                "name": "All papers",
                "value": len(papers),
                "paper_ids": [p.paper_id for p in papers[:20]],
            }
        ]
    return {"themes": themes, "total_papers": len(papers)}


# ---------- Paper rendering ----------

def _authors_short(p: UnifiedPaperEntity) -> str:
    if not p.authors:
        return ""
    names = [a.name for a in p.authors if a.name]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}, {names[1]}"
    if len(names) <= 4:
        return ", ".join(names[:-1]) + f", & {names[-1]}"
    return f"{names[0]} et al."


def _journal_metric_render(p: UnifiedPaperEntity) -> Optional[Dict[str, Any]]:
    """Additively serialise a paper's journal_metric for display (v2.2 Feature A).

    Returns None when the paper has no journal_metric OR the metric carries no
    real data — so the rendered output is byte-identical to the pre-3d behavior
    for every paper that lacks journal data (R-19). Never raises."""
    metric = getattr(p, "journal_metric", None)
    if metric is None:
        return None
    try:
        from .sjr_helper import metric_is_empty  # lazy: keeps imports lean

        if metric_is_empty(metric):
            return None
    except Exception:
        # If sjr_helper is unavailable for any reason, fall back to a direct
        # emptiness check so display still degrades gracefully.
        if (
            not getattr(metric, "sjr_quartile", None)
            and not getattr(metric, "sjr_category_quartiles", None)
            and getattr(metric, "openalex_2yr_mean_citedness", None) is None
            and getattr(metric, "h_index", None) is None
        ):
            return None
    return {
        "sjr_quartile": metric.sjr_quartile,
        "sjr_category_quartiles": dict(metric.sjr_category_quartiles or {}),
        "openalex_2yr_mean_citedness": metric.openalex_2yr_mean_citedness,
        "h_index": metric.h_index,
        "cwts_snip": metric.cwts_snip,
        "sjr_attribution": metric.sjr_attribution,
    }


def _journal_rank_render(p: UnifiedPaperEntity) -> Optional[Dict[str, Any]]:
    """Additively serialise a paper's multi-platform ``journal_rank`` for display
    (v2.2 Feature A, Wave A-3).

    This is the *new* three-platform record (CAS 区 / JCR Q·IF / SJR Q) populated
    by ``rank_filter.annotate_papers`` from ``journal_rank.py`` data. It is wholly
    independent of the older SJR-only ``journal_metric`` above — both slots render
    side by side, neither clobbers the other.

    Returns None when the paper has no ``journal_rank`` OR it carries no real
    platform data — so the rendered output is byte-identical to the pre-A-3
    behavior for every paper that lacks rank data (R-19). Never raises. The
    serialisation goes through ``rank_filter.rank_metric_dict``, the single SSOT
    for the spec §3 schema, so R-04 naming (only JCR has an ``impact_factor``) is
    enforced in exactly one place and the display can never drift from agent mode."""
    rank = getattr(p, "journal_rank", None)
    if rank is None:
        return None
    try:
        from .rank_filter import rank_metric_dict  # lazy: keeps imports lean

        return rank_metric_dict(rank)
    except Exception:
        # If rank_filter is unavailable for any reason, degrade to no rank line
        # (display still succeeds; R-19 byte-identical fallback to "no rank data").
        return None


def _rank_attribution_for(metric: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best per-paper attribution string for a rendered journal_rank dict.

    Picks the attribution of whichever platforms actually carry data, joined so
    every surfaced source is credited (R-01..05). Returns None when the dict is
    empty or attribution constants cannot be loaded. Never raises."""
    if not metric:
        return None
    try:
        from .journal_rank import ATTRIBUTION  # lazy
    except Exception:
        return None
    present = [plat for plat in ("cas", "jcr", "sjr") if metric.get(plat)]
    parts = [ATTRIBUTION[plat] for plat in present if plat in ATTRIBUTION]
    return "  ".join(parts) if parts else None


def _render_paper(p: UnifiedPaperEntity) -> Dict[str, Any]:
    rendered: Dict[str, Any] = {
        "paper_id": p.paper_id,
        "title": p.title or "(untitled)",
        "authors_short": _authors_short(p),
        "authors_full": [a.name for a in p.authors] if p.authors else [],
        "year": p.year,
        "venue": p.venue,
        "doi": p.doi,
        "doi_url": p.doi_url or (f"https://doi.org/{p.doi}" if p.doi else None),
        "abstract": p.abstract,
        "tldr": p.tldr,
        "rcs": p.rcs,
        "rcs_reasoning": p.rcs_reasoning,
        "rcs_flag": p.rcs_flag,
        "citation_count": p.citation_count or 0,
        "influential_citation_count": p.influential_citation_count,
        "discovery_path": p.discovery_path,
        "sources": p.sources,
        "is_oa": p.is_oa,
    }
    # Additive (R-19): only emit the key when real journal data exists, so a run
    # without journal enrichment produces a paper_list byte-identical to before.
    jm = _journal_metric_render(p)
    if jm is not None:
        rendered["journal_metric"] = jm
    # Additive (R-19): the new multi-platform journal_rank renders the SAME way —
    # the key only appears when CAS/JCR/SJR data was actually joined onto this
    # paper. A run that never annotated ranks (no cached CSVs) yields a paper_list
    # byte-identical to the pre-A-3 output, exactly like journal_metric above.
    jr = _journal_rank_render(p)
    if jr is not None:
        rendered["journal_rank"] = jr
        attr = _rank_attribution_for(jr)
        if attr:
            rendered["journal_rank_attribution"] = attr
    return rendered


def _sorted_for_display(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """Display order: highly relevant first, then by citation count."""
    return sorted(papers, key=lambda p: (-(p.rcs or 0), -(p.citation_count or 0), p.year or 0))


# ---------- Metadata ----------

def _build_metadata(
    *,
    kg: Dict[str, UnifiedPaperEntity],
    classified: List[UnifiedPaperEntity],
    discovery_curve: Dict[str, Any],
    user_query: str,
    search_topic: str,
    display_title: str,
    language: Optional[str],
    tier: str,
    search_id: str,
    wall_clock_seconds: Optional[float],
    stop_reason: Optional[str],
) -> Dict[str, Any]:
    highly_relevant = sum(1 for p in classified if (p.rcs or 0) >= 7)
    closely_related = sum(1 for p in classified if (p.rcs or 0) in (5, 6))
    # P0-7 fix: use explicit None check so a real 0.0 still renders 0.0 and a
    # genuine resolved value (e.g. mtime fallback) survives.
    wall_clock = (
        round(float(wall_clock_seconds), 1)
        if wall_clock_seconds is not None
        else 0.0
    )
    identity = build_report_identity(
        original_user_query=user_query,
        search_topic=search_topic,
        display_title=display_title,
        language=language,
    )
    warn_about_title(identity)
    return {
        "search_id": search_id,
        **identity,
        "tier": tier,
        "wall_clock_total_s": wall_clock,
        "papers_evaluated": len(classified),
        "papers_in_kg": len(kg),
        "highly_relevant_count": highly_relevant,
        "closely_related_count": closely_related,
        "coverage_estimate": discovery_curve.get("coverage_estimate"),
        "coverage_ci": [
            discovery_curve.get("ci_low"),
            discovery_curve.get("ci_high"),
        ],
        "coverage_method": discovery_curve.get("method"),
        "generated_at": datetime.now().isoformat(),
        "skill_version": "paper-search-pro/2.5.0",
        "stop_reason": stop_reason,
    }


# ---------- CLI ----------

def _journal_metric_from_json(d: Dict):
    """Reconstruct a JournalMetric from a kg.json paper dict (additive).

    Returns None when absent (the common case), so a kg.json written before
    Feature A decodes identically. Never raises."""
    raw = d.get("journal_metric")
    if not isinstance(raw, dict):
        return None
    from .types import JournalMetric

    return JournalMetric(
        sjr_quartile=raw.get("sjr_quartile"),
        sjr_category_quartiles=dict(raw.get("sjr_category_quartiles") or {}),
        openalex_2yr_mean_citedness=raw.get("openalex_2yr_mean_citedness"),
        h_index=raw.get("h_index"),
        cwts_snip=raw.get("cwts_snip"),
        sjr_attribution=raw.get("sjr_attribution"),
        issn_backfill_needed=bool(raw.get("issn_backfill_needed", False)),
    )


def _journal_rank_from_json(d: Dict):
    """Reconstruct a JournalRank from a kg.json paper dict (additive, A-3).

    Accepts the unified three-platform ``journal_rank`` dict (spec §3 shape, as
    written by agent mode / annotate). Returns None when absent (the common case)
    so a kg.json written before Feature A — or one without cached rank data —
    decodes byte-identically (R-19). Never raises."""
    raw = d.get("journal_rank")
    if not isinstance(raw, dict):
        return None
    try:
        from .types import CASRank, JCRRank, JournalRank, SJRRank
    except Exception:
        return None
    cas = raw.get("cas")
    jcr = raw.get("jcr")
    sjr = raw.get("sjr")
    oa = raw.get("openalex")
    return JournalRank(
        title=raw.get("title"),
        issns=list(raw.get("issns") or []),
        openalex=dict(oa) if isinstance(oa, dict) else None,
        cas=CASRank(
            tier=cas.get("tier"),
            rank=cas.get("rank"),
            top=bool(cas.get("top", False)),
            minor=[dict(m) for m in (cas.get("minor") or [])],
            source_year=cas.get("source_year"),
        ) if isinstance(cas, dict) else None,
        jcr=JCRRank(
            quartile=jcr.get("quartile"),
            impact_factor=jcr.get("impact_factor"),
            rank=jcr.get("rank"),
            category=jcr.get("category"),
            source_year=jcr.get("source_year"),
        ) if isinstance(jcr, dict) else None,
        sjr=SJRRank(
            best_quartile=sjr.get("best_quartile"),
            sjr=sjr.get("sjr"),
            per_category=[dict(c) for c in (sjr.get("per_category") or [])],
            source_year=sjr.get("source_year"),
        ) if isinstance(sjr, dict) else None,
        matched_issn=raw.get("matched_issn"),
        matched_platforms=list(raw.get("matched_platforms") or []),
    )


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
            source_native_id=d.get("source_native_id"),  # 0.2 (None when absent)
            title=d.get("title", "") or "",
            abstract=d.get("abstract"),
            authors=authors,
            year=d.get("year"),
            venue=d.get("venue"),
            issn=d.get("issn"),
            type=d.get("type"),
            citation_count=int(d.get("citation_count") or 0),
            fwci=d.get("fwci"),
            topics=list(d.get("topics") or []),
            keywords=list(d.get("keywords") or []),
            influential_citation_count=d.get("influential_citation_count"),
            tldr=d.get("tldr"),
            doi_url=d.get("doi_url"),
            journal_metric=_journal_metric_from_json(d),
            journal_rank=_journal_rank_from_json(d),
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
            "Materialize a classified KG into report_data.json + sibling "
            "chart_data.json / paper_list.json / metadata.json / prisma_log.json."
        )
    )
    parser.add_argument(
        "--kg",
        required=True,
        type=Path,
        help="Path to kg_classified.json.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        help="Path to the executive summary markdown (written by main agent).",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Original user request, preserved verbatim for audit (never the H1).",
    )
    parser.add_argument(
        "--search-topic",
        default="",
        help="Normalized semantic retrieval topic without operational instructions or filters.",
    )
    parser.add_argument(
        "--display-title",
        default="",
        help="Scholarly report title. Blank uses a safe localized generic title.",
    )
    parser.add_argument(
        "--language",
        choices=("en", "zh"),
        default=None,
        help="Report UI/title fallback language. Defaults to deterministic query-language detection.",
    )
    parser.add_argument(
        "--tier",
        default="standard",
        help="Tier name (quick/standard/deep/audit).",
    )
    parser.add_argument(
        "--search-id",
        default="",
        help="Optional search ID.",
    )
    parser.add_argument(
        "--snapshots",
        type=Path,
        help="Optional path to discovery_curve_snapshots.json.",
    )
    parser.add_argument(
        "--wall-clock-seconds",
        type=float,
        help="Optional wall-clock elapsed time (seconds). Highest priority.",
    )
    parser.add_argument(
        "--started-at",
        default=None,
        help=(
            "Optional ISO timestamp recording when the main agent's STEP 1 "
            "began. Used to compute wall_clock when --wall-clock-seconds is "
            "absent (P0-7)."
        ),
    )
    parser.add_argument(
        "--search-strategies",
        type=Path,
        default=None,
        help=(
            "Optional path to a v2.4 STEP 11.5 search_strategies.json. Folded "
            "verbatim into report_data.json under a new top-level "
            "'search_strategies' key (additive; R-19). Defaults to auto-discovering "
            "<output_dir>/search_strategies.json when present."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to report_data.json (its parent directory receives the sibling files).",
    )
    args = parser.parse_args()

    if not args.kg.exists():
        sys.exit(f"data_materialization: KG not found at {args.kg}")

    kg = _kg_from_json(json.loads(args.kg.read_text(encoding="utf-8")))
    if not kg:
        sys.exit(f"data_materialization: empty KG loaded from {args.kg}")

    summary_text = ""
    if args.summary and args.summary.exists():
        summary_text = args.summary.read_text(encoding="utf-8")

    snapshots: List[Dict] = []
    if args.snapshots and args.snapshots.exists():
        loaded = json.loads(args.snapshots.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            snapshots = [loaded]
        elif isinstance(loaded, list):
            snapshots = [s for s in loaded if isinstance(s, dict)]

    output_dir = args.output.parent
    artifacts = materialize(
        kg,
        output_dir,
        user_query=args.query,
        search_topic=args.search_topic,
        display_title=args.display_title,
        language=args.language,
        tier=args.tier,
        search_id=args.search_id,
        summary=summary_text,
        discovery_curve_snapshots=snapshots,
        wall_clock_seconds=args.wall_clock_seconds,
        started_at=args.started_at,
        # P0-7 graceful fallback: when neither --wall-clock-seconds nor
        # --started-at is passed, fall back to kg.json mtime so metadata
        # carries a non-zero (approximate) wall_clock.
        kg_source_path=args.kg,
        search_strategies_path=args.search_strategies,
    )
    # If --output names a file other than report_data.json, point it there.
    if args.output.name != "report_data.json":
        args.output.write_text(
            artifacts["report_data"].read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    for name, path in artifacts.items():
        print(f"data_materialization: {name} -> {path}")
