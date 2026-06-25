"""Agent search: a headless, single-command full-pipeline entry point for agents.

Why this module exists (R1 + R2 — read those research docs for the full story)
-----------------------------------------------------------------------------
Forensics on 154 real Claude-Code-session samples (R1) showed that when an agent
calls paper-search-pro from inside a larger orchestration, it loads the Skill but
then *only* drives ``openalex_helper`` for raw retrieval and skips classification,
saturation, HTML — every discipline step that lives in the human 14-STEP recipe.
This is not laziness: the agent's consumer is *itself* (it feeds the data to its
own judgement), so a human-facing HTML report solves a problem it does not have.

The external survey (R2) reached the matching conclusion: you cannot make an
agent follow a multi-step recipe by writing a stricter prompt — Opus 4.8 skips
user-defined sequences even with CLAUDE.md + rules + hooks (issue #65951). The
only reliable fix is to **bake the discipline into deterministic code** the agent
*cannot* bypass, and hand it back a single structured envelope.

So this module is the "agent path": one command runs the deterministic core
(multi-strategy retrieve -> federate dedup -> field tidy -> built-in heuristic
relevance score -> lightweight saturation signal -> quota snapshot) and prints a
single JSON envelope to stdout. It NEVER renders HTML, NEVER writes PRISMA, and
NEVER dispatches an LLM classification subagent. The human 14-STEP path is
untouched (R-19): this is a brand-new additive entry point.

Envelope contract (R2 §5.2, ai-native-cli-spec)
-----------------------------------------------
Success::

    {
      "ok": true,
      "schema_version": "1.0",
      "data": [ <paper>, ... ],          # field-tidied, deduped, scored, sorted
      "meta": {
        "query": {...},                  # topic / years / strategy params
        "counts": {...},                 # retrieved_raw / after_dedup / returned
        "relevance": {...},              # heuristic descriptor (NOT an LLM RCS)
        "saturation": {...},             # heuristic stop signal
        "ratelimit": {...},              # quota_guard probe snapshot
        "source_used": "openalex",       # openalex | semantic_scholar
        "warnings": [ ... ]
      }
    }

Failure::

    {"ok": false, "schema_version": "1.0",
     "error": {"code": "E_*", "message": "...", "retryable": bool},
     "meta": {...}}

Each ``<paper>`` carries:
- the full UnifiedPaperEntity field set (so the agent gets rich data, R1 §4),
- ``relevance`` : {score: 0..1, label, method: "heuristic_v1", components: {...}}
  — the built-in, always-computed, deterministic signal (B-2). It is a SIGNAL,
  not a gate: every returned paper carries it; the agent may self-judge on top,
  but it never gets data without a score.
- ``journal_metric`` : reserved slot for Wave 3d (SJR quartile / OpenAlex
  impact). Always present, value ``None`` here — 3d fills it in.
- when ``--verify`` is on, a ``verify`` block (existence + abstract +
  cross-source consistency markers).

Exit codes (aligned to error.code):
    0  ok
    2  E_NO_RESULTS        (retryable=false)  — search ran but returned nothing
    4  E_CONFIG            (retryable=false)  — misconfiguration (e.g. SS w/o key)
    7  E_RATE_LIMITED      (retryable=true)   — upstream throttled / quota gone
    6  E_INTERNAL          (retryable=false)  — unexpected failure
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .types import Config, UnifiedPaperEntity

# These imports are the deterministic core the agent path REUSES (no new search
# logic invented here — same backends the human path uses, R-14/enhance-not-rewrite).
from . import openalex_helper, ss_helper, quota_guard, crossref_helper
from .federated_kg_resolver import federated_dedup, kg_to_list

SCHEMA_VERSION = "1.0"

# Current UTC-ish "now" year for recency scoring. Kept as a module constant so a
# test can monkeypatch it deterministically rather than depending on wall-clock.
_CURRENT_YEAR = 2026


# ===========================================================================
# Error / envelope plumbing
# ===========================================================================


@dataclass
class AgentError(Exception):
    """A structured, envelope-ready error. code maps to an exit code."""

    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.message}"


# error.code -> process exit code
_EXIT_FOR_CODE = {
    "E_NO_RESULTS": 2,
    "E_CONFIG": 4,
    "E_INTERNAL": 6,
    "E_RATE_LIMITED": 7,
}


def _ok_envelope(data: List[Dict], meta: Dict) -> Dict:
    return {"ok": True, "schema_version": SCHEMA_VERSION, "data": data, "meta": meta}


def _error_envelope(err: AgentError, meta: Optional[Dict] = None) -> Dict:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "error": {"code": err.code, "message": err.message, "retryable": err.retryable},
        "meta": meta or {},
    }


# ===========================================================================
# Query tokenisation (for the heuristic relevance score)
# ===========================================================================

# Stopwords that carry no topical signal — excluded so "the role of memory in
# learning" scores on {role, memory, learning}, not on {the, of, in}.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have in into is it its of on or
    that the their to was were will with within without between among across over
    under about via per vs versus using used use based study studies research
    review analysis effect effects role""".split()
)

