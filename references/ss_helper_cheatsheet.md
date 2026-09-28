# ss_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 10 (L3 enrichment of top-N rcs ≥ 6 papers).

**Role**: enrichment-only L3 — Semantic Scholar is NOT an independent search source. It adds `influentialCitationCount` (the unique SS signal OpenAlex has nothing comparable to), `tldr` (HTML display only), abstract fallback when OA reconstruction is null, and cross-source citation count validation.

**Entry point**: `python3 -m scripts.ss_helper --input-file <kg_classified.json> --mode <enrich|validate> [--min-rcs N] [--output-file <path>]`.
**Init source**: `init(load_config())` — uses `semantic_scholar_api_key` from config.

## Two modes

| `--mode` | Function | Output |
|---|---|---|
| `enrich` (default) | Batch enrich influential count + abstract + tldr | the whole KG with the enriched fields patched in |
| `validate` | Cross-source citation_count delta > 30% conflicts | conflicts list `[{paper_id, title, oa_count, ss_count, delta_pct}]` |

`--min-rcs N` limits either mode to papers whose `rcs` is an integer ≥ N; without it every paper is sent.

## Syntax + examples

```bash
# STEP 10: enrich the rcs >= 6 papers of the KG, in place
PYTHONPATH=$PSP_HOME python3 -m scripts.ss_helper \
    --input-file "$SEARCH_DIR/kg_classified.json" \
    --mode enrich --min-rcs 6 \
    --output-file "$SEARCH_DIR/kg_classified.json"

# Validate: detect citation conflicts (Audit-tier data quality check); never writes the KG
PYTHONPATH=$PSP_HOME python3 -m scripts.ss_helper \
    --input-file "$SEARCH_DIR/kg_classified.json" \
    --mode validate --min-rcs 6 \
    > "$SEARCH_DIR/validation_conflicts.json"
# Lists papers where |OA - SS| / OA > 30% — typically arXiv-fallback DOI under-counts
# or pre-2000 papers with SS coverage gaps
```

**What enrich changes in each KG record** (only for papers SS returned; everything else — `rcs`, `rcs_reasoning`, `authors`, `journal_rank`, unknown keys, key order — stays as it was):

- `influential_citation_count`, `tldr` — set from SS
- `abstract`, `ss_paper_id`, `venue`, `issn`, `issns` — filled only where the record has none
- `sources` — `"semantic_scholar"` appended

A JSON **list** of paper dicts is still accepted; it returns a list of 11 fields per paper (`doi, arxiv_id, openalex_id, ss_paper_id, title, abstract, year, citation_count, influential_citation_count, tldr, sources`), so it cannot be written back over the KG.

## The stderr line

Every enrich run ends with one line on stderr:

```
[paper-search-pro] Semantic Scholar enrichment: 52/58 papers enriched (6 not found).
[paper-search-pro] Semantic Scholar enrichment: 0/58 papers enriched (HTTP 403, key rejected).
[paper-search-pro] Semantic Scholar enrichment: 0/58 papers enriched (HTTP 429, rate limited).
```

A reason in brackets means Semantic Scholar refused or failed; the helper has already done the retrying it should (below), the unenriched papers are left as they were, and the exit code is 0. Relay the line to the user when the count is short — see `error_handling.md` E3. A rejected key also prints one line asking the user to renew `semantic_scholar_api_key`. Validate prints a line only when it fails (`Semantic Scholar citation check failed (…); the conflict list is incomplete.`).

## Internal functions (Python API)

| Function | Use |
|---|---|
| `enrich_with_metadata(papers)` | Batch enrich (one `/paper/batch` request per 500 DOIs). Mutates + returns; prints the stderr line. |
| `abstract_fallback(paper)` | Single-paper abstract retry; returns SS abstract, else `tldr.text`, else None. |
| `cross_validate_citation(papers)` | Returns 30%-delta conflicts list. |

## Output JSON fields enriched

- `influential_citation_count: int` — the unique SS signal (use for ranking top influential, not just most-cited)
- `ss_paper_id: str` — SS hex paperId (debugging cross-reference)
- `abstract: str` — filled ONLY if OpenAlex left it None
- `tldr: str` — 2-3 sentence auto-generated summary (HTML DISPLAY ONLY; do NOT feed to AI classifier)
- `venue`, `issn`, `issns` — from SS `publicationVenue` (all its ISSNs), only where missing; the journal-rank join tries every ISSN
- `sources: [...]` — `"semantic_scholar"` appended

