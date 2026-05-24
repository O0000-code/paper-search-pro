# ss_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 10 (L3 enrichment of top-N rcs ≥ 6 papers).

**Role**: enrichment-only L3 — Semantic Scholar is NOT an independent search source. It adds `influentialCitationCount` (the unique SS signal OpenAlex has nothing comparable to), `tldr` (HTML display only), abstract fallback when OA reconstruction is null, and cross-source citation count validation.

**Entry point**: `python3 -m scripts.ss_helper --input-file <papers.json> --mode <enrich|validate> [--output-file <path>]`.
**Init source**: `init(load_config())` — uses `semantic_scholar_api_key` from config.

## Two modes

| `--mode` | Function | Output |
|---|---|---|
| `enrich` (default) | Batch enrich a paper list with influential count + abstract + tldr | enriched paper list (UnifiedPaperEntity[]) |
| `validate` | Cross-source citation_count delta > 30% conflicts | conflicts list `[{paper_id, title, oa_count, ss_count, delta_pct}]` |

## Syntax + examples

```bash
# Standard mode: enrich top-N papers in place
python3 -m scripts.ss_helper \
    --input-file ./paper-search-results/<id>/kg_classified.json \
    --mode enrich \
    --output-file ./paper-search-results/<id>/kg_classified.json
# Adds .influential_citation_count, .ss_paper_id, .abstract (fallback only), .tldr
# Marks sources[] += "semantic_scholar" on successful enrichment

# Validate: detect citation conflicts (Audit-tier data quality check)
python3 -m scripts.ss_helper \
    --input-file ./paper-search-results/<id>/kg_classified.json \
    --mode validate \
    > validation_conflicts.json
# Lists papers where |OA - SS| / OA > 30% — typically arXiv-fallback DOI under-counts
# or pre-2000 papers with SS coverage gaps
```

## Internal functions (Python API)

| Function | Use |
|---|---|
| `enrich_with_metadata(papers)` | Batch enrich (single HTTP request via `sch.get_papers(ids)`). Mutates + returns. |
| `abstract_fallback(paper)` | Single-paper abstract retry; returns SS abstract, else `tldr.text`, else None. |
| `cross_validate_citation(papers)` | Returns 30%-delta conflicts list. |

## Output JSON fields enriched

- `influential_citation_count: int` — the unique SS signal (use for ranking top influential, not just most-cited)
- `ss_paper_id: str` — SS hex paperId (debugging cross-reference)
- `abstract: str` — filled ONLY if OpenAlex left it None
- `tldr: str` — 2-3 sentence auto-generated summary (HTML DISPLAY ONLY; do NOT feed to AI classifier)
- `sources: [...]` — `"semantic_scholar"` appended

## Empirical warnings (24_v1_l3_enrichment_test, 25_round2_synthesis)

- **Hard 1 RPS rate limit** — SS has NO paid tier; API key just buys auth-shape, not throughput. Batch `get_papers()` IS a single HTTP request (verified 2026-05-21: 2 DOIs in 528ms), so prefer batch over per-paper loops.
- **arXiv DOIs return 404 100% of the time** — `_doi_for_ss()` filters them out (any DOI containing `arxiv`). Don't even attempt; SS's arXiv coverage is via paperId only, not DOI.
- **`tldr` is for HTML display only**, NOT for the RCS classifier — per user directive (22_ss_research §4.3, 25_round2 §4). TLDR is auto-generated and can mislead the classifier; abstract is authoritative.
- **Per-paper fallback needs 1.1s sleep** — when batch `get_papers` fails, the helper falls back to `get_paper()` in a loop with `time.sleep(1.1)` between calls (1 RPS sustained + margin).
- **Empty abstract from SS** sometimes returned on publisher takedown — treated as falsy. Fall back to PubMed (medical) via STEP 4 if needed.
- **Citation conflict >30% threshold** chosen empirically — SA-V1 24_v1_l3_enrichment_test §3.1 showed 7/20 papers exceeded 30% in real data; this catches arXiv-fallback artefacts + old-paper coverage gaps without false-positiving normal SS undercount (typically 20-50%).

## Worked example

Input: 3-paper list with mixed status

```json
[
  {"doi": "10.1162/neco.1997.9.8.1735", "title": "LSTM", "citation_count": 65000},
  {"doi": "10.48550/arxiv.1706.03762", "title": "Attention Is All You Need", "citation_count": 6543},
  {"doi": "10.1038/nature14539", "title": "Deep Learning Review", "citation_count": 60000}
]
```

Run: `python3 -m scripts.ss_helper --input-file in.json --mode enrich`

Output (relevant fields only):

```json
[
  {
    "doi": "10.1162/neco.1997.9.8.1735",
    "influential_citation_count": 10359,    // SS unique signal — 16% ratio = real-method usage
    "ss_paper_id": "44d011f...",
    "tldr": "A long short-term memory (LSTM) network can learn...",
    "sources": ["openalex", "semantic_scholar"]
  },
  {
    "doi": "10.48550/arxiv.1706.03762",
    // No SS data — arXiv DOI 404'd; silently skipped
    "sources": ["openalex"]
  },
  {
    "doi": "10.1038/nature14539",
    "influential_citation_count": 2280,     // ~3.8% ratio — review (less "used" than methods)
    "ss_paper_id": "d0c7d59...",
    "sources": ["openalex", "semantic_scholar"]
  }
]
```

Note the influential ratio is the discriminator: BERT 19.5%, Adam 15.9%, LSTM 16%, GAN 14.5%, Attention 11.2% (real methods being adopted) vs. LeCun DL Review 3.8% (cited heavily but not "used"). This is the unique L3 signal worth the latency.

## 中文 query 处理 (Cross-language)

ss_helper is **enrichment-only** (DOI-based lookup) — there is no query string to translate. It operates on the DOI/title set already collected by OpenAlex + PubMed, so Chinese-language papers will be enriched correctly as long as they have valid DOIs upstream.

```bash
# Same invocation regardless of user query language — the input is a DOI-keyed paper list.
python3 -m scripts.ss_helper \
    --input-file ./paper-search-results/<id>/kg_classified.json \
    --mode enrich \
    --output-file ./paper-search-results/<id>/kg_classified.json
```

Caveat: Semantic Scholar's `influential_citation_count` algorithm is trained predominantly on English-language citation patterns. For papers in Chinese-only journals, this signal is less reliable (often `null` or low even for well-cited regional papers). Treat `influential_citation_count == null` as "no signal", not "low influence".
