"""Discovery saturation curve.

Theory: As a search exhausts relevant papers, marginal discovery rate decays.
The coverage estimate is the sample coverage of the run's retrieval files
(see "Coverage estimate" below); the Undermind prior is the labelled fallback.

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

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
# Coverage estimate
# --------------------------------------------------------------------------- #
#
# The report needs a number every run, and it must depend on what was found.
# Fitting N(t) = N_total * (1 - exp(-lambda * t)) needs an ordered discovery
# trajectory, which this recipe does not produce: STEP 7 runs once and the
# retrieval files are complementary strategies, not a best-first sequence.
#
# What every run does produce is several retrieval files (search strategies,
# reviews, seminal, Chinese sources, citation expansion). Treating each file
# as one sampling occasion gives incidence data, and the Good-Turing / Chao &
# Jost (2012) *sample coverage* of that data is the order-free form of the
# curve's final slope: 1 - coverage is the chance that the next relevant paper
# a further search turns up is one we do not have yet. It needs no fit and
# cannot fail once there are two occasions and one relevant detection. With
# less than that there is no evidence to use, and the Undermind prior (median
# tau = 80 across queries, whitepaper s3.1) stands in, labelled as such.

HIGHLY_RELEVANT_RCS = 7
UNDERMIND_MEDIAN_TAU = 80.0


def _id_keys(paper: UnifiedPaperEntity) -> List[str]:
    """Every identifier a record carries, so a paper found under a bare title in
    one file still matches its DOI-bearing KG entry."""
    from .federated_kg_resolver import normalize_arxiv_id, normalize_doi, normalize_title

    keys: List[str] = []
    doi = normalize_doi(paper.doi)
    if doi:
        keys.append(f"doi|{doi}")
    arxiv = normalize_arxiv_id(paper.arxiv_id)
    if arxiv:
        keys.append(f"arxiv|{arxiv}")
    if paper.pmid:
        keys.append(f"pmid|{paper.pmid}")
    if paper.openalex_id:
        keys.append("openalex|" + paper.openalex_id.replace("https://openalex.org/", ""))
    if paper.ss_paper_id:
        keys.append(f"ss|{paper.ss_paper_id}")
    if paper.source_native_id:
        keys.append(f"native|{paper.source_native_id}")
    title = normalize_title(paper.title)
    if title and paper.year:
        keys.append(f"title|{title}|{paper.year}")
    return keys


def retrieval_occasions(
    raw_dir: Path, kg: Dict[str, UnifiedPaperEntity]
) -> List[Set[str]]:
    """One set of KG keys per retrieval file in ``raw_dir``, oldest first.

    Papers are matched to the KG through any shared identifier. A file whose
    papers were all seen in earlier files is skipped: it is a subset or merge
    the agent derived from them, not a new search. Counting such a file would
    re-detect papers for free and inflate coverage; the cost of the rule is that
    a genuine search finding nothing new is skipped too, which errs low.
    Unreadable files are skipped.
    """
    from .federated_kg_resolver import _papers_from_payload

    index: Dict[str, str] = {}
    for key, paper in kg.items():
        for k in _id_keys(paper):
            index.setdefault(k, key)

    occasions: List[Set[str]] = []
    seen: Set[str] = set()
    # Oldest first, and on a timestamp tie the larger file first, so a subset
    # the agent carved out of a search never displaces the search itself.
    files = sorted(
        Path(raw_dir).glob("*.json"),
        key=lambda f: (f.stat().st_mtime, -f.stat().st_size, f.name),
    )
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        members: Set[str] = set()
        for paper in _papers_from_payload(payload):
            ks = _id_keys(paper)
            if not ks:
                continue
            members.add(next((index[k] for k in ks if k in index), ks[0]))
        if not members or members <= seen:
            continue
        occasions.append(members)
        seen |= members
    return occasions


def _wilson(p: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion observed over n detections."""
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def sample_coverage(
    occasions: List[Set[str]], relevant: Set[str]
) -> Optional[Dict]:
    """Chao & Jost (2012) incidence-based sample coverage of ``relevant`` papers.

    Returns None when there is no evidence: fewer than two occasions, or no
    relevant paper found in any of them.
    """
    m = len(occasions)
    counts: Dict[str, int] = {}
    for occ in occasions:
        for key in occ & relevant:
            counts[key] = counts.get(key, 0) + 1
    detections = sum(counts.values())
    if m < 2 or detections == 0:
        return None
    q1 = sum(1 for c in counts.values() if c == 1)
    q2 = sum(1 for c in counts.values() if c == 2)
    if q2 > 0:
        share = (m - 1) * q1 / ((m - 1) * q1 + 2 * q2)
    elif q1 > 1:
        share = (m - 1) * (q1 - 1) / ((m - 1) * (q1 - 1) + 2)
    else:
        share = 0.0
    coverage = min(1.0, max(0.0, 1.0 - (q1 / detections) * share))
    lower, upper = _wilson(coverage, detections)
    return {
        "coverage": coverage,
        "lower": min(lower, coverage),
        "upper": max(upper, coverage),
        "occasions": m,
        "detections": detections,
    }


