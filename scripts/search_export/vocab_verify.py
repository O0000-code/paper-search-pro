"""Controlled-vocabulary existence verification (v2.4 STEP 11.5, layer 3).

Why this module exists (12 A-6 / 13 spec §5.3)
----------------------------------------------
LLM-proposed controlled-vocabulary terms (MeSH descriptors, ERIC Descriptors,
Emtree, CINAHL Headings, APA Thesaurus terms, CMeSH 中文主题词) are a prime
hallucination surface. Verification is **split by whether a free existence API
exists**:

- **MeSH**  -> NCBI E-utilities ``esearch db=mesh`` (reuses the existing NCBI
  channel — biopython/Entrez, config.ncbi_email — zero new dependency, D-19).
  ``Count>=1`` -> verified + a derived ``descriptor_ui`` (the MeSH Entrez UID is the
  descriptor UI with the leading ``D`` written as ``68``; ``68064866`` -> ``D064866``,
  empirically confirmed 2026-07-16). ``Count=0`` -> not a canonical descriptor ->
  recommend downgrade to a ``[tiab]`` free-text word.
- **ERIC**  -> IES ERIC API (Solr). ``subject:"<term>"`` numFound>=1 -> verified;
  ``=0`` -> downgrade. (``descriptor:`` is an undefined Solr field — the controlled
  Descriptors live in the ``subject`` field, confirmed 2026-07-16.)
- **Emtree / CINAHL / APA** -> **no free look-up table** -> returned as
  ``status="pending_manual"`` (llm_suggest_only) with a yellow-flag review point.
  NEVER fake-verified (13 spec §5.3 critic 缝隙3 hard constraint).
- **CMeSH** -> also ``pending_manual`` by default, but an OPTIONAL soft cross-check
  hits SinoMed's free, no-login ``suggest.do`` autocomplete: a non-empty body raises
  confidence, an empty body flags a suspected hallucination. The status is **never
  upgraded** by this soft check — it stays ``pending_manual`` (suggest.do is an
  undocumented autocomplete, not an authoritative descriptor API — sinomed.md).

Graceful degradation
---------------------
Any network / parse failure degrades to ``status="unverified"`` (an honest "could
not check", NOT a hallucination verdict and NOT a fake pass). Nothing here raises on
the network.

Return shape aligns with 13 spec §2.1 ``controlled_vocab_terms[]``:
``{term, vocab, status, descriptor_ui, explode}`` plus additive honest metadata
(``verification_method``, ``review_point``, ``note``, ``verified_date``).
"""

from __future__ import annotations

import time
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# Vocab routing + status vocabulary
# ---------------------------------------------------------------------------

#: Canonical display name + verification track per input vocab label.
#:   free_api          -> mechanical existence check (MeSH / ERIC)
#:   llm_suggest_only  -> no free table -> pending_manual (Emtree / CINAHL / APA)
#:   soft_crosscheck   -> pending_manual + optional suggest.do soft check (CMeSH)
_VOCAB_TRACK: Dict[str, Tuple[str, str]] = {
    "mesh": ("MeSH", "free_api"),
    "eric": ("ERIC", "free_api"),
    "emtree": ("Emtree", "llm_suggest_only"),
    "cinahl": ("CINAHL", "llm_suggest_only"),
    "apa": ("APA", "llm_suggest_only"),
    "psycinfo": ("APA", "llm_suggest_only"),      # PsycINFO = APA Thesaurus
    "cmesh": ("CMeSH", "soft_crosscheck"),
}

#: status values (per term):
#:   verified       -> exists in the authoritative free API
#:   not_found      -> free API says it does NOT exist -> downgrade to free-text
#:   pending_manual -> no free API -> LLM suggestion, must be human-checked
#:   unverified     -> a check was attempted but the network/parse failed (honest gap)

_NCBI_RATE_SLEEP = 0.2  # NCBI politeness: key=10 req/s, no key=3 req/s -> 5/s safe
_HTTP_TIMEOUT = 30
_USER_AGENT = (
    "paper-search-pro/2.4 "
    "(https://github.com/anthropic/paper-search-pro; vocab verify)"
)
_ERIC_API = "https://api.ies.ed.gov/eric/"
_SINOMED_SUGGEST = "https://www.sinomed.ac.cn/suggest.do"

_ESearchMesh = Callable[[str], Tuple[int, List[str]]]


def _today() -> str:
    return date.today().isoformat()


