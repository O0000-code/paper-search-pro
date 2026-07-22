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
- ``search_strategies.md``   — user-facing product doc: platform + link +
  paste-ready strategy + plain-language review notes (35 号产品化契约); all
  audit detail lives in the JSON, internal codes never surface in the MD.
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
# Markdown rendering — product layout v3 (37_md_product_v3.md 契约)
#
# The MD is the USER-FACING deliverable, radically minimal: 目录 + 每平台（纯文本
# 标题 + 打开链接一行 + 检索式代码块 + 0-2 条 ⚠️）+ 附录（分行版 / 检索逻辑 / 备注）。
# All audit detail (PRESS domains, linter findings, per-term vocab statuses, tier
# codes) stays in search_strategies.json; internal codes never appear in the MD
# (契约验收 4 grep guard). 检索式字符串逐字节进代码块，渲染层绝不改写。
# ---------------------------------------------------------------------------

#: 平台排序表（契约渲染规则 1，写死）：知名平台在前、中文靠后；未知宿主排各版末尾。
#: 键是语法卡 stem（syntax_card_ref 的文件名）——排序是呈现层决策，不是平台语法真值。
_EN_PLATFORM_ORDER = [
    "pubmed", "wos", "scopus", "embase_com", "embase_ovid", "cochrane_central",
    "psycinfo_ovid", "psycinfo_ebsco", "cinahl_ebsco", "eric", "ieee_xplore",
    "acm_dl", "econlit_ebsco", "clinicaltrials_gov",
]
_ZH_PLATFORM_ORDER = ["cnki", "wanfang", "sinomed"]

#: 检索入口名（v3 渲染规则 2：粘贴目标并入链接文案 `打开<入口>`——链接文案本身携带
#: "去哪、粘到哪"，正文不再出现独立的"复制整段→粘贴到…"操作提醒）。纯呈现层短语；
#: 未知 stem 落到通用「检索框」。
_ENTRY_NAME = {
    "pubmed": "检索框",
    "wos": "Advanced Search",
    "scopus": "Advanced document search",
    "embase_com": "Advanced Search",
    "embase_ovid": "Ovid 命令行检索",
    "cochrane_central": "Search Manager",
    "psycinfo_ovid": "Ovid 命令行检索",
    "psycinfo_ebsco": "Advanced Search",
    "cinahl_ebsco": "Advanced Search",
    "econlit_ebsco": "Advanced Search",
    "ieee_xplore": "Command Search",
    "acm_dl": "Advanced Search",
    "clinicaltrials_gov": "Expert Search",
    "cnki": "专业检索",
    "wanfang": "专业检索",
    "sinomed": "检索框",
}

#: 订阅提示（附录「备注」）用的平台短名——长展示名压成一眼可读的通名。
_SHORT_NAME = {
    "pubmed": "PubMed", "wos": "WOS", "scopus": "Scopus",
    "embase_com": "Embase", "embase_ovid": "Embase",
    "cochrane_central": "Cochrane", "psycinfo_ovid": "PsycINFO",
    "psycinfo_ebsco": "PsycINFO", "cinahl_ebsco": "CINAHL",
    "econlit_ebsco": "EconLit", "ieee_xplore": "IEEE", "acm_dl": "ACM",
    "clinicaltrials_gov": "ClinicalTrials.gov", "eric": "ERIC",
    "cnki": "知网", "wanfang": "万方", "sinomed": "SinoMed",
}

#: 块角色 -> 中文人话（结构行与逐块行用；role 自带中文时优先取中文）。
_ROLE_ZH = {
    "population": "人群", "patient": "人群", "participants": "人群",
    "intervention": "干预", "exposure": "暴露", "comparator": "对照",
    "comparison": "对照", "control": "对照", "outcome": "结局",
    "context": "情境", "setting": "场景", "concept": "概念",
    "interest": "关注现象", "phenomenon": "现象", "design": "研究设计",
    "evaluation": "评价", "sample": "样本", "timing": "时点",
}

