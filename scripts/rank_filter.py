"""Annotate + filter papers by multi-platform journal rank (Feature A, Wave A-2).

Where this sits in the pipeline
-------------------------------
``journal_rank.py`` (Wave A-1) is the *data layer*: it fetches the CAS / JCR / SJR
CSVs and joins an ISSN to a ``JournalRank``. This module is the *logic layer* on
top of it — the platform-agnostic functions that BOTH the headless path
(agent_search) and the human 14-STEP path (SKILL.md, Wave A-3) call:

    annotate_papers(papers, lookup)      -> attach ``paper.journal_rank`` per paper
    filter_by_rank(papers, platform, ...) -> keep the ones in the wanted tiers/top
    journal_rank_dict(journal_rank)       -> JSON-safe ``journal_rank`` dict per
                                             spec §3 (the unified multi-platform
                                             schema CAS/JCR/SJR + OpenAlex open
                                             impact; R-04 naming enforced).
                                             ``rank_metric_dict`` is a back-compat
                                             alias for the same function.

Design invariants
-----------------
- **annotate is platform-blind**: every paper gets all three platforms' data (or
  None where the journal is not on a platform). Filtering is a *separate* step.
- **filter is "re-filter the annotated pool"**: switching platform / tier is just
  calling filter again on the already-annotated candidates — NO re-search. This is
  the "切换 = 重筛不重搜" contract from spec §7; the adaptive-deepening loop only
  re-searches when the *annotated pool itself* runs short of survivors.
- **papers with no data for the chosen platform are not silently dropped**: they
  are partitioned out as ``no_platform_data`` so the caller can report the count
  (spec §2 "无该平台分区数据的论文单独标记").
- **R-04 / R-09 naming is enforced in the serialised dict**: only JCR's IF(2024)
  is an ``impact_factor``; CAS 区 and SJR quartile are partitions; the OpenAlex
  open-impact figure (filled elsewhere) is never called an impact factor here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

# journal_rank holds the JournalRank dataclass + ATTRIBUTION; we import lazily in
# functions that need ATTRIBUTION to keep this module importable even if requests
# is absent (annotate/filter themselves never touch the network).


# Quartile ordering so "Q1,Q2" comparisons are unambiguous.
_QUARTILE_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}


# ---------------------------------------------------------------------------
# Tier / quartile request normalisation
# ---------------------------------------------------------------------------


def normalize_keep_tiers(platform: str, keep) -> Tuple[List[int], List[str]]:
    """Turn a heterogeneous keep spec into (cas_tiers, quartiles) for a platform.

    Accepts ints (1,2), tier strings ("1","2"), or quartile strings ("Q1","Q2")
    and maps them onto the platform's native taxonomy:
      - cas  -> integer tiers (区 1-4); "Q1" is accepted and read as tier 1.
      - jcr/sjr -> quartile strings; bare ints/"1" are read as "Q1".
    Returns (tiers, quartiles); only the slot relevant to ``platform`` is filled.
    """
    tiers: List[int] = []
    quarts: List[str] = []
    for item in keep or []:
        if item is None:
            continue
        s = str(item).strip().upper()
        if not s:
            continue
        if s.startswith("Q") and s[1:].isdigit():
            n = int(s[1:])
        elif s.isdigit():
            n = int(s)
        else:
            continue
        if not (1 <= n <= 4):
            continue
        if platform == "cas":
            if n not in tiers:
                tiers.append(n)
        else:
            q = f"Q{n}"
            if q not in quarts:
                quarts.append(q)
    return tiers, quarts


# ---------------------------------------------------------------------------
# Annotate (attach the unified JournalRank to each paper — platform-blind)
# ---------------------------------------------------------------------------


def annotate_papers(papers, lookup) -> int:
    """Attach ``paper.journal_rank`` for every paper whose ISSN joins ``lookup``.

    ``lookup`` is a ``journal_rank.RankLookup`` (or None → no-op). Returns the
    number of papers that got a rank record. Idempotent and network-free: it only
    reads each paper's already-present ``issn`` (backfill is the caller's job)."""
    if lookup is None:
        return 0
    annotated = 0
    for p in papers:
        issn = getattr(p, "issn", None)
        if not issn:
            continue
        rec = lookup.lookup(issn)
        if rec is not None:
            p.journal_rank = rec
            annotated += 1
    return annotated


# ---------------------------------------------------------------------------
# Per-paper platform predicates
# ---------------------------------------------------------------------------


def _has_platform_data(rank, platform: str) -> bool:
    """True when the paper's JournalRank actually carries this platform's slot."""
    if rank is None:
        return False
    return getattr(rank, platform, None) is not None


def _cat_matches(want: str, have: Optional[str]) -> bool:
    """Case-insensitive, whitespace-tolerant category match (substring either way).

    CAS / SJR / JCR category labels are free text (Chinese 小类 names, ``;``-joined
    JCR categories, SCImago English category strings), so we match liberally: the
    pinned category matches when it is contained in the journal's category label or
    vice-versa. Empty ``have`` never matches."""
    if not have:
        return False
    a = str(want).strip().lower()
    b = str(have).strip().lower()
    if not a:
        return False
    return a in b or b in a


def _cas_minor_tier_for(slot, category: str):
    """The CAS 小类 tier for the pinned category (or None when the journal is not in
    that 小类). Used to filter on the sub-category partition, not the 大类 tier."""
    for m in getattr(slot, "minor", None) or []:
        if _cat_matches(category, m.get("category")):
            return m.get("tier")
    return None


def _sjr_quartile_for(slot, category: str) -> Optional[str]:
    """The SJR quartile for the pinned category (or None when the journal is not in
    that category). Used to filter on the per-category quartile, not best_quartile."""
    for c in getattr(slot, "per_category", None) or []:
        if _cat_matches(category, c.get("category")):
            return c.get("quartile")
    return None


def _passes_platform(
    rank,
    platform: str,
    tiers: List[int],
    quarts: List[str],
    top: bool,
    category: Optional[str] = None,
) -> bool:
    """Does this paper's rank satisfy the requested tiers / quartiles / top-only?

    Caller guarantees the paper HAS platform data (checked separately so the
    no-data papers can be counted rather than conflated with fails).

    When ``category`` is given (the ``--rank-category`` pin, spec §9), the partition
    is read from that sub-category rather than the journal's best/大类 value:
      - CAS: the 小类 tier for the matching category (``minor[]``); the journal must
        actually be in that 小类 or it fails.
      - SJR: the per-category quartile (``per_category[]``); the journal must be in
        that category or it fails.
      - JCR: per-category quartiles are not in the source, so a category pin acts as
        a membership requirement — the journal's (``;``-joined) ``category`` must
        contain the pin — and the quartile check uses the journal's best quartile."""
    slot = getattr(rank, platform, None)
    if slot is None:
        return False
    if platform == "cas":
        if top and not getattr(slot, "top", False):
            return False
        # Category pin: read the 小类 tier instead of the 大类 tier (and require the
        # journal to be in that 小类 at all).
        if category:
            minor_tier = _cas_minor_tier_for(slot, category)
            if minor_tier is None:
                return False
            if tiers:
                return minor_tier in tiers
            return True  # in the pinned 小类; top (if any) already satisfied above
        if tiers:
            return slot.tier in tiers
        return True  # platform-data present; top (if any) already satisfied above
    # jcr / sjr quartile platforms
    if platform == "sjr" and category:
        # Read the per-category quartile (and require the journal to be in it).
        q = _sjr_quartile_for(slot, category)
        if q is None:
            return False
    elif platform == "jcr" and category:
        # JCR has no per-category quartile breakdown; the pin is a membership gate.
        if not _cat_matches(category, getattr(slot, "category", None)):
            return False
        q = slot.quartile
    else:
        q = slot.quartile if platform == "jcr" else slot.best_quartile
    if top:
        # "top" on a quartile platform == Q1 (the closest analogue).
        if q != "Q1":
            return False
    if quarts:
        return q in quarts
    return True


