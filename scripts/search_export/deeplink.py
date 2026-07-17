"""A-tier deep-link constructor for search-strategy export (v2.4 STEP 11.5, layer 2).

What this module does
---------------------
Given a platform + a boolean search string, produce the ``deep_link`` object that
goes into ``search_strategies.json`` (13 spec §2.1). It constructs **clickable /
machine-verifiable URLs for A-tier platforms ONLY** — the three whose result page
(or API) is reachable without a login/captcha/signature:

- **PubMed**   — ``?term=`` web URL + E-utilities ``esearch.fcgi`` programmatic URL.
- **ERIC**     — ``eric.ed.gov/?q=`` web URL.
- **ClinicalTrials.gov** — **API v2** ``?query.*=...&countTotal=true`` (the true
  machine-verifiable A-grade endpoint) + the human ``expert-search?term=`` URL
  (client-rendered React SPA, strictly B, delivered as a clickable convenience
  link because it is free / no-wall). We annotate *which* URL is machine-verifiable
  (``machine_verifiable_endpoint``) instead of pretending the human page is A-grade
  (per syntax_cards/clinicaltrials_gov.md).

For **every other platform (B/C tier)** it returns *only* the card's
``url_template`` (verbatim, unfilled) plus a tier explanation. It **never**
constructs a filled URL that would bypass a login wall, captcha, or signed session
(12 C-14 / spec §5.4). CNKI's captcha wall and all subscription walls therefore get
``url = None`` and a paste-only delivery note.

Compliance boundaries (read 12_risk_distillation.md §C + 13_design_spec.md §5.4)
--------------------------------------------------------------------------------
- C-14: deep links are official-URL prefill only; never bypass a wall. Enforced by
  restricting *construction* to the three A-tier platforms and refusing to fill any
  B/C URL.
- critic 缝隙5: a deep link is a point-in-time observation → every result carries a
  ``verified_date`` slot; ``build_deep_link`` leaves it None (the URL *pattern* was
  last confirmed on ``PATTERN_VERIFIED_DATE``, exposed separately), and the optional
  ``live_verify`` stamps a *fresh* ``verified_date`` + ``verified_http`` when it
  actually re-checks. We never claim a 200 we did not observe this run.

Zero new dependencies: URL encoding is stdlib ``urllib.parse``; the optional live
re-check uses ``requests`` (already a declared dependency, journal_rank precedent).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The date the A-tier URL *patterns* below were last live-confirmed (curl HTTP
#: 200 + non-error payload; see the syntax cards). This is the pattern's
#: provenance, NOT a claim that a fresh check ran this call — ``build_deep_link``
#: leaves ``verified_date``/``verified_http`` None until ``live_verify`` observes.
PATTERN_VERIFIED_DATE = "2026-07-16"

#: The three platforms whose result page / API is reachable with no login /
#: captcha / signature — the only ones we build clickable URLs for (spec §5.4).
A_TIER_PLATFORMS = ("pubmed", "eric", "clinicaltrials_gov")

#: Tier hint for the common non-A platforms (13 spec §1.1 deep-link table). Used
#: only when the caller does not pass an explicit ``tier``. Anything unknown
#: defaults to the *safest* tier ("C", paste-only, url=None).
#:   B = browser-usable (URL valid, result client-rendered / bot-blocked)
#:   C = paste-only    (login wall / session / captcha)
PLATFORM_TIER_HINTS: Dict[str, str] = {
    # B — browser usable, not script-constructed here
    "ieee": "B", "acm": "B", "wanfang": "B", "cochrane": "B",
    # C — subscription / login / captcha wall
    "wos": "C", "web_of_science": "C", "scopus": "C",
    "embase": "C", "embase_com": "C", "embase_ovid": "C",
    "ovid": "C", "ebsco": "C", "psycinfo": "C",
    "psycinfo_ovid": "C", "psycinfo_ebsco": "C", "cinahl": "C",
    "econlit": "C", "cab": "C", "scifinder": "C",
    "cnki": "C", "sinomed": "C",
}

#: Alias table -> canonical platform key.
_PLATFORM_ALIASES: Dict[str, str] = {
    "pubmed": "pubmed", "medline_pubmed": "pubmed", "medline/pubmed": "pubmed",
    "eric": "eric", "eric_free": "eric", "eric.ed.gov": "eric",
    "clinicaltrials_gov": "clinicaltrials_gov",
    "clinicaltrials.gov": "clinicaltrials_gov",
    "clinicaltrials": "clinicaltrials_gov",
    "clinical_trials_gov": "clinicaltrials_gov",
    "ctgov": "clinicaltrials_gov", "ct.gov": "clinicaltrials_gov",
    "web of science": "wos", "web_of_science": "wos", "wos": "wos",
}

_HTTP_TIMEOUT = 30
_USER_AGENT = (
    "paper-search-pro/2.4 "
    "(https://github.com/O0000-code/paper-search-pro; deep-link verify)"
)

_PUBMED_WEB = "https://pubmed.ncbi.nlm.nih.gov/?term={q}"
_PUBMED_ESEARCH = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}"
)
_ERIC_WEB = "https://eric.ed.gov/?q={q}"
_CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
_CTGOV_UI = "https://clinicaltrials.gov/expert-search?term={q}"

#: CT.gov query.* fields we forward, in a stable emit order.
_CTGOV_FIELDS = ("cond", "intr", "term", "titles", "outc", "spons", "patient", "locn")

_PUBMED_COUNT_RE = re.compile(r"<Count>(\d+)</Count>")


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode_query(query: str) -> str:
    """URL-encode a search string for a ``?term=`` / ``?q=`` query value.

    Uses ``urllib.parse.quote_plus`` (stdlib): spaces -> ``+``; ``[`` ``]`` ``"``
    ``(`` ``)`` -> ``%5B %5D %22 %28 %29``; non-ASCII (Chinese) -> UTF-8 percent
    bytes; ``%`` (e.g. CNKI ``%=``) -> ``%25``; ``'`` -> ``%27``. This matches the
    PubMed deep-link encoding the design spec §1.2 shows byte-for-byte."""
    return quote_plus(query or "")


def normalize_platform(name: Optional[str]) -> str:
    """Canonicalise a platform label to a lookup key (lower/stripped + aliases)."""
    if not name:
        return ""
    key = str(name).strip().lower()
    return _PLATFORM_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def build_deep_link(
    platform: str,
    strategy_string: Optional[str] = None,
    *,
    query_fields: Optional[Dict[str, str]] = None,
    tier: Optional[str] = None,
    url_template: Optional[str] = None,
    verified_date: Optional[str] = None,
) -> Dict:
    """Build the ``deep_link`` object for one platform (13 spec §2.1 shape).

    A-tier (PubMed / ERIC / ClinicalTrials.gov) -> a filled clickable / API URL.
    Everything else -> a B/C descriptor that surfaces the card's ``url_template``
    (verbatim) but **never a constructed filled URL** (C-14).

    Args:
        platform: platform label (aliases resolved; case-insensitive).
        strategy_string: the boolean search string (used as CT.gov query.term when
            no ``query_fields`` given; ignored for platforms that split fields).
        query_fields: CT.gov only — ``{"cond":..,"intr":..,"term":..}`` mapped to
            ``query.<field>`` params. Ignored for PubMed/ERIC.
        tier: explicit B/C tier for a non-A platform (else PLATFORM_TIER_HINTS,
            else the safest "C").
        url_template: the card's ``url_template`` to surface for a B/C platform
            (passed through verbatim; NOT filled).
        verified_date: stamp only if the CALLER already live-verified this URL this
            run (else left None — the pattern's provenance is ``PATTERN_VERIFIED_DATE``).

    Returns a dict always carrying: ``platform``, ``tier``, ``url_kind``, ``url``,
    ``verified_http``, ``verified_date`` (slots present; None until observed),
    ``pattern_verified_date``, ``note``. A-tier adds ``api_url`` (and CT.gov adds
    ``machine_verifiable_endpoint`` + ``ui_render``)."""
    key = normalize_platform(platform)
    vd = verified_date  # None unless the caller observed a fresh check

    if key == "pubmed":
        return _build_pubmed(strategy_string or "", vd)
    if key == "eric":
        return _build_eric(strategy_string or "", vd)
    if key == "clinicaltrials_gov":
        return _build_ctgov(strategy_string, query_fields, vd)

    # ---- B / C tier: surface the card template, never construct a filled URL ----
    resolved_tier = (tier or PLATFORM_TIER_HINTS.get(key, "C")).upper()
    if resolved_tier == "B":
        url_kind = "browser"
        note = (
            "B 档：URL 有效但结果客户端渲染 / bot 被拦。交付形态=浏览器内可用的检索式；"
            "不构造脚本层直达链接。"
        )
    else:  # default / "C"
        resolved_tier = "C"
        url_kind = "paste_only"
        note = (
            "C 档：登录墙 / 会话态 / 验证码墙。交付形态=可粘贴进目标库检索框的检索式本身；"
            "URL 结构（若有）见 url_template，机构登录后可试。绝不绕登录/验证码/签名（C-14）。"
        )
    return {
        "platform": key,
        "tier": resolved_tier,
        "url_kind": url_kind,
        "url": None,                       # never a constructed filled URL for B/C
        "url_template": url_template,      # the card's template, verbatim (may be None)
        "verified_http": None,
        "verified_date": vd,
        "pattern_verified_date": None,
        "note": note,
    }


def _build_pubmed(strategy_string: str, vd: Optional[str]) -> Dict:
    enc = encode_query(strategy_string)
    return {
        "platform": "pubmed",
        "tier": "A",
        "url_kind": "prefill",
        "url": _PUBMED_WEB.format(q=enc),
        "api_url": _PUBMED_ESEARCH.format(q=enc),  # E-utilities programmatic template
        "verified_http": None,
        "verified_date": vd,
        "pattern_verified_date": PATTERN_VERIFIED_DATE,
        "note": (
            "A 档：?term= 服务器端渲染结果页；编程核验走 E-utilities esearch.fcgi "
            "(<Count>)。方括号已编码为 %5B%5D。"
        ),
    }


def _build_eric(strategy_string: str, vd: Optional[str]) -> Dict:
    enc = encode_query(strategy_string)
    return {
        "platform": "eric",
        "tier": "A",
        "url_kind": "prefill",
        "url": _ERIC_WEB.format(q=enc),
        "api_url": None,
        "verified_http": None,
        "verified_date": vd,
        "pattern_verified_date": PATTERN_VERIFIED_DATE,
        "note": "A 档：eric.ed.gov/?q= 服务器端渲染，携带结果计数（最干净的开放深链之一）。",
    }


def _build_ctgov(
    strategy_string: Optional[str],
    query_fields: Optional[Dict[str, str]],
    vd: Optional[str],
) -> Dict:
    """CT.gov dual-track: API v2 (machine-verifiable A) + human expert-search (B, SPA)."""
    params: List[str] = []
    human_term: Optional[str] = None
    if query_fields:
        for field in _CTGOV_FIELDS:
            val = query_fields.get(field)
            if val:
                params.append(f"query.{field}=" + encode_query(val))
        human_term = query_fields.get("term")
        if not human_term:
            # No explicit Other-terms field: join the provided field values so the
            # human expert-search link still carries the query (convenience only).
            joined = [query_fields[f] for f in _CTGOV_FIELDS if query_fields.get(f)]
            human_term = " AND ".join(joined) if joined else None
    elif strategy_string:
        params.append("query.term=" + encode_query(strategy_string))
        human_term = strategy_string

    params.append("countTotal=true")
    api_url = _CTGOV_API + "?" + "&".join(params)
    ui_url = _CTGOV_UI.format(q=encode_query(human_term or ""))

    return {
        "platform": "clinicaltrials_gov",
        "tier": "A",
        "url_kind": "api",                     # primary machine deliverable is the API URL
        "url": ui_url,                         # human clickable (free/no-wall)
        "api_url": api_url,                    # machine-verifiable A-grade endpoint
        "machine_verifiable_endpoint": "api_url",
        "ui_render": "client-SPA",             # honest: /expert-search result is client-rendered
        "verified_http": None,
        "verified_date": vd,
        "pattern_verified_date": PATTERN_VERIFIED_DATE,
        "note": (
            "A 性来自 API v2 端点（服务器端 totalCount，机械可验/可构造）；人读 "
            "expert-search 结果客户端渲染（严格属 B），因免费无墙仍作可点击链接交付。"
        ),
    }


# ---------------------------------------------------------------------------
# Optional live re-verification (fresh point-in-time observation)
# ---------------------------------------------------------------------------


def live_verify(deep_link: Dict, *, session=None) -> Dict:
    """Re-check an A-tier deep link against the live endpoint (fresh observation).

    Returns a NEW dict (input not mutated) with ``verified_http`` set to the
    observed status, ``verified_date`` stamped today, and a ``count`` /
    ``total_count`` where the endpoint exposes one (PubMed ``<Count>``, CT.gov
    ``totalCount``). Never raises on the network: a failure sets
    ``verified_http=None`` + ``verify_error`` and leaves the URLs intact.

    B/C links are returned unchanged (there is nothing to verify without a wall).
    ``session`` is an injectable ``requests.Session`` (tests pass a fake; the
    default constructs one lazily with a polite User-Agent)."""
    out = dict(deep_link)
    if out.get("tier") != "A":
        return out

    platform = normalize_platform(out.get("platform"))
    # Choose the endpoint that actually returns a machine-checkable payload.
    if platform == "pubmed":
        target = out.get("api_url")
    elif platform == "clinicaltrials_gov":
        target = out.get("api_url")
    else:  # eric (and any A fallthrough): web url is server-rendered
        target = out.get("url")
    if not target:
        out["verify_error"] = "no verifiable URL on this deep_link"
        return out

    sess = session
    if sess is None:
        import requests  # lazy: only when a real check is requested
        sess = requests.Session()
        sess.headers["User-Agent"] = _USER_AGENT

    try:
        resp = sess.get(target if platform != "clinicaltrials_gov"
                        else target + "&pageSize=1", timeout=_HTTP_TIMEOUT)
    except Exception as exc:  # network / DNS / timeout — degrade, never crash
        out["verified_http"] = None
        out["verified_date"] = None
        out["verify_error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["verified_http"] = getattr(resp, "status_code", None)
    out["verified_date"] = date.today().isoformat()

    if out["verified_http"] == 200:
        if platform == "pubmed":
            m = _PUBMED_COUNT_RE.search(getattr(resp, "text", "") or "")
            out["count"] = int(m.group(1)) if m else None
        elif platform == "clinicaltrials_gov":
            try:
                out["total_count"] = resp.json().get("totalCount")
            except Exception:
                out["total_count"] = None
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main_cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="deeplink",
        description=(
            "Construct A-tier search deep links (PubMed / ERIC / ClinicalTrials.gov). "
            "B/C platforms return the card url_template only — never a wall-bypassing URL."
        ),
    )
    parser.add_argument("platform", help="pubmed | eric | clinicaltrials_gov | <other>")
    parser.add_argument("query", nargs="?", default="", help="boolean search string")
    parser.add_argument("--cond", default=None, help="CT.gov query.cond")
    parser.add_argument("--intr", default=None, help="CT.gov query.intr")
    parser.add_argument("--term", default=None, help="CT.gov query.term")
    parser.add_argument("--tier", default=None, help="explicit B/C tier for a non-A platform")
    parser.add_argument("--url-template", default=None, help="card url_template to surface (B/C)")
    parser.add_argument("--live", action="store_true", help="live-verify against the endpoint")
    args = parser.parse_args(argv)

    qf = {k: v for k, v in (("cond", args.cond), ("intr", args.intr), ("term", args.term)) if v}
    dl = build_deep_link(
        args.platform, args.query or None,
        query_fields=qf or None, tier=args.tier, url_template=args.url_template,
    )
    if args.live:
        dl = live_verify(dl)
    print(json.dumps(dl, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())