# -- 内部行话 / 方法学引注清洗（契约渲染规则 3：内部信息退出 MD，翻成人话） --
_CITATION_PAREN_RES = [
    re.compile(r"\((?=[^()]*(?:Cochrane|PRISMA|PRESS|MECIR|Handbook|Haddaway"
               r"|McGowan|§))[^()]*\)"),
    re.compile(r"（(?=[^（）]*(?:Cochrane|PRISMA|PRESS|MECIR|Handbook|Haddaway"
               r"|McGowan|§))[^（）]*）"),
]
_INTERNAL_MARK_RES = [
    re.compile(r"（(?:[A-Z]-[0-9a-z]{1,3}|E\d+ ?底线|L\d+|D-[a-z])）"),
    re.compile(r"\((?:[A-Z]-[0-9a-z]{1,3}|E\d+ ?底线|L\d+|D-[a-z])\)"),
    re.compile(r"（flagged[^（）]*）"),
    re.compile(r"[🟦🟨🟩]"),
]

#: 调整指南只收「用户可操作」的条目（契约模板「检索逻辑」节）。
_ACTIONABLE_RE = re.compile(
    r"若|如果|如需|可删|可改|删去|改用|回退|收窄|扩大|提召回|是否保留|按需"
    r"|fallback|too few|remove|add them|if the (?:project|review|scope)",
    re.IGNORECASE,
)
#: 受控词核验类注记不进调整指南——它们已按平台合并进「使用前请核对」。
_VERIFY_NOISE_RE = re.compile(
    r"无免费|无公开|no free|LLM (?:suggestion|建议)|待人工核对|绝不伪装"
    r"|pending_manual",
    re.IGNORECASE,
)


def _pad_latin(phrase: str) -> str:
    """中西混排空格：短语以西文起/收时补半角空格，纯中文两侧不加。"""
    pre = " " if re.match(r"[A-Za-z0-9]", phrase) else ""
    post = " " if re.search(r"[A-Za-z0-9]$", phrase) else ""
    return f"{pre}{phrase}{post}"


def _plain(text: Optional[str]) -> str:
    """Strip methodology citations + internal rule codes from a prose note."""
    t = str(text or "")
    for rx in _CITATION_PAREN_RES + _INTERNAL_MARK_RES:
        t = rx.sub("", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" +([.。；，,])", r"\1", t)
    return t.strip(" ；;·—-—")


def _strategy_stem(s: Dict) -> str:
    m = re.search(r"([^/]+)\.md$", str(s.get("syntax_card_ref") or ""))
    if m:
        return m.group(1)
    return str((s.get("deep_link") or {}).get("platform") or "")


def _strategy_is_cjk(s: Dict) -> bool:
    """EN/ZH 归属：与 D-a 同源（语法卡的半角铁律信号）；卡不可读时回退到
    中文排序表成员 / cjk 渲染风格。"""
    stem = _strategy_stem(s)
    try:
        return _is_cjk_host(load_card(stem))
    except Exception:
        return stem in _ZH_PLATFORM_ORDER or s.get("render_style") == "cjk"


def _ordered_groups(strategies: List[Dict]) -> (List[Dict], List[Dict]):
    """Split into (EN, ZH) and sort each by the hardwired order table (stable;
    unknown stems keep input order at the end of their group)."""
    en, zh = [], []
    for i, s in enumerate(strategies):
        (zh if _strategy_is_cjk(s) else en).append((i, s))

    def _key(order):
        def k(item):
            i, s = item
            stem = _strategy_stem(s)
            return (order.index(stem) if stem in order else len(order), i)
        return k

    en.sort(key=_key(_EN_PLATFORM_ORDER))
    zh.sort(key=_key(_ZH_PLATFORM_ORDER))
    return [s for _, s in en], [s for _, s in zh]


