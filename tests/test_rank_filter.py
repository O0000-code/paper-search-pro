"""Tests for scripts/rank_filter.py — annotate + filter + serialise (Wave A-2).

Pure + network-free: we build JournalRank records and a tiny fake RankLookup in
memory; no CSV, no HTTP. Covers annotate (platform-blind), filter (kept /
filtered / no-platform-data partition), keep-tier normalisation across taxonomies,
and the unified journal_metric dict (R-04 naming).

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_rank_filter
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_rank_filter.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import rank_filter  # noqa: E402
from scripts.journal_rank import normalize_issns  # noqa: E402
from scripts.types import (  # noqa: E402
    Author,
    CASRank,
    JCRRank,
    JournalRank,
    SJRRank,
    UnifiedPaperEntity,
)


# ---------------------------------------------------------------------------
# Fixtures: a fake in-memory RankLookup + paper builder.
# ---------------------------------------------------------------------------


class _FakeLookup:
    """Minimal RankLookup stand-in: an ISSN->JournalRank dict + lookup()."""

    loaded_platforms = ["cas", "jcr", "sjr"]

    def __init__(self, table):
        self._t = table

    def lookup(self, issn):
        for n in normalize_issns(issn):
            if n in self._t:
                rec = self._t[n]
                rec.matched_issn = n
                return rec
        return None


def _lookup():
    return _FakeLookup(
        {
            # JPSP: CAS 区1 Top, JCR Q1 IF 7.6, SJR Q1.
            "0022-3514": JournalRank(
                title="JPSP",
                issns=["0022-3514"],
                cas=CASRank(tier=1, rank="5/100", top=True, source_year=2025),
                jcr=JCRRank(quartile="Q1", impact_factor=7.6, rank="5/100", category="PSYCH(SSCI)", source_year=2024),
                sjr=SJRRank(best_quartile="Q1", sjr=5.1, per_category=[{"category": "Psychology", "quartile": "Q1"}], source_year=2024),
                matched_platforms=["cas", "jcr", "sjr"],
            ),
            # MidJ: CAS 区3 only (not on jcr/sjr).
            "1234-5678": JournalRank(
                title="MidJ",
                issns=["1234-5678"],
                cas=CASRank(tier=3, rank="80/100", top=False, source_year=2025),
                matched_platforms=["cas"],
            ),
        }
    )


def _paper(doi, issn, title="x"):
    return UnifiedPaperEntity(
        doi=doi, title=title, abstract=title, year=2024, citation_count=10,
        issn=issn, authors=[Author(name="A")], sources=["openalex"],
    )


# ---------------------------------------------------------------------------
# normalize_keep_tiers
# ---------------------------------------------------------------------------


def test_normalize_keep_tiers_cas_and_quartile_platforms():
    t, q = rank_filter.normalize_keep_tiers("cas", ["1", "2"])
    assert t == [1, 2] and q == []
    # "Q1" against CAS reads as tier 1.
    t2, q2 = rank_filter.normalize_keep_tiers("cas", ["Q1"])
    assert t2 == [1] and q2 == []
    # ints / "1" against jcr read as Q1.
    t3, q3 = rank_filter.normalize_keep_tiers("jcr", [1, "2", "Q3"])
    assert t3 == [] and q3 == ["Q1", "Q2", "Q3"]
    # garbage dropped.
    t4, q4 = rank_filter.normalize_keep_tiers("sjr", ["Q9", "x", "", None])
    assert t4 == [] and q4 == []
    print("OK  normalize_keep_tiers_cas_and_quartile_platforms")


# ---------------------------------------------------------------------------
# annotate
# ---------------------------------------------------------------------------


def test_annotate_attaches_rank_platform_blind():
    papers = [_paper("10.1/a", "0022-3514"), _paper("10.2/b", "1234-5678"), _paper("10.3/c", "9999-9999")]
    n = rank_filter.annotate_papers(papers, _lookup())
    assert n == 2  # two joined, one ISSN unknown
    assert papers[0].journal_rank.cas.tier == 1
    assert papers[1].journal_rank.cas.tier == 3
    assert papers[2].journal_rank is None
    print("OK  annotate_attaches_rank_platform_blind")


def test_annotate_none_lookup_is_noop():
    papers = [_paper("10.1/a", "0022-3514")]
    assert rank_filter.annotate_papers(papers, None) == 0
    assert papers[0].journal_rank is None
    print("OK  annotate_none_lookup_is_noop")


# ---------------------------------------------------------------------------
# filter_by_rank — kept / filtered / no_platform_data partition
# ---------------------------------------------------------------------------


def test_filter_cas_tier1_partitions_correctly():
    papers = [_paper("10.1/jpsp", "0022-3514"), _paper("10.2/mid", "1234-5678")]
    rank_filter.annotate_papers(papers, _lookup())
    kept, dropped, nodata = rank_filter.filter_by_rank(papers, "cas", tiers=[1])
    assert [p.doi for p in kept] == ["10.1/jpsp"]
    assert [p.doi for p in dropped] == ["10.2/mid"]  # tier 3, has cas data
    assert nodata == []
    print("OK  filter_cas_tier1_partitions_correctly")


def test_filter_no_platform_data_is_counted_not_dropped_silently():
    # MidJ is not on JCR -> it lands in no_platform_data, NOT in filtered_out.
    papers = [_paper("10.1/jpsp", "0022-3514"), _paper("10.2/mid", "1234-5678")]
    rank_filter.annotate_papers(papers, _lookup())
    kept, dropped, nodata = rank_filter.filter_by_rank(papers, "jcr", quartiles=["Q1"])
    assert [p.doi for p in kept] == ["10.1/jpsp"]
    assert dropped == []
    assert [p.doi for p in nodata] == ["10.2/mid"]  # spec §2: counted separately
    print("OK  filter_no_platform_data_is_counted_not_dropped_silently")


def test_filter_top_only_cas():
    papers = [_paper("10.1/jpsp", "0022-3514"), _paper("10.2/mid", "1234-5678")]
    rank_filter.annotate_papers(papers, _lookup())
    kept, dropped, nodata = rank_filter.filter_by_rank(papers, "cas", top=True)
    assert [p.doi for p in kept] == ["10.1/jpsp"]  # only JPSP is Top
    print("OK  filter_top_only_cas")


def test_filter_switch_is_pure_refilter_no_research():
    """Switching platform == filtering the SAME annotated pool again (no search)."""
    papers = [_paper("10.1/jpsp", "0022-3514"), _paper("10.2/mid", "1234-5678")]
    rank_filter.annotate_papers(papers, _lookup())  # annotate ONCE
    cas_kept, _, _ = rank_filter.filter_by_rank(papers, "cas", tiers=[1, 2, 3])
    assert len(cas_kept) == 2  # both on CAS
    sjr_kept, _, sjr_nodata = rank_filter.filter_by_rank(papers, "sjr", quartiles=["Q1"])
    assert [p.doi for p in sjr_kept] == ["10.1/jpsp"]
    assert len(sjr_nodata) == 1  # MidJ has no SJR — re-filter, never re-searched
    print("OK  filter_switch_is_pure_refilter_no_research")


# ---------------------------------------------------------------------------
# filter_by_rank — --rank-category sub-category pin (P1-B: was空转 before)
#
# A journal can sit in different partitions depending on the sub-category: CAS 大类
# 区2 but 小类 区1 in one field; SJR best Q1 but Q3 in a specific category. The
# ``--rank-category`` pin must read the sub-category partition, not the journal's
# best / 大类 value (and must drop journals not present in the pinned category).
# ---------------------------------------------------------------------------


def _cat_lookup():
    """A journal whose 大类/best partition DIFFERS from a pinned sub-category."""
    return _FakeLookup(
        {
            # MatJ: CAS 大类 区2, but 小类 "材料科学:综合" is 区1 and "物理" is 区3.
            #       SJR best Q1, but per-category "Materials" Q1, "Physics" Q3.
            #       JCR best Q2 across "MATERIALS SCIENCE; PHYSICS".
            "2000-0001": JournalRank(
                title="MatJ",
                issns=["2000-0001"],
                cas=CASRank(
                    tier=2, rank="40/300", top=False, source_year=2025,
                    minor=[
                        {"category": "材料科学:综合", "tier": 1, "rank": "5/300"},
                        {"category": "物理:综合", "tier": 3, "rank": "200/300"},
                    ],
                ),
                jcr=JCRRank(
                    quartile="Q2", impact_factor=9.1, rank="20/300",
                    category="MATERIALS SCIENCE; PHYSICS, APPLIED", source_year=2024,
                ),
                sjr=SJRRank(
                    best_quartile="Q1", sjr=2.0, source_year=2024,
                    per_category=[
                        {"category": "Materials Science", "quartile": "Q1"},
                        {"category": "Physics and Astronomy", "quartile": "Q3"},
                    ],
                ),
                matched_platforms=["cas", "jcr", "sjr"],
            ),
        }
    )


def test_cas_category_reads_minor_tier_not_major():
    papers = [_paper("10.1/mat", "2000-0001")]
    rank_filter.annotate_papers(papers, _cat_lookup())
    # 大类 is 区2, so a plain tier=[1] filter drops it...
    kept, dropped, _ = rank_filter.filter_by_rank(papers, "cas", tiers=[1])
    assert kept == [] and len(dropped) == 1
    # ...but pinned to the 材料科学 小类 it is 区1 -> kept.
    kept2, _, _ = rank_filter.filter_by_rank(papers, "cas", tiers=[1], category="材料科学")
    assert [p.doi for p in kept2] == ["10.1/mat"]
    # Pinned to 物理 it is 区3 -> dropped by a tier=[1] filter.
    kept3, dropped3, _ = rank_filter.filter_by_rank(papers, "cas", tiers=[1], category="物理")
    assert kept3 == [] and len(dropped3) == 1
    # A category the journal is NOT in -> dropped (membership fails).
    kept4, dropped4, _ = rank_filter.filter_by_rank(papers, "cas", tiers=[1, 2, 3], category="化学")
    assert kept4 == [] and len(dropped4) == 1
    print("OK  cas_category_reads_minor_tier_not_major")


def test_sjr_category_reads_per_category_quartile():
    papers = [_paper("10.1/mat", "2000-0001")]
    rank_filter.annotate_papers(papers, _cat_lookup())
    # best_quartile is Q1, so a plain Q1 filter keeps it...
    kept, _, _ = rank_filter.filter_by_rank(papers, "sjr", quartiles=["Q1"])
    assert [p.doi for p in kept] == ["10.1/mat"]
    # ...but pinned to Physics (Q3) a Q1 filter drops it.
    kept2, dropped2, _ = rank_filter.filter_by_rank(
        papers, "sjr", quartiles=["Q1"], category="Physics"
    )
    assert kept2 == [] and len(dropped2) == 1
    # Pinned to Materials (Q1) a Q1 filter keeps it.
    kept3, _, _ = rank_filter.filter_by_rank(
        papers, "sjr", quartiles=["Q1"], category="Materials"
    )
    assert [p.doi for p in kept3] == ["10.1/mat"]
    print("OK  sjr_category_reads_per_category_quartile")


def test_jcr_category_is_membership_gate():
    papers = [_paper("10.1/mat", "2000-0001")]
    rank_filter.annotate_papers(papers, _cat_lookup())
    # JCR best quartile is Q2; pinned to a category it IS in -> Q2 filter keeps it.
    kept, _, _ = rank_filter.filter_by_rank(
        papers, "jcr", quartiles=["Q2"], category="MATERIALS SCIENCE"
    )
    assert [p.doi for p in kept] == ["10.1/mat"]
    # Pinned to a category it is NOT in -> dropped (membership gate).
    kept2, dropped2, _ = rank_filter.filter_by_rank(
        papers, "jcr", quartiles=["Q2"], category="CHEMISTRY"
    )
    assert kept2 == [] and len(dropped2) == 1
    print("OK  jcr_category_is_membership_gate")


# ---------------------------------------------------------------------------
# rank_metric_dict — unified three-platform serialisation + R-04 naming
# ---------------------------------------------------------------------------


def test_rank_metric_dict_three_platforms_and_naming():
    lk = _lookup()
    rec = lk.lookup("0022-3514")
    d = rank_filter.rank_metric_dict(rec)
    assert d["cas"]["tier"] == 1 and d["cas"]["top"] is True
    # R-04: only JCR exposes a real impact_factor; CAS exposes a tier (partition).
    assert d["jcr"]["impact_factor"] == 7.6
    assert "impact_factor" not in d["cas"]
    assert d["sjr"]["best_quartile"] == "Q1"
    assert "impact_factor" not in d["sjr"]
    assert set(d["matched_platforms"]) == {"cas", "jcr", "sjr"}
    assert d["matched_issn"] == "0022-3514"
    print("OK  rank_metric_dict_three_platforms_and_naming")


def test_rank_metric_dict_none_and_empty():
    assert rank_filter.rank_metric_dict(None) is None
    empty = JournalRank(title="x", issns=["0000-0000"])
    assert rank_filter.rank_metric_dict(empty) is None  # no platform slot -> None
    print("OK  rank_metric_dict_none_and_empty")


def test_rank_metric_dict_emits_openalex_and_alias():
    # journal_rank_dict is the canonical name; rank_metric_dict is a back-compat alias.
    assert rank_filter.rank_metric_dict is rank_filter.journal_rank_dict
    # The openalex open-impact slot is serialised (R-04: never named impact_factor).
    rec = JournalRank(
        title="JPSP", issns=["0022-3514"],
        sjr=SJRRank(best_quartile="Q1", sjr=5.1, source_year=2024),
        openalex={"mean_citedness_2yr": 2.72, "h_index": 757},
        matched_platforms=["sjr"],
    )
    d = rank_filter.journal_rank_dict(rec)
    assert d["openalex"] == {"mean_citedness_2yr": 2.72, "h_index": 757}
    assert d["sjr"]["best_quartile"] == "Q1"
    assert "impact_factor" not in d["openalex"]
    # An openalex-ONLY record (no platform) still serialises (single-layer impact).
    oa_only = JournalRank(title="X", issns=["1111-1111"], openalex={"mean_citedness_2yr": 1.0, "h_index": 3})
    d2 = rank_filter.journal_rank_dict(oa_only)
    assert d2 is not None and d2["cas"] is None and d2["jcr"] is None and d2["sjr"] is None
    assert d2["openalex"]["mean_citedness_2yr"] == 1.0
    print("OK  rank_metric_dict_emits_openalex_and_alias")


def main() -> int:
    tests = [
        test_normalize_keep_tiers_cas_and_quartile_platforms,
        test_annotate_attaches_rank_platform_blind,
        test_annotate_none_lookup_is_noop,
        test_filter_cas_tier1_partitions_correctly,
        test_filter_no_platform_data_is_counted_not_dropped_silently,
        test_filter_top_only_cas,
        test_filter_switch_is_pure_refilter_no_research,
        test_cas_category_reads_minor_tier_not_major,
        test_sjr_category_reads_per_category_quartile,
        test_jcr_category_is_membership_gate,
        test_rank_metric_dict_three_platforms_and_naming,
        test_rank_metric_dict_none_and_empty,
        test_rank_metric_dict_emits_openalex_and_alias,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            import traceback

            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed.append(t.__name__)
    print()
    print(f"Ran {len(tests)} tests — {len(tests) - len(failed)} pass / {len(failed)} fail")
    if failed:
        print("Failures:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
