"""HTML renderer (web-artifacts-builder + Shadcn path).

Reads the four JSON files produced by data_materialization.py + prisma_s_logger,
maps them into the schema expected by the React App.tsx, then injects them as
`window.__REPORT_DATA__` into a pre-built bundle.html (shipped in assets/).

Raises HtmlRenderError if the pre-built bundle is missing.

Design notes (2026-05-23):
  * No size-driven fallback. Earlier versions degraded to a leaner jinja2
    template when the bundle exceeded a threshold — that created inconsistent
    UX (same Skill produced two different visual reports depending on data
    size). Removed entirely. Modern browsers open 10+ MB HTML files without
    issue; a 1.7 MB self-contained academic report is well within comfort.
  * No oversize sidecar advisories. Users don't care that a report is
    "1.6 MB" — they care that it opens cleanly.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

SKILL_ROOT = Path(__file__).resolve().parent.parent
PREBUILT_BUNDLE = (
    SKILL_ROOT / "assets" / "webartifacts_app" / "paper-report" / "bundle.html"
)


class HtmlRenderError(RuntimeError):
    """Raised when the webartifacts pipeline cannot produce a valid HTML file."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_html_webartifacts(
    materialized_data_dir: Path,
    output_path: Path,
    *,
    user_query: str = "",
    language: Optional[str] = None,
) -> Path:
    """Render a Shadcn-styled HTML report by hydrating the pre-built bundle.

    Strategy:
      1. Read the four JSON files from materialized_data_dir.
      2. Pass them through as the raw shape expected by React `normalize()`.
      3. Read assets/webartifacts_app/paper-report/bundle.html (pre-built once).
      4. Inject `<script>window.__REPORT_LANG__ = "..."</script>` AND
         `<script>window.__REPORT_DATA__ = {...};</script>` before the first
         existing <script> tag (the LANG one comes first so the React bundle's
         `installLanguage()` call picks it up before any component renders).
      5. Write to output_path.

    Args:
        materialized_data_dir: directory containing the four JSON files.
        output_path: where to write the hydrated HTML.
        user_query: fallback query string when metadata lacks one.
        language: "en" or "zh". Resolution order:
            (a) explicit `language` argument, (b) `metadata.language`,
            (c) "en". Anything else falls back to "en" with a console warning
            inside the React bundle. The bundle ships with both `STRINGS.en`
            and `STRINGS.zh` dictionaries; this flag picks which one mounts.
    """
    materialized_data_dir = Path(materialized_data_dir)
    output_path = Path(output_path)

    if not PREBUILT_BUNDLE.exists():
        raise HtmlRenderError(
            f"Pre-built bundle not found at {PREBUILT_BUNDLE}. "
            "Run web-artifacts-builder bundle-artifact.sh first."
        )

    metadata = _read_json(materialized_data_dir / "metadata.json")
    paper_list = _read_json(materialized_data_dir / "paper_list.json")
    chart_data = _read_json(materialized_data_dir / "chart_data.json")
    prisma_log_raw = _read_json(materialized_data_dir / "prisma_log.json")

    # Resolve language: explicit > metadata.language > "en"
    resolved_lang = _resolve_language(language, metadata)

    report_data = _build_report_data(
        metadata=metadata,
        paper_list=paper_list,
        chart_data=chart_data,
        prisma_log_raw=prisma_log_raw,
        user_query=user_query,
    )

    bundle_html = PREBUILT_BUNDLE.read_text(encoding="utf-8")
    # Inject DATA first then LANG, so LANG ends up FIRST in the HTML stream
    # (each _inject_* helper inserts before the current first <script>; the
    # second call therefore lands before the script written by the first
    # call). This matches the docstring's claim that LANG comes first.
    hydrated_html = _inject_report_data(bundle_html, report_data)
    hydrated_html = _inject_language(hydrated_html, resolved_lang)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(hydrated_html, encoding="utf-8")

    log.info(
        "Webartifacts HTML rendered: %s (%.0f KB)",
        output_path,
        output_path.stat().st_size / 1024,
    )
    return output_path