## Empirical warnings (24_v1_l3_enrichment_test, 25_round2_synthesis)

- **Hard 1 RPS rate limit** — SS has NO paid tier; API key just buys auth-shape, not throughput. `/paper/batch` IS a single HTTP request (verified 2026-05-21: 2 DOIs in 528ms), so the helper sends up to 500 DOIs per request.
- **Failures are bounded** — a 429 on the batch request is waited out for up to ~4 min in total (honouring `Retry-After`, ≤ 60 s each), and on a single-paper request at most 3 times (≤ 20 s each); a rejected key is retried once without it, and the rest of the process stays keyless. If the batch fails for its own reasons (network error, HTTP 400/5xx), the helper falls back to one request per paper with `time.sleep(1.1)` between calls; if SS refuses the client itself (403 even without the key, or 429 after the retries), it stops there instead of repeating the refusal per paper.
- **arXiv DOIs return 404 100% of the time** — `_doi_for_ss()` filters them out (any DOI containing `arxiv`). Don't even attempt; SS's arXiv coverage is via paperId only, not DOI.
- **`tldr` is for HTML display only**, NOT for the RCS classifier — per user directive (22_ss_research §4.3, 25_round2 §4). TLDR is auto-generated and can mislead the classifier; abstract is authoritative.
- **Empty abstract from SS** sometimes returned on publisher takedown — treated as falsy. Fall back to PubMed (medical) via STEP 4 if needed.
- **Citation conflict >30% threshold** chosen empirically — SA-V1 24_v1_l3_enrichment_test §3.1 showed 7/20 papers exceeded 30% in real data; this catches arXiv-fallback artefacts + old-paper coverage gaps without false-positiving normal SS undercount (typically 20-50%).

## Worked example

`kg_classified.json` before (other fields omitted):

```json
{
  "doi:10.1162/neco.1997.9.8.1735": {"doi": "10.1162/neco.1997.9.8.1735", "title": "LSTM", "rcs": 9, "sources": ["openalex"]},
  "doi:10.48550/arxiv.1706.03762": {"doi": "10.48550/arxiv.1706.03762", "title": "Attention Is All You Need", "rcs": 8, "sources": ["openalex"]},
  "doi:10.1038/nature14539": {"doi": "10.1038/nature14539", "title": "Deep Learning Review", "rcs": 4, "sources": ["openalex"]}
}
```

Run the STEP 10 command above (`--min-rcs 6`). After:

```jsonc
{
  "doi:10.1162/neco.1997.9.8.1735": {
    "doi": "10.1162/neco.1997.9.8.1735", "title": "LSTM", "rcs": 9,
    "sources": ["openalex", "semantic_scholar"],
    "influential_citation_count": 10359,   // SS unique signal — 16% ratio = real-method usage
    "tldr": "A long short-term memory (LSTM) network can learn...",
    "ss_paper_id": "44d011f..."
  },
  // arXiv DOI: skipped, record unchanged
  "doi:10.48550/arxiv.1706.03762": {"doi": "10.48550/arxiv.1706.03762", "title": "Attention Is All You Need", "rcs": 8, "sources": ["openalex"]},
  // rcs 4 < 6: not sent, record unchanged
  "doi:10.1038/nature14539": {"doi": "10.1038/nature14539", "title": "Deep Learning Review", "rcs": 4, "sources": ["openalex"]}
}
```

stderr: `[paper-search-pro] Semantic Scholar enrichment: 1/2 papers enriched (1 without a usable DOI).`

The influential ratio is the discriminator: BERT 19.5%, Adam 15.9%, LSTM 16%, GAN 14.5%, Attention 11.2% (real methods being adopted) vs. LeCun DL Review 3.8% (cited heavily but not "used"). This is the unique L3 signal worth the latency.

## 中文 query 处理 (Cross-language)

ss_helper is **enrichment-only** (DOI-based lookup) — there is no query string to translate. It operates on the DOI/title set already collected by OpenAlex + PubMed, so Chinese-language papers will be enriched correctly as long as they have valid DOIs upstream; records without a DOI (e.g. NSSD) are left unchanged and counted as "without a usable DOI".

The command is the same regardless of the user's query language (the STEP 10 command above).

Caveat: Semantic Scholar's `influential_citation_count` algorithm is trained predominantly on English-language citation patterns. For papers in Chinese-only journals, this signal is less reliable (often `null` or low even for well-cited regional papers). Treat `influential_citation_count == null` as "no signal", not "low influence".
