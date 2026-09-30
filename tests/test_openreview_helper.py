"""Tests for scripts/openreview_helper.py.

All core tests are OFFLINE: a fake session serves recorded responses from
tests/fixtures/openreview_*.json (real anonymous /notes/search pages captured
2026-10-01, trimmed to the fields the helper reads) plus a few synthetic notes
for venueid forms the capture did not contain. The page sleep is replaced, so
nothing actually sleeps. One optional live smoke test is marked ``live`` and is
deselected by default (pytest.ini).

Run from skill root:
    HOME=<empty dir> PYTHONPATH=. python -m pytest tests/test_openreview_helper.py -q \
        -p no:cacheprovider --disable-socket --allow-unix-socket
"""

from __future__ import annotations

import copy
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

import pytest  # noqa: E402
import requests  # noqa: E402  (at collection time, before sockets are blocked)
from scripts import openreview_helper as orh  # noqa: E402
from scripts.types import UnifiedPaperEntity  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


PAGE1 = _load("openreview_search_page1.json")          # full page (25), every venueid class
PAGE2 = _load("openreview_search_page2.json")          # short last page (7)
CHALLENGE = _load("openreview_challenge_403.json")     # real 403 ChallengeRequiredError body

# The 17 accepted notes across the two fixture pages, in relevance order.
EXPECTED_ACCEPTED = [
    ("NeurIPS 2025 Poster", 2025, "Continuous Diffusion Model for Language Modeling"),
    ("ICLR 2026 Poster", 2026, "FlashDLM"),
    ("ICML 2026", 2026, "Simple Denoising Diffusion Language Models"),
    ("ICLR 2026 Oral", 2026, "Diffusion Language Model Knows the Answer Before It Decodes"),
    ("COLM 2026", 2026, "Mask-Aware Policy Gradients"),
    ("EMNLP 2023 Findings", 2023, "GRACE"),
    ("EMNLP 2023", 2023, "A Cheaper and Better Diffusion Language Model"),
    ("KSMI 2026", 2026, "Music Tagging Graph Neural Network"),
    ("WWW 2025 Poster", 2025, "LargePiG"),
    ("TMLR", 2024, "LLM-grounded Diffusion"),
    ("ICML 2025 Spotlight", 2025, "UniDB"),
    ("ICML 2026 Spotlight", 2026, "HDFlow"),
    ("ICML 2026", 2026, "Efficient-DLM"),
    ("NeurIPS 2025 Poster", 2025, "Anchored Diffusion Language Model"),
    ("ICLR 2026 Poster", 2026, "Don't Settle Too Early"),
    ("ICLR 2024 Poster", 2024, "Learning Multi-Agent Communication"),
    ("TMLR", 2026, "Cost-Aware Routing"),
]


# ---------------------------------------------------------------------------
# Fake HTTP layer
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return copy.deepcopy(self._payload)


class _FakeSession:
    """Serves one scripted response per page; records every request.

    ``responses`` items are a payload dict (served with 200), a (payload, status)
    tuple, or an Exception instance (raised by get()). Requests past the end get
    an empty last page."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "params": dict(params or {}),
                           "headers": dict(headers or {}), "timeout": timeout})
        i = len(self.calls) - 1
        item = self.responses[i] if i < len(self.responses) else {"notes": [], "count": 10000}
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            return _FakeResp(*item)
        return _FakeResp(item)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Replace the page sleep; tests read the recorded durations instead."""
    slept = []
    monkeypatch.setattr(orh, "_sleep", lambda s: slept.append(s))
    return slept


def _note(venueid, venue=None, *, nid="abc123", title="A Paper Title", pdate=None,
          cdate=None, authors=("Ada Lovelace", "Alan Turing"), pdf=True, **content):
    """A synthetic API v2 note."""
    c = {"title": {"value": title}, "venueid": {"value": venueid}}
    if venue is not None:
        c["venue"] = {"value": venue}
    if authors is not None:
        c["authors"] = {"value": list(authors)}
    if pdf:
        c["pdf"] = {"value": "/pdf/0000.pdf"}
    for k, v in content.items():
        c[k] = {"value": v}
    note = {"id": nid, "forum": nid, "content": c}
    if pdate is not None:
        note["pdate"] = pdate
    if cdate is not None:
        note["cdate"] = cdate
    return note


def _page(*notes):
    return {"count": 10000, "notes": list(notes)}


