"""Multi-platform journal-rank data layer (Feature A, v2.2 Wave A-1).

What this module is for
-----------------------
Three independent journal-ranking platforms each answer "what tier / quartile is
this journal in?" with their own taxonomy:

- **CAS (中科院文献情报中心)** — Chinese Academy of Sciences 分区表. 大类分区 1-4
  (区) + a per-大类 rank + a Top flag + up to six 小类 (sub-category) tiers.
- **JCR (Clarivate)** — the *only* source of a real **Impact Factor**. Quartile
  Q1-Q4, IF(2024), category rank.
- **SJR (SCImago)** — SJR Best Quartile Q1-Q4, the SJR indicator value, and a
  per-category quartile breakdown.

This module fetches each platform's CSV from a **public GitHub raw mirror** with
``requests`` (no new dependency, no Cloudflare in the way), parses each platform's
idiosyncratic format, normalises ISSNs onto one ``XXXX-XXXX`` key, and builds one
unified ``ISSN -> JournalRank`` table that downstream code can ``lookup()`` per
paper.

Hard compliance boundaries (read 11_risk_distillation.md + 13_A_redesign_spec.md)
---------------------------------------------------------------------------------
- **We never bundle / commit any ranking data into the repo.** The data is pulled
  *at runtime* from public mirrors into the user's local cache
  (``~/.paper-search-pro/ranks/``). Data never enters our git history. This is the
  "user-side fetch + runtime join + external link" posture the legal review
  (legal_sjr_redistribution.md §7🟢) settled on. The mirror URLs live in config so
  a user can swap them.
- **Attribution is per-platform and exact** (corrects the old SJR mislabel):
    * SJR  -> SCImago custom terms, NOT "CC BY-NC" (legal review §2.4).
    * CAS  -> 中科院文献情报中心; for personal use, 勿公开传播.
    * JCR  -> Clarivate Journal Citation Reports.
  The canonical strings live in ``ATTRIBUTION`` so callers cannot drift.
- **Naming (R-04 / R-09):** only JCR's ``IF(2024)`` is a real **Impact Factor**.
  CAS 区 and SJR quartile are *partition / quartile*, never "影响因子". OpenAlex
  2yr-mean-citedness (filled elsewhere) is an *open journal-impact* figure, also
  not a JIF.

Real headers (empirically fetched 2026-06-25 from the configured mirrors)
-------------------------------------------------------------------------
CAS  (FQBJCR2025-UTF8.csv, comma CSV, UTF-8) — 23 columns:
  ``Journal, 年份, ISSN/EISSN, Review, OA Journal Index（OAJ）, Open Access,
    Web of Science, 标注, 大类, 大类分区, Top, 小类1, 小类1分区, 小类2, 小类2分区,
    小类3, 小类3分区, 小类4, 小类4分区, 小类5, 小类5分区, 小类6, 小类6分区``
  - ISSN/EISSN: ``2053-1583/2053-1583`` (slash-separated, hyphenated).
  - 大类分区:   ``3 [168/495]`` -> tier=3, rank="168/495".
  - Top:        ``是``/``否`` (yes/no).
  - 小类N text: `` MATERIALS SCIENCE, MULTIDISCIPLINARY 材料科学：综合``; 小类N分区
    ``3 [168/436]``. Up to six (most rows use one or two; rest blank).
  - NOTE the live header is "OA Journal Index（OAJ）" (full-width parens), not the
    "OAJ" the spec sketched — columns are resolved by *fuzzy name*, never index.

JCR  (JCR2024-UTF8.csv, comma CSV, UTF-8) — 7 columns:
  ``Journal, ISSN, eISSN, Category, IF(2024), IF Quartile(2024), IF Rank(2024)``
  - ISSN / eISSN: hyphenated; either may be ``N/A``.
  - Category: ``ONCOLOGY(SCIE)``; multiple via ``;`` e.g.
    ``"MATERIALS SCIENCE, MULTIDISCIPLINARY(SCIE);NANOSCIENCE & NANOTECHNOLOGY(SCIE)"``.
  - IF(2024): plain float ``232.4`` (US decimal). IF Rank(2024): ``1/326``.

SJR  (scimagojr 2024.csv, **semicolon** CSV, UTF-8, **European decimals**) —
  27 columns (the live 2024 file added an ``SDG`` column vs older 26-col snapshots,
  which is exactly why columns are resolved by name):
  ``Rank; Sourceid; Title; Type; Issn; Publisher; Open Access; Open Access Diamond;
    SJR; SJR Best Quartile; H index; ...; SDG; Country; Region; Publisher; Coverage;
    Categories; Areas``
  - Issn:       ``"15424863, 00079235"`` (comma-separated, **no hyphen**).
  - SJR:        ``145,004`` (comma is the decimal point).
  - Categories: ``"Hematology (Q1); Oncology (Q1)"``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Compliance constants — single source of truth for per-platform attribution.
# (Corrects the old sjr_helper "CC BY-NC" mislabel; see legal review §2.4.)
# ---------------------------------------------------------------------------

PLATFORMS = ("cas", "jcr", "sjr")

#: Mandatory short attribution per platform (attach wherever data is surfaced).
ATTRIBUTION: Dict[str, str] = {
    "cas": (
        "Data: 中科院文献情报中心期刊分区表 (CAS Journal Ranking). "
        "For personal/non-commercial use; 勿公开传播."
    ),
    "jcr": (
        "Data: Journal Citation Reports (Clarivate). Impact Factor and JCR "
        "quartiles are © Clarivate; for reference only."
    ),
    "sjr": (
        "Data: SCImago Journal Rank, scimagojr.com — non-commercial use as long "
        "as it is cited (SCImago custom terms; NOT a Creative Commons licence)."
    ),
}

#: Longer legal note for report footers / docs.
LEGAL_NOTICE = (
    "Journal rankings are surfaced from third-party platforms and are NOT "
    "redistributed by this tool: data is fetched at runtime from public mirrors "
    "into your local cache. CAS 分区 © 中科院文献情报中心 (personal use, 勿公开传播). "
    "JCR Impact Factor / quartile © Clarivate. SJR quartile / value © SCImago "
    "(scimagojr.com, non-commercial cited use). CAS 区 and SJR quartile are "
    "PARTITIONS, not Impact Factors — only JCR IF(2024) is a real Impact Factor."
)

#: Official portals for "verify at source" external links (Legal Notice allows
#: redirecting to the specific content). Surfaced by display layers (Wave A-3).
PORTAL_URL: Dict[str, str] = {
    "cas": "https://www.fenqubiao.com",
    "jcr": "https://jcr.clarivate.com",
    "sjr": "https://www.scimagojr.com",
}

#: Default source mirrors (overridable via config ``rank.sources``). All three
#: were curl-verified HTTP 200 on 2026-06-25. GitHub raw -> ``requests`` works
#: directly (no Cloudflare, unlike scimagojr.com itself).
DEFAULT_SOURCES: Dict[str, str] = {
    "cas": (
        "https://raw.githubusercontent.com/hitfyd/ShowJCR/master/"
        "%E4%B8%AD%E7%A7%91%E9%99%A2%E5%88%86%E5%8C%BA%E8%A1%A8%E5%8F%8AJCR"
        "%E5%8E%9F%E5%A7%8B%E6%95%B0%E6%8D%AE%E6%96%87%E4%BB%B6/"
        "FQBJCR2025-UTF8.csv"
    ),
    "jcr": (
        "https://raw.githubusercontent.com/hitfyd/ShowJCR/master/"
        "%E4%B8%AD%E7%A7%91%E9%99%A2%E5%88%86%E5%8C%BA%E8%A1%A8%E5%8F%8AJCR"
        "%E5%8E%9F%E5%A7%8B%E6%95%B0%E6%8D%AE%E6%96%87%E4%BB%B6/"
        "JCR2024-UTF8.csv"
    ),
    "sjr": (
        "https://raw.githubusercontent.com/saramabrouk173/zotero-sjr-ranker/"
        "main/scimagojr%202024.csv"
    ),
}

#: Each platform's source year (for the ``source_year`` slot + cache naming).
DEFAULT_YEAR: Dict[str, int] = {"cas": 2025, "jcr": 2024, "sjr": 2024}

#: Default cache dir (overridable via config ``rank.cache_dir``). Data lives under
#: the user's home — NEVER in the repo (R-02/R-03).
DEFAULT_CACHE_DIR = Path.home() / ".paper-search-pro" / "ranks"

#: A cached CSV older than this is considered stale and re-fetched on demand.
#: Rankings update ~once a year, so this is generous; fetch is still init-once
#: (a present, fresh file is never re-downloaded).
DEFAULT_STALE_DAYS = 365

_HTTP_TIMEOUT = 60
_USER_AGENT = (
    "paper-search-pro/2.2 "
    "(https://github.com/anthropic/paper-search-pro; journal-rank fetch)"
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CASRank:
    """CAS (中科院) record for one journal."""

    tier: Optional[int] = None  # 大类分区 区号 1-4
    rank: Optional[str] = None  # "168/495" (within 大类)
    top: bool = False  # Top 期刊 flag
    minor: List[Dict] = field(default_factory=list)  # [{category, tier, rank}]
    source_year: Optional[int] = None


@dataclass
class JCRRank:
    """JCR (Clarivate) record for one journal — the only real Impact Factor."""

    quartile: Optional[str] = None  # "Q1".."Q4" (best across categories)
    impact_factor: Optional[float] = None  # IF(2024) — the *real* IF
    rank: Optional[str] = None  # "1/326"
    category: Optional[str] = None  # raw Category string (may be multi)
    source_year: Optional[int] = None


@dataclass
class SJRRank:
    """SJR (SCImago) record for one journal."""

    best_quartile: Optional[str] = None  # "Q1".."Q4"
    sjr: Optional[float] = None  # the SJR indicator value
    per_category: List[Dict] = field(default_factory=list)  # [{category, quartile}]
    source_year: Optional[int] = None


@dataclass
class JournalRank:
    """Unified multi-platform rank for one journal, keyed by any of its ISSNs.

    Additive / optional: every platform slot defaults to None so a journal found
    on only one platform still produces a valid record. ``matched_platforms``
    lists which platforms actually contributed.

    The ``openalex`` slot ({mean_citedness_2yr, h_index}) is NOT filled by the CSV
    parsers — it is attached downstream by the search pipeline from OpenAlex
    summary_stats (CC0). R-04/R-09: it is an OPEN journal-impact figure, never an
    Impact Factor (only JCR IF(2024) is a real IF).
    """

    title: Optional[str] = None
    issns: List[str] = field(default_factory=list)  # normalised XXXX-XXXX
    cas: Optional[CASRank] = None
    jcr: Optional[JCRRank] = None
    sjr: Optional[SJRRank] = None
    openalex: Optional[Dict] = None  # {mean_citedness_2yr: float|None, h_index: int|None}
    matched_issn: Optional[str] = None  # the ISSN the lookup hit on
    matched_platforms: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ISSN normalisation
# ---------------------------------------------------------------------------

_ISSN_CLEAN_RE = re.compile(r"[^0-9xX]")
#: "MATERIALS SCIENCE (Q1)" -> capture name + quartile (SJR Categories column).
_SJR_CAT_RE = re.compile(r"\s*([^;()]+?)\s*\((Q[1-4])\)")
_QUARTILE_RE = re.compile(r"^Q[1-4]$")
#: CAS partition cell "3 [168/495]" -> tier=3, rank="168/495".
_CAS_PARTITION_RE = re.compile(r"\s*(\d+)\s*(?:\[\s*([^\]]+?)\s*\])?")


def normalize_issn(issn: Optional[str]) -> Optional[str]:
    """Normalise one ISSN to canonical ``XXXX-XXXX`` (hyphenated, upper-X).

    Accepts any of the three platforms' formats: JCR/CAS hyphenated
    (``2053-1583``), SJR hyphen-free (``20531583``), lower-case check digit
    (``1542486x``). Returns None for anything that is not exactly 8 ISSN chars
    after cleaning (e.g. JCR's ``N/A``)."""
    if not issn:
        return None
    cleaned = _ISSN_CLEAN_RE.sub("", str(issn)).upper()
    if len(cleaned) != 8:
        return None
    return f"{cleaned[:4]}-{cleaned[4:]}"


def normalize_issns(raw: Optional[str], *, sep: str = ",") -> List[str]:
    """Split a multi-ISSN cell into a list of canonical ``XXXX-XXXX`` keys.

    Handles SJR's comma-joined ``"15424863, 00079235"`` (sep=",") and CAS's
    slash-joined ``"2053-1583/2053-1583"`` (sep="/"). De-duplicated, order
    preserved, garbage / ``N/A`` dropped."""
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    # Be liberal: split on the requested separator AND on the others, so a
    # caller that passes the wrong sep still recovers both ISSNs.
    parts = re.split(r"[,/;]", str(raw))
    for part in parts:
        norm = normalize_issn(part)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _parse_us_float(value: Optional[str]) -> Optional[float]:
    """Parse a US-format float (``232.4``). Blank / 'N/A' -> None, never raises."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() in ("N/A", "NA", "-", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_european_float(value: Optional[str]) -> Optional[float]:
    """Parse SJR's European decimal (``145,004`` -> 145.004). Never raises.

    The SJR value column uses a comma decimal separator and no thousands
    separator, so a single comma->dot is correct."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _clean_quartile(value: Optional[str]) -> Optional[str]:
    """Validate a quartile cell -> 'Q1'..'Q4' or None."""
    if not value:
        return None
    s = str(value).strip().upper()
    return s if _QUARTILE_RE.match(s) else None


def _best_quartile(quartiles) -> Optional[str]:
    """Best (numerically smallest) quartile from an iterable, or None."""
    valid = [q for q in quartiles if q and _QUARTILE_RE.match(q)]
    return min(valid) if valid else None


def _yn_to_bool(value: Optional[str]) -> bool:
    """CAS '是'/'否' (or 'Y'/'N') -> bool. Anything not affirmative -> False."""
    if not value:
        return False
    s = str(value).strip()
    return s in ("是", "Y", "y", "yes", "Yes", "true", "True", "1")


# ---------------------------------------------------------------------------
# Header resolution (by fuzzy name, never index — live headers drift)
# ---------------------------------------------------------------------------


def _header_map(header: List[str]) -> Dict[str, int]:
    """Map normalised header tokens (lower, stripped) -> column index."""
    return {h.strip().lower(): i for i, h in enumerate(header)}


def _find_col(hmap: Dict[str, int], *candidates: str) -> Optional[int]:
    """Resolve a column index by exact-then-substring fuzzy match.

    Tries each candidate exactly first, then as a substring of any header. This
    survives the live-vs-spec header drift (e.g. CAS's "OA Journal Index（OAJ）"
    vs the spec's "OAJ", or SJR's added "SDG" column)."""
    for cand in candidates:
        c = cand.strip().lower()
        if c in hmap:
            return hmap[c]
    for cand in candidates:
        c = cand.strip().lower()
        for name, idx in hmap.items():
            if c in name:
                return idx
    return None


def _cell(row: List[str], idx: Optional[int]) -> Optional[str]:
    """Safe cell access: returns the stripped cell or None."""
    if idx is None or idx >= len(row):
        return None
    v = row[idx].strip()
    return v or None


# ---------------------------------------------------------------------------
# Per-platform parsers (each returns List[JournalRank] with one platform filled)
# ---------------------------------------------------------------------------


def parse_cas_csv(text: str, *, year: Optional[int] = None) -> List[JournalRank]:
    """Parse a CAS (中科院) CSV into JournalRank records (cas slot filled).

    Comma CSV, UTF-8. Columns resolved by name. 大类分区 -> tier + rank; Top
    flag; up to six 小类 -> minor[]. Rows with no joinable ISSN are skipped.
    Never raises on a malformed row; raises only if the ISSN column is missing."""
    out: List[JournalRank] = []
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return out
    hmap = _header_map(header)
    i_issn = _find_col(hmap, "issn/eissn", "issn", "issn/eissn ")
    if i_issn is None:
        raise ValueError(
            f"CAS CSV has no ISSN/EISSN column (header: {header[:6]}...)."
        )
    i_title = _find_col(hmap, "journal")
    i_year = _find_col(hmap, "年份")
    i_major_cat = _find_col(hmap, "大类")
    i_major_part = _find_col(hmap, "大类分区")
    i_top = _find_col(hmap, "top")
    # Up to six minor categories: text col 小类N + partition col 小类N分区.
    minor_cols = []
    for n in range(1, 7):
        ci = _find_col(hmap, f"小类{n}")
        pi = _find_col(hmap, f"小类{n}分区")
        if ci is not None or pi is not None:
            minor_cols.append((ci, pi))

    for row in reader:
        if not row:
            continue
        issns = normalize_issns(_cell(row, i_issn), sep="/")
        if not issns:
            continue
        tier, rank = _parse_cas_partition(_cell(row, i_major_part))
        minor: List[Dict] = []
        for ci, pi in minor_cols:
            cat = _cell(row, ci)
            mtier, mrank = _parse_cas_partition(_cell(row, pi))
            if cat or mtier is not None:
                minor.append({"category": cat, "tier": mtier, "rank": mrank})
        yr = year
        if yr is None:
            yr_cell = _cell(row, i_year)
            try:
                yr = int(yr_cell) if yr_cell else None
            except ValueError:
                yr = None
        cas = CASRank(
            tier=tier,
            rank=rank,
            top=_yn_to_bool(_cell(row, i_top)),
            minor=minor,
            source_year=yr,
        )
        out.append(
            JournalRank(
                title=_cell(row, i_title),
                issns=issns,
                cas=cas,
                matched_platforms=["cas"],
            )
        )
    return out


def _parse_cas_partition(cell: Optional[str]):
    """CAS partition cell '3 [168/495]' -> (tier:int|None, rank:str|None)."""
    if not cell:
        return None, None
    m = _CAS_PARTITION_RE.match(str(cell).strip())
    if not m:
        return None, None
    try:
        tier = int(m.group(1))
    except (TypeError, ValueError):
        tier = None
    rank = m.group(2).strip() if m.group(2) else None
    return tier, rank


def parse_jcr_csv(text: str, *, year: Optional[int] = None) -> List[JournalRank]:
    """Parse a JCR (Clarivate) CSV into JournalRank records (jcr slot filled).

    Comma CSV. ISSN + eISSN both indexed. IF(2024) is the *real* Impact Factor.
    Category may carry multiple ``;``-separated entries with a ``(SCIE)`` suffix.
    Rows with neither ISSN joinable are skipped."""
    out: List[JournalRank] = []
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return out
    hmap = _header_map(header)
    i_issn = _find_col(hmap, "issn")
    i_eissn = _find_col(hmap, "eissn")
    if i_issn is None and i_eissn is None:
        raise ValueError(f"JCR CSV has no ISSN/eISSN column (header: {header[:6]}...).")
    i_title = _find_col(hmap, "journal")
    i_cat = _find_col(hmap, "category")
    i_if = _find_col(hmap, "if(2024)", "if(2025)", "if")
    i_quart = _find_col(hmap, "if quartile(2024)", "if quartile(2025)", "if quartile")
    i_rank = _find_col(hmap, "if rank(2024)", "if rank(2025)", "if rank")

    for row in reader:
        if not row:
            continue
        issns: List[str] = []
        for ci in (i_issn, i_eissn):
            for norm in normalize_issns(_cell(row, ci)):
                if norm not in issns:
                    issns.append(norm)
        if not issns:
            continue
        jcr = JCRRank(
            quartile=_clean_quartile(_cell(row, i_quart)),
            impact_factor=_parse_us_float(_cell(row, i_if)),
            rank=_cell(row, i_rank),
            category=_cell(row, i_cat),
            source_year=year if year is not None else 2024,
        )
        out.append(
            JournalRank(
                title=_cell(row, i_title),
                issns=issns,
                jcr=jcr,
                matched_platforms=["jcr"],
            )
        )
    return out


def parse_sjr_csv(text: str, *, year: Optional[int] = None) -> List[JournalRank]:
    """Parse an SJR (SCImago) CSV into JournalRank records (sjr slot filled).

    **Semicolon**-separated, European decimals (``145,004``). ISSN cell is
    comma-joined hyphen-free. Categories carry per-category quartiles. Best
    quartile is derived from categories when the dedicated column is blank.
    Columns resolved by name (the live 2024 file has an extra ``SDG`` column)."""
    out: List[JournalRank] = []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return out
    hmap = _header_map(header)
    i_issn = _find_col(hmap, "issn")
    if i_issn is None:
        raise ValueError(f"SJR CSV has no Issn column (header: {header[:6]}...).")
    i_title = _find_col(hmap, "title")
    i_best = _find_col(hmap, "sjr best quartile")
    i_sjr = _find_col(hmap, "sjr")
    i_cats = _find_col(hmap, "categories")

    for row in reader:
        if not row:
            continue
        issns = normalize_issns(_cell(row, i_issn), sep=",")
        if not issns:
            continue
        per_cat = _parse_sjr_categories(_cell(row, i_cats))
        best = _clean_quartile(_cell(row, i_best))
        if best is None and per_cat:
            best = _best_quartile([c["quartile"] for c in per_cat])
        sjr = SJRRank(
            best_quartile=best,
            sjr=_parse_european_float(_cell(row, i_sjr)),
            per_category=per_cat,
            source_year=year if year is not None else 2024,
        )
        out.append(
            JournalRank(
                title=_cell(row, i_title),
                issns=issns,
                sjr=sjr,
                matched_platforms=["sjr"],
            )
        )
    return out


def _parse_sjr_categories(raw: Optional[str]) -> List[Dict]:
    """SJR Categories cell -> [{category, quartile}]. Bare cats (no Qn) skipped."""
    out: List[Dict] = []
    if not raw:
        return out
    for name, quart in _SJR_CAT_RE.findall(str(raw)):
        name = name.strip()
        if name:
            out.append({"category": name, "quartile": quart})
    return out


_PARSERS = {"cas": parse_cas_csv, "jcr": parse_jcr_csv, "sjr": parse_sjr_csv}


# ---------------------------------------------------------------------------
# Unified table assembly (merge the three per-platform record lists by ISSN)
# ---------------------------------------------------------------------------


def build_unified_table(per_platform: Dict[str, List[JournalRank]]) -> Dict[str, JournalRank]:
    """Merge per-platform record lists into one ``ISSN -> JournalRank``.

    Each platform contributes records carrying just its own slot; we merge by
    ISSN so a journal present on all three lands as one JournalRank with cas/jcr/
    sjr all filled, indexed under *every* ISSN it has (print + electronic) so a
    later join on any ISSN hits. On an ISSN collision across platforms, the
    platform slot is filled if empty (first non-None wins, stable)."""
    merged: Dict[str, JournalRank] = {}
    for platform in PLATFORMS:
        for rec in per_platform.get(platform, []) or []:
            slot = getattr(rec, platform)
            # Find any existing merged record that shares an ISSN.
            target: Optional[JournalRank] = None
            for issn in rec.issns:
                if issn in merged:
                    target = merged[issn]
                    break
            if target is None:
                target = JournalRank(title=rec.title, issns=[])
            # Union ISSNs + re-index them all onto the same record.
            for issn in rec.issns:
                if issn not in target.issns:
                    target.issns.append(issn)
                merged[issn] = target
            # Fill the platform slot (first non-None wins).
            if getattr(target, platform) is None and slot is not None:
                setattr(target, platform, slot)
            if platform not in target.matched_platforms:
                target.matched_platforms.append(platform)
            if not target.title and rec.title:
                target.title = rec.title
    return merged


# ---------------------------------------------------------------------------
# Cache + fetch (init-once; never re-fetch a present, fresh file)
# ---------------------------------------------------------------------------


def _cache_dir(cache_dir: Optional[Path] = None) -> Path:
    return Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR


def _cache_path(platform: str, year: Optional[int], cache_dir: Optional[Path]) -> Path:
    yr = year if year is not None else DEFAULT_YEAR.get(platform, "")
    return _cache_dir(cache_dir) / f"{platform}_{yr}.csv"


def _is_fresh(path: Path, stale_days: int) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86400.0
    return age_days <= stale_days


def fetch(
    platform: Optional[str] = None,
    year: Optional[int] = None,
    *,
    sources: Optional[Dict[str, str]] = None,
    cache_dir: Optional[Path] = None,
    stale_days: int = DEFAULT_STALE_DAYS,
    force: bool = False,
    session: Optional[requests.Session] = None,
) -> Dict[str, Optional[Path]]:
    """Fetch one (or all) platform CSV(s) from the mirror into the cache.

    init-once: a present, non-stale cached file is NOT re-downloaded unless
    ``force=True``. Network failure / source 404 degrades gracefully (that
    platform maps to None; the others still fetch). Never raises on the network.

    Args:
        platform: "cas"|"jcr"|"sjr", or None for all three.
        year: source year override (only used for cache naming + source_year).
        sources: {platform: url} override (else DEFAULT_SOURCES / config).
        cache_dir: cache directory override.
        stale_days: re-fetch when a cached file is older than this.
        force: re-fetch even if a fresh cache exists.
        session: an injectable requests.Session (tests pass a fake; default
            constructs one with the polite User-Agent).

    Returns ``{platform: Path|None}`` for the platform(s) requested."""
    src = {**DEFAULT_SOURCES, **(sources or {})}
    targets = [platform] if platform else list(PLATFORMS)
    cdir = _cache_dir(cache_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    sess = session
    result: Dict[str, Optional[Path]] = {}
    for plat in targets:
        if plat not in PLATFORMS:
            print(f"[journal_rank] unknown platform '{plat}' — skipped.")
            result[plat] = None
            continue
        path = _cache_path(plat, year, cache_dir)
        if not force and _is_fresh(path, stale_days):
            result[plat] = path  # init-once: already cached + fresh
            continue
        url = src.get(plat)
        if not url:
            print(f"[journal_rank] no source URL for '{plat}' — skipped.")
            result[plat] = None
            continue
        if sess is None:
            sess = requests.Session()
            sess.headers["User-Agent"] = _USER_AGENT
        try:
            resp = sess.get(url, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            print(f"[journal_rank] fetch failed for '{plat}' ({type(exc).__name__}: "
                  f"{exc}). Quartiles for this platform will be unavailable.")
            result[plat] = None
            continue
        if resp.status_code != 200 or not resp.content:
            print(f"[journal_rank] source for '{plat}' returned HTTP "
                  f"{resp.status_code} (URL may have moved — set a mirror in "
                  f"config rank.sources). Skipped.")
            result[plat] = None
            continue
        try:
            path.write_bytes(resp.content)
        except OSError as exc:
            print(f"[journal_rank] could not write cache for '{plat}': {exc}.")
            result[plat] = None
            continue
        print(f"[journal_rank] fetched {plat} -> {path} ({len(resp.content)} bytes)")
        print(f"  {ATTRIBUTION[plat]}")
        result[plat] = path
    return result


def fetch_all(**kwargs) -> Dict[str, Optional[Path]]:
    """Fetch all three platforms (convenience wrapper over ``fetch``)."""
    return fetch(platform=None, **kwargs)


# ---------------------------------------------------------------------------
# Load -> in-memory unified lookup
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    """Read a cached CSV as UTF-8 (BOM-tolerant)."""
    return path.read_bytes().decode("utf-8-sig", errors="replace")


class RankLookup:
    """Loaded multi-platform rank table + ISSN join surface. Build via ``load()``."""

    def __init__(
        self,
        table: Dict[str, JournalRank],
        *,
        sources: Dict[str, Optional[Path]],
        years: Dict[str, Optional[int]],
    ):
        self._table = table
        self.sources = sources  # {platform: cache Path or None}
        self.years = years  # {platform: source_year or None}
        self.loaded_platforms = [p for p, path in sources.items() if path is not None]

    def __len__(self) -> int:
        """Distinct ISSN keys."""
        return len(self._table)

    @property
    def journal_count(self) -> int:
        """Distinct journal records (de-duped across multi-ISSN indexing)."""
        return len({id(rec) for rec in self._table.values()})

    def lookup(self, issn_list) -> Optional[JournalRank]:
        """Join: first matching JournalRank for any of the given (raw) ISSNs.

        ``issn_list`` may be a single string (possibly comma/slash-joined) or a
        list of raw ISSNs in any platform format. Returns the matched record
        with ``matched_issn`` set, or None when no ISSN joins."""
        if isinstance(issn_list, str):
            candidates = normalize_issns(issn_list)
        else:
            candidates = []
            for raw in issn_list or []:
                candidates.extend(normalize_issns(raw))
        for issn in candidates:
            rec = self._table.get(issn)
            if rec is not None:
                rec.matched_issn = issn
                return rec
        return None

    def info(self) -> Dict:
        """Cache overview: which platforms / years / journal & ISSN counts."""
        per_platform = {p: 0 for p in PLATFORMS}
        for rec in {id(r): r for r in self._table.values()}.values():
            for p in PLATFORMS:
                if getattr(rec, p) is not None:
                    per_platform[p] += 1
        return {
            "loaded_platforms": self.loaded_platforms,
            "sources": {p: (str(path) if path else None) for p, path in self.sources.items()},
            "years": self.years,
            "issn_keys": len(self),
            "journals": self.journal_count,
            "journals_per_platform": per_platform,
            "attribution": {p: ATTRIBUTION[p] for p in self.loaded_platforms},
        }


def load(
    *,
    platforms: Optional[List[str]] = None,
    cache_dir: Optional[Path] = None,
    paths: Optional[Dict[str, Path]] = None,
    years: Optional[Dict[str, int]] = None,
) -> Optional[RankLookup]:
    """Load a RankLookup from the cache (does NOT fetch — call ``fetch`` first).

    Resolution: for each requested platform, use an explicit ``paths[platform]``
    if given, else the cached ``{platform}_{year}.csv``. Platforms with no cached
    file are simply absent from the unified table (graceful degradation — a
    lookup just won't have that platform's slot). Returns None only when NO
    platform has any cached data at all (the caller then degrades fully)."""
    want = platforms or list(PLATFORMS)
    per_platform_records: Dict[str, List[JournalRank]] = {}
    used_paths: Dict[str, Optional[Path]] = {}
    used_years: Dict[str, Optional[int]] = {}
    for plat in want:
        if plat not in PLATFORMS:
            continue
        path = (paths or {}).get(plat) or _cache_path(
            plat, (years or {}).get(plat), cache_dir
        )
        if not path or not Path(path).exists():
            used_paths[plat] = None
            used_years[plat] = (years or {}).get(plat)
            continue
        try:
            text = _read_text(Path(path))
            yr = (years or {}).get(plat, DEFAULT_YEAR.get(plat))
            per_platform_records[plat] = _PARSERS[plat](text, year=yr)
            used_paths[plat] = Path(path)
            used_years[plat] = yr
        except (OSError, ValueError) as exc:
            print(f"[journal_rank] could not parse cached {plat} CSV: {exc}.")
            used_paths[plat] = None
            used_years[plat] = (years or {}).get(plat)
    if not any(used_paths.get(p) for p in PLATFORMS):
        return None  # nothing cached -> full degradation
    table = build_unified_table(per_platform_records)
    return RankLookup(table, sources=used_paths, years=used_years)


# ---------------------------------------------------------------------------
# Serialisation helper (JournalRank -> JSON-safe dict)
# ---------------------------------------------------------------------------


def rank_to_dict(rank: Optional[JournalRank]) -> Optional[Dict]:
    """JournalRank -> JSON-safe dict (or None). Used by display/CLI layers."""
    if rank is None:
        return None
    return asdict(rank)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main_cli(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="journal_rank",
        description=(
            "Multi-platform journal-rank data layer (CAS / JCR / SJR). Fetches "
            "ranking CSVs from public mirrors into a local cache (never bundled "
            "in-repo) and joins them by ISSN. CAS 区 & SJR quartile are "
            "PARTITIONS; only JCR IF(2024) is a real Impact Factor."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="Fetch ranking CSV(s) into the cache (init-once).")
    p_fetch.add_argument("--platform", choices=list(PLATFORMS), default=None,
                         help="One platform; omit for all three.")
    p_fetch.add_argument("--year", type=int, default=None, help="Source year (cache naming).")
    p_fetch.add_argument("--cache-dir", type=Path, default=None)
    p_fetch.add_argument("--force", action="store_true", help="Re-fetch even if cached.")

    p_look = sub.add_parser("lookup", help="Look up one ISSN across all platforms.")
    p_look.add_argument("issn", help="ISSN (any platform format).")
    p_look.add_argument("--cache-dir", type=Path, default=None)

    p_info = sub.add_parser("info", help="Report cached platforms / years / journal counts.")
    p_info.add_argument("--cache-dir", type=Path, default=None)

    args = parser.parse_args(argv)

    # Pull config overrides (sources / cache_dir) if available — degrade if not.
    cfg_sources, cfg_cache_dir = _load_rank_config()

    if args.command == "fetch":
        cache_dir = args.cache_dir or cfg_cache_dir
        result = fetch(
            platform=args.platform, year=args.year, sources=cfg_sources,
            cache_dir=cache_dir, force=args.force,
        )
        ok = any(v is not None for v in result.values())
        print(json.dumps({p: (str(v) if v else None) for p, v in result.items()}, indent=2, ensure_ascii=False))
        return 0 if ok else 1

    cache_dir = args.cache_dir or cfg_cache_dir

    if args.command == "info":
        lk = load(cache_dir=cache_dir)
        if lk is None:
            print(json.dumps({
                "loaded": False,
                "note": "no ranking CSV cached — run `python3 -m scripts.journal_rank fetch`",
            }, indent=2, ensure_ascii=False))
            return 1
        print(json.dumps({"loaded": True, **lk.info()}, indent=2, ensure_ascii=False))
        return 0

    if args.command == "lookup":
        lk = load(cache_dir=cache_dir)
        if lk is None:
            print(json.dumps({
                "found": False,
                "note": "no ranking CSV cached — run `python3 -m scripts.journal_rank fetch`",
            }, indent=2, ensure_ascii=False))
            return 1
        rec = lk.lookup(args.issn)
        if rec is None:
            print(json.dumps({"found": False, "issn": args.issn}, indent=2, ensure_ascii=False))
            return 2
        out = {"found": True, **rank_to_dict(rec)}
        out["attribution"] = {p: ATTRIBUTION[p] for p in rec.matched_platforms}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


def _load_rank_config():
    """Best-effort read of config ``rank.sources`` / ``rank.cache_dir``.

    Returns (sources_dict_or_None, cache_dir_Path_or_None). Degrades silently to
    (None, None) if config is unavailable (CLI still works on defaults)."""
    try:
        try:
            from .config import load_config  # package-relative
        except ImportError:  # pragma: no cover - CLI shim
            import sys as _sys
            _here = Path(__file__).resolve().parent
            _sys.path.insert(0, str(_here.parent))
            from scripts.config import load_config  # type: ignore
        cfg = load_config()
        rank = getattr(cfg, "rank", None)
        if isinstance(rank, dict):
            sources = rank.get("sources") or None
            cache = rank.get("cache_dir")
            cache_dir = Path(cache).expanduser() if cache else None
            return sources, cache_dir
    except Exception:
        pass
    return None, None


if __name__ == "__main__":
    import sys

    sys.exit(_main_cli())