def _result(
    term: str,
    vocab: str,
    status: str,
    *,
    descriptor_ui: Optional[str] = None,
    explode: Optional[bool] = None,
    verification_method: str = "none",
    review_point: Optional[str] = None,
    note: Optional[str] = None,
    verified_date: Optional[str] = None,
    **extra,
) -> Dict:
    """Uniform result dict (13 spec §2.1 shape + additive honest metadata)."""
    out = {
        "term": term,
        "vocab": vocab,
        "status": status,
        "descriptor_ui": descriptor_ui,
        "explode": explode,
        "verification_method": verification_method,
        "review_point": review_point,
        "note": note,
        "verified_date": verified_date if verified_date is not None else _today(),
    }
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# MeSH (NCBI E-utilities esearch db=mesh)
# ---------------------------------------------------------------------------


def _derive_descriptor_ui(uid: Optional[str]) -> Optional[str]:
    """MeSH Entrez UID -> descriptor UI. The Entrez mesh UID is the descriptor UI
    with the leading ``D`` written as ``68`` (``68064866`` -> ``D064866``;
    ``68001007`` -> ``D001007``). Only descriptors (``68`` + digits) are derivable;
    anything else -> None (existence still stands, we just have no clean UI)."""
    if not uid:
        return None
    s = str(uid).strip()
    if s.startswith("68") and s[2:].isdigit():
        return "D" + s[2:]
    return None


def _default_mesh_esearch(
    term: str, *, email: Optional[str] = None, api_key: Optional[str] = None
) -> Tuple[int, List[str]]:
    """Reuse the existing NCBI Entrez channel (biopython) — no new dependency (D-19).

    Returns ``(count, id_list)`` for ``"<term>"[MeSH Terms]`` against db=mesh."""
    from Bio import Entrez  # lazy: tests inject esearch_fn and never import Bio

    Entrez.email = email or "anonymous@example.com"
    Entrez.tool = "paper-search-pro"
    if api_key:
        Entrez.api_key = api_key
    time.sleep(_NCBI_RATE_SLEEP)
    handle = Entrez.esearch(db="mesh", term=f'"{term}"[MeSH Terms]')
    record = Entrez.read(handle)
    handle.close()
    count = int(record.get("Count", 0) or 0)
    id_list = [str(x) for x in (record.get("IdList") or [])]
    return count, id_list


def verify_mesh(
    term: str,
    *,
    esearch_fn: Optional[_ESearchMesh] = None,
    email: Optional[str] = None,
    api_key: Optional[str] = None,
    config=None,
    explode: bool = True,
    verified_date: Optional[str] = None,
) -> Dict:
    """Verify one MeSH descriptor's existence via NCBI esearch db=mesh.

    ``explode`` defaults True ([Mesh] explodes by default). ``config`` (a Config)
    supplies ncbi_email / ncbi_api_key when ``email``/``api_key`` are not passed and
    the default esearch is used. Network failure -> ``unverified`` (honest gap)."""
    if config is not None:
        email = email or getattr(config, "ncbi_email", "") or None
        api_key = api_key or getattr(config, "ncbi_api_key", "") or None
    fn = esearch_fn or (lambda t: _default_mesh_esearch(t, email=email, api_key=api_key))

    try:
        count, id_list = fn(term)
    except Exception as exc:  # network / parse — degrade, never crash
        return _result(
            term, "MeSH", "unverified", explode=explode,
            verification_method="free_api",
            review_point=("MeSH 存在性核验失败（网络/接口），未验证 —— 非幻觉判定，"
                          "请重试或在 PubMed MeSH 库人工核对"),
            note=f"{type(exc).__name__}: {exc}", verified_date=verified_date,
        )

    if count >= 1 and id_list:
        return _result(
            term, "MeSH", "verified",
            descriptor_ui=_derive_descriptor_ui(id_list[0]),
            explode=explode, verification_method="free_api",
            note=f"NCBI esearch db=mesh Count={count}", verified_date=verified_date,
        )
    return _result(
        term, "MeSH", "not_found", explode=explode, verification_method="free_api",
        review_point=("非规范 MeSH descriptor（esearch db=mesh Count=0）→ "
                      "建议降级为 [tiab] 自由词"),
        note="NCBI esearch db=mesh Count=0", verified_date=verified_date,
    )


# ---------------------------------------------------------------------------
# ERIC (IES ERIC API — Solr; controlled Descriptors live in the `subject` field)
# ---------------------------------------------------------------------------