def _full_page(prefix, venueid="ICLR.cc/2026/Conference", venue="ICLR 2026 Poster"):
    return _page(*[_note(venueid, venue, nid=f"{prefix}{i}", title=f"Paper {prefix} {i}")
                   for i in range(orh._PAGE_SIZE)])


# ---------------------------------------------------------------------------
# Whitelist (venueid decides; venue strings never do)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("venueid, expected", [
    ("ICLR.cc/2026/Conference", ("conference", 2026)),
    ("NeurIPS.cc/2025/Conference", ("conference", 2025)),
    ("ICML.cc/2026/Conference", ("conference", 2026)),
    ("colmweb.org/COLM/2026/Conference", ("conference", 2026)),
    ("EMNLP/2023/Conference", ("conference", 2023)),
    ("ACM.org/TheWebConf/2025/Conference", ("conference", 2025)),
    ("music-informatics.kr/KSMI/2026/Conference", ("conference", 2026)),
    ("TMLR", ("tmlr", None)),
])
def test_whitelist_accepts_main_conference_and_tmlr(venueid, expected):
    assert orh._accepted_kind(venueid) == expected


@pytest.mark.parametrize("venueid", [
    # rejected / withdrawn / under review
    "ICLR.cc/2026/Conference/Rejected_Submission",
    "ICLR.cc/2026/Conference/Withdrawn_Submission",
    "ICML.cc/2025/Conference/Rejected_Submission",
    "SwissText.org/2026/Conference/Submission",
    "aclweb.org/ACL/ARR/2026/January/Submission",
    "NeurIPS.cc/2025/Datasets_and_Benchmarks_Track/Rejected_Submission",
    # workshops
    "ICLR.cc/2026/Workshop/Gen2",
    "colmweb.org/COLM/2026/Workshop/NonAR-LM",
    "NeurIPS.cc/2026/Workshop/WiML/Rejected_Submission",
    "IEEE.org/ICRA/2025/Workshop/FMNS",
    # TMLR non-accepted states
    "TMLR/Rejected",
    "TMLR/Withdrawn_Submission",
    "TMLR/Under_Review",
    "TMLR/Decision_Pending",
    # profile imports / anonymous preprints
    "OpenReview.net/Archive",
    "OpenReview.net/Public_Article",
    "OpenReview.net/Anonymous_Preprint",
    "dblp.org/journals/CORR/2024",
    "dblp.org/conf/NIPS/2024",
    "dblp.org/conf/NAACL/2025",
    # tracks outside the spec's whitelist (kept out on purpose)
    "NeurIPS.cc/2025/Datasets_and_Benchmarks_Track",
    "NeurIPS.cc/2023/Track/Datasets_and_Benchmarks",
    # malformed near-misses
    "", "tmlr", " TMLR", "TMLR ", "ICLR.cc/2026/Conference/", "ICLR.cc/26/Conference",
    "/2026/Conference", "ICLR.cc/2026/conference", None, 2026, ["TMLR"],
])
def test_whitelist_rejects_everything_else(venueid):
    assert orh._accepted_kind(venueid) is None


def test_venue_string_never_admits_a_rejected_paper():
    """A rejected / imported record stays out even when its venue string looks
    exactly like an accepted paper's."""
    fakes = [
        _note("ICLR.cc/2026/Conference/Rejected_Submission", "ICLR 2026 Oral", nid="r1", title="R1"),
        _note("dblp.org/conf/NIPS/2024", "NeurIPS 2024", nid="r2", title="R2"),
        _note("OpenReview.net/Public_Article", "ICML 2025 Poster", nid="r3", title="R3"),
        _note("TMLR/Rejected", "Accepted by TMLR", nid="r4", title="R4"),
    ]
    sess = _FakeSession([_page(*fakes)])
    assert orh.search("q", n=10, session=sess) == []
    assert orh.last_search_stats["records_seen"] == 4
    assert orh.last_search_stats["accepted_seen"] == 0


def test_accepted_venueid_with_misleading_venue_string_gets_clean_label():
    """Accepted by venueid, but the venue string says 'Submitted to …': the label
    comes from the venueid, and 'Submitted' never reaches the output."""
    e = orh._note_to_entity(_note("ICLR.cc/2026/Conference", "Submitted to ICLR 2026"))
    assert e is not None and e.venue == "ICLR 2026"


