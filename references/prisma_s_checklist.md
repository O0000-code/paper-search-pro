# PRISMA-S 16-item checklist

Referenced by `SKILL.md` STEP 13 (`prisma_s_logger.py` writes `execution_log.json`).

PRISMA-S is the search-reporting extension to PRISMA 2020 (Rethlefsen et al. 2021, *Systematic Reviews*). Every Audit-tier run MUST log all 16 items; lighter tiers log what's available. The fields below match the keys in `scripts/prisma_s_logger.py::build_prisma_s_log()` 1:1.

**This is NOT a PRISMA replacement** — paper-search-pro is an SR-prep assist (Quick/Standard/Deep/Audit tiers). Full Cochrane-grade SR still requires manual screening, dual reviewers, risk-of-bias scoring, and PROSPERO registration. We log what we can automate; you fill the rest.

## Compliance scope

| Tier | Items auto-filled | User fills (manual) |
|---|---|---|
| Quick / Standard | 1, 2, 8, 13, 14, 15, 16 (7 of 16) | 3, 4, 5, 6, 7, 9, 10, 11, 12 — most are "not performed" / "out of scope" |
| Deep | + 5 (citation searching) | Same as above |
| Audit | + 9, 10, 11 (filters / hedges / force-includes) | Just 3, 4, 6 (registries / online / authors) |

## The 16 items

### 1. database_information
- **Description**: List of databases queried + primary source designation
- **Auto-fills**: `databases` (deduped from all `paper.sources[]`), `primary` (OpenAlex when used), `note`
- **User fills**: Nothing — fully automatic

```jsonc
"1_database_information": {
  "databases": ["openalex", "semantic_scholar", "pubmed", "arxiv", "crossref"],
  "primary": "OpenAlex",
  "note": "OpenAlex polite pool + Semantic Scholar (supplement). Audit may add PubMed/arXiv."
}
```

### 2. multi_database_searching
- **Description**: Whether ≥2 databases used + rationale
- **Auto-fills**: `performed` (≥2 sources), `rationale` (Bramer 2018 98.3% recall benchmark)
- **User fills**: Nothing

### 3. study_registries
- **Description**: Trial/study registries (ClinicalTrials.gov / WHO ICTRP / Cochrane CENTRAL)
- **Auto-fills**: `queried=false`, `note` (out of scope by default)
- **User fills**: If you queried Cochrane CENTRAL manually for Audit, append the search strings + retrieval date here

### 4. online_resources_browsing
- **Description**: Conference proceedings / preprint servers browsed independently
- **Auto-fills**: `performed=false`, `note` (out of scope)
- **User fills**: If you browsed NeurIPS proceedings or arXiv listings manually, note it

### 5. citation_searching
- **Description**: Forward/backward citation chasing
- **Auto-fills**: `performed` (true iff any paper has `discovery_path` starting with `ref of` or `cites`), `method` (OpenAlex bidirectional), `max_hops`, `seeds_count`
- **User fills**: Nothing — fully automatic

```jsonc
"5_citation_searching": {
  "performed": true,
  "method": "OpenAlex forward+backward citation chase up to configured max_hops.",
  "max_hops": 2,
  "seeds_count": 5
}
```

### 6. contacts
- **Description**: Authors / topic experts contacted for grey literature
- **Auto-fills**: `performed=false`
- **User fills**: If you emailed authors for unpublished data, note who + when

### 7. other_methods
- **Description**: Hand-searching, expert consultation, AI-assisted search, etc.
- **Auto-fills**: `performed=false`, `methods=[]`
- **User fills**: If you used Elicit / Undermind / ResearchRabbit alongside, list them

### 8. full_search_strategies
- **Description**: Full Boolean query strings, reproducible across databases
- **Auto-fills**: `queries[]` from `state.query_plan`, `boolean_expressions[]` per-source variants
- **User fills**: Nothing — main agent writes these in STEP 1 query planning

```jsonc
"8_full_search_strategies": {
  "queries": [
    "prospect theory AND (loss aversion OR risk preference) AND decision making",
    "behavioral economics AND framing effect"
  ],
  "boolean_expressions": [
    {"text": "prospect theory ...", "openalex": "...", "semantic_scholar": "...", "type": "concept_block"}
  ],
  "note": "Strategy reproducible; same boolean expressions executed against each database."
}
```

### 9. limits_and_restrictions
- **Description**: Year, language, publication-type filters applied
- **Auto-fills**: `filters_applied[]` from query plan
- **User fills**: `language`, `publication_type` if you applied them (these are currently null)

