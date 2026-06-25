"""Tests for scripts/journal_rank.py — multi-platform journal-rank data layer.

Everything here is deterministic and network-free. The three platform CSVs are
small inline samples that reproduce the REAL headers fetched 2026-06-25 (CAS
comma + 大类分区 "3 [168/495]"; JCR comma + IF(2024); SJR semicolon + European
decimals + the live 27-col header that added an SDG column). HTTP is exercised via
an injected fake ``requests.Session`` — the real network (GitHub raw) is NEVER
touched, so this test does not depend on connectivity and burns zero quota.

Coverage:
  - ISSN normalisation: hyphenated (JCR/CAS), hyphen-free (SJR), lower-x, N/A, multi
  - CAS parse: 大类分区 tier+rank, Top flag, multi 小类 minor[], slash ISSN, fuzzy
    header ("OA Journal Index（OAJ）" not "OAJ"), year
  - JCR parse: IF(2024) real float, quartile, rank "1/326", multi-category, N/A ISSN
  - SJR parse: semicolon, European decimals, per-category quartiles, blank-best
    derivation, the live SDG-bearing header (by-name column resolution)
  - unified table merge: a journal on all 3 platforms -> one record, all slots
  - lookup: cross-format ISSN join, multi-ISSN, miss -> None, matched_issn
  - cache: init-once (fresh cache not re-fetched), force re-fetch, stale re-fetch
  - graceful degradation: 404 source / network error / no cache -> None, no crash
  - CLI fetch/lookup/info via injected session + temp cache

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 -m tests.test_journal_rank
or via pytest:
    PYTHONPATH=. python3 -m pytest tests/test_journal_rank.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import journal_rank as jr  # noqa: E402
from scripts.types import CASRank, JCRRank, JournalRank, SJRRank  # noqa: E402


# ---------------------------------------------------------------------------
# Inline sample CSVs — real headers (2026-06-25), small bodies.
# ---------------------------------------------------------------------------

# CAS: comma CSV; live header uses "OA Journal Index（OAJ）" (full-width parens).
# 大类分区 "3 [168/495]"; up to six 小类; slash-joined hyphenated ISSN/EISSN.
_CAS_CSV = (
    "Journal,年份,ISSN/EISSN,Review,OA Journal Index（OAJ）,Open Access,"
    "Web of Science,标注,大类,大类分区,Top,小类1,小类1分区,小类2,小类2分区,"
    "小类3,小类3分区,小类4,小类4分区,小类5,小类5分区,小类6,小类6分区\n"
    # Nature: 大类一区, Top=是, two 小类
    "Nature,2025,0028-0836/1476-4687,否,否,否,SCIE,,综合性期刊,1 [2/74],是,"
    " MULTIDISCIPLINARY SCIENCES 综合性期刊,1 [2/74],,,,,,,,,,\n"
    # JPSP: CAS 一区 (psychology), Top=否, one 小类
    "Journal of Personality and Social Psychology,2025,0022-3514/1939-1315,"
    "否,否,否,SSCI,,心理学,1 [5/220],否, PSYCHOLOGY SOCIAL 心理学：社会,"
    "1 [5/64],,,,,,,,,,\n"
    # 3D Printing: 医学 三区, two 小类 (multi-minor exercise)
    "3D Printing in Medicine,2025,2365-6271/2365-6271,否,否,是,ESCI,,医学,"
    "3 [1379/5603],否, RADIOLOGY 核医学,3 [56/206], ENGINEERING 工程,"
    "4 [60/70],,,,,,,,\n"
    # No-ISSN row -> skipped (unjoinable)
    "Ghost Journal,2025,/,否,否,否,SCIE,,综合,4 [9/10],否,,,,,,,,,,,,\n"
)

# JCR: comma CSV; IF(2024) real float; ISSN+eISSN hyphenated, may be N/A.
_JCR_CSV = (
    "Journal,ISSN,eISSN,Category,IF(2024),IF Quartile(2024),IF Rank(2024)\n"
    "NATURE,0028-0836,1476-4687,MULTIDISCIPLINARY SCIENCES(SCIE),50.5,Q1,1/74\n"
    "JOURNAL OF PERSONALITY AND SOCIAL PSYCHOLOGY,0022-3514,1939-1315,"
    "PSYCHOLOGY SOCIAL(SSCI),7.6,Q1,3/64\n"
    # Multi-category + a journal with N/A primary ISSN (eISSN still joins)
    "Nature Reviews Earth & Environment,N/A,2662-138X,"
    '"ENVIRONMENTAL SCIENCES(SCIE);GEOSCIENCES, MULTIDISCIPLINARY(SCIE)",71.5,Q1,1/374\n'
    # A mid-tier-only-in-JCR journal (Q3) to exercise jcr-only records
    "Mid Tier Journal,1234-5678,8765-4321,MATERIALS SCIENCE(SCIE),1.2,Q3,300/400\n"
)

# SJR: SEMICOLON CSV; European decimals (145,004); live 27-col header w/ SDG;
# Issn comma-joined hyphen-free; Categories carry per-category quartiles.
_SJR_CSV = (
    "Rank;Sourceid;Title;Type;Issn;Publisher;Open Access;Open Access Diamond;SJR;"
    "SJR Best Quartile;H index;Total Docs. (2024);Total Docs. (3years);Total Refs.;"
    "Total Citations (3years);Citable Docs. (3years);Citations / Doc. (2years);"
    "Ref. / Doc.;%Female;Overton;SDG;Country;Region;Publisher;Coverage;"
    "Categories;Areas\n"
    '1;1;"Nature";journal;"00280836, 14764687";"Nature Research";No;No;18,500;Q1;'
    "1331;800;2400;50000;90000;2300;15,2;30,1;45;100;200;United Kingdom;"
    'Western Europe;"Nature Research";"1869-2025";'
    '"Multidisciplinary (Q1)";"Multidisciplinary"\n'
    '2;2;"Journal of Personality and Social Psychology";journal;'
    '"00223514, 19391315";"American Psychological Association";No;No;5,123;Q1;757;'
    "200;600;8000;9000;590;3,2;45,1;55;10;20;United States;Northern America;"
    '"American Psychological Association";"1965-2024";'
    '"Social Psychology (Q1); Sociology and Political Science (Q2)";"Psychology"\n'
    # Blank best quartile -> derive Q2 from categories (best of Q2,Q4)
    '3;3;"Blank Quartile Journal";journal;"99887766";"Pub X";Yes;No;0,300;;12;'
    "20;50;500;100;48;0,5;10;50;0;3;Canada;Northern America;"
    '"Pub X";"2015-2024";"Education (Q2); Linguistics (Q4)";"Social Sciences"\n'
    # No-ISSN row -> skipped
    '4;4;"No ISSN";journal;"";"Ghost";No;No;0,100;;5;10;30;100;20;28;0,1;5,0;50;'
    '0;1;Unknown;Unknown;"Ghost";"2020-2024";"";"Misc"\n'
)


# ---------------------------------------------------------------------------
# Fake injectable session (no network)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status, content: bytes):
        self.status_code = status
        self.content = content


class _FakeSession:
    """Returns a canned response per URL substring; counts calls for init-once."""

    def __init__(self, mapping, *, raise_on=None):
        self.mapping = mapping  # {url_substr: _FakeResp}
        self.raise_on = raise_on or set()  # url substrings that raise
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        for substr in self.raise_on:
            if substr in url:
                import requests as _rq
                raise _rq.RequestException("boom")
        for substr, resp in self.mapping.items():
            if substr in url:
                return resp
        return _FakeResp(404, b"")


def _full_session():
    return _FakeSession({
        "FQBJCR": _FakeResp(200, _CAS_CSV.encode("utf-8")),
        "JCR2024": _FakeResp(200, _JCR_CSV.encode("utf-8")),
        "scimagojr": _FakeResp(200, _SJR_CSV.encode("utf-8")),
    })


# ===========================================================================
# ISSN normalisation
# ===========================================================================


def test_normalize_issn_formats():
    assert jr.normalize_issn("0028-0836") == "0028-0836"     # hyphenated (JCR/CAS)
    assert jr.normalize_issn("00280836") == "0028-0836"      # hyphen-free (SJR)
    assert jr.normalize_issn("1542-486x") == "1542-486X"     # lower x upper-cased
    assert jr.normalize_issn("N/A") is None                  # JCR N/A
    assert jr.normalize_issn("123") is None                  # too short
    assert jr.normalize_issn("") is None
    assert jr.normalize_issn(None) is None
    print("OK  normalize_issn_formats")


def test_normalize_issns_multi_and_seps():
    # SJR comma-joined hyphen-free
    assert jr.normalize_issns("15424863, 00079235") == ["1542-4863", "0007-9235"]
    # CAS slash-joined hyphenated
    assert jr.normalize_issns("2053-1583/2053-1583", sep="/") == ["2053-1583"]
    # liberal: recovers both even with the "wrong" sep
    assert jr.normalize_issns("0028-0836/1476-4687") == ["0028-0836", "1476-4687"]
    assert jr.normalize_issns("") == []
    print("OK  normalize_issns_multi_and_seps")


# ===========================================================================
# CAS parse
# ===========================================================================


def test_parse_cas_partition_helper():
    assert jr._parse_cas_partition("3 [168/495]") == (3, "168/495")
    assert jr._parse_cas_partition("1 [2/74]") == (1, "2/74")
    assert jr._parse_cas_partition("4") == (4, None)
    assert jr._parse_cas_partition("") == (None, None)
    assert jr._parse_cas_partition(None) == (None, None)
    print("OK  parse_cas_partition_helper")


def test_parse_cas_csv():
    recs = jr.parse_cas_csv(_CAS_CSV)
    assert len(recs) == 3  # Ghost (no ISSN) skipped
    by_issn = {}
    for r in recs:
        for i in r.issns:
            by_issn[i] = r
    nat = by_issn["0028-0836"]
    assert nat.cas.tier == 1
    assert nat.cas.rank == "2/74"
    assert nat.cas.top is True
    assert nat.issns == ["0028-0836", "1476-4687"]  # slash-split both indexed
    assert nat.cas.source_year == 2025
    # 3D Printing: two minor categories
    tdp = by_issn["2365-6271"]
    assert tdp.cas.tier == 3
    assert len(tdp.cas.minor) == 2
    assert tdp.cas.minor[0]["tier"] == 3 and "RADIOLOGY" in tdp.cas.minor[0]["category"]
    assert tdp.cas.minor[1]["tier"] == 4
    print("OK  parse_cas_csv")


# ===========================================================================
# JCR parse
# ===========================================================================


def test_parse_jcr_csv():
    recs = jr.parse_jcr_csv(_JCR_CSV)
    assert len(recs) == 4
    by_issn = {}
    for r in recs:
        for i in r.issns:
            by_issn[i] = r
    nat = by_issn["0028-0836"]
    assert nat.jcr.impact_factor == 50.5   # real IF, US decimal
    assert nat.jcr.quartile == "Q1"
    assert nat.jcr.rank == "1/74"
    assert nat.jcr.source_year == 2024
    # N/A primary ISSN -> only eISSN joins
    nre = by_issn["2662-138X"]
    assert nre.jcr.quartile == "Q1"
    assert "GEOSCIENCES" in nre.jcr.category  # multi-category preserved raw
    print("OK  parse_jcr_csv")


# ===========================================================================
# SJR parse
# ===========================================================================


def test_parse_sjr_csv_semicolon_european_and_sdg_header():
    recs = jr.parse_sjr_csv(_SJR_CSV)
    assert len(recs) == 3  # No-ISSN row skipped
    by_issn = {}
    for r in recs:
        for i in r.issns:
            by_issn[i] = r
    jpsp = by_issn["0022-3514"]
    assert jpsp.sjr.best_quartile == "Q1"
    assert jpsp.sjr.sjr == 5.123  # European decimal parsed despite the SDG col
    cats = {c["category"]: c["quartile"] for c in jpsp.sjr.per_category}
    assert cats == {"Social Psychology": "Q1", "Sociology and Political Science": "Q2"}
    # blank best quartile -> derived as best (min) of categories
    blank = by_issn["9988-7766"]
    assert blank.sjr.best_quartile == "Q2"  # best of Q2, Q4
    print("OK  parse_sjr_csv_semicolon_european_and_sdg_header")


# ===========================================================================
# Unified table merge + lookup
# ===========================================================================


def _loaded_lookup(cache_dir: Path) -> jr.RankLookup:
    """Fetch (fake session) into cache then load — the realistic round-trip."""
    sess = _full_session()
    jr.fetch(cache_dir=cache_dir, session=sess)
    lk = jr.load(cache_dir=cache_dir)
    assert lk is not None
    return lk


def test_unified_merge_all_three_platforms():
    with tempfile.TemporaryDirectory() as td:
        lk = _loaded_lookup(Path(td))
    # Nature is on all three; one merged record carries cas+jcr+sjr.
    nat = lk.lookup("0028-0836")
    assert nat is not None
    assert set(nat.matched_platforms) == {"cas", "jcr", "sjr"}
    assert nat.cas.tier == 1
    assert nat.jcr.impact_factor == 50.5  # real IF only from JCR
    assert nat.sjr.best_quartile == "Q1"
    assert nat.matched_issn == "0028-0836"
    print("OK  unified_merge_all_three_platforms")


def test_lookup_cross_format_and_multi_issn():
    with tempfile.TemporaryDirectory() as td:
        lk = _loaded_lookup(Path(td))
    # JPSP joins on either ISSN, in any format.
    a = lk.lookup("0022-3514")          # hyphenated
    b = lk.lookup("19391315")           # hyphen-free eISSN (SJR style)
    assert a is not None and b is not None
    assert a is b                        # same merged record
    assert a.cas.tier == 1 and a.jcr.quartile == "Q1" and a.sjr.best_quartile == "Q1"
    # list-of-ISSNs input
    c = lk.lookup(["0000-0000", "0022-3514"])
    assert c is a
    # miss
    assert lk.lookup("0000-0000") is None
    print("OK  lookup_cross_format_and_multi_issn")


def test_lookup_single_platform_journal():
    with tempfile.TemporaryDirectory() as td:
        lk = _loaded_lookup(Path(td))
    # Mid Tier Journal exists only in JCR (Q3) -> jcr filled, cas/sjr None.
    mid = lk.lookup("1234-5678")
    assert mid is not None
    assert mid.matched_platforms == ["jcr"]
    assert mid.jcr.quartile == "Q3"
    assert mid.cas is None and mid.sjr is None
    print("OK  lookup_single_platform_journal")


def test_info_reports_platforms_and_counts():
    with tempfile.TemporaryDirectory() as td:
        lk = _loaded_lookup(Path(td))
        info = lk.info()
    assert set(info["loaded_platforms"]) == {"cas", "jcr", "sjr"}
    assert info["journals_per_platform"]["cas"] == 3
    assert info["journals_per_platform"]["jcr"] == 4
    assert info["journals_per_platform"]["sjr"] == 3
    assert "cas" in info["attribution"] and "scimagojr" in info["attribution"]["sjr"]
    json.dumps(info)  # JSON-safe
    print("OK  info_reports_platforms_and_counts")


# ===========================================================================
# Cache: init-once / force / stale
# ===========================================================================


def test_fetch_init_once_does_not_refetch_fresh_cache():
    with tempfile.TemporaryDirectory() as td:
        sess1 = _full_session()
        jr.fetch(cache_dir=Path(td), session=sess1)
        assert len(sess1.calls) == 3  # first time: all three fetched
        # second call with a fresh cache: NO network calls (init-once).
        sess2 = _full_session()
        res = jr.fetch(cache_dir=Path(td), session=sess2)
        assert sess2.calls == []  # nothing re-fetched
        assert all(v is not None for v in res.values())
    print("OK  fetch_init_once_does_not_refetch_fresh_cache")


def test_fetch_force_refetches():
    with tempfile.TemporaryDirectory() as td:
        jr.fetch(cache_dir=Path(td), session=_full_session())
        sess = _full_session()
        jr.fetch(cache_dir=Path(td), session=sess, force=True)
        assert len(sess.calls) == 3  # force overrides init-once
    print("OK  fetch_force_refetches")


def test_fetch_stale_cache_refetches():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        jr.fetch(cache_dir=td, session=_full_session())
        # age the cached files well past stale_days
        old = time.time() - 400 * 86400
        for p in td.glob("*.csv"):
            import os
            os.utime(p, (old, old))
        sess = _full_session()
        jr.fetch(cache_dir=td, session=sess, stale_days=365)
        assert len(sess.calls) == 3  # stale -> re-fetched
    print("OK  fetch_stale_cache_refetches")


def test_fetch_single_platform():
    with tempfile.TemporaryDirectory() as td:
        sess = _full_session()
        res = jr.fetch(platform="sjr", cache_dir=Path(td), session=sess)
        assert list(res.keys()) == ["sjr"]
        assert res["sjr"] is not None
        assert len(sess.calls) == 1
    print("OK  fetch_single_platform")


# ===========================================================================
# Graceful degradation
# ===========================================================================


def test_fetch_404_source_degrades():
    with tempfile.TemporaryDirectory() as td:
        # CAS 404s, the other two succeed.
        sess = _FakeSession({
            "JCR2024": _FakeResp(200, _JCR_CSV.encode("utf-8")),
            "scimagojr": _FakeResp(200, _SJR_CSV.encode("utf-8")),
            "FQBJCR": _FakeResp(404, b""),
        })
        res = jr.fetch(cache_dir=Path(td), session=sess)
        assert res["cas"] is None          # degraded, no crash
        assert res["jcr"] is not None and res["sjr"] is not None
        lk = jr.load(cache_dir=Path(td))
        assert lk is not None
        assert "cas" not in lk.loaded_platforms
        # a JCR+SJR journal still joins; CAS slot just absent
        nat = lk.lookup("0028-0836")
        assert nat.cas is None and nat.jcr is not None and nat.sjr is not None
    print("OK  fetch_404_source_degrades")


def test_fetch_network_error_degrades():
    with tempfile.TemporaryDirectory() as td:
        sess = _FakeSession({
            "JCR2024": _FakeResp(200, _JCR_CSV.encode("utf-8")),
            "scimagojr": _FakeResp(200, _SJR_CSV.encode("utf-8")),
        }, raise_on={"FQBJCR"})
        res = jr.fetch(cache_dir=Path(td), session=sess)
        assert res["cas"] is None  # RequestException swallowed
        assert res["jcr"] is not None
    print("OK  fetch_network_error_degrades")


def test_load_returns_none_when_no_cache():
    with tempfile.TemporaryDirectory() as td:
        assert jr.load(cache_dir=Path(td)) is None
    print("OK  load_returns_none_when_no_cache")


def test_rank_to_dict_json_safe():
    rk = JournalRank(
        title="X", issns=["0028-0836"],
        cas=CASRank(tier=1, rank="2/74", top=True, minor=[{"category": "c", "tier": 1, "rank": "1/2"}], source_year=2025),
        jcr=JCRRank(quartile="Q1", impact_factor=50.5, rank="1/74", category="X(SCIE)", source_year=2024),
        sjr=SJRRank(best_quartile="Q1", sjr=18.5, per_category=[{"category": "M", "quartile": "Q1"}], source_year=2024),
        matched_issn="0028-0836", matched_platforms=["cas", "jcr", "sjr"],
    )
    d = jr.rank_to_dict(rk)
    json.dumps(d)  # must not raise
    assert d["cas"]["tier"] == 1 and d["jcr"]["impact_factor"] == 50.5
    assert jr.rank_to_dict(None) is None
    print("OK  rank_to_dict_json_safe")


# ===========================================================================
# CLI
# ===========================================================================


def test_cli_fetch_then_lookup_then_info(monkeypatch=None):
    """Drive the CLI subcommands against a temp cache + injected session.

    We patch the module's requests.Session so the CLI's internal fetch uses our
    fake (the CLI does not expose a session arg). No network.
    """
    import scripts.journal_rank as mod

    with tempfile.TemporaryDirectory() as td:
        fake = _full_session()
        orig_session = mod.requests.Session
        # also short-circuit config (CLI reads config for sources/cache_dir)
        orig_cfg = mod._load_rank_config
        mod.requests.Session = lambda: fake  # type: ignore
        mod._load_rank_config = lambda: (None, None)  # type: ignore
        try:
            rc = mod._main_cli(["fetch", "--cache-dir", td])
            assert rc == 0
            rc = mod._main_cli(["lookup", "0028-0836", "--cache-dir", td])
            assert rc == 0
            rc = mod._main_cli(["info", "--cache-dir", td])
            assert rc == 0
            # a miss returns 2
            rc = mod._main_cli(["lookup", "0000-0000", "--cache-dir", td])
            assert rc == 2
        finally:
            mod.requests.Session = orig_session  # type: ignore
            mod._load_rank_config = orig_cfg  # type: ignore
    print("OK  cli_fetch_then_lookup_then_info")


def test_cli_info_no_cache_returns_1():
    import scripts.journal_rank as mod
    with tempfile.TemporaryDirectory() as td:
        orig_cfg = mod._load_rank_config
        mod._load_rank_config = lambda: (None, None)  # type: ignore
        try:
            rc = mod._main_cli(["info", "--cache-dir", td])
            assert rc == 1
        finally:
            mod._load_rank_config = orig_cfg  # type: ignore
    print("OK  cli_info_no_cache_returns_1")


# ===========================================================================
# Runner
# ===========================================================================


def main() -> int:
    tests = [
        test_normalize_issn_formats,
        test_normalize_issns_multi_and_seps,
        test_parse_cas_partition_helper,
        test_parse_cas_csv,
        test_parse_jcr_csv,
        test_parse_sjr_csv_semicolon_european_and_sdg_header,
        test_unified_merge_all_three_platforms,
        test_lookup_cross_format_and_multi_issn,
        test_lookup_single_platform_journal,
        test_info_reports_platforms_and_counts,
        test_fetch_init_once_does_not_refetch_fresh_cache,
        test_fetch_force_refetches,
        test_fetch_stale_cache_refetches,
        test_fetch_single_platform,
        test_fetch_404_source_degrades,
        test_fetch_network_error_degrades,
        test_load_returns_none_when_no_cache,
        test_rank_to_dict_json_safe,
        test_cli_fetch_then_lookup_then_info,
        test_cli_info_no_cache_returns_1,
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
