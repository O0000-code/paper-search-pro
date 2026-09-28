"""STEP 10 enrichment CLIs on the real file shapes — offline.

* A KG dict (``kg_classified.json``) goes in and comes back with only the
  enrichment keys changed: rcs, authors, journal_rank and unknown keys survive.
* ``--min-rcs N`` limits which papers are enriched.
* List input is byte-identical to before. The golden hashes below were taken
  from the CLIs at commit 50c9c63 on these same inputs (Semantic Scholar through
  the semanticscholar SDK, its HTTP answered by httpx.MockTransport from the same
  records; CrossRef with ``_fetch_doi`` patched), so a change in the list path's
  output turns them red.

Semantic Scholar is served by patching ``requests.get`` / ``requests.post``
(what ``ss_helper._ss_get`` calls); CrossRef by patching ``_fetch_doi``, its
single network surface.
"""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
import warnings
from pathlib import Path

import pytest
import requests

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import config as config_mod  # noqa: E402
from scripts import crossref_helper  # noqa: E402
from scripts import ss_helper  # noqa: E402
from scripts.types import Config  # noqa: E402


# =============================================================================
# Fixture data (the golden inputs; do not edit without re-capturing)
# =============================================================================

SS_RECORDS = {
    "10.1000/a1": {
        "paperId": "SSA1", "externalIds": {"DOI": "10.1000/A1"}, "title": "Paper A1",
        "year": 2021, "abstract": "SS abstract A1",
        "tldr": {"model": "tldr@v2.0.0", "text": "TLDR A1"},
        "citationCount": 44, "influentialCitationCount": 7,
        "openAccessPdf": {"url": "https://x/a1.pdf"}, "venue": "Journal A",
        "publicationVenue": {"id": "v1", "name": "Journal A", "issn": "1111-1111",
                             "alternate_issns": ["2222-2222"]},
    },
    "10.1000/b2": {
        "paperId": "SSB2", "externalIds": {"DOI": "10.1000/b2"}, "title": "Paper B2",
        "year": 2020, "abstract": "SS abstract B2", "tldr": None,
        "citationCount": 5, "influentialCitationCount": 3, "openAccessPdf": None,
        "venue": "Journal B", "publicationVenue": {"id": "v2", "name": "Journal B", "issn": "3333-3333"},
    },
    "10.1000/c3": {
        "paperId": "SSC3", "externalIds": {"DOI": "10.1000/c3", "ArXiv": "2101.00001"},
        "title": "Paper C3", "year": 2019, "abstract": None, "tldr": {"text": "new tldr"},
        "citationCount": 0, "influentialCitationCount": 2, "openAccessPdf": None,
        "venue": "", "publicationVenue": None,
    },
    "10.1000/d4": {
        "paperId": "SSD4", "externalIds": {"DOI": "10.1000/d4"}, "title": "Paper D4",
        "year": 2018, "abstract": "", "tldr": None, "citationCount": 100,
        "influentialCitationCount": 0, "openAccessPdf": None, "venue": "Journal D",
        "publicationVenue": None,
    },
}

SS_LIST_INPUT = [
    {"doi": "10.1000/A1", "title": "Enriched, no abstract", "citation_count": 40,
     "abstract": None, "sources": ["openalex"], "rcs": 8, "authors": [{"name": "Alice"}],
     "venue": "J A", "issn": "1111-1111"},
    {"doi": "https://doi.org/10.1000/b2", "title": "Has abstract — 中文标题",
     "citation_count": 10, "abstract": "OA abstract", "sources": ["openalex"], "rcs": 6},
    {"doi": "10.1000/missing", "title": "Unknown to SS", "citation_count": 5,
     "sources": ["openalex"]},
    {"doi": "10.48550/arXiv.1706.03762", "title": "arXiv", "citation_count": 100,
     "sources": ["openalex"]},
    {"title": "No DOI", "citation_count": 3},
    {"doi": "10.1000/c3", "title": "Already SS", "citation_count": 0,
     "sources": ["openalex", "semantic_scholar"], "influential_citation_count": 1,
     "ss_paper_id": "OLD", "tldr": "old tldr"},
    {"doi": "10.1000/d4", "title": "Zero influential", "citation_count": 100, "sources": []},
]

