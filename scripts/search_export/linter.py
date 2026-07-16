"""Deterministic search-string linter (Design Spec §5.2, checks L1-L11).

Where this sits in the pipeline
-------------------------------
STEP 11.5 three-sandwich **layer 3** (mechanical validation). The linter is the
machine backstop that runs on every generated per-host search string. It only
flags **mechanically decidable** defects (bracket balance, operator case, wrong-
host truncation/proximity syntax, half-width violations, missing vocab-status
stamps). Everything that needs meaning — is this concept in the right block, is
this MeSH the right descriptor — is *left to the LLM's PRESS self-review* (D-20:
"语义判断交 LLM、机械事实交代码，两个方向都不越界"). The linter never rewrites; it
reports ``Finding``s the caller acts on.

Data, not hardcoded facts
--------------------------
Per-host facts come from the syntax cards (``references/search_export/
syntax_cards/<host>.md``, first ```yaml fence) and the proximity table — the
linter *reads* platform truth, it does not embed it (D-19/D-20). The only things
in code are (a) cross-host structural rules (bracket balance, curly quotes) and
(b) two fixed design facts that are not per-host syntax: the free-API controlled-
vocabulary set for L11 (MeSH/ERIC, Design Spec §5.3) and the CENTRAL study-design
filter signatures for L9 (A-7 / filters_library).

Scope honesty
-------------
- L3's ``*`` role is **position-based** for CNKI: a card that declares ``*`` a
  field-internal AND operator (``boolean.field_internal``) makes ``'a' * 'b'`` /
  ``'a'*'b'`` legal and only a word-attached ``词*`` (truncation intent) an error
  (Gate1-F1 — never false-flag a legal AND search).
- L5 validates the field-tag *styles* that are mechanically unambiguous — bracket
  (``[tiab]``), equals-suffix (``TS=``), paren-wrap (``TITLE-ABS(...)``). Two-letter
  prefix codes (EBSCO ``TI``) and bare colon codes are left to human/LLM review to
  avoid false positives (any 2-letter token could be a search word).
- L9's RCT/study-design signatures are a CENTRAL error only in *filter* context —
  a trial phrase bound to a publication-type tag (``[pt]`` / ``.pt.`` /
  ``[Publication Type]``) or a Cochrane-hedge marker (HSSS). The same phrases as
  plain *topic* words (a methods study *about* RCTs) are legitimate and pass.
- L11 classifies the verification-status stamp by **exact equality** (via
  ``_classify_status``), never a substring test — the honest offline stamp
  ``unverified`` is not the fake claim ``verified`` even though it contains it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from . import proximity as _prox

_CARDS_DIR = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "search_export"
    / "syntax_cards"
)

# Host name / alias -> syntax-card filename stem. Accepts card stems directly plus
# the friendlier names the rest of the pipeline uses.
_CARD_ALIASES = {
    "wos": "wos",
    "web of science": "wos",
    "webofscience": "wos",
    "web_of_science": "wos",
    "cnki": "cnki",
    "知网": "cnki",
    "wanfang": "wanfang",
    "万方": "wanfang",
    "sinomed": "sinomed",
    "cbm": "sinomed",
    "pubmed": "pubmed",
    "scopus": "scopus",
    "eric": "eric",
    "ieee": "ieee_xplore",
    "ieee_xplore": "ieee_xplore",
    "ieee xplore": "ieee_xplore",
    "acm": "acm_dl",
    "acm_dl": "acm_dl",
    "acm dl": "acm_dl",
    "cochrane": "cochrane_central",
    "cochrane_central": "cochrane_central",
    "cochrane central": "cochrane_central",
    "central": "cochrane_central",
    "embase": "embase_com",
    "embase_com": "embase_com",
    "embase.com": "embase_com",
    "embase_ovid": "embase_ovid",
    "cinahl": "cinahl_ebsco",
    "cinahl_ebsco": "cinahl_ebsco",
    "econlit": "econlit_ebsco",
    "econlit_ebsco": "econlit_ebsco",
    "psycinfo_ebsco": "psycinfo_ebsco",
    "psycinfo_ovid": "psycinfo_ovid",
    "cab": "cab_cabi",
    "cabi": "cab_cabi",
    "cab_cabi": "cab_cabi",
    "scifinder": "scifinder",
    "clinicaltrials_gov": "clinicaltrials_gov",
    "clinicaltrials.gov": "clinicaltrials_gov",
    "ct.gov": "clinicaltrials_gov",
    "ctgov": "clinicaltrials_gov",
}

ERROR = "error"
WARN = "warn"

# L11: the only two controlled vocabularies with a free existence-check API
# (Design Spec §5.3). Everything else (Emtree/CINAHL/APA/CMeSH/IEEE...) must stay
# "pending manual" and may NOT be stamped verified (A-6, no fake-verify).
_FREE_API_VOCABS = {"mesh", "eric"}

# Verification-status vocabulary — classified by EXACT equality, never substring.
# A naive ``"verified" in status`` test treats the honest offline stamp
# "unverified" as a fake "verified" claim (its literal substring), which used to
# error → silently withhold a legitimate Emtree/CINAHL string (Gate2 FG2 #9).
# Every status string is bucketed once via set membership so no bucket's token is
# ever matched as a substring of another.
_VERIFIED_STATUSES = {"verified", "confirmed", "machine_verified", "机械已验"}
_DOWNGRADE_STATUSES = {
    "downgraded",
    "degraded",
    "not_found",
    "非规范",
    "已降级",
    "降级",
}
# Honest "could not check" — verification was skipped or the free-API / network
# was unreachable (generate.py offline mode, vocab_verify network failure). This
# is NOT a verified claim; it passes with a WARN (放行), never an error.
_UNVERIFIED_STATUSES = {"unverified", "网络失败"}
# Honest "awaiting manual review" — the designed terminal state for a vocabulary
# with no free lookup API (Emtree/CINAHL/APA/CMeSH → 🟨 语法已验·词表待核).
_PENDING_STATUSES = {
    "pending",
    "pending_manual",
    "llm_suggest",
    "llm_suggest_only",
    "manual",
    "待人工核",
    "待人工核对",
    "待核",
}


def _classify_status(status: str) -> str:
    """Bucket a normalised status string by EXACT match (never a substring test).

    Returns one of ``verified`` / ``downgraded`` / ``unverified`` / ``pending`` /
    ``unknown``. This is the single place status strings are interpreted, so the
    equality-only (never-substring) invariant lives in one function.
    """
    if status in _VERIFIED_STATUSES:
        return "verified"
    if status in _DOWNGRADE_STATUSES:
        return "downgraded"
    if status in _UNVERIFIED_STATUSES:
        return "unverified"
    if status in _PENDING_STATUSES:
        return "pending"
    return "unknown"


# L9: study-design / RCT filter signatures. On a CENTRAL host these are a
# methodological error (A-7: CENTRAL is already a trials register) ONLY when used
# as a *filter* — i.e. a trial-type phrase bound to a publication-type field tag,
# or a distinctive Cochrane-hedge marker. The same phrases as plain *topic* words
# (a methods study *about* RCTs / random allocation / double-blind method) are
# legitimate on CENTRAL and must NOT be withheld (Gate2 FG2 #10 / 26b P3-16).
_RCT_TRIAL_SIGNATURES = (
    "randomized controlled trial",
    "randomised controlled trial",
    "controlled clinical trial",
    "randomized controlled trials as topic",
    "randomised controlled trials as topic",
    "random allocation",
    "double-blind method",
    "single-blind method",
)
# Publication-type / study-design field tags that turn a trial phrase into a
# filter: PubMed/Cochrane ``[pt]`` / ``[publication type]``, Cochrane ``:pt``,
# Ovid ``.pt.``. Word-boundary fenced so ":ti,ab" / "[tiab]" (topic tags) never
# match.
_PUBTYPE_TAG = r"(?:\[\s*(?:pt|publication\s+type)\s*\]|:pt(?![a-z])|\.pt\.)"
# Filter-only markers (Cochrane HSSS) — never a legitimate topic phrase, so they
# fire on presence alone.
_HSSS_MARKERS = ("highly sensitive search strateg", "hsss")

# L6: routing / journal-tier markers that must be stripped before search
# generation (A-10). Mirrors scripts/rank_intent.py's marker vocabulary; Latin
# tokens are word-boundary-fenced so "forecasting" / "broadcast" never match.
_MARKER_PATTERNS = (
    re.compile(r"中科院分区|中科院|科院分区"),
    re.compile(r"(?<![一-鿿])[一二三四1234]\s*区(?![一-鿿])"),
    re.compile(r"CSSCI|C刊|北大核心|南大核心|核心期刊|中文核心"),
    # Unambiguous journal-index markers only; bare "SCI" is dropped (spinal cord
    # injury / other domain abbreviations would false-positive).
    re.compile(r"(?<![A-Za-z])(?:JCR|SJR|SSCI)(?![A-Za-z])"),
    re.compile(r"(?<![A-Za-z])[Qq]\s*[1-4](?![A-Za-z0-9])"),
    re.compile(r"影响因子|impact\s*factor", re.IGNORECASE),
    re.compile(r"顶刊|top\s*journal|分区", re.IGNORECASE),
)

# Full-width / CJK punctuation & full-width alnum that break the half-width rule
# (L7). Half-width ASCII apostrophe/quote/paren are the only legal delimiters.
_FULLWIDTH_RE = re.compile(
    "[！-～　、。，；：“”‘’"
    "（）【】｛｝「」『』／＼]"
)

_CURLY_QUOTES = "“”‘’"  # “ ” ‘ ’


class UnknownHostError(KeyError):
    """Raised when no syntax card exists for the requested host."""


@dataclass
class Finding:
    """One linter defect. ``rule`` is the L-id; ``level`` is ERROR or WARN."""

    rule: str
    level: str
    message: str
    span: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - convenience only
        loc = f" [{self.span}]" if self.span else ""
        return f"{self.rule}/{self.level}: {self.message}{loc}"


@dataclass
class LintResult:
    host: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def passed(self) -> bool:
        """True when no ERROR-level finding fired (WARN does not fail the gate)."""
        return not self.errors

    def by_rule(self, rule: str) -> List[Finding]:
        return [f for f in self.findings if f.rule == rule]


# ---------------------------------------------------------------------------
# Card loading
# ---------------------------------------------------------------------------

_YAML_FENCE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)


def resolve_card_name(host: str) -> str:
    key = (host or "").strip().lower()
    if key in _CARD_ALIASES:
        return _CARD_ALIASES[key]
    # normalise separators then retry (e.g. "IEEE-Xplore")
    norm = re.sub(r"[\s.\-]+", "_", key)
    return _CARD_ALIASES.get(norm, norm)


@lru_cache(maxsize=64)
def _load_card_cached(path_str: str) -> Dict:
    text = Path(path_str).read_text(encoding="utf-8")
    m = _YAML_FENCE.search(text)
    if not m:
        raise ValueError(f"no yaml fence in card {path_str}")
    return yaml.safe_load(m.group(1)) or {}


def load_card(host: str, cards_dir: Optional[Path] = None) -> Dict:
    """Load and parse a host's syntax-card YAML (first ```yaml fence)."""
    stem = resolve_card_name(host)
    base = Path(cards_dir) if cards_dir is not None else _CARDS_DIR
    path = base / f"{stem}.md"
    if not path.exists():
        raise UnknownHostError(f"no syntax card for host {host!r} ({path})")
    return _load_card_cached(str(path))


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------


