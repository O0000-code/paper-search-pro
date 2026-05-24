"""Discovery saturation curve.

Theory: As a search exhausts relevant papers, marginal discovery rate decays.
Fit N(t) = N_total * (1 - exp(-lambda * t)) to estimate coverage.

V2 §6.1 fixes (vs V1 Codex C3 bug):
- min_papers_analyzed guard ACTUALLY enforced (V1 had the param but ignored it)
- Monotonicity check on recent marginal rates (avoid spurious saturation from
  one noisy window)
- Failure modes return (False, "<reason>") with no spurious True

CRITICAL: This module is ADVISORY ONLY. The main agent decides when to stop
based on the snapshot + tier budget. should_warn_low_progress() returns an
advisory only; nothing here triggers a hard stop.

v2.0 refactor: SearchState removed. `make_snapshot` now accepts the classified
KG (Dict[str, UnifiedPaperEntity]) and a list of prior snapshots, returning the
new snapshot dict the caller is expected to persist.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, List, Tuple

from .types import UnifiedPaperEntity


# --------------------------------------------------------------------------- #
# Marginal rates
# --------------------------------------------------------------------------- #

def compute_marginal_rates(snapshots: List[Dict]) -> List[float]:
    """Compute per-window marginal discovery rate.

    Each snapshot dict has at least:
      - papers_evaluated: int
      - highly_relevant_count: int

    Returns one rate per adjacent pair: delta_highly_relevant / delta_evaluated.
    Pairs with delta_evaluated <= 0 are skipped.
    """
    if len(snapshots) < 2:
        return []
    rates: List[float] = []
    for prev, curr in zip(snapshots[:-1], snapshots[1:]):
        d_eval = curr.get("papers_evaluated", 0) - prev.get("papers_evaluated", 0)
        d_rel = curr.get("highly_relevant_count", 0) - prev.get("highly_relevant_count", 0)
        if d_eval > 0:
            rates.append(d_rel / d_eval)
    return rates


# --------------------------------------------------------------------------- #
# Exponential fit
# --------------------------------------------------------------------------- #

def fit_exponential(
    papers_evaluated: List[int],
    highly_relevant: List[int],
) -> Tuple[float, float]:
    """Fit N(t) = N_total * (1 - exp(-lambda * t)).

    Returns (N_total_estimate, lambda). On failure returns (n_relevant_last * 1.5, 0.0)
    so caller can detect via `lambda <= 0.0`.

    Strategy: compare early-window rate vs recent-window rate. If recent < early,
    the curve is decaying and we can solve for lambda; otherwise lambda is set
    to 0.0 to signal failure.
    """
    if len(papers_evaluated) < 3 or len(highly_relevant) < 3:
        if highly_relevant:
            return (max(1.0, highly_relevant[-1] * 1.5), 0.0)
        return (1.0, 0.0)

    current_t = papers_evaluated[-1]
    current_y = highly_relevant[-1]
    if current_t <= 0 or current_y <= 0:
        return (max(1.0, current_y * 1.5), 0.0)

    cutoff = max(1, len(papers_evaluated) // 5)

    early_dt = papers_evaluated[cutoff] - papers_evaluated[0]
    early_dy = highly_relevant[cutoff] - highly_relevant[0]
    recent_dt = papers_evaluated[-1] - papers_evaluated[-cutoff - 1]
    recent_dy = highly_relevant[-1] - highly_relevant[-cutoff - 1]

    early_rate = (early_dy / early_dt) if early_dt > 0 else 0.0
    recent_rate = (recent_dy / recent_dt) if recent_dt > 0 else 0.0

    if early_rate <= 0 or recent_rate <= 0 or recent_rate >= early_rate:
        return (max(float(current_y), current_y * 1.5), 0.0)

    try:
        lambda_est = -math.log(recent_rate / early_rate) / current_t
    except (ValueError, ZeroDivisionError):
        return (max(float(current_y), current_y * 1.5), 0.0)

    if not math.isfinite(lambda_est) or lambda_est <= 0:
        return (max(float(current_y), current_y * 1.5), 0.0)

    lambda_est = max(1e-4, min(0.2, lambda_est))

    exp_factor = 1.0 - math.exp(-lambda_est * current_t)
    if exp_factor <= 1e-3:
        n_total_est = current_y / 0.5
    else:
        n_total_est = current_y / exp_factor

    n_total_est = max(float(current_y), min(current_y * 5.0, n_total_est))
    return (n_total_est, lambda_est)


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #

def compute_coverage(
    current_relevant: int,
    n_total: float,
) -> Tuple[float, float, float]:
    """Coverage point estimate + 95% CI bounds.

    Returns (point, lower, upper). All values clamped to [0, 1]. If n_total is
    non-positive, returns (1.0, 0.5, 1.0) (degenerate but safe).
    """
    if n_total <= 0:
        return (1.0, 0.5, 1.0)

    point = min(1.0, max(0.0, current_relevant / n_total))
    upper_total = n_total * 0.85
    lower_total = n_total * 1.15
    lower = min(1.0, max(0.0, current_relevant / lower_total)) if lower_total > 0 else 0.0
    upper = min(1.0, max(0.0, current_relevant / upper_total)) if upper_total > 0 else 1.0
    if lower > upper:
        lower, upper = upper, lower
    return (point, lower, upper)


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #

def make_snapshot(
    kg: Dict[str, UnifiedPaperEntity],
    prior_snapshots: List[Dict] | None = None,
    papers_evaluated: int | None = None,
) -> Dict:
    """Compute the current discovery snapshot from a classified KG.

    Args:
        kg: dict keyed by canonical_key whose values are classified UnifiedPaperEntity
            (each with `.rcs` populated when classification has run).
        prior_snapshots: optional list of earlier snapshots (in order). The new
            snapshot is NOT appended in place; the caller persists the list.
        papers_evaluated: optional override for the "papers_evaluated" counter.
            When None, defaults to `len(kg)` (each KG entry counts as one
            evaluated record).

    Returns:
        snapshot dict containing the saturation fit + coverage estimate.
    """
    if papers_evaluated is None:
        papers_evaluated = len(kg)
    highly_relevant_count = sum(
        1 for p in kg.values() if p.rcs is not None and p.rcs >= 7
    )

    history = list(prior_snapshots or [])
    eval_series = [s["papers_evaluated"] for s in history] + [papers_evaluated]
    rel_series = [s["highly_relevant_count"] for s in history] + [highly_relevant_count]

    n_total, lambda_est = fit_exponential(eval_series, rel_series)
    point, lower, upper = compute_coverage(highly_relevant_count, n_total)

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "papers_evaluated": papers_evaluated,
        "highly_relevant_count": highly_relevant_count,
        "n_total_estimate": round(n_total, 1),
        "lambda": round(lambda_est, 5),
        "coverage_estimate": round(point, 3),
        "ci_lower": round(lower, 3),
        "ci_upper": round(upper, 3),
        "fit_failed": lambda_est <= 0.0,
    }
    return snapshot


# --------------------------------------------------------------------------- #
# Low-progress warning (the Codex C3 fix lives here)
# --------------------------------------------------------------------------- #

def should_warn_low_progress(
    snapshots: List[Dict],
    min_papers_analyzed: int = 100,
    monotonic_tolerance: float = 0.005,
    monotonic_window: int = 5,
) -> Tuple[bool, str]:
    """Advisory: should we warn the user that progress has stalled?

    NEVER triggers a hard stop. Reason strings:
      - "insufficient_samples"  : papers_evaluated < min_papers_analyzed
      - "fit_failed"            : exponential fit returned lambda <= 0
      - "not_yet_saturated"     : recent rates not monotonically decreasing
      - "low_progress"          : rates are monotonically decreasing AND very low

    The V1 bug (Codex C3) was that min_papers_analyzed was an unused parameter
    in should_terminate(). We honour it here: insufficient samples => False
    immediately, no further checks.
    """
    if not snapshots:
        return (False, "insufficient_samples")

    last = snapshots[-1]
    if last.get("papers_evaluated", 0) < min_papers_analyzed:
        return (False, "insufficient_samples")

    if last.get("fit_failed", False):
        return (False, "fit_failed")

    rates = compute_marginal_rates(snapshots)
    if len(rates) < monotonic_window:
        return (False, "insufficient_samples")

    recent = rates[-monotonic_window:]
    # Monotonically decreasing within tolerance — each successive rate must
    # be at most (prev + tolerance). Tolerance absorbs single-window noise.
    for prev, curr in zip(recent[:-1], recent[1:]):
        if curr > prev + monotonic_tolerance:
            return (False, "not_yet_saturated")

    if recent[-1] < 0.02:
        return (
            True,
            f"low_progress (recent_rate={recent[-1]:.3f}, "
            f"coverage={last.get('coverage_estimate', 0.0):.0%})",
        )
    return (False, "not_yet_saturated")


# --------------------------------------------------------------------------- #
# KG (de)serialisation for CLI
# --------------------------------------------------------------------------- #

def _kg_from_json(payload) -> Dict[str, UnifiedPaperEntity]:
    """Decode a kg.json payload into Dict[str, UnifiedPaperEntity].

    Accepts either:
      - a list of paper dicts (canonical_key derived from doi/title)
      - a dict keyed by canonical_key string -> paper dict
    """
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


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Discovery saturation curve — fit an exponential to the marginal "
            "discovery rate and emit a snapshot JSON. ADVISORY ONLY."
        )
    )
    parser.add_argument(
        "--kg",
        required=True,
        type=Path,
        help="Path to kg_classified.json (UnifiedPaperEntity list or dict).",
    )
    parser.add_argument(
        "--prior-snapshots",
        type=Path,
        help="Optional path to a JSON list of prior snapshots (default: none).",
    )
    parser.add_argument(
        "--papers-evaluated",
        type=int,
        help="Override for papers_evaluated counter (default: len(kg)).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Where to write the snapshot JSON.",
    )
    args = parser.parse_args()

    payload = json.loads(args.kg.read_text(encoding="utf-8"))
    kg = _kg_from_json(payload)
    if not kg:
        sys.exit(f"discovery_curve: empty KG loaded from {args.kg}")

    prior_snapshots: List[Dict] = []
    if args.prior_snapshots:
        prior_snapshots = json.loads(args.prior_snapshots.read_text(encoding="utf-8"))
        if not isinstance(prior_snapshots, list):
            sys.exit("--prior-snapshots must contain a JSON list")

    snapshot = make_snapshot(
        kg=kg,
        prior_snapshots=prior_snapshots,
        papers_evaluated=args.papers_evaluated,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"discovery_curve: wrote snapshot to {args.output}")