# ---------------------------------------------------------------------------
# Filter (re-filter the annotated pool — no re-search)
# ---------------------------------------------------------------------------


def filter_by_rank(
    papers,
    platform: str,
    *,
    tiers: Optional[List[int]] = None,
    quartiles: Optional[List[str]] = None,
    top: bool = False,
    category: Optional[str] = None,
) -> Tuple[list, list, list]:
    """Split the annotated ``papers`` into (kept, filtered_out, no_platform_data).

    - kept              : satisfy the platform's tier/quartile/top request.
    - filtered_out      : have this platform's data but fall outside the request.
    - no_platform_data  : not present on this platform at all (reported, not
                          silently dropped — spec §2).

    Pure re-filter of the in-memory annotated pool — never re-searches (the
    "切换 = 重筛不重搜" contract, spec §7). When neither tiers/quartiles nor top is
    given this still partitions on data presence (so a caller can see how many of
    the pool are even on the chosen platform).

    ``category`` (the ``--rank-category`` pin, spec §9) narrows the partition to a
    specific sub-category: CAS 小类 tier / SJR per-category quartile / JCR category
    membership (see ``_passes_platform``). A journal not present in the pinned
    sub-category fails the filter (it lands in ``filtered_out``, since it does have
    the platform's top-level data)."""
    tiers = tiers or []
    quarts = [q.upper() for q in (quartiles or [])]
    kept, dropped, nodata = [], [], []
    for p in papers:
        rank = getattr(p, "journal_rank", None)
        if not _has_platform_data(rank, platform):
            nodata.append(p)
            continue
        if _passes_platform(rank, platform, tiers, quarts, top, category=category):
            kept.append(p)
        else:
            dropped.append(p)
    return kept, dropped, nodata


