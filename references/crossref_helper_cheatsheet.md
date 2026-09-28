# crossref_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 10 (L3 enrichment) — funder, license, references, clinical-trial-number.

**Role**: enrichment-only L3 — never an independent search source. CrossRef holds the authoritative funder DOIs (OpenAlex `grants` field commonly empty), license content-version + delay-in-days (OpenAlex lacks both), more complete `reference[]` for NEJM/older papers, and clinical-trial-number (mostly empty even on RCTs — see PubMed for primary).

**Entry point**: `python3 -m scripts.crossref_helper --input-file <kg_classified.json> --mode <funder|license|refs|clinical|all> [--min-rcs N] [--output-file <path>]`.
**No key required** — only a `crossref_email` for the polite pool User-Agent (10 req/s × 3 conc vs 5/s × 1 conc anonymous).

## Five modes

| `--mode` | Adds field | Notes |
|---|---|---|
| `all` (default, recommended) | funders + license + refs_count + clinical_trial_number | ONE fetch per paper |
| `funder` | `funders=[{name, doi, award[]}]` | Use alone if other fields not needed |
| `license` | `license=[{URL, content_version, delay_in_days}]` | Embargo/OA timing |
| `refs` | `referenced_works_count` (only when CR > OA) | Threshold skip at OA count ≥ 10 |
| `clinical` | `clinical_trial_number` | Mostly empty — prefer PubMed |

`--min-rcs N` limits enrichment to papers whose `rcs` is an integer ≥ N; without it every paper is fetched.

## Syntax + examples

```bash
# STEP 10: one-shot enrichment of the rcs >= 6 papers, in place (1 fetch per paper, ~0.6s each)
PYTHONPATH=$PSP_HOME python3 -m scripts.crossref_helper \
    --input-file "$SEARCH_DIR/kg_classified.json" \
    --mode all --min-rcs 6 \
    --output-file "$SEARCH_DIR/kg_classified.json"

# Single field (each mode makes its own fetch — use sparingly); same for license / refs / clinical
PYTHONPATH=$PSP_HOME python3 -m scripts.crossref_helper \
    --input-file "$SEARCH_DIR/kg_classified.json" \
    --mode funder --min-rcs 6 \
    --output-file "$SEARCH_DIR/kg_classified.json"
```

**What changes in each KG record**: only `funders`, `license`, `referenced_works_count`, `clinical_trial_number` (each only when CrossRef has a value), and `"crossref"` appended to `sources`. `authors`, `rcs`, `rcs_reasoning`, `journal_rank`, unknown keys and key order stay as they were; a paper CrossRef adds nothing to is untouched.

A JSON **list** of paper dicts is still accepted and returns full entity dicts, but with `authors` emptied — never write list output back over the KG.

## Output field formats

```jsonc
{
  "funders": [
    {"name": "BioNTech and Pfizer", "doi": "10.13039/100004319", "award": ["BNT162-01"]}
  ],
  "license": [
    {
      "URL": "https://www.nejm.org/about-nejm/...",
      "content_version": "vor",            // tdm | vor | am | unspecified
      "delay_in_days": 0
    }
  ],
  "referenced_works_count": 13,            // bumped from OA's 8 only when CR strictly more
  "clinical_trial_number": "NCT04368728",  // mostly null on NEJM RCTs
  "sources": [..., "crossref"]             // marked iff any field enriched
}
```

## Empirical warnings (22_crossref_research, 24_v1_l3_enrichment_test, 25_round2_synthesis)

- **arXiv DOIs return 404 100% of the time** — both `10.48550/arXiv.*` and `10.48550/arxiv.*` forms; `_is_arxiv_doi()` pre-filters them, no network call made. CrossRef indexes published-with-publisher only.
- **HTTP 404 returns plain-text "Resource not found." instead of JSON** — `_fetch_doi()` checks `Content-Type: application/json` before `.json()`. Without this guard you get spurious exceptions.
- **`clinical-trial-number[]` is mostly empty even on NEJM RCTs** — all 4 NEJM clinical-trial papers in V1 test returned empty. Use `pubmed_helper enrich` as primary source for this field; CrossRef provides it as backup (piggybacks the funder fetch, no extra cost).
- **References strictly more complete for NEJM/older papers** — NEJM 2020 COVID: OA `referenced_works_count=8`, CrossRef `reference[]=13`. Helper only overrides when CrossRef strictly larger; skips papers already ≥ 10 (threshold default).
- **Polite pool 10 req/s × 3 concurrent** — helper uses 10/s serial (`time.sleep(0.1)` between calls). For 20 top-N enrichment, ~12s. Don't try to parallelize at user level; the helper batches via `enrich_all` instead.
- **License `content-version` is the embargo type**: `tdm` (text-data-mining) / `vor` (version of record) / `am` (accepted manuscript) / `unspecified`. `delay_in_days` is days from publication to OA — 0 means immediate open access.

## Worked example: NEJM COVID 2020 BNT162b2

KG record before (other fields omitted):
```json
{"doi:10.1056/nejmoa2034577": {"doi": "10.1056/nejmoa2034577", "title": "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine", "authors": [{"name": "F. P. Polack"}], "rcs": 9, "referenced_works_count": 8, "sources": ["openalex"]}}
```

Run the STEP 10 command above (`--mode all --min-rcs 6`). After:
```jsonc
{"doi:10.1056/nejmoa2034577": {
  "doi": "10.1056/nejmoa2034577",
  "title": "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
  "authors": [{"name": "F. P. Polack"}],   // untouched
  "rcs": 9,                                 // untouched
  "referenced_works_count": 13,             // bumped from 8 — CR strictly more
  "sources": ["openalex", "crossref"],
  "funders": [
    {"name": "BioNTech and Pfizer", "doi": "10.13039/100004319", "award": []}
  ],
  "license": [
    {"URL": "https://www.nejm.org/about-nejm/permissions", "content_version": "vor", "delay_in_days": 0}
  ]
  // no clinical_trial_number: empty even on this RCT; use PubMed
}}
```

This is the canonical case where CrossRef pays for itself — funder DOI (10.13039/100004319) is unrecoverable from OpenAlex `grants[]` (empty for this paper) and is required for funding-source bias analysis in Audit-tier reporting.

## 中文 query 处理 (Cross-language)

crossref_helper is **enrichment-only** (DOI-based lookup) — there is no query string to translate. It operates on whatever DOI set the upstream pipeline collected, regardless of original query language; the command is the STEP 10 command above.

Caveats for Chinese-affiliated work:
- Funder DOI coverage is North-American + European biased — Chinese funders (NSFC, MOST) are present but sparser, and `funders[]` will often be empty even on well-funded Chinese papers.
- `license[].URL` returns publisher pages; Chinese publishers (e.g. Higher Education Press) have less consistent `content_version` metadata than NEJM/Springer.
- `referenced_works_count` is fully accurate regardless of language — this is the most language-neutral CrossRef enrichment.