def _mask_quoted(query: str, mask_single: bool = False) -> str:
    """Replace characters inside quoted spans with spaces (length-preserving).

    Lets operator/marker scanning ignore search-term content. Double quotes are
    always masked; single quotes only when ``mask_single`` (CJK value-delimited
    hosts), since English apostrophes ("children's") are not string delimiters.
    """
    out = list(query)
    in_dq = False
    in_sq = False
    for i, ch in enumerate(query):
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            continue
        if mask_single and ch == "'" and not in_dq:
            in_sq = not in_sq
            continue
        if in_dq or in_sq:
            out[i] = " "
    return "".join(out)


def _norm(val) -> str:
    return str(val or "").strip().lower()


def _collect_bracket_tags(card: Dict) -> set:
    """All ``[...]`` tokens declared anywhere in the card (valid tag vocabulary)."""
    blob = yaml.safe_dump(card, allow_unicode=True)
    return set(re.findall(r"\[[^\]\[]+\]", blob))


# ---------------------------------------------------------------------------
# L1 — bracket / quote balance (+ curly quotes)
# ---------------------------------------------------------------------------


def _check_l1(query: str, card: Dict) -> List[Finding]:
    out: List[Finding] = []
    depth = 0
    for ch in query:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                out.append(
                    Finding("L1", ERROR, "unbalanced parentheses: ')' before '('")
                )
                break
    if depth > 0:
        out.append(
            Finding("L1", ERROR, f"unbalanced parentheses: {depth} unclosed '('")
        )
    if query.count('"') % 2:
        out.append(Finding("L1", ERROR, 'unbalanced double quotes (")'))
    # Single-quote parity only for cards that use the half-width single quote as
    # the value delimiter (CNKI). English hosts use apostrophes freely.
    if "单引号" in str(card.get("phrase", {}).get("quote", "")):
        if query.count("'") % 2:
            out.append(
                Finding("L1", ERROR, "unbalanced half-width single quotes (')")
            )
    curly = [c for c in query if c in _CURLY_QUOTES]
    if curly:
        out.append(
            Finding(
                "L1",
                ERROR,
                "curly/smart quotes present; use straight ASCII quotes",
                span="".join(sorted(set(curly))),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2 — boolean operator case
# ---------------------------------------------------------------------------


def _check_l2(query: str, card: Dict) -> List[Finding]:
    case = _norm(card.get("boolean", {}).get("case"))
    if "uppercase-required" not in case and "uppercase, " not in case:
        # case-insensitive / uppercase-conventional -> not a hard requirement.
        return []
    masked = _mask_quoted(query, mask_single="单引号" in str(
        card.get("phrase", {}).get("quote", "")))
    out: List[Finding] = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z]{2,3})(?![A-Za-z0-9_])", masked):
        tok = m.group(1)
        if tok.lower() in {"and", "or", "not"} and tok != tok.upper():
            out.append(
                Finding(
                    "L2",
                    ERROR,
                    f"boolean operator {tok!r} must be UPPERCASE on this host",
                    span=tok,
                )
            )
    return out