# ---------------------------------------------------------------------------
# Mapping: paper-search-pro JSON  ->  App.tsx schema
# ---------------------------------------------------------------------------

def _build_report_data(
    metadata: Dict[str, Any],
    paper_list: List[Dict[str, Any]],
    chart_data: Dict[str, Any],
    prisma_log_raw: Dict[str, Any],
    *,
    user_query: str = "",
) -> Dict[str, Any]:
    """Build the raw-shape payload that React's `normalize(raw)` expects.

    React reads four top-level keys from `window.__REPORT_DATA__`:
    `{metadata, papers, chart_data, prisma_log}` — the same shape produced by
    `data_materialization.py` and validated by the `sample-standard.json`
    fixture in the React app's design assets. The earlier post-materialization
    schema (`reportMeta` / `themes` / `prismaLog`) was a dead branch that
    matched no React surface, leaving Hero / Methods / Audit blank on real
    data even though Mock-data baseline rendered correctly.

    Transformations applied here:
      * `metadata` — pass through; fill in `query` from CLI fallback if missing.
      * `papers` — pass through with ALL fields intact, including `abstract`
        and `rcs_reasoning`. PaperSheet renders an Abstract section (collapsed
        by default, expandable) and a "Why this paper" section (rcs_reasoning).
        Earlier optimization stripped both to keep the hydrated bundle below a
        1500 KB auto-fallback threshold, but two reviewers independently
        confirmed it crippled the research workflow (TLDR is AI-generated,
        not a substitute for the original abstract; rcs_reasoning has no
        substitute). Bundle is now allowed to grow to ~1.6 MB on 250-paper
        reports — within the new 2500 KB threshold.
      * `chart_data` + `prisma_log` — pass through verbatim. React's
        `parsePrismaPythonRepr` already handles Python-style dict repr
        strings inside step values, and the dict-of-step-key shape matches
        what `prisma_s_logger.build_prisma_s_log` emits.
    """
    # Query fallback (legacy data dirs that lacked the `query` key in metadata).
    meta_out: Dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    if not meta_out.get("query") and user_query:
        meta_out["query"] = user_query

    return {
        "metadata": meta_out,
        "papers": list(paper_list) if isinstance(paper_list, list) else [],
        "chart_data": chart_data if isinstance(chart_data, dict) else {},
        "prisma_log": prisma_log_raw if isinstance(prisma_log_raw, dict) else {},
    }


# ---------------------------------------------------------------------------
# HTML hydration
# ---------------------------------------------------------------------------

_FIRST_SCRIPT_RE = re.compile(r"<script(\s|>)")


