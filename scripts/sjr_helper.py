"""SJR (SCImago Journal Rank) helper — journal quartile + impact lookup.

What this module is for (Feature A, v2.2 Wave 3d)
-------------------------------------------------
SCImago Journal Rank is the ONLY free source of *real* journal quartiles (Q1-Q4)
that an open-source tool can lawfully surface (R4 research). This module turns a
locally-cached SJR CSV into an ``ISSN -> {best_quartile, category_quartiles,
sjr_value}`` lookup, normalises ISSNs the way OpenAlex/SS emit them, and joins a
paper's journal ISSN to its SJR record.

Hard compliance boundaries this module enforces (read 11_risk_distillation.md)
------------------------------------------------------------------------------
- R-03 / R-05: the SJR CSV is **never** bundled into / committed to the repo.
  The data is fetched/placed by the user into a local cache directory. Fetching
  is done by the multi-platform ``journal_rank`` module via a public GitHub-raw
  mirror over plain ``requests`` (no Cloudflare in the way, no extra dependency).
  The old Playwright ``--download`` path was REMOVED in v2.2 A-1 (unreliable +
  heavyweight). A bare HTTP GET of scimagojr.com *itself* still 403s behind
  Cloudflare (R-05, empirically verified) — which is why the mirror is used.
- R-03 attribution: every place that surfaces SJR data is responsible for the
  SCImago citation. NOTE (corrected 2026-06-25, legal review §2.4): SJR is **NOT**
  "CC BY-NC" — SCImago uses **custom terms** ("non-commercial use as long as it
  is cited"), not any Creative Commons licence. The canonical, corrected string
  lives in ``SJR_ATTRIBUTION`` / ``SJR_LEGAL_NOTICE`` here so callers cannot drift.
- R-04 / R-09: this is **SJR分区 / 期刊影响力**, NOT a JCR Impact Factor. Nothing
  in this module names its outputs "impact factor", "JCR", or "中科院". The
  OpenAlex 2yr-mean-citedness impact figure (filled elsewhere) is likewise an
  *open journal impact* figure, not a JIF.

CSV schema (empirically verified 2026-06-25, ``year=2024`` snapshot)
--------------------------------------------------------------------
- 32,312 rows, 26 columns, UTF-8, **semicolon-separated**, **European decimals**
  (``145,004`` means 145.004 — comma is the decimal point).
- Column order (verbatim):
  ``Rank; Sourceid; Title; Type; Issn; Publisher; Open Access; Open Access Diamond;
  SJR; SJR Best Quartile; H index; Total Docs. (2024); Total Docs. (3years);
  Total Refs.; Total Citations (3years); Citable Docs. (3years);
  Citations / Doc. (2years); Ref. / Doc.; %Female; Overton; Country; Region;
  Publisher; Coverage; Categories; Areas``
- ``Issn``    : multiple ISSNs, comma-separated, **no hyphen** (e.g.
  ``"15424863, 00079235"``).
- ``SJR Best Quartile`` : single value = the journal's best quartile across all
  its categories (e.g. ``Q1``). Can be blank for unranked journals.
- ``Categories`` : per-category quartiles inline, ``"; "`` separated, e.g.
  ``"Hematology (Q1); Oncology (Q1)"`` or mixed ``"X (Q1); Y (Q2)"``.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Compliance constants (R-03) — the single source of truth for attribution.
# ---------------------------------------------------------------------------

#: Mandatory attribution to attach wherever SJR data is shown (R-03).
#: CORRECTED 2026-06-25 (legal review §2.4): SJR is NOT "CC BY-NC". SCImago uses
#: custom terms — "non-commercial use as long as it is cited" — not a CC licence.
SJR_ATTRIBUTION = (
    "Data: SCImago Journal Rank, scimagojr.com — non-commercial use as long as "
    "it is cited (SCImago custom terms; NOT a Creative Commons licence)."
)

#: Longer legal note for report footers / docs (R-03/R-05). SCImago's footer
#: permits non-commercial cited use; the Legal Notice tightens redistribution, so
#: we surface both and keep the conservative posture (no CSV redistribution).
SJR_LEGAL_NOTICE = (
    "Journal quartiles are from SCImago Journal Rank (SJR), derived from Scopus "
    "data. © SCImago. Free for non-commercial use with citation; see "
    "https://www.scimagojr.com/legal-notice.php. SJR is NOT the Clarivate JCR "
    "Impact Factor."
)

#: Official download endpoint (out=xls actually returns a semicolon CSV).
#: DEPRECATED in v2.2 A-1 (Playwright download removed; the journal_rank mirror
#: fetch is used instead). Kept as a constant only for back-compat / reference.
SJR_DOWNLOAD_URL = "https://www.scimagojr.com/journalrank.php?out=xls&year={year}"
SJR_PORTAL_URL = "https://www.scimagojr.com"

#: Default cache directory for user-supplied / downloaded SJR CSVs. The CSV is
#: NEVER stored in the repo (R-03) — it lives under the user's home by default.
DEFAULT_CACHE_DIR = Path.home() / ".paper-search-pro" / "sjr"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class JournalSJR:
    """One journal's SJR record, keyed downstream by any of its ISSNs."""

    title: Optional[str] = None
    issns: List[str] = field(default_factory=list)  # normalised, 8-char, no hyphen
    best_quartile: Optional[str] = None  # "Q1".."Q4" or None when unranked
    category_quartiles: Dict[str, str] = field(default_factory=dict)  # {category: "Q1"}
    sjr_value: Optional[float] = None

    def quartile_for(self, category: Optional[str] = None) -> Optional[str]:
        """Quartile for a specific category (case-insensitive substring match),
        falling back to the best quartile when no category is given or matched.

        A multi-category journal (e.g. Q1 in Oncology, Q3 in some edge category)
        returns the *best* quartile by default — matching how people say "this is
        a Q1 journal" — but a caller targeting their own field can pin a category
        to avoid edge-category quartile inflation (R4 §4.3)."""
        if category:
            cat_l = category.strip().lower()
            # exact (case-insensitive) first, then substring
            for cat, q in self.category_quartiles.items():
                if cat.lower() == cat_l:
                    return q
            for cat, q in self.category_quartiles.items():
                if cat_l in cat.lower():
                    return q
        return self.best_quartile