def verify_eric(
    term: str, *, session=None, verified_date: Optional[str] = None
) -> Dict:
    """Verify one ERIC Descriptor via the free IES ERIC API (``subject:"<term>"``).

    numFound>=1 -> verified; =0 -> not a canonical Descriptor -> downgrade to
    free-text. An error payload (no ``response.numFound``) or a network failure ->
    ``unverified``. ``session`` is injectable (tests pass a fake)."""
    url = (
        _ERIC_API + "?search=" + quote_plus(f'subject:"{term}"')
        + "&format=json&rows=1&fields=id"
    )
    sess = session
    if sess is None:
        import requests  # lazy
        sess = requests.Session()
        sess.headers["User-Agent"] = _USER_AGENT
    try:
        resp = sess.get(url, timeout=_HTTP_TIMEOUT)
        payload = resp.json()
    except Exception as exc:
        return _result(
            term, "ERIC", "unverified", verification_method="free_api",
            review_point=("ERIC Descriptor 核验失败（网络/解析），未验证 —— "
                          "请在 eric.ed.gov Thesaurus 人工核对"),
            note=f"{type(exc).__name__}: {exc}", verified_date=verified_date,
        )

    num_found = None
    if isinstance(payload, dict):
        num_found = (payload.get("response") or {}).get("numFound")
    if num_found is None:  # Solr error json (e.g. undefined field) — honest gap
        return _result(
            term, "ERIC", "unverified", verification_method="free_api",
            review_point="ERIC API 未返回计数（接口变更？），未验证",
            note=f"http={getattr(resp, 'status_code', None)}", verified_date=verified_date,
        )
    if num_found >= 1:
        return _result(
            term, "ERIC", "verified", verification_method="free_api",
            note=f"IES ERIC API subject:\"{term}\" numFound={num_found}",
            verified_date=verified_date,
        )
    return _result(
        term, "ERIC", "not_found", verification_method="free_api",
        review_point=("非规范 ERIC Descriptor（subject numFound=0）→ "
                      "建议降级为自由词或在 ERIC Thesaurus 人工核对"),
        note="IES ERIC API numFound=0", verified_date=verified_date,
    )


# ---------------------------------------------------------------------------
# CMeSH (pending_manual by default + OPTIONAL suggest.do soft cross-check)
# ---------------------------------------------------------------------------


def verify_cmesh(
    term: str,
    *,
    session=None,
    soft_crosscheck: bool = True,
    verified_date: Optional[str] = None,
) -> Dict:
    """CMeSH 中文主题词: status is ALWAYS ``pending_manual`` (no authoritative free
    API). When ``soft_crosscheck`` is on, SinoMed's free ``suggest.do`` autocomplete
    is consulted as a *soft* signal only:

    - non-empty body  -> confidence note (still must be human-confirmed)
    - empty body      -> flag a suspected hallucination (review point)

    The status is **never upgraded** by this check (13 spec §5.3 / sinomed.md)."""
    res = _result(
        term, "CMeSH", "pending_manual", verification_method="llm_suggest_only",
        review_point=("CMeSH 无权威免费 API：须在 SinoMed 主题检索 UI 人工确认"
                      "主题词 + 副主题词组配"),
        verified_date=verified_date, soft_crosscheck="off",
    )
    if not soft_crosscheck:
        return res

    url = _SINOMED_SUGGEST + "?dbtype=mt_&q=" + quote_plus(term)
    sess = session
    if sess is None:
        import requests  # lazy
        sess = requests.Session()
        sess.headers["User-Agent"] = _USER_AGENT
    try:
        resp = sess.get(url, timeout=_HTTP_TIMEOUT)
        status_code = getattr(resp, "status_code", None)
        body = (getattr(resp, "text", "") or "").strip()
    except Exception as exc:
        res["soft_crosscheck"] = "unavailable"
        res["note"] = f"suggest.do 软交叉核不可用：{type(exc).__name__}"
        return res

    if status_code == 200 and body:
        res["soft_crosscheck"] = "hit"
        res["note"] = ("suggest.do 软交叉核命中候选（置信提升）；仍须人工确认——"
                       "autocomplete 子串匹配，非权威描述符 API")
    elif status_code == 200 and not body:
        res["soft_crosscheck"] = "empty"
        res["review_point"] = ("suggest.do 空结果 → 疑似非 CMeSH 主题词"
                               "（可能 LLM 幻觉），请人工确认")
    else:
        res["soft_crosscheck"] = "unavailable"
        res["note"] = f"suggest.do 返回 http={status_code}，软交叉核不可用"
    # status stays "pending_manual" in every branch.
    return res


# ---------------------------------------------------------------------------
# Emtree / CINAHL / APA (no free table -> pending_manual, never fake-verify)
# ---------------------------------------------------------------------------