def _inject_report_data(bundle_html: str, report_data: Dict[str, Any]) -> str:
    """Insert `<script>window.__REPORT_DATA__ = ...</script>` before the first <script>."""
    payload = json.dumps(
        report_data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Escape sequences that would prematurely close the script tag.
    safe_payload = payload.replace("</script>", "<\\/script>")
    injection = (
        f"<script>window.__REPORT_DATA__ = {safe_payload};</script>"
    )

    match = _FIRST_SCRIPT_RE.search(bundle_html)
    if not match:
        # No <script> in bundle? Append before </body>.
        if "</body>" in bundle_html:
            return bundle_html.replace("</body>", f"{injection}</body>", 1)
        return bundle_html + injection
    insert_at = match.start()
    return bundle_html[:insert_at] + injection + bundle_html[insert_at:]


def _resolve_language(
    explicit: Optional[str],
    metadata: Dict[str, Any],
) -> str:
    """Pick "en" or "zh" from explicit arg, metadata, or default "en".

    Anything other than "en"/"zh" falls back to "en" with a stderr warning.
    The React bundle's `installLanguage()` does an identical fallback, so
    even a corrupted value can't crash rendering — but logging here lets a
    main agent see something is up.
    """
    candidate = explicit or (
        metadata.get("language") if isinstance(metadata, dict) else None
    )
    if candidate in ("en", "zh"):
        return candidate
    if candidate:
        log.warning(
            "Unknown language %r; falling back to 'en'. Acceptable values: en, zh.",
            candidate,
        )
    return "en"


def _inject_language(bundle_html: str, language: str) -> str:
    """Insert `<script>window.__REPORT_LANG__ = "..."</script>` before the first <script>.

    Placed BEFORE `__REPORT_DATA__` so that `installLanguage()` runs first
    inside the React bundle and `window.S` is set before any component reads
    a translation. The bundle's i18n.ts uses the same fallback chain (window
    global → "en"), so a missing injection here is safe — but the explicit
    injection makes the active language visible in the HTML source.
    """
    safe_lang = "zh" if language == "zh" else "en"
    injection = f'<script>window.__REPORT_LANG__ = "{safe_lang}";</script>'

    match = _FIRST_SCRIPT_RE.search(bundle_html)
    if not match:
        if "</body>" in bundle_html:
            return bundle_html.replace("</body>", f"{injection}</body>", 1)
        return bundle_html + injection
    insert_at = match.start()
    return bundle_html[:insert_at] + injection + bundle_html[insert_at:]


# ---------------------------------------------------------------------------
# Size policy
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    if not path.exists():
        raise HtmlRenderError(f"Required input not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import sys
    import tempfile

    parser = argparse.ArgumentParser(
        description=(
            "Render the HTML report (Shadcn webartifacts path) by hydrating "
            "the pre-built React bundle with materialized JSON data."
        )
    )
    parser.add_argument(
        "--data",
        type=Path,
        help="Path to report_data.json (consolidated bundle).",
    )
    parser.add_argument(
        "--materialized-dir",
        type=Path,
        help="Directory with chart_data/paper_list/metadata/prisma_log JSON siblings.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Where to write report.html.",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Optional original user query (fallback when metadata lacks it).",
    )
    parser.add_argument(
        "--language",
        choices=("en", "zh"),
        default=None,
        help=(
            "UI language for the rendered report. The bundle ships with both "
            "English and Chinese dictionaries; this flag controls which one "
            "mounts. Resolution order: explicit flag > metadata.language > 'en'. "
            "Set this based on the user's query language: CJK characters → zh, "
            "otherwise → en. (Paper data — titles, authors, abstracts — is "
            "never translated; only the report's UI chrome.)"
        ),
    )
    args = parser.parse_args()

    if args.materialized_dir:
        materialized_dir = args.materialized_dir
    elif args.data and args.data.exists():
        payload = json.loads(args.data.read_text(encoding="utf-8"))
        tmp_dir = Path(tempfile.mkdtemp(prefix="html_webart_"))
        (tmp_dir / "chart_data.json").write_text(
            json.dumps(payload.get("chart_data", {}), ensure_ascii=False), encoding="utf-8"
        )
        (tmp_dir / "paper_list.json").write_text(
            json.dumps(payload.get("paper_list", []), ensure_ascii=False), encoding="utf-8"
        )
        (tmp_dir / "metadata.json").write_text(
            json.dumps(payload.get("metadata", {}), ensure_ascii=False), encoding="utf-8"
        )
        (tmp_dir / "prisma_log.json").write_text(
            json.dumps(payload.get("prisma_log", {}), ensure_ascii=False), encoding="utf-8"
        )
        materialized_dir = tmp_dir
    else:
        sys.exit(
            "html_renderer_webartifacts: provide --data report_data.json or "
            "--materialized-dir"
        )

    out = render_html_webartifacts(
        materialized_data_dir=materialized_dir,
        output_path=args.output,
        user_query=args.query,
        language=args.language,
    )
    print(f"html_renderer_webartifacts: wrote {out}")