def test_fixture_pages_keep_exactly_the_accepted_notes():
    sess = _FakeSession([PAGE1, PAGE2])
    out = orh.search("diffusion language model", n=100, session=sess)
    got = [(e.venue, e.year, e.title) for e in out]
    assert len(got) == len(EXPECTED_ACCEPTED)
    for (venue, year, title), (ev, ey, et) in zip(got, EXPECTED_ACCEPTED):
        assert (venue, year) == (ev, ey), title
        assert title.startswith(et), (title, et)
    # Nothing from the excluded classes leaks through, by label or by id.
    for e in out:
        assert "Submitted" not in e.venue and "Workshop" not in e.venue
        assert "OpenReview" not in e.venue and "CoRR" not in e.venue
    assert orh.last_search_stats == {
        "query": "diffusion language model", "pages_fetched": 2, "records_seen": 32,
        "accepted_seen": 17, "kept": 17, "stopped": "end_of_results",
    }


# ---------------------------------------------------------------------------
# Venue label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("venueid, venue, expected", [
    ("ICLR.cc/2026/Conference", "ICLR 2026 Oral", "ICLR 2026 Oral"),
    ("ICLR.cc/2026/Conference", "ICLR 2026 Poster", "ICLR 2026 Poster"),
    ("ICLR.cc/2024/Conference", "ICLR 2024 poster", "ICLR 2024 Poster"),
    ("ICLR.cc/2025/Conference", "ICLR 2025 Spotlight", "ICLR 2025 Spotlight"),
    ("ICLR.cc/2023/Conference", "ICLR 2023 notable top 5%", "ICLR 2023"),
    ("NeurIPS.cc/2025/Conference", "NeurIPS 2025 poster", "NeurIPS 2025 Poster"),
    ("NeurIPS.cc/2024/Conference", "NeurIPS 2024 oral", "NeurIPS 2024 Oral"),
    ("ICML.cc/2026/Conference", "ICML 2026 regular", "ICML 2026"),
    ("ICML.cc/2026/Conference", "ICML 2026 spotlight", "ICML 2026 Spotlight"),
    ("ICML.cc/2025/Conference", "ICML 2025 spotlightposter", "ICML 2025 Spotlight"),
    ("colmweb.org/COLM/2026/Conference", "COLM 2026", "COLM 2026"),
    ("EMNLP/2023/Conference", "EMNLP 2023 Findings", "EMNLP 2023 Findings"),
    ("EMNLP/2023/Conference", "EMNLP 2023 Main", "EMNLP 2023"),
    ("ACM.org/TheWebConf/2025/Conference", "WWW 2025 Poster", "WWW 2025 Poster"),
    # one token, so no false "Oral"
    ("music-informatics.kr/KSMI/2026/Conference", "KSMI 2026 ShortOralPoster", "KSMI 2026"),
    # no usable venue string -> name from the venueid segment before the year
    ("colmweb.org/COLM/2026/Conference", None, "COLM 2026"),
    ("ICLR.cc/2026/Conference", None, "ICLR 2026"),
    ("EMNLP/2023/Conference", "", "EMNLP 2023"),
    ("ACM.org/TheWebConf/2025/Conference", "The Web Conference", "TheWebConf 2025"),
    # year in the string disagrees with the venueid -> the venueid wins
    ("ICLR.cc/2026/Conference", "ICLR 2025 Oral", "ICLR 2026 Oral"),
    ("TMLR", "Accepted by TMLR", "TMLR"),
    ("TMLR", None, "TMLR"),
])
def test_venue_label(venueid, venue, expected):
    e = orh._note_to_entity(_note(venueid, venue, pdate=1709745597405))
    assert e is not None and e.venue == expected


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------


def _fixture_entity(title_prefix):
    """The first ACCEPTED fixture note with this title (a dblp copy may share it)."""
    for page in (PAGE1, PAGE2):
        for note in page["notes"]:
            if note["content"]["title"]["value"].startswith(title_prefix):
                e = orh._note_to_entity(note)
                if e is not None:
                    return note, e
    raise AssertionError(title_prefix)


