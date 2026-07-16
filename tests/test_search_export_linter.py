"""Tests for scripts/search_export/linter.py — deterministic L1-L11 checks.

Pure + network-free: reads the in-git syntax cards + proximity table (data files,
no HTTP). Every L-rule gets a trigger AND a non-trigger case (esp. L3's CNKI legal
``*`` = field-internal AND, which must NEVER be mis-flagged), and the three
Design-Spec §1.2 example strategies (PubMed / WoS / CNKI) must all pass clean.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_search_export_linter
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_search_export_linter.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.search_export import linter as lt  # noqa: E402


def _rules(result):
    return sorted({f.rule for f in result.findings})


def _fires(result, rule, level=None):
    fs = result.by_rule(rule)
    if level is not None:
        fs = [f for f in fs if f.level == level]
    return bool(fs)


# ---------------------------------------------------------------------------
# The three Design-Spec §1.2 example strategies must all pass clean.
# ---------------------------------------------------------------------------

PUBMED_EXAMPLE = (
    '("Mindfulness"[Mesh] OR mindfulness[tiab] OR MBSR[tiab] OR MBCT[tiab] OR '
    '"mindfulness based"[tiab])\n'
    "AND\n"
    '("Students"[Mesh] OR "college students"[tiab] OR "university students"[tiab] '
    "OR undergraduates[tiab])\n"
    "AND\n"
    '("Anxiety"[Mesh] OR "Anxiety Disorders"[Mesh] OR anxiety[tiab] OR '
    "anxious[tiab])"
)

WOS_EXAMPLE = (
    "TS=(\n"
    '  ("mindfulness" OR "mindfulness-based" OR MBSR OR MBCT)\n'
    '  AND ("college student*" OR "university student*" OR undergraduate*)\n'
    "  AND (anxiety OR anxious*)\n"
    ")"
)

CNKI_EXAMPLE = (
    "(SU %= '正念' OR SU %= '正念减压' OR SU %= '正念认知')\n"
    "AND (SU %= '大学生' OR SU %= '高校学生' OR SU %= '本科生')\n"
    "AND (SU %= '焦虑' OR SU %= '焦虑症')"
)


def test_spec_examples_pass_clean():
    for q, host in (
        (PUBMED_EXAMPLE, "pubmed"),
        (WOS_EXAMPLE, "wos"),
        (CNKI_EXAMPLE, "cnki"),
    ):
        r = lt.lint(q, host)
        assert r.passed, f"{host} example should pass, got {_rules(r)}"
        assert not r.findings, f"{host} example clean, got {[str(f) for f in r.findings]}"


# ---------------------------------------------------------------------------
# L1 — bracket / quote balance + curly quotes.
# ---------------------------------------------------------------------------


def test_l1_unbalanced_parens_triggers():
    assert _fires(lt.lint("(a[tiab] OR b[tiab]", "pubmed"), "L1", lt.ERROR)
    assert _fires(lt.lint("a[tiab]) OR b[tiab]", "pubmed"), "L1", lt.ERROR)


def test_l1_unbalanced_double_quote_triggers():
    assert _fires(lt.lint('"sleep therapy[tiab]', "pubmed"), "L1", lt.ERROR)


def test_l1_curly_quotes_trigger():
    assert _fires(lt.lint('“mindfulness”[tiab]', "pubmed"), "L1", lt.ERROR)


def test_l1_cnki_unbalanced_single_quote_triggers():
    assert _fires(lt.lint("SU %= '正念", "cnki"), "L1", lt.ERROR)


def test_l1_balanced_does_not_trigger():
    assert not _fires(lt.lint('("a"[tiab] OR "b"[tiab])', "pubmed"), "L1")
    # English apostrophe on a non-single-quote host must NOT trip L1
    assert not _fires(lt.lint("children[tiab]", "pubmed"), "L1")


# ---------------------------------------------------------------------------
# L2 — boolean operator case.
# ---------------------------------------------------------------------------


def test_l2_lowercase_operator_triggers_on_uppercase_host():
    assert _fires(lt.lint("cancer[tiab] and therapy[tiab]", "pubmed"), "L2", lt.ERROR)
    assert _fires(lt.lint("TITLE(cancer) or TITLE(x)", "scopus"), "L2", lt.ERROR)


def test_l2_uppercase_operator_does_not_trigger():
    assert not _fires(lt.lint("cancer[tiab] AND therapy[tiab]", "pubmed"), "L2")


def test_l2_case_insensitive_host_does_not_trigger():
    # WoS is case-insensitive -> lowercase 'and' is not an L2 error.
    assert not _fires(lt.lint("cancer and therapy", "wos"), "L2")


# ---------------------------------------------------------------------------
# L3 — truncation / wildcard by host (incl. CNKI position-based '*').
# ---------------------------------------------------------------------------


def test_l3_pubmed_min_chars_before_star():
    assert _fires(lt.lint("co*[tiab]", "pubmed"), "L3", lt.ERROR)
    assert not _fires(lt.lint("colo*[tiab]", "pubmed"), "L3")


def test_l3_cnki_legal_and_star_not_flagged():
    # '*' between quoted operands is the field-internal AND operator -> legal.
    assert not _fires(lt.lint("FT = '大数据' * '隐私'", "cnki"), "L3")
    assert not _fires(lt.lint("FT='大数据'*'隐私'", "cnki"), "L3")


def test_l3_cnki_word_attached_star_is_truncation_error():
    assert _fires(lt.lint("FT = '大数据*'", "cnki"), "L3", lt.ERROR)


def test_l3_wanfang_star_is_deprecated_warn():
    r = lt.lint("题名:大数据*", "wanfang")
    assert _fires(r, "L3", lt.WARN)
    assert not _fires(r, "L3", lt.ERROR)


def test_l3_wos_dollar_is_zero_or_one_warn():
    r = lt.lint("colo$r", "wos")
    assert _fires(r, "L3", lt.WARN)


def test_l3_unsupported_star_errors():
    # ClinicalTrials.gov Essie has no '*' wildcard -> error.
    assert _fires(lt.lint("cancer*", "clinicaltrials_gov"), "L3", lt.ERROR)


# ---------------------------------------------------------------------------
# L4 — proximity <-> host constraints.
# ---------------------------------------------------------------------------


def test_l4_wos_and_inside_near_parens_triggers():
    assert _fires(lt.lint("Germany NEAR/10 (monetary AND union)", "wos"), "L4", lt.ERROR)


def test_l4_wos_and_outside_near_scope_ok():
    assert not _fires(lt.lint("TS=(cancer AND (a NEAR/3 b))", "wos"), "L4")


def test_l4_pubmed_proximity_with_truncation_triggers():
    assert _fires(lt.lint('"sleep therap*"[tiab:~3]', "pubmed"), "L4", lt.ERROR)


def test_l4_pubmed_proximity_requires_quotes():
    assert _fires(lt.lint("sleep therapy[tiab:~3]", "pubmed"), "L4", lt.ERROR)


def test_l4_pubmed_proximity_clean_ok():
    assert not _fires(lt.lint('"sleep therapy"[tiab:~3]', "pubmed"), "L4")


def test_l4_embase_near_needs_parens():
    assert _fires(lt.lint("'a':ti NEAR/3 'b':ti", "embase_com"), "L4", lt.ERROR)
    assert not _fires(lt.lint("('a' NEAR/3 'b'):ti,ab", "embase_com"), "L4")


def test_l4_ieee_near_with_wildcard_triggers():
    assert _fires(lt.lint("cabl* NEAR/3 fault", "ieee"), "L4", lt.ERROR)


def test_l4_foreign_operator_triggers():
    # Ovid 'adj' operator on a WoS query -> family/syntax mismatch.
    assert _fires(lt.lint("TS=(heart adj2 attack)", "wos"), "L4", lt.ERROR)


# ---------------------------------------------------------------------------
# L5 — illegal / mistyped field tags.
# ---------------------------------------------------------------------------


def test_l5_pubmed_bad_bracket_tag_triggers():
    assert _fires(lt.lint("cancer[tiba]", "pubmed"), "L5", lt.ERROR)


def test_l5_pubmed_mesh_synonym_not_flagged():
    # [Mesh] is a valid MeSH tag synonym (card controlled_vocab name) -> no L5.
    assert not _fires(lt.lint('"Neoplasms"[Mesh]', "pubmed"), "L5")


def test_l5_wos_bad_equals_tag_triggers():
    assert _fires(lt.lint("TX=(cancer)", "wos"), "L5", lt.ERROR)
    assert not _fires(lt.lint("TS=(cancer)", "wos"), "L5")


def test_l5_scopus_bad_paren_tag_triggers():
    assert _fires(lt.lint("TITLX(cancer)", "scopus"), "L5", lt.ERROR)
    assert not _fires(lt.lint("TITLE-ABS-KEY(cancer)", "scopus"), "L5")


# ---------------------------------------------------------------------------
# L6 — residual routing markers.
# ---------------------------------------------------------------------------


def test_l6_cas_tier_marker_triggers():
    assert _fires(lt.lint("正念 中科院一区 焦虑", "cnki"), "L6", lt.ERROR)


def test_l6_quartile_marker_triggers():
    assert _fires(lt.lint("cancer[tiab] AND Q1", "pubmed"), "L6", lt.ERROR)
    assert _fires(lt.lint("cancer[tiab] AND CSSCI", "pubmed"), "L6", lt.ERROR)


def test_l6_clean_query_no_marker():
    assert not _fires(lt.lint("cancer[tiab] AND therapy[tiab]", "pubmed"), "L6")
    # boundary safety: 'forecasting'/'case' must not match cas/Q markers
    assert not _fires(lt.lint("forecasting[tiab] AND case[tiab]", "pubmed"), "L6")


# ---------------------------------------------------------------------------
# L7 — CJK half-width mandate.
# ---------------------------------------------------------------------------


def test_l7_fullwidth_punctuation_triggers():
    assert _fires(lt.lint("SU %= '正念'（OR）", "cnki"), "L7", lt.ERROR)


def test_l7_fullwidth_alnum_triggers():
    assert _fires(lt.lint("YE = '２０２０'", "cnki"), "L7", lt.ERROR)


def test_l7_halfwidth_ok_and_non_cjk_host_skipped():
    assert not _fires(lt.lint(CNKI_EXAMPLE, "cnki"), "L7")
    # A non-half-width-mandate host never runs L7.
    assert not _fires(lt.lint("cancer[tiab]", "pubmed"), "L7")


# ---------------------------------------------------------------------------
# L8 — NOT usage (warn).
# ---------------------------------------------------------------------------


def test_l8_not_operator_warns():
    r = lt.lint("cancer[tiab] NOT benign[tiab]", "pubmed")
    assert _fires(r, "L8", lt.WARN)
    assert r.passed  # warn does not fail the gate


def test_l8_no_not_clean():
    assert not _fires(lt.lint("cancer[tiab] AND therapy[tiab]", "pubmed"), "L8")


# ---------------------------------------------------------------------------
# L9 — CENTRAL + RCT / study-design filter co-occurrence.
# ---------------------------------------------------------------------------


def test_l9_central_with_rct_filter_triggers():
    q = "(cancer):ti,ab AND randomized controlled trial:pt"
    assert _fires(lt.lint(q, "cochrane_central"), "L9", lt.ERROR)


def test_l9_central_with_filters_used_triggers():
    r = lt.lint("(cancer):ti,ab", "cochrane_central", filters_used=["Cochrane-HSSS"])
    assert _fires(r, "L9", lt.ERROR)


def test_l9_central_clean_ok():
    assert not _fires(lt.lint("(cancer):ti,ab AND (therapy):ti,ab",
                              "cochrane_central"), "L9")


def test_l9_non_central_host_never_fires():
    q = "randomized controlled trial[pt] AND cancer[tiab]"
    assert not _fires(lt.lint(q, "pubmed"), "L9")


def test_l9_central_topic_words_not_flagged():
    # FG2 #10 / 26b P3-16: a methods study *about* RCTs / random allocation /
    # double-blind method uses these as TOPIC words (ti/ab) — legitimate on
    # CENTRAL, must NOT be withheld. The old ``sig in low`` substring scan
    # false-flagged every one of these.
    for q in (
        "(random allocation):ti,ab",
        '"double-blind method":ti,ab',
        "randomized controlled trials:ti,ab",
        '("randomized controlled trial" OR "controlled clinical trial"):ti,ab',
        "(single-blind method):ti,ab AND stroke:ti,ab",
    ):
        assert not _fires(lt.lint(q, "cochrane_central"), "L9"), q


def test_l9_central_pubtype_filter_still_caught():
    # The other direction: a real CHSSS fragment binds the trial phrase to a
    # publication-type tag ([pt] / .pt. / [Publication Type]) -> still a filter.
    for q in (
        "(stroke):ti,ab AND randomized controlled trial [pt]",
        "controlled clinical trial.pt.",
        '"randomized controlled trial"[Publication Type]',
    ):
        assert _fires(lt.lint(q, "cochrane_central"), "L9", lt.ERROR), q


def test_l9_central_hsss_marker_caught():
    # A distinctive Cochrane-hedge marker is a filter-only token (never a topic).
    assert _fires(lt.lint("(x):ti,ab AND Cochrane HSSS", "cochrane_central"),
                  "L9", lt.ERROR)


# ---------------------------------------------------------------------------
# L10 — orphan lines.
# ---------------------------------------------------------------------------


def test_l10_orphan_line_warns():
    q = "#1 cancer[tiab]\n#2 therapy[tiab]\n#3 #1"
    r = lt.lint(q, "pubmed")
    assert _fires(r, "L10", lt.WARN)


def test_l10_all_lines_referenced_clean():
    q = "#1 cancer[tiab]\n#2 therapy[tiab]\n#3 #1 AND #2"
    assert not _fires(lt.lint(q, "pubmed"), "L10")


# ---------------------------------------------------------------------------
# L11 — controlled-vocab verification-status stamp.
# ---------------------------------------------------------------------------


def test_l11_missing_status_triggers():
    r = lt.lint("cancer[tiab]", "pubmed",
                vocab_terms=[{"term": "Neoplasms", "vocab": "MeSH"}])
    assert _fires(r, "L11", lt.ERROR)


def test_l11_fake_verify_no_free_api_triggers():
    # Emtree has no free API -> may not be stamped 'verified' (A-6).
    r = lt.lint("x", "embase_com",
                vocab_terms=[{"term": "neoplasm", "vocab": "Emtree",
                              "status": "verified"}])
    assert _fires(r, "L11", lt.ERROR)


def test_l11_mesh_unverified_without_downgrade_triggers():
    r = lt.lint("cancer[tiab]", "pubmed",
                vocab_terms=[{"term": "Bogusterm", "vocab": "MeSH",
                              "status": "llm_suggest_only"}])
    assert _fires(r, "L11", lt.ERROR)


def test_l11_correct_stamps_clean():
    r = lt.lint("cancer[tiab]", "pubmed", vocab_terms=[
        {"term": "Neoplasms", "vocab": "MeSH", "status": "verified"},
        {"term": "Bad", "vocab": "MeSH", "status": "downgraded"},
        {"term": "x", "vocab": "Emtree", "status": "待人工核"},
    ])
    assert not _fires(r, "L11")


def _l11_verdict(vocab, status, host):
    r = lt.lint("x", host, vocab_terms=[{"term": "t", "vocab": vocab, "status": status}])
    if _fires(r, "L11", lt.ERROR):
        return "error"
    if _fires(r, "L11", lt.WARN):
        return "warn"
    return "clean"


def test_l11_status_matrix_free_vs_no_api():
    """FG2 #9 exact-equality three-state x vocab-class matrix (Design Spec §5.2 L11).

    | status         | free-API (MeSH) | no-API (Emtree)     |
    |----------------|-----------------|---------------------|
    | verified       | clean           | error (fake-verify) |
    | unverified     | warn (放行)      | warn (放行)          |
    | pending_manual | error           | clean (normal 🟨)   |
    """
    # free-API vocab (MeSH on PubMed): must be verified/downgraded; honest
    # 'unverified' (offline/network) warns; a free-API vocab may not be punted to
    # manual review.
    assert _l11_verdict("MeSH", "verified", "pubmed") == "clean"
    assert _l11_verdict("MeSH", "unverified", "pubmed") == "warn"
    assert _l11_verdict("MeSH", "pending_manual", "pubmed") == "error"
    # no-API vocab (Emtree on Embase.com): may NOT claim verified (A-6); honest
    # 'unverified' warns; 'pending_manual' is the designed normal 🟨 state.
    assert _l11_verdict("Emtree", "verified", "embase_com") == "error"
    assert _l11_verdict("Emtree", "unverified", "embase_com") == "warn"
    assert _l11_verdict("Emtree", "pending_manual", "embase_com") == "clean"


def test_l11_no_api_unverified_passes_repro_26a4_26c_p1():
    # 26a#4 / 26c P1-1: offline mode stamps a no-API Emtree term 'unverified'.
    # The old substring test ("verified" is a substring of "unverified") wrongly
    # raised a fake-verify error -> the legitimate string was silently withheld.
    # Exact equality: honest 'unverified' WARNS but PASSES the gate.
    r = lt.lint("x", "embase_com",
                vocab_terms=[{"term": "neoplasm", "vocab": "Emtree",
                              "status": "unverified"}])
    assert r.passed                          # gate not failed (no withhold)
    assert not _fires(r, "L11", lt.ERROR)    # no fake-verify error
    assert _fires(r, "L11", lt.WARN)         # honest 'unverified' -> warn 放行


def test_l11_classify_status_is_exact_not_substring():
    # 'unverified' must NOT be read as 'verified' (its literal substring) — the
    # exact root cause of the L11 silent-withhold bug (FG2 #9).
    assert lt._classify_status("unverified") == "unverified"
    assert lt._classify_status("unverified") != "verified"
    assert lt._classify_status("verified") == "verified"
    assert lt._classify_status("pending_manual") == "pending"
    assert lt._classify_status("not_found") == "downgraded"
    # substring lookalikes are 'unknown', never silently bucketed as verified
    assert lt._classify_status("preverified") == "unknown"
    assert lt._classify_status("self-verified-by-llm") == "unknown"


def test_l11_no_bare_substring_status_comparison_in_source():
    # Guard the invariant that L11 classifies status by set-membership (equality),
    # never a bare ``token in status`` substring scan (FG2 #11).
    import inspect

    src = inspect.getsource(lt._check_l11) + inspect.getsource(lt._classify_status)
    assert "tok in status" not in src
    assert "in status for" not in src


# ---------------------------------------------------------------------------
# Card loading / host resolution guards.
# ---------------------------------------------------------------------------


def test_unknown_host_raises():
    try:
        lt.lint("cancer", "not_a_real_host")
    except lt.UnknownHostError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownHostError")


def test_host_aliases_resolve():
    assert lt.resolve_card_name("知网") == "cnki"
    assert lt.resolve_card_name("Web of Science") == "wos"
    assert lt.resolve_card_name("cochrane") == "cochrane_central"
    assert lt.resolve_card_name("IEEE-Xplore") == "ieee_xplore"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
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
