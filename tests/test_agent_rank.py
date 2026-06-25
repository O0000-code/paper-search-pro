"""Tests for agent_search's multi-platform journal-RANK integration (Wave A-2).

Network-free: the OpenAlex/SS retrieval backends, the quota probe, AND
journal_rank.load are monkeypatched with fakes, so the rank annotate / filter /
adaptive-deepening / switch / ambiguity / degrade paths are exercised without
touching the network or the real ranking cache.

Covers (spec §5/§6/§7):
  - NL intent strips the rank phrasing from the search topic + filters (the bug).
  - explicit --rank-platform / --keep-tiers flags.
  - adaptive deepening: first pass short on survivors -> deeper re-retrieve.
  - switch = re-filter the annotated pool (no re-search).
  - bare-quartile ambiguity -> flagged, NOT filtered.
  - no cached rank data -> graceful degrade (labels None, run still ok).
  - default platform LABELS but does not FILTER.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_agent_rank
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_agent_rank.py -q
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import agent_search  # noqa: E402
from scripts.journal_rank import normalize_issns  # noqa: E402
from scripts.types import (  # noqa: E402
    Author,
    CASRank,
    Config,
    JCRRank,
    JournalRank,
    SJRRank,
    UnifiedPaperEntity,
)


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


class _FakeQuota:
    ok = True
    should_switch = False
    remaining_usd = 0.9

    def to_dict(self):
        return {"ok": True, "remaining_usd": 0.9, "mode": "probe"}


class _FakeLookup:
    """In-memory ISSN -> JournalRank table + lookup()/loaded_platforms."""

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


def _two_journal_lookup():
    return _FakeLookup(
        {
            "0022-3514": JournalRank(
                title="JPSP", issns=["0022-3514"],
                cas=CASRank(tier=1, rank="5/100", top=True, source_year=2025),
                jcr=JCRRank(quartile="Q1", impact_factor=7.6, source_year=2024),
                sjr=SJRRank(best_quartile="Q1", sjr=5.1, source_year=2024),
                matched_platforms=["cas", "jcr", "sjr"],
            ),
            "1234-5678": JournalRank(
                title="MidJ", issns=["1234-5678"],
                cas=CASRank(tier=3, rank="80/100", top=False, source_year=2025),
                matched_platforms=["cas"],
            ),
        }
    )


def _paper(doi, title, issn, cites):
    return UnifiedPaperEntity(
        doi=doi, title=title, abstract=title, year=2024, citation_count=cites,
        issn=issn, authors=[Author(name="A")], sources=["openalex"],
    )


def _cfg(default_platform=None):
    c = Config()
    c.primary_source = "openalex"
    c.openalex_api_key = "k"
    c.openalex_email = "e@x.com"
    if default_platform:
        c.rank = {"default_platform": default_platform}
    return c


def _oa_targets(papers_by_sort, lookup):
    def fake_search(query, total_papers=50, sort="cited_by_count:desc", year_min=None, year_max=None):
        return list(papers_by_sort.get(sort, []))[:total_papers]

    return [
        (agent_search.openalex_helper, "search_top_n_pages", fake_search),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.openalex_helper, "get_source_impact", lambda issn: None),
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (agent_search.journal_rank, "load", lambda **kw: lookup),
    ]


# ---------------------------------------------------------------------------
# 1. NL intent: strip the phrase from the topic + filter to the tier (the bug).
# ---------------------------------------------------------------------------


def test_intent_strips_phrase_and_filters_cas_tier1():
    papers = [
        _paper("10.1/jpsp", "emotion regulation study", "0022-3514", 5000),
        _paper("10.2/mid", "emotion regulation mid", "1234-5678", 50),
    ]
    targets = _oa_targets({"cited_by_count:desc": papers}, _two_journal_lookup())
    with _patched(*targets):
        env = agent_search.run_agent_search("中科院一区 情绪调节", _cfg(), per_strategy=10, now_year=2026)
    assert env["ok"] is True
    # The rank phrasing was stripped: the search ran on "情绪调节", not "中科院一区...".
    assert env["meta"]["query"]["search_query"] == "情绪调节"
    r = env["meta"]["rank"]
    assert r["platform"] == "cas" and r["platform_source"] == "intent"
    assert r["keep_tiers"] == [1]
    assert r["applied_filter"] is True
    assert r["kept"] == 1 and r["filtered"] == 1 and r["no_platform_data"] == 0
    # Only the tier-1 journal survives.
    assert [d["doi"] for d in env["data"]] == ["10.1/jpsp"]
    # The unified journal_rank dict is attached.
    assert env["data"][0]["journal_rank"]["cas"]["tier"] == 1
    # switching is a re-filter, not a re-search.
    assert r["switch_is_refilter_not_research"] is True
    assert set(r["switchable_platforms"]) == {"cas", "jcr", "sjr"}
    print("OK  intent_strips_phrase_and_filters_cas_tier1")


# ---------------------------------------------------------------------------
# 2. Explicit flags.
# ---------------------------------------------------------------------------


def test_explicit_flags_filter_jcr_q1():
    papers = [
        _paper("10.1/jpsp", "anxiety study", "0022-3514", 5000),  # jcr Q1
        _paper("10.2/mid", "anxiety mid", "1234-5678", 50),       # not on jcr
    ]
    targets = _oa_targets({"cited_by_count:desc": papers}, _two_journal_lookup())
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "anxiety", _cfg(), per_strategy=10,
            rank_platform="jcr", keep_tiers=["Q1"], now_year=2026,
        )
    r = env["meta"]["rank"]
    assert r["platform"] == "jcr" and r["platform_source"] == "flags"
    assert r["keep_quartiles"] == ["Q1"]
    assert r["kept"] == 1 and r["no_platform_data"] == 1  # MidJ counted, not dropped
    assert [d["doi"] for d in env["data"]] == ["10.1/jpsp"]
    assert env["data"][0]["journal_rank"]["jcr"]["impact_factor"] == 7.6
    print("OK  explicit_flags_filter_jcr_q1")


# ---------------------------------------------------------------------------
# 2b. --rank-category actually filters end-to-end (P1-B: was空转 before).
# ---------------------------------------------------------------------------


def test_rank_category_filters_on_cas_minor_tier():
    # MatJ: CAS 大类 区2, but 小类 "材料科学" 区1. Without a category pin a tier=[1]
    # filter drops it; pinned to 材料科学 it is 区1 and survives. This proves the
    # flag is no longer a no-op (it reaches filter_by_rank and changes the result).
    matj = JournalRank(
        title="MatJ", issns=["2000-0001"],
        cas=CASRank(
            tier=2, rank="40/300", top=False, source_year=2025,
            minor=[{"category": "材料科学:综合", "tier": 1, "rank": "5/300"}],
        ),
        matched_platforms=["cas"],
    )
    lookup = _FakeLookup({"2000-0001": matj}, loaded=("cas",))
    papers = [_paper("10.1/mat", "battery materials", "2000-0001", 900)]

    # (a) no category pin: 大类 is 区2 -> tier=[1] drops it.
    targets = _oa_targets({"cited_by_count:desc": papers}, lookup)
    with _patched(*targets):
        env_no_cat = agent_search.run_agent_search(
            "battery materials", _cfg(), per_strategy=10,
            rank_platform="cas", keep_tiers=["1"], now_year=2026,
        )
    assert env_no_cat["meta"]["rank"]["kept"] == 0
    assert env_no_cat["data"] == []

    # (b) category pin 材料科学: 小类 is 区1 -> survives.
    targets = _oa_targets({"cited_by_count:desc": papers}, lookup)
    with _patched(*targets):
        env_cat = agent_search.run_agent_search(
            "battery materials", _cfg(), per_strategy=10,
            rank_platform="cas", keep_tiers=["1"], rank_category="材料科学", now_year=2026,
        )
    r = env_cat["meta"]["rank"]
    assert r["category"] == "材料科学"
    assert r["kept"] == 1
    assert [d["doi"] for d in env_cat["data"]] == ["10.1/mat"]
    print("OK  rank_category_filters_on_cas_minor_tier")


# ---------------------------------------------------------------------------
# 3. Adaptive deepening: first pass short -> deeper re-retrieve finds survivors.
# ---------------------------------------------------------------------------


def test_adaptive_deepening_finds_more_survivors():
    # 4 tier-1 journals + 16 tier-3; the two extra tier-1 are placed deep so the
    # shallow first pass misses them and deepening is required.
    table = {}
    for i in range(1, 21):
        issn = f"{i:04d}-000X"
        tier = 1 if i <= 4 else 3
        table[issn] = JournalRank(
            title=f"J{i}", issns=[issn],
            cas=CASRank(tier=tier, top=(tier == 1), source_year=2025),
            matched_platforms=["cas"],
        )
    lookup = _FakeLookup(table, loaded=("cas",))

    papers = [_paper(f"10.x/{i}", f"memory {i}", f"{i:04d}-000X", 1000 - i) for i in range(1, 21)]
    # Order so tier-1 #3,#4 sit at the very end -> only reachable by deepening.
    ordered = [papers[0], papers[1]] + papers[4:] + [papers[2], papers[3]]

    def fake_search(query, total_papers=50, sort="cited_by_count:desc", year_min=None, year_max=None):
        if sort != "cited_by_count:desc":
            return []
        return ordered[:total_papers]

    targets = [
        (agent_search.openalex_helper, "search_top_n_pages", fake_search),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.openalex_helper, "get_source_impact", lambda issn: None),
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (agent_search.journal_rank, "load", lambda **kw: lookup),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "memory", _cfg(), per_strategy=4,
            rank_platform="cas", keep_tiers=["1"], deepen_target=4, now_year=2026,
        )
    r = env["meta"]["rank"]
    assert r["deepen"]["active"] is True
    assert r["deepen"]["rounds"] >= 1  # it had to deepen at least once
    assert r["kept"] == 4
    assert sorted(d["doi"] for d in env["data"]) == ["10.x/1", "10.x/2", "10.x/3", "10.x/4"]
    print("OK  adaptive_deepening_finds_more_survivors")


def test_deepening_saturates_when_no_new_papers():
    # Only 1 tier-1 exists; target 5 can never be met -> deepening saturates and
    # stops rather than looping forever.
    table = {
        "0001-000X": JournalRank(title="T1", issns=["0001-000X"], cas=CASRank(tier=1, top=True, source_year=2025), matched_platforms=["cas"]),
        "0002-000X": JournalRank(title="T3", issns=["0002-000X"], cas=CASRank(tier=3, source_year=2025), matched_platforms=["cas"]),
    }
    lookup = _FakeLookup(table, loaded=("cas",))
    papers = [
        _paper("10.x/1", "reading 1", "0001-000X", 500),
        _paper("10.x/2", "reading 2", "0002-000X", 400),
    ]

    def fake_search(query, total_papers=50, sort="cited_by_count:desc", year_min=None, year_max=None):
        return papers if sort == "cited_by_count:desc" else []

    targets = [
        (agent_search.openalex_helper, "search_top_n_pages", fake_search),
        (agent_search.openalex_helper, "init_pyalex", lambda cfg: None),
        (agent_search.openalex_helper, "get_source_impact", lambda issn: None),
        (agent_search.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (agent_search.journal_rank, "load", lambda **kw: lookup),
    ]
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "reading", _cfg(), per_strategy=2,
            rank_platform="cas", keep_tiers=["1"], deepen_target=5,
            max_deepen_rounds=5, now_year=2026,
        )
    r = env["meta"]["rank"]
    assert r["kept"] == 1  # only the one tier-1 exists
    assert r["deepen"]["saturated"] is True  # gave up cleanly
    assert r["deepen"]["rounds"] >= 1
    print("OK  deepening_saturates_when_no_new_papers")


# ---------------------------------------------------------------------------
# 4. Ambiguity: bare "Q1" with no platform -> flagged, NOT filtered.
# ---------------------------------------------------------------------------


def test_bare_quartile_is_ambiguous_and_not_filtered():
    papers = [
        _paper("10.1/jpsp", "depression study", "0022-3514", 5000),
        _paper("10.2/mid", "depression mid", "1234-5678", 50),
    ]
    targets = _oa_targets({"cited_by_count:desc": papers}, _two_journal_lookup())
    with _patched(*targets):
        env = agent_search.run_agent_search("Q1 depression", _cfg(), per_strategy=10, now_year=2026)
    r = env["meta"]["rank"]
    assert r["ambiguous"] is True
    assert set(r["candidate_platforms"]) == {"jcr", "sjr"}
    assert r["applied_filter"] is False  # never filters without a resolved platform
    assert env["meta"]["query"]["search_query"] == "depression"
    # Both papers returned (no filter); both still labelled where data joins.
    assert len(env["data"]) == 2
    print("OK  bare_quartile_is_ambiguous_and_not_filtered")


# ---------------------------------------------------------------------------
# 5. Graceful degrade: no cached rank data.
# ---------------------------------------------------------------------------


def test_no_rank_cache_degrades_gracefully():
    papers = [_paper("10.1/jpsp", "memory study", "0022-3514", 5000)]
    targets = _oa_targets({"cited_by_count:desc": papers}, None)  # load -> None
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "中科院一区 记忆", _cfg(), per_strategy=10, now_year=2026
        )
    assert env["ok"] is True
    r = env["meta"]["rank"]
    assert r["data_loaded"] is False
    assert r["applied_filter"] is False  # cannot filter without data
    assert r["platform"] == "cas"  # intent still resolved the platform
    assert r["note"] and "journal_rank fetch" in r["note"]
    assert env["data"][0]["journal_rank"] is None  # no labels, but run succeeded
    # The query is still cleaned (the bug fix works even without rank data).
    assert env["meta"]["query"]["search_query"] == "记忆"
    print("OK  no_rank_cache_degrades_gracefully")


# ---------------------------------------------------------------------------
# 6. Default platform LABELS but does not FILTER.
# ---------------------------------------------------------------------------


def test_default_platform_labels_only_no_filter():
    papers = [
        _paper("10.1/jpsp", "cognition study", "0022-3514", 5000),
        _paper("10.2/mid", "cognition mid", "1234-5678", 50),
    ]
    targets = _oa_targets({"cited_by_count:desc": papers}, _two_journal_lookup())
    with _patched(*targets):
        env = agent_search.run_agent_search("cognition", _cfg(default_platform="jcr"), per_strategy=10, now_year=2026)
    r = env["meta"]["rank"]
    assert r["platform"] == "jcr" and r["platform_source"] == "default"
    assert r["applied_filter"] is False
    assert r["kept"] is None  # no filter ran
    # No filter -> both returned, both labelled with the unified dict where joined.
    assert len(env["data"]) == 2
    jpsp = next(d for d in env["data"] if d["doi"] == "10.1/jpsp")
    assert jpsp["journal_rank"]["jcr"]["quartile"] == "Q1"
    print("OK  default_platform_labels_only_no_filter")


def test_envelope_with_rank_is_json_safe():
    import json

    papers = [_paper("10.1/jpsp", "emotion study", "0022-3514", 5000)]
    targets = _oa_targets({"cited_by_count:desc": papers}, _two_journal_lookup())
    with _patched(*targets):
        env = agent_search.run_agent_search(
            "中科院一区 情绪", _cfg(), per_strategy=10, verify=True, now_year=2026
        )
    json.dumps(env)  # must not raise
    print("OK  envelope_with_rank_is_json_safe")


def main() -> int:
    tests = [
        test_intent_strips_phrase_and_filters_cas_tier1,
        test_explicit_flags_filter_jcr_q1,
        test_rank_category_filters_on_cas_minor_tier,
        test_adaptive_deepening_finds_more_survivors,
        test_deepening_saturates_when_no_new_papers,
        test_bare_quartile_is_ambiguous_and_not_filtered,
        test_no_rank_cache_degrades_gracefully,
        test_default_platform_labels_only_no_filter,
        test_envelope_with_rank_is_json_safe,
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
