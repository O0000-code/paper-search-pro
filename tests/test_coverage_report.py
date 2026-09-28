"""The report shows ONE coverage estimate (hero, Methods, PRISMA-S item 14, report.md),
records how it was obtained, carries the run's filters into the audit log, and
report.md carries the agent's summary even when --summary is omitted."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import data_materialization as dm  # noqa: E402
from scripts.prisma_s_logger import normalize_query_plan  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402


def _kg(n_rel: int, n_other: int):
    kg = {}
    for i in range(n_rel + n_other):
        doi = f"10.1/{i}"
        kg[f"doi|{doi}"] = UnifiedPaperEntity(
            doi=doi, title=f"P{i}", year=2024, rcs=8 if i < n_rel else 2
        )
    return kg


def _raw(run: Path, groups):
    raw = run / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for i, dois in enumerate(groups):
        f = raw / f"s{i}.json"
        f.write_text(json.dumps([{"doi": d, "title": d, "year": 2024} for d in dois]))
        os.utime(f, (1000 + i, 1000 + i))


def _materialize(run: Path, kg, snapshots=None, summary=""):
    (run / "kg_classified.json").write_text("{}")
    dm.materialize(
        kg, run, tier="standard", summary=summary,
        discovery_curve_snapshots=snapshots, kg_source_path=run / "kg_classified.json",
    )
    return json.loads((run / "report_data.json").read_text())


def test_one_estimate_everywhere_and_it_reflects_what_was_found(tmp_path):
    kg = _kg(4, 20)
    rel = [f"10.1/{i}" for i in range(4)]
    other = [f"10.1/{i}" for i in range(4, 24)]
    _raw(tmp_path, [rel + other[:10], rel[:2] + other[10:]])
    data = _materialize(tmp_path, kg)
    curve = data["chart_data"]["discovery_curve"]
    assert curve["method"] == "sample_coverage"
    assert data["metadata"]["coverage_estimate"] == curve["coverage_estimate"]
    assert data["metadata"]["coverage_method"] == "sample_coverage"
    assert data["prisma_log"]["14_total_records"]["coverage_estimate"] == curve["coverage_estimate"]
    # Not the old 1 - exp(-n/80) (24 papers -> 0.26)
    assert abs(curve["coverage_estimate"] - 0.259) > 0.05
    # The drawn curve passes through (papers screened, relevant found).
    import math
    y = curve["estimated_total_relevant"] * (1 - math.exp(-24 / curve["tau"]))
    assert abs(y - 4) < 0.1


def test_old_curve_json_placeholder_is_not_shown(tmp_path):
    kg = _kg(3, 10)
    _raw(tmp_path, [[f"10.1/{i}" for i in range(12)], ["10.1/0", "10.1/1", "10.1/12"]])
    old = {"papers_evaluated": 13, "highly_relevant_count": 3, "coverage_estimate": 0.667,
           "ci_lower": 0.58, "ci_upper": 0.784, "fit_failed": True}
    data = _materialize(tmp_path, kg, snapshots=[old])
    assert data["metadata"]["coverage_estimate"] != 0.667
    assert data["chart_data"]["discovery_curve"]["method"] == "sample_coverage"


def test_no_retrieval_files_still_gives_a_labelled_number(tmp_path):
    data = _materialize(tmp_path, _kg(2, 30))
    assert data["metadata"]["coverage_estimate"] is not None
    assert data["metadata"]["coverage_method"] == "prior"


def test_query_plan_object_filters_reach_the_audit_log(tmp_path):
    plan = {"year_min": 2026, "year_max": 2026,
            "rank_filter": {"platform": "cas", "tiers": [1, 2]},
            "strategies": [{"id": "S1", "query": "children artificial intelligence"}]}
    (tmp_path / "query_plan.json").write_text(json.dumps(plan))
    data = _materialize(tmp_path, _kg(1, 3))
    item9 = data["prisma_log"]["9_limits_and_restrictions"]
    assert item9["filters_applied"] == ["publication_year 2026-2026", "journal rank: CAS 1,2"]
    assert item9["note"] is None  # the report then shows the filters
    assert data["prisma_log"]["8_full_search_strategies"]["queries"] == ["children artificial intelligence"]


def test_query_plan_list_shape_is_unchanged():
    plan = [{"text": "q", "filters": ["year>=2013"], "type": "double-sort"}]
    assert normalize_query_plan(plan) == plan


def _md(run: Path, *extra):
    env = {**os.environ, "PYTHONPATH": str(SKILL_ROOT)}
    out = run / "report.md"
    r = subprocess.run(
        [sys.executable, "-m", "scripts.md_report", "--materialized-dir", str(run),
         "--output", str(out), *extra],
        capture_output=True, text=True, env=env, cwd=str(SKILL_ROOT),
    )
    assert r.returncode == 0, r.stderr
    return out.read_text(encoding="utf-8")


def test_md_report_uses_the_run_summary_without_the_flag(tmp_path):
    _materialize(tmp_path, _kg(2, 5), summary="AGENT-WRITTEN SUMMARY")
    md = _md(tmp_path)
    assert "AGENT-WRITTEN SUMMARY" in md
    assert "This report addresses" not in md  # not the generated stub


def test_md_report_falls_back_to_summary_md(tmp_path):
    _materialize(tmp_path, _kg(2, 5))
    (tmp_path / "summary.md").write_text("FROM SUMMARY FILE", encoding="utf-8")
    assert "FROM SUMMARY FILE" in _md(tmp_path)


def test_md_report_names_the_coverage_method(tmp_path):
    _raw(tmp_path, [["10.1/0", "10.1/1", "10.1/5"], ["10.1/0", "10.1/6"]])
    _materialize(tmp_path, _kg(2, 5), summary="s")
    assert "sample coverage" in _md(tmp_path)