# ---------------------------------------------------------------------------
# L3 — truncation / wildcard by host (+ position-based CNKI '*')
# ---------------------------------------------------------------------------


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or "一" <= ch <= "鿿"


def _field_internal_star_is_and(card: Dict) -> bool:
    fi = str(card.get("boolean", {}).get("field_internal", ""))
    return bool(fi) and "*" in fi and ("AND" in fi.upper() or "与" in fi)


def _card_deprecates_star(card: Dict) -> bool:
    for g in card.get("gotchas", []) or []:
        s = str(g)
        if "*" in s and "废弃" in s:
            return True
    return False


def _check_l3(query: str, card: Dict, host: str) -> List[Finding]:
    out: List[Finding] = []
    trunc = card.get("truncation", {}) or {}
    multi = trunc.get("multi_char")
    zero_one = trunc.get("zero_or_one")
    min_before = trunc.get("min_chars_before")

    star_positions = [i for i, ch in enumerate(query) if ch == "*"]

    if _field_internal_star_is_and(card):
        # CNKI: '*' is a field-internal AND operator. Legal between operands
        # ('a' * 'b' / 'a'*'b' / ) * '...'); a word-attached '词*' is truncation
        # intent -> error (Gate1-F1: never false-flag a legal AND search).
        for i in star_positions:
            left = query[i - 1] if i > 0 else ""
            if _is_word_char(left):
                out.append(
                    Finding(
                        "L3",
                        ERROR,
                        "'*' attached to a word reads as truncation, which CNKI "
                        "does not support ('*' is the field-internal AND operator)",
                        span=query[max(0, i - 4):i + 1],
                    )
                )
    elif multi == "*":
        # Host supports '*' truncation; enforce min-chars-before if declared.
        if isinstance(min_before, int):
            for i in star_positions:
                j = i - 1
                cnt = 0
                while j >= 0 and query[j].isalnum():
                    cnt += 1
                    j -= 1
                if 0 < cnt < min_before:
                    out.append(
                        Finding(
                            "L3",
                            ERROR,
                            f"truncation '*' needs >= {min_before} chars before it "
                            f"(only {cnt})",
                            span=query[max(0, i - min_before):i + 1],
                        )
                    )
    elif star_positions:
        if _card_deprecates_star(card):
            out.append(
                Finding(
                    "L3",
                    WARN,
                    "'*' is deprecated to an ordinary search word on this host "
                    "(no longer an operator/wildcard); use AND/OR/NOT",
                    span="*",
                )
            )
        else:
            out.append(
                Finding(
                    "L3",
                    ERROR,
                    "'*' is not a supported wildcard on this host",
                    span="*",
                )
            )

    # '$' = zero-or-one on WoS / Embase.com — flag as a likely mistaken-for-
    # truncation symbol (A-4), but only where the card assigns it that role.
    if zero_one == "$" and "$" in query:
        out.append(
            Finding(
                "L3",
                WARN,
                "'$' here means zero-or-one character (NOT truncation); confirm "
                "it is not a mis-ported truncation symbol",
                span="$",
            )
        )
    return out