# Boolean-query operators SS/OpenAlex understand; we strip them for term scoring
# so "(machine learning) + (healthcare)" tokenises to {machine, learning,
# healthcare} rather than scoring the "+"/parens.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize_query(query: str) -> List[str]:
    """Lowercase the query, drop boolean punctuation and stopwords, keep terms
    of length >= 3 (so 'ml' survives only as 'machine'/'learning' when spelled
    out; very short tokens are noise for coverage scoring)."""
    raw = _TOKEN_RE.findall((query or "").lower())
    terms = [t for t in raw if len(t) >= 3 and t not in _STOPWORDS]
    # Preserve order but dedupe so a repeated term doesn't inflate coverage.
    seen = set()
    out: List[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _coverage(terms: List[str], text: Optional[str]) -> float:
    """Fraction of query terms present in text (substring match on whole-word
    boundaries-ish: we just test token membership in the text's token set).

    Substring-free, token-set membership avoids 'cat' matching 'category'."""
    if not terms or not text:
        return 0.0
    text_tokens = set(_TOKEN_RE.findall(text.lower()))
    if not text_tokens:
        return 0.0
    hits = sum(1 for t in terms if t in text_tokens)
    return hits / len(terms)


# ===========================================================================
# Heuristic relevance score (B-2) — deterministic, always computed, NOT an RCS
# ===========================================================================
#
# Design rationale (documented in impl_3c_notes.md):
# The score is a weighted blend of four query-grounded signals. It is a SIGNAL
# the agent can build on, never a silent gate. It is explicitly labelled
# "heuristic_v1" so no consumer mistakes it for the LLM-based RCS (0-10) that the
# human path computes via a classification subagent.
#
#   relevance = 0.50 * title_coverage
#             + 0.25 * abstract_coverage
#             + 0.15 * citation_signal     (log-scaled, saturating)
#             + 0.10 * recency_signal      (linear over a 25-year window)
#
# Why these weights:
# - Title coverage is the strongest precision signal a query word appearing in a
#   title is far more diagnostic of on-topic-ness than in a long abstract, so it
#   carries the most weight (0.50).
# - Abstract coverage broadens recall but is noisier (abstracts mention many
#   adjacent concepts), hence 0.25.
# - Citation signal is a *quality/impact* prior, not a topical one; it nudges
#   well-cited on-topic papers up without letting a hugely-cited off-topic paper
#   win (capped at 0.15 and log-scaled so 100 vs 10000 cites differ modestly).
# - Recency is a mild freshness prior (0.10) so that, among similarly on-topic
#   and similarly cited papers, newer ones edge ahead — useful for the agent's
#   "is this a live area" judgement without burying seminal old work.
#
# Components are returned alongside the score so the agent (and reviewers) can
# see exactly why a paper scored what it did — no black box.

_W_TITLE = 0.50
_W_ABSTRACT = 0.25
_W_CITATION = 0.15
_W_RECENCY = 0.10

# Citation saturates: log10(cites+1) / log10(CAP+1), clamped to 1. CAP=2000 means
# a 2000-cite paper gets ~full citation credit; beyond that the marginal signal
# is flat (a 50k-cite classic shouldn't dominate purely on impact).
_CITATION_CAP = 2000.0
# Recency window: papers older than this many years get 0 recency credit; this
# year gets full credit. Linear in between.
_RECENCY_WINDOW_YEARS = 25.0


def _citation_signal(citation_count: Optional[int]) -> float:
    c = max(0, int(citation_count or 0))
    if c <= 0:
        return 0.0
    return min(1.0, math.log10(c + 1) / math.log10(_CITATION_CAP + 1))


def _recency_signal(year: Optional[int], *, now_year: int = _CURRENT_YEAR) -> float:
    if not year or year <= 0:
        return 0.0
    age = now_year - int(year)
    if age <= 0:
        return 1.0
    if age >= _RECENCY_WINDOW_YEARS:
        return 0.0
    return 1.0 - (age / _RECENCY_WINDOW_YEARS)


def _label_for(score: float) -> str:
    """Coarse human-/agent-readable band for the heuristic score."""
    if score >= 0.6:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def compute_relevance(
    paper: UnifiedPaperEntity, terms: List[str], *, now_year: int = _CURRENT_YEAR
) -> Dict:
    """Deterministic, query-grounded heuristic relevance for one paper.

    Returns a dict (never None): {score, label, method, components}. The score is
    in [0, 1]. ``method`` is fixed to "heuristic_v1" and ``is_llm_rcs`` is False
    so no consumer confuses it with the human path's LLM RCS.
    """
    title_cov = _coverage(terms, paper.title)
    abstract_cov = _coverage(terms, paper.abstract)
    cite_sig = _citation_signal(paper.citation_count)
    rec_sig = _recency_signal(paper.year, now_year=now_year)

    score = (
        _W_TITLE * title_cov
        + _W_ABSTRACT * abstract_cov
        + _W_CITATION * cite_sig
        + _W_RECENCY * rec_sig
    )
    score = round(min(1.0, max(0.0, score)), 4)

    return {
        "score": score,
        "label": _label_for(score),
        "method": "heuristic_v1",
        "is_llm_rcs": False,
        "components": {
            "title_coverage": round(title_cov, 4),
            "abstract_coverage": round(abstract_cov, 4),
            "citation_signal": round(cite_sig, 4),
            "recency_signal": round(rec_sig, 4),
        },
    }


# ===========================================================================
# Saturation signal (heuristic, no LLM classification)
# ===========================================================================
#
# Without an LLM classifier we cannot compute the human path's RCS-based
# discovery curve. Instead we expose two cheap, deterministic signals the agent
# can read to judge whether the search was thorough:
#
# 1. Marginal-yield decay across strategies: each retrieval strategy is run in
#    sequence; we record how many *new* (previously-unseen) papers each strategy
#    contributed. A search that has saturated shows the later strategies adding
#    few new papers. We report the per-strategy new-yield and a boolean
#    ``looks_saturated`` when the last strategy's marginal new-yield fraction is
#    below a small threshold.
# 2. Score distribution: the share of returned papers scoring "high" vs "low".
#    A pool dominated by low scores hints the query under-specifies the topic.
#
# This is explicitly ADVISORY (mirrors discovery_curve.py's contract). It never
# truncates or gates results.

_SATURATION_YIELD_THRESHOLD = 0.15  # last strategy adding <15% new -> saturated


def _saturation_signal(
    per_strategy_new: List[int], total_unique: int, scores: List[float]
) -> Dict:
    """Build the heuristic saturation block.

    Args:
        per_strategy_new: count of NEW unique papers each strategy contributed,
            in strategy order.
        total_unique: total unique papers after dedup.
        scores: relevance scores of the returned papers.
    """
    last_new = per_strategy_new[-1] if per_strategy_new else 0
    # Marginal new-yield fraction of the final strategy relative to the running
    # total at that point. If total is tiny, treat as not-saturated (too little
    # evidence).
    marginal = (last_new / total_unique) if total_unique > 0 else 0.0
    looks_saturated = (
        total_unique >= 10
        and len(per_strategy_new) >= 2
        and marginal <= _SATURATION_YIELD_THRESHOLD
    )

    high = sum(1 for s in scores if s >= 0.6)
    medium = sum(1 for s in scores if 0.35 <= s < 0.6)
    low = sum(1 for s in scores if s < 0.35)

    return {
        "method": "heuristic_v1",
        "advisory": True,
        "looks_saturated": bool(looks_saturated),
        "per_strategy_new_papers": list(per_strategy_new),
        "last_strategy_marginal_yield": round(marginal, 4),
        "score_distribution": {"high": high, "medium": medium, "low": low},
        "note": (
            "Heuristic stop signal (no LLM classification). 'looks_saturated' = "
            "later strategies added few new papers. Advisory only."
        ),
    }


# ===========================================================================
# Retrieval (reuses openalex_helper / ss_helper.search — no new search logic)
# ===========================================================================


def _resolve_source(config: Config) -> Tuple[str, bool]:
    """Decide which primary source to use for this run.

    Returns (source_used, switched) where source_used is "openalex" or
    "semantic_scholar" and ``switched`` notes whether an auto-mode quota fallback
    fired.

    Routing (mirrors the Wave 3b contract):
      - primary_source == "semantic_scholar" -> SS.
      - primary_source == "auto"             -> OpenAlex, but a run-mode quota
        probe may stickily fall back to SS when OA USD budget is low (and
        quota_fallback is enabled).
      - anything else (incl. "openalex")     -> OpenAlex (default, unchanged).
    """
    primary = (getattr(config, "primary_source", "openalex") or "openalex").lower()
    if primary == "semantic_scholar":
        return "semantic_scholar", False
    if primary == "auto" and getattr(config, "quota_fallback", True):
        status = quota_guard.evaluate(config, mode="run")
        if status.ok and status.should_switch:
            return "semantic_scholar", True
        return "openalex", False
    return "openalex", False


def _retrieve(
    query: str,
    source: str,
    *,
    year_min: Optional[int],
    year_max: Optional[int],
    per_strategy: int,
) -> Tuple[List[List[UnifiedPaperEntity]], List[str]]:
    """Run the multi-strategy retrieval for the chosen source.

    Returns (strategy_results, warnings). ``strategy_results`` is a list of
    per-strategy entity lists (so the caller can compute marginal yield). We
    reuse the *existing* multi-strategy backends rather than reinventing:

      - OpenAlex: the three double_sort strategies (cited / recent / relevance),
        run individually so we can measure per-strategy yield. (double_sort_search
        collapses them; here we call its constituents to keep the marginal-yield
        signal — same queries, same sorts, no new logic.)
      - Semantic Scholar: ss_helper.search already runs its three bulk strategies
        and returns a merged list; we treat that merged list as one "strategy"
        for yield purposes since SS does not expose per-strategy splits through
        the public search() API. (Documented limitation, not a correctness gap.)
    """
    warnings: List[str] = []

    if source == "openalex":
        strategies = [
            ("cited_by_count:desc", openalex_helper.search_top_n_pages),
            ("publication_date:desc", openalex_helper.search_top_n_pages),
            ("relevance_score:desc", openalex_helper.search_top_n_pages),
        ]
        results: List[List[UnifiedPaperEntity]] = []
        for sort, fn in strategies:
            try:
                batch = fn(query, total_papers=per_strategy, sort=sort, year_min=year_min)
            except Exception as exc:  # one bad strategy must not kill the run
                warnings.append(f"openalex strategy {sort} failed: {exc}")
                batch = []
            results.append(batch)
        return results, warnings

    # Semantic Scholar primary.
    try:
        merged = ss_helper.search(
            query, year_min=year_min, year_max=year_max, total_per_strategy=per_strategy
        )
    except Exception as exc:
        warnings.append(f"semantic_scholar search failed: {exc}")
        merged = []
    if not merged:
        warnings.append(
            "semantic_scholar returned 0 papers (no key -> 429 on shared pool is "
            "the most common cause; set semantic_scholar_api_key)."
        )
    return [merged], warnings


# ===========================================================================
# Dedup + per-strategy marginal-yield accounting
# ===========================================================================


def _dedup_with_yield(
    strategy_results: List[List[UnifiedPaperEntity]],
) -> Tuple[List[UnifiedPaperEntity], List[int], int]:
    """Federate-dedup the strategy results, tracking how many NEW unique papers
    each strategy added (for the saturation signal).

    Returns (unique_papers_sorted, per_strategy_new, retrieved_raw).
    Uses the same federated_dedup the human path uses (R-14: don't reinvent).
    """
    from .federated_kg_resolver import canonical_key

    retrieved_raw = sum(len(s) for s in strategy_results)
    seen_keys: set = set()
    per_strategy_new: List[int] = []
    for strat in strategy_results:
        new_here = 0
        for p in strat:
            k = canonical_key(p)
            if k not in seen_keys:
                seen_keys.add(k)
                new_here += 1
        per_strategy_new.append(new_here)

    # Now do the real merge (which also fuses fields across duplicates).
    kg = federated_dedup(*strategy_results)
    unique = kg_to_list(kg, sort_by="citation_count")
    return unique, per_strategy_new, retrieved_raw


# ===========================================================================
# Verification (--verify): existence + abstract + cross-source consistency
# ===========================================================================
#
# R1 §4 found citation/abstract verification is the agent's most-needed and
# most error-prone hand-rolled capability (it fears fabricating papers). We give
# it a deterministic, no-LLM check per paper:
#
#  - exists: True when the paper has a resolvable identity. We treat a paper as
#    "exists" if it has a DOI OR an OpenAlex/SS/PubMed/arXiv id (it came back from
#    a real source query, so it exists by construction; the markers below tell the
#    agent HOW grounded that existence is).
#  - has_doi / has_abstract: explicit booleans so the agent knows when metadata
#    it might want to cite is missing.
#  - multi_source: True when the federated record was hit by >=2 sources
#    (stronger existence evidence).
#  - title_year_present: cross-source consistency proxy — we flag records missing
#    a title or year (the two fields an agent most often needs to cite).
#
# This is intentionally network-free in its default form: every signal is derived
# from the already-fetched federated entity, so --verify adds no extra API cost
# and cannot fabricate. (A future deeper verify could resolve DOIs over HTTP; the
# B-2 contract only requires the deterministic existence/consistency markers,
# which we provide here.)


def _verify_paper(paper: UnifiedPaperEntity) -> Dict:
    has_doi = bool(paper.doi)
    has_abstract = bool(paper.abstract and paper.abstract.strip())
    n_sources = len(paper.sources or [])
    has_any_id = bool(
        paper.doi
        or paper.openalex_id
        or paper.ss_paper_id
        or paper.pmid
        or paper.arxiv_id
    )
    flags: List[str] = []
    if not has_doi:
        flags.append("no_doi")
    if not has_abstract:
        flags.append("no_abstract")
    if not paper.title:
        flags.append("no_title")
    if not paper.year:
        flags.append("no_year")
    if n_sources < 2:
        flags.append("single_source")

    return {
        "exists": has_any_id,
        "has_doi": has_doi,
        "has_abstract": has_abstract,
        "multi_source": n_sources >= 2,
        "source_count": n_sources,
        "title_year_present": bool(paper.title and paper.year),
        "flags": flags,
    }


def _verify_summary(verifies: List[Dict]) -> Dict:
    n = len(verifies)
    return {
        "total": n,
        "with_doi": sum(1 for v in verifies if v["has_doi"]),
        "with_abstract": sum(1 for v in verifies if v["has_abstract"]),
        "multi_source": sum(1 for v in verifies if v["multi_source"]),
        "missing_title_or_year": sum(1 for v in verifies if not v["title_year_present"]),
    }


# ===========================================================================
# Reference verification (--verify-refs): direct anti-hallucination entry
# ===========================================================================
#
# R1 §4 found the single most valuable thing an agent needs from this Skill is
# NOT a topic search at all — it is "I already have a list of papers I want to
# cite; tell me which of them actually EXIST so I never cite a hallucinated one."
# The topic-search `--verify` markers only describe results the agent just
# retrieved; they cannot answer "is THIS specific DOI/title real?" without first
# running a full search and hoping the paper turns up in it.
#
# `verify_references` is that direct entry point. Given a list of refs (each a
# DOI and/or a title), it checks each one's EXISTENCE across the free
# authoritative sources (OpenAlex / CrossRef / Semantic Scholar) and returns a
# per-ref ruling plus the canonical metadata of whatever it matched, so the agent
# can both confirm existence and self-correct drifted titles/years/venues.
#
# Contract per ref:
#   {
#     "ref":            {<the input ref, echoed back>},
#     "exists":         bool,            # matched in >=1 authoritative source
#     "matched_source": "openalex"|"crossref"|"semantic_scholar"|null,
#     "canonical":      {title, year, doi, venue} | null,  # from the match
#     "note":           "<human-readable explanation>"
#   }
# plus a summary: {total, verified, not_found, by_source, errors}.
#
# Existence policy (deliberate, R-09-style honesty about what each signal means):
#   - A ref with a DOI "exists" when ANY source resolves that DOI to a record.
#     We prefer OpenAlex (richest canonical), then CrossRef (registry of record
#     for DOIs), then SS. The DOI is the strongest existence proof there is.
#   - A title-only ref "exists" when an OpenAlex title search returns a record
#     whose normalized title matches the input closely (token-set equality on
#     the significant tokens). This is necessarily weaker than a DOI hit — a near
#     match is reported with a clear note so the agent does not over-trust it.
#   - Anything not matched is exists=False with a note. We NEVER fabricate a
#     "probably real" verdict — the whole point is to catch hallucinations.


def _normalize_title_tokens(title: Optional[str]) -> frozenset:
    """Significant-token set of a title for fuzzy equality (lowercased, stopwords
    and short tokens dropped, deduped). Used to decide whether a title-search hit
    is really the same paper as the requested title."""
    raw = _TOKEN_RE.findall((title or "").lower())
    return frozenset(t for t in raw if len(t) >= 3 and t not in _STOPWORDS)


def _title_match_ratio(requested: Optional[str], candidate: Optional[str]) -> float:
    """Jaccard-style overlap of the two titles' significant token sets, in [0,1].
    1.0 = identical significant tokens; used with a threshold so a loosely related
    paper is NOT accepted as a match."""
    a = _normalize_title_tokens(requested)
    b = _normalize_title_tokens(candidate)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# A title-search candidate is accepted as "the same paper" at or above this
# token-set overlap. Tuned conservatively: anti-hallucination wants few false
# "exists" verdicts, so we err towards "not found" on a weak match.
_TITLE_MATCH_THRESHOLD = 0.85


def _canonical_from_entity(p: UnifiedPaperEntity) -> Dict:
    """The four fields an agent most needs to confirm/correct a citation."""
    return {
        "title": p.title or None,
        "year": p.year,
        "doi": p.doi,
        "venue": p.venue,
    }


def _verify_one_ref(
    ref: Dict,
    *,
    oa_ready: bool,
    cr_ready: bool,
    ss_ready: bool,
) -> Dict:
    """Verify a single reference's existence across the available sources.

    ``ref`` is a dict that may carry ``doi`` and/or ``title`` (other keys are
    echoed back untouched). Each source call is wrapped so one failure never
    aborts the batch. Returns the per-ref ruling dict (see module section above).
    """
    doi = (ref.get("doi") or ref.get("DOI") or "").strip() or None
    title = (ref.get("title") or "").strip() or None

    result: Dict = {
        "ref": ref,
        "exists": False,
        "matched_source": None,
        "canonical": None,
        "note": "",
    }

    if not doi and not title:
        result["note"] = "no doi and no title supplied — nothing to verify"
        return result

    # ---- DOI path: strongest existence proof. Try OA -> CrossRef -> SS. ----
    if doi:
        # OpenAlex (richest canonical record).
        if oa_ready:
            try:
                oa_paper = openalex_helper.get_work(doi)
            except Exception:
                oa_paper = None
            if oa_paper is not None and (oa_paper.doi or oa_paper.title or oa_paper.openalex_id):
                result["exists"] = True
                result["matched_source"] = "openalex"
                result["canonical"] = _canonical_from_entity(oa_paper)
                result["note"] = "DOI resolved in OpenAlex."
                return result

        # CrossRef — the DOI registry of record; authoritative for "does this DOI
        # exist". _fetch_doi returns None for arXiv DOIs and any non-hit.
        if cr_ready:
            try:
                cr_msg = crossref_helper._fetch_doi(doi)
            except Exception:
                cr_msg = None
            if cr_msg:
                titles = cr_msg.get("title") or []
                cr_title = titles[0] if isinstance(titles, list) and titles else None
                year = None
                issued = (cr_msg.get("issued") or {}).get("date-parts") or []
                if issued and issued[0]:
                    year = issued[0][0]
                containers = cr_msg.get("container-title") or []
                venue = containers[0] if isinstance(containers, list) and containers else None
                result["exists"] = True
                result["matched_source"] = "crossref"
                result["canonical"] = {
                    "title": cr_title,
                    "year": year,
                    "doi": (cr_msg.get("DOI") or doi).lower(),
                    "venue": venue,
                }
                result["note"] = "DOI resolved in CrossRef registry."
                return result

        # Semantic Scholar single-paper lookup as a last DOI resolver.
        if ss_ready:
            ss_doi = ss_helper._doi_for_ss(doi)
            if ss_doi:
                try:
                    sp = ss_helper._get_client().get_paper(
                        ss_doi, fields="title,year,externalIds,venue"
                    )
                except Exception:
                    sp = None
                if sp is not None and (getattr(sp, "title", None) or getattr(sp, "paperId", None)):
                    result["exists"] = True
                    result["matched_source"] = "semantic_scholar"
                    result["canonical"] = {
                        "title": getattr(sp, "title", None),
                        "year": getattr(sp, "year", None),
                        "doi": doi.lower(),
                        "venue": getattr(sp, "venue", None),
                    }
                    result["note"] = "DOI resolved in Semantic Scholar."
                    return result

        # DOI supplied but no source resolved it.
        if title:
            result["note"] = (
                "DOI did not resolve in OpenAlex/CrossRef/SS; trying the title next."
            )
        else:
            result["note"] = (
                "DOI did not resolve in OpenAlex/CrossRef/SS — likely fabricated "
                "or malformed. Supply a title for a secondary check."
            )
            return result

    # ---- Title path: weaker; require a close token-set match (anti-FP). ----
    if title and oa_ready:
        try:
            candidates = openalex_helper.search_works(title, limit=5)
        except Exception:
            candidates = []
        best = None
        best_ratio = 0.0
        for cand in candidates:
            ratio = _title_match_ratio(title, cand.title)
            if ratio > best_ratio:
                best_ratio = ratio
                best = cand
        if best is not None and best_ratio >= _TITLE_MATCH_THRESHOLD:
            result["exists"] = True
            result["matched_source"] = "openalex"
            result["canonical"] = _canonical_from_entity(best)
            note = f"Title matched in OpenAlex (token overlap {best_ratio:.2f})."
            if doi:
                # DOI failed but the title resolved — flag the likely-wrong DOI.
                note += (
                    " NOTE: the supplied DOI did NOT resolve but the title did — "
                    "the DOI is probably wrong; use canonical.doi."
                )
            result["note"] = note
            return result
        # A best-but-weak match is informative without being accepted as proof.
        if best is not None and best_ratio > 0.0:
            result["note"] = (
                f"No confident title match (best token overlap {best_ratio:.2f} < "
                f"{_TITLE_MATCH_THRESHOLD}); closest OpenAlex title: "
                f"{best.title!r}. Treat as NOT verified."
            )
        else:
            result["note"] = "Title not found in OpenAlex. Treat as NOT verified."
        return result

    if title and not oa_ready:
        result["note"] = "OpenAlex unavailable; could not verify title-only ref."
    return result


def verify_references(refs: List[Dict], config: Config) -> Dict:
    """Verify a list of references' EXISTENCE across free authoritative sources.

    This is the direct anti-hallucination entry point (does NOT require running a
    topic search first). Never raises: source init failures degrade to "that
    source unavailable" and are reported in the summary; per-ref source calls are
    individually guarded. Returns an envelope::

        {ok, schema_version, data: [<per-ref ruling>, ...], meta: {...summary}}

    Existence is decided per ref (see the module section above): a DOI that
    resolves in any source is the strongest proof; a title-only ref must clear a
    conservative token-overlap threshold; anything else is exists=False — we never
    invent a "probably real" verdict.
    """
    warnings: List[str] = []

    if not isinstance(refs, list):
        return _error_envelope(
            AgentError(
                "E_CONFIG",
                "verify-refs input must be a JSON list of refs (or {references:[...]}).",
                retryable=False,
            )
        )
    if not refs:
        return _error_envelope(
            AgentError("E_NO_RESULTS", "no references supplied to verify", retryable=False),
            meta={"summary": {"total": 0}},
        )

    # Initialise the three free resolvers; any that fails to init is simply marked
    # unavailable (the others still verify). OpenAlex is required for title-only
    # refs but DOI refs can still resolve via CrossRef/SS without it.
    try:
        openalex_helper.init_pyalex(config)
        oa_ready = True
    except Exception as exc:
        oa_ready = False
        warnings.append(f"OpenAlex init failed (DOI/title OA checks skipped): {exc}")
    try:
        crossref_helper.init(config)
        cr_ready = True
    except Exception as exc:
        cr_ready = False
        warnings.append(f"CrossRef init failed (CrossRef DOI checks skipped): {exc}")
    try:
        ss_helper.init(config)
        ss_ready = True
    except Exception as exc:
        ss_ready = False
        warnings.append(f"Semantic Scholar init failed (SS DOI checks skipped): {exc}")

    data: List[Dict] = []
    by_source: Dict[str, int] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            ref = {"raw": ref}
        try:
            ruling = _verify_one_ref(
                ref, oa_ready=oa_ready, cr_ready=cr_ready, ss_ready=ss_ready
            )
        except Exception as exc:  # absolute per-ref backstop
            ruling = {
                "ref": ref,
                "exists": False,
                "matched_source": None,
                "canonical": None,
                "note": f"verification error: {exc}",
            }
        if ruling.get("matched_source"):
            by_source[ruling["matched_source"]] = by_source.get(ruling["matched_source"], 0) + 1
        data.append(ruling)

    verified = sum(1 for r in data if r["exists"])
    meta = {
        "mode": "verify_references",
        "sources_available": {
            "openalex": oa_ready,
            "crossref": cr_ready,
            "semantic_scholar": ss_ready,
        },
        "summary": {
            "total": len(data),
            "verified": verified,
            "not_found": len(data) - verified,
            "by_source": by_source,
        },
        "title_match_threshold": _TITLE_MATCH_THRESHOLD,
        "warnings": warnings,
        "note": (
            "Existence verification across free authoritative sources (OpenAlex / "
            "CrossRef / Semantic Scholar). A resolved DOI is the strongest proof; "
            "title-only matches must clear a conservative token-overlap threshold. "
            "exists=false means NOT confirmed — likely hallucinated or wrong."
        ),
    }
    return _ok_envelope(data, meta)


def _load_refs_file(path: str) -> List[Dict]:
    """Load the verify-refs input file. Accepts a bare JSON list, or an object
    with a top-level ``references`` / ``refs`` list. Each element should be an
    object with ``doi`` and/or ``title`` (a bare string is treated as a title)."""
    import json

    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, dict):
        payload = payload.get("references") or payload.get("refs") or []
    if not isinstance(payload, list):
        return []
    out: List[Dict] = []
    for item in payload:
        if isinstance(item, str):
            out.append({"title": item})
        elif isinstance(item, dict):
            out.append(item)
        else:
            out.append({"raw": item})
    return out