def _host_entry_url(host: Optional[str]) -> Optional[str]:
    """官网检索入口：从 host 字段（如「中国知网 / kns.cnki.net」）取域名。"""
    m = re.search(r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}", str(host or ""))
    return f"https://{m.group(0)}" if m else None


def _clean_template_url(tmpl: str) -> str:
    """url_template 可能带 {urlenc} 占位符——链接只指到检索页，不带占位参数。"""
    if "{" not in tmpl:
        return tmpl
    qpos, bpos = tmpl.find("?"), tmpl.find("{")
    if 0 <= qpos < bpos:
        return tmpl[:qpos]
    return tmpl[:bpos].rstrip("?&=/") or tmpl


def _platform_link(s: Dict):
    """(url, 链接文案) —— v3 渲染规则 2：粘贴目标并入链接文案，链接后不带任何括注后缀
    （"需机构登录/浏览器内可用" 已并入附录「备注」一句，不再逐平台复述）。

    A 档真深链（点开即执行）文案为「打开并直接执行检索」；其余（B/C 档模板页、宿主
    入口页）文案为「打开<检索入口>」——入口名取自 ``_ENTRY_NAME``，链接文案本身即告诉
    读者去哪、把整段式子粘到哪。"""
    dl = s.get("deep_link") or {}
    tier = str(dl.get("tier") or "").upper()
    url, tmpl = dl.get("url"), dl.get("url_template")
    entry = _ENTRY_NAME.get(_strategy_stem(s), "检索框")
    open_entry = "打开" + _pad_latin(entry).rstrip()
    if tier == "A" and url:
        return url, "打开并直接执行检索"
    if tmpl:
        return _clean_template_url(tmpl), open_entry
    entry_url = _host_entry_url(s.get("host"))
    if entry_url:
        return entry_url, open_entry
    return None, ""


def _role_zh(role) -> str:
    role = str(role or "").strip()
    cjk = "".join(re.findall(r"[一-鿿]+", role))
    if cjk:
        return cjk
    key = role.lower().split()[0] if role else ""
    return _ROLE_ZH.get(key, role or "概念")


