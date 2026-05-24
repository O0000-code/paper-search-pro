"""CrossRef helper: L3 enrichment (funder, license, references, clinical-trial-number).

Architecture (paper-search-pro v2.0):
- No new dependencies: uses ``requests`` (already vendored via openalex stack).
- No API key required; uses CrossRef's *polite pool* by embedding a mailto in
  the User-Agent header (5 req/s/1conc -> 10 req/s/3conc, ~6x throughput).
- L3 role: enrichment ONLY, never an independent search source.

Empirical findings driving this implementation (see 22_crossref_research.md,
24_v1_l3_enrichment_test.md, 25_round2_synthesis.md):

1. **arXiv DOIs are 100% 404 in CrossRef.** Both ``10.48550/arXiv.*`` and
   ``10.48550/arxiv.*`` return ``"Resource not found."`` (plain text, not JSON).
   We pre-filter and skip these — no network call is made.

2. **CrossRef returns plain-text errors with HTTP 404.** Parsing must check
   ``Content-Type`` before calling ``.json()`` to avoid spurious exceptions.

3. **funder coverage is high for clinical / funded studies.** Empirical: NEJM
   2020 BNT162b2 paper -> ``[{name: "BioNTech and Pfizer", DOI: "10.13039/100004319"}]``;
   all 6 NEJM clinical-trial papers in the V1 test set returned non-empty funders.
   OpenAlex ``grants[]`` is empty for the same papers -> CrossRef is the
   authoritative source for funder metadata.

4. **license[] includes ``delay-in-days`` and ``content-version``** (tdm / vor /
   am / unspecified), which OpenAlex lacks. Useful for OA audit + embargo timing.

5. **CrossRef references are more complete for older papers and NEJM.** E.g.
   NEJM 2020 COVID: OA referenced_works_count=8, CrossRef reference[]=13. We
   only override the count when CrossRef has strictly more.

6. **clinical-trial-number is mostly empty even on NEJM RCTs.** All 4 NEJM
   clinical-trial papers in V1 returned empty ``clinical-trial-number[]``.
   We still attempt extraction (cheap, same fetch), but PubMed is the primary
   source for this field — see pubmed_helper.py.

Rate limiting: polite pool gives 10 req/s x 3 concurrent. We use 10 req/s
serial (sleep 0.1s between calls) to stay well under limits. paper-search-pro
only calls L3 enrichment on top-N rcs>=6 papers (typically 20-30), so total
latency is ~2-3s per enrichment pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# Avoid circular: import types via package-relative path; CLI mode shims this.
try:
    from .types import Config, UnifiedPaperEntity
except ImportError:  # pragma: no cover - CLI-only fallback
    SCRIPTS_DIR = Path(__file__).resolve().parent
    SKILL_ROOT = SCRIPTS_DIR.parent
    sys.path.insert(0, str(SKILL_ROOT))
    from scripts.types import Config, UnifiedPaperEntity  # type: ignore


# =============================================================================
# Constants
# =============================================================================

_USER_AGENT_TEMPLATE = (
    "paper-search-pro/2.0 "
    "(https://github.com/anthropic/paper-search-pro; mailto:{email})"
)
_BASE_URL = "https://api.crossref.org/works"
_RATE_LIMIT_SLEEP = 0.1  # 10 req/s — well under polite-pool 10/s ceiling.
_TIMEOUT = 15
_DEFAULT_EMAIL = "anonymous@example.com"

# Module-level singletons — re-initialisable via init().
_session: Optional[requests.Session] = None
_email: str = _DEFAULT_EMAIL


# =============================================================================
# Session lifecycle
# =============================================================================

def init(config: Optional[Config] = None) -> None:
    """Initialise the HTTP session with polite-pool User-Agent.

    Safe to call multiple times; resets the session each call. If ``config``
    is None or has no ``crossref_email``, we still construct a session using
    the anonymous mailto — CrossRef accepts it but downgrades to public pool.
    """
    global _session, _email
    _email = (config.crossref_email if config else "") or _DEFAULT_EMAIL
    _session = requests.Session()
    _session.headers["User-Agent"] = _USER_AGENT_TEMPLATE.format(email=_email)


def _get_session() -> requests.Session:
    """Lazy session accessor. Auto-initialises with anonymous email if needed."""
    global _session
    if _session is None:
        init(None)
    assert _session is not None  # appease type-checker
    return _session


# =============================================================================
# Helpers
# =============================================================================

def _is_arxiv_doi(doi: Optional[str]) -> bool:
    """Return True for arXiv-deposited DOIs (CrossRef returns 100% 404 for these).

    Covers both prefix forms observed in OpenAlex / SS responses:
        - 10.48550/arXiv.1706.03762
        - 10.48550/arxiv.1706.03762  (lower-cased)
    Also returns True for empty / None DOIs (caller should skip those too).
    """
    if not doi:
        return True
    doi_lower = doi.lower()
    return "10.48550/arxiv" in doi_lower or doi_lower.startswith("arxiv:")


def _fetch_doi(doi: str) -> Optional[Dict[str, Any]]:
    """Fetch a single DOI's CrossRef metadata. Returns the ``message`` payload.

    Returns None when:
    - DOI is arXiv (pre-filtered, no network call)
    - HTTP non-200
    - Response is plain text "Resource not found." (CrossRef's 404 body)
    - JSON decode fails
    - Network / connection error

    This function is the single network surface; tests monkey-patch it.
    """
    if _is_arxiv_doi(doi):
        return None
    try:
        # CrossRef accepts trailing slash variants; use the encoded path-form.
        url = f"{_BASE_URL}/{doi}"
        resp = _get_session().get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    # CrossRef sometimes returns 200 with text/plain "Resource not found".
    ctype = resp.headers.get("content-type", "")
    if "application/json" not in ctype:
        return None

    try:
        payload = resp.json()
    except (ValueError, json.JSONDecodeError):
        return None

    return payload.get("message")


def _extract_funders(cr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise CrossRef funder[] -> list of {name, doi, award}."""
    out: List[Dict[str, Any]] = []
    for f in cr.get("funder", []) or []:
        out.append({
            "name": f.get("name"),
            "doi": f.get("DOI"),
            "award": list(f.get("award", []) or []),
        })
    return out


def _extract_license(cr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalise CrossRef license[] -> list of {URL, content_version, delay_in_days}.

    Note: we replace the hyphenated CrossRef field names with snake_case so
    consumers don't need to use ``dict["delay-in-days"]`` syntax.
    """
    out: List[Dict[str, Any]] = []
    for lic in cr.get("license", []) or []:
        out.append({
            "URL": lic.get("URL"),
            "content_version": lic.get("content-version"),
            "delay_in_days": lic.get("delay-in-days"),
        })
    return out


def _extract_clinical_trial_number(cr: Dict[str, Any]) -> Optional[str]:
    """Return the first clinical-trial-number entry, or None.

    CrossRef returns ``clinical-trial-number: [{registry, clinical-trial-number}]``
    or omits the field entirely. Empirically empty for NEJM RCTs (see header).
    """
    ctns = cr.get("clinical-trial-number", []) or []
    if not ctns:
        return None
    first = ctns[0]
    # Field name uses hyphen even nested
    return first.get("clinical-trial-number") or first.get("clinicalTrialNumber")


def _mark_source(paper: UnifiedPaperEntity) -> None:
    """Add 'crossref' to paper.sources if not already present."""
    if "crossref" not in paper.sources:
        paper.sources.append("crossref")


# =============================================================================
# Per-field enrichment functions (composable; share a single _fetch_doi each)
# =============================================================================

def enrich_funder(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """In-place: populate ``paper.funders`` from CrossRef funder[].

    Empirically high coverage on funded / clinical papers; null on most
    pre-2000 papers and arXiv preprints (skipped automatically).
    """
    for p in papers:
        if _is_arxiv_doi(p.doi):
            continue
        time.sleep(_RATE_LIMIT_SLEEP)
        cr = _fetch_doi(p.doi)
        if not cr:
            continue
        funders = _extract_funders(cr)
        if funders:
            p.funders = funders
            _mark_source(p)
    return papers


def enrich_license(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """In-place: populate ``paper.license`` with structured license entries."""
    for p in papers:
        if _is_arxiv_doi(p.doi):
            continue
        time.sleep(_RATE_LIMIT_SLEEP)
        cr = _fetch_doi(p.doi)
        if not cr:
            continue
        lic = _extract_license(cr)
        if lic:
            p.license = lic
            _mark_source(p)
    return papers


def enrich_references(
    papers: List[UnifiedPaperEntity], threshold: int = 10
) -> List[UnifiedPaperEntity]:
    """In-place: bump ``referenced_works_count`` when CrossRef has strictly more.

    Empirically: NEJM 2020 COVID had OA=8 vs CrossRef=13. We only override when
    CrossRef's count is strictly greater than what OpenAlex provided. Papers
    already at or above ``threshold`` are skipped (CrossRef won't add enough
    value to justify the call). Default threshold=10 ensures NEJM-style 8->13
    bumps still happen while skipping papers already well-referenced by OA.
    """
    for p in papers:
        if _is_arxiv_doi(p.doi):
            continue
        if p.referenced_works_count is not None and p.referenced_works_count >= threshold:
            continue
        time.sleep(_RATE_LIMIT_SLEEP)
        cr = _fetch_doi(p.doi)
        if not cr:
            continue
        cr_refs = cr.get("reference", []) or []
        if len(cr_refs) > (p.referenced_works_count or 0):
            p.referenced_works_count = len(cr_refs)
            _mark_source(p)
    return papers


def enrich_clinical_trial(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """In-place: populate ``paper.clinical_trial_number`` if present.

    Empirically near-empty on NEJM RCTs — PubMed is the primary source for
    this field. Provided here as a non-primary backup that piggybacks on the
    single CrossRef fetch already needed for funder/license.
    """
    for p in papers:
        if _is_arxiv_doi(p.doi):
            continue
        time.sleep(_RATE_LIMIT_SLEEP)
        cr = _fetch_doi(p.doi)
        if not cr:
            continue
        ctn = _extract_clinical_trial_number(cr)
        if ctn:
            p.clinical_trial_number = ctn
            _mark_source(p)
    return papers


# =============================================================================
# One-shot enrichment (preferred entry point)
# =============================================================================

def enrich_all(papers: List[UnifiedPaperEntity]) -> List[UnifiedPaperEntity]:
    """In-place: enrich funder + license + references + clinical_trial in ONE fetch per paper.

    This is the recommended entry point — calling the per-field functions
    separately makes N fetches per paper instead of 1. ``enrich_all`` matches
    the V1 measurement (~0.6s/paper) and keeps total enrichment ~12s for 20
    papers.

    Skips arXiv DOIs (100% 404). Marks ``paper.sources`` with 'crossref' iff
    at least one field is enriched.
    """
    for p in papers:
        if _is_arxiv_doi(p.doi):
            continue
        time.sleep(_RATE_LIMIT_SLEEP)
        cr = _fetch_doi(p.doi)
        if not cr:
            continue

        enriched_any = False

        # ---- funder ----
        funders = _extract_funders(cr)
        if funders:
            p.funders = funders
            enriched_any = True

        # ---- license ----
        lic = _extract_license(cr)
        if lic:
            p.license = lic
            enriched_any = True

        # ---- references count (CrossRef has more for some journals) ----
        cr_refs = cr.get("reference", []) or []
        if len(cr_refs) > (p.referenced_works_count or 0):
            p.referenced_works_count = len(cr_refs)
            enriched_any = True

        # ---- clinical-trial-number ----
        ctn = _extract_clinical_trial_number(cr)
        if ctn:
            p.clinical_trial_number = ctn
            enriched_any = True

        if enriched_any:
            _mark_source(p)

    return papers


# =============================================================================
# CLI entry point
# =============================================================================

def _paper_from_dict(d: Dict[str, Any]) -> UnifiedPaperEntity:
    """Best-effort dict -> UnifiedPaperEntity (CLI input loading)."""
    # Only forward known dataclass fields; ignore extras to stay forward-compatible.
    allowed = {f for f in UnifiedPaperEntity.__dataclass_fields__}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in d.items() if k in allowed and k != "authors"}
    paper = UnifiedPaperEntity(**kwargs)
    return paper


def _paper_to_dict(p: UnifiedPaperEntity) -> Dict[str, Any]:
    """UnifiedPaperEntity -> JSON-serialisable dict."""
    if is_dataclass(p):
        return asdict(p)
    return dict(p)  # type: ignore[arg-type]


def _cli_main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crossref_helper",
        description="CrossRef L3 enrichment helper for paper-search-pro v2.0",
    )
    parser.add_argument(
        "--input-file", required=True,
        help="Path to JSON file containing a list of paper dicts (UnifiedPaperEntity-shaped)",
    )
    parser.add_argument(
        "--mode", choices=["funder", "license", "refs", "clinical", "all"],
        default="all",
        help="Which enrichment to run (default: all in a single fetch per paper)",
    )
    parser.add_argument(
        "--output-file",
        help="Where to write enriched JSON (defaults to stdout)",
    )
    args = parser.parse_args(argv)

    # Initialise session from user config (polite pool email).
    try:
        from .config import load_config
    except ImportError:  # pragma: no cover - CLI shim
        from scripts.config import load_config  # type: ignore
    init(load_config())

    input_path = Path(args.input_file)
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("ERROR: --input-file must contain a JSON list of papers", file=sys.stderr)
        return 2

    papers = [_paper_from_dict(d) for d in raw]

    if args.mode == "funder":
        enrich_funder(papers)
    elif args.mode == "license":
        enrich_license(papers)
    elif args.mode == "refs":
        enrich_references(papers)
    elif args.mode == "clinical":
        enrich_clinical_trial(papers)
    else:
        enrich_all(papers)

    out = json.dumps([_paper_to_dict(p) for p in papers], ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(out, encoding="utf-8")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
