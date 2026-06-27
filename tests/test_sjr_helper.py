"""Tests for scripts/sjr_helper.py + agent_search journal_metric integration.

Everything here is deterministic and network-free: the SJR CSV is a small inline
sample written to a temp dir (never the real Cloudflare-gated download), and the
agent_search integration monkeypatches the OpenAlex retrieval + impact lookup +
quota probe with fakes. The OpenAlex/SJR network is NEVER touched (avoids the
live-key 429 the project's other live tests can hit).

Coverage:
  - ISSN normalisation (hyphen strip, 8-char gate, multi-ISSN split)
  - European-decimal parsing (145,004 -> 145.004)
  - multi-category quartile parsing + best-quartile derivation
  - CSV parse (semicolon, name-resolved columns, no-ISSN row skipped)
  - ISSN-set-intersection join (hyphenated OA ISSN -> hyphen-free SJR key)
  - build_journal_metric (quartile + impact + attribution; backfill flag; empty)
  - metric_is_empty contract
  - agent_search: journal_metric fill, --quartile / --min-impact filters,
    after_journal_filter count, --no-journal-metric, attribution in meta
  - R-19: a paper WITHOUT journal data omits the key (additive, byte-identical)

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_sjr_helper
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_sjr_helper.py -q
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import sjr_helper, agent_search, openalex_helper, quota_guard  # noqa: E402
from scripts.journal_rank import normalize_issns  # noqa: E402
from scripts.types import (  # noqa: E402
    Author,
    CASRank,
    Config,
    JCRRank,
    JournalMetric,
    JournalRank,
    SJRRank,
    UnifiedPaperEntity,
)


# ---------------------------------------------------------------------------
# Patching helper (restores originals — pytest collects test files alphabetically
# and a leaked patch of openalex_helper / quota_guard would corrupt their later
# live tests). Mirrors test_agent_search._patched.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched(*targets):
    saved = [(obj, attr, getattr(obj, attr)) for (obj, attr, _new) in targets]
    try:
        for obj, attr, new in targets:
            setattr(obj, attr, new)
        yield
    finally:
        for obj, attr, old in saved:
            setattr(obj, attr, old)


# A small but representative SJR CSV: real schema (26 cols), semicolon, European
# decimals, multi-category quartiles, a no-ISSN row, and a blank-best-quartile row.
_SAMPLE_CSV = (
    "Rank;Sourceid;Title;Type;Issn;Publisher;Open Access;Open Access Diamond;SJR;"
    "SJR Best Quartile;H index;Total Docs. (2024);Total Docs. (3years);Total Refs.;"
    "Total Citations (3years);Citable Docs. (3years);Citations / Doc. (2years);"
    "Ref. / Doc.;%Female;Overton;Country;Region;Publisher;Coverage;Categories;Areas\n"
    '1;28773;"Ca-A Cancer Journal for Clinicians";journal;"15424863, 00079235";'
    '"John Wiley and Sons Inc";No;No;145,004;Q1;236;43;122;1500;5000;120;50,5;30,2;'
    '40;5;United States;Northern America;"John Wiley and Sons Inc";1950-2024;'
    '"Hematology (Q1); Oncology (Q1)";"Medicine"\n'
    '2;19434;"Journal of Personality and Social Psychology";journal;'
    '"00223514, 19391315";"American Psychological Association";No;No;5,123;Q1;757;'
    '200;600;8000;9000;590;3,2;45,1;55;2;United States;Northern America;'
    '"American Psychological Association";1965-2024;'
    '"Social Psychology (Q1); Sociology and Political Science (Q2)";"Psychology"\n'
    '3;99999;"Mid Tier Journal";journal;"12345678";"Some Publisher";No;No;0,850;Q3;'
    '40;80;200;3000;500;190;0,9;15,0;48;0;United Kingdom;Western Europe;'
    '"Some Publisher";2000-2024;"Materials Science (Q3); Engineering (Q4)";'
    '"Materials Science"\n'
    '4;88888;"No ISSN Journal";journal;"";"Ghost Publisher";No;No;0,100;;5;10;30;'
    '100;20;28;0,1;5,0;50;0;Unknown;Unknown;"Ghost Publisher";2020-2024;"";"Misc"\n'
    '5;77777;"Blank Quartile Journal";journal;"99887766";"Pub X";Yes;No;0,300;;12;'
    '20;50;500;100;48;0,5;10;50;0;Canada;Northern America;"Pub X";2015-2024;'
    '"Education (Q2); Linguistics (Q4)";"Social Sciences"\n'
)


@contextlib.contextmanager
def _sample_csv():
    with tempfile.TemporaryDirectory(prefix="sjr_test_") as td:
        p = Path(td) / "scimagojr 2024.csv"
        p.write_text(_SAMPLE_CSV, encoding="utf-8")
        yield p


# ===========================================================================
# ISSN normalisation
# ===========================================================================


def test_normalize_issn_strips_hyphen_and_gates_length():
    assert sjr_helper.normalize_issn("0022-3514") == "00223514"
    assert sjr_helper.normalize_issn("00223514") == "00223514"
    assert sjr_helper.normalize_issn("1542-486x") == "1542486X"  # X upper-cased
    assert sjr_helper.normalize_issn("123") is None  # too short
    assert sjr_helper.normalize_issn("") is None
    assert sjr_helper.normalize_issn(None) is None
    print("OK  normalize_issn_strips_hyphen_and_gates_length")


def test_normalize_issns_splits_multi_and_dedupes():
    out = sjr_helper.normalize_issns("15424863, 00079235")
    assert out == ["15424863", "00079235"]
    # dedupe + drop garbage
    assert sjr_helper.normalize_issns("0022-3514, 00223514, junk") == ["00223514"]
    assert sjr_helper.normalize_issns("") == []
    print("OK  normalize_issns_splits_multi_and_dedupes")


# ===========================================================================
# European decimal + category parsing
# ===========================================================================


def test_parse_european_float():
    assert sjr_helper._parse_european_float("145,004") == 145.004
    assert sjr_helper._parse_european_float("5,123") == 5.123
    assert sjr_helper._parse_european_float("0,100") == 0.1
    assert sjr_helper._parse_european_float("") is None
    assert sjr_helper._parse_european_float("n/a") is None
    print("OK  parse_european_float")


def test_parse_categories_multi_quartile():
    cats = sjr_helper.parse_categories("Hematology (Q1); Oncology (Q1)")
    assert cats == {"Hematology": "Q1", "Oncology": "Q1"}
    mixed = sjr_helper.parse_categories("Software (Q2); Information Systems (Q3)")
    assert mixed == {"Software": "Q2", "Information Systems": "Q3"}
    # bare category w/o (Qn) is skipped
    assert sjr_helper.parse_categories("Misc; Other (Q4)") == {"Other": "Q4"}
    assert sjr_helper.parse_categories("") == {}
    print("OK  parse_categories_multi_quartile")


# ===========================================================================
# CSV parse + lookup
# ===========================================================================


def test_parse_sjr_csv_skips_no_issn_and_resolves_columns():
    with _sample_csv() as p:
        recs = sjr_helper.parse_sjr_csv(p)
    # 5 rows but the no-ISSN row is unjoinable -> 4 records.
    assert len(recs) == 4
    titles = {r.title for r in recs}
    assert "No ISSN Journal" not in titles
    by_issn = {tuple(r.issns): r for r in recs}
    caa = sjr_helper.build_issn_lookup(recs)["15424863"]
    assert caa.sjr_value == 145.004  # European decimal parsed
    assert caa.best_quartile == "Q1"
    assert caa.category_quartiles == {"Hematology": "Q1", "Oncology": "Q1"}
    print("OK  parse_sjr_csv_skips_no_issn_and_resolves_columns")


def test_blank_best_quartile_derived_from_categories():
    with _sample_csv() as p:
        lk = sjr_helper.load(csv_path=p)
    blank = lk.for_issn("9988-7766")  # Education (Q2); Linguistics (Q4)
    assert blank is not None
    assert blank.best_quartile == "Q2"  # best (min) of Q2,Q4
    print("OK  blank_best_quartile_derived_from_categories")


def test_join_hyphenated_oa_issn_to_hyphenfree_sjr_key():
    with _sample_csv() as p:
        lk = sjr_helper.load(csv_path=p)
    # OpenAlex emits hyphenated; SJR stores hyphen-free — set-intersection join.
    jpsp = lk.for_issn("0022-3514")
    assert jpsp is not None and "Personality" in jpsp.title
    # join also works on the eISSN of the same journal.
    assert lk.for_issn("1939-1315") is jpsp
    assert lk.for_issn("0000-0000") is None  # unjoinable
    print("OK  join_hyphenated_oa_issn_to_hyphenfree_sjr_key")


def test_quartile_for_category_pin_vs_best():
    with _sample_csv() as p:
        lk = sjr_helper.load(csv_path=p)
    jpsp = lk.for_issn("0022-3514")
    assert jpsp.quartile_for() == "Q1"  # best, default
    assert jpsp.quartile_for("Sociology and Political Science") == "Q2"  # pinned
    assert jpsp.quartile_for("nonexistent") == "Q1"  # fall back to best
    print("OK  quartile_for_category_pin_vs_best")


def test_load_returns_none_when_no_csv():
    with tempfile.TemporaryDirectory() as td:
        assert sjr_helper.load(cache_dir=Path(td)) is None  # empty cache -> None
    print("OK  load_returns_none_when_no_csv")


def test_find_cached_csv_picks_newest():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "scimagojr 2023.csv").write_text("a", encoding="utf-8")
        newer = td / "scimagojr 2024.csv"
        newer.write_text("b", encoding="utf-8")
        # bump mtime so 2024 is newest deterministically
        import os, time
        os.utime(newer, (time.time() + 10, time.time() + 10))
        assert sjr_helper.find_cached_csv(td) == newer
    print("OK  find_cached_csv_picks_newest")


# ===========================================================================
# build_journal_metric + metric_is_empty
# ===========================================================================


def _fake_impact(issn):
    if "0022" in issn:
        return {"two_year_mean_citedness": 2.72, "h_index": 757}
    if "1234" in issn:
        return {"two_year_mean_citedness": 0.5, "h_index": 40}
    return None


def test_build_journal_metric_full_join_sets_attribution():
    with _sample_csv() as p:
        lk = sjr_helper.load(csv_path=p)
    m = sjr_helper.build_journal_metric("0022-3514", sjr=lk, impact_lookup=_fake_impact)
    assert m.sjr_quartile == "Q1"
    assert m.openalex_2yr_mean_citedness == 2.72
    assert m.h_index == 757
    assert m.sjr_attribution == sjr_helper.SJR_ATTRIBUTION  # R-03
    assert m.issn_backfill_needed is False
    print("OK  build_journal_metric_full_join_sets_attribution")


def test_build_journal_metric_missing_issn_flags_backfill():
    m = sjr_helper.build_journal_metric(None, sjr=None)
    assert m.issn_backfill_needed is True  # R-08: gap is visible
    assert sjr_helper.metric_is_empty(m) is True
    print("OK  build_journal_metric_missing_issn_flags_backfill")


def test_build_journal_metric_unjoinable_is_empty():
    with _sample_csv() as p:
        lk = sjr_helper.load(csv_path=p)
    m = sjr_helper.build_journal_metric("0000-0000", sjr=lk, impact_lookup=None)
    assert sjr_helper.metric_is_empty(m) is True
    assert m.sjr_attribution is None  # no SJR data -> no attribution
    print("OK  build_journal_metric_unjoinable_is_empty")


def test_metric_is_empty_contract():
    assert sjr_helper.metric_is_empty(None) is True
    assert sjr_helper.metric_is_empty(JournalMetric()) is True
    assert sjr_helper.metric_is_empty(JournalMetric(issn_backfill_needed=True)) is True
    assert sjr_helper.metric_is_empty(JournalMetric(sjr_quartile="Q1")) is False
    assert sjr_helper.metric_is_empty(JournalMetric(openalex_2yr_mean_citedness=1.0)) is False
    print("OK  metric_is_empty_contract")


# ===========================================================================
# agent_search journal RANK integration (network-free) — single-layer collapse.
#
# v2.2: the legacy SJR-only journal_metric path in agent_search is RETIRED. SJR
# quartile + OpenAlex open impact now live in the SINGLE journal_rank record
# (CAS/JCR/SJR + an ``openalex`` sub-slot). These integration tests therefore
# assert the new single layer: per-paper ``journal_rank`` (NO journal_metric key),
# --quartile filtering journal_rank.sjr.best_quartile, --min-impact filtering
# journal_rank.openalex.mean_citedness_2yr, and the ``meta.enrichment`` audit.
# (The pure sjr_helper unit tests above are unchanged — sjr_helper itself stays.)
# ===========================================================================


def _mk(doi, title, issn, cites, oaid):
    return UnifiedPaperEntity(
        doi=doi, openalex_id=oaid, title=title, abstract=title, year=2024,
        citation_count=cites, issn=issn, authors=[Author(name="A. One")],
        sources=["openalex"],
    )


class _FakeQuota:
    ok = True
    should_switch = False
    remaining_usd = 0.9

    def to_dict(self):
        return {"ok": True, "remaining_usd": 0.9, "mode": "probe"}


class _FakeRankLookup:
    """In-memory ISSN -> JournalRank table + lookup()/loaded_platforms (mirrors
    journal_rank.RankLookup so agent_search annotates the single journal layer)."""

    def __init__(self, table, loaded=("cas", "jcr", "sjr")):
        self._t = table
        self.loaded_platforms = list(loaded)

    def lookup(self, issn):
        for n in normalize_issns(issn):
            if n in self._t:
                rec = self._t[n]
                rec.matched_issn = n
                return rec
        return None


def _rank_lookup():
    """JPSP (0022-3514) = SJR Q1; Mid Tier (1234-5678) = SJR Q3 — mirrors the SJR
    quartiles in the inline sample CSV, but served via the new journal_rank layer."""
    return _FakeRankLookup(
        {
            "0022-3514": JournalRank(
                title="Journal of Personality and Social Psychology",
                issns=["0022-3514"],
                cas=CASRank(tier=1, rank="5/100", top=True, source_year=2025),
                jcr=JCRRank(quartile="Q1", impact_factor=7.6, source_year=2024),
                sjr=SJRRank(best_quartile="Q1", sjr=5.1, source_year=2024),
                matched_platforms=["cas", "jcr", "sjr"],
            ),
            "1234-5678": JournalRank(
                title="Mid Tier Journal",
                issns=["1234-5678"],
                sjr=SJRRank(best_quartile="Q3", sjr=0.85, source_year=2024),
                matched_platforms=["sjr"],
            ),
        }
    )


def _oa_search_targets(papers, lookup=None):
    def fake_search(query, total_papers=50, sort=None, year_min=None):
        return papers if sort == "cited_by_count:desc" else []
    if lookup is None:
        lookup = _rank_lookup()
    return [
        (openalex_helper, "search_top_n_pages", fake_search),
        (openalex_helper, "init_pyalex", lambda c: None),
        (openalex_helper, "get_source_impact", _fake_impact),
        (quota_guard, "evaluate", lambda c, mode="probe": _FakeQuota()),
        # Single journal layer served via journal_rank.load (deterministic — does
        # not depend on machine cache state). Pass lookup=None-via-arg to a test
        # to model "no rank data cached".
        (agent_search.journal_rank, "load", lambda **kw: lookup),
    ]


def _cfg():
    c = Config()
    c.primary_source = "openalex"
    c.openalex_api_key = "k"
    c.openalex_email = "e@x.com"
    return c


def test_agent_search_fills_journal_rank_sjr_and_openalex():
    """Single layer: each paper's journal_rank carries SJR quartile + the OpenAlex
    open impact (in journal_rank.openalex); NO per-paper journal_metric key."""
    papers = [
        _mk("10.1/jpsp", "prospect theory psychology", "0022-3514", 5000, "W1"),
        _mk("10.3/none", "prospect theory unknown", "0000-0000", 10, "W3"),
    ]
    with _patched(*_oa_search_targets(papers)):
        env = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10, now_year=2026
        )
    assert env["ok"] is True
    jpsp = next(d for d in env["data"] if "psychology" in d["title"])
    assert "journal_metric" not in jpsp  # legacy per-paper key retired
    jr = jpsp["journal_rank"]
    assert jr["sjr"]["best_quartile"] == "Q1"
    assert jr["openalex"]["mean_citedness_2yr"] == 2.72
    assert jr["openalex"]["h_index"] == 757
    # Unjoinable journal with no reachable impact -> journal_rank None.
    unknown = next(d for d in env["data"] if "unknown" in d["title"])
    assert unknown["journal_rank"] is None
    # Enrichment audit + per-platform attribution.
    en = env["meta"]["enrichment"]
    assert en["enriched"] is True
    assert en["impact_source"] == "openalex_summary_stats"
    assert en["impact_attached"] >= 1
    assert env["meta"]["rank"]["data_loaded"] is True
    print("OK  agent_search_fills_journal_rank_sjr_and_openalex")


def test_agent_search_quartile_filter_is_opt_in():
    """--quartile filters journal_rank.sjr.best_quartile (the single layer)."""
    papers = [
        _mk("10.1/jpsp", "prospect theory psychology", "0022-3514", 5000, "W1"),  # SJR Q1
        _mk("10.2/mid", "prospect theory mid tier", "1234-5678", 50, "W2"),       # SJR Q3
    ]
    with _patched(*_oa_search_targets(papers)):
        # No filter: both returned, both annotated.
        env_all = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10, now_year=2026
        )
        assert env_all["meta"]["counts"]["after_journal_filter"] == 2
        # Q1 only: drops the Q3 mid-tier journal.
        env_q1 = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10,
            quartiles=["Q1"], now_year=2026,
        )
    titles = [d["title"] for d in env_q1["data"]]
    assert titles == ["prospect theory psychology"]
    assert env_q1["meta"]["counts"]["after_journal_filter"] == 1
    assert env_q1["meta"]["enrichment"]["filter_quartiles"] == ["Q1"]
    print("OK  agent_search_quartile_filter_is_opt_in")


def test_agent_search_min_impact_filter():
    """--min-impact filters journal_rank.openalex.mean_citedness_2yr."""
    papers = [
        _mk("10.1/jpsp", "prospect theory psychology", "0022-3514", 5000, "W1"),  # 2.72
        _mk("10.2/mid", "prospect theory mid tier", "1234-5678", 50, "W2"),       # 0.5
    ]
    with _patched(*_oa_search_targets(papers)):
        env = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10,
            min_impact=1.0, now_year=2026,
        )
    assert [d["title"] for d in env["data"]] == ["prospect theory psychology"]
    assert env["meta"]["counts"]["after_journal_filter"] == 1
    assert env["meta"]["enrichment"]["filter_min_impact"] == 1.0
    print("OK  agent_search_min_impact_filter")


def test_agent_search_no_journal_metric_keeps_slots_none():
    """--no-journal-metric (enrich_journal=False): journal_rank stays None for all."""
    papers = [_mk("10.1/jpsp", "prospect theory", "0022-3514", 5000, "W1")]
    with _patched(*_oa_search_targets(papers)):
        env = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10,
            enrich_journal=False, now_year=2026,
        )
    assert all(d["journal_rank"] is None for d in env["data"])
    assert all("journal_metric" not in d for d in env["data"])
    assert env["meta"]["enrichment"]["enriched"] is False
    print("OK  agent_search_no_journal_metric_keeps_slots_none")


def test_agent_search_no_rank_cache_degrades_gracefully():
    """No cached rank data: 分区 labels unavailable, run still succeeds, the OpenAlex
    open impact still attaches to an openalex-only journal_rank (single layer)."""
    papers = [_mk("10.1/jpsp", "prospect theory", "0022-3514", 5000, "W1")]
    # lookup=False-like: model "no rank data cached" with journal_rank.load -> None.
    targets = _oa_search_targets(papers, lookup=None)
    # Override the load mock to return None (no cache) while keeping impact reachable.
    targets = [t for t in targets if not (t[0] is agent_search.journal_rank and t[1] == "load")]
    targets.append((agent_search.journal_rank, "load", lambda **kw: None))
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10, now_year=2026,
        )
    assert env["ok"] is True
    assert env["meta"]["rank"]["data_loaded"] is False
    jr = env["data"][0]["journal_rank"]
    # No SJR partition (no cache) but the open impact is present in journal_rank.
    assert jr is not None and jr["sjr"] is None
    assert jr["openalex"]["mean_citedness_2yr"] == 2.72
    assert env["meta"]["enrichment"]["impact_source"] == "openalex_summary_stats"
    print("OK  agent_search_no_rank_cache_degrades_gracefully")


def test_agent_search_envelope_json_safe_single_layer():
    papers = [_mk("10.1/jpsp", "prospect theory", "0022-3514", 5000, "W1")]
    with _patched(*_oa_search_targets(papers)):
        env = agent_search.run_agent_search(
            "prospect theory", _cfg(), per_strategy=10,
            verify=True, now_year=2026,
        )
    json.dumps(env)  # must not raise
    print("OK  agent_search_envelope_json_safe_single_layer")


# ===========================================================================
# SS-primary ISSN backfill (R-08, open item #3) — agent_search integration.
# SS records carry ISSN only ~2/3 of the time. For relevance-survivors that
# lack an ISSN but have a DOI, agent_search does a FREE OpenAlex single-paper
# lookup to backfill source.issn so the SJR join is not silently lost. Papers
# with no DOI stay unjoinable. All network is stubbed (no live API).
# ===========================================================================


def _ss_cfg():
    c = Config()
    c.primary_source = "semantic_scholar"
    c.semantic_scholar_api_key = "KEY"
    c.openalex_api_key = "k"
    c.openalex_email = "e@x.com"
    return c


def _mk_ss(doi, title, issn, cites):
    """A Semantic-Scholar-origin entity (sources=['semantic_scholar']), issn may
    be None to model the ~1/3 of SS records without publicationVenue.issn."""
    return UnifiedPaperEntity(
        doi=doi, title=title, abstract=title, year=2024, citation_count=cites,
        issn=issn, authors=[Author(name="A. One")], sources=["semantic_scholar"],
    )


def _ss_primary_targets(ss_papers, oa_get_work):
    """Stub SS as primary: SS key present, SS search returns ss_papers, OA
    get_work backfills ISSN, OA impact + quota stubbed, journal_rank.load returns
    the single-layer fake lookup. No network."""
    return [
        (quota_guard, "evaluate", lambda c, mode="probe", **kw: _FakeQuota()),
        (agent_search.ss_helper, "init", lambda cfg: None),
        (agent_search.ss_helper, "_api_key_from_config", lambda: "KEY"),
        (agent_search.ss_helper, "search", lambda q, **kw: list(ss_papers)),
        (openalex_helper, "init_pyalex", lambda c: None),
        (openalex_helper, "get_work", oa_get_work),
        (openalex_helper, "get_source_impact", _fake_impact),
        (agent_search.journal_rank, "load", lambda **kw: _rank_lookup()),
    ]


def test_ss_primary_backfills_issn_then_joins_rank():
    """SS paper has a DOI but NO ISSN -> OA get_work backfills 0022-3514 ->
    the journal_rank SJR Q1 join + OpenAlex impact succeed (no silent loss)."""
    ss_papers = [_mk_ss("10.1/jpsp", "prospect theory psychology", None, 5000)]

    def fake_get_work(doi):
        # Model the free OA lookup returning the journal's ISSN for this DOI.
        return UnifiedPaperEntity(doi=doi, title="jpsp", issn="0022-3514")

    with _patched(*_ss_primary_targets(ss_papers, fake_get_work)):
        env = agent_search.run_agent_search(
            "prospect theory", _ss_cfg(), per_strategy=10, now_year=2026
        )
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "semantic_scholar"
    assert "journal_metric" not in env["data"][0]
    jr = env["data"][0]["journal_rank"]
    assert jr is not None and jr["sjr"]["best_quartile"] == "Q1"
    # Impact reachable because a backfilled ISSN enabled the OA impact lookup.
    assert jr["openalex"]["mean_citedness_2yr"] == 2.72
    en = env["meta"]["enrichment"]
    assert en["issn_backfill_attempted"] == 1
    assert en["issn_backfilled"] == 1
    print("OK  ss_primary_backfills_issn_then_joins_rank")


def test_ss_primary_no_doi_stays_unjoinable():
    """SS paper with NO DOI cannot be backfilled -> journal_rank stays None (gap
    kept visible, not silently joined). No OA get_work call is even attempted."""
    ss_papers = [_mk_ss(None, "prospect theory unknown venue", None, 30)]
    calls = {"n": 0}

    def fake_get_work(doi):
        calls["n"] += 1
        return UnifiedPaperEntity(doi=doi, title="x", issn="0022-3514")

    with _patched(*_ss_primary_targets(ss_papers, fake_get_work)):
        env = agent_search.run_agent_search(
            "prospect theory", _ss_cfg(), per_strategy=10, now_year=2026
        )
    assert env["ok"] is True
    assert env["data"][0]["journal_rank"] is None  # unjoinable -> None (R-19 shape)
    assert calls["n"] == 0  # no DOI -> no lookup attempted
    en = env["meta"]["enrichment"]
    assert en["issn_backfill_attempted"] == 0
    assert en["issn_backfilled"] == 0
    print("OK  ss_primary_no_doi_stays_unjoinable")


def test_ss_primary_backfill_failure_is_graceful():
    """OA get_work raising must NOT crash the search; the paper just stays
    unjoined and the attempted-but-not-backfilled gap is counted."""
    ss_papers = [_mk_ss("10.9/err", "prospect theory error case", None, 100)]

    def boom(doi):
        raise RuntimeError("OpenAlex down")

    with _patched(*_ss_primary_targets(ss_papers, boom)):
        env = agent_search.run_agent_search(
            "prospect theory", _ss_cfg(), per_strategy=10, now_year=2026
        )
    assert env["ok"] is True  # graceful — no crash
    assert env["data"][0]["journal_rank"] is None
    en = env["meta"]["enrichment"]
    assert en["issn_backfill_attempted"] == 1
    assert en["issn_backfilled"] == 0
    print("OK  ss_primary_backfill_failure_is_graceful")


def test_ss_primary_no_issn_backfill_flag_skips_lookup():
    """issn_backfill=False (the --no-issn-backfill flag, P2): even a perfect
    backfill candidate (DOI present, ISSN missing) gets NO OpenAlex lookup; the
    paper stays unjoinable and the audit reports the disabled gate. Other SS-primary
    behaviour is unchanged."""
    ss_papers = [_mk_ss("10.1/jpsp", "prospect theory psychology", None, 5000)]
    calls = {"n": 0}

    def fake_get_work(doi):
        calls["n"] += 1
        return UnifiedPaperEntity(doi=doi, title="jpsp", issn="0022-3514")

    with _patched(*_ss_primary_targets(ss_papers, fake_get_work)):
        env = agent_search.run_agent_search(
            "prospect theory", _ss_cfg(), per_strategy=10,
            issn_backfill=False, now_year=2026,
        )
    assert env["ok"] is True
    assert env["meta"]["source_used"] == "semantic_scholar"
    # No ISSN was recovered -> no journal_rank join -> stays None (gap kept visible).
    assert env["data"][0]["journal_rank"] is None
    assert calls["n"] == 0  # the OA lookup was NOT attempted
    en = env["meta"]["enrichment"]
    assert en["issn_backfill_enabled"] is False
    assert en["issn_backfill_attempted"] == 0
    assert en["issn_backfilled"] == 0
    print("OK  ss_primary_no_issn_backfill_flag_skips_lookup")


# ===========================================================================
# Runner
# ===========================================================================


def main() -> int:
    tests = [
        test_normalize_issn_strips_hyphen_and_gates_length,
        test_normalize_issns_splits_multi_and_dedupes,
        test_parse_european_float,
        test_parse_categories_multi_quartile,
        test_parse_sjr_csv_skips_no_issn_and_resolves_columns,
        test_blank_best_quartile_derived_from_categories,
        test_join_hyphenated_oa_issn_to_hyphenfree_sjr_key,
        test_quartile_for_category_pin_vs_best,
        test_load_returns_none_when_no_csv,
        test_find_cached_csv_picks_newest,
        test_build_journal_metric_full_join_sets_attribution,
        test_build_journal_metric_missing_issn_flags_backfill,
        test_build_journal_metric_unjoinable_is_empty,
        test_metric_is_empty_contract,
        test_agent_search_fills_journal_rank_sjr_and_openalex,
        test_agent_search_quartile_filter_is_opt_in,
        test_agent_search_min_impact_filter,
        test_agent_search_no_journal_metric_keeps_slots_none,
        test_agent_search_no_rank_cache_degrades_gracefully,
        test_agent_search_envelope_json_safe_single_layer,
        test_ss_primary_backfills_issn_then_joins_rank,
        test_ss_primary_no_doi_stays_unjoinable,
        test_ss_primary_backfill_failure_is_graceful,
        test_ss_primary_no_issn_backfill_flag_skips_lookup,
    ]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            import traceback

            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed.append(t.__name__)
    print()
    print(f"Ran {len(tests)} tests — {len(tests) - len(failed)} pass / {len(failed)} fail")
    if failed:
        print("Failures:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