def test_field_mapping_iclr_oral():
    note, e = _fixture_entity("Diffusion Language Model Knows the Answer")
    assert isinstance(e, UnifiedPaperEntity)
    assert e.source_native_id == "openreview:g88nt4ieTG"
    assert e.paper_id == "openreview:g88nt4ieTG"
    assert e.sources == ["openreview"]
    assert e.type == "article"
    assert e.venue == "ICLR 2026 Oral" and e.year == 2026
    assert e.title == "Diffusion Language Model Knows the Answer Before It Decodes"
    assert e.abstract and e.abstract.startswith("Diffusion language models (DLMs)")
    assert [a.name for a in e.authors][:3] == ["Pengxiang Li", "Yefan Zhou", "Dilxat Muhtar"]
    assert e.keywords == ["diffusion language model", "discrete"]
    assert e.pdf_url == "https://openreview.net/pdf?id=g88nt4ieTG"
    assert e.oa_locations == ["https://openreview.net/forum?id=g88nt4ieTG"]
    assert e.discovery_path is None
    assert e.doi is None and e.arxiv_id is None


def test_field_mapping_tldr():
    note, e = _fixture_entity("Anchored Diffusion Language Model")
    assert e.tldr == note["content"]["TLDR"]["value"].strip()
    assert e.venue == "NeurIPS 2025 Poster"


def test_pdf_url_only_when_the_note_has_a_pdf():
    """The KSMI 2026 note carries no pdf: emitting a pdf URL would be a dead link."""
    note, e = _fixture_entity("Music Tagging Graph Neural Network")
    assert "pdf" not in note["content"]
    assert e.pdf_url is None
    assert e.oa_locations == [f"https://openreview.net/forum?id={note['forum']}"]


def test_forum_id_is_the_native_id_even_when_note_id_differs():
    n = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="noteX")
    n["forum"] = "forumY"
    e = orh._note_to_entity(n)
    assert e.source_native_id == "openreview:forumY"
    assert e.pdf_url == "https://openreview.net/pdf?id=noteX"
    assert e.oa_locations == ["https://openreview.net/forum?id=forumY"]


def test_authors_accept_fullname_objects_and_skip_junk():
    n = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster",
              authors=[{"fullname": "Ada Lovelace", "username": "~Ada1"}, "  Alan Turing ",
                       {"username": "~x"}, None, 7, ""])
    assert [a.name for a in orh._note_to_entity(n).authors] == ["Ada Lovelace", "Alan Turing"]


def test_api_v1_unwrapped_values_are_read():
    n = {"id": "v1", "forum": "v1", "content": {
        "title": "Old Style", "venueid": "ICLR.cc/2022/Conference", "venue": "ICLR 2022 Oral",
        "authors": ["A B"], "keywords": ["k"], "pdf": "/pdf/x.pdf"}}
    e = orh._note_to_entity(n)
    assert (e.title, e.venue, e.year, [a.name for a in e.authors]) == ("Old Style", "ICLR 2022 Oral", 2022, ["A B"])


