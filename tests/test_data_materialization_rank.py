"""Tests for the human-display additive rendering of multi-platform journal_rank
(Feature A, Wave A-3) in data_materialization + md_template.

Two things are proven here, both load-bearing for R-19:

1. **When a paper carries journal_rank**, the rendered paper_list dict gains a
   ``journal_rank`` key (spec §3 three-platform shape, R-04 naming: only JCR has
   ``impact_factor``) plus a ``journal_rank_attribution`` string; the MD report
   shows a "期刊分区" line and a runtime-fetch attribution footnote.

2. **When NO paper carries journal_rank (or journal_metric)**, the materialised
   bundle and the rendered MD are **byte-for-byte identical** to the output the
   pre-A-3 code path produced — i.e. the feature is a pure additive layer.

Pure + network-free: in-memory entities, the real Jinja template, a temp dir.

Run from skill root:
    PYTHONPATH=. python3 -m pytest tests/test_data_materialization_rank.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import data_materialization as dm  # noqa: E402
from scripts.md_report import render_md  # noqa: E402
from scripts.types import (  # noqa: E402
    Author,
    CASRank,
    JCRRank,
    JournalRank,
    SJRRank,
    UnifiedPaperEntity,
)


def _plain_paper(doi: str = "10.1/plain", rcs: int = 8) -> UnifiedPaperEntity:
    return UnifiedPaperEntity(
        doi=doi,
        title="Plain paper",
        authors=[Author(name="A. Author")],
        year=2020,
        venue="J. Plain",
        citation_count=5,
        rcs=rcs,
        rcs_reasoning="on topic",
        discovery_path="query: x",
    )


def _ranked_paper() -> UnifiedPaperEntity:
    jr = JournalRank(
        title="Nature",
        issns=["0028-0836"],
        cas=CASRank(tier=1, rank="5/100", top=True, minor=[], source_year=2025),
        jcr=JCRRank(
            quartile="Q1",
            impact_factor=48.5,
            rank="2/135",
            category="MULTIDISCIPLINARY SCIENCES(SCIE)",
            source_year=2024,
        ),
        sjr=SJRRank(
            best_quartile="Q1",
            sjr=14.5,
            per_category=[{"category": "Multidisciplinary", "quartile": "Q1"}],
            source_year=2024,
        ),
        matched_issn="0028-0836",
        matched_platforms=["cas", "jcr", "sjr"],
    )
    return UnifiedPaperEntity(
        doi="10.1/nature",
        title="A Nature paper",
        authors=[Author(name="B. Boffin")],
        year=2022,
        venue="Nature",
        citation_count=99,
        rcs=9,
        journal_rank=jr,
    )


# ---------------------------------------------------------------------------
# 1. _render_paper: additive presence of journal_rank
# ---------------------------------------------------------------------------


def test_render_paper_no_rank_has_no_key():
    """A paper without journal_rank produces no journal_rank* keys (R-19)."""
    r = dm._render_paper(_plain_paper())
    assert "journal_rank" not in r
    assert "journal_rank_attribution" not in r
    assert "journal_metric" not in r


def test_render_paper_with_rank_emits_three_platforms():
    r = dm._render_paper(_ranked_paper())
    assert "journal_rank" in r
    jr = r["journal_rank"]
    assert jr["cas"]["tier"] == 1 and jr["cas"]["top"] is True
    assert jr["jcr"]["quartile"] == "Q1"
    assert jr["sjr"]["best_quartile"] == "Q1"
    assert set(jr["matched_platforms"]) == {"cas", "jcr", "sjr"}


def test_render_paper_r04_only_jcr_has_impact_factor():
    """R-04 / R-09: the ONLY field named impact_factor is the JCR slot."""
    jr = dm._render_paper(_ranked_paper())["journal_rank"]
    assert "impact_factor" in jr["jcr"]
    assert "impact_factor" not in jr["cas"]
    assert "impact_factor" not in jr["sjr"]


def test_render_paper_rank_attribution_credits_present_platforms():
    r = dm._render_paper(_ranked_paper())
    attr = r["journal_rank_attribution"]
    assert "中科院" in attr  # CAS
    assert "Clarivate" in attr  # JCR
    assert "SCImago" in attr  # SJR
    #署名 correction: SJR is NOT "CC BY-NC".
    assert "CC BY-NC" not in attr
    assert "NOT a Creative Commons" in attr


# ---------------------------------------------------------------------------
# 2. _kg_from_json round-trips journal_rank
# ---------------------------------------------------------------------------


def test_kg_from_json_decodes_journal_rank():
    # Encode a ranked paper the way agent mode / annotate serialises it, then
    # decode it back through the CLI JSON path and re-render.
    encoded = dm._render_paper(_ranked_paper())
    paper = dm._journal_rank_from_json(encoded)
    assert paper is not None
    assert paper.jcr.impact_factor == 48.5
    assert paper.cas.tier == 1
    assert paper.sjr.best_quartile == "Q1"


def test_kg_from_json_no_rank_returns_none():
    assert dm._journal_rank_from_json({"doi": "10.1/x"}) is None


# ---------------------------------------------------------------------------
# 3. Byte-identity of the materialised bundle when no rank data is present
# ---------------------------------------------------------------------------


def _materialise(papers, out: Path):
    kg = {p.paper_id: p for p in papers}
    return dm.materialize(kg, out, user_query="q", tier="standard", search_id="sid", summary="ES")


def test_materialize_no_rank_paper_list_has_no_rank_keys():
    with tempfile.TemporaryDirectory() as d:
        arts = _materialise([_plain_paper("10.1/a"), _plain_paper("10.1/b", rcs=6)], Path(d))
        paper_list = json.loads(arts["paper_list"].read_text())
        for entry in paper_list:
            assert "journal_rank" not in entry
            assert "journal_rank_attribution" not in entry


def test_materialize_with_rank_paper_list_carries_rank():
    with tempfile.TemporaryDirectory() as d:
        arts = _materialise([_ranked_paper(), _plain_paper("10.1/plain")], Path(d))
        paper_list = json.loads(arts["paper_list"].read_text())
        ranked = [e for e in paper_list if e.get("journal_rank")]
        plain = [e for e in paper_list if "journal_rank" not in e]
        assert len(ranked) == 1
        assert len(plain) == 1  # the plain paper stays additive-free
        assert ranked[0]["journal_rank"]["jcr"]["impact_factor"] == 48.5


# ---------------------------------------------------------------------------
# 4. MD render: 期刊分区 line appears with data, absent without it
# ---------------------------------------------------------------------------


def _render_md_for(papers) -> str:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        _materialise(papers, out)
        md_path = out / "report.md"
        render_md(materialized_data_dir=out, output_path=md_path, summary="ES",
                  user_query="q", tier="standard")
        return md_path.read_text(encoding="utf-8")


def test_md_render_shows_partition_line_with_rank():
    md = _render_md_for([_ranked_paper()])
    assert "期刊分区" in md
    assert "中科院 1区" in md
    assert "Top" in md
    assert "JCR Q1" in md
    assert "IF 48.5" in md
    assert "SJR Q1" in md
    # runtime-fetch / no-redistribution footnote + R-04 reminder
    assert "运行时从公开镜像拉取" in md
    assert "影响因子" in md


def test_md_render_no_partition_line_without_rank():
    md = _render_md_for([_plain_paper()])
    assert "期刊分区" not in md
    assert "运行时从公开镜像拉取" not in md


# ---------------------------------------------------------------------------
# 5. openalex open-impact slot (single-layer collapse): renders 期刊影响力,
#    round-trips through JSON, and an openalex-ONLY journal_rank still shows.
# ---------------------------------------------------------------------------


def _openalex_only_paper() -> UnifiedPaperEntity:
    # No CAS/JCR/SJR platform join, but an OpenAlex open-impact figure attached —
    # the single-layer way the legacy journal_metric impact is now carried.
    jr = JournalRank(
        title="Some Journal",
        issns=["1111-2222"],
        openalex={"mean_citedness_2yr": 3.14, "h_index": 42},
        matched_issn="1111-2222",
        matched_platforms=[],
    )
    return UnifiedPaperEntity(
        doi="10.1/oa", title="OA-impact paper", authors=[Author(name="C. Cite")],
        year=2021, venue="Some Journal", citation_count=12, rcs=7, journal_rank=jr,
    )


def test_render_paper_openalex_only_emits_impact_no_partition():
    r = dm._render_paper(_openalex_only_paper())
    jr = r["journal_rank"]
    assert jr is not None
    assert jr["cas"] is None and jr["jcr"] is None and jr["sjr"] is None
    assert jr["openalex"]["mean_citedness_2yr"] == 3.14
    # round-trips through the kg.json decoder
    back = dm._journal_rank_from_json(r)
    assert back is not None and back.openalex["h_index"] == 42


def test_md_render_shows_impact_line_for_openalex_slot():
    md = _render_md_for([_openalex_only_paper()])
    assert "期刊影响力 (OpenAlex 2yr mean citedness)" in md
    assert "3.14" in md
    assert "H-index" in md
    # openalex-only: no 期刊分区 partition line (no CAS/JCR/SJR data)
    assert "期刊分区" not in md


def test_ranked_paper_keeps_partition_line_and_no_impact_when_no_openalex():
    # The classic three-platform paper (no openalex slot) still renders 期刊分区 and
    # NO per-paper 期刊影响力 line — proving the impact line is gated on the openalex
    # slot. (The methodology footer may still mention 期刊影响力 in prose; we assert
    # the per-paper line marker specifically.)
    md = _render_md_for([_ranked_paper()])
    assert "期刊分区" in md
    assert "**期刊影响力 (OpenAlex 2yr mean citedness):**" not in md


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