CR_PAYLOADS = {
    "10.1056/NEJMoa2034577": {
        "DOI": "10.1056/nejmoa2034577",
        "funder": [{"name": "BioNTech and Pfizer", "DOI": "10.13039/100004319", "award": []}],
        "license": [{"URL": "http://www.nejmgroup.org/legal/terms-of-use.htm",
                     "content-version": "vor", "delay-in-days": 0}],
        "reference": [{"key": f"r{i}"} for i in range(13)],
        "clinical-trial-number": [],
    },
    "10.1234/trial": {
        "DOI": "10.1234/trial",
        "funder": [{"name": "NIH", "DOI": "10.13039/100000002", "award": ["R01-12345"]}],
        "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/",
                     "content-version": "vor", "delay-in-days": 365}],
        "reference": [{"key": "r1"}, {"key": "r2"}, {"key": "r3"}],
        "clinical-trial-number": [{"registry": "10.18810/clinical-trials-gov",
                                   "clinical-trial-number": "NCT04501978"}],
    },
    "10.2307/1914185": {"DOI": "10.2307/1914185", "funder": [], "license": [],
                        "reference": [], "clinical-trial-number": []},
}

CR_LIST_INPUT = [
    {"doi": "10.1056/NEJMoa2034577", "title": "NEJM — 中文", "authors": [{"name": "F. Polack"}],
     "referenced_works_count": 8, "sources": ["openalex"], "rcs": 9, "venue": "NEJM",
     "issns": ["0028-4793"], "custom": 1},
    {"doi": "10.1234/trial", "title": "Trial", "referenced_works_count": 1,
     "sources": ["openalex"], "funders": []},
    {"doi": "10.2307/1914185", "title": "K&T"},
    {"doi": "10.48550/arXiv.1706.03762", "title": "arXiv"},
    {"doi": "10.9999/nonexistent", "title": "404", "rcs": 2},
]

GOLDEN_SHA256 = {
    "ss_enrich_stdout": "80a8179c6f526851a2120ed1629399d536880fb94bfbdba7ace1672d290416ba",
    "ss_enrich_outfile": "a68f6fa059011265df038045fa6d37c430a7e99a7f85cbedabda28d40c9c8c7a",
    "ss_validate_stdout": "9b228cfde0918e3e1c419cb56d65433bbd8ab3ad3b4ab2f4f15867ab6ba54514",
    "cr_all_stdout": "2a2db404c1566018d7d164b0dee3d24f86c4e313438c564c6abb9446f5b5cac9",
    "cr_funder_stdout": "a63ee439a88280006dbf9616e90b36dc5ff093f21ef4dd0d580faf3b01875e10",
    "cr_refs_stdout": "c3ecac361c3f287d368919aac7a4a5ebdead52b2879f99efc9fcccbb4ab09d63",
    "cr_license_stdout": "7c2ea5bba6c51401e102a69f9cfacc0eb721bec24986f7bba6e618d9ad41635c",
    "cr_clinical_stdout": "fab697e64743e2c4f14282ebcf78b9c886296a37e400331bcdd39e7a46762082",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# =============================================================================
# Fake Semantic Scholar graph API + CLI runners
# =============================================================================

class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload


class _FakeSS:
    """Answers /paper/batch and /paper/DOI:x from SS_RECORDS, honouring
    ``fields`` like the real API. ``status`` forces an error on every request
    (``batch_status`` on the batch endpoint only)."""

    def __init__(self):
        self.status = None
        self.batch_status = None
        self.calls = []

    def _fields(self, params):
        return [f for f in str((params or {}).get("fields", "")).split(",") if f]

    def post(self, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append(("POST", list((json or {}).get("ids", [])), dict(headers or {})))
        status = self.status or self.batch_status
        if status:
            return _Resp(status, {"error": "forced"})
        fields = self._fields(params)
        out = []
        for i in json["ids"]:
            rec = SS_RECORDS.get(i[4:].lower())
            out.append({k: rec[k] for k in fields if k in rec} if rec else None)
        return _Resp(200, out)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url.split("/paper/", 1)[1], dict(headers or {})))
        if self.status:
            return _Resp(self.status, {"error": "forced"})
        rec = SS_RECORDS.get(url.split("/paper/DOI:", 1)[1].lower())
        if not rec:
            return _Resp(404, {"error": "not found"})
        return _Resp(200, {k: rec[k] for k in self._fields(params) if k in rec})


@pytest.fixture
def fake_ss(monkeypatch):
    fake = _FakeSS()
    monkeypatch.setattr(requests, "post", fake.post)
    monkeypatch.setattr(requests, "get", fake.get)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: Config())
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    return fake


def _run_ss(argv, capsys):
    """Run ``python -m scripts.ss_helper <argv>`` in-process (fresh module
    globals, as a real invocation gets). Returns (stdout, stderr)."""
    capsys.readouterr()
    old = sys.argv
    sys.argv = ["ss_helper", *argv]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # re-running an imported module
            runpy.run_module("scripts.ss_helper", run_name="__main__", alter_sys=True)
    finally:
        sys.argv = old
    captured = capsys.readouterr()
    return captured.out, captured.err