# ===========================================================================
# Serialisation
# ===========================================================================


def _paper_to_dict(p: UnifiedPaperEntity) -> Dict:
    """Full entity serialisation (same broad field set as openalex_helper._to_dict),
    flattening Author objects. The relevance/journal_metric/verify blocks are
    attached by the caller after scoring.

    NOTE: the entity's own ``journal_metric`` field (a dataclass or None) is
    dropped here — the caller re-attaches a fully-serialised journal_metric dict
    into the reserved slot, so the value is always a plain dict/None in output."""
    d: Dict = {}
    for f, v in p.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        elif f == "journal_metric":
            continue  # re-attached as a dict by the caller (reserved slot)
        else:
            d[f] = v
    return d


def _journal_metric_to_dict(metric) -> Optional[Dict]:
    """Serialise a JournalMetric dataclass to a JSON-safe dict, or None when the
    metric carries no real data (so the slot stays None — byte-identical to the
    pre-3d behavior for papers with no journal data)."""
    from . import sjr_helper

    if sjr_helper.metric_is_empty(metric):
        return None
    return {
        "sjr_quartile": metric.sjr_quartile,
        "sjr_category_quartiles": dict(metric.sjr_category_quartiles),
        "openalex_2yr_mean_citedness": metric.openalex_2yr_mean_citedness,
        "h_index": metric.h_index,
        "cwts_snip": metric.cwts_snip,
        "sjr_attribution": metric.sjr_attribution,
        "issn_backfill_needed": metric.issn_backfill_needed,
    }