def _body_vocab_bullets(s: Dict) -> List[str]:
    """正文 ⚠️ 条（v3 渲染规则 1：0-2 条，仅真 actionable）。

    只保留使用前**必须人工确认**的受控词项——建议值（pending_manual/unverified，
    无公开接口可自动核对）与疑似非规范主题词（免费词表查无）——以及"本平台主题词语法
    无法机械生成，只含自由词"的说明。已核实（可直接用）、查无此词（仅告知无需处理）等
    非 actionable 项不进正文，其审计细节仍在 search_strategies.json。同平台同 vocab
    同类合并为一条，词表工具用通名「库内 <vocab> 工具」。"""
    bullets: List[str] = []
    groups: Dict = {}
    for t in s.get("controlled_vocab_terms") or []:
        key = (str(t.get("vocab")), str(t.get("status")),
               str(t.get("review_point") or ""))
        groups.setdefault(key, []).append(str(t.get("term")))

    for (vocab, status, rp), names in groups.items():
        n = len(names)
        if status in ("verified", "not_found"):
            continue  # 已核实 / 查无此词：非 actionable，不进正文
        if "空结果" in rp or "疑似非" in rp:
            lead = (f"式中 '{names[0]}' 等 {n} 个" if n > 1 else f"式中 '{names[0]}'")
            bullets.append(
                f"⚠️ {lead} 疑似非规范 {vocab} 主题词（官方词表查无），"
                f"请在库内 {vocab} 工具确认，不符则从式中删除。")
        elif status in ("pending_manual", "unverified"):
            lead = (f"式中 '{names[0]}' 等 {n} 个 {vocab} 主题词" if n > 1
                    else f"式中的 '{names[0]}' 这个 {vocab} 主题词")
            bullets.append(
                f"⚠️ {lead}为建议值（无公开接口可自动核对），"
                f"请在库内 {vocab} 工具确认后使用。")
        else:
            cleaned = _plain(rp)
            if cleaned:
                quoted = "、".join(f"'{x}'" for x in names)
                bullets.append(f"⚠️ {quoted}：{cleaned}")

    # 主题词语法无法机械模板化 -> 检索式只含自由词（真 actionable：读者会误以为已叠主题词）
    for rp in s.get("review_points") or []:
        if "人工组装" in rp or "无法机械模板化" in rp:
            bullets.append(
                "⚠️ 本平台主题词语法无法自动生成，检索式只含自由词；"
                "如需叠加主题词，请在库内检索界面手动添加。")
            break

    # 去重（保序）
    seen, out = set(), []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _withhold_sentence(s: Dict) -> str:
    """Withhold 的平台整节一句话（契约渲染规则 3）——原因翻成人话。"""
    reason = ""
    for rp in s.get("review_points") or []:
        if "withhold" in rp or "机械校验未通过" in rp:
            reason = rp
            break
    if "缺中文词项" in reason:
        return "本平台是中文数据库，本次概念模型未提供对应的中文检索词，无法生成可靠的检索式。"
    if "operator_logic" in reason:
        return "概念块的组合逻辑无法可靠转换成本平台的语法，为避免输出错误逻辑的检索式，本次未生成。"
    if "机械校验未通过" in reason:
        return "生成的检索式未通过语法校验，为避免交付带语法错误的式子，本次未输出。"
    if "为空" in reason or "无可渲染词项" in reason:
        return "概念模型中没有可用于本平台的检索词，本次未生成检索式。"
    cleaned = _plain(re.sub(r"^检索式已 withhold(?:（未生成）)?：", "", reason))
    return cleaned or "详见同目录 search_strategies.json 的 review_points。"


def _render_platform_section(s: Dict, *, level: str = "##") -> List[str]:
    """一个平台的正文节（v3 极简）：纯文本标题（供目录锚点）+ 打开链接一行 +
    检索式代码块 + 0-2 条 ⚠️。分行版移入附录、说明性内容退出正文。``level`` 为标题
    级别（单语言文档 ``##``；中英双语文档平台降 ``###``，语言分组标题在两组之间）。"""
    L: List[str] = []
    title = str(s.get("platform") or "")
    L.append(f"{level} {title}")
    L.append("")

    if not s.get("strategy_string"):
        L.append(f"本平台未能生成合规检索式：{_withhold_sentence(s)}")
        L.append("")
        return L

    url, text = _platform_link(s)
    if url:
        L.append(f"[{text}]({url})")
        L.append("")
    L.append("```")
    L.append(s["strategy_string"])
    L.append("```")
    L.append("")
    bullets = _body_vocab_bullets(s)
    if bullets:
        L.extend(f"- {b}" for b in bullets)
        L.append("")
    return L


def _sub_block_ids(text: str, blocks: List[Dict]) -> str:
    """把自由文本里的内部块 ID（B1/B2、E/P/O…）替换为中文角色名（39 号验收 P1-1：
    结构行早已做此替换，omitted 原因与调整指南 tips 同样必须做——内部代号绝不
    进用户可见文本）。最长 ID 优先（防 B1 误伤 B12），词边界匹配。"""
    for b in sorted(blocks, key=lambda x: -len(str(x.get("id") or ""))):
        bid = str(b.get("id") or "")
        if bid:
            text = re.sub(rf"\b{re.escape(bid)}\b", _role_zh(b.get("role")), text)
    return text