# ---------------------------------------------------------------------------
# ISSN normalisation + parsing helpers
# ---------------------------------------------------------------------------

_ISSN_CLEAN_RE = re.compile(r"[^0-9xX]")
# Captures "(Q1)" trailing each category name in the Categories column.
_CATEGORY_RE = re.compile(r"\s*([^;()]+?)\s*\((Q[1-4])\)")
_QUARTILE_RE = re.compile(r"^Q[1-4]$")


def normalize_issn(issn: Optional[str]) -> Optional[str]:
    """Normalise one ISSN to an 8-char, hyphen-free, uppercase-X string.

    OpenAlex emits hyphenated ``0022-3514``; SS emits hyphenated too; SJR emits
    hyphen-free ``00223514``. We strip everything but digits + X and upper-case
    the check digit so both sides compare on the same 8-char key (R4 §4.4).
    Returns None for anything that is not exactly 8 chars after cleaning."""
    if not issn:
        return None
    cleaned = _ISSN_CLEAN_RE.sub("", str(issn)).upper()
    return cleaned if len(cleaned) == 8 else None


def normalize_issns(raw: Optional[str]) -> List[str]:
    """Split a possibly multi-ISSN string (comma-separated) into normalised keys.

    Handles SJR's ``"15424863, 00079235"`` and OpenAlex's single ``"0022-3514"``.
    Drops anything that does not normalise to a clean 8-char ISSN. De-duplicated,
    order preserved."""
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    for part in str(raw).split(","):
        norm = normalize_issn(part)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _parse_european_float(value: Optional[str]) -> Optional[float]:
    """Parse SJR's European-format decimal (``145,004`` -> 145.004).

    The CSV uses comma as the decimal separator and no thousands separator in the
    SJR column, so a single comma -> dot replacement is correct. Blank/garbage ->
    None (never raises)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_categories(raw: Optional[str]) -> Dict[str, str]:
    """Parse the SJR ``Categories`` column into {category_name: quartile}.

    Input examples:
        "Hematology (Q1); Oncology (Q1)"     -> {Hematology: Q1, Oncology: Q1}
        "Software (Q2); Information Sys (Q3)" -> {Software: Q2, Information Sys: Q3}
    A category with no ``(Qn)`` suffix is skipped (some rows carry a trailing
    bare category). Never raises."""
    out: Dict[str, str] = {}
    if not raw:
        return out
    for name, quartile in _CATEGORY_RE.findall(str(raw)):
        name = name.strip()
        if name:
            out[name] = quartile
    return out


def _clean_quartile(value: Optional[str]) -> Optional[str]:
    """Validate a single 'SJR Best Quartile' cell -> 'Q1'..'Q4' or None."""
    if not value:
        return None
    s = str(value).strip().upper()
    return s if _QUARTILE_RE.match(s) else None


# ---------------------------------------------------------------------------
# CSV loading -> ISSN lookup
# ---------------------------------------------------------------------------

# Header tokens we tolerate variation on (different year snapshots reorder a few
# columns / rename the docs-year suffix). We resolve columns by name, not index,
# so a column reshuffle in a future SJR year does not silently corrupt parsing.
_COL_ISSN = "issn"
_COL_TITLE = "title"
_COL_BEST_Q = "sjr best quartile"
_COL_CATEGORIES = "categories"
_COL_SJR = "sjr"


def _header_index(header: List[str]) -> Dict[str, int]:
    """Map lowercased/trimmed header names to their column index."""
    return {h.strip().lower(): i for i, h in enumerate(header)}


def parse_sjr_csv(path: Path) -> List[JournalSJR]:
    """Parse an SJR CSV file into a list of JournalSJR records.

    Semicolon-separated, UTF-8, header row required. Columns are resolved by
    NAME (case-insensitive) not position, so a future SJR snapshot that reorders
    columns still parses. Rows with no usable ISSN are skipped (they cannot be
    joined). Never raises on a malformed individual row; raises only when the
    file is missing or lacks the required ISSN column."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"SJR CSV not found at {path}. Run `python3 -m scripts.journal_rank "
            f"fetch --platform sjr` to pull a public mirror, or place a "
            f"manually-downloaded CSV there. Source: {SJR_PORTAL_URL}"
        )

    records: List[JournalSJR] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        try:
            header = next(reader)
        except StopIteration:
            return records
        idx = _header_index(header)
        if _COL_ISSN not in idx:
            raise ValueError(
                f"SJR CSV at {path} has no 'Issn' column (found: {header[:6]}...). "
                "Is this a valid SCImago journalrank export?"
            )
        i_issn = idx[_COL_ISSN]
        i_title = idx.get(_COL_TITLE)
        i_best = idx.get(_COL_BEST_Q)
        i_cats = idx.get(_COL_CATEGORIES)
        i_sjr = idx.get(_COL_SJR)

        for row in reader:
            if not row or len(row) <= i_issn:
                continue
            issns = normalize_issns(row[i_issn])
            if not issns:
                continue  # unjoinable
            rec = JournalSJR(
                title=(row[i_title].strip() if i_title is not None and i_title < len(row) else None) or None,
                issns=issns,
                best_quartile=_clean_quartile(row[i_best]) if i_best is not None and i_best < len(row) else None,
                category_quartiles=parse_categories(row[i_cats]) if i_cats is not None and i_cats < len(row) else {},
                sjr_value=_parse_european_float(row[i_sjr]) if i_sjr is not None and i_sjr < len(row) else None,
            )
            # If best quartile was blank but categories carry quartiles, derive it
            # as the best (Q1 < Q2 < Q3 < Q4) across categories.
            if rec.best_quartile is None and rec.category_quartiles:
                rec.best_quartile = min(rec.category_quartiles.values())
            records.append(rec)
    return records


