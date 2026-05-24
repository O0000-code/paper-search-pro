# pubmed_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 4 (L2 booster for medical queries) — primary use: MeSH enrichment of OA papers; Audit-tier secondary use: independent MeSH search for PRISMA workflow.

**Role**: L2 booster. PubMed's value is **precision via MeSH + publication_types + PMC URL**, NOT independent recall (SA-V2 24_v2_l2_booster_test verified: 30/30 "unique PubMed" papers already in OpenAlex globally). Use it as an enricher first, an independent search only for explicit PRISMA workflows.

**Entry point**: `python3 -m scripts.pubmed_helper <subcmd> [args]`.
**Init source**: `init(load_config())` — uses `ncbi_email` (required by NCBI ToS even without key) + `ncbi_api_key` (boosts 3 → 10 req/s).

## Four subcommands

| Cmd | Use | Tier |
|---|---|---|
| `enrich` | Bulk-enrich papers with `pmid` already set (from OpenAlex) | Standard / Deep |
| `search-mesh` | Independent MeSH-precise search (PRISMA workflow) | Audit only |
| `search` | Generic keyword search (auto-expands to MeSH internally) | Audit fallback |
| `by-pmid` | Single record by PMID | Diagnostic |

## Syntax + examples

```bash
# enrich — add MeSH terms + publication_types + PMC URL to existing papers
# Input: any JSON list with UnifiedPaperEntity dicts; papers without .pmid are skipped silently
python3 -m scripts.pubmed_helper enrich \
    --input-file ./paper-search-results/<id>/raw/openalex.json \
    --output-file ./paper-search-results/<id>/raw/openalex_enriched.json
# Single bulk efetch — one network call for the full eligible pmid list (NCBI accepts ~200 ids/call).

# search-mesh — Audit-tier independent search by MeSH descriptor
python3 -m scripts.pubmed_helper search-mesh "Diabetes Mellitus, Type 2" \
    --year-min 2020 \
    --limit 25 \
    > ./paper-search-results/<id>/raw/pubmed.json
# Quote multi-word MeSH terms exactly as they appear in NCBI MeSH browser.

# search-mesh with publication-type filter (PRISMA RCT inclusion)
python3 -m scripts.pubmed_helper search-mesh "Irritable Bowel Syndrome" \
    --year-min 2010 \
    --pub-type "Randomized Controlled Trial" \
    --pub-type "Meta-Analysis" \
    --limit 50

# search — generic keyword (Audit fallback when explicit MeSH unknown)
python3 -m scripts.pubmed_helper search "metformin gut microbiome" --year-min 2020 --limit 30
# Compare recall vs search-mesh: same query reaches ~70% more papers via keyword;
# precision drops correspondingly. Use MeSH unless you need recall.

# by-pmid — single record diagnostic / cross-reference
python3 -m scripts.pubmed_helper by-pmid 33301246
```

## Output JSON format

`enrich` output: enriched UnifiedPaperEntity dicts with these additional/updated fields:

| Field | Source |
|---|---|
| `mesh_terms: List[str]` | PubMed MedlineCitation.MeshHeadingList.DescriptorName (authoritative) |
| `publication_types: List[str]` | e.g. `["Journal Article", "Randomized Controlled Trial", "Multicenter Study"]` |
| `pmcid: str` | "PMC9876543" (only filled if missing) |
| `pmc_url: str` | "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9876543/" |
| `abstract: str` | Filled ONLY if missing — OA reconstructed wins; PubMed = fallback |
| `sources: List[str]` | Appends `"pubmed"` |

`search-mesh` / `search` / `by-pmid` output: parsed dicts (not full UnifiedPaperEntity) with `{pmid, doi, pmcid, pmc_url, title, abstract, year, mesh_terms, publication_types}`. Main agent materializes UnifiedPaperEntity downstream during STEP 5 federation.

## MeSH vs keyword precision-recall (empirical, 22_pubmed_research)

| Query | Keyword | MeSH |
|---|---|---|
| `metformin` | 37,148 records | 21,000 records (`"Metformin"[MeSH Terms]`) |
| `working memory` | ~78,000 | 38,500 (`"Memory, Short-Term"[MeSH]`) |
| `prospect theory` | ~5,400 | n/a (no MeSH term) — keyword only |

MeSH narrows to the precise concept; keyword catches synonyms + adjacent topics. Cochrane/PRISMA workflow requires MeSH for primary search; use keyword only for sensitivity analysis.

## Publication Type filter values

Repeat `--pub-type "X"` for OR. Common types (case-sensitive, must match NCBI exactly):

| Filter | Use |
|---|---|
| `Randomized Controlled Trial` | RCT inclusion criterion |
| `Meta-Analysis` | SR/MA evidence pyramid top |
| `Systematic Review` | SR/MA evidence pyramid top |
| `Clinical Trial` | Broader than RCT (includes Phase I/II/III) |
| `Review` | Narrative + scoping reviews |
| `Multicenter Study` | Cross-site evidence |
| `Comparative Study` | Comparator-based design |
| `Practice Guideline` | Clinical practice guidelines |
| `Observational Study` | Cohort / case-control |

## Empirical warnings (22_pubmed_research, 24_v2_l2_booster_test, 25_round2_synthesis)

- **No independent recall over OpenAlex** — 30/30 "PubMed unique" papers in test set were already in OpenAlex globally. Use enrich as primary mode; search-mesh only when PRISMA workflow requires explicit MeSH search.
- **NCBI key boosts 3 → 10 req/s** but is NOT required — anonymous works, slower. Helper uses 5 req/s (`time.sleep(0.2)`) as safe rate with key.
- **`ncbi_email` is mandatory** per NCBI API ToS even without a key. Without it: 429 / blocked. See `setup.md`.
- **Bulk efetch is ONE network call regardless of size** (up to ~200 PMIDs in single comma-list). Helper exploits this — `enrich_with_mesh` makes 1 call for the whole eligible set. Don't loop.
- **MeSH terms always overwritten** with PubMed authoritative data (vs. OA-fallback). PMCID / PMC URL / abstract only filled if missing (OA wins when present).
- **No abstract on takedown** — some 2020+ papers have abstract redacted; helper returns empty string, leaves OA value in place.

## 中文 query 处理 (Cross-language)

PubMed's MeSH is an English-language controlled vocabulary — Chinese keywords route through PubMed's translation layer with mediocre precision, and `search-mesh` requires the **canonical English MeSH descriptor** to match. When the user query is in Chinese, the main agent must translate the search concept to the official MeSH term (lookup at https://meshb.nlm.nih.gov/) before passing to this helper. The original Chinese query is preserved as report metadata, not as a search argument.

```bash
# User: "青少年焦虑认知行为治疗"
# Map each concept → MeSH descriptor; do NOT pass Chinese to PubMed.
# 青少年 → "Adolescent" (MeSH)
# 焦虑   → "Anxiety Disorders" (MeSH)
# 认知行为治疗 → "Cognitive Behavioral Therapy" (MeSH)
python3 -m scripts.pubmed_helper search-mesh "Cognitive Behavioral Therapy" \
    --year-min 2018 --limit 25 \
    > ./paper-search-results/<id>/raw/pubmed.json
# Combine with PubMed's MeSH AND-stacking when needed — but each term must be an exact descriptor.

# Anti-pattern (won't work): search-mesh "认知行为治疗" → returns ~0 hits.
```

For `enrich` mode (the primary use), the helper looks up PMIDs already attached to OA papers — no query translation is needed there. Translation only matters when running `search-mesh` / `search` in Audit tier.
