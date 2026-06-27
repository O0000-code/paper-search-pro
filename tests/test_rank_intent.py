"""Tests for scripts/rank_intent.py — query-intent recognition (Wave A-2).

Pure + network-free: the parser is regex over the query string. We cover the bug
fix (rank phrasing stripped from the topic), Chinese + English phrasing, every
platform, and the bare-quartile ambiguity rule.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_rank_intent
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_rank_intent.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.rank_intent import parse_rank_intent  # noqa: E402


# ---------------------------------------------------------------------------
# The bug fix: rank phrasing must be stripped from the search topic.
# ---------------------------------------------------------------------------


def test_cas_tier1_chinese_strips_phrase():
    r = parse_rank_intent("中科院一区 情绪调节")
    assert r.platform == "cas"
    assert r.tiers == [1]
    assert r.quartiles is None
    assert r.cleaned_query == "情绪调节"  # the core bug fix
    assert r.ambiguous is False
    print("OK  cas_tier1_chinese_strips_phrase")


def test_cas_multi_tier_chinese():
    r = parse_rank_intent("中科院一二区 工作记忆")
    assert r.platform == "cas"
    assert r.tiers == [1, 2]
    assert r.cleaned_query == "工作记忆"
    print("OK  cas_multi_tier_chinese")


def test_cas_arabic_numeral_tier():
    r = parse_rank_intent("1区 注意力")
    assert r.platform == "cas"
    assert r.tiers == [1]
    assert r.cleaned_query == "注意力"
    print("OK  cas_arabic_numeral_tier")


def test_cas_word_only_no_tier_is_platform_hint():
    r = parse_rank_intent("中科院 emotion regulation")
    assert r.platform == "cas"
    assert r.tiers is None
    assert r.has_filter is False  # platform hint, no tier filter
    assert r.cleaned_query == "emotion regulation"
    print("OK  cas_word_only_no_tier_is_platform_hint")


# ---------------------------------------------------------------------------
# JCR / SJR explicit platform + quartile.
# ---------------------------------------------------------------------------


def test_jcr_quartile_english():
    r = parse_rank_intent("JCR Q1 depression")
    assert r.platform == "jcr"
    assert r.quartiles == ["Q1"]
    assert r.tiers is None
    assert r.cleaned_query == "depression"
    assert r.ambiguous is False
    print("OK  jcr_quartile_english")


def test_sjr_quartile_english():
    r = parse_rank_intent("SJR Q1 anxiety")
    assert r.platform == "sjr"
    assert r.quartiles == ["Q1"]
    assert r.cleaned_query == "anxiety"
    print("OK  sjr_quartile_english")


def test_jcr_with_chinese_qu_numeral_maps_to_quartile():
    # "JCR 1区" -> platform jcr, the 区 numeral maps to Q1.
    r = parse_rank_intent("JCR 1区 fMRI")
    assert r.platform == "jcr"
    assert r.quartiles == ["Q1"]
    assert r.tiers is None  # jcr taxonomy is quartiles, not 区
    assert r.cleaned_query == "fMRI"
    print("OK  jcr_with_chinese_qu_numeral_maps_to_quartile")


# ---------------------------------------------------------------------------
# Ambiguity: a bare quartile with no platform.
# ---------------------------------------------------------------------------


def test_bare_quartile_is_ambiguous():
    r = parse_rank_intent("Q1 attention")
    assert r.platform is None
    assert r.quartiles == ["Q1"]
    assert r.ambiguous is True  # must NOT guess a platform
    assert r.cleaned_query == "attention"
    print("OK  bare_quartile_is_ambiguous")


# ---------------------------------------------------------------------------
# "top" / 顶刊.
# ---------------------------------------------------------------------------


def test_top_chinese_and_english():
    r1 = parse_rank_intent("顶刊 prospect theory")
    assert r1.top is True
    assert r1.platform is None  # top alone names no platform
    assert r1.cleaned_query == "prospect theory"

    r2 = parse_rank_intent("top-tier journals on memory")
    assert r2.top is True
    assert "memory" in r2.cleaned_query
    print("OK  top_chinese_and_english")


# ---------------------------------------------------------------------------
# No rank phrasing at all -> identity (this is what keeps the default path
# byte-identical in agent_search, R-19).
# ---------------------------------------------------------------------------


def test_plain_query_is_identity():
    r = parse_rank_intent("机器学习 综述")
    assert r.platform is None
    assert r.tiers is None and r.quartiles is None
    assert r.top is False
    assert r.ambiguous is False
    assert r.cleaned_query == "机器学习 综述"  # unchanged
    assert r.has_filter is False
    print("OK  plain_query_is_identity")


def test_empty_query():
    r = parse_rank_intent("")
    assert r.platform is None and r.cleaned_query == ""
    r2 = parse_rank_intent(None)  # type: ignore
    assert r2.platform is None and r2.cleaned_query == ""
    print("OK  empty_query")


def test_cas_word_with_cas_prefix_and_space():
    r = parse_rank_intent("cas 1 区 reading comprehension")
    assert r.platform == "cas"
    assert r.tiers == [1]
    assert "reading comprehension" in r.cleaned_query
    print("OK  cas_word_with_cas_prefix_and_space")


# ---------------------------------------------------------------------------
# P1-A regression: no false-positive substring matches (R-19 red line).
#
# The platform keywords (cas/wos/jcr/sjr/...) must match as WHOLE tokens, never as
# substrings inside ordinary English words, and a bare "N区" must only fire as a
# standalone partition token — never glued inside a compound (第一区域 / 三区制 /
# 二区供暖 / 第三区块链 / 社区 / 经济特区). For any query with NO real partition
# intent, ``cleaned_query`` MUST equal the original query byte-for-byte and no
# platform may be guessed. (This is the bug the two A-line reviews flagged: a bare
# substring match corrupted the search term that was actually sent to the engine —
# "case study" -> "e study", "broadcast" -> "broad t".)
# ---------------------------------------------------------------------------

# Every entry here is a legitimate topic that merely CONTAINS a platform/tier
# substring. None of them expresses a journal-rank filter.
_NO_INTENT_QUERIES = [
    # English topics containing a Latin platform substring.
    "case study of teacher burnout",
    "broadcast media",
    "broadcast journalism ethics",
    "forecasting models",
    "showcase of methods",
    "cascade models",
    "SJR-indexed",  # hyphen-joined compound -> NOT a standalone platform hint
    # Chinese compounds containing "数字+区" but NOT a partition.
    "第一区域的人口研究",
    "三区制",
    "三区制供热系统",
    "二区供暖",
    "二区供暖 能耗",
    "第三区块链",
    "一区一带 倡议",
    # Chinese compounds containing "区" but no numeral (already safe, locked anyway).
    "社区研究",
    "社区心理学",
    "地区差异研究",
    "经济特区",
    "经济特区政策",
    "湾区发展",
]


def test_no_false_positive_substring_pollution():
    """No-intent queries must come back byte-identical with no platform guessed.

    Locks the two reviews' false-positive examples: the Latin keywords are
    whole-token, the bare N区 only fires as a standalone partition token."""
    for q in _NO_INTENT_QUERIES:
        r = parse_rank_intent(q)
        assert r.platform is None, f"{q!r}: wrongly guessed platform {r.platform!r}"
        assert r.has_filter is False, f"{q!r}: wrongly set a tier/quartile/top filter"
        assert r.ambiguous is False, f"{q!r}: wrongly flagged ambiguous"
        assert r.tiers is None and r.quartiles is None, f"{q!r}: leaked tiers/quartiles"
        # The R-19 invariant: the engine must receive the ORIGINAL query, unchanged.
        assert r.cleaned_query == q, (
            f"{q!r}: cleaned_query corrupted to {r.cleaned_query!r}"
        )
    print("OK  no_false_positive_substring_pollution")


def test_real_intent_still_parses_after_boundary_hardening():
    """The genuine partition phrasings must still be recognised + stripped."""
    cases = [
        # (query, platform, tiers, quartiles, cleaned)
        ("中科院一区 情绪调节", "cas", [1], None, "情绪调节"),
        ("中科院1区 working memory", "cas", [1], None, "working memory"),
        ("中科院一二区 工作记忆", "cas", [1, 2], None, "工作记忆"),
        ("一区 注意力", "cas", [1], None, "注意力"),
        ("一二区 depression", "cas", [1, 2], None, "depression"),
        ("一区二区 个体差异", "cas", [1, 2], None, "个体差异"),  # consecutive tiers chain
        ("三区期刊 心理学", "cas", [3], None, "心理学"),  # journal-context confirms intent
        ("JCR Q1 depression", "jcr", None, ["Q1"], "depression"),
        ("SJR Q1 anxiety", "sjr", None, ["Q1"], "anxiety"),
        ("JCR 1区 fMRI", "jcr", None, ["Q1"], "fMRI"),
        ("cas 1 区 reading comprehension", "cas", [1], None, "reading comprehension"),
    ]
    for q, plat, tiers, quarts, cleaned in cases:
        r = parse_rank_intent(q)
        assert r.platform == plat, f"{q!r}: platform {r.platform!r} != {plat!r}"
        assert r.tiers == tiers, f"{q!r}: tiers {r.tiers!r} != {tiers!r}"
        assert r.quartiles == quarts, f"{q!r}: quartiles {r.quartiles!r} != {quarts!r}"
        assert r.cleaned_query == cleaned, f"{q!r}: cleaned {r.cleaned_query!r} != {cleaned!r}"
    # A bare Latin platform word used as a research TOPIC (no tier/quartile, no top,
    # not followed by 分区) is left untouched — it is NOT a platform hint. This
    # reverses the earlier "stripping is INTENDED" stance, which corrupted the search
    # term for bibliometric topics (review_A_alpha P1-① / review2 P2-2).
    r = parse_rank_intent("WoS coverage")
    assert r.platform is None and r.has_filter is False and r.cleaned_query == "WoS coverage"
    # But a standalone platform word DOES resolve when it sits in a real partition
    # context (followed by 分区, or co-occurring with top-journal intent).
    r = parse_rank_intent("JCR 顶刊 protein structure")
    assert r.platform == "jcr" and r.top is True and r.ambiguous is False
    assert r.cleaned_query == "protein structure"
    # A bare "Q1" with no platform is still ambiguous (must not guess).
    r = parse_rank_intent("Q1 attention")
    assert r.platform is None and r.ambiguous is True and r.cleaned_query == "attention"
    print("OK  real_intent_still_parses_after_boundary_hardening")


# ---------------------------------------------------------------------------
# F1 fix #1: top-only with no platform must NOT be silently dropped.
#
# Before the fix, "顶刊 protein" stripped "顶刊" out of the search query but left
# top=False / ambiguous=False, so the headless path neither filtered nor asked —
# the intent simply vanished (the exact anti-goal this feature exists to kill).
# Now top-only-no-platform mirrors a bare quartile: ambiguous=True + candidates.
# ---------------------------------------------------------------------------


def test_top_only_no_platform_is_ambiguous():
    r = parse_rank_intent("顶刊 protein")
    assert r.top is True
    assert r.platform is None  # top alone names no platform
    assert r.ambiguous is True  # must NOT silently drop — flag for the caller to ask
    assert r.has_filter is True  # top IS a stated filter intent
    assert r.cleaned_query == "protein"  # the topic survives, 顶刊 stripped
    # candidate_platforms lets the caller ask "which platform?" (top exists on all 3).
    assert r.candidate_platforms == ["cas", "jcr", "sjr"]

    # English form behaves identically.
    r2 = parse_rank_intent("top journals on working memory")
    assert r2.top is True and r2.platform is None and r2.ambiguous is True
    assert r2.candidate_platforms == ["cas", "jcr", "sjr"]
    print("OK  top_only_no_platform_is_ambiguous")


def test_top_only_filler_words_stripped_cleanly():
    """'只要顶刊的X' / '只要顶刊 X' must strip to a clean topic — no 只要/的 residue."""
    r = parse_rank_intent("只要顶刊的认知")
    assert r.top is True and r.platform is None and r.ambiguous is True
    assert r.cleaned_query == "认知"  # not "只要 的认知"

    r2 = parse_rank_intent("只要顶刊 transformer")
    assert r2.top is True and r2.cleaned_query == "transformer"  # not "只要 transformer"

    # When a platform word is present, the filler/的 still strip cleanly and the
    # platform resolves (not ambiguous).
    r3 = parse_rank_intent("只要中科院顶刊的情绪调节")
    assert r3.platform == "cas" and r3.top is True and r3.ambiguous is False
    assert r3.cleaned_query == "情绪调节"
    print("OK  top_only_filler_words_stripped_cleanly")


# ---------------------------------------------------------------------------
# F1 fix #2: bare Latin platform words used as research TOPICS must not be
# stripped / mistaken for a platform. Bibliometric queries about WoS/Scopus/etc.
# were being bisected ("Web of Science coverage analysis" -> "coverage analysis").
# Red line: when the platform word is the topic, cleaned_query == query byte-for-
# byte, no platform guessed, has_filter False.
# ---------------------------------------------------------------------------

_PLATFORM_AS_TOPIC_QUERIES = [
    "Web of Science coverage analysis",
    "WoS coverage",
    "Scopus database comparison",
    "Scopus vs WoS comparison",
    "Web of Science vs Scopus database overlap",
    "CAS registry number lookup",
    "SJR indexing methodology",
    "clarivate analytics market report",
    "scimago journal ranking methodology",
    "JCR coverage of open access journals",
]


def test_latin_platform_word_as_topic_is_not_stripped():
    for q in _PLATFORM_AS_TOPIC_QUERIES:
        r = parse_rank_intent(q)
        assert r.platform is None, f"{q!r}: wrongly guessed platform {r.platform!r}"
        assert r.has_filter is False, f"{q!r}: wrongly set a filter"
        assert r.ambiguous is False, f"{q!r}: wrongly flagged ambiguous"
        assert r.cleaned_query == q, (
            f"{q!r}: topic corrupted to {r.cleaned_query!r} (must be byte-identical)"
        )
    print("OK  latin_platform_word_as_topic_is_not_stripped")


def test_platform_word_resolves_only_in_partition_context():
    """The flip side: a standalone platform word DOES resolve when partition intent
    is present (followed by 分区, or co-occurring with top-journal intent)."""
    # co-occurring top intent -> platform resolves, not ambiguous.
    r = parse_rank_intent("JCR 顶刊 protein structure")
    assert r.platform == "jcr" and r.top is True and r.ambiguous is False
    assert r.cleaned_query == "protein structure"

    r = parse_rank_intent("SJR 顶刊 climate change")
    assert r.platform == "sjr" and r.top is True and r.cleaned_query == "climate change"

    # followed by 分区 -> platform hint, stripped cleanly (no dangling 分区).
    r = parse_rank_intent("Web of Science 分区 心理学")
    assert r.platform == "jcr" and r.has_filter is False and r.cleaned_query == "心理学"

    r = parse_rank_intent("cas 分区 材料科学")
    assert r.platform == "cas" and r.has_filter is False and r.cleaned_query == "材料科学"

    # CJK 中科院 keeps its substring-hint semantics (unchanged).
    r = parse_rank_intent("中科院顶刊 emotion regulation")
    assert r.platform == "cas" and r.top is True and r.ambiguous is False
    assert r.cleaned_query == "emotion regulation"
    print("OK  platform_word_resolves_only_in_partition_context")


def main() -> int:
    tests = [
        test_cas_tier1_chinese_strips_phrase,
        test_cas_multi_tier_chinese,
        test_cas_arabic_numeral_tier,
        test_cas_word_only_no_tier_is_platform_hint,
        test_jcr_quartile_english,
        test_sjr_quartile_english,
        test_jcr_with_chinese_qu_numeral_maps_to_quartile,
        test_bare_quartile_is_ambiguous,
        test_top_chinese_and_english,
        test_plain_query_is_identity,
        test_empty_query,
        test_cas_word_with_cas_prefix_and_space,
        test_no_false_positive_substring_pollution,
        test_real_intent_still_parses_after_boundary_hardening,
        test_top_only_no_platform_is_ambiguous,
        test_top_only_filler_words_stripped_cleanly,
        test_latin_platform_word_as_topic_is_not_stripped,
        test_platform_word_resolves_only_in_partition_context,
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