# ---------------------------------------------------------------------------
# L4 — proximity <-> host (co-occurrence + foreign-operator / family mismatch)
# ---------------------------------------------------------------------------

# Distinctive proximity tokens and the card-stem host that owns them. Used to
# flag a foreign host's operator (a family mismatch surrogate — you cannot infer
# the canonical k from the string, but the wrong host's operator is decidable).
_FOREIGN_PROX = (
    (re.compile(r"(?<![A-Za-z])adj\d*(?![A-Za-z])"), {"embase_ovid", "psycinfo_ovid"},
     "Ovid 'adj' operator"),
    (re.compile(r"(?<![A-Za-z])ONEAR/\d+"), {"ieee_xplore"}, "IEEE 'ONEAR' operator"),
    (re.compile(r"/(?:NEAR|PREV|AFT|SEN|PRG)\b"), {"cnki"},
     "CNKI positional operator (/NEAR //PREV //AFT //SEN //PRG)"),
    (re.compile(r":~\d+\]"), {"pubmed"}, "PubMed proximity [field:~N]"),
)


def _paren_depth_at(s: str, idx: int) -> int:
    return s[:idx].count("(") - s[:idx].count(")")


def _group_after(s: str, idx: int) -> Optional[str]:
    """The balanced ``(...)`` group starting at the first non-space char >= idx."""
    i = idx
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s) or s[i] != "(":
        return None
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return s[i:j + 1]
    return None


