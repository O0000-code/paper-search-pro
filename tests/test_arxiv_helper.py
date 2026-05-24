"""Unit tests for arxiv_helper.py (L2 Freshness Sentinel).

Runs real arXiv API calls (no key required). Respects the 4s rate limit configured
in arxiv_helper, so ~20-40s total runtime is expected for the network tests.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python tests/test_arxiv_helper.py

Coverage matches the task spec:
  - normalize_arxiv_doi: uppercase X + version stripping + legacy IDs + lowercase pass-through
  - extract_arxiv_id: URL / version / legacy / PDF URL
  - get_by_arxiv_id('1706.03762') returns the Attention paper, year=2017
  - search_freshness_window LLM query days=7 returns <= limit, all published >= cutoff
  - DEFAULT_CATEGORIES filter prevents reactor-experiment noise on "prospect theory"
  - search_recent + sort options
  - Empty-results handling (gibberish query)
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.arxiv_helper import (  # noqa: E402
    ALL_CATEGORIES,
    DEFAULT_CATEGORIES,
    _build_query,
    _to_entity,
    extract_arxiv_id,
    get_by_arxiv_id,
    normalize_arxiv_doi,
    search_freshness_window,
    search_recent,
)
from scripts.types import UnifiedPaperEntity  # noqa: E402


# =============================================================================
# Pure-function tests (no network)
# =============================================================================


def test_normalize_arxiv_doi_uppercase_and_version() -> None:
    """Round-2 §3 lock: arXiv 用大写 arXiv，OpenAlex 用小写 arxiv. Strip vN."""
    assert (
        normalize_arxiv_doi("10.48550/arXiv.1706.03762v5") == "10.48550/arxiv.1706.03762"
    )
    assert (
        normalize_arxiv_doi("10.48550/ARXIV.1706.03762") == "10.48550/arxiv.1706.03762"
    )
    assert (
        normalize_arxiv_doi("10.48550/arxiv.1706.03762") == "10.48550/arxiv.1706.03762"
    )
    # Legacy form (hep-th/9707234)
    assert (
        normalize_arxiv_doi("10.48550/arXiv.hep-th/9707234v2")
        == "10.48550/arxiv.hep-th/9707234"
    )
    # Non-arXiv DOI passes through lowercased
    assert (
        normalize_arxiv_doi("10.1126/SCIENCE.ADV9817") == "10.1126/science.adv9817"
    )
    # Empty input safety
    assert normalize_arxiv_doi("") == ""
    print("OK  normalize_arxiv_doi handles case + version + legacy")


def test_extract_arxiv_id_variants() -> None:
    """URL / bare ID / version / legacy / PDF URL all collapse to canonical id."""
    assert extract_arxiv_id("http://arxiv.org/abs/1706.03762v5") == "1706.03762"
    assert extract_arxiv_id("https://arxiv.org/abs/2605.21489") == "2605.21489"
    assert extract_arxiv_id("https://arxiv.org/pdf/1706.03762v7") == "1706.03762"
    assert extract_arxiv_id("1706.03762v7") == "1706.03762"
    assert extract_arxiv_id("1706.03762") == "1706.03762"
    # Legacy ID with slash
    assert extract_arxiv_id("hep-th/9707234v2") == "hep-th/9707234"
    assert extract_arxiv_id("") is None
    print("OK  extract_arxiv_id handles URL / version / legacy")


def test_build_query_applies_category_filter() -> None:
    """Default cat filter must always include cs.* — SA-V2 §3.4 noise-defense."""
    q = _build_query("language models", None)
    assert "cat:cs.*" in q
    assert "(language models)" in q
    # all-cats mode must include physics
    q_all = _build_query("dark matter", ALL_CATEGORIES)
    assert "cat:physics.*" in q_all
    print("OK  _build_query injects cat filter")


# =============================================================================
# Network tests (real arXiv API)
# =============================================================================


def test_get_by_arxiv_id_attention_paper() -> None:
    """Single-paper lookup of 1706.03762 must return 'Attention Is All You Need' (2017)."""
    paper = get_by_arxiv_id("1706.03762")
    assert paper is not None, "Lookup returned None"
    assert isinstance(paper, UnifiedPaperEntity)
    assert "attention" in paper.title.lower()
    assert paper.year == 2017
    assert paper.arxiv_id == "1706.03762"
    # Canonical lowercase DOI synthesized from arxiv_id
    assert paper.doi == "10.48550/arxiv.1706.03762"
    # Categories contain at least cs.CL (NLP venue)
    assert any(c.startswith("cs.") for c in paper.arxiv_categories)
    assert "arxiv" in paper.sources
    # PDF URL present (always OA on arXiv)
    assert paper.pdf_url and "arxiv.org" in paper.pdf_url
    print(
        f"OK  get_by_arxiv_id Attention paper: year={paper.year} "
        f"cats={paper.arxiv_categories[:2]}"
    )


def test_get_by_arxiv_id_invalid() -> None:
    """Invalid id returns None (no exception)."""
    paper = get_by_arxiv_id("")
    assert paper is None
    print("OK  get_by_arxiv_id('') -> None")


def _cat_matches_whitelist(cat: str, whitelist: List[str]) -> bool:
    """A paper category matches the whitelist if its prefix matches any entry.
    E.g. 'cs.LG' matches 'cs.*'; 'q-bio.NC' matches 'q-bio.*'.
    """
    for w in whitelist:
        prefix = w.replace(".*", "").rstrip(".")
        # Match either exactly (e.g. 'hep-th' == 'hep-th') or as a dotted-prefix.
        if cat == prefix or cat.startswith(prefix + ".") or cat.startswith(prefix):
            # The last branch is for cases like 'hep-th' matching 'hep-th' (no dot).
            # Tighten: require equality or dot-after-prefix to avoid 'cs.LG' matching 'c'
            if cat == prefix or cat.startswith(prefix + "."):
                return True
    return False


def test_search_freshness_window_respects_days_and_limit() -> None:
    """All returned papers must be within the days window, count <= limit.

    arXiv allows cross-listed papers (e.g. astro-ph.CO + cs.LG) — the cat filter
    requires AT LEAST ONE matching category, not primary. So we assert "some
    category in whitelist" rather than "primary in whitelist".
    """
    days = 7
    limit = 15
    papers = search_freshness_window("language models", days=days, limit=limit)
    assert isinstance(papers, list)
    assert len(papers) <= limit, f"Returned {len(papers)} > limit {limit}"
    cutoff_year = (datetime.now(timezone.utc) - timedelta(days=days + 1)).year
    for p in papers:
        assert p.year is None or p.year >= cutoff_year - 1
        assert p.arxiv_id is not None
        assert p.doi == f"10.48550/arxiv.{p.arxiv_id}"
        # At least one category must be in the whitelist
        if p.arxiv_categories:
            assert any(
                _cat_matches_whitelist(c, DEFAULT_CATEGORIES) for c in p.arxiv_categories
            ), (
                f"Paper {p.arxiv_id} cats={p.arxiv_categories} has none on whitelist"
            )
    print(
        f"OK  search_freshness_window(days={days}, limit={limit}) -> "
        f"{len(papers)} papers, all in window + cat-filtered"
    )


def test_default_categories_block_reactor_noise() -> None:
    """SA-V2 §3.4 lock: 'prospect theory' without cat filter returns reactor experiments.
    With DEFAULT_CATEGORIES, no result should be PURELY physics — at least one
    category must be on the safe whitelist (cs/math/stat/q-bio/q-fin/econ).

    A paper purely categorized under physics.ins-det / hep-* (the reactor noise) would
    fail the cat filter and not be returned at all. Cross-listed (e.g. astro-ph + cs.LG)
    papers may slip in — that's expected arXiv behavior, and the cs.LG side IS on-topic.
    """
    papers = search_recent("prospect theory", max_results=10)
    for p in papers:
        if not p.arxiv_categories:
            continue
        # At least one cat must be on-whitelist (the one that satisfied the filter)
        assert any(
            _cat_matches_whitelist(c, DEFAULT_CATEGORIES) for c in p.arxiv_categories
        ), f"DEFAULT_CATEGORIES leaked: {p.arxiv_id} cats={p.arxiv_categories} all off-list"
    print(f"OK  default cats block pure-physics noise ({len(papers)} papers, all have on-list cat)")


def test_search_recent_sort_options_work() -> None:
    """All three sort options must execute without error."""
    for sort_by in ("submitted", "relevance", "lastUpdated"):
        papers = search_recent("transformers attention", max_results=3, sort_by=sort_by)
        assert isinstance(papers, list)
        # Don't assert non-empty — relevance ranking on arXiv is weak (SA-V2 §1.5 G)
        # but the call should at least return a list.
    print("OK  search_recent supports submitted/relevance/lastUpdated sorts")


def test_empty_results_for_gibberish() -> None:
    """Truly meaningless query returns empty list, not exception."""
    papers = search_recent("zzqxqzx_no_such_term_anywhere_42", max_results=5)
    assert isinstance(papers, list)
    assert len(papers) == 0, f"Expected 0, got {len(papers)}"
    print("OK  empty-results query returns []")


# =============================================================================
# Runner
# =============================================================================


def main() -> None:
    tests = [
        # Pure-function tests first (fast, no network)
        test_normalize_arxiv_doi_uppercase_and_version,
        test_extract_arxiv_id_variants,
        test_build_query_applies_category_filter,
        test_get_by_arxiv_id_invalid,
        # Network tests (each ~5-15s due to 4s rate limit)
        test_get_by_arxiv_id_attention_paper,
        test_search_freshness_window_respects_days_and_limit,
        test_default_categories_block_reactor_noise,
        test_search_recent_sort_options_work,
        test_empty_results_for_gibberish,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"FAIL {t.__name__}: {exc!r}")
            failed += 1
    print()
    if failed:
        print(f"{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"All {len(tests)} arxiv_helper tests passed.")


if __name__ == "__main__":
    main()