@pytest.fixture
def fake_cr(monkeypatch):
    calls = []

    def fetch(doi):
        calls.append(doi)
        return CR_PAYLOADS.get(doi)

    monkeypatch.setattr(crossref_helper, "_fetch_doi", fetch)
    monkeypatch.setattr(crossref_helper.time, "sleep", lambda _s: None)
    monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: Config())
    return calls


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


# =============================================================================
# A KG dict in the shape STEP 6 leaves it
# =============================================================================

def _kg():
    return {
        "doi:10.1000/a1": {
            "doi": "10.1000/a1", "openalex_id": "W1", "title": "Paper A — 中文",
            "abstract": None, "authors": [{"name": "Alice Smith", "orcid": None}],
            "year": 2021, "venue": None, "issn": None, "citation_count": 40,
            "journal_rank": {"issns": ["1111-1111"], "cas": {"tier": 1}},
            "rcs": 8, "rcs_reasoning": "core", "rcs_flag": None,
            "sources": ["openalex"], "discovery_path": "query: q", "_provenance": {"x": 1},
        },
        "doi:10.1000/b2": {
            "doi": "10.1000/b2", "title": "Paper B", "abstract": "OA abstract",
            "authors": [{"name": "Bob"}], "venue": "OA Venue", "issn": "4444-4444",
            "issns": ["4444-4444"], "ss_paper_id": "KEEP", "citation_count": 10,
            "rcs": 6, "rcs_reasoning": "ok", "sources": ["openalex"], "custom_key": [1, 2],
        },
        "doi:10.1000/c3": {
            "doi": "10.1000/c3", "title": "Low rcs", "citation_count": 3, "rcs": 3,
            "sources": ["openalex"], "authors": [{"name": "Carol"}],
        },
        "doi:10.1000/d4": {"doi": "10.1000/d4", "title": "Unscored", "rcs": None,
                           "sources": ["openalex"]},
        "native|nssd:X1": {"title": "中文无 DOI", "rcs": 9, "source_native_id": "nssd:X1",
                           "sources": ["nssd"], "authors": [{"name": "张三"}]},
        "doi:10.1000/missing": {"doi": "10.1000/missing", "title": "Not in SS", "rcs": 7,
                                "sources": ["openalex"]},
        "doi:10.1000/boolrcs": {"doi": "10.1000/a1", "title": "bool rcs", "rcs": True},
        "doi:10.1000/strrcs": {"doi": "10.1000/a1", "title": "str rcs", "rcs": "7"},
    }


# =============================================================================
# Semantic Scholar
# =============================================================================

def test_ss_list_input_is_byte_identical(fake_ss, capsys, tmp_path):
    inp = _write(tmp_path, "list.json", SS_LIST_INPUT)
    out, err = _run_ss(["--input-file", str(inp), "--mode", "enrich"], capsys)
    assert _sha(out) == GOLDEN_SHA256["ss_enrich_stdout"], out
    assert "Semantic Scholar enrichment: 4/7 papers enriched" in err

    of = tmp_path / "out.json"
    _run_ss(["--input-file", str(inp), "--mode", "enrich", "--output-file", str(of)], capsys)
    assert _sha(of.read_text(encoding="utf-8")) == GOLDEN_SHA256["ss_enrich_outfile"]

    out, _ = _run_ss(["--input-file", str(inp), "--mode", "validate"], capsys)
    assert _sha(out) == GOLDEN_SHA256["ss_validate_stdout"], out


def test_ss_list_input_per_paper_fallback_is_byte_identical(fake_ss, capsys, tmp_path):
    """Batch fails -> one request per paper; same output as the batch path."""
    fake_ss.batch_status = 500
    inp = _write(tmp_path, "list.json", SS_LIST_INPUT)
    out, _ = _run_ss(["--input-file", str(inp), "--mode", "enrich"], capsys)
    assert _sha(out) == GOLDEN_SHA256["ss_enrich_stdout"], out
    assert [c[0] for c in fake_ss.calls] == ["POST"] + ["GET"] * 5