# Quartile ordering for filtering: a paper passes ``--quartile Q1,Q2`` when its
# SJR quartile is in the requested set.
_QUARTILE_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


# ===========================================================================
# Orchestration — the one function that runs the whole agent pipeline
# ===========================================================================


def run_agent_search(
    query: str,
    config: Config,
    *,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    per_strategy: int = 50,
    limit: Optional[int] = None,
    min_relevance: float = 0.0,
    verify: bool = False,
    quartiles: Optional[List[str]] = None,
    min_impact: Optional[float] = None,
    journal_category: Optional[str] = None,
    sjr_csv: Optional[str] = None,
    enrich_journal: bool = True,
    issn_backfill: bool = True,
    now_year: int = _CURRENT_YEAR,
) -> Dict:
    """Run the full deterministic agent pipeline and return the envelope dict.

    Never raises: any failure is converted to an error envelope. The relevance
    score is ALWAYS computed for every returned paper (B-2) — ``min_relevance``
    only filters which papers are returned, it does not disable scoring.

    Feature A (journal metric, v2.2 Wave 3d): when ``enrich_journal`` is True
    (default) each paper's reserved ``journal_metric`` slot is filled with its SJR
    quartile (from a cached SJR CSV, if any) + OpenAlex open impact. This is a
    pure additive enrichment — with no CSV cached and no impact reachable the slot
    stays None, exactly as before. ``quartiles`` (e.g. ["Q1","Q2"]) and
    ``min_impact`` are OPT-IN filters: like ``min_relevance``, the metric is
    always computed; these only filter *which* papers are returned.

    ``issn_backfill`` (default True) only affects the SEMANTIC-SCHOLAR-primary
    path: SS records often lack an ISSN, so by default each relevance-survivor
    that has a DOI but no ISSN gets a free single-paper OpenAlex lookup to recover
    it (so the SJR join is not silently lost). Set it False to skip those per-paper
    lookups on large SS result sets — papers then stay unjoinable and the gap stays
    visible (``journal_metric.issn_backfill_needed``). No effect on the OpenAlex
    path or the human path.
    """
    warnings: List[str] = []

    if not (query or "").strip():
        return _error_envelope(
            AgentError("E_CONFIG", "query is empty", retryable=False)
        )

    terms = _tokenize_query(query)

    # ---- Source routing (+ auto-mode quota fallback) ----
    try:
        source_used, switched = _resolve_source(config)
    except Exception as exc:
        source_used, switched = "openalex", False
        warnings.append(f"source routing fell back to openalex: {exc}")

    # SS-as-primary requires a key (R-06). Surface a config error early rather
    # than silently returning [] from a 429.
    if source_used == "semantic_scholar":
        ss_helper.init(config)
        if not ss_helper._api_key_from_config():
            return _error_envelope(
                AgentError(
                    "E_CONFIG",
                    "primary_source resolves to semantic_scholar but no SS API key "
                    "is configured (semantic_scholar_api_key). SS as a primary "
                    "source 429s on the shared pool without a key (R-06).",
                    retryable=False,
                ),
                meta={"source_used": source_used},
            )
    else:
        openalex_helper.init_pyalex(config)

    # ---- Quota snapshot (probe mode — never a switch directive here) ----
    try:
        qstatus = quota_guard.evaluate(config, mode="probe")
        ratelimit = qstatus.to_dict()
        ratelimit["switched_source"] = switched
    except Exception as exc:
        ratelimit = {"ok": False, "error": str(exc), "switched_source": switched}

    # ---- Retrieve ----
    strategy_results, retr_warnings = _retrieve(
        query, source_used, year_min=year_min, year_max=year_max, per_strategy=per_strategy
    )
    warnings.extend(retr_warnings)

    # ---- Dedup + per-strategy yield ----
    unique, per_strategy_new, retrieved_raw = _dedup_with_yield(strategy_results)

    if not unique:
        meta = {
            "query": {
                "topic": query,
                "year_min": year_min,
                "year_max": year_max,
                "per_strategy": per_strategy,
                "terms": terms,
            },
            "counts": {"retrieved_raw": retrieved_raw, "after_dedup": 0, "returned": 0},
            "source_used": source_used,
            "ratelimit": ratelimit,
            "warnings": warnings,
        }
        # No results: distinguish a likely rate-limit from a genuine empty query.
        if source_used == "semantic_scholar" and retrieved_raw == 0:
            return _error_envelope(
                AgentError(
                    "E_RATE_LIMITED",
                    "semantic_scholar returned no papers (likely 429 / no key).",
                    retryable=True,
                ),
                meta=meta,
            )
        return _error_envelope(
            AgentError("E_NO_RESULTS", "search returned no papers", retryable=False),
            meta=meta,
        )

    # ---- Score (ALWAYS, B-2) + reserve journal_metric slot + optional verify ----
    scored: List[Tuple[UnifiedPaperEntity, Dict]] = []
    for p in unique:
        rel = compute_relevance(p, terms, now_year=now_year)
        scored.append((p, rel))

    # Sort by heuristic relevance (desc), tie-break on citation_count (desc).
    scored.sort(key=lambda pr: (pr[1]["score"], pr[0].citation_count or 0), reverse=True)

    # Filter by min_relevance (signal-as-knob: filtering is opt-in, scoring is not).
    kept = [(p, rel) for (p, rel) in scored if rel["score"] >= min_relevance]
    after_relevance_filter = len(kept)

    # ---- Journal metric enrichment (Feature A, additive) + opt-in filtering ----
    # Enrich the relevance-survivors (not the whole dedup pool) since the impact
    # lookup is per-ISSN. SJR CSV is cache-first (None when absent → no quartile,
    # never an error). quartiles / min_impact are OPT-IN gates; the metric itself
    # is always attached.
    from . import sjr_helper

    sjr_lookup = None
    impact_lookup = None
    if enrich_journal:
        try:
            sjr_lookup = sjr_helper.load(csv_path=sjr_csv)
        except Exception as exc:
            warnings.append(f"SJR CSV load failed (continuing without quartiles): {exc}")
            sjr_lookup = None
        if sjr_lookup is None:
            warnings.append(
                "no SJR CSV cached — quartiles unavailable (impact still attached "
                "where reachable). Run `python3 -m scripts.sjr_helper --download`."
            )
        # OpenAlex open-impact lookup (CC0) only meaningful on the OpenAlex path
        # and when OA is initialised; SS-primary runs skip it to avoid extra calls.
        if source_used == "openalex":
            impact_lookup = openalex_helper.get_source_impact

    # ---- SS-primary ISSN backfill (R-08, open item #3) ----
    # SS records carry ISSN only in publicationVenue.issn (~2/3 coverage). For the
    # relevance-survivors that lack an ISSN but have a DOI, do a FREE single-paper
    # OpenAlex lookup to backfill source.issn so the SJR join is not silently lost.
    # Papers with no DOI remain unjoinable (the metric's issn_backfill_needed flag
    # keeps that gap visible). Per-paper try/except: a failed lookup never crashes
    # the search and never forces a switch — it just leaves that paper unjoined.
    issn_backfilled = 0
    issn_backfill_attempted = 0
    if enrich_journal and issn_backfill and source_used == "semantic_scholar":
        # Initialise OpenAlex once for the free DOI lookups (idempotent, cheap).
        try:
            openalex_helper.init_pyalex(config)
            oa_ready = True
        except Exception as exc:
            oa_ready = False
            warnings.append(
                f"OpenAlex init failed; SS-primary ISSN backfill skipped: {exc}"
            )
        if oa_ready:
            for p, _rel in kept:
                if p.issn or not p.doi:
                    continue
                issn_backfill_attempted += 1
                try:
                    oa_paper = openalex_helper.get_work(p.doi)
                except Exception:
                    oa_paper = None
                if oa_paper is not None and getattr(oa_paper, "issn", None):
                    p.issn = oa_paper.issn
                    issn_backfilled += 1
            # Any backfilled ISSN means the OpenAlex open-impact figure is now
            # reachable for those journals; enable the (CC0) impact lookup so SS
            # papers do not lose impact relative to the OpenAlex path.
            if issn_backfilled and impact_lookup is None:
                impact_lookup = openalex_helper.get_source_impact

    metric_by_id: Dict[int, object] = {}
    if enrich_journal:
        for p, _rel in kept:
            metric = sjr_helper.build_journal_metric(
                p.issn,
                sjr=sjr_lookup,
                category=journal_category,
                impact_lookup=impact_lookup,
            )
            metric_by_id[id(p)] = metric

    want_quartiles = {q.upper() for q in (quartiles or []) if q}
    apply_journal_filter = bool(want_quartiles) or (min_impact is not None)

    def _passes_journal_filter(metric) -> bool:
        if not apply_journal_filter:
            return True
        if want_quartiles:
            if not metric or metric.sjr_quartile not in want_quartiles:
                return False
        if min_impact is not None:
            val = metric.openalex_2yr_mean_citedness if metric else None
            if val is None or val < min_impact:
                return False
        return True

    if apply_journal_filter:
        kept = [(p, rel) for (p, rel) in kept if _passes_journal_filter(metric_by_id.get(id(p)))]
    after_journal_filter = len(kept)

    after_filter = after_relevance_filter  # back-compat name (relevance stage)
    if limit is not None and limit >= 0:
        kept = kept[:limit]

    data: List[Dict] = []
    verifies: List[Dict] = []
    for p, rel in kept:
        d = _paper_to_dict(p)
        d["relevance"] = rel
        # Reserved slot now filled (Wave 3d): SJR quartile + OpenAlex impact.
        # Serialised to a plain dict, or None when no journal data was joined
        # (byte-identical to the pre-3d None for unjoinable papers).
        metric = metric_by_id.get(id(p))
        d["journal_metric"] = _journal_metric_to_dict(metric) if metric is not None else None
        if verify:
            v = _verify_paper(p)
            d["verify"] = v
            verifies.append(v)
        data.append(d)

    all_scores = [rel["score"] for (_p, rel) in scored]
    saturation = _saturation_signal(per_strategy_new, len(unique), all_scores)

    meta: Dict = {
        "query": {
            "topic": query,
            "year_min": year_min,
            "year_max": year_max,
            "per_strategy": per_strategy,
            "terms": terms,
        },
        "counts": {
            "retrieved_raw": retrieved_raw,
            "after_dedup": len(unique),
            "after_relevance_filter": after_filter,
            "after_journal_filter": after_journal_filter,
            "returned": len(data),
        },
        "journal_metric": {
            "enriched": bool(enrich_journal),
            "sjr_loaded": sjr_lookup is not None,
            "sjr_source": str(sjr_lookup.source_path) if sjr_lookup is not None else None,
            "impact_source": "openalex_summary_stats" if impact_lookup is not None else None,
            "filter_quartiles": sorted(want_quartiles) if want_quartiles else None,
            "filter_min_impact": min_impact,
            "category": journal_category,
            # SS-primary ISSN backfill audit (R-08, open item #3): whether the
            # backfill ran, how many SS records lacked an ISSN, and how many were
            # recovered via a free OA DOI lookup.
            "issn_backfill_enabled": bool(issn_backfill),
            "issn_backfill_attempted": issn_backfill_attempted,
            "issn_backfilled": issn_backfilled,
            "attribution": (sjr_helper.SJR_ATTRIBUTION if sjr_lookup is not None else None),
            "note": (
                "SJR分区/期刊影响力 — NOT a JCR Impact Factor (R-04/R-09). "
                "openalex_2yr_mean_citedness is an OPEN impact figure for relative "
                "ranking only. Quartiles require a cached SJR CSV."
            ),
        },
        "relevance": {
            "method": "heuristic_v1",
            "is_llm_rcs": False,
            "min_relevance": min_relevance,
            "weights": {
                "title_coverage": _W_TITLE,
                "abstract_coverage": _W_ABSTRACT,
                "citation_signal": _W_CITATION,
                "recency_signal": _W_RECENCY,
            },
            "note": (
                "Deterministic query-grounded heuristic, NOT the human path's LLM "
                "RCS. A signal for self-judgement, computed for every paper."
            ),
        },
        "saturation": saturation,
        "ratelimit": ratelimit,
        "source_used": source_used,
        "warnings": warnings,
    }
    if verify:
        meta["verify_summary"] = _verify_summary(verifies)

    return _ok_envelope(data, meta)