# ---------------------------------------------------------------------------
# Serialisation: unified multi-platform journal_rank dict (spec §3)
# ---------------------------------------------------------------------------


def journal_rank_dict(rank) -> Optional[Dict]:
    """Serialise a ``JournalRank`` into the unified ``journal_rank`` dict (spec §3).

    This is the SINGLE serialisation point for the multi-platform record — both the
    headless agent envelope and the human report render through it, so the schema
    can never drift between modes. The output carries four slots: CAS 区 / JCR
    Q·IF / SJR Q + an ``openalex`` open-impact slot ({mean_citedness_2yr, h_index}).

    Returns None when ``rank`` is None or carries no data at all (no platform AND no
    OpenAlex impact). R-04 / R-09 naming is enforced: only the JCR slot exposes
    ``impact_factor`` (the real IF); CAS exposes ``tier`` (区, a partition), SJR
    exposes a quartile, and the OpenAlex slot is ``mean_citedness_2yr`` — never named
    "影响因子" / "impact_factor"."""
    if rank is None:
        return None
    oa = getattr(rank, "openalex", None)
    if not (rank.cas or rank.jcr or rank.sjr or oa):
        return None
    out: Dict = {
        "cas": None,
        "jcr": None,
        "sjr": None,
        # OPEN journal-impact (CC0) — NOT an Impact Factor (R-04/R-09). None unless
        # the search pipeline attached it from OpenAlex summary_stats.
        "openalex": dict(oa) if isinstance(oa, dict) else None,
        "matched_issn": rank.matched_issn,
        "matched_platforms": list(rank.matched_platforms or []),
    }
    if rank.cas is not None:
        out["cas"] = {
            "tier": rank.cas.tier,  # 区 1-4 (PARTITION, not an IF)
            "rank": rank.cas.rank,
            "top": rank.cas.top,
            "minor": [dict(m) for m in (rank.cas.minor or [])],
            "source_year": rank.cas.source_year,
        }
    if rank.jcr is not None:
        out["jcr"] = {
            "quartile": rank.jcr.quartile,
            # The ONLY field in this whole schema that is a real Impact Factor.
            "impact_factor": rank.jcr.impact_factor,
            "rank": rank.jcr.rank,
            "category": rank.jcr.category,
            "source_year": rank.jcr.source_year,
        }
    if rank.sjr is not None:
        out["sjr"] = {
            "best_quartile": rank.sjr.best_quartile,  # PARTITION/quartile, not an IF
            "sjr": rank.sjr.sjr,
            "per_category": [dict(c) for c in (rank.sjr.per_category or [])],
            "source_year": rank.sjr.source_year,
        }
    return out


#: Back-compat alias. The output was historically called the "journal_metric dict"
#: (spec §3); it is the journal_rank dict. Existing callers/imports keep working.
rank_metric_dict = journal_rank_dict


__all__ = [
    "annotate_papers",
    "filter_by_rank",
    "normalize_keep_tiers",
    "journal_rank_dict",
    "rank_metric_dict",
]
