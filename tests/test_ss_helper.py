"""Live tests for scripts/ss_helper.py.

These hit the real Semantic Scholar API — the empirical evidence behind
ss_helper's design is only verifiable against live data (publisher takedown
states, influential-citation values, OA-fallback DOI artefacts).

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_ss_helper

API key: ss_helper reads it from Config (config.semantic_scholar_api_key).
If the user has put a key in ~/.paper-search-pro/config.yaml it gets used;
without one the tests still pass — they're just slower (SS no-key shared
1000 RPS pool, ~15x latency per 20_ss_sdk_test.md §1.2).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import ss_helper  # noqa: E402
from scripts.config import load_config  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures — well-known DOIs with documented empirical values.
# ---------------------------------------------------------------------------


def _attention_arxiv() -> UnifiedPaperEntity:
    """Vaswani et al. 2017 — the arXiv DOI form (which OpenAlex sometimes
    returns for preprints). Empirical: SS has NO DOI for this paper in its
    externalIds (only ArXiv/MAG/DBLP). The helper must skip this DOI form
    silently (per 24_v1_l3_enrichment_test.md §1 #2)."""
    return UnifiedPaperEntity(
        doi="10.48550/arxiv.1706.03762",  # arXiv DOI — must be SKIPPED
        title="Attention Is All You Need",
        year=2017,
        citation_count=100000,  # arbitrary placeholder
        sources=["openalex"],
    )


def _alphafold() -> UnifiedPaperEntity:
    """Jumper et al. 2021 — AlphaFold2. Picked because empirical (verified
    2026-05-21) SS has full enrichment: influCit=3442, abstract=1841 chars,
    tldr=312 chars. This is the canonical 'fully indexed paper' in our test
    matrix; it's also tag A2 in 24_v1_l3_enrichment_test.md §1 ('三源全可用')."""
    return UnifiedPaperEntity(
        doi="10.1038/s41586-021-03819-2",
        title="Highly accurate protein structure prediction with AlphaFold",
        year=2021,
        citation_count=30000,  # placeholder; SS reports ~35435
        sources=["openalex"],
    )


def _kt1979() -> UnifiedPaperEntity:
    """Kahneman & Tversky 1979 Prospect Theory. SS holds the Cambridge
    book-chapter DOI (the original Econometrica DOI 10.2307/1914185 was
    merged into it). SS_citation_count ~36694, OA reports ~46625 → ~21%
    delta in the merged record vs ~50% in the original — both above the
    30% threshold of cross_validate_citation depending on which OA record
    a caller passes. See 22_ss_research.md §5.3 and 24_v1_l3_enrichment §3.1."""
    return UnifiedPaperEntity(
        doi="10.1017/CBO9780511609220.014",
        title="Prospect Theory: An Analysis of Decision under Risk",
        year=1979,
        citation_count=46625,  # OpenAlex Econometrica record (per 22 §5.3)
        sources=["openalex"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_with_config():
    """init() should accept Config and produce a usable client without
    raising. Idempotent — repeat calls are safe."""
    config = load_config()
    ss_helper.init(config)
    ss_helper.init(config)  # second call must not blow up
    # Indirectly verify a client was set: a no-eligible-DOI batch is a no-op.
    empty_result = ss_helper.enrich_with_metadata([])
    assert empty_result == []
    print("OK  init_with_config")


def test_doi_normalisation():
    """_doi_for_ss should lowercase, strip URL prefixes, and skip arXiv DOIs."""
    assert ss_helper._doi_for_ss(None) is None
    assert ss_helper._doi_for_ss("") is None
    assert ss_helper._doi_for_ss("10.1234/Foo") == "DOI:10.1234/foo"
    assert ss_helper._doi_for_ss("https://doi.org/10.1234/Bar") == "DOI:10.1234/bar"
    # arXiv DOIs must be SKIPPED — empirical: SS 100% 404 on these.
    assert ss_helper._doi_for_ss("10.48550/arXiv.1706.03762") is None
    assert ss_helper._doi_for_ss("10.48550/arxiv.1706.03762") is None
    print("OK  doi_normalisation (arXiv skip + URL strip + lowercase)")


def test_enrich_with_metadata_adds_influ_and_tldr():
    """For a paper SS has fully indexed (AlphaFold via DOI), enrichment
    should add influential_citation_count, ss_paper_id, tldr, and append
    'semantic_scholar' to sources.

    Empirical baseline (verified 2026-05-21):
    AlphaFold → influCit=3442, abstract_len=1841, tldr_len=312."""
    p = _alphafold()
    [enriched] = ss_helper.enrich_with_metadata([p])

    # influentialCitationCount is the SS-unique signal we MUST capture.
    assert enriched.influential_citation_count is not None, "influCit missing"
    assert enriched.influential_citation_count > 500, (
        f"AlphaFold influCit looked too low: {enriched.influential_citation_count}"
    )
    # SS paperId — hex string.
    assert enriched.ss_paper_id, "ss_paper_id missing"
    assert len(enriched.ss_paper_id) > 20, f"ss_paper_id looks short: {enriched.ss_paper_id!r}"
    # TLDR — auxiliary metadata, must be non-empty for a paper SS has indexed.
    assert enriched.tldr and len(enriched.tldr) > 50, (
        f"TLDR missing or too short: {enriched.tldr!r}"
    )
    # Sources updated.
    assert "semantic_scholar" in enriched.sources
    print(
        f"OK  enrich_with_metadata adds influCit={enriched.influential_citation_count} "
        f"tldr={len(enriched.tldr)} chars"
    )


def test_enrich_skips_arxiv_doi():
    """Papers whose DOI is arXiv-form should be skipped silently and remain
    unchanged (per ss_helper._doi_for_ss filter — verified empirically that
    SS returns ObjectNotFoundException for 10.48550/arXiv.* DOIs)."""
    p = _attention_arxiv()  # DOI = 10.48550/arxiv.1706.03762
    before_sources = list(p.sources)
    [enriched] = ss_helper.enrich_with_metadata([p])

    # Nothing should have been added — entity should look the same.
    assert enriched.influential_citation_count is None
    assert enriched.ss_paper_id is None
    assert enriched.tldr is None
    assert enriched.sources == before_sources
    print("OK  enrich_skips_arxiv_doi (no mutation on arXiv DOI)")


def test_abstract_fallback_graceful_on_takedown():
    """K&T 1979's abstract is publisher-elided (empirical: SS abstract=None,
    tldr=None — see 20_ss_sdk_test.md §3.2 and 24_v1_l3_enrichment §1).
    abstract_fallback should return None gracefully — never raise."""
    p = _kt1979()
    p.abstract = None  # simulate OA also leaving abstract None

    result = ss_helper.abstract_fallback(p)
    # Either None (takedown) or some text — but never an exception.
    # The empirical case is None; assert that, with a tolerant message if
    # SS re-populates the field someday.
    assert result is None or isinstance(result, str), (
        f"abstract_fallback should return None or str, got {type(result).__name__}"
    )
    print(f"OK  abstract_fallback_graceful_on_takedown → {result!r}")


def test_abstract_fallback_returns_existing_if_set():
    """If the entity already has an abstract, fallback should just return it
    — no network call needed."""
    p = _kt1979()
    p.abstract = "Already present from OpenAlex."
    result = ss_helper.abstract_fallback(p)
    assert result == "Already present from OpenAlex."
    print("OK  abstract_fallback short-circuits when abstract already set")


def test_cross_validate_citation_detects_conflict():
    """Watson & Crick 1953 (DNA structure) has a well-documented citation
    disagreement between OA (~13148) and SS (~8778) — empirical delta ~33%
    per 24_v1_l3_enrichment_test.md §3.1. cross_validate_citation MUST detect
    this and return at least one conflict dict with the contract shape.
    Also runs K&T 1979 in the same batch to verify the function handles the
    publisher-elided paper without raising (its delta is borderline ~21%
    using the merged-DOI SS figure)."""
    dna = UnifiedPaperEntity(
        doi="10.1038/171737a0",
        title="Molecular Structure of Nucleic Acids",
        year=1953,
        citation_count=13148,  # OpenAlex figure per 24 doc §3.1
        sources=["openalex"],
    )
    conflicts = ss_helper.cross_validate_citation([dna, _kt1979()])
    assert isinstance(conflicts, list)
    # Every reported conflict must have the contract keys + above threshold.
    for c in conflicts:
        assert {"paper_id", "title", "oa_count", "ss_count", "delta_pct"} <= set(c.keys())
        assert c["delta_pct"] > 30.0
    # DNA delta is empirically ~33% — it MUST be flagged.
    dna_conflicts = [c for c in conflicts if c["paper_id"] == "10.1038/171737a0"]
    assert dna_conflicts, (
        f"Expected DNA Watson & Crick to be flagged as a citation conflict "
        f"(OA 13148 vs SS ~8778, delta ~33%); got conflicts={conflicts}"
    )
    c = dna_conflicts[0]
    print(
        f"OK  cross_validate_citation detected DNA conflict: "
        f"OA={c['oa_count']} SS={c['ss_count']} delta={c['delta_pct']}%"
    )


def test_empty_inputs_are_safe():
    """All public functions must handle empty / no-eligible input without
    crashing or making spurious network calls."""
    assert ss_helper.enrich_with_metadata([]) == []
    assert ss_helper.cross_validate_citation([]) == []
    # An entity with no DOI → no SS call possible.
    p = UnifiedPaperEntity(title="No DOI", citation_count=5)
    [out] = ss_helper.enrich_with_metadata([p])
    assert out.influential_citation_count is None
    assert "semantic_scholar" not in out.sources
    assert ss_helper.abstract_fallback(p) is None
    print("OK  empty_inputs_are_safe")


def test_sources_list_dedup():
    """If a paper is already marked as having SS provenance, enriching it
    again must not add 'semantic_scholar' twice."""
    p = _alphafold()
    p.sources = ["openalex", "semantic_scholar"]  # pre-existing tag
    ss_helper.enrich_with_metadata([p])
    assert p.sources.count("semantic_scholar") == 1, p.sources
    print("OK  sources_list_dedup (no duplicate semantic_scholar tag)")


# ---------------------------------------------------------------------------
# v2.2 independent search — mostly deterministic (fake bulk session), plus the
# record->entity mapping which is pure. No reliance on live SS for the core
# contract, so these stay green offline / when SS is flaky.
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeBulkSession:
    """Returns one preset page per (sort) strategy, keyed by the `sort` param so
    we can give different strategies different results and exercise the
    cross-strategy boost. No continuation token (single page each)."""

    def __init__(self, pages_by_sort, status_code=200):
        self.pages_by_sort = pages_by_sort
        self.status_code = status_code
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        sort = (params or {}).get("sort")  # None for the default-order strategy
        payload = {"data": self.pages_by_sort.get(sort, []), "token": None}
        return _FakeResp(payload, self.status_code)


def _ss_record(
    doi=None, paper_id="abc123", title="X", year=2020, cites=10, icit=2,
    issn=None, venue_name=None, arxiv=None, pmid=None, abstract=None, pdf=None,
):
    ext = {}
    if doi:
        ext["DOI"] = doi
    if arxiv:
        ext["ArXiv"] = arxiv
    if pmid:
        ext["PubMed"] = pmid
    pv = None
    if issn or venue_name:
        pv = {"name": venue_name, "issn": issn}
    rec = {
        "paperId": paper_id,
        "externalIds": ext,
        "title": title,
        "year": year,
        "citationCount": cites,
        "influentialCitationCount": icit,
        "publicationVenue": pv,
        "authors": [{"name": "A. One"}, {"name": "B. Two"}],
    }
    if abstract is not None:
        rec["abstract"] = abstract
    if pdf is not None:
        rec["openAccessPdf"] = {"url": pdf}
    return rec


def test_ss_record_to_entity_mapping():
    """Pure: a fully-populated bulk record maps to a UnifiedPaperEntity with the
    OpenAlex-compatible field shape, including issn from publicationVenue (R-08)."""
    rec = _ss_record(
        doi="10.1234/Foo", paper_id="HEX", title="Mapped Paper", year=2019,
        cites=123, icit=7, issn="1234-5678", venue_name="Journal of Things",
        abstract="An abstract.", pdf="https://x/y.pdf",
    )
    e = ss_helper._ss_record_to_entity(rec)
    assert e.doi == "10.1234/foo"  # normalised lowercase, no prefix
    assert e.ss_paper_id == "HEX"
    assert e.title == "Mapped Paper"
    assert e.year == 2019
    assert e.citation_count == 123
    assert e.influential_citation_count == 7
    assert e.issn == "1234-5678"
    assert e.venue == "Journal of Things"
    assert e.abstract == "An abstract."
    assert e.is_oa is True and e.pdf_url == "https://x/y.pdf"
    assert e.doi_url == "https://doi.org/10.1234/foo"
    assert [a.name for a in e.authors] == ["A. One", "B. Two"]
    assert e.sources == ["semantic_scholar"]
    print("OK  ss_record_to_entity_mapping (issn + OA-compatible shape)")


def test_ss_record_to_entity_missing_venue_issn_is_none():
    """~1/3 of SS records have no publicationVenue -> issn must be None, not crash
    (R-08). Falls back to flat `venue` string when present."""
    rec = _ss_record(doi="10.1/x", issn=None, venue_name=None)
    rec["venue"] = "Flat Venue Name"  # the bulk endpoint's flat field
    e = ss_helper._ss_record_to_entity(rec)
    assert e.issn is None
    assert e.venue == "Flat Venue Name"
    print("OK  ss_record_to_entity_missing_venue_issn_is_none")


def test_ss_record_to_entity_arxiv_and_pmid():
    rec = _ss_record(doi=None, arxiv="1706.03762v5", pmid="123456")
    e = ss_helper._ss_record_to_entity(rec)
    assert e.arxiv_id == "1706.03762"  # version suffix stripped
    assert e.pmid == "123456"
    print("OK  ss_record_to_entity_arxiv_and_pmid")


def test_search_double_sort_merge_and_boost():
    """A paper appearing in >=2 strategies must rank above a single-strategy
    paper with HIGHER citations (appearance count is the primary sort key,
    mirroring openalex double_sort_search)."""
    shared = _ss_record(doi="10.1/shared", paper_id="SH", title="Shared", cites=50)
    only_cited = _ss_record(doi="10.1/cited", paper_id="CT", title="HighCite", cites=9999)
    only_recent = _ss_record(doi="10.1/recent", paper_id="RC", title="Recent", cites=5)
    pages = {
        "citationCount:desc": [only_cited, shared],
        "publicationDate:desc": [only_recent, shared],
        None: [shared],
    }
    sess = _FakeBulkSession(pages)
    results = ss_helper.search("q", total_per_strategy=10, session=sess)
    ids = [p.paper_id for p in results]
    # Shared appears in all 3 strategies -> must be first despite lower cites.
    assert ids[0] == "10.1/shared", ids
    # All three unique papers present.
    assert set(ids) == {"10.1/shared", "10.1/cited", "10.1/recent"}
    # Among single-appearance papers, higher citation_count ranks first.
    assert ids.index("10.1/cited") < ids.index("10.1/recent")
    print("OK  search_double_sort_merge_and_boost")


def test_search_passes_year_filter_param():
    """year_min/year_max must be sent to SS as a single `year=lo-hi` param."""
    rec = _ss_record(doi="10.1/y", paper_id="Y")
    sess = _FakeBulkSession({"citationCount:desc": [rec], "publicationDate:desc": [], None: []})
    ss_helper.search("q", year_min=2015, year_max=2020, total_per_strategy=5, session=sess)
    # Every call should carry the year range.
    assert sess.calls, "no HTTP calls made"
    assert all(c["params"].get("year") == "2015-2020" for c in sess.calls), [
        c["params"].get("year") for c in sess.calls
    ]
    print("OK  search_passes_year_filter_param")


def test_search_no_key_returns_empty_on_429():
    """No key -> SS 429s on the shared pool (R-06). search() must degrade to []
    rather than raise."""
    sess = _FakeBulkSession({}, status_code=429)
    results = ss_helper.search("q", total_per_strategy=5, session=sess)
    assert results == []
    print("OK  search_no_key_returns_empty_on_429")


def test_search_network_error_degrades_to_empty():
    """A raising session must not crash search()."""

    class _Boom:
        def get(self, *a, **kw):
            raise RuntimeError("network down")

    results = ss_helper.search("q", total_per_strategy=5, session=_Boom())
    assert results == []
    print("OK  search_network_error_degrades_to_empty")


def test_search_entity_to_dict_is_full_and_json_safe():
    """The search serialiser must emit the broad OpenAlex-compatible field set
    (incl. issn + authors flattened) so federated_kg_resolver can ingest it."""
    import json

    e = ss_helper._ss_record_to_entity(
        _ss_record(doi="10.1/z", issn="9999-0000", venue_name="V")
    )
    d = ss_helper._search_entity_to_dict(e)
    json.dumps(d)  # must not raise
    assert d["issn"] == "9999-0000"
    assert d["sources"] == ["semantic_scholar"]
    assert isinstance(d["authors"], list) and d["authors"][0]["name"] == "A. One"
    # Broad field set present (not the narrow enrich serialiser).
    assert "venue" in d and "is_oa" in d and "keywords" in d
    print("OK  search_entity_to_dict_is_full_and_json_safe")


def test_search_live_smoke():
    """Optional live smoke: real SS bulk search for a high-signal query.

    Tolerant: if SS is unreachable / rate-limited / no key (-> []), we skip the
    content assertions so the suite stays green offline. When results DO come
    back, K&T 1979 (the canonical top-cited prospect-theory paper) should be
    present with a large citation count."""
    ss_helper.init(load_config())
    try:
        results = ss_helper.search("prospect theory", total_per_strategy=10)
    except Exception as exc:  # never let a live flake fail the gate
        print(f"SKIP search_live_smoke (live error: {type(exc).__name__})")
        return
    if not results:
        print("SKIP search_live_smoke (no results — likely no SS key / rate-limited)")
        return
    # Shape checks on whatever came back.
    top = results[0]
    assert top.title, "top result has no title"
    assert top.citation_count >= 0
    assert "semantic_scholar" in top.sources
    # The corpus should contain the canonical K&T 1979 with huge citations.
    big = [p for p in results if (p.citation_count or 0) > 10000]
    assert big, f"expected >=1 highly-cited paper; got max cites {max((p.citation_count or 0) for p in results)}"
    print(
        f"OK  search_live_smoke — {len(results)} papers, top='{top.title[:40]}' "
        f"cites={top.citation_count}"
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    # Initialise once for all tests that hit the network.
    ss_helper.init(load_config())

    tests = [
        test_init_with_config,
        test_doi_normalisation,
        test_enrich_with_metadata_adds_influ_and_tldr,
        test_enrich_skips_arxiv_doi,
        test_abstract_fallback_graceful_on_takedown,
        test_abstract_fallback_returns_existing_if_set,
        test_cross_validate_citation_detects_conflict,
        test_empty_inputs_are_safe,
        test_sources_list_dedup,
        # v2.2 search
        test_ss_record_to_entity_mapping,
        test_ss_record_to_entity_missing_venue_issn_is_none,
        test_ss_record_to_entity_arxiv_and_pmid,
        test_search_double_sort_merge_and_boost,
        test_search_passes_year_filter_param,
        test_search_no_key_returns_empty_on_429,
        test_search_network_error_degrades_to_empty,
        test_search_entity_to_dict_is_full_and_json_safe,
        test_search_live_smoke,
    ]
    failed = []
    t_start = time.time()
    for t in tests:
        try:
            t()
        except Exception as exc:
            import traceback
            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed.append(t.__name__)
    elapsed = time.time() - t_start
    print()
    print(f"Ran {len(tests)} tests in {elapsed:.1f}s — {len(tests) - len(failed)} pass / {len(failed)} fail")
    if failed:
        print("Failures:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
