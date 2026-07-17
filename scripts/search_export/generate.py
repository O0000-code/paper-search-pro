"""Search-strategy-export generator (v2.4 STEP 11.5 — three-sandwich layer 2/3).

Where this sits in the pipeline
-------------------------------
STEP 11.5 turns a **platform-independent** ``concept_model`` (the layer-1 LLM
output: concept blocks + synonyms + controlled-vocab candidates + operator logic)
into per-platform, paste-ready search strategies. This module is **layers 2 and 3
only** — the mechanical templating + validation:

- **layer 2 (mechanical templating)**: read each host's syntax card and render the
  concept blocks into that host's native surface syntax (controlled-vocab + field
  tags + boolean shell), convert any proximity intent through ``proximity.py``, and
  build the A-tier deep link through ``deeplink.py``.
- **layer 3 (mechanical validation)**: verify controlled vocabulary through
  ``vocab_verify.py`` (MeSH/ERIC free-API existence check; everything else honestly
  flagged), then run every rendered string through the ``linter.py`` gate. **A
  string the linter rejects is NEVER emitted** (13 spec §6 Wave 3): its
  ``strategy_string`` is withheld and a review point records why.

Layer 1 (the LLM concept-block re-composition, synonym expansion, controlled-vocab
proposal, register judgement, PRESS semantic self-review) is NOT done here — it is
done by the main agent / calling agent under the SKILL's guidance and handed to this
module as the ``concept_model`` input (D-20: "语义判断交 LLM、机械事实交代码").

Outputs (into ``$OUT``)
-----------------------
- ``search_strategies.md``   — human-first, content-over-form (13 spec §1.1).
- ``search_strategies.json`` — the structured record (13 spec §2.1), pre-wired to
  fold into ``report_data.json`` (data_materialization) and to enrich PRISMA-S item
  8/1/9/10 (prisma_s_logger).

Card-driven, not hardcoded (D-19/D-20)
--------------------------------------
Every per-host fact — field tags, controlled-vocab name/tag, boolean case,
truncation symbol, half-width mandate, match operators, deep-link tier/template —
is read off the syntax card (``references/search_export/syntax_cards/<host>.md``).
The generator embeds no platform truth; it only owns the *presentation layout* (how
blocks are laid out on the page) and the mapping from card shape to a render style
(bracket / equals / cjk / colon / paren / unfielded). Controlled-vocab clauses are
rendered ONLY from a template mechanically derivable from the card's
``controlled_vocab`` / ``field_tags`` fields — when no such template exists the CV
clause is omitted with a review point instead of emitting illegal syntax (Gate2
D-d: 绝不输出非法语法).

Honesty gates (Gate2 fix contract, 2026-07-17)
----------------------------------------------
- ``operator_logic`` is honoured as declared (block-level AND/OR); anything the
  mechanical layer cannot parse -> withhold + review point, never a silent
  rewrite (D-b).
- cjk render hosts (CNKI/万方/SinoMed — the half-width-mandate cards) take their
  word faces from ``blocks[].free_text_zh`` ONLY; a block without Chinese word
  faces withholds that host's strategy (D-a: 绝不把英文词渲染进中文库).
- ``not_found`` (free-API Count=0) controlled terms are culled from the CV clause
  and downgraded into the free-text track (13 spec §5.3), and the strategy label
  carries a downgrade marker instead of a bare "机械已验".
- An empty rendered string is never delivered as passed — it is withheld with a
  review point; a proximity intent on a host with no proximity operator is
  rendered via the proximity table's declared fallback + review point, never
  silently dropped.

Zero new dependencies: stdlib + PyYAML (already used by linter) + the four sibling
mechanical modules. Network (MeSH/ERIC verify, optional deep-link live check) is
reachable only through the injected/config path so tests stay offline.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import deeplink as _deeplink
from . import linter as _linter
from . import proximity as _prox
from . import vocab_verify as _vocab

# Reuse the linter's card loader / host resolver — one SSOT for card parsing.
load_card = _linter.load_card
resolve_card_name = _linter.resolve_card_name

SCHEMA_VERSION = "1.0"
QUALITY_CLAIM = "professional first draft with flagged review points"

#: The three standing global review points that every export carries (13 §2.1
#: global_review_points) — they underwrite the "初稿 + 复核点" quality claim.
_STANDING_GLOBAL_REVIEW_POINTS = [
    "受控词机械验证仅覆盖 MeSH/ERIC；Emtree/CINAHL/APA/CMeSH 为 LLM 建议，须在目标库人工核对。",
    "订阅墙平台（WOS/Scopus/Embase/Ovid/EBSCO 等）执行需机构登录，本工具未实测墙内行为。",
    "注册制 SR：本导出是专业初稿，非署名成品——受控词请在目标库人工复核，订阅墙平台请机构账号执行。",
]

#: Default supplementary-search block (13 §2.1 supplementary / §1.1 §4). Emitted as
#: a one-line honesty note; the caller may override/extend via ``supplementary=``.
_DEFAULT_SUPPLEMENTARY = {
    "clinicaltrials_gov": {
        "role": "registry", "mecir": "C27 mandatory", "promoted_to_strategy": False,
        "note": "试验注册库（MECIR C27 强制）：如为注册制 SR，请补 ClinicalTrials.gov 字段"
                "适配检索式 + A 档深链。",
    },
    "who_ictrp": {
        "role": "registry", "deep_link": "https://trialsearch.who.int",
        "kind": "browser_entry",
        "note": "WHO ICTRP 官网检索入口（浏览器检索，非布尔式导出，PRISMA-S item 3）。",
    },
    "google_scholar": {
        "role": "supplementary", "reproducible": False,
        "note": "补充/灰文源：记录前 1000 条、title-only 抓灰文（Haddaway 2015）；"
                "结果不可复现（PRISMA-S item 4）。",
    },
    "grey_literature": {
        "role": "grey", "mecir": "C28 highly-desirable",
        "note": "灰色文献门户（CADTH Grey Matters 等，PRISMA-S item 4）。",
    },
}

_METHODOLOGY_REFS = [
    "Cochrane Handbook Ch.4（检索方法学）",
    "PRESS 2015 Guideline Statement（McGowan et al. 2016, J Clin Epidemiol）",
    "PRISMA-S 2021（Rethlefsen et al.）— item 8 full search strategies",
]


# ---------------------------------------------------------------------------
# Card-shape -> render style
# ---------------------------------------------------------------------------

def _field_tag_values(card: Dict) -> List[str]:
    return [str(v) for v in (card.get("field_tags", {}) or {}).values() if v]


def render_style(card: Dict) -> str:
    """Classify a host's render style from the *shape* of its card (never its name).

    - ``cjk``       — the card declares ``match_operators`` (CNKI-style 字段+匹配符).
    - ``equals``    — field tags look like ``TS=`` (WoS/Scopus one-wrapper form).
    - ``bracket``   — field tags look like ``[tiab]`` (PubMed per-term tag form).
    - ``colon``     — field tags look like ``title:`` (ERIC free-site prefix form).
    - ``paren``     — a field tag is a single paren-wrap code ``TITLE-ABS-KEY(...)``
      (Scopus): the WHOLE query must be wrapped in that code (Gate2 FG1 #3 — a
      bare unfielded string is not legal Scopus advanced-search syntax).
    - ``unfielded`` — no recognisable field-tag surface -> bare/quoted terms.
    """
    if card.get("match_operators"):
        return "cjk"
    values = _field_tag_values(card)
    if any(re.search(r"[A-Za-z]{2,}=", v) for v in values):
        return "equals"
    if any("[" in v for v in values):
        return "bracket"
    if any(v.rstrip().endswith(":") for v in values):
        return "colon"
    if any(re.fullmatch(r"[A-Z][A-Z0-9\-]*\(\.\.\.\)", v.strip()) for v in values):
        return "paren"
    return "unfielded"


def _paren_wrap_code(tags: Dict) -> str:
    """The paren-wrap field code of a ``paren``-style host (``TITLE-ABS-KEY``)."""
    for k in ("title_abstract_keyword", "topic", "title_abstract", "all"):
        v = str(tags.get(k) or "").strip()
        if re.fullmatch(r"[A-Z][A-Z0-9\-]*\(\.\.\.\)", v):
            return v.split("(", 1)[0]
    return ""


def _is_cjk_host(card: Dict) -> bool:
    """CJK-native render host (CNKI/万方/SinoMed) — identified by the card's
    half-width mandate (``special_chars_escape`` 半角铁律), the same card-shape
    signal linter L7 keys on. These hosts take their word faces from
    ``blocks[].free_text_zh`` only (Gate2 D-a)."""
    return "半角" in str(card.get("special_chars_escape") or "")


# ---------------------------------------------------------------------------
# Vocabulary routing (card controlled-vocab name -> verify track + candidate key)
# ---------------------------------------------------------------------------

# Normalised vocab label -> canonical verify key. Matched by EXACT equality after
# case/whitespace normalisation — NEVER by substring (Gate2 FG1 #1): substring
# matching routed "CMeSH" into mesh and "Emtree … MeSH … APA Thesaurus" into
# whichever alias iterated first, injecting cross-vocabulary candidates and
# free-API-"verifying" no-API vocabularies (26b P1-2, A-5/A-6 violations).
# Two families of keys live here:
#   1. short labels as used in concept_model.controlled_vocab_candidates keys;
#   2. the exact controlled_vocab.name strings of the in-git syntax cards (the
#      card set is the SSOT and finite — extend when a card is added/renamed).
# A label NOT in this table normalises to itself (原样): its candidates only match
# a card carrying the identical label, and vocab_verify routes every unknown
# label to the honest pending_manual track — never fake-verified.
_VOCAB_KEY_ALIASES = {
    # -- short candidate-key labels (concept_model.controlled_vocab_candidates) --
    "mesh": "mesh",
    "mesh terms": "mesh",
    "eric": "eric",
    "eric descriptors": "eric",
    "eric thesaurus": "eric",
    "emtree": "emtree",
    "cinahl": "cinahl",
    "cinahl headings": "cinahl",
    "cinahl subject headings": "cinahl",
    "apa": "apa",
    "apa thesaurus": "apa",
    "psycinfo": "apa",
    "cmesh": "cmesh",
    "cbm": "cmesh",
    # -- exact card controlled_vocab.name strings (syntax_cards/*.md) --
    "mesh (via search manager)": "mesh",                       # cochrane_central
    "eric thesaurus descriptors（受控叙词）": "eric",             # eric
    ("emtree (embase-on-ovid) ; medline-on-ovid 用 mesh ; "
     "psycinfo-on-ovid 用 apa thesaurus"): "emtree",            # embase_ovid
    "cinahl subject headings (cinahl headings)": "cinahl",     # cinahl_ebsco
    "apa thesaurus of psychological index terms (psycinfo)": "apa",   # psycinfo_ebsco
    "apa thesaurus of psychological index terms (via ovid)": "apa",   # psycinfo_ovid
}


def _norm_vocab(name: Optional[str]) -> Optional[str]:
    """Canonical verify key for a vocab label — exact-match lookup, no substrings.

    Unknown labels come back AS-IS (case/whitespace-normalised): they are never
    mistaken for a known vocabulary, and verify_term routes them to the honest
    pending_manual track (Gate2 FG1 #1: 未知词表 → 原样 + pending_manual)."""
    if not name:
        return None
    low = " ".join(str(name).strip().lower().split())
    return _VOCAB_KEY_ALIASES.get(low, low)


def platform_vocab(card: Dict) -> Optional[str]:
    """The canonical controlled-vocab key this host uses (None = no CV track).

    Card-driven: a card whose ``controlled_vocab.verification`` is
    ``not_applicable`` (ACM CCS facet, WoS/Scopus/CNKI no-table hosts) has NO
    search-string CV track regardless of its display name."""
    cv = card.get("controlled_vocab", {}) or {}
    if not cv.get("name"):
        return None
    if str(cv.get("verification") or "").strip().lower() == "not_applicable":
        return None
    return _norm_vocab(cv.get("name"))


def _candidates_for(block: Dict, vocab_key: Optional[str]) -> List[str]:
    """Pull the concept block's controlled-vocab candidates for ``vocab_key``."""
    if not vocab_key:
        return []
    cands = block.get("controlled_vocab_candidates") or {}
    for k, terms in cands.items():
        if _norm_vocab(k) == vocab_key:
            return [str(t) for t in (terms or []) if str(t).strip()]
    return []


# ---------------------------------------------------------------------------
# Term rendering
# ---------------------------------------------------------------------------

def _is_multi_token(term: str) -> bool:
    return len(str(term).split()) > 1


def _first_token(value: Optional[str]) -> str:
    """The leading operator/field token of a verbose card value ("%= (相关…)" -> "%=")."""
    return str(value or "").strip().split()[0] if str(value or "").strip() else ""


def _boolean(card: Dict, key: str, default: str) -> str:
    val = (card.get("boolean", {}) or {}).get(key)
    return str(val).strip() if val else default


def _truncated_stem(term: str, block: Dict) -> Optional[str]:
    """The truncation stem for ``term`` if the block declares one (symbol stripped)."""
    ti = block.get("truncation_intent") or {}
    if term in ti and ti[term] is not None:
        return str(ti[term]).rstrip("*$?").strip()
    return None


#: Card ``truncation.phrase_truncation`` values that mean "do NOT apply word
#: truncation on this host" — either the host has no wildcard, or the wildcard is
#: discouraged/side-effecting (PubMed ``*`` closes auto-term-mapping, ERIC/CNKI n/a).
#: A single platform-independent ``truncation_intent`` therefore lands as a native
#: wildcard only where the host treats truncation as a normal, safe idiom (WoS/
#: Scopus/Embase "allowed") — matching the conservative 13 §1.2 PubMed example (A-4).
_NO_TRUNCATION_PHRASE = {"discouraged", "n/a", "none", ""}


def _apply_truncation(term: str, block: Dict, card: Dict) -> str:
    """Return the surface form of a free-text term, applying host truncation.

    Applies the block's truncation intent (``stem + wildcard``) ONLY when the host
    has a multi-char wildcard AND does not discourage it (card
    ``truncation.phrase_truncation``). A host with no/discouraged truncation —
    PubMed (``*`` closes ATM), ERIC/CNKI — keeps the plain term, so the export stays
    conservative there exactly like the 13 §1.2 PubMed example (A-4)."""
    stem = _truncated_stem(term, block)
    trunc = card.get("truncation", {}) or {}
    multi = trunc.get("multi_char")
    phrase_rule = str(trunc.get("phrase_truncation", "") or "").strip().lower()
    if stem is not None and multi and phrase_rule not in _NO_TRUNCATION_PHRASE:
        return f"{stem}{multi}"
    return str(term)


def _quote(term: str, quote_pair: str) -> str:
    """Wrap ``term`` in the card's phrase quote (``""`` -> "term", "单引号" -> 'term')."""
    if "单引号" in quote_pair or quote_pair.strip() in ("''", "'"):
        return f"'{term}'"
    return f'"{term}"'


def _render_free_term(term: str, block: Dict, card: Dict, style: str) -> str:
    surface = _apply_truncation(term, block, card)
    quote_pair = str((card.get("phrase", {}) or {}).get("quote", '""'))
    tags = card.get("field_tags", {}) or {}

    if style == "cjk":
        field = str(tags.get("subject_heading") or tags.get("title_abstract") or "SU")
        op = _first_token((card.get("match_operators", {}) or {}).get("relevance")) or "%="
        return f"{field} {op} '{term}'"

    if style == "bracket":
        tag = str(tags.get("title_abstract") or tags.get("text_word") or tags.get("all") or "")
        body = _quote(surface, quote_pair) if _is_multi_token(surface) else surface
        return f"{body}{tag}"

    # equals / colon / unfielded: no per-term field tag (or unfielded free text)
    return _quote(surface, quote_pair) if _is_multi_token(surface) else surface


#: EBSCO-style controlled-heading example embedded in a card CV field value, e.g.
#: ``(MH "Pregnancy in Diabetes+")`` (cinahl explode) / ``DE "exact descriptor"``
#: (psycinfo no_explode) — generalised into a render template. Surrounding parens
#: must be balanced (both present or both absent) for the example to count.
_CV_EXAMPLE_RE = re.compile(r'(\(?)([A-Z]{2,3})\s+"([^"+]+?)(\+?)"(\)?)')

#: Split a card CV field value into its mechanical head vs the trailing prose
#: note: "exp 主题词/  (爆炸)" -> "exp 主题词/" ; "/exp  (爆炸，含下位词)" -> "/exp".
_CV_NOTE_SPLIT = re.compile(r"\s{2,}|[（(]")


def _cv_head(value) -> str:
    return _CV_NOTE_SPLIT.split(str(value or "").strip(), 1)[0].strip()


def _cv_template(card: Dict, style: str, explode: bool) -> Optional[str]:
    """Per-term controlled-vocab render template (``{term}`` placeholder), derived
    ONLY from what the card mechanically declares (Gate2 D-d). Returns None when
    the card's CV syntax cannot be templated mechanically — the caller then OMITS
    the CV clause and surfaces a review point instead of emitting illegal syntax
    (绝不输出非法语法). Derivation sources, in order:

    1. ``controlled_vocab.machine_expr`` — the card's explicit machine-writable
       form (SinoMed CMeSH ``"<主题词>/全部树/全部副主题词"`` = explode + all
       subheadings), used when exploding.
    2. ``controlled_vocab.explode`` / ``no_explode`` field forms (preferring the
       requested explosion state; falling back to the other only when it alone is
       mechanically expressible — e.g. APA explode is a Thesaurus-UI action, so
       the paste form is the no-explode ``DE "term"``):
       - an embedded EBSCO-style example  -> ``(MH "{term}+")`` / ``DE "{term}"``
       - a bare suffix code ``/exp``      -> ``'{term}'/exp``   (embase.com)
       - an Ovid placeholder ``exp 主题词/`` or ``exp 词/`` -> ``exp {term}/``
    3. Field-tag shape fallbacks: a prefix-colon subject tag (``descriptor:``) ->
       ``descriptor:"{term}"``; a postfix-bracket subject tag on a host whose
       free-text tags are ALSO postfix brackets (PubMed) -> ``"{term}"[mh]``.
       A bracket subject tag on a colon-tag host (Cochrane, where the term goes
       INSIDE the brackets) is NOT mechanically renderable -> None (omit).
    """
    cv = card.get("controlled_vocab", {}) or {}
    tags = card.get("field_tags", {}) or {}
    sh_tag = str(tags.get("subject_heading") or "").strip()
    quote_pair = str((card.get("phrase", {}) or {}).get("quote", '""'))

    if explode and cv.get("machine_expr"):
        head = _cv_head(cv["machine_expr"])
        for ph in ("<主题词>", "<term>"):
            if ph in head:
                return head.replace(ph, "{term}")

    for key in (("explode", "no_explode") if explode else ("no_explode", "explode")):
        val = str(cv.get(key) or "")
        if not val:
            continue
        m = _CV_EXAMPLE_RE.search(val)
        if m and bool(m.group(1)) == bool(m.group(5)):
            return f'{m.group(1)}{m.group(2)} "{{term}}{m.group(4)}"{m.group(5)}'
        head = _cv_head(val)
        if re.fullmatch(r"/[A-Za-z]+", head):
            return _quote("{term}", quote_pair) + head
        hm = re.fullmatch(r"(exp\s+)?(主题词|词)/", head)
        if hm:
            return f"{hm.group(1) or ''}{{term}}/"

    if sh_tag.endswith(":"):
        return f'{sh_tag}"{{term}}"'
    if style == "bracket" and re.fullmatch(r"\[[^\[\]]+\]", sh_tag):
        ta = str(tags.get("title_abstract") or tags.get("text_word")
                 or tags.get("all") or "").strip()
        if re.fullmatch(r"\[[^\[\]]+\]", ta):
            return _quote("{term}", quote_pair) + sh_tag
    return None


def _proximity_clause(
    block: Dict, card: Dict, host: str, cjk: bool, notes: List[str]
) -> Optional[str]:
    """Render a block-level proximity intent via proximity.py — degrading HONESTLY.

    ``proximity_intent`` = ``{"terms": ["a","b"], "k": N, "ordered": bool}``.
    - supported host    -> the native operator expression (canonical ``k`` is never
      hand-computed — A-3);
    - no-proximity host -> the proximity table's declared ``fallback`` (AND-join or
      quoted phrase) + a review note — never silently dropped (Gate2 FG1 #6);
    - cjk host          -> not rendered (the intent's word faces belong to the
      Latin channel; D-a forbids rendering them into a Chinese database) + a note;
    - conversion failure -> omitted + a note (never a fabricated operator)."""
    pi = block.get("proximity_intent")
    if not pi:
        return None
    terms = [str(t) for t in (pi.get("terms") or []) if str(t).strip()]
    if len(terms) < 2:
        return None
    if cjk:
        notes.append(
            "proximity_intent 未在中文宿主渲染（其词面属拉丁语言通道，D-a 禁止渲染进中文库）"
            "——如需位置算符请按语法卡以中文词面人工组装"
        )
        return None
    quote_pair = str((card.get("phrase", {}) or {}).get("quote", '""'))
    k = int(pi.get("k", 0))
    ordered = bool(pi.get("ordered"))
    try:
        r = _prox.render(host, terms, k, ordered=ordered)
    except _prox.UnknownHostError:
        # Card stems and proximity-shell keys differ for a few hosts (acm_dl vs
        # acm): retry with the stem's first token before giving up, so the
        # table's declared fallback is still reached (never silently dropped).
        try:
            r = _prox.render(host.split("_")[0], terms, k, ordered=ordered)
        except Exception as exc:
            notes.append(f"邻近意图未渲染（换算表不可用：{exc}）——已省略，请按语法卡人工组装")
            return None
    except Exception as exc:
        notes.append(f"邻近意图未渲染（换算表不可用：{exc}）——已省略，请按语法卡人工组装")
        return None
    if r.supported and r.expression:
        return r.expression
    fb = str(r.fallback or "AND_or_phrase")
    if fb.upper().startswith("AND"):
        and_op = _boolean(card, "and", "AND")
        expr = "(" + f" {and_op} ".join(terms) + ")"
    else:
        expr = _quote(" ".join(terms), quote_pair)
    notes.append(
        f"本宿主无邻近算符：proximity_intent({' / '.join(terms)}, k={pi.get('k')}) "
        f"已按换算表 fallback（{fb}）降级为 {expr} ——请复核语义/召回影响（A-3）"
    )
    return expr


def _render_block(
    block: Dict,
    card: Dict,
    style: str,
    vocab_key: Optional[str],
    host: str,
    *,
    cjk: bool,
    cv_tmpl: Optional[str],
    not_found: frozenset,
    notes: List[str],
) -> Optional[str]:
    """One concept block's inner OR-join.

    Returns None when a cjk host has no Chinese word faces for this block —
    the D-a withhold signal (绝不把英文词渲染进中文库). ``not_found`` candidates
    are culled from the CV clause and downgraded into the free-text track
    (13 spec §5.3); a host whose CV syntax has no mechanical template renders no
    CV clause at all (the caller surfaces the D-d review point)."""
    or_op = _boolean(card, "or", "OR")
    parts: List[str] = []

    cands = _candidates_for(block, vocab_key)
    live = [c for c in cands if c not in not_found]
    downgraded = [c for c in cands if c in not_found]
    if live and cv_tmpl:
        parts.extend(cv_tmpl.replace("{term}", c) for c in live)

    if cjk:
        terms = [str(t).strip() for t in (block.get("free_text_zh") or [])
                 if str(t).strip()]
        if not terms:
            return None
    else:
        terms = [str(t).strip() for t in (block.get("free_text") or [])
                 if str(t).strip()]
        seen = {t.lower() for t in terms}
        terms.extend(d for d in downgraded if d.lower() not in seen)

    parts.extend(_render_free_term(t, block, card, style) for t in terms)

    prox = _proximity_clause(block, card, host, cjk, notes)
    if prox:
        parts.append(prox)
    return f" {or_op} ".join(parts)


# ---------------------------------------------------------------------------
# Query assembly (per-style layout)
# ---------------------------------------------------------------------------

def _blocks(concept_model: Dict) -> List[Dict]:
    return [b for b in (concept_model.get("blocks") or []) if isinstance(b, dict)]


def _parse_operator_logic(logic, block_ids: List[str]):
    """Parse the declared block-level logic ``"(P) AND (I) AND (O)"`` (Gate2 D-b).

    Returns ``(ordered_ids, op_word, error, note)``. Only the flat mechanical
    subset is parsed: block ids — **parenthesised ``(P)`` OR bare ``B1``** —
    joined by ONE uniform operator (AND | OR). Anything else — mixed operators,
    NOT/other operators, nesting, unknown or duplicate ids — returns an ``error``
    and the caller withholds the strategy (机械层绝不静默改写逻辑). Missing/empty
    logic falls back to AND-joining all blocks (the A-1 domain default) with an
    honest note. Accepting bare ids (e.g. ``"B1 AND B2 AND B3"``, unambiguously
    the same all-AND intent as the parenthesised form) closes a blind-test
    withhold trap (Gate3 finding A) without weakening D-b: genuinely ambiguous
    logic still hits the error branches below."""
    if logic is None or not str(logic).strip():
        return (
            list(block_ids), "AND", None,
            "concept_model 未声明 operator_logic——按默认块间 AND 连接（A-1）",
        )
    s = str(logic).strip()
    if s.count("(") != s.count(")"):
        return None, None, f"operator_logic 括号不配平：{s!r}", None
    _bool_ops = ("AND", "OR", "NOT")
    ids: List[str] = []
    ops: List[str] = []
    expect = "id"
    # A token is a parenthesised group ``(X)`` or a bare identifier ``B1`` /
    # ``P`` (letter-led, digits allowed). Classification is by position: in an
    # id-slot a bare token is a block id (an operator keyword there is malformed);
    # in an op-slot a bare token is the operator (validated against AND/OR below).
    for m in re.finditer(r"\(\s*([^()]+?)\s*\)|([A-Za-z][A-Za-z0-9_]*)", s):
        if m.group(1) is not None:
            if expect != "id":
                return None, None, f"operator_logic 不可机械解析：{s!r}", None
            ids.append(m.group(1))
            expect = "op"
        elif expect == "id":
            if m.group(2).upper() in _bool_ops:
                return None, None, f"operator_logic 不可机械解析：{s!r}", None
            ids.append(m.group(2))
            expect = "op"
        else:
            ops.append(m.group(2).upper())
            expect = "id"
    if expect == "id" or not ids:
        return None, None, f"operator_logic 不可机械解析：{s!r}", None
    bad = [o for o in ops if o not in ("AND", "OR")]
    if bad:
        return None, None, (
            f"operator_logic 含机械层不支持的算符 {bad}（仅支持块间 AND/OR）：{s!r}"
        ), None
    if len(set(ops)) > 1:
        return None, None, (
            f"operator_logic 混用 AND/OR（机械层不解析优先级，请显式分组改写）：{s!r}"
        ), None
    if len(ids) != len(set(ids)):
        return None, None, f"operator_logic 重复引用同一块：{s!r}", None
    unknown = [i for i in ids if i not in block_ids]
    if unknown:
        return None, None, f"operator_logic 引用未知块 {unknown}：{s!r}", None
    note = None
    unref = [b for b in block_ids if b not in ids]
    if unref:
        note = f"块 {unref} 未被 operator_logic 引用——按声明逻辑未渲染"
    return ids, (ops[0] if ops else "AND"), None, note


def _assemble(
    concept_model: Dict,
    card: Dict,
    style: str,
    vocab_key: Optional[str],
    host: str,
    *,
    cjk: bool = False,
    cv_tmpl: Optional[str] = None,
    not_found: frozenset = frozenset(),
) -> Dict:
    """Assemble one host's strategy from the concept model.

    Returns ``{"string", "lines", "notes", "reason"}``. A non-None ``reason``
    means the strategy MUST be withheld (never emitted): unparseable
    operator_logic (D-b), missing Chinese word faces on a cjk host (D-a), or an
    empty render — an empty string is never delivered as passed (Gate2 FG1 #6).
    ``notes`` are honest review points collected during assembly."""
    notes: List[str] = []
    blocks = _blocks(concept_model)
    ids = [str(b.get("id")) for b in blocks]
    ordered, op_word, err, note = _parse_operator_logic(
        concept_model.get("operator_logic"), ids)
    if note:
        notes.append(note)
    if err:
        return {"string": None, "lines": None, "notes": notes, "reason": err}

    by_id = {str(b.get("id")): b for b in blocks}
    inners: List[str] = []
    for bid in ordered:
        inner = _render_block(
            by_id[bid], card, style, vocab_key, host,
            cjk=cjk, cv_tmpl=cv_tmpl, not_found=not_found, notes=notes)
        if inner is None:
            return {
                "string": None, "lines": None, "notes": notes,
                "reason": (f"缺中文词项：cjk 宿主需 blocks[].free_text_zh（块 {bid} 未提供）"
                           "——绝不把英文词面渲染进中文库（D-a）"),
            }
        if not inner:
            return {
                "string": None, "lines": None, "notes": notes,
                "reason": f"块 {bid} 无可渲染词项——无法按 operator_logic 组装检索式",
            }
        inners.append(inner)
    if not inners:
        return {"string": None, "lines": None, "notes": notes,
                "reason": "概念模型为空（无概念块可渲染）"}

    tags = card.get("field_tags", {}) or {}
    join_op = _boolean(card, "and" if op_word == "AND" else "or", op_word)
    wrapped = [f"({i})" for i in inners]

    if style == "equals":
        field = str(tags.get("topic") or tags.get("title_abstract") or tags.get("all") or "")
        body = f"\n  {join_op} ".join(wrapped)
        strategy_string = f"{field}(\n  {body}\n)"
    elif style == "paren":
        code = _paren_wrap_code(tags)
        body = f"\n  {join_op} ".join(wrapped)
        strategy_string = f"{code}(\n  {body}\n)" if code else f" {join_op} ".join(wrapped)
    elif style == "cjk":
        strategy_string = f"\n{join_op} ".join(wrapped)
    elif style == "bracket":
        strategy_string = f"\n{join_op}\n".join(wrapped)
    else:  # colon / unfielded
        strategy_string = f" {join_op} ".join(wrapped)

    strategy_lines = _line_form(inners, card, style, join_op, tags)
    return {"string": strategy_string, "lines": strategy_lines,
            "notes": notes, "reason": None}


#: Line-search grammar sample parsed off the card's ``line_search.syntax``
#: ("#1 AND #2" -> prefix "#" / "S1 AND S2" -> prefix "S" / Ovid "1 and 2" ->
#: bare numbers, lowercase combine). A card with no parsable numbered-line sample
#: gets NO fabricated line form — e.g. CNKI's line_search is a 7-row advanced-UI
#: description with no #N reference grammar (Gate2 FG1 #7 / 26b P3-4).
_LINE_SYNTAX_RE = re.compile(r"(#|S)?1\s+(AND|and|OR|or)\s+(?:#|S)?2")


def _line_form(
    inners: List[str], card: Dict, style: str, join_op: str, tags: Dict
) -> Optional[List[str]]:
    ls = card.get("line_search", {}) or {}
    if not ls.get("supported"):
        return None
    m = _LINE_SYNTAX_RE.search(str(ls.get("syntax") or ""))
    if not m:
        return None
    prefix = m.group(1) or ""
    op = join_op.lower() if m.group(2).islower() else join_op
    lines: List[str] = []
    for i, inner in enumerate(inners, 1):
        if style == "equals":
            field = str(tags.get("topic") or tags.get("title_abstract") or "")
            lines.append(f"{prefix}{i} {field}({inner})")
        elif style == "paren":
            code = _paren_wrap_code(tags)
            lines.append(f"{prefix}{i} {code}({inner})" if code
                         else f"{prefix}{i} {inner}")
        elif style == "cjk":
            lines.append(f"{prefix}{i} ({inner})")
        else:  # bracket / colon / unfielded
            lines.append(f"{prefix}{i} {inner}")
    combine = f" {op} ".join(f"{prefix}{i}" for i in range(1, len(inners) + 1))
    lines.append(f"{prefix}{len(inners) + 1} {combine}")
    return lines


# ---------------------------------------------------------------------------
# Field scope / vocab status label
# ---------------------------------------------------------------------------

def _field_scope(card: Dict, style: str, has_cv: bool) -> str:
    tags = card.get("field_tags", {}) or {}
    if style == "cjk":
        return f"主题字段 {tags.get('subject_heading', 'SU')} 相关匹配（%=）"
    ta = tags.get("title_abstract") or tags.get("topic") or tags.get("all") or ""
    base = f"题名/摘要 {ta}".strip()
    if has_cv:
        cvname = (card.get("controlled_vocab", {}) or {}).get("name") or ""
        cvtag = tags.get("subject_heading") or ""
        return f"{base} + {cvname} {cvtag}".strip()
    return base


def _vocab_status_summary(results: List[Dict]) -> Optional[str]:
    """Strategy-level roll-up of per-term vocab statuses (13 §1.1 三态 + 降级角标).

    Status comparison is EXACT equality — the FG2 L11 discipline, never substring.
    A set containing ``not_found`` terms is never labelled a bare "机械已验": those
    candidates were culled from the CV clause and downgraded to free text (13 spec
    §5.3), so the label carries the downgrade marker (Gate2 FG1 #2 / 26b P1-1 —
    the old ``summarize_vocab_status`` folded not_found into "机械已验", stamping
    a strategy that still carried the hallucinated descriptor)."""
    if not results:
        return None
    statuses = [str(r.get("status") or "") for r in results]
    if any(s in ("pending_manual", "unverified") for s in statuses):
        return "语法已验·词表待核"
    if all(s in ("verified", "not_found") for s in statuses):
        if any(s == "not_found" for s in statuses):
            return "机械已验·含降级"
        return "机械已验"
    return "语法已验·词表待核"


def _vocab_status_label(has_cv: bool, cv_summary: Optional[str], card: Dict) -> str:
    """The strategy-level 三态 label (13 §1.1 / §2.1).

    has CV                    -> vocab_verify roll-up (机械已验 | 语法已验·词表待核)
    no CV + CJK half-width    -> 语法已验·无受控词表   (CNKI: syntax linted, no table)
    no CV + otherwise         -> 结构参考              (WoS/Scopus: wall, no table)
    """
    if has_cv and cv_summary:
        return cv_summary
    esc = str(card.get("special_chars_escape", "") or "")
    if "半角" in esc:
        return "语法已验·无受控词表"
    return "结构参考"


# ---------------------------------------------------------------------------
# PRESS six-domain mechanical pre-fill (LLM-judgement domains -> placeholder)
# ---------------------------------------------------------------------------

def _press_check(lint_res, has_cv: bool, cv_summary: Optional[str]) -> Dict:
    """Pre-fill the PRESS six-domain self-review (press_checklist.md).

    Mechanically-decidable domains (2 boolean/proximity, 5 spelling/syntax, part of
    6 limits) are filled from linter findings. The LLM-semantic domains (1 translation,
    4 text words, the semantic part of 3 subject headings) get a ``pending_review``
    placeholder — those are the layer-1 LLM self-review's job (role isolation)."""
    by = {}
    for f in lint_res.findings:
        by.setdefault(f.rule, []).append(f)

    def _mech(rules: List[str], ok_note: str, bad_prefix: str):
        hits = [str(f) for r in rules for f in by.get(r, []) if f.level == _linter.ERROR]
        if hits:
            return {"verdict": "⚠️", "note": f"{bad_prefix}：" + "; ".join(hits)}
        return {"verdict": "pass", "note": ok_note}

    d3_note = "受控词状态戳机械已核（L11）；主题词相关性/爆炸/副主题需 LLM 判断。"
    if has_cv and cv_summary == "机械已验·含降级":
        d3 = {"verdict": "⚠️", "note": ("部分受控词候选经免费 API 核验 Count=0，"
                                        "已降级为自由词（见复核点）；") + d3_note}
    elif has_cv and cv_summary and cv_summary != "机械已验":
        d3 = {"verdict": "⚠️", "note": f"{cv_summary}：无免费 API 的受控词须人工核对；" + d3_note}
    elif has_cv:
        d3 = {"verdict": "pass", "note": d3_note}
    else:
        d3 = {"verdict": "pass", "note": "本平台无受控词表（纯自由词）；主题词域不适用。"}

    return {
        "d1_translation": {
            "verdict": "pending_review",
            "note": "LLM 语义域：每 OR 块是否单一概念、PICO 元素多寡、召回宽窄——需新视角 self-review。",
        },
        "d2_boolean": _mech(["L1", "L2", "L4"], "括号/引号配平、算符大小写、邻近家族机械校验通过。", "布尔/邻近机械项"),
        "d3_subject_headings": d3,
        "d4_text_words": {
            "verdict": "pending_review",
            "note": "LLM 语义域：拼写变体、同义词、缩写全称是否齐全——需 self-review（截词位置已过 L3）。",
        },
        "d5_spelling_syntax": _mech(["L3", "L5", "L7", "L10"], "字段标签合法、半角、无孤儿行、截词符正确。", "拼写/语法机械项"),
        "d6_limits_filters": _mech(["L9"], "默认不加语言/日期/文献类型限制（E12 底线）；CENTRAL 未误加 RCT 过滤器。", "限制/过滤器机械项"),
    }


def _collect_review_points(press: Dict, extra: List[str]) -> List[str]:
    pts = list(extra)
    for dom in press.values():
        if isinstance(dom, dict) and dom.get("verdict") == "⚠️":
            pts.append(dom.get("note", ""))
    return [p for p in pts if p]


# ---------------------------------------------------------------------------
# Per-platform strategy build
# ---------------------------------------------------------------------------

def build_strategy(
    platform: str,
    concept_model: Dict,
    *,
    register: str = "audit",
    config=None,
    esearch_fn: Optional[Callable] = None,
    vocab_session=None,
    verify_vocab: bool = True,
    live_verify_links: bool = False,
    deeplink_session=None,
    cards_dir: Optional[Path] = None,
) -> Dict:
    """Build one ``strategies[]`` element (13 §2.1) for ``platform``.

    Reads the syntax card, renders the concept model, verifies controlled vocab,
    builds the deep link, and runs the linter gate. **A linter-rejected string is
    withheld** (strategy_string/lines -> None) with a review point (never emitted).
    Every network touch (vocab verify, optional live link check) goes through the
    injected ``esearch_fn`` / ``*_session`` / ``config`` so tests stay offline.
    """
    card = load_card(platform, cards_dir=cards_dir)
    stem = resolve_card_name(platform)
    style = render_style(card)
    vocab_key = platform_vocab(card)
    cjk = _is_cjk_host(card)
    explode_default = (card.get("controlled_vocab", {}) or {}).get("explode") not in (None, "")

    # ---- controlled-vocabulary verification (layer 3, MeSH/ERIC real, rest flagged)
    cv_items: List[Dict] = []
    for block in _blocks(concept_model):
        for cvterm in _candidates_for(block, vocab_key):
            cv_items.append({"term": cvterm, "vocab": vocab_key, "explode": bool(explode_default)})

    if cv_items and verify_vocab:
        controlled_vocab_terms = _vocab.verify_terms(
            cv_items, config=config, esearch_fn=esearch_fn, session=vocab_session,
        )
    else:
        # No network: stamp an honest "unverified" (still a valid L11 status stamp).
        # The display name comes from the canonical verify track (consistent with
        # the online path), falling back to the raw label for unknown vocabs.
        controlled_vocab_terms = [
            _vocab._result(
                it["term"],
                _vocab._VOCAB_TRACK.get(
                    str(it["vocab"]).lower(), (str(it["vocab"]), ""))[0],
                "unverified", explode=it.get("explode"),
                verification_method="free_api" if vocab_key in ("mesh", "eric") else "llm_suggest_only",
                review_point="受控词未核验（离线/未启用），须人工核对——非幻觉判定。",
            )
            for it in cv_items
        ] if cv_items else []
    has_cv = bool(controlled_vocab_terms)
    cv_summary = _vocab_status_summary(controlled_vocab_terms) if has_cv else None

    # not_found candidates are culled from the CV clause and downgraded to the
    # free-text track inside _render_block (13 spec §5.3 — Gate2 FG1 #2).
    not_found = frozenset(
        t.get("term") for t in controlled_vocab_terms if t.get("status") == "not_found"
    )
    cv_tmpl = _cv_template(card, style, explode_default) if vocab_key else None
    cv_omitted = (
        cv_tmpl is None
        and any(it["term"] not in not_found for it in cv_items)
    )

    # ---- render (layer 2) ----
    asm = _assemble(
        concept_model, card, style, vocab_key, stem,
        cjk=cjk, cv_tmpl=cv_tmpl, not_found=not_found,
    )
    strategy_string = asm["string"] or ""
    strategy_lines = asm["lines"]

    # ---- linter gate (layer 3) ----
    lint_res = _linter.lint(
        strategy_string, platform, cards_dir=cards_dir,
        filters_used=None, vocab_terms=controlled_vocab_terms or None,
    )
    linter_block = {
        "passed": lint_res.passed,
        "warnings": [str(f) for f in lint_res.warnings],
        "errors": [str(f) for f in lint_res.errors],
    }

    press = _press_check(lint_res, has_cv, cv_summary)

    # An assembly-withheld or EMPTY string is never delivered as passed (FG1 #6).
    withheld = (
        (not lint_res.passed)
        or bool(asm["reason"])
        or not strategy_string.strip()
    )
    extra_rp: List[str] = list(asm["notes"])
    if cv_omitted:
        extra_rp.append(
            "受控词候选未写入检索串：本宿主的受控词语法无法机械模板化"
            f"（D-d 绝不输出非法语法）——请按语法卡 {stem}.md 人工组装受控词子句"
        )
    if asm["reason"]:
        extra_rp.append(f"检索式已 withhold（未生成）：{asm['reason']}")
    elif not strategy_string.strip():
        extra_rp.append("检索式已 withhold：渲染结果为空串（空串不交付）")
    if not lint_res.passed:
        extra_rp.append(
            "机械校验未通过，检索式已 withhold（不输出无效串）：" + "; ".join(linter_block["errors"])
        )
    # per-term vocab flags surface as review points; not_found carries the §5.3
    # downgrade wording (已降级, not a mere suggestion).
    for t in controlled_vocab_terms:
        status = t.get("status")
        if status == "not_found":
            extra_rp.append(
                f"[{t.get('vocab')}] {t.get('term')}: 非规范 {t.get('vocab')} "
                "descriptor（免费 API Count=0）→ 已降级为自由词，不再作为受控词写入检索串"
            )
            continue
        rp = t.get("review_point")
        if rp and status in ("pending_manual", "unverified"):
            extra_rp.append(f"[{t.get('vocab')}] {t.get('term')}: {rp}")

    review_points = _collect_review_points(press, extra_rp)

    # ---- deep link (A-tier constructed; B/C surface the card template) ----
    card_dl = card.get("deep_link", {}) or {}
    if withheld:
        deep_link = {
            "platform": stem, "tier": card_dl.get("tier"), "url_kind": "withheld",
            "url": None, "verified_http": None, "verified_date": None,
            "note": "检索式未生成或未过机械校验，深链不构造（避免编码无效串）。",
        }
    else:
        deep_link = _deeplink.build_deep_link(
            platform, strategy_string,
            tier=card_dl.get("tier"), url_template=card_dl.get("url_template"),
        )
        if live_verify_links and deep_link.get("tier") == "A":
            deep_link = _deeplink.live_verify(deep_link, session=deeplink_session)

    vocab_label = _vocab_status_label(has_cv, cv_summary, card)

    out_string = None if withheld else strategy_string
    out_lines = None if withheld else strategy_lines

    return {
        "platform": card.get("platform", platform),
        "host": card.get("host"),
        "database": card.get("database"),
        "access": card.get("access"),
        "syntax_card_ref": f"references/search_export/syntax_cards/{stem}.md",
        "render_style": style,
        "strategy_lines": out_lines,
        "strategy_string": out_string,
        "field_scope": _field_scope(card, style, has_cv),
        "deep_link": deep_link,
        "vocab_verification_status": vocab_label,
        "controlled_vocab_terms": controlled_vocab_terms,
        "filters_used": [],
        "linter": linter_block,
        "press_check": press,
        "review_points": review_points,
        "prisma_s": {
            "item8_boolean_expression": out_string,
            "item1_database": f"{card.get('database') or platform} ({card.get('host') or ''})".strip(),
            "item9_limits": {"language": "none", "date": "none", "pub_type": "none"},
            "item10_filter": None,
        },
    }


# ---------------------------------------------------------------------------
# Top-level generation
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unwrap(concept_model_or_envelope: Dict) -> Dict:
    """Accept either the bare concept_model or a wrapper carrying it + meta."""
    if isinstance(concept_model_or_envelope, dict) and "concept_model" in concept_model_or_envelope:
        return concept_model_or_envelope
    return {"concept_model": concept_model_or_envelope}


def generate(
    concept_model: Dict,
    platforms: List[str],
    *,
    topic: str = "",
    framework: str = "PICO",
    register: str = "audit",
    language_space: str = "both",
    search_id: str = "",
    generated_at: Optional[str] = None,
    supplementary: Optional[Dict] = None,
    global_review_points: Optional[List[str]] = None,
    config=None,
    esearch_fn: Optional[Callable] = None,
    vocab_session=None,
    verify_vocab: bool = True,
    live_verify_links: bool = False,
    deeplink_session=None,
    cards_dir: Optional[Path] = None,
) -> Dict:
    """Produce the ``search_strategies.json`` dict (13 §2.1) — no file I/O.

    ``concept_model`` is the platform-independent IR (blocks + candidates + operator
    logic). ``platforms`` is the host list to render (STEP 2 discipline-routed by the
    caller). Everything else is meta or an injection point for offline tests."""
    strategies: List[Dict] = []
    extra_global: List[str] = []
    for platform in platforms:
        try:
            strat = build_strategy(
                platform, concept_model, register=register, config=config,
                esearch_fn=esearch_fn, vocab_session=vocab_session,
                verify_vocab=verify_vocab, live_verify_links=live_verify_links,
                deeplink_session=deeplink_session, cards_dir=cards_dir,
            )
            strategies.append(strat)
            for rp in strat.get("review_points", []):
                extra_global.append(f"[{strat.get('platform')}] {rp}")
        except _linter.UnknownHostError as exc:
            extra_global.append(f"[{platform}] 无语法卡，跳过：{exc}")

    grp = list(global_review_points or _STANDING_GLOBAL_REVIEW_POINTS) + extra_global

    return {
        "schema_version": SCHEMA_VERSION,
        "search_id": search_id,
        "generated_at": generated_at or _now_iso(),
        "topic": topic,
        "framework": framework,
        "register": register,
        "language_space": language_space,
        "quality_claim": QUALITY_CLAIM,
        "concept_model": concept_model,
        "strategies": strategies,
        "supplementary": supplementary if supplementary is not None else _DEFAULT_SUPPLEMENTARY,
        "global_review_points": grp,
        "prisma_s_item8_ref": "populates execution_log.json -> 8_full_search_strategies",
    }


# ---------------------------------------------------------------------------
# Markdown rendering (human-first, content-over-form; 13 §1.1)
# ---------------------------------------------------------------------------

def _md_escape_block(s: Optional[str]) -> str:
    return s if s else "(withheld — 见复核点)"


def render_markdown(record: Dict) -> str:
    """Render ``search_strategies.md`` from the JSON record (13 §1.1 layout)."""
    cm = record.get("concept_model", {}) or {}
    L: List[str] = []
    topic = record.get("topic") or "(untitled topic)"
    L.append(f"# 检索式导出 — {topic}")
    L.append(
        f"> 生成：{record.get('search_id') or '-'} · {record.get('generated_at')} · "
        f"框架 {record.get('framework')} · 档位 {record.get('register')} · "
        f"语言轨 {record.get('language_space')}"
    )
    L.append("> ⚠️ 质量声明：**专业初稿 + 标注复核点**。非「可署名直用 / 馆员级成品」。")
    L.append("> 注册制 SR：受控词请在目标库人工核对；订阅墙平台的执行需机构登录。")
    L.append("")

    # §0 concept model
    L.append("## 0. 概念模型（平台无关）")
    for b in _blocks(cm):
        syns = "、".join(b.get("free_text") or [])
        cv = b.get("controlled_vocab_candidates") or {}
        cv_str = "；".join(f"{k}: {', '.join(v)}" for k, v in cv.items()) if cv else "—"
        L.append(f"- **{b.get('id')}（{b.get('role')}）** {b.get('label') or ''}")
        L.append(f"  - 自由词：{syns or '—'}")
        zh = "、".join(b.get("free_text_zh") or [])
        if zh:
            L.append(f"  - 中文词项（cjk 宿主专用，D-a）：{zh}")
        L.append(f"  - 受控词候选：{cv_str}")
    L.append(f"- 块级逻辑：`{cm.get('operator_logic') or ''}`")
    for om in (cm.get("omitted_blocks") or []):
        L.append(f"- 略去块 {om.get('role')}：{om.get('reason')}")
    for note in (cm.get("register_notes") or []):
        L.append(f"- 档位取向：{note}")
    L.append("")

    # §1 per-platform blocks
    L.append("## 1. 逐平台区块")
    for s in record.get("strategies", []):
        dl = s.get("deep_link", {}) or {}
        tier = dl.get("tier")
        L.append(
            f"### {s.get('platform')} · {s.get('vocab_verification_status')} · "
            f"{tier or '-'} 档（{dl.get('url_kind')}）"
        )
        L.append("")
        L.append("**可粘贴检索式（单串合并版）**")
        L.append("```")
        L.append(_md_escape_block(s.get("strategy_string")))
        L.append("```")
        if s.get("strategy_lines"):
            L.append("**行式（PRISMA-S 原样复制用）**")
            L.append("```")
            L.extend(s["strategy_lines"])
            L.append("```")
        if dl.get("url"):
            L.append(f"- **深链（{tier} 档）**：{dl['url']}  [点此执行]")
        elif dl.get("url_template"):
            L.append(f"- **深链（{tier} 档）**：URL 结构 `{dl['url_template']}`（机构登录后可试；不绕墙）")
        else:
            L.append(f"- **深链（{tier} 档）**：无稳定无状态深链 → 交付=粘贴进目标库检索框的检索式本身。")
        L.append(f"- **字段范围**：{s.get('field_scope')}")
        cvt = s.get("controlled_vocab_terms") or []
        if cvt:
            statuses = "；".join(
                f"{t.get('term')}={t.get('status')}"
                + (f"({t.get('descriptor_ui')})" if t.get("descriptor_ui") else "")
                for t in cvt
            )
            L.append(f"- **受控词状态**：{statuses}")
        else:
            L.append("- **受控词状态**：无受控词表（纯自由词）")
        rps = s.get("review_points") or []
        L.append("- **复核点**：" + ("；".join(rps) if rps else "本平台无"))
        L.append("")

    # §2 PRESS summary (per platform, compact)
    L.append("## 2. PRESS 六域自评摘要")
    for s in record.get("strategies", []):
        L.append(f"**{s.get('platform')}**")
        for dom, val in (s.get("press_check") or {}).items():
            L.append(f"- {dom}: {val.get('verdict')} — {val.get('note')}")
        L.append("")

    # §3 global review points
    L.append("## 3. 全局复核点清单")
    for rp in record.get("global_review_points", []):
        L.append(f"- {rp}")
    L.append("")

    # §4 supplementary
    L.append("## 4. 补充检索建议（一行式）")
    for _k, v in (record.get("supplementary") or {}).items():
        if isinstance(v, dict) and v.get("note"):
            L.append(f"- {v['note']}")
    L.append("")

    # §5 provenance
    L.append("## 5. 溯源")
    for s in record.get("strategies", []):
        L.append(f"- {s.get('platform')} 语法卡：`{s.get('syntax_card_ref')}`")
    for ref in _METHODOLOGY_REFS:
        L.append(f"- 方法学出处：{ref}")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# File writing / one-shot run
# ---------------------------------------------------------------------------

def write_outputs(record: Dict, out_dir: Path) -> Dict[str, Path]:
    """Write ``search_strategies.json`` + ``search_strategies.md`` into ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "search_strategies.json"
    md_path = out_dir / "search_strategies.md"
    json_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(record), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def run(
    concept_model: Dict,
    platforms: List[str],
    out_dir: Path,
    **kwargs,
) -> Dict[str, Path]:
    """Generate + write both files. Returns ``{"json": path, "md": path}``."""
    record = generate(concept_model, platforms, **kwargs)
    return write_outputs(record, out_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main_cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys

    SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))

    parser = argparse.ArgumentParser(
        prog="search_export.generate",
        description=(
            "STEP 11.5 Search Strategy Export generator (layer 2/3). Input: a "
            "platform-independent concept_model JSON (13 §2.1) + a platform list. "
            "Output: $OUT/search_strategies.md + search_strategies.json. Linter-"
            "rejected strings are never emitted."
        ),
    )
    parser.add_argument(
        "--concept-model", required=True, type=Path,
        help="Path to the concept_model JSON (bare concept_model, or a wrapper "
             "{topic, framework, register, language_space, search_id, concept_model, "
             "platforms}).",
    )
    parser.add_argument(
        "--platforms", default=None,
        help="Comma-separated host list (e.g. pubmed,wos,cnki). Overrides a "
             "'platforms' key in the input file.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Output directory.")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--framework", default=None)
    parser.add_argument("--register", default=None, help="quick|standard|deep|audit")
    parser.add_argument("--language-space", default=None, help="en|zh|both")
    parser.add_argument("--search-id", default=None)
    parser.add_argument(
        "--no-verify-vocab", action="store_true",
        help="Skip the MeSH/ERIC free-API existence check (stamp terms 'unverified').",
    )
    parser.add_argument(
        "--live-verify-links", action="store_true",
        help="Live-GET each A-tier deep link to stamp a fresh verified_http/date.",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.concept_model).read_text(encoding="utf-8"))
    except OSError as exc:
        parser.error(f"cannot read --concept-model file: {exc}")
    except json.JSONDecodeError as exc:
        parser.error(f"--concept-model is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        parser.error("--concept-model must be a JSON object "
                     "(bare concept_model or wrapper)")
    env = _unwrap(payload)
    cm = env.get("concept_model", {})

    platforms = (
        [p.strip() for p in args.platforms.split(",") if p.strip()]
        if args.platforms
        else env.get("platforms")
    )
    if not platforms:
        parser.error("no platforms given (pass --platforms or a 'platforms' key)")

    config = None
    if not args.no_verify_vocab:
        try:
            from scripts.config import load_config  # type: ignore
            config = load_config()
        except Exception:
            config = None

    meta = {
        "topic": args.topic if args.topic is not None else env.get("topic", ""),
        "framework": args.framework if args.framework is not None else env.get("framework", "PICO"),
        "register": args.register if args.register is not None else env.get("register", "audit"),
        "language_space": (
            args.language_space if args.language_space is not None
            else env.get("language_space", "both")
        ),
        "search_id": args.search_id if args.search_id is not None else env.get("search_id", ""),
        "supplementary": env.get("supplementary"),
    }

    paths = run(
        cm, platforms, args.out,
        config=config, verify_vocab=not args.no_verify_vocab,
        live_verify_links=args.live_verify_links, **meta,
    )
    print(f"search_export.generate: json -> {paths['json']}")
    print(f"search_export.generate: md   -> {paths['md']}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())


__all__ = [
    "SCHEMA_VERSION",
    "QUALITY_CLAIM",
    "render_style",
    "platform_vocab",
    "build_strategy",
    "generate",
    "render_markdown",
    "write_outputs",
    "run",
]
