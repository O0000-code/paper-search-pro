"""Export IDs must match the report's and survive across processes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))


def test_untitled_paper_id_is_the_same_in_every_process():
    code = "from scripts.types import UnifiedPaperEntity as U; print(U(title='无 DOI 的论文').paper_id)"
    env = {**os.environ, "PYTHONPATH": str(SKILL_ROOT)}
    ids = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**env, "PYTHONHASHSEED": seed}, cwd=str(SKILL_ROOT)).stdout.strip()
        for seed in ("1", "2")
    }
    assert len(ids) == 1 and next(iter(ids)).startswith("untitled_")


def test_loaders_keep_the_native_id():
    from scripts import generate_exports, md_report, prisma_s_logger, discovery_curve

    d = {"k": {"title": "中文论文", "source_native_id": "nssd:ABC123", "rcs": 7}}
    for mod in (generate_exports, md_report, prisma_s_logger, discovery_curve):
        assert mod._kg_from_json(d)["k"].paper_id == "nssd:ABC123", mod.__name__


def test_openalex_keeps_every_issn():
    from scripts.openalex_helper import _to_entity

    w = {"id": "https://openalex.org/W1", "title": "T", "publication_year": 2024,
         "primary_location": {"source": {"display_name": "The Lancet", "issn_l": "0099-5355",
                                         "issn": ["0140-6736", "1474-547X"]}}}
    e = _to_entity(w)
    assert e.issn == "0099-5355"
    assert e.issns == ["0099-5355", "0140-6736", "1474-547X"]
