"""Tests for scripts/search_export/generate.py + the three v2.4 STEP 11.5 pipeline
integration points (data_materialization / prisma_s_logger / agent_search).

Network-free: MeSH/ERIC/CMeSH verification is injected (fake esearch / fake
session) and deep-link live-verify is never invoked, so no HTTP is issued. Covers:

- render-style detection + per-host rendering (bracket / equals / cjk / paren)
- the 13 §1.2 three-platform examples reproduced linter-clean by the generator
- the double-file (json + md) output + full §2.1 schema field completeness
- the linter GATE: a marker-poisoned block is withheld, never emitted
- Gate2 FG1 regression battery: exact (no-substring) vocab routing, per-host CV
  clause snapshots (embase.com / CINAHL / PsycINFO / Ovid / SinoMed CMeSH),
  Scopus TITLE-ABS-KEY wrap, Cochrane CV omission (D-d), Count=0 downgrade
  (§5.3), operator_logic honoured/withheld (D-b), bilingual free_text_zh channel
  (D-a), proximity fallback + empty-string withhold, card-driven line forms,
  CLI argparse boundaries
- MeSH verification integration + honest downgrade / offline stamps
- R-19 integration: report_data.json / PRISMA-S log / agent envelope are
  unchanged without the new inputs, and additively enriched WITH them.

Run from skill root:
    PYTHONPATH=. python3 -m pytest tests/test_search_export_generate.py -q
or:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_search_export_generate
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.search_export import generate as g  # noqa: E402
from scripts.search_export import linter as lt  # noqa: E402
from scripts.types import Author, Config, UnifiedPaperEntity  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Platform-independent IR mirroring 13 §1.2 (mindfulness / students / anxiety).
CM_EN = {
    "blocks": [
        {"id": "I", "role": "intervention", "label": "mindfulness",
         "free_text": ["mindfulness", "mindfulness-based", "MBSR", "MBCT"],
         "controlled_vocab_candidates": {"MeSH": ["Mindfulness"]}},
        {"id": "P", "role": "population", "label": "students",
         "free_text": ["college students", "university students", "undergraduates"],
         "controlled_vocab_candidates": {"MeSH": ["Students"]},
         "truncation_intent": {"college students": "college student",
                               "university students": "university student",
                               "undergraduates": "undergraduate"}},
        {"id": "O", "role": "outcome", "label": "anxiety",
         "free_text": ["anxiety", "anxious"],
         "controlled_vocab_candidates": {"MeSH": ["Anxiety", "Anxiety Disorders"]},
         "truncation_intent": {"anxious": "anxious"}},
    ],
    "operator_logic": "(I) AND (P) AND (O)",
    "omitted_blocks": [{"role": "C", "reason": "A-2 comparator omitted"}],
    "register_notes": ["audit=偏召回；受控词+自由词双轨"],
}

# Chinese word faces live in free_text_zh — the ONLY channel cjk render hosts
# (CNKI/万方/SinoMed) read (Gate2 D-a: a cjk host whose blocks carry no
# free_text_zh withholds; English word faces never enter a Chinese database).
CM_ZH = {
    "blocks": [
        {"id": "I", "role": "intervention",
         "free_text_zh": ["正念", "正念减压", "正念认知"]},
        {"id": "P", "role": "population",
         "free_text_zh": ["大学生", "高校学生", "本科生"]},
        {"id": "O", "role": "outcome", "free_text_zh": ["焦虑", "焦虑症"]},
    ],
    "operator_logic": "(I) AND (P) AND (O)",
}

# Dual-channel model (language_space=both): en faces for Latin hosts, zh faces
# for cjk hosts — the two channels must never cross-pollute (D-a).
CM_BOTH = {
    "blocks": [
        {"id": "I", "role": "intervention",
         "free_text": ["mindfulness", "MBSR"],
         "free_text_zh": ["正念", "正念减压"],
         "controlled_vocab_candidates": {"MeSH": ["Mindfulness"]}},
        {"id": "O", "role": "outcome",
         "free_text": ["anxiety"],
         "free_text_zh": ["焦虑"],
         "controlled_vocab_candidates": {}},
    ],
    "operator_logic": "(I) AND (O)",
}

_MESH_UIDS = {"Mindfulness": "68064866", "Students": "68013334",
              "Anxiety": "68001007", "Anxiety Disorders": "68001008"}


def fake_mesh_esearch(term):
    """Offline MeSH esearch: every fixture descriptor 'exists', others do not."""
    uid = _MESH_UIDS.get(term)
    return (1, [uid]) if uid else (0, [])


# ---------------------------------------------------------------------------
# Render-style detection
# ---------------------------------------------------------------------------

def test_render_style_detection():
    assert g.render_style(lt.load_card("pubmed")) == "bracket"
    assert g.render_style(lt.load_card("wos")) == "equals"
    assert g.render_style(lt.load_card("cnki")) == "cjk"
    assert g.render_style(lt.load_card("eric")) == "colon"
    # Scopus is the paren-wrap shape: TITLE-ABS-KEY(...) wraps the WHOLE query
    # (Gate2 FG1 #3 — it was previously misclassified as unfielded, emitting a
    # bare string Scopus advanced search does not accept, 26b P1-3).
    assert g.render_style(lt.load_card("scopus")) == "paren"


def test_platform_vocab_routing():
    assert g.platform_vocab(lt.load_card("pubmed")) == "mesh"
    assert g.platform_vocab(lt.load_card("eric")) == "eric"
    assert g.platform_vocab(lt.load_card("wos")) is None
    assert g.platform_vocab(lt.load_card("cnki")) is None


def test_vocab_routing_exact_no_substring_collisions():
    """Gate2 FG1 #1 (26a#1 / 26b P1-2): vocab labels route by EXACT match only.

    The old substring loop folded "CMeSH" into mesh ("mesh" ⊂ "cmesh"), the
    embase_ovid compound name into mesh, and "…Thesaurus…" names into apa —
    injecting cross-vocabulary candidates and free-API-"verifying" no-API
    vocabularies (A-5/A-6). Would fail on the pre-Gate2 code."""
    assert g.platform_vocab(lt.load_card("sinomed")) == "cmesh"
    assert g.platform_vocab(lt.load_card("embase_ovid")) == "emtree"
    assert g.platform_vocab(lt.load_card("embase_com")) == "emtree"
    assert g.platform_vocab(lt.load_card("cinahl_ebsco")) == "cinahl"
    assert g.platform_vocab(lt.load_card("psycinfo_ebsco")) == "apa"
    assert g.platform_vocab(lt.load_card("psycinfo_ovid")) == "apa"
    assert g.platform_vocab(lt.load_card("cochrane_central")) == "mesh"
    # unknown vocabularies stay themselves — never folded into a known key
    known = {"mesh", "eric", "emtree", "cinahl", "apa", "cmesh"}
    for host in ("ieee_xplore", "cab_cabi", "econlit_ebsco", "scifinder"):
        key = g.platform_vocab(lt.load_card(host))
        assert key not in known, (host, key)
    # a card declaring verification: not_applicable has NO CV track at all
    assert g.platform_vocab(lt.load_card("acm")) is None
    # candidate-key labels: exact, not substring
    assert g._norm_vocab("CMeSH") == "cmesh"
    assert g._norm_vocab("MeSH") == "mesh"
    assert g._norm_vocab("IEEE Thesaurus") not in known


def test_sinomed_does_not_ingest_mesh_candidates():
    """The routing collision's downstream effect (26b P1-2): SinoMed must not
    pick up a block's MeSH (English) candidates, send them to NCBI, and stamp
    the strategy 机械已验. With exact routing its key is cmesh -> the MeSH
    candidates simply do not match (offline: no candidates -> no network)."""
    cm = {
        "blocks": [{"id": "P", "role": "population",
                    "free_text_zh": ["糖尿病"],
                    "controlled_vocab_candidates": {"MeSH": ["Mindfulness"]}}],
        "operator_logic": "(P)",
    }
    s = g.build_strategy("sinomed", cm)   # no esearch_fn: must stay offline
    assert s["controlled_vocab_terms"] == []
    assert "Mindfulness" not in (s["strategy_string"] or "")
    assert s["vocab_verification_status"] != "机械已验"


# ---------------------------------------------------------------------------
# 13 §1.2 reproduction — generator output is linter-clean + structurally faithful
# ---------------------------------------------------------------------------

def test_pubmed_reproduction_linter_clean():
    s = g.build_strategy("pubmed", CM_EN, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    # linter-clean (the hard gate)
    r = lt.lint(q, "pubmed", vocab_terms=s["controlled_vocab_terms"])
    assert r.passed and not r.findings, [str(f) for f in r.findings]
    # structural faithfulness to §1.2: MeSH + [tiab] dual-track, 3 blocks AND-joined
    assert '"Mindfulness"[mh]' in q          # card-canonical MeSH tag ([mh] == [Mesh])
    assert "mindfulness[tiab]" in q
    assert q.count("\nAND\n") == 2           # (P) AND (I) AND (O)
    # PubMed stays CONSERVATIVE (no '*' — it closes ATM, "discouraged"): matches the
    # 13 §1.2 example's plural free words, NOT truncation (A-4).
    assert '"college students"[tiab]' in q and "undergraduates[tiab]" in q
    assert "*" not in q
    assert s["vocab_verification_status"] == "机械已验"
    assert s["render_style"] == "bracket"


def test_wos_reproduction_linter_clean():
    s = g.build_strategy("wos", CM_EN, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    r = lt.lint(q, "wos")
    assert r.passed and not r.findings, [str(f) for f in r.findings]
    assert q.startswith("TS=(")
    # WoS byte-matches the §1.2 P & O blocks (truncation via native '*')
    assert '("college student*" OR "university student*" OR undergraduate*)' in q
    assert "(anxiety OR anxious*)" in q
    assert s["vocab_verification_status"] == "结构参考"   # no table + subscription wall
    assert s["render_style"] == "equals"


def test_cnki_reproduction_byte_identical_and_clean():
    s = g.build_strategy("cnki", CM_ZH, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    r = lt.lint(q, "cnki")
    assert r.passed and not r.findings, [str(f) for f in r.findings]
    # byte-identical to the 13 §1.2 CNKI example
    expected = (
        "(SU %= '正念' OR SU %= '正念减压' OR SU %= '正念认知')\n"
        "AND (SU %= '大学生' OR SU %= '高校学生' OR SU %= '本科生')\n"
        "AND (SU %= '焦虑' OR SU %= '焦虑症')"
    )
    assert q == expected
    assert s["vocab_verification_status"] == "语法已验·无受控词表"
    assert s["render_style"] == "cjk"


def test_literal_spec_examples_lint_clean():
    """The literal 13 §1.2 example strings pass the linter clean (mirrors C1 at the
    generator's validation layer — proves the spec examples are reproducible+valid)."""
    from tests.test_search_export_linter import (
        CNKI_EXAMPLE, PUBMED_EXAMPLE, WOS_EXAMPLE,
    )
    for q, h in ((PUBMED_EXAMPLE, "pubmed"), (WOS_EXAMPLE, "wos"), (CNKI_EXAMPLE, "cnki")):
        r = lt.lint(q, h)
        assert r.passed and not r.findings, f"{h}: {[str(f) for f in r.findings]}"


# ---------------------------------------------------------------------------
# Double-file output + full §2.1 schema completeness
# ---------------------------------------------------------------------------

_TOP_KEYS = [
    "schema_version", "search_id", "generated_at", "topic", "framework", "register",
    "language_space", "quality_claim", "concept_model", "strategies", "supplementary",
    "global_review_points", "prisma_s_item8_ref",
]
_STRAT_KEYS = [
    "platform", "host", "database", "access", "syntax_card_ref", "strategy_lines",
    "strategy_string", "field_scope", "deep_link", "vocab_verification_status",
    "controlled_vocab_terms", "filters_used", "linter", "press_check", "review_points",
    "prisma_s",
]


def test_generate_full_schema_completeness():
    rec = g.generate(CM_EN, ["pubmed", "wos"], topic="正念对大学生焦虑",
                     search_id="sid1", esearch_fn=fake_mesh_esearch)
    assert [k for k in _TOP_KEYS if k not in rec] == []
    assert rec["schema_version"] == "1.0"
    assert rec["quality_claim"] == g.QUALITY_CLAIM
    for s in rec["strategies"]:
        assert [k for k in _STRAT_KEYS if k not in s] == []
        assert list(s["press_check"].keys()) == [
            "d1_translation", "d2_boolean", "d3_subject_headings",
            "d4_text_words", "d5_spelling_syntax", "d6_limits_filters",
        ]
        assert list(s["prisma_s"].keys()) == [
            "item8_boolean_expression", "item1_database", "item9_limits", "item10_filter",
        ]
    json.dumps(rec, ensure_ascii=False)  # must be JSON-serialisable


def test_controlled_vocab_term_shape_and_descriptor_ui():
    s = g.build_strategy("pubmed", CM_EN, esearch_fn=fake_mesh_esearch)
    terms = {t["term"]: t for t in s["controlled_vocab_terms"]}
    assert terms["Mindfulness"]["status"] == "verified"
    assert terms["Mindfulness"]["descriptor_ui"] == "D064866"   # 68064866 -> D064866
    for t in s["controlled_vocab_terms"]:
        for k in ("term", "vocab", "status", "descriptor_ui", "explode"):
            assert k in t


def test_write_outputs_creates_both_files():
    rec = g.generate(CM_EN, ["pubmed", "cnki"], topic="T", esearch_fn=fake_mesh_esearch)
    with tempfile.TemporaryDirectory() as d:
        paths = g.write_outputs(rec, Path(d))
        assert paths["json"].exists() and paths["md"].exists()
        parsed = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert parsed["topic"] == "T"
        md = paths["md"].read_text(encoding="utf-8")
        for section in ("## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
            assert section in md
        assert "```" in md  # code fences for the strategy strings


def test_run_one_shot_writes_files():
    with tempfile.TemporaryDirectory() as d:
        paths = g.run(CM_EN, ["pubmed"], Path(d), topic="R", esearch_fn=fake_mesh_esearch)
        assert paths["json"].exists() and paths["md"].exists()


# ---------------------------------------------------------------------------
# MeSH verification integration (mocked)
# ---------------------------------------------------------------------------

def test_mesh_hallucination_culled_and_downgraded_to_free_text():
    """13 spec §5.3: Count=0 -> the candidate is CULLED from the CV clause and
    DOWNGRADED into the [tiab] free-text track; the strategy label carries the
    downgrade marker (never a bare 机械已验); the deep link and PRISMA item 8
    carry no [mh]-tagged hallucination.

    Replaces the wrong-oracle test that froze the pre-Gate2 behaviour (26b P1-1 /
    26c 漏-1: the old assertions guarded the bug — a hallucinated descriptor was
    kept in strategy_string/deep_link/item8 under a pure 机械已验 label)."""
    cm = {
        "blocks": [{"id": "P", "role": "population", "free_text": ["kids"],
                    "controlled_vocab_candidates": {
                        "MeSH": ["Mindfulness", "Zzz Not A Real Descriptor"]}}],
        "operator_logic": "(P)",
    }
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    by_term = {t["term"]: t for t in s["controlled_vocab_terms"]}
    assert by_term["Zzz Not A Real Descriptor"]["status"] == "not_found"
    assert by_term["Mindfulness"]["status"] == "verified"
    q = s["strategy_string"]
    assert q is not None and s["linter"]["passed"]
    # verified CV stays; the not_found candidate is culled from the CV clause…
    assert '"Mindfulness"[mh]' in q
    assert '"Zzz Not A Real Descriptor"[mh]' not in q
    assert '"Zzz Not A Real Descriptor"[mh]' not in s["prisma_s"]["item8_boolean_expression"]
    assert "%5Bmh%5D" not in (s["deep_link"]["url"] or "").split("Zzz")[-1]
    # …and downgraded INTO the free-text dual track (§5.3 原文)
    assert '"Zzz Not A Real Descriptor"[tiab]' in q
    # label carries the downgrade marker, never a pure 机械已验 (26c P0-3)
    assert s["vocab_verification_status"] == "机械已验·含降级"
    assert any("已降级" in rp for rp in s["review_points"])


def test_mesh_downgrade_does_not_duplicate_existing_free_text():
    """A not_found candidate already present in the block's free_text (case-
    insensitively) is not appended a second time."""
    cm = {
        "blocks": [{"id": "P", "role": "population",
                    "free_text": ["kids", "zzz not a real descriptor"],
                    "controlled_vocab_candidates": {"MeSH": ["Zzz Not A Real Descriptor"]}}],
        "operator_logic": "(P)",
    }
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    assert q.lower().count("zzz not a real descriptor") == 1


def test_verify_vocab_false_is_offline_and_lint_safe():
    s = g.build_strategy("pubmed", CM_EN, verify_vocab=False)  # no esearch_fn, no network
    assert all(t["status"] == "unverified" for t in s["controlled_vocab_terms"])
    # 'unverified' is a valid L11 status stamp -> still linter-clean, not withheld
    assert s["linter"]["passed"] and s["strategy_string"] is not None


# ---------------------------------------------------------------------------
# Deep-link integration
# ---------------------------------------------------------------------------

def test_deeplink_a_tier_constructed_and_bc_not():
    p = g.build_strategy("pubmed", CM_EN, esearch_fn=fake_mesh_esearch)
    assert p["deep_link"]["tier"] == "A"
    assert p["deep_link"]["url"] and p["deep_link"]["url"].startswith(
        "https://pubmed.ncbi.nlm.nih.gov/?term="
    )
    w = g.build_strategy("wos", CM_EN, esearch_fn=fake_mesh_esearch)
    assert w["deep_link"]["tier"] == "C"
    assert w["deep_link"]["url"] is None            # never a wall-bypassing URL (C-14)


# ===========================================================================
# Gate2 FG1 #3 — per-host CV clause + field-wrap rendering (26a#3 / 26b P1-3)
# ===========================================================================

_CM_CV = {
    "blocks": [
        {"id": "I", "role": "intervention",
         "free_text": ["mindfulness", "MBSR"],
         "controlled_vocab_candidates": {
             "MeSH": ["Mindfulness"], "Emtree": ["mindfulness"],
             "CINAHL": ["Mindfulness"], "APA": ["Mindfulness"]}},
        {"id": "O", "role": "outcome", "free_text": ["anxiety", "anxious"],
         "controlled_vocab_candidates": {}},
    ],
    "operator_logic": "(I) AND (O)",
}


def test_cv_clause_snapshots_per_host():
    """The CV clause is rendered from a card-derived template — the four host
    families 26a#3 showed emitting ILLEGAL syntax now emit the card's canonical
    forms (and the whole string stays linter-clean):

      embase.com      'mindfulness'/exp    (was  'mindfulness'':de' — double-quote splice)
      CINAHL (EBSCO)  (MH "Mindfulness+")  (was  "Mindfulness"MH   — postfix, illegal)
      PsycINFO (EBSCO) DE "Mindfulness"    (was  "Mindfulness"DE   — postfix, illegal)
      Ovid hosts      exp <term>/          (was  "term".sh."       — non-canonical)
      PubMed          "Mindfulness"[mh]    (unchanged, pinned)
    """
    cases = {
        "embase_com": "'mindfulness'/exp",
        "cinahl_ebsco": '(MH "Mindfulness+")',
        "psycinfo_ebsco": 'DE "Mindfulness"',
        "embase_ovid": "exp mindfulness/",
        "psycinfo_ovid": "exp Mindfulness/",
        "pubmed": '"Mindfulness"[mh]',
    }
    for host, clause in cases.items():
        s = g.build_strategy(host, _CM_CV, esearch_fn=fake_mesh_esearch)
        q = s["strategy_string"]
        assert q and clause in q, (host, q)
        assert s["linter"]["passed"], (host, s["linter"]["errors"])


def test_eric_cv_clause_prefix_colon():
    class _FakeEricSession:
        def get(self, url, timeout=None):
            class R:
                status_code = 200
                def json(self):
                    return {"response": {"numFound": 3}}
            return R()

    cm = {
        "blocks": [{"id": "O", "role": "outcome", "free_text": ["anxiety"],
                    "controlled_vocab_candidates": {"ERIC": ["Anxiety"]}}],
        "operator_logic": "(O)",
    }
    s = g.build_strategy("eric", cm, vocab_session=_FakeEricSession())
    assert 'descriptor:"Anxiety"' in s["strategy_string"]
    assert s["controlled_vocab_terms"][0]["status"] == "verified"
    assert s["linter"]["passed"]


def test_cochrane_cv_clause_omitted_not_illegal():
    """Cochrane's card declares a bracket subject tag on a colon-tag host (the
    term goes INSIDE [mh …]) — not mechanically templatable, so per D-d the CV
    clause is OMITTED with a review point; the PubMed-style postfix form
    ("Mindfulness"[mh]) 26a#3 observed is never emitted. Free-text dual track
    stays (the card itself mandates 必须叠自由词)."""
    s = g.build_strategy("cochrane_central", _CM_CV, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    assert q is not None and s["linter"]["passed"]
    assert "[mh]" not in q and '"Mindfulness"[mh]' not in q
    assert "mindfulness:ti,ab" in q          # free-text side intact
    assert any("人工组装" in rp for rp in s["review_points"])
    # verification info is still delivered (terms listed, just not in the string)
    assert s["controlled_vocab_terms"]


def test_scopus_whole_query_wrapped_in_title_abs_key():
    """Scopus advanced search requires a field code — the whole query is wrapped
    in TITLE-ABS-KEY(...) (26a#3: the old output was a bare unfielded string)."""
    s = g.build_strategy("scopus", CM_EN, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    assert q.startswith("TITLE-ABS-KEY(") and q.rstrip().endswith(")")
    assert s["linter"]["passed"], s["linter"]["errors"]
    assert s["render_style"] == "paren"
    # line form carries the wrap too
    assert s["strategy_lines"][0].startswith("#1 TITLE-ABS-KEY(")


def test_sinomed_cmesh_machine_expr_pending_manual():
    """SinoMed CMeSH renders via the card's machine_expr template
    ("<主题词>/全部树/全部副主题词" = explode + all subheadings) and stays
    pending_manual (soft cross-check never upgrades) -> 语法已验·词表待核."""
    class _FakeSuggestSession:
        def get(self, url, timeout=None):
            class R:
                status_code = 200
                text = "糖尿病"
            return R()

    cm = {
        "blocks": [{"id": "P", "role": "population",
                    "free_text_zh": ["糖尿病"],
                    "controlled_vocab_candidates": {"CMeSH": ["糖尿病"]}}],
        "operator_logic": "(P)",
    }
    s = g.build_strategy("sinomed", cm, vocab_session=_FakeSuggestSession())
    assert '"糖尿病/全部树/全部副主题词"' in s["strategy_string"]
    t = s["controlled_vocab_terms"][0]
    assert (t["vocab"], t["status"]) == ("CMeSH", "pending_manual")
    assert s["vocab_verification_status"] == "语法已验·词表待核"
    assert s["linter"]["passed"]


# ===========================================================================
# Gate2 FG1 #4 — operator_logic honoured as declared (D-b)
# ===========================================================================

_CM_AB = {
    "blocks": [
        {"id": "A", "role": "concept", "free_text": ["alpha"],
         "controlled_vocab_candidates": {}},
        {"id": "B", "role": "concept", "free_text": ["beta"],
         "controlled_vocab_candidates": {}},
    ],
    "operator_logic": "(A) OR (B)",
}


def test_operator_logic_or_honoured():
    """26a Additional#1: "(A) OR (B)" used to render as AND — meaning inverted
    while the linter passed. The declared operator is now honoured."""
    s = g.build_strategy("pubmed", _CM_AB, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    assert "\nOR\n" in q and "AND" not in q
    assert s["linter"]["passed"]
    # the line-form combine line follows the declared operator too
    assert s["strategy_lines"][-1] == "#3 #1 OR #2"


def test_operator_logic_declared_order_and_unreferenced_note():
    cm = {
        "blocks": [
            {"id": "A", "role": "concept", "free_text": ["alpha"]},
            {"id": "B", "role": "concept", "free_text": ["beta"]},
            {"id": "C", "role": "concept", "free_text": ["gamma"]},
        ],
        "operator_logic": "(B) AND (A)",
    }
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    # declared order (B before A); unreferenced C is not rendered but is noted
    assert q.index("beta") < q.index("alpha")
    assert "gamma" not in q
    assert any("未被 operator_logic 引用" in rp for rp in s["review_points"])


def test_operator_logic_unparseable_withholds():
    """D-b: anything the mechanical layer cannot parse -> withhold + review
    point; the logic is NEVER silently rewritten."""
    for bad_logic in ("(A) NOT (B)", "(A) AND (B) OR (A)", "(A) XOR (B)",
                      "(A) AND (Z)", "A AND"):
        cm = dict(_CM_AB, operator_logic=bad_logic)
        s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
        assert s["strategy_string"] is None, bad_logic
        assert s["strategy_lines"] is None
        assert s["prisma_s"]["item8_boolean_expression"] is None
        assert s["deep_link"]["url"] is None
        assert any("operator_logic" in rp for rp in s["review_points"]), bad_logic


def test_operator_logic_missing_defaults_to_and_with_note():
    cm = {"blocks": [
        {"id": "A", "role": "concept", "free_text": ["alpha"]},
        {"id": "B", "role": "concept", "free_text": ["beta"]},
    ]}
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    assert "\nAND\n" in s["strategy_string"]
    assert any("未声明 operator_logic" in rp for rp in s["review_points"])


# ===========================================================================
# Gate2 FG1 #5 — bilingual channel (D-a): cjk hosts read free_text_zh ONLY
# ===========================================================================

def test_cjk_host_withholds_without_free_text_zh():
    """26b P1-4: an English-faced model used to render straight into CNKI
    ((SU %= 'mindfulness')) — near-zero recall in a Chinese database. A cjk host
    with no free_text_zh now withholds with the 缺中文词项 review point."""
    cm = {
        "blocks": [{"id": "I", "role": "intervention",
                    "free_text": ["mindfulness", "MBSR"],
                    "controlled_vocab_candidates": {}}],
        "operator_logic": "(I)",
    }
    for host in ("cnki", "wanfang", "sinomed"):
        s = g.build_strategy(host, cm, esearch_fn=fake_mesh_esearch)
        assert s["strategy_string"] is None, host
        assert s["strategy_lines"] is None
        assert s["prisma_s"]["item8_boolean_expression"] is None
        assert s["deep_link"]["url"] is None
        assert any("缺中文词项" in rp for rp in s["review_points"]), host


def test_bilingual_channels_no_cross_pollution():
    """language_space=both: the zh channel feeds cjk hosts, the en channel feeds
    Latin hosts — neither leaks into the other (D-a)."""
    c = g.build_strategy("cnki", CM_BOTH, esearch_fn=fake_mesh_esearch)
    assert "正念" in c["strategy_string"]
    assert "mindfulness" not in c["strategy_string"].lower()
    assert c["linter"]["passed"]
    p = g.build_strategy("pubmed", CM_BOTH, esearch_fn=fake_mesh_esearch)
    assert "mindfulness" in p["strategy_string"]
    assert "正念" not in p["strategy_string"]
    assert p["linter"]["passed"]


# ===========================================================================
# Gate2 FG1 #6 — proximity fallback + empty renders are never passed-empty
# ===========================================================================

def test_proximity_only_block_delivers_fallback_not_empty():
    """26a Additional#2: an ACM block carrying only a proximity intent used to
    emit an EMPTY strategy_string with linter.passed=True and no review point.
    The proximity table's declared fallback (AND/phrase) is now rendered with a
    review point — never a silent empty pass."""
    cm = {
        "blocks": [{"id": "X", "role": "concept", "free_text": [],
                    "controlled_vocab_candidates": {},
                    "proximity_intent": {"terms": ["sleep", "therapy"], "k": 3}}],
        "operator_logic": "(X)",
    }
    s = g.build_strategy("acm", cm, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"]
    assert q and "sleep AND therapy" in q and "NEAR" not in q
    assert s["linter"]["passed"]
    assert any("降级" in rp and "邻近" in rp.replace("无邻近算符", "邻近")
               for rp in s["review_points"]) or \
        any("无邻近算符" in rp for rp in s["review_points"])


def test_empty_or_malformed_concept_model_withheld():
    """26c P2-1: blocks=[] / term-less blocks used to yield '' with passed=True
    (an empty code fence delivered as a valid strategy). Now: withheld + reason."""
    empty = {"blocks": [], "operator_logic": ""}
    s = g.build_strategy("pubmed", empty, esearch_fn=fake_mesh_esearch)
    assert s["strategy_string"] is None
    assert any("概念模型为空" in rp or "withhold" in rp for rp in s["review_points"])

    termless = {"blocks": [{"id": "P", "role": "population", "free_text": []}],
                "operator_logic": "(P)"}
    s = g.build_strategy("pubmed", termless, esearch_fn=fake_mesh_esearch)
    assert s["strategy_string"] is None
    assert any("无可渲染词项" in rp for rp in s["review_points"])

    junk = {"blocks": ["not-a-dict", 42], "operator_logic": "(P)"}
    s = g.build_strategy("pubmed", junk, esearch_fn=fake_mesh_esearch)
    assert s["strategy_string"] is None   # unknown id P -> unparseable -> withheld


# ===========================================================================
# Gate2 FG1 #7 — line forms read the card's line_search.syntax (never hardcoded)
# ===========================================================================

def test_line_form_grammar_read_from_card():
    """26a Additional#3 / 26b P3-4: #N was hardcoded for every host. Now the
    grammar sample is parsed off each card: EBSCO -> S1/S2, Ovid -> bare numbers
    with lowercase combine, CNKI -> NO line form (its 高级检索 7-row UI has no
    #N reference grammar), PubMed/SinoMed -> #N."""
    cm = {
        "blocks": [
            {"id": "A", "role": "concept", "free_text": ["alpha"],
             "free_text_zh": ["正念"]},
            {"id": "B", "role": "concept", "free_text": ["beta"],
             "free_text_zh": ["焦虑"]},
        ],
        "operator_logic": "(A) AND (B)",
    }
    s = g.build_strategy("cinahl_ebsco", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] == ["S1 alpha", "S2 beta", "S3 S1 AND S2"]
    s = g.build_strategy("embase_ovid", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] == ["1 alpha", "2 beta", "3 1 and 2"]
    s = g.build_strategy("cnki", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] is None and s["strategy_string"] is not None
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] == ["#1 alpha[tiab]", "#2 beta[tiab]", "#3 #1 AND #2"]
    s = g.build_strategy("sinomed", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] == ["#1 正念", "#2 焦虑", "#3 #1 AND #2"]
    # embase.com's card sample ("query numbers…") has no parsable grammar -> None
    s = g.build_strategy("embase_com", cm, esearch_fn=fake_mesh_esearch)
    assert s["strategy_lines"] is None


# ===========================================================================
# Gate2 FG1 — L11 joint verification with FG2 (26c P1-1 / P0-5 generate side)
# ===========================================================================

_CM_EMTREE = {
    "blocks": [{"id": "C", "role": "concept", "free_text": ["neoplasm"],
                "controlled_vocab_candidates": {"Emtree": ["neoplasm"]}}],
    "operator_logic": "(C)",
}


def test_embase_offline_unverified_is_not_withheld():
    """26c P1-1 (joint with FG2's L11 exact-match fix): --no-verify-vocab stamps
    'unverified'; the linter treats that as an honest gap (WARN, 放行) — the
    legitimate Embase strategy is NOT silently withheld."""
    s = g.build_strategy("embase_com", _CM_EMTREE, verify_vocab=False)  # offline
    assert s["linter"]["passed"] and s["strategy_string"] is not None
    t = s["controlled_vocab_terms"][0]
    assert (t["vocab"], t["status"]) == ("Emtree", "unverified")
    assert any("L11" in w and "unverified" in w for w in s["linter"]["warnings"])


def test_embase_online_pending_manual_is_not_withheld():
    """The designed 🟨 state: online, a no-free-API vocab stays pending_manual
    and the strategy is delivered with the yellow-flag review point."""
    s = g.build_strategy("embase_com", _CM_EMTREE, esearch_fn=fake_mesh_esearch)
    assert s["linter"]["passed"] and s["strategy_string"] is not None
    t = s["controlled_vocab_terms"][0]
    assert (t["vocab"], t["status"]) == ("Emtree", "pending_manual")
    assert s["vocab_verification_status"] == "语法已验·词表待核"


# ===========================================================================
# Gate2 FG1 #8 — CLI argparse boundaries (26c P2-2)
# ===========================================================================

def _run_cli(argv):
    try:
        return g._main_cli(argv), None
    except SystemExit as e:
        return None, e.code


def test_cli_bad_json_and_missing_file_error_cleanly():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "cm.json"
        bad.write_text("{not json", encoding="utf-8")
        _, code = _run_cli(["--concept-model", str(bad),
                            "--platforms", "pubmed", "--out", d])
        assert code == 2                     # argparse error, not a traceback
        _, code = _run_cli(["--concept-model", str(Path(d) / "nope.json"),
                            "--platforms", "pubmed", "--out", d])
        assert code == 2
        arr = Path(d) / "arr.json"
        arr.write_text("[1,2,3]", encoding="utf-8")
        _, code = _run_cli(["--concept-model", str(arr),
                            "--platforms", "pubmed", "--out", d])
        assert code == 2                     # not an object -> clean error


def test_cli_missing_platforms_errors_and_happy_path_offline():
    with tempfile.TemporaryDirectory() as d:
        cmf = Path(d) / "cm.json"
        cmf.write_text(json.dumps({"concept_model": CM_EN, "topic": "T"},
                                  ensure_ascii=False), encoding="utf-8")
        _, code = _run_cli(["--concept-model", str(cmf), "--out", d])
        assert code == 2                     # no platforms anywhere -> error
        rc, code = _run_cli(["--concept-model", str(cmf), "--platforms", "pubmed",
                             "--out", d, "--no-verify-vocab"])
        assert code is None and rc == 0      # offline happy path
        assert (Path(d) / "search_strategies.json").exists()
        assert (Path(d) / "search_strategies.md").exists()


# ---------------------------------------------------------------------------
# The linter GATE — a rejected string is withheld, never emitted
# ---------------------------------------------------------------------------

def test_linter_reject_withholds_string():
    poisoned = {
        "blocks": [{"id": "P", "role": "population",
                    "free_text": ["中科院一区"],          # routing marker -> L6 error
                    "controlled_vocab_candidates": {}}],
        "operator_logic": "(P)",
    }
    s = g.build_strategy("pubmed", poisoned, esearch_fn=fake_mesh_esearch)
    assert s["linter"]["passed"] is False
    assert s["linter"]["errors"]
    # withheld: no invalid string is ever emitted (spec §6 Wave 3)
    assert s["strategy_string"] is None
    assert s["strategy_lines"] is None
    assert s["prisma_s"]["item8_boolean_expression"] is None
    assert s["deep_link"]["url"] is None
    assert any("withhold" in rp or "机械校验未通过" in rp for rp in s["review_points"])


# ---------------------------------------------------------------------------
# Vocab-status labels for the no-controlled-vocab platforms
# ---------------------------------------------------------------------------

def test_vocab_status_labels_no_cv():
    assert g.build_strategy("wos", CM_EN, esearch_fn=fake_mesh_esearch)[
        "vocab_verification_status"] == "结构参考"
    assert g.build_strategy("cnki", CM_ZH)[
        "vocab_verification_status"] == "语法已验·无受控词表"


# ---------------------------------------------------------------------------
# Proximity intent -> proximity.py (canonical k, never hand-computed)
# ---------------------------------------------------------------------------

def test_proximity_intent_rendered_and_clean():
    cm = {
        "blocks": [{"id": "X", "role": "concept", "free_text": ["insomnia"],
                    "controlled_vocab_candidates": {},
                    "proximity_intent": {"terms": ["sleep", "therapy"], "k": 3}}],
        "operator_logic": "(X)",
    }
    s = g.build_strategy("pubmed", cm, esearch_fn=fake_mesh_esearch)
    assert ":~3]" in s["strategy_string"]          # PubMed proximity clause present
    assert s["linter"]["passed"]


def test_proximity_degrades_on_no_proximity_host():
    cm = {
        "blocks": [{"id": "X", "role": "concept", "free_text": ["alpha"],
                    "controlled_vocab_candidates": {},
                    "proximity_intent": {"terms": ["sleep", "therapy"], "k": 3}}],
        "operator_logic": "(X)",
    }
    # ACM has no proximity operator -> never a fabricated NEAR; the table's
    # declared fallback is rendered instead, with a review point (FG1 #6).
    s = g.build_strategy("acm", cm, esearch_fn=fake_mesh_esearch)
    q = s["strategy_string"] or ""
    assert "NEAR" not in q
    assert "sleep AND therapy" in q
    assert any("无邻近算符" in rp for rp in s["review_points"])


# ---------------------------------------------------------------------------
# Unknown platform is skipped gracefully
# ---------------------------------------------------------------------------

def test_unknown_platform_skipped():
    rec = g.generate(CM_EN, ["pubmed", "not_a_real_platform"],
                     esearch_fn=fake_mesh_esearch)
    assert [s["platform"] for s in rec["strategies"]] == ["PubMed"]
    assert any("not_a_real_platform" in rp for rp in rec["global_review_points"])


# ===========================================================================
# R-19 integration point 1 — data_materialization.report_data.json
# ===========================================================================

def _mini_kg():
    p = UnifiedPaperEntity(
        doi="10.1/x", title="Alpha study", abstract="alpha beta",
        authors=[Author(name="A. One")], year=2022, citation_count=12,
        sources=["openalex"], rcs=8, tldr="t",
    )
    return {"k1": p}


def _materialize(output_dir, **kw):
    from scripts import data_materialization as dm
    return dm.materialize(_mini_kg(), Path(output_dir), user_query="alpha",
                          tier="audit", search_id="sid", summary="s", **kw)


def test_r19_report_data_byte_identical_without_export():
    """No search_strategies.json present -> report_data.json is byte-identical to the
    pre-v2.4 shape (original 5 keys, in order, no new key)."""
    with tempfile.TemporaryDirectory() as d:
        _materialize(d)
        rd = json.loads((Path(d) / "report_data.json").read_text(encoding="utf-8"))
    assert list(rd.keys()) == [
        "metadata", "chart_data", "paper_list", "prisma_log", "summary"
    ]
    assert "search_strategies" not in rd


def test_r19_report_data_folds_export_additively():
    """search_strategies.json present -> it is folded verbatim under a NEW trailing
    key, and the deterministic sections are unchanged from the no-export run."""
    ss = g.generate(CM_EN, ["pubmed"], topic="T", esearch_fn=fake_mesh_esearch)
    with tempfile.TemporaryDirectory() as d:
        # baseline (no export file)
        _materialize(d)
        base = json.loads((Path(d) / "report_data.json").read_text(encoding="utf-8"))
        # now write the export and re-materialize into the SAME dir (auto-discovery)
        (Path(d) / "search_strategies.json").write_text(
            json.dumps(ss, ensure_ascii=False), encoding="utf-8")
        _materialize(d)
        folded = json.loads((Path(d) / "report_data.json").read_text(encoding="utf-8"))
    # additive: the new key is present and LAST
    assert list(folded.keys())[-1] == "search_strategies"
    assert folded["search_strategies"]["strategies"][0]["platform"] == "PubMed"
    # the deterministic (timestamp-free) sections are unchanged by the fold
    assert folded["chart_data"] == base["chart_data"]
    assert folded["paper_list"] == base["paper_list"]
    assert folded["summary"] == base["summary"]


# ===========================================================================
# R-19 integration point 2 — prisma_s_logger items 8/1/9/10
# ===========================================================================

def test_r19_prisma_byte_identical_without_export():
    from scripts import prisma_s_logger as pl
    kg = _mini_kg()
    base = pl.build_prisma_s_log(kg, user_query="alpha", tier="audit", search_id="sid")
    none = pl.build_prisma_s_log(kg, user_query="alpha", tier="audit", search_id="sid",
                                 search_strategies=None)
    # build_prisma_s_log has no wall-clock/now() -> fully deterministic -> byte-equal
    assert json.dumps(base, ensure_ascii=False) == json.dumps(none, ensure_ascii=False)


def test_r19_prisma_enriched_with_export():
    from scripts import prisma_s_logger as pl
    kg = _mini_kg()
    ss = g.generate(CM_EN, ["pubmed", "wos"], esearch_fn=fake_mesh_esearch)
    base = pl.build_prisma_s_log(kg, search_strategies=None)
    enr = pl.build_prisma_s_log(kg, search_strategies=ss)
    assert enr != base
    # item 8: the per-platform boolean expressions are appended (source-tagged)
    exprs = enr["8_full_search_strategies"]["boolean_expressions"]
    exported = [e for e in exprs if isinstance(e, dict) and e.get("source") == "search_export"]
    assert len(exported) == 2
    assert any(e["platform"] == "PubMed" and e["text"] for e in exported)
    assert "search_export" in enr["8_full_search_strategies"]
    # items 1 / 9 additively enriched; base entries untouched
    assert "export_platforms" in enr["1_database_information"]
    assert "export_platforms" not in base["1_database_information"]
    assert "export_limits" in enr["9_limits_and_restrictions"]


# ===========================================================================
# R-19 integration point 3 — agent_search envelope + the C3 zh-block seam
# ===========================================================================

@contextlib.contextmanager
def _patched(*targets):
    saved = [(o, a, getattr(o, a)) for (o, a, _n) in targets]
    try:
        for o, a, n in targets:
            setattr(o, a, n)
        yield
    finally:
        for o, a, old in saved:
            setattr(o, a, old)


class _FakeQuota:
    def to_dict(self):
        return {"ok": True, "remaining_usd": 0.9, "should_switch": False, "mode": "probe"}


def _agent_cfg():
    c = Config()
    c.primary_source = "openalex"
    c.openalex_api_key = "k"
    c.openalex_email = "e@x.com"
    return c


def _oa_targets():
    from scripts import agent_search as a
    kt = UnifiedPaperEntity(doi="10.2307/1914185", title="prospect theory analysis",
                            abstract="prospect theory under risk",
                            authors=[Author(name="A. One")], year=2024,
                            citation_count=5000, sources=["openalex"])

    def fake_search_top_n_pages(query, total_papers=100, sort="cited_by_count:desc",
                                year_min=None, year_max=None):
        return [kt]

    return [
        (a.openalex_helper, "search_top_n_pages", fake_search_top_n_pages),
        (a.openalex_helper, "init_pyalex", lambda cfg: None),
        (a.quota_guard, "evaluate", lambda config, mode="probe", **kw: _FakeQuota()),
        (a.journal_rank, "load", lambda **kw: None),
    ]


def test_r19_agent_envelope_default_flags_equal_explicit_defaults():
    """Determinism + default==explicit-default for the new flags: the envelope
    with no v2.4 flags equals the envelope with with_strategies=False /
    zh_blocks=None, and carries no search_strategies key.

    HONESTY NOTE (Gate2 #8 rename, was …byte_identical_without_flags): this is
    a same-process determinism check, NOT a vs-main byte diff (that R-19 level
    is D2's manual segment check), and it does NOT cover the multi-word zh NSSD
    split — an authorized P2-5 behaviour change (Gate2 D-c), pinned in
    test_nssd_helper.py::test_build_pq_multiword_differs_from_legacy_by_design."""
    from scripts import agent_search as a
    with _patched(*_oa_targets()):
        off = a.run_agent_search("prospect theory", _agent_cfg(), per_strategy=5, now_year=2026)
        off2 = a.run_agent_search("prospect theory", _agent_cfg(), per_strategy=5,
                                  now_year=2026, with_strategies=False, zh_blocks=None)
    assert "search_strategies" not in off
    assert json.dumps(off, default=str, ensure_ascii=False) == \
        json.dumps(off2, default=str, ensure_ascii=False)


def test_with_strategies_adds_floor_only_key():
    from scripts import agent_search as a
    with _patched(*_oa_targets()):
        off = a.run_agent_search("prospect theory", _agent_cfg(), per_strategy=5, now_year=2026)
        on = a.run_agent_search("prospect theory", _agent_cfg(), per_strategy=5,
                                now_year=2026, with_strategies=True)
    assert "search_strategies" in on
    # removing the additive key recovers the exact byte-identical default envelope
    on_minus = {k: v for k, v in on.items() if k != "search_strategies"}
    assert json.dumps(on_minus, default=str, ensure_ascii=False) == \
        json.dumps(off, default=str, ensure_ascii=False)
    # the floor is a real, linter-gated export carrying the honest floor notice
    floor = on["search_strategies"]
    assert floor["strategies"][0]["strategy_string"] is not None
    assert "floor_notice" in floor
    assert floor["register"] == "quick"


def test_zh_block_seam_default_passes_none_to_retrieve_chinese():
    """--zh-block absent -> _retrieve_chinese receives nssd_blocks=None (C3 seam
    forwarding ONLY — this test does NOT assert NSSD-call byte-identity:
    single-token stays byte-identical, multi-word is the authorized P2-5
    multiblock split (Gate2 D-c), pinned in
    test_nssd_helper.py::test_build_pq_multiword_differs_from_legacy_by_design).

    Renamed from …default_none_is_byte_identical, whose name/docstring asserted
    an untested (and for multi-word queries false) proposition — 26b 漏-2 /
    26c 交叉验证轮."""
    from scripts import agent_search as a
    seen = {}

    def spy(query, sources, *, year_min, year_max, n, nssd_blocks=None):
        seen["nssd_blocks"] = nssd_blocks
        return [], []

    with _patched(*_oa_targets(), (a, "_retrieve_chinese", spy)):
        a.run_agent_search("prospect theory", _agent_cfg(), per_strategy=5,
                           now_year=2026, with_nssd=True, lang="both")
    assert seen["nssd_blocks"] is None  # the seam forwards the default None


def test_zh_block_forwarded_to_nssd():
    from scripts import agent_search as a
    seen = {}

    def spy(query, sources, *, year_min, year_max, n, nssd_blocks=None):
        seen["nssd_blocks"] = nssd_blocks
        return [], []

    with _patched(*_oa_targets(), (a, "_retrieve_chinese", spy)):
        a.run_agent_search("数字经济 共同富裕", _agent_cfg(), per_strategy=5, now_year=2026,
                           with_nssd=True, lang="both",
                           zh_blocks=[["数字经济", "数字化"], ["共同富裕"]])
    assert seen["nssd_blocks"] == [["数字经济", "数字化"], ["共同富裕"]]


# ---------------------------------------------------------------------------
# Standalone runner (mirrors the other search_export test files)
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_render_style_detection,
    test_platform_vocab_routing,
    test_vocab_routing_exact_no_substring_collisions,
    test_sinomed_does_not_ingest_mesh_candidates,
    test_pubmed_reproduction_linter_clean,
    test_wos_reproduction_linter_clean,
    test_cnki_reproduction_byte_identical_and_clean,
    test_literal_spec_examples_lint_clean,
    test_generate_full_schema_completeness,
    test_controlled_vocab_term_shape_and_descriptor_ui,
    test_write_outputs_creates_both_files,
    test_run_one_shot_writes_files,
    test_mesh_hallucination_culled_and_downgraded_to_free_text,
    test_mesh_downgrade_does_not_duplicate_existing_free_text,
    test_verify_vocab_false_is_offline_and_lint_safe,
    test_deeplink_a_tier_constructed_and_bc_not,
    test_cv_clause_snapshots_per_host,
    test_eric_cv_clause_prefix_colon,
    test_cochrane_cv_clause_omitted_not_illegal,
    test_scopus_whole_query_wrapped_in_title_abs_key,
    test_sinomed_cmesh_machine_expr_pending_manual,
    test_operator_logic_or_honoured,
    test_operator_logic_declared_order_and_unreferenced_note,
    test_operator_logic_unparseable_withholds,
    test_operator_logic_missing_defaults_to_and_with_note,
    test_cjk_host_withholds_without_free_text_zh,
    test_bilingual_channels_no_cross_pollution,
    test_proximity_only_block_delivers_fallback_not_empty,
    test_empty_or_malformed_concept_model_withheld,
    test_line_form_grammar_read_from_card,
    test_embase_offline_unverified_is_not_withheld,
    test_embase_online_pending_manual_is_not_withheld,
    test_cli_bad_json_and_missing_file_error_cleanly,
    test_cli_missing_platforms_errors_and_happy_path_offline,
    test_linter_reject_withholds_string,
    test_vocab_status_labels_no_cv,
    test_proximity_intent_rendered_and_clean,
    test_proximity_degrades_on_no_proximity_host,
    test_unknown_platform_skipped,
    test_r19_report_data_byte_identical_without_export,
    test_r19_report_data_folds_export_additively,
    test_r19_prisma_byte_identical_without_export,
    test_r19_prisma_enriched_with_export,
    test_r19_agent_envelope_default_flags_equal_explicit_defaults,
    test_with_strategies_adds_floor_only_key,
    test_zh_block_seam_default_passes_none_to_retrieve_chinese,
    test_zh_block_forwarded_to_nssd,
]


def main() -> int:
    passed, failed = 0, 0
    for fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{len(ALL_TESTS)} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
