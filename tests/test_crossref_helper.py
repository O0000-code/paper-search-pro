"""Unit tests for crossref_helper.py (paper-search-pro Wave 6b SA).

All tests use monkey-patched ``_fetch_doi`` — no network calls. The fixture
data mirrors real CrossRef responses observed during SA-W2 / SA-V1 testing:

- NEJM 2020 BNT162b2 (10.1056/NEJMoa2034577): funder = BioNTech + Pfizer,
  license + 13 references.
- K&T 1979 prospect theory (10.2307/1914185): pre-funder-era, references = 0.
- arXiv "Attention" DOI (10.48550/arXiv.1706.03762): would 404 in CrossRef;
  our pre-filter should skip without any fetch.

Run from skill root:
    cd ~/.claude/skills/paper-search-pro && python3 tests/test_crossref_helper.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts import crossref_helper  # noqa: E402
from scripts.crossref_helper import (  # noqa: E402
    _DEFAULT_EMAIL,
    _USER_AGENT_TEMPLATE,
    _extract_clinical_trial_number,
    _extract_funders,
    _extract_license,
    _is_arxiv_doi,
    enrich_all,
    enrich_clinical_trial,
    enrich_funder,
    enrich_license,
    enrich_references,
    init,
)
from scripts.types import Config, UnifiedPaperEntity  # noqa: E402


# =============================================================================
# Fixtures: trimmed CrossRef "message" payloads from real responses
# =============================================================================

_NEJM_COVID_DOI = "10.1056/NEJMoa2034577"
_KT1979_DOI = "10.2307/1914185"
_ARXIV_ATTENTION_DOI = "10.48550/arXiv.1706.03762"
_ARXIV_BERT_DOI = "10.48550/arxiv.1810.04805"  # lower-case variant
_FAKE_404_DOI = "10.9999/nonexistent"
_NEJM_OLD_DOI = "10.1056/NEJM196909042811001"

_NEJM_COVID_PAYLOAD: Dict[str, Any] = {
    "DOI": _NEJM_COVID_DOI.lower(),
    "title": ["Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine"],
    "container-title": ["New England Journal of Medicine"],
    "funder": [
        {
            "name": "BioNTech and Pfizer",
            "DOI": "10.13039/100004319",
            "award": [],
        }
    ],
    "license": [
        {
            "URL": "http://www.nejmgroup.org/legal/terms-of-use.htm",
            "content-version": "vor",
            "delay-in-days": 0,
        }
    ],
    # 13 reference stubs (only count matters for our test)
    "reference": [{"key": f"r{i}"} for i in range(13)],
    "clinical-trial-number": [],  # NEJM RCTs are empirically empty here
}

_KT1979_PAYLOAD: Dict[str, Any] = {
    "DOI": _KT1979_DOI,
    "title": ["Prospect Theory: An Analysis of Decision under Risk"],
    "container-title": ["Econometrica"],
    # Pre-funder era; no funder/license
    "funder": [],
    "license": [],
    "reference": [],
    "clinical-trial-number": [],
}

# A clinical trial paper that DOES have CTN — synthetic but matches CrossRef format
_TRIAL_PAYLOAD: Dict[str, Any] = {
    "DOI": "10.1234/trial",
    "funder": [{"name": "NIH", "DOI": "10.13039/100000002", "award": ["R01-12345"]}],
    "license": [
        {"URL": "https://creativecommons.org/licenses/by/4.0/",
         "content-version": "vor", "delay-in-days": 365}
    ],
    "reference": [{"key": "r1"}, {"key": "r2"}, {"key": "r3"}],
    "clinical-trial-number": [
        {"registry": "10.18810/clinical-trials-gov",
         "clinical-trial-number": "NCT04501978"}
    ],
}


# =============================================================================
# Helpers
# =============================================================================

class _CallRecorder:
    """Records each (doi -> payload) lookup so we can assert skip behaviour."""

    def __init__(self, table: Dict[str, Optional[Dict[str, Any]]]):
        self.table = table
        self.calls: List[str] = []

    def __call__(self, doi: str) -> Optional[Dict[str, Any]]:
        self.calls.append(doi)
        # arXiv DOIs should NEVER reach this fn — _is_arxiv_doi pre-filters them.
        # Fixture defaults to None (404) for unknown DOIs.
        return self.table.get(doi)


def _make_paper(
    doi: Optional[str],
    title: str = "Test",
    referenced_works_count: Optional[int] = None,
) -> UnifiedPaperEntity:
    return UnifiedPaperEntity(
        doi=doi,
        title=title,
        referenced_works_count=referenced_works_count,
    )


# =============================================================================
# Test cases
# =============================================================================

class CrossRefHelperTests(unittest.TestCase):

    def setUp(self) -> None:
        # Make sleep a no-op so the 0.1s/call rate-limit doesn't slow tests.
        self._orig_sleep = crossref_helper.time.sleep
        crossref_helper.time.sleep = lambda _s: None
        # Snapshot _fetch_doi so each test can swap freely.
        self._orig_fetch_doi = crossref_helper._fetch_doi

    def tearDown(self) -> None:
        crossref_helper.time.sleep = self._orig_sleep
        crossref_helper._fetch_doi = self._orig_fetch_doi

    # ------------------------------------------------------------------ #
    # 1. Polite-pool User-Agent set correctly
    # ------------------------------------------------------------------ #

    def test_01_polite_pool_user_agent_with_email(self) -> None:
        """init(Config(crossref_email=X)) must embed X in the UA mailto."""
        cfg = Config(crossref_email="test@example.com")
        init(cfg)
        ua = crossref_helper._get_session().headers.get("User-Agent", "")
        self.assertIn("mailto:test@example.com", ua)
        self.assertIn("paper-search-pro/2.0", ua)

    def test_02_polite_pool_user_agent_anonymous_fallback(self) -> None:
        """init(None) or empty email must still construct a session with anon mailto."""
        init(None)
        ua = crossref_helper._get_session().headers.get("User-Agent", "")
        self.assertIn(f"mailto:{_DEFAULT_EMAIL}", ua)

    # ------------------------------------------------------------------ #
    # 3. arXiv DOI skip (the most load-bearing pre-filter)
    # ------------------------------------------------------------------ #

    def test_03_is_arxiv_doi_recognises_both_cases(self) -> None:
        self.assertTrue(_is_arxiv_doi(_ARXIV_ATTENTION_DOI))   # mixed-case
        self.assertTrue(_is_arxiv_doi(_ARXIV_BERT_DOI))        # lower-case
        self.assertTrue(_is_arxiv_doi("arxiv:1706.03762"))     # prefix form
        self.assertTrue(_is_arxiv_doi(None))                   # empty
        self.assertTrue(_is_arxiv_doi(""))                     # empty string
        self.assertFalse(_is_arxiv_doi(_NEJM_COVID_DOI))       # real DOI
        self.assertFalse(_is_arxiv_doi(_KT1979_DOI))           # real DOI

    def test_04_arxiv_doi_never_triggers_fetch(self) -> None:
        """Empirical fact: arXiv DOIs are 100% 404 in CrossRef. We must skip them."""
        recorder = _CallRecorder({})  # any call would be a test failure
        crossref_helper._fetch_doi = recorder

        papers = [
            _make_paper(_ARXIV_ATTENTION_DOI, "Attention is All You Need"),
            _make_paper(_ARXIV_BERT_DOI, "BERT"),
            _make_paper(None, "no-doi"),
        ]
        enrich_all(papers)

        self.assertEqual(recorder.calls, [],
                         "arXiv / None DOIs must not reach _fetch_doi")
        # None of the papers should have crossref in their sources.
        for p in papers:
            self.assertNotIn("crossref", p.sources)

    # ------------------------------------------------------------------ #
    # 5. NEJM funder enrichment (the headline use-case)
    # ------------------------------------------------------------------ #

    def test_05_nejm_funder_biontech_pfizer(self) -> None:
        recorder = _CallRecorder({_NEJM_COVID_DOI: _NEJM_COVID_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper(_NEJM_COVID_DOI, "NEJM COVID")]
        enrich_funder(papers)

        self.assertEqual(len(papers[0].funders), 1)
        self.assertEqual(papers[0].funders[0]["name"], "BioNTech and Pfizer")
        self.assertEqual(papers[0].funders[0]["doi"], "10.13039/100004319")
        self.assertIn("crossref", papers[0].sources)
        self.assertEqual(recorder.calls, [_NEJM_COVID_DOI])

    # ------------------------------------------------------------------ #
    # 6. License enrichment, structured normalisation
    # ------------------------------------------------------------------ #

    def test_06_nejm_license_normalised(self) -> None:
        recorder = _CallRecorder({_NEJM_COVID_DOI: _NEJM_COVID_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper(_NEJM_COVID_DOI, "NEJM COVID")]
        enrich_license(papers)

        self.assertEqual(len(papers[0].license), 1)
        lic = papers[0].license[0]
        # Field names are snake_case after normalisation
        self.assertEqual(lic["URL"], "http://www.nejmgroup.org/legal/terms-of-use.htm")
        self.assertEqual(lic["content_version"], "vor")
        self.assertEqual(lic["delay_in_days"], 0)
        self.assertIn("crossref", papers[0].sources)

    # ------------------------------------------------------------------ #
    # 7. References count: only bumps when CrossRef has strictly more
    # ------------------------------------------------------------------ #

    def test_07_references_bumped_only_when_more(self) -> None:
        recorder = _CallRecorder({_NEJM_COVID_DOI: _NEJM_COVID_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        # Threshold semantics: "if OA already has >= threshold refs, skip CR fetch".
        # Use threshold=10 (matches helper default) -> NEJM-style 8->13 still bumps.

        # OA had 8 refs; below threshold=10 -> fetched, CR has 13 -> bump to 13
        p_lo = _make_paper(_NEJM_COVID_DOI, "NEJM COVID", referenced_works_count=8)
        # OA already at 13; below threshold? no (13>=10) -> skip (no fetch)
        p_hi = _make_paper(_NEJM_COVID_DOI, "NEJM COVID", referenced_works_count=13)
        # OA at 10; exactly at threshold -> skip
        p_thresh = _make_paper(_NEJM_COVID_DOI, "NEJM COVID", referenced_works_count=10)

        enrich_references([p_lo, p_hi, p_thresh], threshold=10)

        # Only p_lo triggered a fetch and got bumped
        self.assertEqual(p_lo.referenced_works_count, 13)
        self.assertIn("crossref", p_lo.sources)
        # p_hi and p_thresh: never fetched, count unchanged, no source added
        self.assertEqual(p_hi.referenced_works_count, 13)
        self.assertNotIn("crossref", p_hi.sources)
        self.assertEqual(p_thresh.referenced_works_count, 10)
        self.assertNotIn("crossref", p_thresh.sources)
        # Exactly one fetch issued (only p_lo)
        self.assertEqual(recorder.calls, [_NEJM_COVID_DOI])

    # ------------------------------------------------------------------ #
    # 8. K&T 1979 has empty funder + license (pre-funder era)
    # ------------------------------------------------------------------ #

    def test_08_kt1979_empty_funder_license_no_source_added(self) -> None:
        """Empirical: K&T 1979 returns 200 with empty funder/license arrays.
        We should NOT mark crossref as a source when nothing was actually added.
        """
        recorder = _CallRecorder({_KT1979_DOI: _KT1979_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper(_KT1979_DOI, "Prospect Theory")]
        enrich_all(papers)

        self.assertEqual(papers[0].funders, [])
        self.assertEqual(papers[0].license, [])
        self.assertEqual(papers[0].referenced_works_count, None)
        self.assertEqual(papers[0].clinical_trial_number, None)
        # No fields enriched -> no 'crossref' source mark
        self.assertNotIn("crossref", papers[0].sources)

    # ------------------------------------------------------------------ #
    # 9. Clinical trial number extraction
    # ------------------------------------------------------------------ #

    def test_09_clinical_trial_number_extracted(self) -> None:
        recorder = _CallRecorder({"10.1234/trial": _TRIAL_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper("10.1234/trial", "Some Trial")]
        enrich_clinical_trial(papers)

        self.assertEqual(papers[0].clinical_trial_number, "NCT04501978")
        self.assertIn("crossref", papers[0].sources)

    def test_10_clinical_trial_number_empty_for_nejm(self) -> None:
        """NEJM COVID empirically returns empty CTN array — must not crash, set None."""
        recorder = _CallRecorder({_NEJM_COVID_DOI: _NEJM_COVID_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper(_NEJM_COVID_DOI, "NEJM COVID")]
        enrich_clinical_trial(papers)

        self.assertIsNone(papers[0].clinical_trial_number)
        self.assertNotIn("crossref", papers[0].sources)

    # ------------------------------------------------------------------ #
    # 11. enrich_all: ONE fetch per paper, all 4 fields populated
    # ------------------------------------------------------------------ #

    def test_11_enrich_all_single_fetch_per_paper(self) -> None:
        recorder = _CallRecorder({"10.1234/trial": _TRIAL_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        # Paper starts with referenced_works_count=1 so CrossRef refs=3 wins
        p = _make_paper("10.1234/trial", "Trial", referenced_works_count=1)
        enrich_all([p])

        # Exactly ONE network call for all 4 enrichments
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0], "10.1234/trial")

        # All 4 fields populated
        self.assertEqual(p.funders[0]["name"], "NIH")
        self.assertEqual(p.funders[0]["doi"], "10.13039/100000002")
        self.assertEqual(p.funders[0]["award"], ["R01-12345"])
        self.assertEqual(p.license[0]["delay_in_days"], 365)
        self.assertEqual(p.referenced_works_count, 3)
        self.assertEqual(p.clinical_trial_number, "NCT04501978")
        self.assertIn("crossref", p.sources)
        # Exactly one 'crossref' entry (not appended multiple times)
        self.assertEqual(p.sources.count("crossref"), 1)

    # ------------------------------------------------------------------ #
    # 12. 404 (fake DOI) handling: returns None, no crash, no side-effects
    # ------------------------------------------------------------------ #

    def test_12_404_handled_gracefully(self) -> None:
        """Empirical: CrossRef returns text/plain "Resource not found" for unknown DOIs.
        Our _fetch_doi must return None and enrich_* must skip the paper."""
        recorder = _CallRecorder({_FAKE_404_DOI: None})  # None == 404
        crossref_helper._fetch_doi = recorder

        papers = [_make_paper(_FAKE_404_DOI, "Fake")]
        enrich_all(papers)

        # _fetch_doi was called once (DOI is not arXiv), returned None, no enrich
        self.assertEqual(recorder.calls, [_FAKE_404_DOI])
        self.assertEqual(papers[0].funders, [])
        self.assertEqual(papers[0].license, [])
        self.assertIsNone(papers[0].clinical_trial_number)
        self.assertNotIn("crossref", papers[0].sources)

    # ------------------------------------------------------------------ #
    # 13. Empty papers list returns empty list (no crash)
    # ------------------------------------------------------------------ #

    def test_13_empty_papers_list(self) -> None:
        for fn in (enrich_funder, enrich_license, enrich_references,
                   enrich_clinical_trial, enrich_all):
            self.assertEqual(fn([]), [])

    # ------------------------------------------------------------------ #
    # 14. Extractor helpers handle missing / None / empty keys
    # ------------------------------------------------------------------ #

    def test_14_extractors_robust_to_missing_fields(self) -> None:
        # Empty message
        self.assertEqual(_extract_funders({}), [])
        self.assertEqual(_extract_license({}), [])
        self.assertIsNone(_extract_clinical_trial_number({}))

        # Explicit None values
        self.assertEqual(_extract_funders({"funder": None}), [])
        self.assertEqual(_extract_license({"license": None}), [])
        self.assertIsNone(_extract_clinical_trial_number({"clinical-trial-number": None}))

        # Funder without DOI / award
        out = _extract_funders({"funder": [{"name": "Solo"}]})
        self.assertEqual(out, [{"name": "Solo", "doi": None, "award": []}])

    # ------------------------------------------------------------------ #
    # 15. Sources list integrity: crossref added at most once, OA source preserved
    # ------------------------------------------------------------------ #

    def test_15_sources_idempotent_and_preserves_existing(self) -> None:
        recorder = _CallRecorder({_NEJM_COVID_DOI: _NEJM_COVID_PAYLOAD})
        crossref_helper._fetch_doi = recorder

        p = _make_paper(_NEJM_COVID_DOI, "NEJM")
        p.sources.append("openalex")  # pre-existing source
        # Running enrich_all twice should still leave exactly one 'crossref'
        enrich_all([p])
        enrich_all([p])

        self.assertEqual(p.sources.count("crossref"), 1)
        self.assertEqual(p.sources.count("openalex"), 1)
        self.assertIn("openalex", p.sources)


# =============================================================================
# Runner
# =============================================================================

if __name__ == "__main__":
    # Verbose runner so we can count the passes printed in the final report.
    unittest.main(verbosity=2)
