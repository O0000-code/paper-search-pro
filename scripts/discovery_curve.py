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
# a further search turns up is one we do not have yet. It needs no fit.
#
# It can still say nothing. The estimate is exactly 1 when no relevant paper was
# found by only one search, or when one was and none by exactly two (Q1 = 0, or
# Q1 = 1 and Q2 = 0): with no singletons to go on, the bias-corrected estimator
# puts the unseen count at zero. That reads as "found everything" but means "too
# few papers to tell", and it happens when the rcs >= 7 set is a handful of
# papers (two, found by 3 and 1 of 8 searches -> 100%, and STEP 8 stopped the
# search). Then the estimate is taken over rcs >= 6, which rcs_rubric.md still
# calls highly relevant (7 adds "> 100 citations or landmark", which few recent
# papers reach; citation_chasing.md drops to 6 for the same reason). Central
# papers are re-found more often than the rest, so the wider band errs low.
#
# With no usable estimate (fewer than two occasions, no relevant detection, or
# both bands saying nothing) the Undermind prior (median tau = 80 across
# queries, whitepaper s3.1) stands in, labelled as such and capped at 50% with
# no lower bound: the prior depends only on how many papers were screened, and
# no evidence must never read as high coverage (it would stop the search and
# tell the user the set is near-exhaustive).

HIGHLY_RELEVANT_RCS = 7
RELEVANCE_BANDS = (HIGHLY_RELEVANT_RCS, 6)
NO_EVIDENCE_CEILING = 0.5
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

    owners: Dict[str, Set[str]] = {}
    for key, paper in kg.items():
        for k in _id_keys(paper):
            owners.setdefault(k, set()).add(key)
    # An identifier shared by two KG papers (two "Editorial" titles in one year)
    # cannot say which one a raw record is; only unambiguous ones are used.
    index = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}

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


def _coverage_from_counts(freqs: List[int], m: int) -> Optional[float]:
    """Chao & Jost (2012) incidence sample coverage from per-paper detection
    counts (how many of the m occasions found each paper)."""
    detections = sum(freqs)
    if m < 2 or detections == 0:
        return None
    q1 = freqs.count(1)
    q2 = freqs.count(2)
    if q2 > 0:
        share = (m - 1) * q1 / ((m - 1) * q1 + 2 * q2)
    elif q1 > 1:
        share = (m - 1) * (q1 - 1) / ((m - 1) * (q1 - 1) + 2)
    else:
        share = 0.0
    return min(1.0, max(0.0, 1.0 - (q1 / detections) * share))


def _bootstrap_interval(
    freqs: List[int], m: int, coverage: float, reps: int = 200
) -> Tuple[float, float]:
    """95% interval by the Chao & Jost (2012) bootstrap, simplified: rebuild an
    assemblage from the observed detection counts (each paper found in a given
    occasion with probability count/m) plus the Chao2-estimated undetected
    papers sharing the missing coverage, draw m occasions from it ``reps`` times
    (fixed seed, so the report is reproducible) and take coverage +/- 1.96 SD."""
    import random
    import statistics

    q1 = freqs.count(1)
    q2 = freqs.count(2)
    k = (m - 1) / m
    unseen = k * q1 * q1 / (2 * q2) if q2 > 0 else k * q1 * (q1 - 1) / 2
    probs = [f / m for f in freqs]
    n0 = int(math.ceil(unseen))
    if n0 > 0:
        missing_per_occasion = (sum(freqs) / m) * (1.0 - coverage)
        probs += [min(1.0, missing_per_occasion / n0)] * n0

    rng = random.Random(0)
    values: List[float] = []
    for _ in range(reps):
        drawn = [sum(1 for _ in range(m) if rng.random() < p) for p in probs]
        value = _coverage_from_counts([d for d in drawn if d], m)
        if value is not None:
            values.append(value)
    spread = 1.96 * statistics.pstdev(values) if len(values) > 1 else 0.0
    return (max(0.0, coverage - spread), min(1.0, coverage + spread))


def sample_coverage(
    occasions: List[Set[str]], relevant: Set[str]
) -> Optional[Dict]:
    """Chao & Jost (2012) incidence-based sample coverage of ``relevant`` papers.

    Returns None when there is no evidence: fewer than two occasions, or no
    relevant paper found in any of them. ``informative`` is False when the
    counts leave the estimator nothing to go on (Q1 = 0, or Q1 = 1 and Q2 = 0);
    the coverage is then exactly 1 and must not be reported as a measurement.
    """
    m = len(occasions)
    counts: Dict[str, int] = {}
    for occ in occasions:
        for key in occ & relevant:
            counts[key] = counts.get(key, 0) + 1
    # Sorted: set order varies with the per-process string hash seed, and the
    # bootstrap draws follow this order, so the interval would too.
    freqs = sorted(counts.values())
    coverage = _coverage_from_counts(freqs, m)
    if coverage is None:
        return None
    lower, upper = _bootstrap_interval(freqs, m, coverage)
    q1, q2 = freqs.count(1), freqs.count(2)
    return {
        "coverage": coverage,
        "lower": lower,
        "upper": upper,
        "occasions": m,
        "detections": sum(freqs),
        "informative": q1 > 1 or (q1 == 1 and q2 > 0),
    }


def prior_coverage(papers_evaluated: int) -> Tuple[float, float, float]:
    """Undermind prior 1 - exp(-n/tau), tau = 80, with tau in [40, 160] as the band."""
    n = max(0, papers_evaluated)
    return (
        1.0 - math.exp(-n / UNDERMIND_MEDIAN_TAU),
        1.0 - math.exp(-n / (2 * UNDERMIND_MEDIAN_TAU)),
        1.0 - math.exp(-n / (UNDERMIND_MEDIAN_TAU / 2)),
    )


def no_evidence_coverage(papers_evaluated: int) -> Tuple[float, float, float]:
    """The number shown when nothing was measured: the prior, capped at
    NO_EVIDENCE_CEILING, from 0 up to the prior band's upper end."""
    point, _, upper = prior_coverage(papers_evaluated)
    point = min(point, NO_EVIDENCE_CEILING)
    return (point, 0.0, max(point, upper))


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
        (`method`: "sample_coverage" or "prior"; `relevance_band`: the rcs
        floor the estimate was taken over, None for the prior).
    """
    if papers_evaluated is None:
        papers_evaluated = len(kg)

    def band(floor: int) -> Set[str]:
        return {key for key, p in kg.items() if p.rcs is not None and p.rcs >= floor}

    highly_relevant_count = len(band(HIGHLY_RELEVANT_RCS))

    estimate, relevance_band = None, None
    for floor in (RELEVANCE_BANDS if occasions else ()):
        candidate = sample_coverage(occasions, band(floor))
        if candidate and candidate["informative"]:
            estimate, relevance_band = candidate, floor
            break
    if estimate:
        point, lower, upper = estimate["coverage"], estimate["lower"], estimate["upper"]
        method = "sample_coverage"
    else:
        point, lower, upper = no_evidence_coverage(papers_evaluated)
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
        "relevance_band": relevance_band,
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
    band_note = (
        f" over rcs >= {snapshot['relevance_band']}" if snapshot["relevance_band"] else ""
    )
    print(
        f"discovery_curve: coverage {snapshot['coverage_estimate']:.0%} "
        f"({snapshot['method']}{band_note}, {snapshot['occasions']} retrieval files) -> {args.output}"
    )