def build_issn_lookup(records: List[JournalSJR]) -> Dict[str, JournalSJR]:
    """Build ``ISSN -> JournalSJR`` from parsed records.

    Each record may carry several ISSNs (print + electronic); we index the same
    record under all of them so a join on either hits. On the rare collision of
    the same ISSN across two records (data noise), the first wins (stable)."""
    lookup: Dict[str, JournalSJR] = {}
    for rec in records:
        for issn in rec.issns:
            lookup.setdefault(issn, rec)
    return lookup


# ---------------------------------------------------------------------------
# High-level cache-first loader
# ---------------------------------------------------------------------------


def find_cached_csv(cache_dir: Optional[Path] = None) -> Optional[Path]:
    """Return the newest SJR CSV in the cache dir, or None.

    Accepts the official filename shape (``scimagojr 2024.csv``) and any
    ``*.csv`` the user dropped in. Picks the most recently modified so a freshly
    downloaded year wins."""
    cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    if not cache_dir.exists():
        return None
    csvs = sorted(
        cache_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return csvs[0] if csvs else None


class SJRLookup:
    """Loaded SJR data + ISSN join surface. Construct via ``load()``."""

    def __init__(self, lookup: Dict[str, JournalSJR], source_path: Optional[Path]):
        self._lookup = lookup
        self.source_path = source_path
        self.attribution = SJR_ATTRIBUTION

    def __len__(self) -> int:  # number of distinct ISSN keys
        return len(self._lookup)

    @property
    def journal_count(self) -> int:
        """Distinct journal records (de-duped across multi-ISSN indexing)."""
        return len({id(rec) for rec in self._lookup.values()})

    def for_issns(self, issns: List[str]) -> Optional[JournalSJR]:
        """Join: first matching SJR record for any of the given (raw) ISSNs.

        ``issns`` may be hyphenated/raw — we normalise here. Returns the matched
        JournalSJR or None. Set-intersection semantics: any ISSN match hits."""
        for raw in issns or []:
            norm = normalize_issn(raw)
            if norm and norm in self._lookup:
                return self._lookup[norm]
        return None

    def for_issn(self, issn: Optional[str]) -> Optional[JournalSJR]:
        """Convenience single-ISSN join (may itself be a comma-joined string)."""
        return self.for_issns(normalize_issns(issn))


def load(
    csv_path: Optional[Path] = None,
    *,
    cache_dir: Optional[Path] = None,
) -> Optional[SJRLookup]:
    """Load an SJRLookup, cache-first.

    Resolution order:
      1. explicit ``csv_path`` if given,
      2. newest ``*.csv`` in ``cache_dir`` (default ``~/.paper-search-pro/sjr``).
    Returns None when no CSV is available (the caller then degrades gracefully —
    journal_metric just carries OpenAlex impact / no quartile; never an error)."""
    path: Optional[Path] = None
    if csv_path:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"SJR CSV not found at {path}")
    else:
        path = find_cached_csv(cache_dir)
    if not path:
        return None
    records = parse_sjr_csv(path)
    return SJRLookup(build_issn_lookup(records), source_path=path)