# ===========================================================================
# CLI
# ===========================================================================


def _main_cli() -> int:
    import argparse
    import json
    import sys

    try:
        from .config import load_config
    except ImportError:  # standalone invocation
        from scripts.config import load_config  # type: ignore

    parser = argparse.ArgumentParser(
        prog="agent_search",
        description=(
            "Headless full-pipeline paper search for AGENT callers. One command -> "
            "one JSON envelope on stdout (retrieve -> dedup -> heuristic relevance "
            "score -> saturation signal -> quota snapshot). No HTML, no PRISMA, no "
            "LLM classification subagent. The human 14-STEP path is unaffected. "
            "Use --verify-refs to instead check whether a list of DOIs/titles "
            "actually EXIST (anti-hallucination), without running a topic search."
        ),
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Search topic (boolean ops supported by the source). Omit when using "
        "--verify-refs.",
    )
    parser.add_argument("--year-min", type=int, help="Minimum publication year (inclusive).")
    parser.add_argument("--year-max", type=int, help="Maximum publication year (inclusive).")
    parser.add_argument(
        "--per-strategy",
        type=int,
        default=50,
        help="Papers per retrieval strategy before cross-strategy dedup (default 50).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max papers to return after scoring/filtering (default: all).",
    )
    parser.add_argument(
        "--min-relevance",
        type=float,
        default=0.0,
        help="Drop papers scoring below this heuristic relevance (0..1). Scoring is "
        "ALWAYS computed; this only filters what is returned. Default 0.0 (keep all).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Attach per-paper existence + abstract + cross-source consistency markers.",
    )
    parser.add_argument(
        "--quartile",
        default=None,
        help="Comma-separated SJR quartiles to KEEP, e.g. 'Q1,Q2'. OPT-IN filter "
        "(metric is always attached). SJR分区, NOT JCR (R-04). Needs a cached SJR CSV.",
    )
    parser.add_argument(
        "--min-impact",
        type=float,
        default=None,
        help="Drop papers whose OPEN journal impact (OpenAlex 2yr mean citedness) "
        "is below this. R-09: this is NOT the JCR Impact Factor; relative use only.",
    )
    parser.add_argument(
        "--journal-category",
        default=None,
        help="Pin the SJR quartile to a specific category (else the journal's best).",
    )
    parser.add_argument(
        "--sjr-csv",
        default=None,
        help="Explicit SJR CSV path (else newest in ~/.paper-search-pro/sjr/).",
    )
    parser.add_argument(
        "--no-journal-metric",
        action="store_true",
        help="Skip journal_metric enrichment entirely (slots stay None).",
    )
    parser.add_argument(
        "--no-issn-backfill",
        action="store_true",
        help="On the SS-primary path, do NOT recover missing ISSNs via free "
        "OpenAlex DOI lookups. Default is ON (so SJR quartiles are not silently "
        "lost). Turn off for large SS result sets to save per-paper OA calls; "
        "papers then stay unjoinable (journal_metric.issn_backfill_needed stays "
        "visible). No effect on the OpenAlex-primary or human path.",
    )
    parser.add_argument(
        "--verify-refs",
        metavar="FILE.json",
        default=None,
        help="ANTI-HALLUCINATION mode: instead of a topic search, read a JSON list "
        "of references (each with a 'doi' and/or 'title') and check whether each "
        "one actually EXISTS across OpenAlex / CrossRef / Semantic Scholar. Emits a "
        "per-ref ruling {ref, exists, matched_source, canonical, note} + a summary. "
        "Accepts a bare list, or {\"references\": [...]}; a bare string item is "
        "treated as a title. Ignores the query and the search flags.",
    )
    args = parser.parse_args()

    config = load_config()

    # ---- verify-refs mode (anti-hallucination) takes precedence over search ----
    if args.verify_refs is not None:
        try:
            refs = _load_refs_file(args.verify_refs)
        except FileNotFoundError:
            envelope = _error_envelope(
                AgentError(
                    "E_CONFIG",
                    f"--verify-refs file not found: {args.verify_refs}",
                    retryable=False,
                )
            )
        except Exception as exc:
            envelope = _error_envelope(
                AgentError(
                    "E_CONFIG",
                    f"could not read --verify-refs file: {exc}",
                    retryable=False,
                )
            )
        else:
            try:
                envelope = verify_references(refs, config)
            except Exception as exc:  # absolute backstop
                envelope = _error_envelope(
                    AgentError("E_INTERNAL", f"unexpected failure: {exc}", retryable=False)
                )
        json.dump(envelope, sys.stdout, default=str, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        if envelope.get("ok"):
            return 0
        code = envelope.get("error", {}).get("code", "E_INTERNAL")
        return _EXIT_FOR_CODE.get(code, 6)

    # ---- normal topic-search mode ----
    if not (args.query or "").strip():
        parser.error("a query is required unless --verify-refs is given")

    quartiles = (
        [q.strip() for q in args.quartile.split(",") if q.strip()]
        if args.quartile
        else None
    )

    try:
        envelope = run_agent_search(
            args.query,
            config,
            year_min=args.year_min,
            year_max=args.year_max,
            per_strategy=args.per_strategy,
            limit=args.limit,
            min_relevance=args.min_relevance,
            verify=args.verify,
            quartiles=quartiles,
            min_impact=args.min_impact,
            journal_category=args.journal_category,
            sjr_csv=args.sjr_csv,
            enrich_journal=not args.no_journal_metric,
            issn_backfill=not args.no_issn_backfill,
        )
    except Exception as exc:  # absolute backstop — never leak a traceback to stdout
        envelope = _error_envelope(
            AgentError("E_INTERNAL", f"unexpected failure: {exc}", retryable=False)
        )

    json.dump(envelope, sys.stdout, default=str, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")

    if envelope.get("ok"):
        return 0
    code = envelope.get("error", {}).get("code", "E_INTERNAL")
    return _EXIT_FOR_CODE.get(code, 6)


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())