def test_note_without_title_or_id_is_dropped():
    assert orh._note_to_entity(_note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", title="   ")) is None
    n = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster")
    n.pop("id"), n.pop("forum")
    assert orh._note_to_entity(n) is None
    assert orh._note_to_entity({"id": "x"}) is None
    assert orh._note_to_entity({"id": "x", "content": "oops"}) is None


# ---------------------------------------------------------------------------
# Year: venueid for conferences, pdate -> cdate for TMLR; client-side filter
# ---------------------------------------------------------------------------


def test_tmlr_year_from_pdate_then_cdate():
    # pdate 2024-03-06, cdate 2023-10-24 (the real fixture note's values)
    both = _note("TMLR", "Accepted by TMLR", pdate=1709745597405, cdate=1698133346337)
    only_c = _note("TMLR", "Accepted by TMLR", cdate=1698133346337)
    neither = _note("TMLR", "Accepted by TMLR")
    assert orh._note_to_entity(both).year == 2024
    assert orh._note_to_entity(only_c).year == 2023
    assert orh._note_to_entity(neither).year is None


def test_conference_year_comes_from_venueid_not_dates():
    n = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", pdate=1609459200000)  # 2021
    assert orh._note_to_entity(n).year == 2026


@pytest.mark.parametrize("year_min, year_max, expected_years", [
    (2025, None, {2025, 2026}),
    (None, 2024, {2023, 2024}),
    (2024, 2025, {2024, 2025}),
    (2026, 2026, {2026}),
    (2030, None, set()),
])
def test_year_filter_client_side(year_min, year_max, expected_years):
    out = orh.search("q", n=100, year_min=year_min, year_max=year_max,
                     session=_FakeSession([PAGE1, PAGE2]))
    assert {e.year for e in out} == expected_years
    everything = [y for _, y, _ in EXPECTED_ACCEPTED]
    assert len(out) == sum(1 for y in everything if y in expected_years)


def test_year_filter_drops_unknown_year_only_when_a_bound_is_set():
    tmlr_no_date = _note("TMLR", "Accepted by TMLR", nid="t0", title="No Date")
    assert len(orh.search("q", n=5, session=_FakeSession([_page(tmlr_no_date)]))) == 1
    assert orh.search("q", n=5, year_min=2000, session=_FakeSession([_page(tmlr_no_date)])) == []
    assert orh.search("q", n=5, year_max=2100, session=_FakeSession([_page(tmlr_no_date)])) == []


def test_inverted_year_bounds_return_empty_without_network():
    sess = _FakeSession([PAGE1])
    assert orh.search("q", year_min=2026, year_max=2025, session=sess) == []
    assert sess.calls == []


# ---------------------------------------------------------------------------
# Request contract and paging
# ---------------------------------------------------------------------------


def test_request_contract():
    sess = _FakeSession([PAGE1, PAGE2])
    orh.search("  diffusion language model ", n=100, session=sess)
    assert [c["params"]["offset"] for c in sess.calls] == [0, 25]
    for c in sess.calls:
        assert c["url"] == "https://api2.openreview.net/notes/search"
        p = c["params"]
        assert p["term"] == "diffusion language model"
        assert (p["type"], p["content"], p["group"], p["source"], p["limit"]) == (
            "terms", "all", "all", "forum", 25)
        assert c["timeout"] is not None and 0 < c["timeout"] <= 20


def test_sleep_between_pages_only(_no_sleep):
    sess = _FakeSession([_full_page("a"), _full_page("b"), _page()])
    orh.search("q", n=1000, session=sess)
    assert len(sess.calls) == 3
    assert len(_no_sleep) == 2 and all(s >= 1 for s in _no_sleep)


def test_single_page_never_sleeps(_no_sleep):
    orh.search("q", n=100, session=_FakeSession([PAGE2]))
    assert _no_sleep == []


def test_stops_as_soon_as_n_accepted_records_are_collected(_no_sleep):
    sess = _FakeSession([PAGE1, PAGE2])
    out = orh.search("q", n=5, session=sess)
    assert [e.venue for e in out] == [v for v, _, _ in EXPECTED_ACCEPTED[:5]]
    assert len(sess.calls) == 1 and _no_sleep == []
    assert orh.last_search_stats["stopped"] == "n_reached"


def test_n_counts_accepted_records_not_raw_records():
    """Page 1 has 25 notes but only 12 accepted: n=15 must read page 2."""
    sess = _FakeSession([PAGE1, PAGE2])
    out = orh.search("q", n=15, session=sess)
    assert len(out) == 15 and len(sess.calls) == 2


def test_stops_at_max_pages():
    pages = [_full_page(f"p{i}_") for i in range(20)]
    sess = _FakeSession(pages)
    out = orh.search("q", n=1000, max_pages=3, session=sess)
    assert len(sess.calls) == 3 and len(out) == 75
    assert orh.last_search_stats["stopped"] == "max_pages"


def test_default_max_pages_is_eight():
    sess = _FakeSession([_full_page(f"p{i}_") for i in range(20)])
    orh.search("q", n=1000, session=sess)
    assert len(sess.calls) == 8


def test_short_page_ends_paging():
    sess = _FakeSession([PAGE2, PAGE1])
    orh.search("q", n=1000, session=sess)
    assert len(sess.calls) == 1
    assert orh.last_search_stats["stopped"] == "end_of_results"


def test_empty_page_ends_paging():
    sess = _FakeSession([_page()])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "end_of_results"


# ---------------------------------------------------------------------------
# Failures: stop paging, return what was collected, never raise
# ---------------------------------------------------------------------------


def test_challenge_403_on_first_page_returns_empty():
    sess = _FakeSession([(CHALLENGE["body"], 403)])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "challenge"
    assert len(sess.calls) == 1


def test_challenge_403_on_later_page_keeps_earlier_results():
    sess = _FakeSession([_full_page("a"), (CHALLENGE["body"], 403), _full_page("c")])
    out = orh.search("q", n=1000, session=sess)
    assert len(out) == 25 and len(sess.calls) == 2
    assert orh.last_search_stats["stopped"] == "challenge"


def test_challenge_body_served_with_200_is_still_a_stop():
    sess = _FakeSession([CHALLENGE["body"]])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "challenge"


def test_plain_403_is_a_stop():
    sess = _FakeSession([({"name": "ForbiddenError"}, 403)])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "http_403"


def test_timeout_returns_empty():
    sess = _FakeSession([requests.exceptions.ReadTimeout("read timed out")])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "timeout"


def test_timeout_on_later_page_keeps_earlier_results():
    sess = _FakeSession([_full_page("a"), requests.exceptions.ConnectTimeout("x")])
    out = orh.search("q", n=1000, session=sess)
    assert len(out) == 25 and orh.last_search_stats["stopped"] == "timeout"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 404])