def verify_llm_only(
    term: str, vocab_display: str, *, verified_date: Optional[str] = None
) -> Dict:
    """Vocabs with no free look-up table: return an honest pending_manual flag."""
    return _result(
        term, vocab_display, "pending_manual", verification_method="llm_suggest_only",
        review_point=(f"{vocab_display} 无免费查表途径 → LLM 建议，须在目标库人工"
                      f"核对（不得伪装已验）"),
        verified_date=verified_date,
    )


# ---------------------------------------------------------------------------
# Dispatcher + batch
# ---------------------------------------------------------------------------


def verify_term(
    term: str,
    vocab: str,
    *,
    config=None,
    esearch_fn: Optional[_ESearchMesh] = None,
    session=None,
    soft_crosscheck: bool = True,
    explode: bool = True,
    verified_date: Optional[str] = None,
) -> Dict:
    """Verify one controlled-vocabulary term, routing by ``vocab`` to the right track."""
    key = (vocab or "").strip().lower()
    display, track = _VOCAB_TRACK.get(key, (vocab or "?", "llm_suggest_only"))

    if track == "free_api" and display == "MeSH":
        return verify_mesh(term, esearch_fn=esearch_fn, config=config,
                           explode=explode, verified_date=verified_date)
    if track == "free_api" and display == "ERIC":
        return verify_eric(term, session=session, verified_date=verified_date)
    if track == "soft_crosscheck":
        return verify_cmesh(term, session=session, soft_crosscheck=soft_crosscheck,
                            verified_date=verified_date)
    # llm_suggest_only (Emtree/CINAHL/APA) or an unknown vocab.
    return verify_llm_only(term, display, verified_date=verified_date)


def verify_terms(
    items: List,
    *,
    config=None,
    esearch_fn: Optional[_ESearchMesh] = None,
    session=None,
    soft_crosscheck: bool = True,
    verified_date: Optional[str] = None,
) -> List[Dict]:
    """Batch-verify. ``items`` = list of ``{"term","vocab"[,"explode"]}`` dicts or
    ``(term, vocab)`` tuples. Returns one result dict per item, order preserved."""
    out: List[Dict] = []
    for item in items:
        if isinstance(item, dict):
            term, vocab = item.get("term", ""), item.get("vocab", "")
            explode = bool(item.get("explode", True))
        else:
            term, vocab = item[0], item[1]
            explode = True
        out.append(verify_term(
            term, vocab, config=config, esearch_fn=esearch_fn, session=session,
            soft_crosscheck=soft_crosscheck, explode=explode, verified_date=verified_date,
        ))
    return out


def summarize_vocab_status(results: List[Dict]) -> Optional[str]:
    """Roll per-term statuses up to the strategy-level 三态 label (13 spec §1.1).

    - all terms verified via free_api            -> ``机械已验``
    - verified + not_found (culled/downgraded)   -> ``机械已验·含降级`` (a not_found
      term must never yield a bare 机械已验 — Gate2 FG1 #2 / 26b P1-1; aligned with
      generate._vocab_status_summary)
    - any pending_manual / unverified            -> ``语法已验·词表待核``
    - no controlled terms at all                 -> None (caller may set ``结构参考``
      for a pure free-text subscription-wall platform).
    """
    if not results:
        return None
    if any(r.get("status") in ("pending_manual", "unverified") for r in results):
        return "语法已验·词表待核"
    if all(r.get("status") in ("verified", "not_found") for r in results):
        if any(r.get("status") == "not_found" for r in results):
            return "机械已验·含降级"
        return "机械已验"
    return "语法已验·词表待核"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main_cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json
    import sys
    from pathlib import Path

    SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))

    parser = argparse.ArgumentParser(
        prog="vocab_verify",
        description=(
            "Verify controlled-vocabulary terms. MeSH/ERIC -> free-API existence "
            "check; Emtree/CINAHL/APA -> pending manual; CMeSH -> optional suggest.do "
            "soft cross-check (status never upgraded)."
        ),
    )
    parser.add_argument("vocab", help="mesh | eric | emtree | cinahl | apa | cmesh")
    parser.add_argument("term", help="the controlled-vocabulary term to check")
    parser.add_argument("--no-soft", action="store_true",
                        help="disable the CMeSH suggest.do soft cross-check")
    args = parser.parse_args(argv)

    config = None
    try:
        from scripts.config import load_config  # type: ignore
        config = load_config()
    except Exception:
        pass

    res = verify_term(args.term, args.vocab, config=config,
                      soft_crosscheck=not args.no_soft)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())