# ---------------------------------------------------------------------------
# journal_metric assembly (join SJR quartile + OpenAlex open impact onto papers)
# ---------------------------------------------------------------------------


def build_journal_metric(
    issn: Optional[str],
    *,
    sjr: Optional["SJRLookup"] = None,
    category: Optional[str] = None,
    impact_lookup=None,
):
    """Assemble a ``JournalMetric`` for one paper from its journal ISSN.

    Args:
        issn: the paper's journal ISSN (raw, hyphenated or not). When falsy, the
            returned metric carries ``issn_backfill_needed=True`` so the gap is
            visible (R-08 — SS-primary records often lack ISSN; an OpenAlex
            DOI-lookup backfill can be wired in here).
        sjr: an SJRLookup (or None when no CSV is cached → no quartile).
        category: optional category to pin the SJR quartile to (else best).
        impact_lookup: optional callable ``issn -> {two_year_mean_citedness,
            h_index, ...}`` (typically ``openalex_helper.get_source_impact``).
            Injected so the join is testable without network. None → no impact.

    Returns a ``JournalMetric`` (always — never None) so the schema slot is
    populated deterministically. When nothing could be joined the metric is an
    empty-but-present record, which still tells the consumer "we looked"."""
    from .types import JournalMetric  # local import: keeps top imports lean

    metric = JournalMetric()

    if not issn:
        metric.issn_backfill_needed = True
        return metric

    # ---- SJR quartile (SCImago custom terms, NOT CC BY-NC; attribution mandatory
    # when present, R-03) ----
    if sjr is not None:
        rec = sjr.for_issn(issn)
        if rec is not None:
            metric.sjr_quartile = rec.quartile_for(category)
            metric.sjr_category_quartiles = dict(rec.category_quartiles)
            if metric.sjr_quartile or metric.sjr_category_quartiles:
                metric.sjr_attribution = SJR_ATTRIBUTION

    # ---- OpenAlex open impact (CC0; R-09: NOT a JIF) ----
    if impact_lookup is not None:
        try:
            impact = impact_lookup(issn)
        except Exception:
            impact = None
        if impact:
            metric.openalex_2yr_mean_citedness = impact.get("two_year_mean_citedness")
            h = impact.get("h_index")
            metric.h_index = int(h) if isinstance(h, (int, float)) else None

    return metric