def _search_logic_appendix(record: Dict) -> List[str]:
    """附录「检索逻辑」小节（v3 渲染规则 6）：结构一行 + ≤5 条 actionable 单行条目
    （块词概览删除）。条目来自被省略的概念块原因 + register_notes 里用户可操作的调整
    指南（内部引注/代号已清洗）。总条目 ≤6 行。"""
    cm = record.get("concept_model", {}) or {}
    blocks = _blocks(cm)
    L: List[str] = ["**检索逻辑**", ""]

    logic = str(cm.get("operator_logic") or "").strip()
    if logic:
        disp = _sub_block_ids(logic, blocks)
    else:
        disp = " AND ".join(f"({_role_zh(b.get('role'))})" for b in blocks)
    L.append(f"- 结构：{disp}——块间 AND（全部满足），块内同义词 OR（命中其一）。")

    tips: List[str] = []
    for om in cm.get("omitted_blocks") or []:
        reason = _sub_block_ids(_plain(om.get("reason")), blocks)
        if reason:
            # 历史记录里块名字段既有 "role" 也有 "block"，两者都认。
            name = _role_zh(om.get("role") or om.get("block"))
            tips.append(f"未纳入「{name}」块：{reason}")

    for note in cm.get("register_notes") or []:
        note = str(note or "")
        if _VERIFY_NOISE_RE.search(note):
            continue  # 受控词核验类——已按平台放进正文 ⚠️
        if not _ACTIONABLE_RE.search(note):
            continue  # 非用户可操作的构建说明不进产品文档
        cleaned = _sub_block_ids(_plain(note), blocks)
        if cleaned:
            tips.append(cleaned)

    L.extend(f"- {t}" for t in tips[:5])   # 结构 1 行 + ≤5 条 = ≤6 行
    L.append("")
    return L


def _sr_registries(record: Dict) -> List[str]:
    """注册制 SR 需补检索的试验注册库名（supplementary 里 role==registry 的项）。"""
    known = {"clinicaltrials_gov": "ClinicalTrials.gov", "who_ictrp": "WHO ICTRP"}
    out: List[str] = []
    for key, v in (record.get("supplementary") or {}).items():
        if isinstance(v, dict) and v.get("role") == "registry":
            out.append(known.get(key) or _plain(v.get("note") or key) or key)
    return out


def _notes_appendix(record: Dict, ordered: List[Dict]) -> List[str]:
    """附录「备注」小节（v3 渲染规则 6）：订阅提示 + [中文库半角提示] + SR 补充 +
    方法学依据，共 ≤4 行。逐平台重复的「需机构登录/未实测/先试检」在此合并为一句。"""
    L: List[str] = ["**备注**", ""]

    # 订阅提示：access=subscription 一律列出。订阅属性与深链档位是两根正交轴——
    # B 档只说明结果页是浏览器渲染，不代表免登录（39 号验收 P2-2：原 tier 门控
    # 把万方漏出了名单，会误导用户以为它不需机构登录）。
    subs, seen = [], set()
    for s in ordered:
        if str(s.get("access") or "").lower() != "subscription":
            continue
        name = _SHORT_NAME.get(_strategy_stem(s)) or str(s.get("platform") or "")
        if name and name not in seen:
            seen.add(name)
            subs.append(name)
    if subs:
        L.append(f"- 订阅库（{'、'.join(subs)}）需机构登录，工具未在登录墙内实测，"
                 "首次使用建议先小规模试检。")

    # 中文库半角提示：仅当文档里真的有一条可复制的中文检索式时（全 withhold 的
    # 文档没有可复制对象，提示是空话——39 号验收 P3-1）。
    if any(_strategy_is_cjk(s) and str(s.get("strategy_string") or "").strip()
           for s in ordered):
        L.append("- 中文库检索式中的括号、引号、AND/OR 均为英文半角，请整段复制、勿手打。")

    reg = _sr_registries(record)
    if reg:
        L.append(f"- 注册制系统综述另需检索试验注册库（{'、'.join(reg)}）与灰色文献源。")

    L.append(_METHODOLOGY_LINE)
    L.append("")
    return L


