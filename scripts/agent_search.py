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
- ``journal_rank`` : the SINGLE journal layer (v2.2 collapse) — CAS 区 / JCR Q·IF
  / SJR Q + an ``openalex`` open-impact sub-slot ({mean_citedness_2yr, h_index}),
  or ``None`` when nothing joined. The legacy per-paper ``journal_metric`` key is
  retired (its data lives in journal_rank now). Enrichment audit is in
  ``meta.enrichment``; the partition-filter decision is in ``meta.rank``.
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
# Chinese supplemental sources (v2.3.0, B1): independent primary sources that emit
# the SAME UnifiedPaperEntity shape, so their results fold into federated dedup
# exactly like an openalex/ss strategy list. Explicit-flag only in the agent path
# (--with-nssd / --with-yiigle); no discipline-signal auto-routing here (§8).
from . import nssd_helper, yiigle_helper
from .federated_kg_resolver import federated_dedup, kg_to_list

# Feature A (v2.2 Wave A-2): multi-platform journal-rank intent + annotate/filter.
# journal_rank is the data layer (A-1); rank_intent parses NL queries; rank_filter
# annotates + filters the candidate pool. All additive / opt-in (R-19).
from . import journal_rank, rank_filter
from .rank_intent import parse_rank_intent

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

# CJK character class (shared source of truth): ideograph + CJK-extension +
# compatibility ranges. Used both for the mechanical zh query signal
# (``_query_has_cjk`` below reuses it) and for CJK n-gram coverage (#9). A CJK
# query has no whitespace token boundaries, so the latin ``_TOKEN_RE`` yields
# NOTHING and the heuristic score would floor at citation+recency only. We add
# character 2-grams for the CJK runs so a Chinese query is query-grounded too.
# A pure-ASCII query contains no CJK char, so ``_cjk_ngrams`` returns [] and the
# English tokenise / coverage path is byte-for-byte unchanged (R-19).
_CJK_CLASS = "㐀-䶿一-鿿豈-﫿\U00020000-\U0002ffff\U0002f800-\U0002fa1f"
_CJK_RUN_RE = re.compile(f"[{_CJK_CLASS}]+")


def _cjk_ngrams(text: Optional[str]) -> List[str]:
    """Character 2-grams over each maximal CJK run in ``text`` (a length-1 run
    yields that single char). Returns [] for any text without a CJK character, so
    the English tokenise / coverage path is completely unaffected (#9 / R-19)."""
    grams: List[str] = []
    for run in _CJK_RUN_RE.findall(text or ""):
        if len(run) == 1:
            grams.append(run)
        else:
            for i in range(len(run) - 1):
                grams.append(run[i : i + 2])
    return grams