def _group_before(s: str, idx: int) -> Optional[str]:
    """The balanced ``(...)`` group ending at the first non-space char < idx."""
    i = idx - 1
    while i >= 0 and s[i] == " ":
        i -= 1
    if i < 0 or s[i] != ")":
        return None
    depth = 0
    for j in range(i, -1, -1):
        if s[j] == ")":
            depth += 1
        elif s[j] == "(":
            depth -= 1
            if depth == 0:
                return s[j:i + 1]
    return None


def _check_l4(query: str, card: Dict, host: str) -> List[Finding]:
    out: List[Finding] = []
    stem = resolve_card_name(host)
    masked = _mask_quoted(query, mask_single="单引号" in str(
        card.get("phrase", {}).get("quote", "")))
    has_star = "*" in query
    prox = card.get("proximity", {}) or {}
    constraints = [str(c) for c in (prox.get("constraints") or [])]
    # gather this host's own NEAR/NEXT-style tokens for the co-occurrence checks
    near_tokens = re.findall(r"(?<![A-Za-z])(?:O?NEAR|NEXT)(?:/\d+)?", masked)

    # L4a — WoS: AND may not sit inside a parenthesised operand of NEAR
    # (illegal: 'Germany NEAR/10 (monetary AND union)'). We inspect each NEAR's
    # adjacent ( ) operand for a nested AND, so a legal 'x AND (a NEAR/3 b)'
    # (AND outside NEAR's scope) is not flagged.
    illegal = [str(x) for x in (prox.get("illegal") or [])]
    if stem == "wos" or "no_AND_inside_NEAR_parentheses" in constraints or \
            "AND_inside_NEAR_parens" in illegal:
        and_re = re.compile(r"(?<![A-Za-z])AND(?![A-Za-z])")
        for m in re.finditer(r"(?<![A-Za-z])NEAR(?:/\d+)?", masked):
            for operand in (
                _group_after(masked, m.end()),
                _group_before(masked, m.start()),
            ):
                if operand and and_re.search(operand):
                    out.append(
                        Finding(
                            "L4",
                            ERROR,
                            "WoS forbids AND inside a parenthesised NEAR operand "
                            "('a NEAR/n (b AND c)' is illegal)",
                            span=operand.strip()[:40],
                        )
                    )
                    break

    # L4b — PubMed: proximity must be quoted and cannot co-occur with truncation.
    if stem == "pubmed":
        for m in re.finditer(r'(.?)\[(ti|tiab|ad):~(\d+)\]', query):
            before = m.group(1)
            # locate the phrase this proximity tag closes
            start = m.start()
            phrase = ""
            if before == '"':
                # before-char IS the closing quote (at index ``start``); walk back
                # to the opening quote and take everything between them.
                q = query.rfind('"', 0, start)
                if q != -1:
                    phrase = query[q + 1:start]
            else:
                out.append(
                    Finding(
                        "L4",
                        ERROR,
                        "PubMed proximity [field:~N] must wrap a quoted phrase "
                        '("term1 term2"[tiab:~N])',
                        span=m.group(0),
                    )
                )
            if "*" in phrase:
                out.append(
                    Finding(
                        "L4",
                        ERROR,
                        "PubMed proximity is mutually exclusive with truncation "
                        "'*' (A-9)",
                        span=m.group(0),
                    )
                )

    # L4c — Embase.com: NEAR/NEXT operands must be parenthesised.
    if "must_parenthesize_operands" in constraints:
        for m in re.finditer(r"(?<![A-Za-z])(?:NEAR|NEXT)(?:/\d+)?", masked):
            if _paren_depth_at(masked, m.start()) <= 0:
                out.append(
                    Finding(
                        "L4",
                        ERROR,
                        "Embase NEAR/NEXT operands must be wrapped in parentheses",
                        span=m.group(0),
                    )
                )

    # L4d — IEEE: NEAR/ONEAR cannot co-occur with '*'.
    if ("no_wildcard_with_NEAR" in constraints) and near_tokens and has_star:
        out.append(
            Finding(
                "L4",
                ERROR,
                "IEEE proximity NEAR/ONEAR cannot be used together with wildcard "
                "'*'",
                span=near_tokens[0],
            )
        )

    # L4e — foreign proximity operator (wrong host / family mismatch surrogate).
    for pat, owners, label in _FOREIGN_PROX:
        if stem in owners:
            continue
        m = pat.search(masked if pat.pattern != r":~\d+\]" else query)
        if m:
            out.append(
                Finding(
                    "L4",
                    ERROR,
                    f"{label} does not belong to this host (proximity family / "
                    "syntax mismatch); use this host's operator via proximity.py",
                    span=m.group(0),
                )
            )
    return out


