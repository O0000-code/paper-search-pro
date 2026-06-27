"""Query-intent recognition for journal-rank filtering (Feature A, Wave A-2).

Why this module exists (the bug it fixes)
-----------------------------------------
The user got burned by "中科院一区 情绪调节": the partition phrase "中科院一区" was
sent to the search engine *as a topic term*, so the search looked for papers
*about* "中科院一区" instead of papers *on* 情绪调节 *filtered to* CAS tier 1. This
module is the deterministic fix: it reads a natural-language query, pulls out the
journal-rank intent (which platform, which tiers / top-only), and returns the
**cleaned topic string** with the rank phrasing stripped, so the search engine
only ever sees the real subject.

Design boundaries
-----------------
- **Pure + deterministic + network-free.** Just regex over the query string.
- **Both Chinese and English** trigger phrasing is recognised (一区 / 1区 / Q1 /
  top-tier / quartile ...).
- **A rank intent with no resolvable platform is AMBIGUOUS** — this covers BOTH a
  bare "Q1"/"Q2" (no platform word) AND a bare "顶刊"/"top journal" (no platform
  word). We record the intent (tiers/quartiles/top) but mark ``ambiguous=True``,
  do NOT guess a platform, and expose ``candidate_platforms`` (the platforms the
  caller could ask the user about). The headless CLI surfaces this in
  ``meta.rank.ambiguous`` so the *calling agent* asks the user (interactive Q&A is
  an agent-layer concern, not a CLI one); the human path (Wave A-3) asks inline.
  Either way the recogniser never silently picks a platform — and, crucially,
  never silently *drops* a stated intent (the anti-goal this module exists to kill:
  a stripped "顶刊" must not vanish without either filtering or asking).
- **Latin platform keywords only strip in a real partition context.** A bare Latin
  platform word (wos / web of science / scopus / jcr / sjr / scimago / clarivate /
  cas) is treated as a journal-rank hint ONLY when it sits next to a tier/quartile
  (e.g. "JCR Q1"), is followed by "分区", or co-occurs with top-journal intent
  (e.g. "JCR 顶刊"). When it is a *research topic* — followed by ordinary words like
  coverage / analysis / comparison / database, or standing as the query subject
  ("Web of Science coverage analysis", "WoS coverage", "CAS registry number") — it
  is left untouched: ``cleaned_query == query`` byte-for-byte and no platform is
  guessed. CJK CAS words (中科院 / 科院分区) keep substring-hint semantics (they never
  collide with ordinary English topics).
- Reused by BOTH the headless path (agent_search, now) and the human 14-STEP
  path (SKILL.md STEP 1, Wave A-3) so intent parsing is identical on both.

Output contract (``RankIntent``)
--------------------------------
``parse_rank_intent(query) -> RankIntent`` always returns a value (never None):
    platform      : "cas" | "jcr" | "sjr" | None   (None = none stated)
    tiers         : [int, ...] | None               (CAS 区 numbers, e.g. [1] or [1,2])
    quartiles     : ["Q1", ...] | None              (JCR/SJR quartiles)
    top           : bool                            ("顶刊" / "top journal" only)
    ambiguous     : bool                            (a tier/quartile OR a bare "顶刊"/
                                                     "top journal" was stated but no
                                                     platform could be resolved)
    cleaned_query : str                             (query with rank phrasing removed)
    matched       : [str, ...]                      (the raw phrases we stripped —
                                                     for transparency / debugging)
    candidate_platforms : [str, ...]                (when ambiguous: the platforms the
                                                     caller could ask the user about —
                                                     [jcr,sjr] for a bare quartile,
                                                     [cas,jcr,sjr] for a bare top-only)

Platforms map onto their native taxonomy:
    CAS  -> ``tiers`` (区 1-4)         "中科院一区" -> platform=cas, tiers=[1]
    JCR  -> ``quartiles`` (Q1-Q4)     "JCR Q1"     -> platform=jcr, quartiles=["Q1"]
    SJR  -> ``quartiles`` (Q1-Q4)     "SJR Q1"     -> platform=sjr, quartiles=["Q1"]
A bare "Q1" with no platform -> quartiles=["Q1"], platform=None, ambiguous=True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


@dataclass
class RankIntent:
    """Parsed journal-rank intent extracted from a natural-language query."""

    platform: Optional[str] = None
    tiers: Optional[List[int]] = None  # CAS 区 numbers
    quartiles: Optional[List[str]] = None  # JCR / SJR quartiles "Q1".."Q4"
    top: bool = False
    ambiguous: bool = False
    cleaned_query: str = ""
    matched: List[str] = field(default_factory=list)
    candidate_platforms: List[str] = field(default_factory=list)  # set when ambiguous

    @property
    def has_filter(self) -> bool:
        """True when the query expressed *any* rank filter intent (tier/quartile/top)."""
        return bool(self.tiers or self.quartiles or self.top)


# ---------------------------------------------------------------------------
# Chinese numerals for 一二三四 -> 1234 (CAS 区 are usually written 一/二区).
# ---------------------------------------------------------------------------

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}

# A "tier token" inside a CAS phrase: 一 / 二 / 三 / 四 / 1 / 2 / 3 / 4 (one char).
_CN_NUM_CLASS = "一二三四1234"


# ---------------------------------------------------------------------------
# Word-boundary discipline (the P1 fix for R-19's "no intent -> query unchanged")
# ---------------------------------------------------------------------------
# Latin-script platform keywords (cas / wos / jcr / sjr / ...) must match as WHOLE
# tokens, never as substrings inside ordinary English words: a bare-substring
# match corrupted everyday topics ("case study" -> "cas" matched -> "e study",
# "broadcast"/"forecasting"/"showcase"/"cascade" likewise) and that corrupted
# string was the one sent to the search engine. We wrap each Latin keyword with a
# non-letter/digit/hyphen boundary so "cas" only fires when it stands alone and
# never inside "case"/"broadcast"/"SJR-indexed". CJK keywords (中科院/科院) keep
# substring semantics — they never collide with ordinary English topics and Python
# \b is not meaningful between a CJK char and ASCII.
_LATIN_BDRY_L = r"(?<![a-z0-9-])"   # not preceded by a letter / digit / hyphen
_LATIN_BDRY_R = r"(?![a-z0-9-])"    # not followed by a letter / digit / hyphen


def _latin_token_re(*words: str) -> str:
    """Alternation of Latin platform keywords, each fenced by word boundaries."""
    return "|".join(_LATIN_BDRY_L + re.escape(w) + _LATIN_BDRY_R for w in words)


# Highest CJK codepoint used in the boundary classes below (CJK Unified base block).
_CJK = r"一-鿿"
# Journal-context words that confirm a glued "N区期刊" really IS partition intent
# (so "三区期刊" fires) while a compound like "三区制"/"三区块" does not.
_JOURNAL_CTX = r"期刊|杂志|刊物|刊"


# ---------------------------------------------------------------------------
# Platform keyword sets.
# ---------------------------------------------------------------------------

# CAS — Chinese Academy of Sciences 分区. CJK forms are matched as substrings;
# the Latin "cas" form is boundary-fenced (see _CAS_LATIN_WORD_RE).
_CAS_CJK_WORDS = ("中科院分区", "中科院", "科院分区")  # longest first for clean stripping
# JCR — Clarivate. "JCR" / "Web of Science 分区" / "WoS".
_JCR_WORDS = ("jcr", "web of science", "wos", "clarivate")
# SJR — SCImago.
_SJR_WORDS = ("sjr", "scimago", "scimagojr")


# ---------------------------------------------------------------------------
# Regexes (compiled once). Order of stripping matters: strip the most specific
# (platform + tier together) first, then standalone quartiles, then top.
# ---------------------------------------------------------------------------

# CAS "中科院" optionally glued to a tier: 中科院一区 / 中科院 1 区 / 中科院一二区 /
# 科院二区 / cas一区. The tier chunk is 1-2 consecutive numeral chars then 区.
# The "cas" alternative is boundary-fenced so "broadcast一区" can never match it.
_CAS_PHRASE_RE = re.compile(
    r"(?:中科院|科院|" + _LATIN_BDRY_L + r"cas" + r")\s*(?:分区)?\s*"
    r"([" + _CN_NUM_CLASS + r"]{1,2})?\s*区?",
    re.IGNORECASE,
)
# Bare "一区"/"二区"/"一二区"/"1 区" (CAS 区 terminology, no other platform uses 区) —
# but ONLY as a standalone partition token, never when the "N区" is glued into an
# ordinary compound. We require: not preceded by a CJK char (excludes "第一区域",
# "第三区块"), and immediately followed by end / non-CJK / another tier token
# ("一区二区") / a journal-context word ("三区期刊"). This blocks "三区制",
# "二区供暖", "第三区块链", "一区一带" while keeping "一区"/"1区"/"一二区" working.
# A trailing journal-context word ("期刊"/"杂志"…) is consumed as part of the match
# (group 2) so the whole "三区期刊" is stripped cleanly, leaving no dangling word.
_CAS_BARE_TIER_RE = re.compile(
    # Preceded by 区 (the tail of a prior tier token, so "一区二区" chains) OR not by
    # any CJK char at all (so "第一区"/"第三区" stay glued and are skipped).
    r"(?:(?<=区)|(?<![" + _CJK + r"]))"
    r"([" + _CN_NUM_CLASS + r"]{1,2})\s*区"
    r"(?:(" + _JOURNAL_CTX + r")|(?=$|[^" + _CJK + r"]|[" + _CN_NUM_CLASS + r"]\s*区))"
)
# "中科院" / "cas" mentioned with NO tier and NO 区 — platform hint only. CJK forms
# are substrings; the Latin "cas" / "cas 分区" forms are boundary-fenced.
_CAS_CJK_WORD_RE = re.compile(r"(?:中科院分区|中科院|科院分区)")
_CAS_LATIN_WORD_RE = re.compile(
    _LATIN_BDRY_L + r"cas" + r"(?:\s*分区)?" + _LATIN_BDRY_R, re.IGNORECASE
)

# A quartile token, possibly bound to a platform word in front of it:
#   "JCR Q1" / "SJR Q1" / "JCR一区"(rare) / "JCR 1区".  We capture platform + quartile.
# The Latin platform alternation is boundary-fenced so a word like "forecasting Q1"
# cannot have "cas"... (cas is not in this set, but wos/jcr/sjr still need fencing).
_PLATFORM_QUARTILE_RE = re.compile(
    r"(" + _latin_token_re("jcr", "sjr", "scimagojr", "scimago", "wos", "clarivate")
    + r"|web of science)\s*"
    r"(?:分区)?\s*(q\s*[1-4]|[" + _CN_NUM_CLASS + r"]\s*区)",
    re.IGNORECASE,
)
# A bare quartile "Q1" / "q 2" with no platform in front (ambiguous).
_BARE_QUARTILE_RE = re.compile(r"\bq\s*([1-4])\b", re.IGNORECASE)

# "top journal" / "顶刊" / "顶级期刊" / "top-tier" / "top tier".
# A leading Chinese filler ("只要"/"想要"/"只想要" = "I just want …") and a trailing
# "的" (the nominaliser that glues 顶刊 to the topic, e.g. "只要顶刊的认知") are
# OPTIONALLY consumed as part of the match so the strip leaves no dangling "只要"/"的"
# residue ("只要顶刊的认知" -> "认知", not "只要 的认知"). The top phrase itself stays
# mandatory, so a bare "只要"/"的" with no 顶刊 is never touched.
_TOP_RE = re.compile(
    r"(?:只要|想要|只想要)?\s*"
    r"(顶刊|顶级期刊|顶尖期刊|top[\s-]*tier|top[\s-]*journals?)"
    r"(?:\s*的)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _platform_for_word(word: str) -> Optional[str]:
    w = word.lower()
    if any(k in w for k in _SJR_WORDS):
        return "sjr"
    if any(k in w for k in _JCR_WORDS):
        return "jcr"
    if any(k in w for k in ("中科院", "科院", "cas")):
        return "cas"
    return None


def _tiers_from_numeral_run(run: Optional[str]) -> List[int]:
    """'一' -> [1]; '一二' -> [1,2]; '12' -> [1,2]; '' / None -> []."""
    if not run:
        return []
    out: List[int] = []
    for ch in run:
        n = _CN_NUM.get(ch)
        if n is not None and n not in out:
            out.append(n)
    return out


def _quartiles_from_tiers(tiers: List[int]) -> List[str]:
    """Map a list of tier ints onto Q-strings (used when a platform is JCR/SJR but
    the user wrote 区 numerals, e.g. 'JCR 1区')."""
    return [f"Q{t}" for t in tiers if 1 <= t <= 4]


def _norm_quartile(tok: str) -> Optional[str]:
    """'q 1' / 'Q1' -> 'Q1'; '一区'/'1区' -> 'Q1'. Returns None on garbage."""
    s = tok.strip().lower().replace(" ", "")
    m = re.match(r"q([1-4])$", s)
    if m:
        return f"Q{m.group(1)}"
    m = re.match(r"([" + _CN_NUM_CLASS + r"])区$", tok.strip())
    if m:
        n = _CN_NUM.get(m.group(1))
        return f"Q{n}" if n else None
    return None


def _collapse_ws(text: str) -> str:
    """Collapse the whitespace left behind after stripping rank phrases."""
    return re.sub(r"\s+", " ", text).strip(" ,;，；、")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_rank_intent(query: Optional[str]) -> RankIntent:
    """Extract journal-rank intent from a natural-language query.

    Returns a RankIntent (never None) with the platform/tiers/quartiles/top
    parsed and ``cleaned_query`` carrying the topic with the rank phrasing
    stripped. See the module docstring for the full contract."""
    intent = RankIntent(cleaned_query=(query or "").strip())
    if not query or not query.strip():
        return intent

    work = query  # we strip matched spans out of this progressively
    matched: List[str] = []
    platform: Optional[str] = None
    tiers: List[int] = []
    quartiles: List[str] = []

    # --- 1. platform + quartile bound together: "JCR Q1", "SJR 一区" -------------
    for m in list(_PLATFORM_QUARTILE_RE.finditer(work)):
        plat = _platform_for_word(m.group(1))
        q = _norm_quartile(m.group(2))
        if plat:
            platform = platform or plat
        if q and q not in quartiles:
            quartiles.append(q)
        matched.append(m.group(0))
    work = _PLATFORM_QUARTILE_RE.sub(" ", work)

    # --- 2. CAS phrase with an explicit tier: "中科院一区", "cas 1 区" -----------
    for m in list(_CAS_PHRASE_RE.finditer(work)):
        run = m.group(1)
        these = _tiers_from_numeral_run(run)
        if these:  # only treat as a CAS *filter* when a tier numeral is present
            platform = platform or "cas"
            for t in these:
                if t not in tiers:
                    tiers.append(t)
            matched.append(m.group(0))
    # Remove only the CAS phrases that carried a tier (keep a bare "中科院" word for
    # step 4 so the platform hint is not lost if it stood alone). The "cas" form is
    # boundary-fenced so a tier glued to an English word never gets stripped.
    work = re.sub(
        r"(?:中科院|科院|" + _LATIN_BDRY_L + r"cas)\s*(?:分区)?\s*"
        r"[" + _CN_NUM_CLASS + r"]{1,2}\s*区?",
        " ",
        work,
        flags=re.IGNORECASE,
    )

    # --- 3. bare 区 tier with no platform word: "一区", "1区", "一二区" ----------
    # In Chinese, 区 partitioning is CAS terminology; treat as CAS.
    for m in list(_CAS_BARE_TIER_RE.finditer(work)):
        these = _tiers_from_numeral_run(m.group(1))
        if these:
            platform = platform or "cas"
            for t in these:
                if t not in tiers:
                    tiers.append(t)
            matched.append(m.group(0))
    work = _CAS_BARE_TIER_RE.sub(" ", work)

    # --- 4. standalone platform words with no tier/quartile (hint only) ---------
    # e.g. "中科院" alone, or "JCR 顶刊" — sets the platform but no tier filter.
    #
    # Latin keywords are matched as WHOLE tokens (boundary-fenced), AND a bare Latin
    # platform word is only treated as a platform HINT when it is in a *real
    # partition context*: immediately followed by "分区", or the query also carries
    # top-journal intent ("JCR 顶刊"). A bare Latin platform word followed by ordinary
    # research words ("WoS coverage analysis", "Web of Science database") is a
    # research TOPIC, not a filter — stripping it there both guessed a bogus platform
    # AND corrupted the search term sent to the engine (review_A_alpha P1-① / review2
    # P2-2). When it is a topic we leave it untouched: cleaned_query == query and no
    # platform is guessed — the R-19 "no intent -> query unchanged" red line.
    # CJK CAS words (中科院 / 科院分区) keep substring-hint semantics (they never collide
    # with ordinary English topics).
    top_ctx = bool(_TOP_RE.search(work))  # 顶刊/top is still in `work` (stripped in step 6)
    if platform is None:
        for words, plat in ((_SJR_WORDS, "sjr"), (_JCR_WORDS, "jcr")):
            for w in words:
                token = _LATIN_BDRY_L + re.escape(w) + _LATIN_BDRY_R
                mm = re.search(token, work, re.IGNORECASE)
                if not mm:
                    continue
                followed_by_fenqu = re.match(r"\s*分区", work[mm.end():]) is not None
                if not (followed_by_fenqu or top_ctx):
                    continue  # research topic, not a filter — leave it untouched
                platform = plat
                matched.append(w)
                strip = token + r"\s*分区" if followed_by_fenqu else token
                work = re.sub(strip, " ", work, flags=re.IGNORECASE)
                break
            if platform:
                break
    if platform is None:
        # CJK CAS words ("中科院" / "科院分区") match as substrings and are always a
        # platform hint. The Latin "cas" word is gated like the others above (so a
        # topic such as "CAS registry number" is never read as the CAS platform).
        m = _CAS_CJK_WORD_RE.search(work)
        if m:
            platform = "cas"
            matched.append(m.group(0))
            work = work[: m.start()] + " " + work[m.end() :]
        else:
            m = _CAS_LATIN_WORD_RE.search(work)
            if m and ("分区" in m.group(0) or top_ctx):
                platform = "cas"
                matched.append(m.group(0))
                work = work[: m.start()] + " " + work[m.end() :]

    # --- 5. bare quartile with no platform: "Q1" -> ambiguous ------------------
    for m in list(_BARE_QUARTILE_RE.finditer(work)):
        q = f"Q{m.group(1)}"
        if q not in quartiles:
            quartiles.append(q)
        matched.append(m.group(0))
    work = _BARE_QUARTILE_RE.sub(" ", work)

    # --- 6. "top journal" / "顶刊" --------------------------------------------
    if _TOP_RE.search(work):
        intent.top = True
        for m in _TOP_RE.finditer(work):
            matched.append(m.group(0))
        work = _TOP_RE.sub(" ", work)

    # --- reconcile platform vs. taxonomy --------------------------------------
    # If the platform is CAS but the user wrote quartiles (rare: "中科院 Q1"), map
    # Q -> 区. If the platform is JCR/SJR but the user wrote 区 tiers, map 区 -> Q.
    if platform == "cas" and quartiles and not tiers:
        tiers = [int(q[1]) for q in quartiles if q[1:].isdigit()]
        quartiles = []
    if platform in ("jcr", "sjr") and tiers and not quartiles:
        quartiles = _quartiles_from_tiers(tiers)
        tiers = []

    # --- ambiguity: a tier/quartile OR a bare "顶刊"/"top" was stated but no -----
    # platform could be resolved. Bare quartile and top-only are handled the SAME
    # way: record the intent, flag it ambiguous, and hand the caller a candidate
    # list so it can ASK "which platform?" instead of silently dropping the intent
    # (a stripped "顶刊" that neither filters nor asks is the exact anti-goal — P1).
    stated_filter = bool(tiers or quartiles)
    intent.ambiguous = (stated_filter or intent.top) and platform is None
    if intent.ambiguous:
        # top applies to all three platforms (cas.top / jcr,sjr Q1); a bare quartile
        # is a JCR/SJR concept (CAS uses 区 numerals, never Q).
        intent.candidate_platforms = (
            ["cas", "jcr", "sjr"] if intent.top else ["jcr", "sjr"]
        )

    intent.platform = platform
    intent.tiers = tiers or None
    intent.quartiles = quartiles or None
    intent.matched = matched
    intent.cleaned_query = _collapse_ws(work) or (query or "").strip()
    return intent


__all__ = ["RankIntent", "parse_rank_intent"]