### 10. search_filters
- **Description**: Validated search filters / hedges (e.g. Cochrane RCT filter)
- **Auto-fills**: `validated_filters_used=[]`
- **User fills**: If you used a Cochrane Highly Sensitive Search Strategy, cite it (e.g. "Cochrane HSSS 2008 sensitivity-maximizing RCT filter")

### 11. prior_work
- **Description**: Force-included papers from prior knowledge (seed list)
- **Auto-fills**: `force_includes[]` from config
- **User fills**: If you manually injected DOIs known a priori, list them with rationale

### 12. updates
- **Description**: Incremental search to update prior review
- **Auto-fills**: `incremental_search=false`
- **User fills**: If this run is an update of a prior SR, list the prior search end-date

### 13. dates_of_searches
- **Description**: Start / end timestamps + wall-clock
- **Auto-fills**: `search_started_at`, `search_ended_at`, `wall_clock_seconds`
- **User fills**: Nothing — fully automatic

```jsonc
"13_dates_of_searches": {
  "search_started_at": "2026-05-21T14:30:00Z",
  "search_ended_at":   "2026-05-21T14:42:15Z",
  "wall_clock_seconds": 735.4
}
```

### 14. total_records
- **Description**: Records retrieved, deduped, screened, included
- **Auto-fills**: `records_screened`, `papers_in_kg`, `highly_relevant_count` (rcs ≥ 7), `coverage_estimate` (from discovery curve)
- **User fills**: Manual screening N for Audit — paper-search-pro doesn't do title/abstract dual review

### 15. deduplication
- **Description**: Dedup method
- **Auto-fills**: `performed=true`, `method` (DOI → arXiv ID → PMID → title-Jaro-Winkler), `note` (single-writer FederatedKG)
- **User fills**: Nothing

```jsonc
"15_deduplication": {
  "performed": true,
  "method": "FederatedKG 3-level dedup: DOI (Level 1) -> arXiv ID (Level 2) -> Jaro-Winkler title similarity >= 0.92 (Level 3). Main agent single-writer pattern prevents race conditions.",
  "note": "Provenance preserved per paper in sources[]."
}
```

### 16. record_management
- **Description**: Tool / format / outputs produced
- **Auto-fills**: `tool="paper-search-pro/2.0"`, `format`, `outputs_produced[]`
- **User fills**: Nothing

```jsonc
"16_record_management": {
  "tool": "paper-search-pro/2.0",
  "format": "JSONL append-only checkpoint + materialized JSON outputs",
  "outputs_produced": ["report.html", "report.md", "papers.csv", "bibtex.bib", "ris.ris", "papers.json", "kg_classified.json", "summary.md", "execution_log.json"]
}
```

## Full execution_log.json schema

```jsonc
{
  "prisma_s": { "1_database_information": {...}, "2_multi_database_searching": {...}, ... "16_record_management": {...} },
  "discovery_curve_snapshots": [
    {"n_evaluated": 50, "n_highly_relevant": 12, "round": 1},
    {"n_evaluated": 100, "n_highly_relevant": 22, "round": 2}
  ],
  "agent_invocations": [],   // reserved for future use; reconstructed from CheckpointJSONL
  "errors": [
    {"code": "E3", "stage": "ss_enrich", "msg": "rate limit 429", "stop_reason": null}
  ],
  "stop_reason": "complete" | "budget_max_papers (200)" | "budget_max_wallclock" | ...,
  "search_id": "20260521_143052_prospect-theory-decision",
  "user_query": "prospect theory in decision making",
  "tier": "standard",
  "generated_at": "2026-05-21T14:42:15.234567"
}
```

## When the user submits to a journal

For Cochrane / JBI / Campbell SRs, the auto-filled fields cover ~70% of PRISMA-S. The 30% requiring manual completion: items 3 (registries), 6 (author contacts), 10 (validated hedges), 14 (manual screening counts post-screening). These are review-team responsibilities, not search-tool responsibilities.

For lighter SRs (rapid review / scoping review / narrative review), paper-search-pro's auto log + a 1-page methods narrative is usually sufficient.

## Reading the log

```bash
# Pretty-print just the PRISMA-S section
jq '.prisma_s' ./paper-search-results/<id>/execution_log.json

# Get the stop reason + duration
jq '{stop_reason, search_id, tier, prisma_s: .prisma_s["13_dates_of_searches"]}' \
   ./paper-search-results/<id>/execution_log.json

# Check coverage estimate
jq '.prisma_s["14_total_records"].coverage_estimate' ./paper-search-results/<id>/execution_log.json
```