def prior_coverage(papers_evaluated: int) -> Tuple[float, float, float]:
    """Undermind prior 1 - exp(-n/tau), tau = 80, with tau in [40, 160] as the band."""
    n = max(0, papers_evaluated)
    return (
        1.0 - math.exp(-n / UNDERMIND_MEDIAN_TAU),
        1.0 - math.exp(-n / (2 * UNDERMIND_MEDIAN_TAU)),
        1.0 - math.exp(-n / (UNDERMIND_MEDIAN_TAU / 2)),
    )


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #

def make_snapshot(
    kg: Dict[str, UnifiedPaperEntity],
    prior_snapshots: List[Dict] | None = None,
    papers_evaluated: int | None = None,
    occasions: List[Set[str]] | None = None,
) -> Dict:
    """Compute the current discovery snapshot from a classified KG.

    Args:
        kg: dict keyed by canonical_key whose values are classified UnifiedPaperEntity
            (each with `.rcs` populated when classification has run).
        prior_snapshots: optional list of earlier snapshots (in order). Kept for
            the low-progress warning; the coverage estimate does not need them.
        papers_evaluated: optional override for the "papers_evaluated" counter.
            When None, defaults to `len(kg)` (each KG entry counts as one
            evaluated record).
        occasions: retrieval occasions from `retrieval_occasions()`. Without
            them (or with too little evidence) the prior is used.

    Returns:
        snapshot dict with the coverage estimate and how it was obtained
        (`method`: "sample_coverage" or "prior").
    """
    if papers_evaluated is None:
        papers_evaluated = len(kg)
    relevant = {
        key for key, p in kg.items() if p.rcs is not None and p.rcs >= HIGHLY_RELEVANT_RCS
    }
    highly_relevant_count = len(relevant)

    estimate = sample_coverage(occasions, relevant) if occasions else None
    if estimate:
        point, lower, upper = estimate["coverage"], estimate["lower"], estimate["upper"]
        method = "sample_coverage"
    else:
        point, lower, upper = prior_coverage(papers_evaluated)
        method = "prior"

    n_total = highly_relevant_count / point if point > 0 else float(highly_relevant_count)
    # Rate of the saturation curve through (papers_evaluated, point), for plotting.
    if 0 < point < 1 and papers_evaluated > 0:
        lambda_est = -math.log(1 - point) / papers_evaluated
    else:
        lambda_est = 1 / UNDERMIND_MEDIAN_TAU

    return {
        "timestamp": datetime.now().isoformat(),
        "papers_evaluated": papers_evaluated,
        "highly_relevant_count": highly_relevant_count,
        "n_total_estimate": round(n_total, 1),
        "lambda": round(lambda_est, 5),
        "coverage_estimate": round(point, 3),
        "ci_lower": round(lower, 3),
        "ci_upper": round(upper, 3),
        "method": method,
        "occasions": estimate["occasions"] if estimate else len(occasions or []),
        "fit_failed": method == "prior",
    }


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


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Discovery saturation snapshot — estimate how much of the relevant "
            "literature this run has found and emit a snapshot JSON. ADVISORY ONLY."
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
        help="Optional earlier snapshot(s): a previous curve.json or a JSON list of them.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        help=(
            "Directory of this run's retrieval files (default: raw/ next to --kg). "
            "Each file is one search; the coverage estimate is computed from them."
        ),
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
        if isinstance(prior_snapshots, dict):
            prior_snapshots = [prior_snapshots]
        if not isinstance(prior_snapshots, list):
            sys.exit("--prior-snapshots must contain a snapshot or a JSON list of them")

    raw_dir = args.raw_dir or args.kg.parent / "raw"
    occasions = retrieval_occasions(raw_dir, kg) if raw_dir.is_dir() else []

    snapshot = make_snapshot(
        kg=kg,
        prior_snapshots=prior_snapshots,
        papers_evaluated=args.papers_evaluated,
        occasions=occasions,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"discovery_curve: coverage {snapshot['coverage_estimate']:.0%} "
        f"({snapshot['method']}, {snapshot['occasions']} retrieval files) -> {args.output}"
    )