def test_non_200_is_a_stop(status):
    sess = _FakeSession([_full_page("a"), ({"name": "Err"}, status), _full_page("c")])
    out = orh.search("q", n=1000, session=sess)
    assert len(out) == 25 and len(sess.calls) == 2
    assert orh.last_search_stats["stopped"] == f"http_{status}"


def test_bad_json_returns_empty():
    sess = _FakeSession([(ValueError("Expecting value"), 200)])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "bad_json"


@pytest.mark.parametrize("payload", [
    [{"notes": []}],
    {"notes": {"a": 1}},
    {"count": 3},
    "notes",
    None,
])
def test_wrong_shape_returns_empty(payload):
    assert orh.search("q", session=_FakeSession([(payload, 200)])) == []
    assert orh.last_search_stats["stopped"] == "bad_shape"


def test_network_error_returns_empty():
    sess = _FakeSession([ConnectionError("network down")])
    assert orh.search("q", session=sess) == []
    assert orh.last_search_stats["stopped"] == "network_error"


def test_garbage_notes_are_skipped_not_fatal():
    good = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="ok", title="Good")
    junk = ["oops", None, 3, {}, {"content": None}, {"id": "x", "content": {"venueid": {"value": None}}},
            {"id": "y", "content": {"venueid": "TMLR", "title": {"value": 5}}},
            {"id": "z", "forum": 9, "content": {"venueid": "TMLR", "title": "T"}},
            {"id": "w", "content": {"venueid": "TMLR", "title": "W"}, "pdate": "2024"}]
    out = orh.search("q", session=_FakeSession([_page(*junk, good)]))
    assert [e.title for e in out] == ["W", "Good"]
    assert out[0].year is None  # a string pdate is not trusted


def test_session_that_is_not_a_session_does_not_raise():
    assert orh.search("q", session=object()) == []


def _raise_after(monkeypatch, name, k):
    real = getattr(orh, name)
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] > k:
            raise RuntimeError("boom")
        return real(*a, **kw)

    monkeypatch.setattr(orh, name, flaky)


def test_error_converting_one_note_skips_only_that_note(monkeypatch):
    _raise_after(monkeypatch, "_note_to_entity", 3)
    out = orh.search("q", n=100, session=_FakeSession([_full_page("a")]))
    assert len(out) == 3
    assert orh.last_search_stats["stopped"] == "end_of_results"


def test_unexpected_error_in_the_loop_returns_what_was_collected(monkeypatch):
    _raise_after(monkeypatch, "_title_key", 2)
    out = orh.search("q", n=100, session=_FakeSession([_full_page("a")]))
    assert len(out) == 2
    assert orh.last_search_stats["stopped"] == "error"
    assert orh.last_search_stats["kept"] == 2


@pytest.mark.parametrize("kwargs", [
    {"query": "   "}, {"query": ""}, {"query": None},
    {"query": "q", "n": 0}, {"query": "q", "n": -1}, {"query": "q", "max_pages": 0},
])
def test_degenerate_arguments_return_empty_without_network(kwargs):
    sess = _FakeSession([PAGE1])
    assert orh.search(session=sess, **kwargs) == []
    assert sess.calls == []


def test_default_requests_path_degrades_to_empty(monkeypatch):
    """session=None goes through the real ``requests`` module; a connection
    failure there must still return [] rather than raise. requests.get is
    replaced, so this never reaches the network even without --disable-socket."""
    def boom(*a, **kw):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", boom)
    assert orh.search("diffusion language model", n=3) == []
    assert orh.last_search_stats["stopped"] == "network_error"


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------


