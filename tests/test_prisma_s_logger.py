"""Regression test for prisma_s_logger — dict-shaped curve.json (PR #2)."""

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def test_prisma_s_logger_accepts_dict_snapshot(tmp_path):
    """`discovery_curve.py` persists a SINGLE snapshot *dict*, so the documented
    `--snapshots curve.json` input to STEP 13 is a dict, not a list.

    Before PR #2, `snapshots[-1]` on a dict raised ``KeyError: -1`` (aborting the
    PRISMA-S log step) and the `isinstance(snapshots, list)` guard silently
    dropped it, leaving `coverage_estimate` at 0. The fix normalizes a dict to a
    one-element list; this test would crash (non-zero exit) if that is reverted.
    """
    kg = {
        "doi|10.1/p1": {
            "doi": "10.1/p1",
            "title": "P1",
            "rcs": 9.0,
            "sources": ["openalex"],
        }
    }
    (tmp_path / "kg.json").write_text(json.dumps(kg), encoding="utf-8")

    # Exactly what discovery_curve.make_snapshot() persists: a single dict.
    snapshot = {
        "timestamp": "2026-07-04T00:00:00",
        "papers_evaluated": 30,
        "coverage_estimate": 0.667,
        "ci_low": 0.5,
        "ci_high": 0.8,
    }
    (tmp_path / "curve.json").write_text(json.dumps(snapshot), encoding="utf-8")

    out = tmp_path / "exec_log.json"
    proc = subprocess.run(
        [
            sys.executable, "-m", "scripts.prisma_s_logger",
            "--kg", str(tmp_path / "kg.json"),
            "--snapshots", str(tmp_path / "curve.json"),
            "--output", str(out),
            "--search-id", "test_run",
            "--tier", "standard",
            "--user-query", "q",
        ],
        cwd=str(SKILL_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"prisma_s_logger crashed on a dict snapshot: {proc.stderr}"

    log = json.loads(out.read_text(encoding="utf-8"))
    snaps = log.get("discovery_curve_snapshots")
    # The single dict must be carried through as a 1-element list, not dropped.
    assert isinstance(snaps, list) and len(snaps) == 1
    assert snaps[0]["coverage_estimate"] == 0.667


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