def metric_is_empty(metric) -> bool:
    """True when a JournalMetric carries no real data (only the backfill flag /
    all-None). Lets the human path keep behavior byte-identical: an empty metric
    is treated exactly like ``None`` for display (nothing is shown)."""
    if metric is None:
        return True
    return (
        not metric.sjr_quartile
        and not metric.sjr_category_quartiles
        and metric.openalex_2yr_mean_citedness is None
        and metric.h_index is None
        and metric.cwts_snip is None
    )


# ---------------------------------------------------------------------------
# Manual-acquisition guidance (Playwright auto-download REMOVED in v2.2 A-1:
# it was unreliable + an extra dependency. The multi-platform `journal_rank`
# module fetches GitHub-raw mirrors with plain `requests` instead. A direct GET
# of scimagojr.com itself still 403s behind Cloudflare — R-05 — so the manual
# path here points at the mirror-based fetcher.)
# ---------------------------------------------------------------------------

_MANUAL_DOWNLOAD_HELP = """\
No SJR CSV is cached yet.

Get the data without a browser (one-time, ~1 min; SJR updates only once a year):
  - Preferred: run the multi-platform fetcher, which pulls a public mirror with
    plain HTTP (no Cloudflare, no extra dependency):
        python3 -m scripts.journal_rank fetch --platform sjr
  - Or manually: download the CSV from {portal} (or a mirror) and drop it into:
        {cache}
  - Then re-run your search — the quartile data is picked up automatically.

A bare HTTP GET of scimagojr.com itself 403s behind Cloudflare (R-05), which is
exactly why the mirror-based `journal_rank` fetch is the supported path.

{attribution}
"""
# (kept as a module constant so callers/tests that reference the guidance text
#  keep working after the Playwright `download()` function was removed.)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main_cli() -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="sjr_helper",
        description=(
            "SJR (SCImago Journal Rank) quartile + impact lookup. Cache-first: "
            "reads a locally-stored SJR CSV (never bundled in-repo, R-03). "
            "Surfaces SJR分区 / 期刊影响力 — NOT a JCR Impact Factor (R-04/R-09)."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # NOTE: the Playwright `download` subcommand was REMOVED in v2.2 A-1. Fetch
    # SJR data via `python3 -m scripts.journal_rank fetch --platform sjr` (mirror
    # over plain HTTP — no browser, no extra dependency).

    p_look = sub.add_parser("lookup", help="Look up one ISSN's quartile/impact.")
    p_look.add_argument("issn", help="ISSN (hyphenated or not).")
    p_look.add_argument("--csv", type=Path, default=None, help="Explicit CSV path (else cache).")
    p_look.add_argument("--cache-dir", type=Path, default=None, help="Cache dir override.")
    p_look.add_argument("--category", default=None, help="Pin a category for the quartile.")

    p_info = sub.add_parser("info", help="Report which CSV is cached and how many journals it has.")
    p_info.add_argument("--csv", type=Path, default=None)
    p_info.add_argument("--cache-dir", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "info":
        lookup = load(csv_path=args.csv, cache_dir=args.cache_dir)
        if not lookup:
            print(json.dumps({"loaded": False, "note": "no SJR CSV cached", "attribution": SJR_ATTRIBUTION}, indent=2))
            return 1
        print(json.dumps({
            "loaded": True,
            "source": str(lookup.source_path),
            "issn_keys": len(lookup),
            "journals": lookup.journal_count,
            "attribution": SJR_ATTRIBUTION,
        }, indent=2))
        return 0

    if args.command == "lookup":
        lookup = load(csv_path=args.csv, cache_dir=args.cache_dir)
        if not lookup:
            print(json.dumps({"found": False, "note": "no SJR CSV cached"}, indent=2))
            return 1
        rec = lookup.for_issn(args.issn)
        if not rec:
            print(json.dumps({"found": False, "issn": args.issn}, indent=2))
            return 2
        print(json.dumps({
            "found": True,
            "title": rec.title,
            "issns": rec.issns,
            "sjr_quartile": rec.quartile_for(args.category),
            "best_quartile": rec.best_quartile,
            "category_quartiles": rec.category_quartiles,
            "sjr_value": rec.sjr_value,
            "attribution": SJR_ATTRIBUTION,
        }, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())