# ---------------------------------------------------------------------------
# L5 — illegal / mistyped field tags (unambiguous styles only)
# ---------------------------------------------------------------------------


def _check_l5(query: str, card: Dict, host: str) -> List[Finding]:
    out: List[Finding] = []
    tags = card.get("field_tags", {}) or {}
    values = [str(v) for v in tags.values() if v]
    valid_brackets = _collect_bracket_tags(card)

    uses_bracket = any("[" in v for v in values)
    uses_equals = any(re.search(r"\b[A-Z]{2,}=", v) for v in values)
    uses_paren = any(re.search(r"[A-Z][A-Z\-]+\(", v) for v in values)

    if uses_bracket:
        valid_fields = {
            re.sub(r"[\[\]]", "", b).lower() for b in valid_brackets
        }
        # The controlled-vocab name is a valid subject-heading tag synonym the
        # short-code list may omit (PubMed accepts [mh] == [Mesh] == [MeSH Terms]).
        # Read it off the card so we never false-flag the canonical MeSH tag.
        cv_name = _norm(card.get("controlled_vocab", {}).get("name"))
        if cv_name:
            valid_fields.add(cv_name)
            valid_fields.add(cv_name.split()[0])
        for m in re.finditer(r"\[([^\]\[]+)\]", query):
            raw = m.group(0)
            inner = m.group(1)
            pm = re.match(r"([A-Za-z]+):~\d+$", inner)  # proximity tag
            if pm:
                if pm.group(1).lower() not in valid_fields:
                    out.append(
                        Finding("L5", ERROR, f"unknown field tag {raw!r}", span=raw)
                    )
                continue
            if raw not in valid_brackets and inner.lower() not in valid_fields:
                out.append(
                    Finding("L5", ERROR, f"unknown field tag {raw!r}", span=raw)
                )

    if uses_equals:
        valid_eq = {
            m.group(0).upper()
            for v in values
            for m in re.finditer(r"\b[A-Z]{2,}=", v)
        }
        for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2,})=", query):
            if m.group(0).upper() not in valid_eq:
                out.append(
                    Finding(
                        "L5", ERROR, f"unknown field tag {m.group(0)!r}",
                        span=m.group(0),
                    )
                )

    if uses_paren:
        valid_par = {
            m.group(1).upper()
            for v in values
            for m in re.finditer(r"([A-Z][A-Z\-]+)\(", v)
        }
        for m in re.finditer(r"(?<![A-Za-z])([A-Z][A-Z\-]{2,})\(", query):
            if m.group(1).upper() not in valid_par:
                tag = m.group(1) + "("
                out.append(Finding("L5", ERROR, f"unknown field tag {tag!r}", span=tag))
    return out


# ---------------------------------------------------------------------------
# L6 — residual routing markers
# ---------------------------------------------------------------------------