def test_dedup_by_forum_across_pages():
    first = _full_page("a")
    repeat = _page(_note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="a3", title="Paper a 3"),
                   _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="new", title="Fresh"))
    out = orh.search("q", n=1000, session=_FakeSession([first, repeat]))
    ids = [e.source_native_id for e in out]
    assert ids.count("openreview:a3") == 1 and "openreview:new" in ids and len(out) == 26


def test_dedup_by_normalised_title_keeps_first():
    a = _note("NeurIPS.cc/2025/Conference", "NeurIPS 2025 poster", nid="n1", title="Anchored Diffusion Language Model")
    b = _note("TMLR", "Accepted by TMLR", nid="n2", title="anchored diffusion-language model ", pdate=1709745597405)
    out = orh.search("q", session=_FakeSession([_page(a, b)]))
    assert [e.source_native_id for e in out] == ["openreview:n1"]


def test_non_latin_titles_do_not_collide():
    a = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="c1", title="扩散语言模型")
    b = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="c2", title="图神经网络")
    assert len(orh.search("q", session=_FakeSession([_page(a, b)]))) == 2


def test_year_dropped_record_does_not_block_a_later_match():
    """Filter before marking seen: an out-of-range duplicate must not hide the
    in-range copy that follows it."""
    old = _note("TMLR", "Accepted by TMLR", nid="t1", title="Same Title", pdate=1609459200000)  # 2021
    new = _note("ICLR.cc/2026/Conference", "ICLR 2026 Poster", nid="t2", title="Same Title")
    out = orh.search("q", year_min=2025, session=_FakeSession([_page(old, new)]))
    assert [e.source_native_id for e in out] == ["openreview:t2"]


# ---------------------------------------------------------------------------
# Serialisation and CLI
# ---------------------------------------------------------------------------


def test_entity_to_dict_is_full_and_json_safe():
    _, e = _fixture_entity("Diffusion Language Model Knows the Answer")
    d = orh._entity_to_dict(e)
    json.dumps(d, ensure_ascii=False)
    assert d["sources"] == ["openreview"]
    assert d["source_native_id"] == "openreview:g88nt4ieTG"
    assert d["authors"][0]["name"] == "Pengxiang Li"
    assert set(UnifiedPaperEntity().__dict__) == set(d)


def _cli(monkeypatch, argv, responses):
    real = orh.search
    sess = _FakeSession(responses)
    monkeypatch.setattr(orh, "search", lambda *a, **kw: real(*a, session=sess, **kw))
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        orh._main_cli(argv)
    return out.getvalue(), err.getvalue(), sess


def test_cli_stdout_is_pure_json_and_stderr_has_attribution(monkeypatch):
    out, err, sess = _cli(monkeypatch, ["--search", "diffusion language model", "--n", "20",
                                         "--year-min", "2025"], [PAGE1, PAGE2])
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == min(20, sum(1 for _, y, _ in EXPECTED_ACCEPTED if y >= 2025))
    assert all(d["year"] >= 2025 for d in data)
    assert data[0]["venue"] == "NeurIPS 2025 Poster"
    assert "OpenReview" in err and "stopped: end_of_results" in err
    assert sess.calls[0]["params"]["term"] == "diffusion language model"


def test_cli_output_file(monkeypatch, tmp_path):
    target = tmp_path / "openreview.json"
    out, err, _ = _cli(monkeypatch, ["--search", "q", "--year-max", "2024",
                                      "--output-file", str(target)], [PAGE1, PAGE2])
    assert out == ""
    data = json.loads(target.read_text(encoding="utf-8"))
    assert {d["year"] for d in data} == {2023, 2024}


def test_cli_failure_still_prints_valid_json(monkeypatch):
    out, err, _ = _cli(monkeypatch, ["--search", "q"], [(CHALLENGE["body"], 403)])
    assert json.loads(out) == []
    assert "stopped: challenge" in err


# ---------------------------------------------------------------------------
# Optional live smoke — deselected by default (pytest.ini: -m "not live").
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_search_live_smoke():
    out = orh.search("diffusion language model", n=5, year_min=2025, max_pages=2)
    if not out:
        pytest.skip(f"no live results (stopped: {orh.last_search_stats.get('stopped')})")
    for e in out:
        assert e.sources == ["openreview"] and e.year >= 2025
        assert e.venue == "TMLR" or e.venue.split()[1].isdigit()


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
