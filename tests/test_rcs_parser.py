"""Tests for rcs_parser — 5-layer deterministic fallback ladder."""

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.rcs_parser import (  # noqa: E402
    parse_rcs_response,
    apply_to_kg,
    VALID_FLAGS,
)
from scripts.types import UnifiedPaperEntity  # noqa: E402


def _sample_papers(n=3):
    return [
        UnifiedPaperEntity(doi=f"10.1/p{i}", title=f"Paper {i}", year=2020 + i)
        for i in range(1, n + 1)
    ]


# Layer 1: clean JSON
def test_layer1_clean_json():
    papers = _sample_papers(2)
    response = json.dumps([
        {"paper_id": "10.1/p1", "rcs": 8, "reasoning": "Highly relevant to the topic of test."},
        {"paper_id": "10.1/p2", "rcs": 3, "reasoning": "Tangentially related at best."},
    ])
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 2
    assert parsed[0].rcs == 8
    assert parsed[1].rcs == 3


# Layer 2: ```json fence
def test_layer2_json_fence():
    papers = _sample_papers(2)
    response = """Here are my classifications:

```json
[
    {"paper_id": "10.1/p1", "rcs": 9, "reasoning": "Foundational paper for this field."},
    {"paper_id": "10.1/p2", "rcs": 5, "reasoning": "Moderately related, methodology touched on."}
]
```

Hope that helps."""
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 2
    assert parsed[0].rcs == 9


# Layer 3: balanced array scan
def test_layer3_balanced_array():
    papers = _sample_papers(1)
    response = """The classifications follow:
[{"paper_id": "10.1/p1", "rcs": 7, "reasoning": "Highly relevant to the topic of test."}]
End of output."""
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 1
    assert parsed[0].rcs == 7


# Layer 4: strict per-paper regex (mixed text)
def test_layer4_strict_regex():
    papers = _sample_papers(2)
    response = """My analysis:
Paper 1: {"paper_id": "10.1/p1", "rcs": 6, "reasoning": "Related to topic in scope of test."}
Paper 2: {"paper_id": "10.1/p2", "rcs": 4, "reasoning": "Marginally related to the question."}"""
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 2
    assert parsed[0].rcs == 6


# Layer 5: tolerant regex (quotes/equals)
def test_layer5_tolerant_regex():
    papers = _sample_papers(1)
    response = """paper_id='10.1/p1' rcs=8 reasoning='Strongly relevant to topic and methodology.'"""
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 1
    assert parsed[0].rcs == 8


# Bottom out (layer 7): everything fails
def test_layer7_bottom_out():
    papers = _sample_papers(2)
    response = "I cannot classify these papers right now, sorry."
    parsed = parse_rcs_response(response, papers)
    assert len(parsed) == 2
    assert all(p.rcs == 5 for p in parsed)
    assert all(p.flag == "parse_failed_uncertain" for p in parsed)


# Validation: rejects invalid rcs
def test_invalid_rcs_value():
    papers = _sample_papers(1)
    bad = json.dumps([{"paper_id": "10.1/p1", "rcs": 99, "reasoning": "Out of range."}])
    parsed = parse_rcs_response(bad, papers)
    # Should fall through to bottom-out since validation fails
    assert parsed[0].rcs == 5
    assert parsed[0].flag == "parse_failed_uncertain"


# Validation: rejects unknown paper_id
def test_unknown_paper_id_rejected():
    papers = _sample_papers(1)
    bad = json.dumps([{"paper_id": "10.1/UNKNOWN", "rcs": 7, "reasoning": "Wrong id mapped here."}])
    parsed = parse_rcs_response(bad, papers)
    assert parsed[0].flag == "parse_failed_uncertain"


# Flags: valid set
def test_valid_flags_accepted():
    papers = _sample_papers(1)
    response = json.dumps([{
        "paper_id": "10.1/p1", "rcs": 4, "flag": "no_abstract_uncertain",
        "reasoning": "Cannot fully assess without abstract.",
    }])
    parsed = parse_rcs_response(response, papers)
    assert parsed[0].flag == "no_abstract_uncertain"


# apply_to_kg: mutates entities
def test_apply_to_kg():
    papers = _sample_papers(2)
    kg = {("doi", p.doi): p for p in papers}
    response = json.dumps([
        {"paper_id": "10.1/p1", "rcs": 8, "reasoning": "Highly relevant in scope of work."},
        {"paper_id": "10.1/p2", "rcs": 3, "reasoning": "Tangentially related at best here."},
    ])
    parsed = parse_rcs_response(response, papers)
    n_updated = apply_to_kg(parsed, kg)
    assert n_updated == 2
    assert papers[0].rcs == 8
    assert papers[1].rcs == 3


# Empty input
def test_empty_papers():
    parsed = parse_rcs_response("", [])
    assert parsed == []


# Valid flags set sanity
def test_valid_flags_set():
    expected_in_set = {"abstract_unavailable", "no_abstract_uncertain", "off_topic_despite_keywords",
                       "parse_failed_uncertain", "recent_unindexed", None}
    assert VALID_FLAGS == expected_in_set


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
