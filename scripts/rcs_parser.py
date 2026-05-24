"""RCS response parser — 5 layers of deterministic fallback + flag-based bottoming.

v2.0 architecture: pure deterministic Python. The LLM call happens in the main
Claude Code agent or in a parallel SubAgent (which writes JSON to a file).
This module only PARSES the LLM's output string into ParsedRCS objects.

Pattern adapted from paper-qa core.py:178-380 (Apache 2.0). See
scripts/vendored/README-vendored.md change #2 for full attribution.

Layers (each returns None to fall through):
  1. Direct json.loads (clean JSON array)
  2. ```json fence extract
  3. First balanced array (scan for [...])
  4. Strict per-paper regex (each paper object)
  5. Tolerant per-paper regex (quotes/equals variants)
  6. Shrink batch (recurse on halves; pure re-parse of existing response)
  7. Bottom out: rcs=5 + flag=parse_failed_uncertain
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional

from .types import Author, ParsedRCS, UnifiedPaperEntity

logger = logging.getLogger(__name__)

VALID_FLAGS = {
    None,
    "abstract_unavailable",
    "no_abstract_uncertain",
    "off_topic_despite_keywords",
    "parse_failed_uncertain",
    "recent_unindexed",
}
MIN_REASONING_LEN = 10
MAX_SHRINK_DEPTH = 4

_FENCE_RE = re.compile(r"```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```", re.DOTALL)
_STRICT_OBJ_RE = re.compile(
    r'\{\s*"paper_id"\s*:\s*"([^"]+)"\s*,\s*"rcs"\s*:\s*(\d+)\s*,\s*'
    r'"reasoning"\s*:\s*"([^"]*)"\s*(?:,\s*"flag"\s*:\s*(null|"[^"]*"))?\s*\}',
    re.DOTALL,
)
_TOLERANT_OBJ_RE = re.compile(
    r'paper_id["\']?\s*[:=]\s*["\']([^"\']+)["\'].*?'
    r'rcs["\']?\s*[:=]\s*(\d+).*?'
    r'reasoning["\']?\s*[:=]\s*["\']([^"\']{10,})["\']'
    r'(?:.*?flag["\']?\s*[:=]\s*(null|["\'][^"\']*["\']))?',
    re.DOTALL | re.IGNORECASE,
)


# ============================================================================
# Public API
# ============================================================================

def parse_rcs_response(
    llm_response: str,
    input_papers: List[UnifiedPaperEntity],
    _shrink_depth: int = 0,
) -> List[ParsedRCS]:
    """Parse LLM RCS output. Always returns len(input_papers) ParsedRCS objects.

    Caller passes the raw LLM string (from main agent or SubAgent JSON file content).
    """
    if not input_papers:
        return []

    for layer_fn in (_layer1, _layer2, _layer3, _layer4, _layer5):
        parsed = layer_fn(llm_response, input_papers)
        if parsed is not None:
            return parsed

    if len(input_papers) > 1 and _shrink_depth < MAX_SHRINK_DEPTH:
        return _layer6_shrink(llm_response, input_papers, _shrink_depth)

    logger.warning(
        "RCS parse exhausted all layers (n=%d, ids=%s)",
        len(input_papers), [p.paper_id for p in input_papers][:5],
    )
    return _layer7_bottom(input_papers)


def apply_to_kg(parsed_list: List[ParsedRCS], kg: dict) -> int:
    """Mutate kg in place: set rcs / rcs_reasoning / rcs_flag on matching entities.

    Returns number of entities updated. kg is the dict from federated_kg_resolver
    (keyed by canonical_key tuple, but entities have .paper_id property for matching).
    """
    by_id = {entity.paper_id: entity for entity in kg.values()}
    updated = 0
    for p in parsed_list:
        entity = by_id.get(p.paper_id)
        if entity is None:
            continue
        entity.rcs = p.rcs
        entity.rcs_reasoning = p.reasoning
        entity.rcs_flag = p.flag
        updated += 1
    return updated


# ============================================================================
# Layers
# ============================================================================

def _validate_objs(objs, input_papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    """Convert dict list to ParsedRCS list, validating ids/quantity/range."""
    valid_ids = {p.paper_id for p in input_papers}
    out: List[ParsedRCS] = []

    for obj in objs:
        if not isinstance(obj, dict):
            return None
        pid = obj.get("paper_id")
        rcs = obj.get("rcs")
        reasoning = obj.get("reasoning") or ""
        flag = obj.get("flag")

        # Validate
        if pid not in valid_ids:
            return None
        if not isinstance(rcs, int) or not (0 <= rcs <= 10):
            return None
        if not isinstance(reasoning, str) or len(reasoning) < MIN_REASONING_LEN:
            return None
        if flag is not None and flag not in VALID_FLAGS:
            return None

        out.append(ParsedRCS(paper_id=pid, rcs=rcs, reasoning=reasoning, flag=flag))

    # Strict 1:1 mapping
    if len(out) != len(input_papers):
        return None
    returned_ids = {p.paper_id for p in out}
    if returned_ids != valid_ids:
        return None
    return out


def _layer1(response: str, papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    try:
        data = json.loads(response.strip())
        if isinstance(data, list):
            return _validate_objs(data, papers)
    except json.JSONDecodeError:
        pass
    return None


def _layer2(response: str, papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    m = _FENCE_RE.search(response)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        if isinstance(data, list):
            return _validate_objs(data, papers)
    except json.JSONDecodeError:
        pass
    return None


def _layer3(response: str, papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    # Scan for first balanced [...]
    start = response.find("[")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(response)):
        ch = response[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    try:
        data = json.loads(response[start:end])
        if isinstance(data, list):
            return _validate_objs(data, papers)
    except json.JSONDecodeError:
        pass
    return None


def _layer4(response: str, papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    matches = _STRICT_OBJ_RE.findall(response)
    if not matches:
        return None
    objs = []
    for pid, rcs_str, reasoning, flag in matches:
        flag_val = None
        if flag and flag != "null":
            flag_val = flag.strip('"')
        objs.append({"paper_id": pid, "rcs": int(rcs_str), "reasoning": reasoning, "flag": flag_val})
    return _validate_objs(objs, papers)


def _layer5(response: str, papers: List[UnifiedPaperEntity]) -> Optional[List[ParsedRCS]]:
    matches = _TOLERANT_OBJ_RE.findall(response)
    if not matches:
        return None
    objs = []
    for pid, rcs_str, reasoning, flag in matches:
        flag_val = None
        if flag and flag.lower() != "null":
            flag_val = flag.strip("'\"")
        objs.append({"paper_id": pid, "rcs": int(rcs_str), "reasoning": reasoning, "flag": flag_val})
    return _validate_objs(objs, papers)


def _layer6_shrink(
    response: str, papers: List[UnifiedPaperEntity], shrink_depth: int
) -> List[ParsedRCS]:
    """Split papers into two halves and recurse. Useful when the LLM partially returned data."""
    mid = len(papers) // 2
    first = parse_rcs_response(response, papers[:mid], _shrink_depth=shrink_depth + 1)
    second = parse_rcs_response(response, papers[mid:], _shrink_depth=shrink_depth + 1)
    return first + second


def _layer7_bottom(papers: List[UnifiedPaperEntity]) -> List[ParsedRCS]:
    """All parsing failed. Mark every paper rcs=5 (uncertain mid) + flag=parse_failed_uncertain.
    Main agent should re-classify these papers manually or accept as uncertain.
    """
    return [
        ParsedRCS(
            paper_id=p.paper_id,
            rcs=5,
            reasoning="Parser exhausted all layers; rcs set to mid-uncertain pending manual review.",
            flag="parse_failed_uncertain",
        )
        for p in papers
    ]


# ============================================================================
# CLI
# ============================================================================

def main():
    p = argparse.ArgumentParser(description="RCS parser — merge classifier SubAgent output into KG")
    p.add_argument("--input-dir", required=True, help="Directory with batch_NNN_result.json files")
    p.add_argument("--kg", required=True, help="kg.json from federated_kg_resolver")
    p.add_argument("--output", required=True, help="Output kg_classified.json path")
    args = p.parse_args()

    # Load KG
    kg_path = Path(args.kg)
    with kg_path.open() as f:
        kg_raw = json.load(f)

    # Reconstruct entities
    from dataclasses import fields as dc_fields
    entity_fields = {f.name for f in dc_fields(UnifiedPaperEntity)}
    kg = {}
    for key_tuple_str, entity_dict in kg_raw.items():
        clean_dict = {k: v for k, v in entity_dict.items() if k in entity_fields}
        # P1-8 fix: rebuild Author objects rather than dropping them. The
        # previous code popped "authors" because passing raw dicts to
        # UnifiedPaperEntity(**clean_dict) leaves entity.authors as List[dict],
        # which downstream tools (data_materialization._authors_short) crash
        # on. Convert each dict to an Author instance so authors survive the
        # RCS classification stage end-to-end.
        raw_authors = clean_dict.get("authors") or []
        rebuilt_authors: List[Author] = []
        for a in raw_authors:
            if isinstance(a, Author):
                rebuilt_authors.append(a)
            elif isinstance(a, dict):
                rebuilt_authors.append(
                    Author(
                        name=str(a.get("name") or ""),
                        orcid=a.get("orcid"),
                        affiliation=a.get("affiliation"),
                        country=a.get("country"),
                        is_first=bool(a.get("is_first")),
                        is_corresponding=bool(a.get("is_corresponding")),
                    )
                )
            else:
                rebuilt_authors.append(Author(name=str(a)))
        clean_dict["authors"] = rebuilt_authors
        try:
            kg[key_tuple_str] = UnifiedPaperEntity(**clean_dict)
        except TypeError as e:
            logger.warning("Skipping entity %s: %s", key_tuple_str, e)

    # Process every classification file
    input_dir = Path(args.input_dir)
    total_updated = 0
    total_processed = 0
    for result_file in sorted(input_dir.glob("batch_*_result.json")):
        with result_file.open() as f:
            result_data = json.load(f)
        # result_data should be: {"papers": [{paper_id, rcs, reasoning, flag}, ...]}
        # OR raw string we need to parse
        if isinstance(result_data, list):
            parsed = [ParsedRCS(**obj) for obj in result_data if all(k in obj for k in ("paper_id", "rcs", "reasoning"))]
        elif isinstance(result_data, dict) and "papers" in result_data:
            parsed = [ParsedRCS(**obj) for obj in result_data["papers"]]
        elif isinstance(result_data, dict) and "raw_response" in result_data:
            # SubAgent stored raw LLM text + the batch_paper_ids
            batch_ids = result_data.get("batch_paper_ids", [])
            batch_papers = [e for e in kg.values() if e.paper_id in batch_ids]
            parsed = parse_rcs_response(result_data["raw_response"], batch_papers)
        else:
            logger.warning("Unknown format in %s", result_file)
            continue

        updated = apply_to_kg(parsed, kg)
        total_updated += updated
        total_processed += len(parsed)
        logger.info("Processed %s: %d papers, %d KG entities updated", result_file.name, len(parsed), updated)

    # Save kg_classified
    out_path = Path(args.output)

    def _entity_to_dict(entity: UnifiedPaperEntity) -> dict:
        d = dict(entity.__dict__)
        # P1-8: serialize Author dataclasses back to plain dicts so the
        # downstream JSON contract matches federated_kg_resolver._paper().
        d["authors"] = [
            {
                "name": a.name,
                "orcid": a.orcid,
                "affiliation": a.affiliation,
                "country": a.country,
                "is_first": a.is_first,
                "is_corresponding": a.is_corresponding,
            }
            for a in (entity.authors or [])
        ]
        return d

    with out_path.open("w") as f:
        json.dump(
            {key: _entity_to_dict(entity) for key, entity in kg.items()},
            f, indent=2, default=str,
        )

    print(f"Done. Processed {total_processed} classifications, updated {total_updated} KG entities.")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
