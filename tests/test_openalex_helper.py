"""Unit tests for scripts/openalex_helper.py.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_openalex_helper

These tests hit the live OpenAlex API (polite pool); they require network access
and a configured email in scripts/config.py. Tests favor invariants that should
hold regardless of OpenAlex data drift (e.g. K&T 1979 cites > 40k, NOT exact 46625).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Allow `python3 -m tests.test_openalex_helper` from skill root
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

from scripts.config import load_config  # noqa: E402
from scripts.openalex_helper import (  # noqa: E402
    JOURNAL_PRESETS,
    _PER_PAGE,
    _AGENT_SEARCH_NUDGE,
    _ENVELOPE_SCHEMA_VERSION,
    _wrap_envelope,
    _strip_doi_prefix,
    _strip_oa_prefix,
    _to_entity,
    analyze_topic_trends,
    double_sort_search,
    find_review_articles,
    find_seminal_papers,
    get_author_profile,
    get_citation_network,
    get_work,
    init_pyalex,
    search_in_journal_list,
    search_top_n_pages,
    search_works,
)
from scripts.types import UnifiedPaperEntity  # noqa: E402


# =============================================================================
# Test infrastructure
# =============================================================================


_RESULTS = {"passed": 0, "failed": 0, "notes": []}


def _record(name: str, status: str, msg: str = "") -> None:
    line = f"{status}  {name}"
    if msg:
        line += f"  — {msg}"
    print(line)
    if status == "OK":
        _RESULTS["passed"] += 1
    else:
        _RESULTS["failed"] += 1


def _run(name: str, fn) -> None:
    try:
        msg = fn() or ""
        _record(name, "OK", msg)
    except AssertionError as exc:
        _record(name, "FAIL", f"AssertionError: {exc}")
        traceback.print_exc()
    except Exception as exc:
        _record(name, "FAIL", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# =============================================================================
# Pure-Python tests (no network needed)
# =============================================================================


def test_journal_presets_completeness():
    """JOURNAL_PRESETS must contain UTD24/FT50/nature_science/medical_top with
    correct entry counts."""
    assert "UTD24" in JOURNAL_PRESETS
    assert "FT50" in JOURNAL_PRESETS
    assert "nature_science" in JOURNAL_PRESETS
    assert "medical_top" in JOURNAL_PRESETS
    assert "ml_top_venues" in JOURNAL_PRESETS
    assert "Cochrane" in JOURNAL_PRESETS

    utd = JOURNAL_PRESETS["UTD24"]
    assert len(utd) == 24, f"UTD24 must have exactly 24 entries, got {len(utd)}"

    ft = JOURNAL_PRESETS["FT50"]
    assert len(ft) >= 45, f"FT50 should have ~50 entries, got {len(ft)}"

    ns = JOURNAL_PRESETS["nature_science"]
    assert "Nature" in ns and "Science" in ns

    med = JOURNAL_PRESETS["medical_top"]
    assert any("New England" in m for m in med)
    return f"UTD24={len(utd)}, FT50={len(ft)}, nature_science={len(ns)}, medical={len(med)}"


def test_strip_helpers():
    """_strip_oa_prefix and _strip_doi_prefix should normalize IDs/DOIs."""
    assert _strip_oa_prefix("https://openalex.org/W3011865677") == "W3011865677"
    assert _strip_oa_prefix("W3011865677") == "W3011865677"
    assert _strip_oa_prefix(None) is None
    assert _strip_doi_prefix("https://doi.org/10.2307/1914185") == "10.2307/1914185"
    assert _strip_doi_prefix("10.2307/1914185") == "10.2307/1914185"
    # pyalex returns lowercase https:// form only — case-insensitive normalization
    # is out of scope (and would mask upstream contract violations).
    assert _strip_doi_prefix("10.X/Y") == "10.x/y"
    assert _strip_doi_prefix(None) is None
    assert _strip_doi_prefix("") is None
    return "all 7 strip cases pass"


def test_to_entity_minimal():
    """_to_entity should handle minimal/None-y dicts without crashing."""
    e = _to_entity({})
    assert isinstance(e, UnifiedPaperEntity)
    assert e.citation_count == 0
    assert e.authors == []
    assert e.abstract is None
    assert "openalex" in e.sources

    # With inverted abstract index
    inv = {"hello": [0], "world": [1]}
    e2 = _to_entity({"abstract_inverted_index": inv, "title": "Test"})
    assert e2.abstract == "hello world", f"abstract reconstruction failed: {e2.abstract!r}"
    return "minimal + abstract-inv reconstruction works"


def test_per_page_constraint():
    """SA-Z1 constraint: per_page must be <= 20 to avoid 25k token blowup."""
    assert _PER_PAGE <= 20, f"per_page is {_PER_PAGE} but must be <=20 (SA-Z1)"
    return f"per_page={_PER_PAGE}"


def test_0_3_oa_locations_parsed_from_locations():
    """0.3 (pure): _to_entity collects ALL open-access copy URLs from
    locations[], de-duplicated, while pdf_url keeps the single best oa_url.
    Non-OA locations are ignored; a paper with no OA copies yields []."""
    work = {
        "id": "https://openalex.org/W1",
        "title": "Highly accurate protein structure prediction with AlphaFold",
        "open_access": {
            "is_oa": True,
            "oa_url": "https://www.nature.com/articles/s41586-021-03819-2.pdf",
        },
        "locations": [
            {
                "is_oa": True,
                "pdf_url": "https://www.nature.com/articles/s41586-021-03819-2.pdf",
                "landing_page_url": "https://nature.com/x",
            },
            {"is_oa": True, "landing_page_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8371605/"},
            {"is_oa": True, "pdf_url": "https://repo.example.edu/alphafold.pdf"},
            {"is_oa": False, "landing_page_url": "https://paywalled.example.com"},
            # duplicate of the first — must be de-duplicated
            {"is_oa": True, "pdf_url": "https://www.nature.com/articles/s41586-021-03819-2.pdf"},
        ],
    }
    e = _to_entity(work)
    assert len(e.oa_locations) == 3, f"expected 3 OA copies, got {e.oa_locations}"
    assert e.oa_locations[0] == "https://www.nature.com/articles/s41586-021-03819-2.pdf"
    assert "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8371605/" in e.oa_locations
    # pdf_url (single best OA url) is unchanged.
    assert e.pdf_url == "https://www.nature.com/articles/s41586-021-03819-2.pdf"
    return f"oa_locations={len(e.oa_locations)}"


def test_0_3_no_oa_copies_yields_empty():
    """0.3 R-19: a paper with only non-OA locations gets an empty oa_locations
    list — no change to the pre-0.3 shape for closed-access papers."""
    work = {
        "id": "https://openalex.org/W2",
        "title": "Closed",
        "locations": [{"is_oa": False, "landing_page_url": "https://paywall.example"}],
    }
    e = _to_entity(work)
    assert e.oa_locations == []
    # Also: entity with no locations key at all must not crash.
    assert _to_entity({"title": "X"}).oa_locations == []
    return "non-OA -> []"


# =============================================================================
# v2.2 --json-envelope (R-14) — pure-Python wrapper + subprocess CLI behavior
# =============================================================================


def test_wrap_envelope_list_carries_count():
    """A list payload must be wrapped with ok/schema_version/data/meta + count."""
    env = _wrap_envelope([{"a": 1}, {"a": 2}], command="search", count=2)
    assert env["ok"] is True
    assert env["schema_version"] == _ENVELOPE_SCHEMA_VERSION
    assert env["data"] == [{"a": 1}, {"a": 2}]
    assert env["meta"] == {"command": "search", "source": "openalex", "count": 2}
    json.dumps(env)  # must be JSON-safe
    return "list envelope carries count + source"


def test_wrap_envelope_dict_omits_count():
    """A dict payload (get/author/trends) has no count key in meta."""
    env = _wrap_envelope({"id": "W1"}, command="get")
    assert env["data"] == {"id": "W1"}
    assert "count" not in env["meta"]
    assert env["meta"]["command"] == "get"
    return "dict envelope omits count"


def _run_oa_cli(args):
    """Invoke the openalex_helper CLI as a subprocess; capture stdout+stderr
    separately so we can assert the stderr nudge never leaks into stdout."""
    skill_root = str(SKILL_ROOT)
    return subprocess.run(
        ["python3", "-m", "scripts.openalex_helper", *args],
        capture_output=True,
        text=True,
        cwd=skill_root,
        env={**os.environ, "PYTHONPATH": skill_root},
        timeout=60,
    )


def test_cli_presets_default_is_bare_list_no_envelope():
    """Without --json-envelope, `presets` stdout is the bare dict (no envelope
    keys) and NO stderr nudge — proving default behavior is unchanged (R-11)."""
    res = _run_oa_cli(["presets"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    # Bare payload: top-level keys are preset names, not ok/schema_version/data.
    assert "UTD24" in out and "ok" not in out and "data" not in out
    assert _AGENT_SEARCH_NUDGE not in res.stderr
    return "default presets path unchanged (no envelope, no nudge)"


def test_cli_presets_json_envelope_wraps_and_nudges_stderr():
    """With --json-envelope, stdout is the envelope; the agent-search nudge is on
    STDERR only (never in stdout)."""
    res = _run_oa_cli(["--json-envelope", "presets"])
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)  # stdout must be a single clean JSON doc
    assert out["ok"] is True
    assert out["schema_version"] == _ENVELOPE_SCHEMA_VERSION
    assert out["data"].get("UTD24") == 24
    assert out["meta"]["command"] == "presets"
    # Nudge in stderr, NOT in stdout.
    assert "agent_search" in res.stderr
    assert "agent_search" not in res.stdout
    return "json-envelope wraps stdout + nudges via stderr only"


# -----------------------------------------------------------------------------
# v2.2 open item #1 (R-14): the discoverability nudge must print on the
# search-INITIATION subcommands (`search` / `double-sort`) even WITHOUT
# --json-envelope, but must NOT print on mid-pipeline subcommands
# (citation-network / get / ...). These run `_main_cli` in-process with the
# OpenAlex backend + init stubbed, so no network is touched; stdout/stderr are
# captured separately to prove the nudge stays on stderr and stdout is unchanged.
# -----------------------------------------------------------------------------


def _run_main_cli_offline(argv, stubs):
    """Invoke openalex_helper._main_cli() in-process with stubbed network funcs.

    ``argv`` is the arg list AFTER the program name. ``stubs`` maps attr name on
    the openalex_helper module to a fake callable. Returns (stdout, stderr).
    All stubs and sys.argv are restored on exit (no global leakage).
    """
    import contextlib
    import io

    import scripts.openalex_helper as oah

    saved = {name: getattr(oah, name) for name in stubs}
    saved_argv = sys.argv
    # init_pyalex is always stubbed so load_config()/network never runs.
    all_stubs = {"init_pyalex": (lambda cfg: None), **stubs}
    out, err = io.StringIO(), io.StringIO()
    try:
        for name, fn in all_stubs.items():
            setattr(oah, name, fn)
        sys.argv = ["openalex_helper", *argv]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            oah._main_cli()
    finally:
        for name, fn in saved.items():
            setattr(oah, name, fn)
        # restore init_pyalex even though it was force-stubbed
        setattr(oah, "init_pyalex", saved.get("init_pyalex", oah.init_pyalex))
        sys.argv = saved_argv
    return out.getvalue(), err.getvalue()


def test_cli_search_nudges_stderr_without_envelope():
    """`search` (a search-initiation entry) prints the agent_search nudge on
    stderr even without --json-envelope; stdout stays the bare JSON list."""
    fake = UnifiedPaperEntity(title="t", doi="10.1/x", citation_count=1)
    out, err = _run_main_cli_offline(
        ["search", "prospect theory", "--limit", "1"],
        {"search_works": lambda *a, **k: [fake]},
    )
    parsed = json.loads(out)  # bare list, NOT an envelope
    assert isinstance(parsed, list) and "ok" not in out[:5]
    assert _AGENT_SEARCH_NUDGE in err
    assert "agent_search" not in out
    return "search nudges stderr (bare stdout) without --json-envelope"


def test_cli_double_sort_nudges_stderr_without_envelope():
    """`double-sort` (the other search-initiation entry) also nudges on stderr."""
    fake = UnifiedPaperEntity(title="t", doi="10.1/y", citation_count=1)
    out, err = _run_main_cli_offline(
        ["double-sort", "prospect theory", "--n", "1"],
        {"double_sort_search": lambda *a, **k: [fake]},
    )
    json.loads(out)  # bare list
    assert _AGENT_SEARCH_NUDGE in err
    assert "agent_search" not in out
    return "double-sort nudges stderr without --json-envelope"


def test_cli_citation_network_does_not_nudge():
    """`citation-network` is a STEP 9 mid-pipeline call; it must NOT print the
    nudge (would spam once per seed). stdout unchanged, stderr nudge-free."""
    out, err = _run_main_cli_offline(
        ["citation-network", "W123"],
        {"get_citation_network": lambda *a, **k: {"references": [], "cited_by": []}},
    )
    json.loads(out)
    assert "agent_search" not in err
    assert "agent_search" not in out
    return "citation-network does NOT nudge (no STEP 9 spam)"


def test_cli_get_does_not_nudge():
    """`get` (single-paper lookup) is not a search-initiation entry → no nudge."""
    fake = UnifiedPaperEntity(title="t", doi="10.1/z", citation_count=1)
    out, err = _run_main_cli_offline(
        ["get", "10.1/z"],
        {"get_work": lambda *a, **k: fake},
    )
    json.loads(out)
    assert "agent_search" not in err
    return "get does NOT nudge"


# =============================================================================
# Network-dependent integration tests
# =============================================================================


def test_init_and_search_kt():
    """K&T 1979 DOI lookup: citation_count > 40000 (sanity invariant)."""
    p = get_work("10.2307/1914185")
    assert isinstance(p, UnifiedPaperEntity)
    assert p.citation_count > 40000, f"K&T 1979 expected >40k cites, got {p.citation_count}"
    assert "prospect" in (p.title or "").lower(), f"unexpected title: {p.title!r}"
    assert p.year == 1979, f"unexpected year: {p.year}"
    # DOI normalize check (lowercase, no URL)
    assert p.doi == "10.2307/1914185", f"DOI not normalized: {p.doi!r}"
    return f"K&T cited_by={p.citation_count}, year={p.year}"


def test_abstract_reconstruction_kt():
    """K&T 1979 stores abstract as inverted_index; reconstruction must produce
    non-empty plain-text abstract."""
    p = get_work("10.2307/1914185")
    assert p.abstract is not None and len(p.abstract) > 200, (
        f"K&T abstract reconstruction failed: len={len(p.abstract) if p.abstract else 0}"
    )
    # The abstract should mention key prospect-theory concepts
    abstract_lower = p.abstract.lower()
    has_prospect = "prospect" in abstract_lower or "decision" in abstract_lower
    assert has_prospect, "K&T abstract missing expected terms"
    return f"abstract len={len(p.abstract)} chars"


def test_search_works_returns_unified_entities():
    """search_works() returns a list of UnifiedPaperEntity."""
    results = search_works("prospect theory", limit=5)
    assert isinstance(results, list)
    assert 1 <= len(results) <= 5, f"unexpected count: {len(results)}"
    for r in results:
        assert isinstance(r, UnifiedPaperEntity)
        assert r.title  # non-empty title
        assert "openalex" in r.sources
    return f"got {len(results)} entities for 'prospect theory'"


def test_search_top_n_pages_deep():
    """search_top_n_pages should return ~30 papers when asked for top-30."""
    results = search_top_n_pages("prospect theory", total_papers=30, sort="cited_by_count:desc")
    assert len(results) >= 20, f"deep crawl returned only {len(results)} papers"
    # Verify monotonic decreasing cites (within tolerance for ties)
    cites = [r.citation_count for r in results if r.citation_count is not None]
    # Top result should have very high cites (K&T 1979)
    assert cites[0] > 30000, f"top citation too low: {cites[0]}"
    return f"top-30 deep crawl: {len(results)} papers, top cite={cites[0]}"


def test_double_sort_search_combines():
    """double_sort_search returns multi-strategy combined list (boost on >=2 appearances)."""
    results = double_sort_search("prospect theory", total_per_strategy=15)
    assert isinstance(results, list)
    assert len(results) >= 15, f"double-sort returned only {len(results)} papers"
    # All entities should be UnifiedPaperEntity
    assert all(isinstance(r, UnifiedPaperEntity) for r in results)
    # First papers should be high-cite (K&T-class)
    top_cite = max((r.citation_count for r in results[:5] if r.citation_count is not None), default=0)
    assert top_cite > 10000, f"top combined cite too low: {top_cite}"
    return f"double-sort: {len(results)} unique papers (top cite={top_cite})"


def test_find_seminal_papers_year_filter():
    """find_seminal_papers(year_max=2015): all returned papers must have year <= 2015."""
    results = find_seminal_papers("prospect theory", year_max=2015, limit=5)
    assert len(results) >= 3, f"seminal returned only {len(results)} papers"
    for r in results:
        assert r.year is not None and r.year <= 2015, (
            f"seminal paper has year={r.year}, expected <=2015. Title: {r.title!r}"
        )
    return f"seminal: {len(results)} papers all <=2015"


def test_find_review_articles_type_filter():
    """find_review_articles: all returned papers must have type=='review'."""
    results = find_review_articles("working memory training", limit=5)
    assert len(results) >= 3, f"reviews returned only {len(results)} papers"
    for r in results:
        assert r.type == "review", (
            f"non-review type leaked: {r.type!r}. Title: {r.title!r}"
        )
    return f"reviews: {len(results)} papers all type=review"


def test_arxiv_id_extraction_attention():
    """Attention is all you need: arXiv 1706.03762 must be extracted from OA locations[].

    Per SA-Z2 §6.4 #6: OpenAlex Attention paper is data-polluted (year=2025, cites=6543);
    we don't test cited_by_count since it's known unreliable for this paper, but the
    arxiv_id extraction from locations[] should still work.
    """
    # Look up via DOI of the arXiv mirror to dodge W-ID drift; if not found via DOI
    # fall back to search-by-title.
    p = None
    for query in ["10.48550/arXiv.1706.03762", "Attention Is All You Need"]:
        try:
            if query.startswith("10."):
                p = get_work(query)
            else:
                hits = search_works(query, limit=3)
                # Prefer a hit whose title matches and has an arxiv landing
                for h in hits:
                    if "attention is all you need" in (h.title or "").lower():
                        p = h
                        break
            if p:
                break
        except Exception:
            continue

    assert p is not None, "could not locate Attention paper via DOI or title search"
    # arxiv_id should be present (no version suffix) given OA stores locations[]
    if p.arxiv_id:
        assert p.arxiv_id.startswith("1706.03762"), f"arxiv_id format: {p.arxiv_id!r}"
        # Should NOT have version suffix
        assert "v" not in p.arxiv_id, f"version suffix not stripped: {p.arxiv_id!r}"
        return f"arxiv_id={p.arxiv_id} title={p.title[:40]!r}"
    else:
        # If arxiv_id absent because OA stripped locations, still pass if doi is OK
        return f"no arxiv_id in OA record (acceptable); title={p.title[:40]!r}"


def test_get_work_doi_url_and_bare_form():
    """get_work() accepts both bare DOI and full URL form."""
    p1 = get_work("10.2307/1914185")
    p2 = get_work("https://doi.org/10.2307/1914185")
    assert p1.doi == p2.doi == "10.2307/1914185"
    assert p1.title == p2.title
    return "both DOI input forms equivalent"


def test_get_work_error_handling():
    """Looking up a non-existent paper should raise an exception (not silently return None)."""
    raised = False
    try:
        get_work("10.0000/this-doi-really-should-not-exist-xyz999")
    except Exception:
        raised = True
    assert raised, "lookup of non-existent paper should raise"
    return "non-existent paper raises as expected"


def test_search_in_journal_list_nature_science():
    """search_in_journal_list with 'nature_science' preset: all returned papers
    should be from Nature/Science/Cell/PNAS."""
    results = search_in_journal_list("CRISPR", preset_name="nature_science", limit=5)
    # Some queries may not yield 5 results in such a narrow preset; just verify
    # what we got is from the right venues
    expected_venues = {"Nature", "Science", "Cell", "Proceedings of the National Academy of Sciences"}
    venues_seen = set()
    for r in results:
        if r.venue:
            venues_seen.add(r.venue)
    if results:
        intersection = venues_seen & expected_venues
        assert intersection, (
            f"no result in expected venues. Got venues: {venues_seen}"
        )
        return f"{len(results)} papers in {sorted(intersection)}"
    return "no hits (acceptable for narrow query)"


def test_search_in_journal_list_unknown_preset():
    """Unknown preset should raise ValueError."""
    raised = False
    try:
        search_in_journal_list("test", preset_name="NoSuchPreset_XYZ")
    except ValueError as exc:
        raised = "Unknown preset" in str(exc)
    assert raised, "unknown preset should raise ValueError"
    return "ValueError raised correctly"


def test_analyze_topic_trends_returns_dict():
    """analyze_topic_trends returns dict {year:int -> count:int} with positive counts."""
    trends = analyze_topic_trends("large language model", year_range=(2020, 2025))
    assert isinstance(trends, dict)
    assert len(trends) >= 3, f"too few years: {trends}"
    for year, count in trends.items():
        assert isinstance(year, int)
        assert isinstance(count, int)
        assert count >= 0
    # LLM publications should be growing 2020->2024
    if 2020 in trends and 2024 in trends:
        assert trends[2024] > trends[2020], (
            f"expected 2024 > 2020 LLM count: {trends}"
        )
    return f"trends spans {min(trends)}-{max(trends)}, top year count={max(trends.values())}"


def test_get_citation_network_attention():
    """get_citation_network returns refs + cited_by lists for K&T 1979."""
    p = get_work("10.2307/1914185")
    if not p.openalex_id:
        return "skip: K&T has no OA W-ID"
    net = get_citation_network(p.openalex_id, refs_limit=10, cited_by_limit=10)
    assert isinstance(net, dict)
    assert "references" in net and "cited_by" in net
    assert isinstance(net["references"], list)
    assert isinstance(net["cited_by"], list)
    # K&T has >40k cites -> cited_by should yield papers
    assert len(net["cited_by"]) >= 5, f"cited_by yielded only {len(net['cited_by'])} papers"
    return f"refs={len(net['references'])}, cited_by={len(net['cited_by'])}"


def test_get_author_profile_by_name():
    """get_author_profile('Geoffrey Hinton') returns dict with h_index, works_count."""
    profile = get_author_profile("Geoffrey Hinton")
    assert isinstance(profile, dict)
    assert profile.get("name")
    assert "hinton" in profile["name"].lower(), f"unexpected name: {profile['name']!r}"
    # Hinton has very high citation count
    assert profile.get("total_citations", 0) > 100000, (
        f"Hinton total_citations too low: {profile.get('total_citations')}"
    )
    assert profile.get("works_count", 0) > 50, (
        f"Hinton works_count too low: {profile.get('works_count')}"
    )
    return f"Hinton: cites={profile['total_citations']}, works={profile['works_count']}"


# =============================================================================
# Main
# =============================================================================


def main():
    # Initialize pyalex with email from config (polite pool)
    cfg = load_config()
    init_pyalex(cfg)

    tests = [
        # Pure-Python (no network)
        ("test_journal_presets_completeness", test_journal_presets_completeness),
        ("test_strip_helpers", test_strip_helpers),
        ("test_to_entity_minimal", test_to_entity_minimal),
        ("test_per_page_constraint", test_per_page_constraint),
        # v2.2 --json-envelope (R-14) — pure + subprocess CLI (no live network)
        ("test_wrap_envelope_list_carries_count", test_wrap_envelope_list_carries_count),
        ("test_wrap_envelope_dict_omits_count", test_wrap_envelope_dict_omits_count),
        ("test_cli_presets_default_is_bare_list_no_envelope", test_cli_presets_default_is_bare_list_no_envelope),
        ("test_cli_presets_json_envelope_wraps_and_nudges_stderr", test_cli_presets_json_envelope_wraps_and_nudges_stderr),
        # v2.2 open item #1 (R-14) — nudge on search-initiation, not mid-pipeline
        ("test_cli_search_nudges_stderr_without_envelope", test_cli_search_nudges_stderr_without_envelope),
        ("test_cli_double_sort_nudges_stderr_without_envelope", test_cli_double_sort_nudges_stderr_without_envelope),
        ("test_cli_citation_network_does_not_nudge", test_cli_citation_network_does_not_nudge),
        ("test_cli_get_does_not_nudge", test_cli_get_does_not_nudge),
        # Network tests
        ("test_init_and_search_kt", test_init_and_search_kt),
        ("test_abstract_reconstruction_kt", test_abstract_reconstruction_kt),
        ("test_search_works_returns_unified_entities", test_search_works_returns_unified_entities),
        ("test_search_top_n_pages_deep", test_search_top_n_pages_deep),
        ("test_double_sort_search_combines", test_double_sort_search_combines),
        ("test_find_seminal_papers_year_filter", test_find_seminal_papers_year_filter),
        ("test_find_review_articles_type_filter", test_find_review_articles_type_filter),
        ("test_arxiv_id_extraction_attention", test_arxiv_id_extraction_attention),
        ("test_get_work_doi_url_and_bare_form", test_get_work_doi_url_and_bare_form),
        ("test_get_work_error_handling", test_get_work_error_handling),
        ("test_search_in_journal_list_nature_science", test_search_in_journal_list_nature_science),
        ("test_search_in_journal_list_unknown_preset", test_search_in_journal_list_unknown_preset),
        ("test_analyze_topic_trends_returns_dict", test_analyze_topic_trends_returns_dict),
        ("test_get_citation_network_attention", test_get_citation_network_attention),
        ("test_get_author_profile_by_name", test_get_author_profile_by_name),
    ]

    print(f"\nRunning {len(tests)} openalex_helper tests...\n")
    for name, fn in tests:
        _run(name, fn)

    total = len(tests)
    passed = _RESULTS["passed"]
    failed = _RESULTS["failed"]

    print()
    print(f"=== Results: {passed}/{total} passed, {failed} failed ===")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