def _tokenize_query(query: str) -> List[str]:
    """Lowercase the query, drop boolean punctuation and stopwords, keep terms
    of length >= 3 (so 'ml' survives only as 'machine'/'learning' when spelled
    out; very short tokens are noise for coverage scoring).

    A CJK query has no whitespace boundaries, so the latin token pass yields
    nothing; we additionally emit CJK character 2-grams so a Chinese query is
    query-grounded (#9). A pure-ASCII query produces no CJK grams, so its term
    list is byte-for-byte unchanged (R-19)."""
    low = (query or "").lower()
    raw = _TOKEN_RE.findall(low)
    terms = [t for t in raw if len(t) >= 3 and t not in _STOPWORDS]
    # Additive CJK support: [] for a pure-ASCII query, so the English path is intact.
    terms.extend(_cjk_ngrams(low))
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

    Latin terms match on token-set membership (substring-free, so 'cat' does not
    match 'category'). CJK n-gram terms match as substrings — CJK text has no word
    boundaries, so a Chinese query grounds via substring presence (#9). For a
    pure-ASCII query every term is latin, so this is byte-for-byte the original
    token-membership behaviour (R-19)."""
    if not terms or not text:
        return 0.0
    low = text.lower()
    text_tokens = set(_TOKEN_RE.findall(low))
    hits = 0
    for t in terms:
        if _CJK_RUN_RE.search(t):   # CJK n-gram term -> substring match
            if t in low:
                hits += 1
        elif t in text_tokens:      # latin term -> token-set membership (unchanged)
            hits += 1
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
    per_strategy_new: List[int],
    total_unique: int,
    scores: List[float],
    *,
    query_grounded: bool = True,
) -> Dict:
    """Build the heuristic saturation block.

    Args:
        per_strategy_new: count of NEW unique papers each strategy contributed,
            in strategy order.
        total_unique: total unique papers after dedup.
        scores: relevance scores of the returned papers.
        query_grounded: whether the run had groundable query terms. When False
            (e.g. a CJK query that tokenised to nothing, #9) the score
            distribution reflects only citation/recency, not topical coverage, so
            we mark it not-applicable rather than emit a misleading high/med/low.
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

    sig = {
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
    if not query_grounded:
        # #9: the score bands are meaningless without groundable terms — the score
        # only carries citation+recency then. Mark not-applicable (additive keys,
        # emitted ONLY on this non-default path -> R-19 default envelope intact).
        sig["score_distribution"] = None
        sig["score_distribution_note"] = (
            "not applicable: the query produced no groundable terms, so relevance "
            "scores reflect only citation/recency, not topical coverage."
        )
    return sig


# ===========================================================================
# Retrieval (reuses openalex_helper / ss_helper.search — no new search logic)
# ===========================================================================


def _resolve_source(config: Config, *, override: Optional[str] = None) -> Tuple[str, bool]:
    """Decide which primary source to use for this run.

    Returns (source_used, switched) where source_used is "openalex" or
    "semantic_scholar" and ``switched`` notes whether an auto-mode quota fallback
    fired.

    ``override`` (#8) is the transient --primary-source flag: when given it wins
    over ``config.primary_source`` for THIS run only (single-use, never persisted),
    letting the agent make a per-query 引擎 choice (e.g. AI decides SS for one
    query). When None the behaviour is byte-for-byte the config-driven original
    (R-19). ``config.quota_fallback`` still governs the auto path either way.

    Routing (mirrors the Wave 3b contract):
      - primary_source == "semantic_scholar" -> SS.
      - primary_source == "auto"             -> OpenAlex, but a run-mode quota
        probe may stickily fall back to SS when OA USD budget is low (and
        quota_fallback is enabled).
      - anything else (incl. "openalex")     -> OpenAlex (default, unchanged).
    """
    primary = (override or getattr(config, "primary_source", "openalex") or "openalex").lower()
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
# Language space (三轴模型 axis 2) — agent-path resolution + Chinese sources
# ===========================================================================
#
# The three orthogonal axes (22_routing_ux_design §3; both routing groups share
# this exact wording):
#   - 引擎  primary_source (openalex/SS/auto) = WHO runs the primary retrieval.
#   - 语言  search_language (auto/en/zh/both)  = WHICH sea to fish in.
#   - 补充源 supplemental sources             = per-space discipline sources.
#
# Agent-path philosophy (§8): the agent path NEVER asks and NEVER guesses. It has
# no discipline-signal detection (just like it has no PubMed/arXiv auto-routing).
# So the language axis is resolved from EXPLICIT signals only:
#   1. --lang flag          -> scope_source "flags"   (explicit; wins).
#   2. config.search_language (non-auto) -> "config"  (silently adopted, §8).
#   3. auto:
#        3a. no CJK in query -> en, "query_passthrough", not ambiguous
#            (this is the byte-identical current behaviour — R-19).
#        3b. CJK in query    -> zh, "query_passthrough", ambiguous=True
#            (Chinese query hitting OpenAlex/SS already returns Chinese results —
#             the agent version of "问一句" is to pass through + flag the ambiguity
#             in meta.language so the caller, who has context, decides whether to
#             re-run with an explicit --lang. §5.1 4b / §8).
# Supplemental Chinese sources (NSSD 社科 / yiigle 医学) are added ONLY by explicit
# --with-nssd / --with-yiigle (§8: 补充源只认显式 flag). A --with-* on an en scope
# upgrades it to both, so the Chinese query actually reaches the Chinese source
# (§6.6, agent form) — reported via meta.language + a warning.

# CJK / CJK-extension / compatibility-ideograph ranges — a query carrying any of
# these is "Chinese" for the mechanical query_lang signal (matches detect_language
# discipline: script detection is mechanical, everything else is caller judgement).
_CJK_RE = re.compile(f"[{_CJK_CLASS}]")


def _query_has_cjk(text: Optional[str]) -> bool:
    """True when the query contains a CJK ideograph (the mechanical zh signal)."""
    return bool(_CJK_RE.search(text or ""))


@dataclass
class _LanguagePlan:
    """Resolved language axis for one agent run (post precedence-merge)."""

    query_lang: str = "en"          # zh | en — mechanical CJK detection
    scope_used: str = "en"          # en | zh | both
    scope_source: str = "query_passthrough"  # flags | config | query_passthrough
    ambiguous: bool = False         # auto + Chinese query + no explicit signal
    chinese_sources: List[str] = None  # sources to actually query (--with-*)
    engaged: bool = False           # whether the language feature is active at all
    upgraded_en_to_both: bool = False


def _resolve_language(
    query: str,
    config: Config,
    *,
    lang_flag: Optional[str],
    with_nssd: bool,
    with_yiigle: bool,
) -> _LanguagePlan:
    """Resolve the language axis from explicit signals only (agent path never asks).

    ``engaged`` is False ONLY on the fully-default path (English query, no --lang,
    no --with-*, config auto) — in which case the caller must NOT emit meta.language
    so the envelope stays byte-identical to v2.2 (R-19)."""
    query_lang = "zh" if _query_has_cjk(query) else "en"
    config_lang = (getattr(config, "search_language", "auto") or "auto").lower()
    if config_lang not in ("auto", "en", "zh", "both"):
        config_lang = "auto"

    plan = _LanguagePlan(query_lang=query_lang, chinese_sources=[])

    if lang_flag:                       # 1. explicit flag wins
        plan.scope_used = lang_flag
        plan.scope_source = "flags"
    elif config_lang != "auto":         # 2. persisted config value, silently adopted
        plan.scope_used = config_lang
        plan.scope_source = "config"
    else:                               # 3. auto
        plan.scope_source = "query_passthrough"
        if query_lang == "en":          # 3a — byte-identical current behaviour (R-19)
            plan.scope_used = "en"
        else:                           # 3b — Chinese query, no signal: pass through + flag
            plan.scope_used = "zh"
            plan.ambiguous = True

    # --with-* select the Chinese supplemental sources (explicit only, §8).
    if with_nssd:
        plan.chinese_sources.append("nssd")
    if with_yiigle:
        plan.chinese_sources.append("yiigle")

    # A --with-* on an en scope needs zh present — upgrade en -> both (§6.6).
    if plan.chinese_sources and plan.scope_used == "en":
        plan.scope_used = "both"
        plan.upgraded_en_to_both = True

    # The language feature is "engaged" whenever any explicit signal or a Chinese
    # query is present. Only the fully-default path leaves it off (R-19: no
    # meta.language key, byte-identical envelope).
    plan.engaged = bool(
        lang_flag
        or with_nssd
        or with_yiigle
        or config_lang != "auto"
        or query_lang == "zh"
    )
    return plan


def _retrieve_chinese(
    query: str,
    chinese_sources: List[str],
    *,
    year_min: Optional[int],
    year_max: Optional[int],
    n: int,
) -> Tuple[List[List[UnifiedPaperEntity]], List[str]]:
    """Query the explicit Chinese supplemental sources and return their result
    lists (one per source) for federated dedup, plus warnings.

    Each helper (nssd_helper / yiigle_helper, B1) is an independent primary source
    emitting the SAME UnifiedPaperEntity shape, so its list folds into
    _dedup_with_yield exactly like an openalex/ss strategy. Every helper degrades
    gracefully (never raises); we still guard per source so one failing source
    never kills the run.

    #6: the Chinese helpers only accept ``year_min`` (their forms expose no
    reliable year-max param), so we apply the recency CEILING client-side here —
    otherwise a Chinese source would ignore ``--year-max`` while the primary engine
    honours it. A paper is kept when its year is unknown OR <= year_max (we only
    drop papers we can PROVE exceed the ceiling; unknown-year records are left for
    the caller to judge, matching how the primary engines surface them)."""
    results: List[List[UnifiedPaperEntity]] = []
    warnings: List[str] = []
    for src in chinese_sources:
        try:
            if src == "nssd":
                batch = nssd_helper.search(query, n=n, year_min=year_min)
            elif src == "yiigle":
                batch = yiigle_helper.search(query, n=n, year_min=year_min)
            else:  # pragma: no cover - guarded by the flag parser
                continue
        except Exception as exc:  # helpers shouldn't raise, but never let one kill the run
            warnings.append(f"{src} search failed: {exc}")
            batch = []
        if year_max is not None:
            batch = [p for p in batch if p.year is None or p.year <= year_max]
        if not batch:
            warnings.append(f"{src} returned 0 papers.")
        results.append(list(batch))
    return results, warnings


def _language_meta(plan: _LanguagePlan) -> Dict:
    """The additive ``meta.language`` block (§8). Only attached when the language
    feature is engaged (never on the byte-identical default path — R-19)."""
    return {
        "query_lang": plan.query_lang,          # zh | en (mechanical CJK detection)
        "scope_used": plan.scope_used,          # en | zh | both
        "scope_source": plan.scope_source,      # flags | config | query_passthrough
        # ambiguous=True is the agent version of the human path's "问一句": auto +
        # a Chinese query with no explicit --lang/config signal. The caller (which
        # has context the CLI does not) decides whether to re-run with --lang.
        "ambiguous": plan.ambiguous,
        "chinese_sources_used": list(plan.chinese_sources or []),
    }


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
# Journal-rank intent resolution (Feature A, Wave A-2)
# ===========================================================================
#
# Resolution precedence (spec §7 — explicit flags win, then NL intent, then the
# config default which only LABELS, never FILTERS):
#   1. explicit flags (--rank-platform / --keep-tiers) — caller meant exactly this.
#   2. NL intent parsed from the query ("中科院一区" -> cas tier 1) — the bug fix.
#   3. config rank.default_platform (factory jcr) — label every paper with this
#      platform's slot but DO NOT filter (no tier was requested).
# A bare "Q1" with no platform stays ambiguous: we DO NOT pick a platform; the
# envelope flags it so the calling agent asks the user (spec §7, CLI is non-
# interactive).


@dataclass
class _RankPlan:
    """The resolved journal-rank intent for one run (post precedence-merge)."""

    platform: Optional[str] = None  # cas | jcr | sjr | None
    tiers: Optional[List[int]] = None  # CAS 区 numbers
    quartiles: Optional[List[str]] = None  # JCR/SJR quartiles
    top: bool = False
    category: Optional[str] = None  # pin a sub-category (CAS 小类 / SJR/JCR category)
    ambiguous: bool = False  # quartile/tier stated but no platform resolvable
    candidate_platforms: List[str] = None  # for an ambiguous bare quartile
    cleaned_query: str = ""  # query with rank phrasing stripped (the bug fix)
    source: str = "none"  # flags | intent | default | none — how we resolved
    applied_filter: bool = False  # whether a tier/quartile/top filter is active
    intent_matched: List[str] = None  # raw phrases the parser stripped


def _resolve_rank_plan(
    query: str,
    config: Config,
    *,
    rank_platform: Optional[str],
    keep_tiers: Optional[List],
    rank_category: Optional[str],
) -> _RankPlan:
    """Merge explicit flags + NL intent + config default into one _RankPlan.

    The cleaned_query is ALWAYS the intent parser's stripped topic so the rank
    phrasing never reaches the search engine (the "中科院一区 被当检索词" fix), even
    when the platform itself came from an explicit flag."""
    intent = parse_rank_intent(query)
    plan = _RankPlan(
        cleaned_query=intent.cleaned_query or query,
        candidate_platforms=[],
        intent_matched=list(intent.matched),
    )

    # ---- 1. explicit flags take precedence ----
    if rank_platform:
        plan.platform = rank_platform.lower()
        plan.source = "flags"
        tiers, quarts = rank_filter.normalize_keep_tiers(plan.platform, keep_tiers or [])
        if plan.platform == "cas":
            plan.tiers = tiers or None
        else:
            plan.quartiles = quarts or None
        plan.category = rank_category
        plan.applied_filter = bool(plan.tiers or plan.quartiles)
        return plan

    # A keep-tiers flag with no platform flag: still ambiguous unless intent or
    # default resolves a platform. Stash it and fall through.
    flag_keep = keep_tiers or []

    # ---- 2. NL intent ----
    if intent.platform:
        plan.platform = intent.platform
        plan.source = "intent"
        plan.tiers = intent.tiers
        plan.quartiles = intent.quartiles
        plan.top = intent.top
        plan.category = rank_category
        # A keep-tiers flag refines/overrides the intent's tier list on the same
        # platform (explicit flag detail beats parsed phrasing).
        if flag_keep:
            tiers, quarts = rank_filter.normalize_keep_tiers(plan.platform, flag_keep)
            if plan.platform == "cas":
                plan.tiers = tiers or plan.tiers
            else:
                plan.quartiles = quarts or plan.quartiles
        plan.applied_filter = bool(plan.tiers or plan.quartiles or plan.top)
        return plan

    # Intent expressed a tier/quartile/top but no platform -> ambiguous.
    if intent.has_filter and intent.ambiguous:
        plan.ambiguous = True
        plan.quartiles = intent.quartiles
        plan.top = intent.top
        plan.source = "intent"
        plan.candidate_platforms = getattr(intent, "candidate_platforms", None) or ["jcr", "sjr"]
        # Do NOT apply a filter without a resolved platform; only label on default.

    # ---- 3. config default platform (labels only, never filters) ----
    default_platform = "jcr"
    rank_cfg = getattr(config, "rank", None)
    if isinstance(rank_cfg, dict) and rank_cfg.get("default_platform"):
        default_platform = str(rank_cfg["default_platform"]).lower()
    if default_platform not in journal_rank.PLATFORMS:
        default_platform = "jcr"
    plan.platform = default_platform
    if plan.source == "none":
        plan.source = "default"
    plan.category = rank_category
    # The default platform NEVER auto-filters (spec §7: 不提分区 → 不过滤). A bare
    # keep-tiers flag against the default platform DOES filter, though (the user
    # asked for tiers, just didn't name a platform — apply to the default).
    if flag_keep and not plan.ambiguous:
        tiers, quarts = rank_filter.normalize_keep_tiers(plan.platform, flag_keep)
        if plan.platform == "cas":
            plan.tiers = tiers or None
        else:
            plan.quartiles = quarts or None
        plan.applied_filter = bool(plan.tiers or plan.quartiles)
        plan.source = "flags"
    return plan


def _rank_cache_dir(config: Config):
    """Resolve the journal_rank cache dir from config (else built-in default)."""
    rank_cfg = getattr(config, "rank", None)
    if isinstance(rank_cfg, dict) and rank_cfg.get("cache_dir"):
        from pathlib import Path

        return Path(str(rank_cfg["cache_dir"])).expanduser()
    return None


def _rank_sources(config: Config):
    """Resolve the journal_rank mirror sources from config (else None=built-ins)."""
    rank_cfg = getattr(config, "rank", None)
    if isinstance(rank_cfg, dict) and isinstance(rank_cfg.get("sources"), dict):
        return rank_cfg["sources"]
    return None


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
    flattening Author objects. The relevance / journal_rank / verify blocks are
    attached by the caller after scoring.

    NOTE: the entity's ``journal_rank`` dataclass and the legacy ``journal_metric``
    field are dropped here. The caller re-attaches a fully-serialised ``journal_rank``
    dict (the single multi-platform layer); the legacy ``journal_metric`` slot is no
    longer emitted (v2.2 single-layer collapse — its SJR quartile + OpenAlex impact
    now live inside ``journal_rank``)."""
    d: Dict = {}
    for f, v in p.__dict__.items():
        if f == "authors":
            d[f] = [a.__dict__ for a in v]
        elif f in ("journal_metric", "journal_rank"):
            continue  # journal_metric: retired; journal_rank: re-attached as a dict
        else:
            d[f] = v
    return d


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
    rank_platform: Optional[str] = None,
    keep_tiers: Optional[List] = None,
    rank_category: Optional[str] = None,
    deepen_target: Optional[int] = None,
    max_deepen_rounds: int = 3,
    lang: Optional[str] = None,
    with_nssd: bool = False,
    with_yiigle: bool = False,
    primary_source: Optional[str] = None,
    now_year: int = _CURRENT_YEAR,
) -> Dict:
    """Run the full deterministic agent pipeline and return the envelope dict.

    Never raises: any failure is converted to an error envelope. The relevance
    score is ALWAYS computed for every returned paper (B-2) — ``min_relevance``
    only filters which papers are returned, it does not disable scoring.

    Feature A journal RANK (v2.2, SINGLE layer): when ``enrich_journal`` is True
    (default) and journal-rank CSVs are cached, each paper's ``journal_rank`` slot
    is filled with the unified multi-platform record — CAS 区 / JCR Q·IF / SJR Q
    plus an ``openalex`` OPEN-impact sub-slot ({mean_citedness_2yr, h_index}). This
    is the ONE journal layer; the legacy SJR-only ``journal_metric`` slot is no
    longer populated or emitted (its SJR quartile + OpenAlex impact now live inside
    journal_rank). Pure additive — with no CSVs cached and no impact reachable the
    slot stays None, exactly as before.

    - ``quartiles`` (e.g. ["Q1","Q2"], the --quartile flag) and ``min_impact``
      (--min-impact) are OPT-IN filters, BOTH sourced from journal_rank now:
      ``quartiles`` matches ``journal_rank.sjr.best_quartile`` and ``min_impact``
      gates ``journal_rank.openalex.mean_citedness_2yr`` (an OPEN impact figure,
      NOT a JCR Impact Factor — R-09). Like ``min_relevance`` they only filter
      *which* papers are returned; the record is always attached.
    - ``sjr_csv`` is DEPRECATED (the legacy sjr_helper SJR-only path is retired);
      it is accepted but ignored. Use ``journal_rank fetch`` to cache SJR data into
      ~/.paper-search-pro/ranks/.

    ``issn_backfill`` (default True) only affects the SEMANTIC-SCHOLAR-primary
    path: SS records often lack an ISSN, so by default each relevance-survivor
    that has a DOI but no ISSN gets a free single-paper OpenAlex lookup to recover
    it (so the journal_rank join is not silently lost). Set it False to skip those
    per-paper lookups on large SS result sets — papers then stay unjoinable (the
    ``meta.enrichment.issn_backfill_*`` audit keeps the gap visible). No effect on
    the OpenAlex path or the human path.

    Multi-platform journal RANK partition filtering:
    - ``rank_platform`` ("cas"|"jcr"|"sjr"): the platform to FILTER on this run.
      When None, the platform is taken from the query's NL intent ("中科院一区" ->
      cas) and otherwise from config ``rank.default_platform`` (factory jcr, which
      only LABELS — never filters).
    - ``keep_tiers``: tiers/quartiles to KEEP (ints/["1","2"]/["Q1","Q2"]), mapped
      onto the chosen platform's taxonomy. Opt-in: with none given every paper is
      labelled with all three platforms but nothing is filtered.
    - ``rank_category``: pin a sub-category for the quartile/区 (CAS 小类 etc).
    - NL intent is ALWAYS parsed so the rank phrasing is stripped from the topic
      before search (the "中科院一区 被当检索词" bug fix), regardless of flags.
    - When a tier filter is active and survivors fall short of ``deepen_target``
      (default = ``limit`` or 10), the search ADAPTIVELY DEEPENS: it re-retrieves
      at greater depth and re-filters the same annotated pool until the target is
      met or the pool saturates (spec §6). Switching platform/tier later is just a
      re-filter of the annotated pool — no re-search (spec §7).
    - A bare quartile with no platform ("Q1") is AMBIGUOUS: the envelope flags it
      (``meta.rank.ambiguous``) for the calling agent to ask the user; the CLI
      itself never guesses a platform.

    Language axis (三轴模型 axis 2 — additive, §8):
    - ``lang`` ("en"|"zh"|"both"|None): the language SPACE to search. Explicit wins
      (scope_source "flags"); None falls to config ``search_language`` (non-auto
      adopted silently, "config") then auto (English query -> en; Chinese query ->
      zh passthrough flagged ``ambiguous`` in ``meta.language``). The agent path
      NEVER asks/guesses — it passes the query through and reports the ambiguity for
      the caller (which has context) to resolve.
    - ``with_nssd`` / ``with_yiigle``: also query the Chinese supplemental sources
      (NSSD 社科 / yiigle 医学) and MERGE their results into the candidate pool
      (federated dedup). Explicit only (§8: 补充源只认显式 flag). A --with-* on an en
      scope upgrades it to 'both' so the Chinese query reaches the source (§6.6).
    - ``meta.language`` (query_lang / scope_used / scope_source / ambiguous /
      chinese_sources_used) is emitted ONLY when the language feature is engaged; the
      fully-default English path never emits it, keeping the envelope byte-identical
      to v2.2 (R-19). For a Chinese query the FLOOR relevance score is now CJK-aware
      (#9: character 2-gram coverage) so a zh query is query-grounded; the caller can
      still layer its own semantic judgement (see agent_mode.md).

    Engine axis (三轴模型 axis 1 — additive):
    - ``primary_source`` ("openalex"|"semantic_scholar"|"auto"|None): the transient
      --primary-source flag (#8). When given it OVERRIDES ``config.primary_source``
      for THIS run only (single-use, never persisted), so the agent can make a
      per-query 引擎 choice (e.g. force SS for one query the AI judged SS-better).
      None => the config-driven routing, byte-for-byte unchanged (R-19). SS-as-
      primary still requires a key (E_CONFIG otherwise, R-06).
    """
    warnings: List[str] = []

    if not (query or "").strip():
        return _error_envelope(
            AgentError("E_CONFIG", "query is empty", retryable=False)
        )

    # ---- Journal-rank intent: resolve platform/tiers + strip rank phrasing -----
    # ALWAYS parse intent so the rank phrasing never reaches the search engine
    # (the bug fix). When the query carries no rank phrasing, cleaned_query ==
    # query and the platform falls to the config default (label-only, no filter),
    # so the default path is byte-identical to before (R-19).
    rank_plan = _resolve_rank_plan(
        query, config,
        rank_platform=rank_platform, keep_tiers=keep_tiers, rank_category=rank_category,
    )
    search_query = rank_plan.cleaned_query or query

    # ---- Language axis (三轴模型 axis 2) — resolve scope + Chinese sources -------
    # Explicit signals only (agent path never asks/guesses, §8). On the fully
    # default path (English query, no --lang, no --with-*, config auto) lang_plan
    # .engaged is False -> meta.language is NOT emitted -> envelope byte-identical
    # to v2.2 (R-19). Chinese supplemental sources are added ONLY via --with-*.
    lang_plan = _resolve_language(
        query, config, lang_flag=lang, with_nssd=with_nssd, with_yiigle=with_yiigle,
    )
    if lang_plan.upgraded_en_to_both:
        warnings.append(
            "--with-nssd/--with-yiigle requested a Chinese source on an en scope; "
            "scope upgraded to 'both' so the query reaches the Chinese source (§6.6)."
        )
    # #1: a Chinese query resolved to an en scope (via --lang en or config
    # search_language=en) means the agent path searches the CJK string VERBATIM
    # against English-language indexes and does NOT translate (headless: no LLM in
    # the loop). Warn so the caller supplies English terms itself instead of
    # silently getting near-empty results under a scope_used:en label. (Only fires
    # when no Chinese source was added — a --with-* upgrades en -> both, so the
    # query does reach a Chinese source and the warning would be moot.)
    if lang_plan.query_lang == "zh" and lang_plan.scope_used == "en":
        warnings.append(
            "CJK query under en scope: the agent path does not translate in "
            "headless mode — pass English terms yourself (or use --lang zh / a "
            "Chinese source via --with-nssd/--with-yiigle)."
        )

    terms = _tokenize_query(search_query)

    # ---- Source routing (+ auto-mode quota fallback) ----
    # #8: ``primary_source`` (the --primary-source flag) transiently overrides
    # config.primary_source for this run only when given; None => config-driven
    # routing, byte-for-byte unchanged (R-19).
    try:
        source_used, switched = _resolve_source(config, override=primary_source)
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

    # ---- Retrieve (on the CLEANED query so rank phrasing never reaches search) --
    # ``search_query`` == ``query`` when no rank phrasing was present (R-19). When a
    # tier filter is active and survivors fall short, the deepening loop below
    # re-retrieves at greater depth — but the FIRST pass is identical to the
    # non-rank path, so the default behaviour is unchanged.
    cur_per_strategy = per_strategy
    strategy_results, retr_warnings = _retrieve(
        search_query, source_used, year_min=year_min, year_max=year_max,
        per_strategy=cur_per_strategy,
    )
    warnings.extend(retr_warnings)

    # ---- Chinese supplemental sources (agent path: explicit --with-* only) -------
    # Each is an independent primary source in the same UnifiedPaperEntity shape, so
    # its result list is just one more strategy list feeding federated dedup. Empty
    # (no --with-*) => zero change to strategy_results => R-19 default path intact.
    # The Chinese sources have no depth knob, so we keep their lists constant across
    # any adaptive-deepening rounds below (re-appended on every re-dedup).
    chinese_results: List[List[UnifiedPaperEntity]] = []
    if lang_plan.chinese_sources:
        chinese_results, cn_warn = _retrieve_chinese(
            search_query, lang_plan.chinese_sources, year_min=year_min,
            year_max=year_max, n=cur_per_strategy,
        )
        warnings.extend(cn_warn)
        strategy_results = strategy_results + chinese_results

    # ---- Dedup + per-strategy yield ----
    unique, per_strategy_new, retrieved_raw = _dedup_with_yield(strategy_results)

    if not unique:
        meta = {
            "query": {
                "topic": query,
                "search_query": search_query,
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
        if lang_plan.engaged:
            meta["language"] = _language_meta(lang_plan)
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

    # ---- Journal-rank load (Feature A, Wave A-2; cache-first, no network) -------
    # Load the unified CAS/JCR/SJR table from the local cache (NEVER fetched here —
    # fetch is an explicit user/init action). None => graceful degradation: papers
    # get no 分区 labels (the OpenAlex open impact can still attach to an
    # openalex-only journal_rank) and a tier filter cannot be honoured (reported in
    # meta.rank).
    # The "no data cached — run fetch" note is ONLY surfaced when the user actually
    # asked for partitions (an explicit platform/tier flag, or NL intent like
    # "中科院一区", or a bare-quartile ambiguity). A plain default search never asked
    # for 分区, so it must NOT be nagged about fetching them (D3-P1 first-use fix).
    partition_requested = (
        rank_plan.source in ("flags", "intent")
        or rank_plan.applied_filter
        or rank_plan.ambiguous
        or bool(quartiles)
        or (min_impact is not None)
    )
    rank_lookup = None
    rank_load_note = None
    if enrich_journal:
        try:
            rank_lookup = journal_rank.load(cache_dir=_rank_cache_dir(config))
        except Exception as exc:  # never let a bad cache crash the search
            rank_lookup = None
            rank_load_note = f"journal_rank load failed: {exc}"
        if rank_lookup is None and rank_load_note is None and partition_requested:
            rank_load_note = (
                "no journal-rank data cached — 分区/quartile labels & filters "
                "unavailable. Run `python3 -m scripts.journal_rank fetch` "
                "(one-time, no API key needed; data lands in ~/.paper-search-pro/"
                "ranks/) to enable CAS/JCR/SJR partitions."
            )

    # ---- Adaptive deepening (spec §6) — only when a tier/quartile filter is on --
    # The cheap deterministic rank filter runs BEFORE expensive scoring. If the
    # annotated pool yields fewer survivors than the target, re-retrieve at greater
    # depth and re-filter the SAME pool until the target is met or the search
    # saturates (a deepen round that adds no new papers). High 区 ↔ high citations
    # (r≈0.96), so the citation-sorted strategy floats survivors up fast; we keep
    # the existing multi-strategy retrieval and just grow the depth.
    deepen_rounds = 0
    deepen_saturated = False
    rank_filter_active = (
        rank_plan.applied_filter and rank_lookup is not None and not rank_plan.ambiguous
    )
    if rank_filter_active:
        target = deepen_target if deepen_target is not None else (limit or 10)
        # Annotate the current pool and count survivors of the rank filter.
        rank_filter.annotate_papers(unique, rank_lookup)
        kept_now, _dropped, _nodata = rank_filter.filter_by_rank(
            unique, rank_plan.platform,
            tiers=rank_plan.tiers, quartiles=rank_plan.quartiles, top=rank_plan.top,
            category=rank_plan.category,
        )
        while (
            len(kept_now) < target
            and deepen_rounds < max_deepen_rounds
            and source_used == "openalex"  # SS search() has no depth knob (one shot)
        ):
            prev_unique = len(unique)
            cur_per_strategy *= 2  # grow retrieval depth one level
            deepen_rounds += 1
            more_results, more_warn = _retrieve(
                search_query, source_used, year_min=year_min, year_max=year_max,
                per_strategy=cur_per_strategy,
            )
            warnings.extend(more_warn)
            # Re-dedup the deeper superset (deterministic sorts => stable superset).
            # Chinese sources have no depth knob, so re-append their constant lists
            # so they survive the deeper re-dedup (no-op when --with-* was not used).
            new_unique, new_psn, new_raw = _dedup_with_yield(more_results + chinese_results)
            unique, per_strategy_new, retrieved_raw = new_unique, new_psn, new_raw
            if len(unique) <= prev_unique:
                deepen_saturated = True  # deeper crawl added nothing new
                break
            rank_filter.annotate_papers(unique, rank_lookup)
            kept_now, _dropped, _nodata = rank_filter.filter_by_rank(
                unique, rank_plan.platform,
                tiers=rank_plan.tiers, quartiles=rank_plan.quartiles, top=rank_plan.top,
                category=rank_plan.category,
            )
        if len(kept_now) < target and not deepen_saturated:
            deepen_saturated = deepen_rounds >= max_deepen_rounds
    elif rank_lookup is not None and enrich_journal:
        # No filter, but data is loaded: still LABEL the whole pool (spec §7:
        # 不提分区 → 不过滤, only label). Annotation is network-free + idempotent.
        rank_filter.annotate_papers(unique, rank_lookup)

    # ---- Score (ALWAYS, B-2) + journal_rank enrichment + optional verify --------
    scored: List[Tuple[UnifiedPaperEntity, Dict]] = []
    for p in unique:
        rel = compute_relevance(p, terms, now_year=now_year)
        scored.append((p, rel))

    # Sort. Default: heuristic relevance (desc), tie-break on citation_count.
    # With a tier/quartile filter active (spec §6) prefer CITATION order — high 区
    # ↔ high citations (r≈0.96), so citation-first surfaces high-partition papers
    # fastest with the least over-fetching; relevance is the tie-break there.
    if rank_filter_active:
        scored.sort(
            key=lambda pr: (pr[0].citation_count or 0, pr[1]["score"]), reverse=True
        )
    else:
        scored.sort(key=lambda pr: (pr[1]["score"], pr[0].citation_count or 0), reverse=True)

    # Filter by min_relevance (signal-as-knob: filtering is opt-in, scoring is not).
    # #9: when the query produced no groundable terms (e.g. a CJK query that
    # tokenised to nothing), the score is not query-grounded — every paper floors at
    # citation+recency, so a nonzero --min-relevance would wrongly filter the whole
    # (zh) pool to empty. Guard by treating min_relevance as 0 when terms is empty.
    # Default English path always has terms, so effective_min == min_relevance and
    # this comprehension is byte-for-byte the original (R-19).
    effective_min = min_relevance if terms else 0.0
    kept = [(p, rel) for (p, rel) in scored if rel["score"] >= effective_min]
    after_relevance_filter = len(kept)

    # ---- Journal-rank enrichment (Feature A, single layer) + opt-in filtering ----
    # The multi-platform journal_rank record (CAS/JCR/SJR + an OpenAlex open-impact
    # slot) is the ONE journal layer — the legacy SJR-only journal_metric path is
    # retired (no sjr_helper load here; no per-paper journal_metric in the envelope).
    # We enrich the relevance-survivors (not the whole dedup pool) since the OpenAlex
    # impact lookup is per-ISSN. ``quartiles`` (--quartile) and ``min_impact``
    # (--min-impact) are OPT-IN filters, now BOTH sourced from journal_rank: SJR
    # best_quartile and the OpenAlex open impact respectively.

    # OpenAlex open-impact lookup (CC0) is only meaningful on the OpenAlex path (and
    # after an SS-primary ISSN backfill, below). SS-primary runs otherwise skip it.
    impact_lookup = None
    if enrich_journal and source_used == "openalex":
        impact_lookup = openalex_helper.get_source_impact

    # ---- SS-primary ISSN backfill (R-08) ----
    # SS records carry ISSN only in publicationVenue.issn (~2/3 coverage). For the
    # relevance-survivors that lack an ISSN but have a DOI, do a FREE single-paper
    # OpenAlex lookup to backfill source.issn so the journal_rank join is not
    # silently lost. Papers with no DOI remain unjoinable (the audit counts keep
    # that gap visible). Per-paper try/except: a failed lookup never crashes the
    # search and never forces a switch — it just leaves that paper unjoined.
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
            # A backfilled ISSN makes the OpenAlex open-impact figure reachable for
            # those journals; enable the (CC0) impact lookup so SS papers do not lose
            # impact relative to the OpenAlex path.
            if issn_backfilled and impact_lookup is None:
                impact_lookup = openalex_helper.get_source_impact

    # ---- Annotate the relevance-survivors with platform data (network-free) ----
    # Re-annotate here so any SS-primary ISSN backfilled above is now joinable.
    # Switching platform/tier later is a pure re-filter of this annotated pool —
    # NO re-search (spec §7).
    if enrich_journal and rank_lookup is not None:
        rank_filter.annotate_papers([p for (p, _r) in kept], rank_lookup)

    # ---- Attach OpenAlex open impact (CC0) into journal_rank.openalex ----
    # The open-impact figure now lives INSIDE the single journal_rank record
    # (replacing the retired journal_metric impact slot). For a paper not joined to
    # any platform we still create an openalex-only journal_rank so the figure is not
    # lost. R-04/R-09: ``mean_citedness_2yr`` is an OPEN impact figure, never an IF.
    impact_attached = 0
    impact_source = None
    if enrich_journal and impact_lookup is not None:
        impact_cache: Dict[str, object] = {}
        for p, _rel in kept:
            issn = getattr(p, "issn", None)
            if not issn:
                continue
            if issn not in impact_cache:
                try:
                    impact_cache[issn] = impact_lookup(issn)
                except Exception:
                    impact_cache[issn] = None
            imp = impact_cache[issn]
            if not imp:
                continue
            mc = imp.get("two_year_mean_citedness")
            h = imp.get("h_index")
            if mc is None and h is None:
                continue
            oa_slot = {
                "mean_citedness_2yr": mc,
                "h_index": int(h) if isinstance(h, (int, float)) else None,
            }
            jr = getattr(p, "journal_rank", None)
            if jr is None:
                jr = journal_rank.JournalRank()
                p.journal_rank = jr
            jr.openalex = oa_slot
            impact_attached += 1
        if impact_attached:
            impact_source = "openalex_summary_stats"

    # ---- Opt-in --quartile / --min-impact filters (now sourced from journal_rank) -
    want_quartiles = {q.upper() for q in (quartiles or []) if q}
    apply_journal_filter = bool(want_quartiles) or (min_impact is not None)

    def _passes_journal_filter(p) -> bool:
        if not apply_journal_filter:
            return True
        jr = getattr(p, "journal_rank", None)
        if want_quartiles:
            sjr_slot = getattr(jr, "sjr", None) if jr is not None else None
            q = getattr(sjr_slot, "best_quartile", None) if sjr_slot is not None else None
            if q not in want_quartiles:
                return False
        if min_impact is not None:
            oa = getattr(jr, "openalex", None) if jr is not None else None
            val = oa.get("mean_citedness_2yr") if isinstance(oa, dict) else None
            if val is None or val < min_impact:
                return False
        return True

    if apply_journal_filter:
        kept = [(p, rel) for (p, rel) in kept if _passes_journal_filter(p)]
    after_journal_filter = len(kept)

    # ---- Multi-platform journal RANK tier/quartile filter (--rank-platform) ------
    # (CAS/JCR/SJR 分区 layer.) Pure re-filter of the already-annotated pool:
    # switching platform/tier == calling this again, NO re-search (spec §7).
    rank_kept_count = None
    rank_filtered_count = None
    rank_nodata_count = None
    if enrich_journal and rank_lookup is not None and rank_filter_active:
        survivors, dropped, nodata = rank_filter.filter_by_rank(
            [p for (p, _r) in kept], rank_plan.platform,
            tiers=rank_plan.tiers, quartiles=rank_plan.quartiles, top=rank_plan.top,
            category=rank_plan.category,
        )
        survivor_ids = {id(p) for p in survivors}
        rank_kept_count = len(survivors)
        rank_filtered_count = len(dropped)
        rank_nodata_count = len(nodata)
        # No-platform-data papers are EXCLUDED from a tier filter but COUNTED
        # (spec §2: 无该平台分区数据的论文单独标记，不静默丢).
        kept = [(p, rel) for (p, rel) in kept if id(p) in survivor_ids]

    after_rank_filter = len(kept)

    after_filter = after_relevance_filter  # back-compat name (relevance stage)
    if limit is not None and limit >= 0:
        kept = kept[:limit]

    data: List[Dict] = []
    verifies: List[Dict] = []
    for p, rel in kept:
        d = _paper_to_dict(p)
        # #17: paper_id is a @property (not in __dict__), so _paper_to_dict never
        # serialises it; downstream joins (rcs_rubric / classifier) key on it. Emit
        # it explicitly — but ONLY when the language feature is engaged. R-19:
        # adding a key to every paper on the default English path would break the
        # byte-identical default envelope, and there paper_id is trivially
        # reconstructable (every paper exposes a directly-readable doi/openalex_id
        # as the top priority). The NON-obvious paper_id — a NSSD/yiigle record
        # whose id falls back to source_native_id — only ever occurs in an engaged
        # envelope, which is exactly where we surface the explicit join key.
        if lang_plan.engaged:
            d["paper_id"] = p.paper_id
        d["relevance"] = rel
        # SINGLE journal layer (v2.2 collapse): the unified journal_rank dict
        # (CAS/JCR/SJR + OpenAlex open impact, spec §3) or None when the journal
        # joined no platform and had no reachable open impact. No separate
        # journal_metric key is emitted any more (it was a per-paper SJR double).
        d["journal_rank"] = rank_filter.journal_rank_dict(getattr(p, "journal_rank", None))
        if verify:
            v = _verify_paper(p)
            d["verify"] = v
            verifies.append(v)
        data.append(d)

    all_scores = [rel["score"] for (_p, rel) in scored]
    # #10: the Chinese supplemental source lists are appended AFTER the primary
    # strategies, so per_strategy_new's tail entries are Chinese-source yields —
    # per_strategy_new[-1] would then measure a Chinese source, not the primary
    # engine's last strategy. The marginal-yield saturation signal is about the
    # PRIMARY engine's strategy decay (the Chinese sources have no depth knob), so
    # compute it on the primary strategies only. n_chinese==0 on the default path,
    # so primary_psn == per_strategy_new and this is byte-for-byte unchanged (R-19).
    n_chinese = len(chinese_results)
    primary_psn = per_strategy_new[:-n_chinese] if n_chinese else per_strategy_new
    # #9: mark the score distribution not-applicable when there were no groundable
    # terms (bool(terms) is always True on the English default path -> unchanged).
    saturation = _saturation_signal(
        primary_psn, len(unique), all_scores, query_grounded=bool(terms)
    )
    if n_chinese:
        saturation["excludes_chinese_sources"] = True
        saturation["chinese_sources_note"] = (
            "Marginal-yield saturation is computed on the PRIMARY engine strategies "
            "only; the Chinese supplemental sources (no depth knob) are excluded "
            "from this signal, though they DO contribute to counts and returned "
            "data (see counts.retrieved_raw_chinese, #10/#11)."
        )

    # ---- Build the meta.rank block (Feature A, Wave A-2) -----------------------
    rank_attribution = None
    switchable = []
    if rank_lookup is not None:
        switchable = list(rank_lookup.loaded_platforms)
        if rank_plan.platform in journal_rank.ATTRIBUTION:
            rank_attribution = journal_rank.ATTRIBUTION.get(rank_plan.platform)
    # D2 hint: bare numeric --keep-tiers with no --rank-platform are read as the
    # DEFAULT platform's quartiles (factory jcr), which surprises users thinking in
    # 中科院 "区". Surface a clear, deterministic note when that mapping happened.
    keep_tiers_note = None
    if (
        rank_platform is None
        and keep_tiers
        and rank_plan.source == "flags"
        and rank_plan.platform in ("jcr", "sjr")
        and rank_plan.quartiles
    ):
        bare = [str(t).strip() for t in keep_tiers if str(t).strip().isdigit()]
        if bare:
            keep_tiers_note = (
                f"--keep-tiers {','.join(bare)} had no --rank-platform, so the bare "
                f"numbers were read as {rank_plan.platform.upper()} quartiles "
                f"{','.join(rank_plan.quartiles)} (the default platform). For 中科院 "
                f"区 pass --rank-platform cas."
            )
    rank_meta = {
        "platform": rank_plan.platform,
        "platform_source": rank_plan.source,  # flags | intent | default | none
        "keep_tiers": rank_plan.tiers,
        "keep_quartiles": rank_plan.quartiles,
        "top_only": rank_plan.top,
        "category": rank_plan.category,
        "applied_filter": rank_filter_active,
        "ambiguous": rank_plan.ambiguous,
        # When ambiguous (bare "Q1"), the calling agent should ASK the user which
        # platform (CLI is non-interactive; spec §7). Until then nothing is filtered.
        "candidate_platforms": list(rank_plan.candidate_platforms or []) if rank_plan.ambiguous else [],
        "kept": rank_kept_count,
        "filtered": rank_filtered_count,
        "no_platform_data": rank_nodata_count,
        "data_loaded": rank_lookup is not None,
        "loaded_platforms": list(rank_lookup.loaded_platforms) if rank_lookup is not None else [],
        # Switching standard/tier is a RE-FILTER of the already-annotated pool —
        # no re-search needed (spec §7). These platforms are ready to switch to now.
        "switchable_platforms": switchable,
        "switch_is_refilter_not_research": True,
        "stripped_phrases": rank_plan.intent_matched,
        "deepen": {
            "active": rank_filter_active,
            "rounds": deepen_rounds,
            "saturated": deepen_saturated,
            "final_per_strategy": cur_per_strategy if rank_filter_active else per_strategy,
        },
        "attribution": rank_attribution,
        "note": rank_load_note,
        "keep_tiers_note": keep_tiers_note,
        "naming": (
            "CAS 区 & SJR best_quartile are PARTITIONS; only JCR impact_factor is a "
            "real Impact Factor (R-04/R-09). 切换标准/档位 = 重筛已标注的候选池，不重搜。"
        ),
    }

    meta: Dict = {
        "query": {
            "topic": query,
            "search_query": search_query,
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
            "after_rank_filter": after_rank_filter,
            "returned": len(data),
        },
        "rank": rank_meta,
        # Journal-enrichment audit for the SINGLE journal_rank layer (the legacy
        # SJR-only journal_metric block + per-paper key are retired). This reports
        # what got attached to journal_rank; the partition-filter decision lives in
        # ``meta.rank``.
        "enrichment": {
            "enriched": bool(enrich_journal),
            # OpenAlex open impact attached into journal_rank.openalex (CC0).
            "impact_source": impact_source,  # "openalex_summary_stats" | None
            "impact_attached": impact_attached,
            # --quartile filters journal_rank.sjr.best_quartile; --min-impact filters
            # journal_rank.openalex.mean_citedness_2yr (an OPEN impact figure, NOT a
            # JCR Impact Factor — R-04/R-09).
            "filter_quartiles": sorted(want_quartiles) if want_quartiles else None,
            "filter_min_impact": min_impact,
            "category": journal_category,
            # SS-primary ISSN backfill audit (R-08): whether the backfill ran, how
            # many SS records lacked an ISSN, and how many were recovered via a free
            # OA DOI lookup so the journal_rank join is not silently lost.
            "issn_backfill_enabled": bool(issn_backfill),
            "issn_backfill_attempted": issn_backfill_attempted,
            "issn_backfilled": issn_backfilled,
            "note": (
                "Single journal_rank layer. Quartile/影响力 data lives in each "
                "paper's journal_rank (CAS/JCR/SJR + openalex). Partition data is "
                "cached under ~/.paper-search-pro/ranks/ (run `journal_rank fetch`, "
                "no API key needed). Only JCR IF(2024) is a real Impact Factor."
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
    # #11: retrieved_raw counts the Chinese supplemental sources too, but
    # source_used names only the primary engine — split the raw count so the agent
    # sees how many rows came from Chinese sources vs the primary engine. Additive
    # keys, emitted ONLY when a Chinese source ran (n_chinese>0), so the default
    # English counts block is byte-identical (R-19). chinese_results is constant
    # across any deepen rounds, so this stays consistent with retrieved_raw.
    if n_chinese:
        chinese_raw = sum(len(s) for s in chinese_results)
        meta["counts"]["retrieved_raw_chinese"] = chinese_raw
        meta["counts"]["retrieved_raw_primary"] = retrieved_raw - chinese_raw
    # Additive language axis (§8). Emitted ONLY when the language feature is engaged
    # (explicit --lang / --with-* / config non-auto / Chinese query). The fully
    # default English path never engages it -> no meta.language key -> the envelope
    # is byte-identical to v2.2 (R-19).
    if lang_plan.engaged:
        meta["language"] = _language_meta(lang_plan)

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
        help="Comma-separated SJR quartiles to KEEP, e.g. 'Q1,Q2'. OPT-IN filter on "
        "journal_rank.sjr.best_quartile (the single layer). SJR分区, NOT JCR (R-04). "
        "Needs cached journal-rank data (run `journal_rank fetch`, lands in "
        "~/.paper-search-pro/ranks/). For 区/category control use --rank-platform.",
    )
    parser.add_argument(
        "--min-impact",
        type=float,
        default=None,
        help="Drop papers whose OPEN journal impact (journal_rank.openalex "
        "mean_citedness_2yr, OpenAlex 2yr mean citedness) is below this. R-09: this "
        "is NOT the JCR Impact Factor; relative use only.",
    )
    parser.add_argument(
        "--journal-category",
        default=None,
        help="DEPRECATED (legacy SJR-only layer). Use --rank-platform sjr "
        "--rank-category to pin a per-category quartile in the single layer.",
    )
    parser.add_argument(
        "--sjr-csv",
        default=None,
        help="DEPRECATED / ignored: the legacy sjr_helper SJR-only path is retired. "
        "Cache SJR data with `journal_rank fetch --platform sjr` (-> ranks/) instead.",
    )
    parser.add_argument(
        "--no-journal-metric",
        action="store_true",
        help="Skip journal-rank enrichment entirely (journal_rank stays None: no "
        "partition labels, no OpenAlex open impact).",
    )
    parser.add_argument(
        "--rank-platform",
        choices=list(journal_rank.PLATFORMS),
        default=None,
        help="Multi-platform journal RANK to FILTER on: cas (中科院 区) | jcr | sjr. "
        "Omit to take the platform from the query's NL intent ('中科院一区' -> cas) "
        "or, failing that, config rank.default_platform (which only LABELS, never "
        "filters). CAS 区 & SJR quartile are PARTITIONS; only JCR is a real IF (R-04).",
    )
    parser.add_argument(
        "--keep-tiers",
        default=None,
        help="Comma-separated tiers/quartiles to KEEP, mapped onto the chosen "
        "platform: CAS uses 区 numbers ('1,2'); JCR/SJR use quartiles ('Q1,Q2'). "
        "OPT-IN: with none given every paper is labelled with all three platforms "
        "but nothing is filtered. With a tier filter the search ADAPTIVELY DEEPENS "
        "to meet the target count (spec §6).",
    )
    parser.add_argument(
        "--rank-category",
        default=None,
        help="Pin the partition/quartile to a specific sub-category (CAS 小类 / "
        "JCR/SJR category) instead of the journal's best.",
    )
    parser.add_argument(
        "--deepen-target",
        type=int,
        default=None,
        help="Target survivor count that adaptive deepening aims for when a tier "
        "filter is active (default: --limit, or 10). Deepening re-retrieves at "
        "greater depth and RE-FILTERS the same annotated pool — switching "
        "platform/tier afterwards is a re-filter, not a re-search (spec §7).",
    )
    parser.add_argument(
        "--primary-source",
        choices=["openalex", "semantic_scholar", "auto"],
        default=None,
        help="Engine (三轴模型 axis 1) to run the primary retrieval THIS run: "
        "openalex | semantic_scholar | auto. TRANSIENT override of "
        "config.primary_source — single-use, never persisted — so the agent can "
        "make a per-query 引擎 choice (e.g. AI judges SS better for one query). "
        "'auto' lets the quota probe stickily fall back to SS on low OA budget. "
        "Omit to use config.primary_source (default openalex). NB: semantic_scholar "
        "needs a key or it fails E_CONFIG (R-06).",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "zh", "both"],
        default=None,
        help="Language SPACE (三轴模型 axis 2) to search: en | zh | both. Omit to "
        "take config.search_language (non-auto adopted silently) or auto (English "
        "query -> en; Chinese query -> zh passthrough, flagged ambiguous in "
        "meta.language for the caller to resolve). Explicit --lang wins and sets "
        "meta.language.scope_source=flags. The agent path never asks/guesses.",
    )
    parser.add_argument(
        "--with-nssd",
        action="store_true",
        help="Also query NSSD (国家哲社文献中心, Chinese social-sciences source) and "
        "MERGE its results into the candidate pool (federated dedup). Chinese "
        "supplemental source; requires zh in scope (an en scope is upgraded to "
        "'both'). Reported in meta.language.chinese_sources_used. Explicit-only "
        "(no discipline-signal auto-routing in the agent path).",
    )
    parser.add_argument(
        "--with-yiigle",
        action="store_true",
        help="Also query yiigle (中华医学期刊全文数据库, Chinese medical source) and "
        "MERGE its results into the candidate pool. Chinese supplemental source; "
        "requires zh in scope (an en scope is upgraded to 'both'). Reported in "
        "meta.language.chinese_sources_used. Explicit-only.",
    )
    parser.add_argument(
        "--no-issn-backfill",
        action="store_true",
        help="On the SS-primary path, do NOT recover missing ISSNs via free "
        "OpenAlex DOI lookups. Default is ON (so the journal_rank join is not "
        "silently lost). Turn off for large SS result sets to save per-paper OA "
        "calls; papers then stay unjoinable (the meta.enrichment.issn_backfill_* "
        "audit keeps the gap visible). No effect on the OpenAlex-primary or human path.",
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
    keep_tiers = (
        [t.strip() for t in args.keep_tiers.split(",") if t.strip()]
        if args.keep_tiers
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
            rank_platform=args.rank_platform,
            keep_tiers=keep_tiers,
            rank_category=args.rank_category,
            deepen_target=args.deepen_target,
            lang=args.lang,
            with_nssd=args.with_nssd,
            with_yiigle=args.with_yiigle,
            primary_source=args.primary_source,
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