def test_ss_kg_round_trip_patches_only_enrichment_keys(fake_ss, capsys, tmp_path):
    kg = _kg()
    path = _write(tmp_path, "kg_classified.json", kg)
    _, err = _run_ss(["--input-file", str(path), "--output-file", str(path),
                      "--min-rcs", "6"], capsys)
    out = json.loads(path.read_text(encoding="utf-8"))

    # Same records, same key order; existing keys keep their order too.
    assert list(out) == list(kg)
    for key, before in kg.items():
        assert list(out[key])[:len(before)] == list(before), key

    a = out["doi:10.1000/a1"]
    assert {k: a[k] for k in ("rcs", "rcs_reasoning", "rcs_flag", "authors", "journal_rank",
                              "_provenance", "discovery_path", "openalex_id", "title")} == {
        k: kg["doi:10.1000/a1"][k] for k in ("rcs", "rcs_reasoning", "rcs_flag", "authors",
                                             "journal_rank", "_provenance", "discovery_path",
                                             "openalex_id", "title")}
    assert a["influential_citation_count"] == 7
    assert a["tldr"] == "TLDR A1"
    assert a["abstract"] == "SS abstract A1"          # was empty
    assert a["ss_paper_id"] == "SSA1"
    assert a["venue"] == "Journal A"                  # was empty
    assert a["issn"] == "1111-1111"
    assert a["issns"] == ["1111-1111", "2222-2222"]
    assert a["sources"] == ["openalex", "semantic_scholar"]
    assert a["citation_count"] == 40                  # SS's 44 is not an enrichment key

    b = out["doi:10.1000/b2"]
    changed = {k for k in b if b.get(k) != kg["doi:10.1000/b2"].get(k)}
    assert changed == {"influential_citation_count", "sources"}  # tldr is null at SS
    assert (b["abstract"], b["ss_paper_id"], b["venue"], b["issn"], b["issns"]) == (
        "OA abstract", "KEEP", "OA Venue", "4444-4444", ["4444-4444"])
    assert b["custom_key"] == [1, 2]

    # Not candidates (rcs < 6, None, bool, str) or not in SS / no DOI: untouched.
    for key in ("doi:10.1000/c3", "doi:10.1000/d4", "doi:10.1000/boolrcs",
                "doi:10.1000/strrcs", "native|nssd:X1", "doi:10.1000/missing"):
        assert out[key] == kg[key], key

    # Only the rcs >= 6 papers with a usable DOI were sent.
    assert fake_ss.calls[0][1] == ["DOI:10.1000/a1", "DOI:10.1000/b2", "DOI:10.1000/missing"]
    assert ("[paper-search-pro] Semantic Scholar enrichment: 2/4 papers enriched "
            "(1 not found; 1 without a usable DOI).") in err


def test_ss_kg_without_min_rcs_enriches_every_paper(fake_ss, capsys, tmp_path):
    path = _write(tmp_path, "kg.json", _kg())
    out, _ = _run_ss(["--input-file", str(path)], capsys)
    kg = json.loads(out)
    assert kg["doi:10.1000/c3"]["influential_citation_count"] == 2  # rcs 3, enriched anyway
    assert "DOI:10.1000/d4" in fake_ss.calls[0][1]


def test_ss_kg_total_failure_leaves_kg_unchanged(fake_ss, capsys, tmp_path, monkeypatch):
    """Key refused and keyless refused: the KG is written back unchanged, the
    run exits normally, and the user gets the renew line plus one summary."""
    monkeypatch.setattr(config_mod, "load_config",
                        lambda *a, **k: Config(semantic_scholar_api_key="DEAD"))
    fake_ss.status = 403
    kg = _kg()
    path = _write(tmp_path, "kg.json", kg)
    _, err = _run_ss(["--input-file", str(path), "--output-file", str(path),
                      "--min-rcs", "6"], capsys)

    assert json.loads(path.read_text(encoding="utf-8")) == kg
    assert [c[0] for c in fake_ss.calls] == ["POST", "POST"]
    summaries = [ln for ln in err.splitlines() if "Semantic Scholar enrichment:" in ln]
    assert summaries == ["[paper-search-pro] Semantic Scholar enrichment: 0/4 papers enriched "
                         "(HTTP 403, key rejected; 1 without a usable DOI)."]
    assert err.count("rejected the configured API key") == 1


def test_ss_kg_validate_lists_conflicts(fake_ss, capsys, tmp_path):
    kg = _kg()
    kg["doi:10.1000/d4"].update(citation_count=40, rcs=6)   # SS says 100 -> 150 %
    path = _write(tmp_path, "kg.json", kg)
    out, _ = _run_ss(["--input-file", str(path), "--mode", "validate", "--min-rcs", "6"], capsys)
    conflicts = json.loads(out)
    assert [c["paper_id"] for c in conflicts] == ["10.1000/b2", "10.1000/d4"]
    assert json.loads(path.read_text(encoding="utf-8")) == kg  # validate never writes the KG