#: 溯源一行（契约模板末行）。注意：这是全文唯一允许出现「PRESS」的位置——
#: 它是公开发表的检索式同行评审指南名（PRESS 2015），不是内部代号；
#: 守卫测试对本行豁免、并断言 PRESS 不出现在其他任何行。
_METHODOLOGY_LINE = (
    "- 方法学依据：Cochrane Handbook · PRESS 2015 · PRISMA-S 2021。"
)


def _slug(title: str) -> str:
    """GitHub/Typora 标题锚点 slug（v3 渲染规则 3）：转小写、删标点（括号/点号/斜杠/
    冒号…），空格逐个转连字符（与 GitHub 一致：'a / b' -> 'a--b'）；字母/数字/CJK/既有
    连字符保留。目录链接与平台标题共用此函数，保证锚点自洽。"""
    s = str(title).strip().lower()
    s = re.sub(r"[^0-9a-z㐀-䶿一-鿿\- ]", "", s)
    return s.replace(" ", "-")


def _toc_line(ordered: List[Dict]) -> str:
    """标题下的单行式目录：每平台一个锚点链接 · 附录（v3 渲染规则 3）。"""
    parts = [f"[{str(s.get('platform') or '')}](#{_slug(str(s.get('platform') or ''))})"
             for s in ordered]
    parts.append("[附录](#附录)")
    return "**目录**：" + " · ".join(parts)


def _appendix(record: Dict, ordered: List[Dict], *, heading: str) -> List[str]:
    """附录（v3 渲染规则 5-6）：分行版（仅有分行版的平台出现）/ 检索逻辑 / 备注。"""
    L: List[str] = [f"{heading} 附录", ""]
    line_hosts = [s for s in ordered if s.get("strategy_lines")]
    if line_hosts:
        L.append("**分行版**（写 PRISMA-S 方法学 / 逐行录入时用）")
        L.append("")
        for s in line_hosts:
            L.append(f"{s.get('platform')}：")
            L.append("```")
            L.extend(s["strategy_lines"])
            L.append("```")
            L.append("")
    L.extend(_search_logic_appendix(record))
    L.extend(_notes_appendix(record, ordered))
    return L


def render_markdown(record: Dict) -> str:
    """Render ``search_strategies.md`` from the JSON record (v3 产品版式，37 号契约).

    结构：标题 + 质量声明一行 + 单行式目录 → 正文（每平台 = 纯文本标题 + 打开链接一行 +
    检索式代码块 + 0-2 条 ⚠️；节间 ``---``）→ 附录（分行版 / 检索逻辑 / 备注）。语言分组
    标题条件化：仅中英双库并存时才在两组间插「# 英文数据库」「# 中文数据库」并把平台降
    H3；单语言文档不出现任何分组标题。检索式字符串一字节不动地进代码块。"""
    topic = record.get("topic") or "(未命名主题)"
    date = str(record.get("generated_at") or "")[:10]
    en, zh = _ordered_groups(record.get("strategies") or [])
    bilingual = bool(en) and bool(zh)
    ordered = en + zh

    L: List[str] = [f"# 检索式 · {topic}", ""]
    L.append(f"> 专业初稿——⚠️ 标记使用前需人工确认的项。生成：{date}")
    L.append("")
    L.append(_toc_line(ordered))
    L.append("")

    if bilingual:
        for header, group in (("# 英文数据库", en), ("# 中文数据库", zh)):
            L.append("---")
            L.append("")
            L.append(header)
            L.append("")
            for i, s in enumerate(group):
                if i:
                    L.append("---")
                    L.append("")
                L.extend(_render_platform_section(s, level="###"))
    else:
        for s in ordered:
            L.append("---")
            L.append("")
            L.extend(_render_platform_section(s, level="##"))

    L.append("---")
    L.append("")
    L.extend(_appendix(record, ordered, heading="#" if bilingual else "##"))
    return "\n".join(L).rstrip() + "\n"


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
