"""Tests for scripts/discovery_curve.py — the coverage estimate the report shows.

The estimate must (a) always be a number, (b) depend on what the run found,
not only on how many papers were screened, and (c) say how it was obtained.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import discovery_curve as dc  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402


def _p(doi, rcs=None, title=None, year=2024):
    return UnifiedPaperEntity(doi=doi, title=title or f"Paper {doi}", year=year, rcs=rcs)


def _kg(papers):
    return {f"doi|{p.doi}": p for p in papers}


def _write(path: Path, papers, mtime: float):
    path.write_text(
        json.dumps([{"doi": p.doi, "title": p.title, "year": p.year} for p in papers]),
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))


# --------------------------------------------------------------------------- #
# sample_coverage (Chao & Jost 2012, incidence form)
# --------------------------------------------------------------------------- #

def test_sample_coverage_matches_formula():
    # 3 occasions; relevant a,b found twice, c once -> Q1=1, Q2=2, U=5, m=3
    occ = [{"a", "b", "x"}, {"a", "c"}, {"b", "y"}]
    est = dc.sample_coverage(occ, {"a", "b", "c"})
    share = (3 - 1) * 1 / ((3 - 1) * 1 + 2 * 2)
    assert abs(est["coverage"] - (1 - (1 / 5) * share)) < 1e-9
    assert est["lower"] <= est["coverage"] <= est["upper"]
    assert est["occasions"] == 3 and est["detections"] == 5


def test_sample_coverage_depends_on_what_was_found():
    # Same number of occasions and papers; only re-finding differs.
    refound = [{"a", "b", "c"}, {"a", "b", "c"}]
    new_each_time = [{"a", "b", "c"}, {"d", "e", "f"}]
    hi = dc.sample_coverage(refound, {"a", "b", "c"})["coverage"]
    lo = dc.sample_coverage(new_each_time, {"a", "b", "c", "d", "e", "f"})["coverage"]
    assert hi > 0.9 and lo < 0.3


def test_sample_coverage_needs_two_occasions_and_a_detection():
    assert dc.sample_coverage([{"a"}], {"a"}) is None
    assert dc.sample_coverage([{"a"}, {"b"}], set()) is None


# --------------------------------------------------------------------------- #
# retrieval_occasions
# --------------------------------------------------------------------------- #

def test_occasions_skip_files_derived_from_earlier_ones(tmp_path):
    a, b, c, d = _p("10.1/a", 8), _p("10.1/b", 8), _p("10.1/c", 2), _p("10.1/d", 2)
    kg = _kg([a, b, c, d])
    _write(tmp_path / "openalex.json", [a, b, c], 1000)
    _write(tmp_path / "openalex_screened.json", [a, b], 2000)  # subset, written later
    _write(tmp_path / "reviews.json", [a, d], 3000)
    occ = dc.retrieval_occasions(tmp_path, kg)
    assert len(occ) == 2  # the screened subset is not a new search


def test_occasions_read_citation_network_output_and_match_on_any_id(tmp_path):
    a = _p("10.1/a", 8, title="Social media and depression", year=2021)
    kg = _kg([a])
    # citation-network shape; the neighbour carries no DOI, only title + year
    (tmp_path / "citations_01.json").write_text(json.dumps({
        "references": [{"title": "Social Media and Depression", "year": 2021}],
        "cited_by": [{"doi": "10.9/other", "title": "Other", "year": 2022}],
    }), encoding="utf-8")
    _write(tmp_path / "openalex.json", [a], 10)
    occ = dc.retrieval_occasions(tmp_path, kg)
    assert all("doi|10.1/a" in o for o in occ) and len(occ) == 2


def test_unreadable_files_are_skipped(tmp_path):
    (tmp_path / "citations.json").write_text("[1]\n[2]\n", encoding="utf-8")  # appended with >>
    assert dc.retrieval_occasions(tmp_path, {}) == []


# --------------------------------------------------------------------------- #
# make_snapshot + CLI
# --------------------------------------------------------------------------- #

def test_snapshot_uses_sample_coverage_when_there_is_evidence():
    kg = _kg([_p("10.1/a", 8), _p("10.1/b", 7), _p("10.1/c", 3)])
    occ = [{"doi|10.1/a", "doi|10.1/b"}, {"doi|10.1/a", "doi|10.1/c"}]
    snap = dc.make_snapshot(kg, occasions=occ)
    assert snap["method"] == "sample_coverage"
    assert snap["fit_failed"] is False
    assert 0 < snap["coverage_estimate"] < 1


def test_snapshot_falls_back_to_labelled_prior_but_always_gives_a_number():
    kg = _kg([_p(f"10.1/{i}", 8 if i < 5 else 2) for i in range(160)])
    snap = dc.make_snapshot(kg, occasions=[])
    assert snap["method"] == "prior"
    assert snap["coverage_estimate"] is not None
    assert snap["ci_lower"] <= snap["coverage_estimate"] <= snap["ci_upper"]


def _run_cli(*args):
    env = {**os.environ, "PYTHONPATH": str(SKILL_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "scripts.discovery_curve", *args],
        capture_output=True, text=True, env=env, cwd=str(SKILL_ROOT),
    )


def test_cli_finds_raw_dir_next_to_kg_and_accepts_a_curve_json(tmp_path):
    a, b = _p("10.1/a", 8), _p("10.1/b", 8)
    kg = {"doi|10.1/a": {"doi": "10.1/a", "title": a.title, "year": 2024, "rcs": 8},
          "doi|10.1/b": {"doi": "10.1/b", "title": b.title, "year": 2024, "rcs": 8}}
    (tmp_path / "kg_classified.json").write_text(json.dumps(kg), encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    _write(raw / "s1.json", [a, b], 10)
    _write(raw / "s2.json", [a, b, _p("10.1/z")], 20)
    first = _run_cli("--kg", str(tmp_path / "kg_classified.json"), "--output", str(tmp_path / "curve.json"))
    assert first.returncode == 0, first.stderr
    snap = json.loads((tmp_path / "curve.json").read_text())
    assert snap["method"] == "sample_coverage" and snap["occasions"] == 2
    # The STEP 7 -> 9 -> 7 loop: pass the previous curve.json back in.
    again = _run_cli(
        "--kg", str(tmp_path / "kg_classified.json"),
        "--prior-snapshots", str(tmp_path / "curve.json"),
        "--output", str(tmp_path / "curve2.json"),
    )
    assert again.returncode == 0, again.stderr


def test_ambiguous_title_alias_is_not_used_to_match(tmp_path):
    """Two KG papers share title + year; a raw record with only that title
    cannot be assigned to either."""
    a = _p("10.1/a", 8, title="Editorial", year=2024)
    b = _p("10.1/b", 8, title="Editorial", year=2024)
    kg = _kg([a, b])
    (tmp_path / "s1.json").write_text(json.dumps([{"title": "Editorial", "year": 2024}]))
    occ = dc.retrieval_occasions(tmp_path, kg)
    assert occ and not ({"doi|10.1/a", "doi|10.1/b"} & occ[0])


def test_interval_is_reproducible_and_brackets_the_estimate():
    occ = [{"a", "b", "c"}, {"a", "b", "d"}, {"a", "e"}, {"b", "c", "f"}]
    rel = {"a", "b", "c", "d", "e", "f"}
    one, two = dc.sample_coverage(occ, rel), dc.sample_coverage(occ, rel)
    assert one == two
    assert 0 <= one["lower"] <= one["coverage"] <= one["upper"] <= 1
    assert one["upper"] - one["lower"] > 0.05  # few detections -> a real spread