def _check_l6(query: str) -> List[Finding]:
    out: List[Finding] = []
    seen = set()
    for pat in _MARKER_PATTERNS:
        m = pat.search(query)
        if m and m.group(0) not in seen:
            seen.add(m.group(0))
            out.append(
                Finding(
                    "L6",
                    ERROR,
                    "routing / journal-tier marker leaked into the search string "
                    "(strip before generation, A-10)",
                    span=m.group(0).strip(),
                )
            )
    return out


# ---------------------------------------------------------------------------
# L7 — CJK half-width + field-internal operator role
# ---------------------------------------------------------------------------


def _check_l7(query: str, card: Dict, host: str) -> List[Finding]:
    esc = str(card.get("special_chars_escape", "") or "")
    if "半角" not in esc:  # only CJK half-width-mandate hosts (CNKI/万方/SinoMed)
        return []
    out: List[Finding] = []
    fulls = _FULLWIDTH_RE.findall(query)
    if fulls:
        out.append(
            Finding(
                "L7",
                ERROR,
                "full-width / CJK punctuation present; this host requires all "
                "operators, brackets and quotes to be half-width ASCII",
                span="".join(sorted(set(fulls))),
            )
        )
    # full-width digits/letters
    fw_alnum = re.findall(r"[０-９Ａ-Ｚａ-ｚ]", query)
    if fw_alnum:
        out.append(
            Finding(
                "L7",
                ERROR,
                "full-width digits/letters present; use half-width ASCII",
                span="".join(sorted(set(fw_alnum))),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L8 — NOT usage
# ---------------------------------------------------------------------------


def _check_l8(query: str, card: Dict) -> List[Finding]:
    masked = _mask_quoted(query, mask_single="单引号" in str(
        card.get("phrase", {}).get("quote", "")))
    if re.search(r"(?<![A-Za-z])NOT(?![A-Za-z])", masked):
        return [
            Finding(
                "L8",
                WARN,
                "NOT operator used; A-1 discourages NOT (risk of dropping "
                "relevant records) unless part of a whitelisted filter",
                span="NOT",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# L9 — CENTRAL + RCT/study-design filter co-occurrence
# ---------------------------------------------------------------------------


def _is_central(card: Dict, host: str) -> bool:
    if resolve_card_name(host) == "cochrane_central":
        return True
    blob = f"{card.get('database','')} {card.get('platform','')}".upper()
    return "CENTRAL" in blob


def _check_l9(
    query: str, card: Dict, host: str, filters_used: Optional[List] = None
) -> List[Finding]:
    if not _is_central(card, host):
        return []
    out: List[Finding] = []
    if filters_used:
        out.append(
            Finding(
                "L9",
                ERROR,
                "CENTRAL is already a controlled-trials register; do not add an "
                f"RCT / study-design filter (A-7). filters_used={filters_used}",
            )
        )
        return out
    low = query.lower()
    # (a) Distinctive Cochrane-hedge markers are always a filter (never a topic).
    for marker in _HSSS_MARKERS:
        if re.search(r"(?<![a-z])" + re.escape(marker), low):
            out.append(
                Finding(
                    "L9",
                    ERROR,
                    "CENTRAL is already a controlled-trials register; remove the "
                    "RCT / study-design filter (A-7)",
                    span=marker,
                )
            )
            return out
    # (b) A trial-type phrase bound to a publication-type tag is a filter; the
    # same phrase as a topic word (in ti/ab, or unfielded) is a legitimate
    # methods search on CENTRAL and is left alone (FG2 #10 / 26b P3-16).
    for sig in _RCT_TRIAL_SIGNATURES:
        pat = re.compile(
            r"(?<![a-z])" + re.escape(sig) + r"s?[\s\"']*" + _PUBTYPE_TAG,
            re.IGNORECASE,
        )
        m = pat.search(query)
        if m:
            out.append(
                Finding(
                    "L9",
                    ERROR,
                    "CENTRAL is already a controlled-trials register; remove the "
                    "RCT / study-design publication-type filter (A-7)",
                    span=m.group(0).strip()[:40],
                )
            )
            break
    return out


# ---------------------------------------------------------------------------
# L10 — orphan lines (line-form / Search History strategies)
# ---------------------------------------------------------------------------


def _check_l10(query: str) -> List[Finding]:
    lines = query.splitlines()
    defs = []  # (line_num, body)
    for ln in lines:
        m = re.match(r"\s*#(\d+)\b(.*)$", ln)
        if m:
            defs.append((int(m.group(1)), m.group(2)))
    if len(defs) < 2:
        return []
    defined_nums = [d for d, _ in defs]
    final = defined_nums[-1]
    referenced = set()
    for num, body in defs:
        for r in re.findall(r"#(\d+)\b", body):
            referenced.add(int(r))
    out: List[Finding] = []
    for num in defined_nums:
        if num != final and num not in referenced:
            out.append(
                Finding(
                    "L10",
                    WARN,
                    f"line #{num} is never referenced by a later line (orphan)",
                    span=f"#{num}",
                )
            )
    return out


# ---------------------------------------------------------------------------
# L11 — controlled-vocab verification-status stamp
# ---------------------------------------------------------------------------


def _check_l11(vocab_terms: Optional[List[Dict]]) -> List[Finding]:
    if not vocab_terms:
        return []
    out: List[Finding] = []
    for t in vocab_terms:
        term = t.get("term", "?")
        vocab = _norm(t.get("vocab"))
        status = _norm(t.get("status"))
        if not status:
            out.append(
                Finding(
                    "L11",
                    ERROR,
                    f"controlled term {term!r} ({t.get('vocab')}) has no "
                    "verification status stamp",
                    span=str(term),
                )
            )
            continue
        kind = _classify_status(status)
        free_api = vocab in _FREE_API_VOCABS

        # Honest "could not verify" (offline / network failure) applies to BOTH
        # vocab classes: it is never a fake-verify. Surface a WARN, let it pass.
        if kind == "unverified":
            out.append(
                Finding(
                    "L11",
                    WARN,
                    f"{t.get('vocab')} term {term!r} is stamped 'unverified' "
                    "(existence check skipped or the free-API/network was "
                    "unreachable); confirm the term manually before use",
                    span=str(term),
                )
            )
            continue

        if free_api:
            if kind in ("verified", "downgraded"):
                continue  # verified via free API, or explicitly downgraded -> clean
            if kind == "pending":
                out.append(
                    Finding(
                        "L11",
                        ERROR,
                        f"{t.get('vocab')} has a free lookup API; term {term!r} must "
                        "be free-API 'verified' or explicitly downgraded, not punted "
                        "to manual review",
                        span=str(term),
                    )
                )
            else:  # unknown status string
                out.append(
                    Finding(
                        "L11",
                        ERROR,
                        f"{t.get('vocab')} term {term!r} has an unrecognised "
                        f"verification status {status!r}",
                        span=str(term),
                    )
                )
        else:
            # No free API -> may NOT claim verified (A-6, no fake-verify).
            if kind == "verified":
                out.append(
                    Finding(
                        "L11",
                        ERROR,
                        f"{t.get('vocab')} has no free lookup API; term {term!r} may "
                        "not be stamped 'verified' (no fake-verify, A-6) -> mark "
                        "pending manual",
                        span=str(term),
                    )
                )
            elif kind in ("pending", "downgraded"):
                continue  # pending-manual (normal 🟨 state) / explicit downgrade -> clean
            else:  # unknown status string
                out.append(
                    Finding(
                        "L11",
                        ERROR,
                        f"{t.get('vocab')} term {term!r} needs a 'pending manual' "
                        f"status stamp (got unrecognised status {status!r})",
                        span=str(term),
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def lint(
    query: str,
    host: str,
    *,
    cards_dir: Optional[Path] = None,
    filters_used: Optional[List] = None,
    vocab_terms: Optional[List[Dict]] = None,
) -> LintResult:
    """Run L1-L11 on ``query`` for ``host``. Returns a :class:`LintResult`.

    ``filters_used`` / ``vocab_terms`` are the structured side-channel the STEP
    11.5 generator already has (Design Spec §2.1 ``strategies[]``); L9 and L11 use
    them when present. Everything else is derived from the string + syntax card.
    """
    card = load_card(host, cards_dir=cards_dir)
    result = LintResult(host=resolve_card_name(host))
    result.findings.extend(_check_l1(query, card))
    result.findings.extend(_check_l2(query, card))
    result.findings.extend(_check_l3(query, card, host))
    result.findings.extend(_check_l4(query, card, host))
    result.findings.extend(_check_l5(query, card, host))
    result.findings.extend(_check_l6(query))
    result.findings.extend(_check_l7(query, card, host))
    result.findings.extend(_check_l8(query, card))
    result.findings.extend(_check_l9(query, card, host, filters_used=filters_used))
    result.findings.extend(_check_l10(query))
    result.findings.extend(_check_l11(vocab_terms))
    return result


__all__ = [
    "Finding",
    "LintResult",
    "UnknownHostError",
    "ERROR",
    "WARN",
    "load_card",
    "resolve_card_name",
    "lint",
]