def test_ss_list_input_honours_min_rcs(fake_ss, capsys, tmp_path):
    inp = _write(tmp_path, "list.json", SS_LIST_INPUT)
    out, _ = _run_ss(["--input-file", str(inp), "--min-rcs", "7"], capsys)
    rows = json.loads(out)
    assert fake_ss.calls[0][1] == ["DOI:10.1000/a1"]
    assert rows[0]["influential_citation_count"] == 7
    assert rows[1]["influential_citation_count"] is None   # rcs 6 < 7


def test_selected_requires_an_int_rcs():
    for selected in (ss_helper._selected, crossref_helper._selected):
        assert selected({"rcs": None}, None) is True          # no flag: everyone
        assert selected({"rcs": 6}, 6) is True
        assert selected({"rcs": 5}, 6) is False
        for rcs in (None, True, "7", 7.0):
            assert selected({"rcs": rcs}, 6) is False, rcs
        assert selected({}, 0) is False


# =============================================================================
# CrossRef
# =============================================================================

def test_crossref_list_input_is_byte_identical(fake_cr, capsys, tmp_path):
    inp = _write(tmp_path, "list.json", CR_LIST_INPUT)
    for mode in ("all", "funder", "refs", "license", "clinical"):
        capsys.readouterr()
        assert crossref_helper._cli_main(["--input-file", str(inp), "--mode", mode]) == 0
        out = capsys.readouterr().out
        assert _sha(out) == GOLDEN_SHA256[f"cr_{mode}_stdout"], (mode, out)


def _cr_kg():
    return {
        "doi:10.1056/nejmoa2034577": {
            "doi": "10.1056/NEJMoa2034577", "title": "NEJM", "authors": [{"name": "F. Polack"}],
            "referenced_works_count": 8, "rcs": 9, "rcs_reasoning": "core",
            "journal_rank": {"cas": {"tier": 1}}, "sources": ["openalex"], "extra": {"k": 1},
        },
        "doi:10.1234/trial": {
            "doi": "10.1234/trial", "title": "Trial", "authors": [{"name": "T"}],
            "referenced_works_count": 1, "rcs": 6, "funders": [], "sources": ["openalex"],
        },
        "doi:10.2307/1914185": {"doi": "10.2307/1914185", "title": "K&T", "rcs": 7,
                                "authors": [{"name": "Kahneman"}]},
        "doi:10.1234/low": {"doi": "10.1234/trial", "title": "Low", "rcs": 2,
                            "authors": [{"name": "L"}]},
    }


def test_crossref_kg_round_trip_keeps_authors_and_rcs(fake_cr, tmp_path):
    kg = _cr_kg()
    path = _write(tmp_path, "kg_classified.json", kg)
    assert crossref_helper._cli_main(["--input-file", str(path), "--mode", "all",
                                      "--output-file", str(path), "--min-rcs", "6"]) == 0
    out = json.loads(path.read_text(encoding="utf-8"))

    assert list(out) == list(kg)
    for key, before in kg.items():
        assert list(out[key])[:len(before)] == list(before), key
        for k in ("authors", "rcs", "rcs_reasoning", "journal_rank", "extra", "title", "doi"):
            assert out[key].get(k) == before.get(k), (key, k)

    nejm = out["doi:10.1056/nejmoa2034577"]
    assert nejm["funders"][0]["name"] == "BioNTech and Pfizer"
    assert nejm["license"][0]["content_version"] == "vor"
    assert nejm["referenced_works_count"] == 13
    assert nejm["sources"] == ["openalex", "crossref"]
    assert "clinical_trial_number" not in nejm          # CrossRef had none: key not added

    trial = out["doi:10.1234/trial"]
    assert trial["clinical_trial_number"] == "NCT04501978"
    assert trial["funders"][0]["award"] == ["R01-12345"]

    assert out["doi:10.2307/1914185"] == kg["doi:10.2307/1914185"]  # nothing to add
    assert out["doi:10.1234/low"] == kg["doi:10.1234/low"]          # rcs 2: not a candidate
    assert fake_cr == ["10.1056/NEJMoa2034577", "10.1234/trial", "10.2307/1914185"]


def test_crossref_kg_without_min_rcs_enriches_every_paper(fake_cr, tmp_path, capsys):
    path = _write(tmp_path, "kg.json", _cr_kg())
    assert crossref_helper._cli_main(["--input-file", str(path), "--mode", "funder"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["doi:10.1234/low"]["funders"][0]["name"] == "NIH"
    assert out["doi:10.1234/low"]["authors"] == [{"name": "L"}]

