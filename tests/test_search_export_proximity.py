"""Tests for scripts/search_export/proximity.py — canonical max_gap -> host n.

Pure + network-free: reads the in-git ``references/search_export/
proximity_table.json`` (a data file, not a network call). Covers the two families
+ standalone hosts, the Ovid adj2 ≡ EBSCO N1 equivalence the spec pins, operator-
shell rendering (infix + phrase shells), and the honest degradation signal for
no-proximity hosts.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_search_export_proximity
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_search_export_proximity.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.search_export import proximity as px  # noqa: E402


# ---------------------------------------------------------------------------
# The pinned equivalence: Ovid adj2 ≡ EBSCO N1 (same canonical k=1).
# ---------------------------------------------------------------------------


def test_ovid_adj2_equals_ebsco_n1():
    # Both render from the SAME canonical intent k=1 (<=1 intervening word).
    ovid = px.render("ovid", ["heart", "attack"], 1)
    ebsco = px.render("ebsco", ["heart", "attack"], 1)
    assert ovid.n == 2 and ovid.operator == "adj2"
    assert ebsco.n == 1 and ebsco.operator == "N1"
    assert ovid.expression == "heart adj2 attack"
    assert ebsco.expression == "heart N1 attack"
    # Inverse recovers the same canonical k -> equivalent.
    assert px.canonical_k("ovid", 2) == 1
    assert px.canonical_k("ebsco", 1) == 1
    assert px.equivalent("ovid", 2, "ebsco", 1)
    assert not px.equivalent("ovid", 2, "ebsco", 2)


# ---------------------------------------------------------------------------
# Family formulas: gap -> n=k, gap_plus_one -> n=k+1.
# ---------------------------------------------------------------------------


def test_gap_family_is_identity():
    for host in ("ebsco", "proquest", "scopus", "wos"):
        sem, in_fam = px.semantics_for(host)
        assert sem == "gap" and in_fam
        assert px.host_n(host, 3) == 3


def test_gap_plus_one_family_adds_one():
    for host in ("cochrane", "ovid", "embase_com"):
        sem, in_fam = px.semantics_for(host)
        assert sem == "gap_plus_one" and in_fam
        assert px.host_n(host, 3) == 4
        assert px.host_n(host, 0) == 1


def test_standalone_hosts_carry_own_semantics():
    # Not in the two families; n_semantics is read off the operator shell.
    for host in ("pubmed", "cnki", "ieee", "cabi"):
        sem, in_fam = px.semantics_for(host)
        assert sem == "gap" and not in_fam
        assert px.host_n(host, 2) == 2


def test_aliases_resolve_to_shell_keys():
    assert px.host_n("cochrane_central", 1) == 2  # -> cochrane (gap+1)
    assert px.host_n("embase.com", 1) == 2  # -> embase_com (gap+1)
    assert px.host_n("web of science", 2) == 2  # -> wos (gap)
    assert px.host_n("cinahl_ebsco", 2) == 2  # -> ebsco (gap)
    assert px.host_n("psycinfo_ovid", 1) == 2  # -> ovid (gap+1)


# ---------------------------------------------------------------------------
# Rendering: infix operators, ordered variants, phrase shells.
# ---------------------------------------------------------------------------


def test_infix_render_wos_scopus_embase():
    assert px.render("wos", ["a", "b"], 2).expression == "a NEAR/2 b"
    assert px.render("scopus", ["a", "b"], 2).expression == "a W/2 b"
    assert px.render("embase_com", ["a", "b"], 1).expression == "a NEAR/2 b"


def test_ordered_variants():
    assert px.render("scopus", ["a", "b"], 2, ordered=True).operator == "PRE/2"
    assert px.render("embase_com", ["a", "b"], 1, ordered=True).operator == "NEXT/2"
    assert px.render("ieee", ["a", "b"], 3, ordered=True).operator == "ONEAR/3"
    # ordered=False keeps the unordered operator
    assert px.render("scopus", ["a", "b"], 2).operator == "W/2"


def test_phrase_shell_pubmed_embeds_field_and_terms():
    r = px.render("pubmed", ["sleep", "therapy"], 3, field_code="tiab")
    assert r.expression == '"sleep therapy"[tiab:~3]'
    assert r.operator is None  # phrase shell has no bare infix operator
    assert r.n == 3
    # default field falls back to the shell's first declared field
    assert px.render("pubmed", ["a", "b"], 1).expression.endswith(":~1]")


def test_phrase_shell_cabi_slop():
    assert px.render("cabi", ["a", "b"], 2).expression == '"a b"~2'


def test_cnki_infix_positional():
    assert px.render("cnki", ["大数据", "隐私"], 1).expression == "大数据 /NEAR 1 隐私"


# ---------------------------------------------------------------------------
# Degradation: no-proximity hosts return an honest signal, never an operator.
# ---------------------------------------------------------------------------


def test_no_proximity_hosts_degrade():
    for host in ("acm", "clinicaltrials_gov", "wanfang", "eric", "scifinder",
                 "sinomed"):
        r = px.render(host, ["a", "b"], 2)
        assert r.supported is False, host
        assert r.expression is None, host
        assert r.operator is None, host
        assert r.n is None, host
        assert r.fallback, host  # a concrete fallback strategy is present
        assert px.semantics_for(host)[0] is None, host
        assert px.host_n(host, 2) is None, host
        assert px.canonical_k(host, 2) is None, host


def test_no_proximity_constant_matches_table():
    # The convenience frozenset must match the table's unordered=null hosts.
    table = px.load_table()
    from_table = {
        h for h, shell in table["operator_shells"].items()
        if shell.get("unordered") is None
    }
    assert from_table == set(px.NO_PROXIMITY_HOSTS)


# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------


def test_unknown_host_raises():
    try:
        px.render("not_a_host", ["a", "b"], 1)
    except px.UnknownHostError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownHostError")


def test_negative_k_rejected():
    try:
        px.render("wos", ["a", "b"], -1)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for negative k")


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
