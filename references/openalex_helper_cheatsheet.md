# openalex_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 3 (always-on L1 retrieval) and STEP 9 (citation expansion).

**Entry point**: `python3 -m scripts.openalex_helper <subcmd> [args]` (must be run from skill root).
**Init source**: `init_pyalex(load_config())` — uses `openalex_email` + `openalex_api_key` from `~/.paper-search-pro/config.yaml`. See `setup.md`.
**Output**: every subcommand writes a JSON `UnifiedPaperEntity[]` (or single object) to stdout. Redirect to `raw/openalex.json` for STEP 5 federation.

## 11 subcommands

| Cmd | Use | Default budget |
|---|---|---|
| `search` | Keyword + year + type filter, top-N by relevance | limit=25 |
| `get` | Single paper by OA-ID or DOI | n/a |
| `deep` | Top-N by a single sort (cited / recency / relevance) | n=100 |
| `double-sort` | Multi-strategy combine + cross-strategy boost | n=50 per strat |
| `seminal` | High-cited classics (year<=year_max, cited desc) | limit=10 |
| `reviews` | type=review filter | limit=10 |
| `journal-list` | Restrict to a JOURNAL_PRESETS whitelist | limit=25 |
| `citation-network` | Backward refs + forward cited_by for one paper | refs=50 cited=100 |
| `author` | h-index, i10, affiliations, topics by A-ID or name | n/a |
| `trends` | year histogram via group_by("publication_year") | 2010-2026 |
| `presets` | List available journal preset names + size | n/a |

## Syntax + examples

```bash
# Search — Quick tier default; broad keyword scan
python3 -m scripts.openalex_helper search "prospect theory" --limit 30 --year-min 2018

# Get — single paper lookup; both forms accepted
python3 -m scripts.openalex_helper get W3011865677
python3 -m scripts.openalex_helper get 10.2307/1914185           # DOI bare form
python3 -m scripts.openalex_helper get https://doi.org/10.1038/x

# Deep — single-sort top-100 (Standard tier baseline)
python3 -m scripts.openalex_helper deep "working memory training" --n 100 \
    --sort cited_by_count:desc --year-min 2015
# Valid --sort: cited_by_count:desc | publication_date:desc | relevance_score:desc

# Double-sort — Standard+/Deep multi-strategy (RECOMMENDED)
python3 -m scripts.openalex_helper double-sort "attachment human-robot interaction" \
    --n 50 --year-min 2018 > raw/openalex.json
# Combines cited + recent + relevance, papers seen in ≥2 strategies ranked higher.

# Seminal — high-cited classics (Deep tier signature move)
python3 -m scripts.openalex_helper seminal "prospect theory" --year-max 2000 --limit 15
# E.g. K&T 1979 Econometrica cited 46625, returns as #1 for "prospect theory"

# Reviews — type-filter for review articles (Deep tier; lit review writing)
python3 -m scripts.openalex_helper reviews "working memory training elderly" --limit 15 --year-min 2018

# Journal-list — whitelist top-tier venues
python3 -m scripts.openalex_helper journal-list "ESG disclosure" --preset UTD24 --limit 30
python3 -m scripts.openalex_helper journal-list "BNT162b2 efficacy" --preset medical_top --limit 20

# Citation-network — STEP 9 expansion for top-RCS seeds
python3 -m scripts.openalex_helper citation-network W2964249885 \
    --refs-limit 50 --cited-by-limit 100 >> raw/citations.json
# Returns {"references": [UnifiedPaperEntity], "cited_by": [UnifiedPaperEntity]}

# Author profile
python3 -m scripts.openalex_helper author "Daniel Kahneman"
python3 -m scripts.openalex_helper author A1969205032

# Trends — year histogram for the topic
python3 -m scripts.openalex_helper trends "transformer language model" --year-min 2017 --year-max 2026
```

## Output JSON fields

Per-paper (`UnifiedPaperEntity`): `doi`, `arxiv_id`, `openalex_id`, `pmid`, `pmcid`, `title`, `abstract`, `authors[]`, `year`, `venue`, `type`, `citation_count`, `referenced_works_count`, `fwci`, `cited_by_percentile_year`, `topics[]`, `keywords[]`, `sdgs[]`, `is_oa`, `doi_url`, `openalex_url`, `pdf_url`, `sources=["openalex"]`. Full schema: `scripts/types.py`.

`author` subcommand: `{id, name, h_index, i10_index, two_year_mean_citedness, total_citations, works_count, top_affiliations[], top_topics[], orcid}`.

`citation-network`: `{references: [UnifiedPaperEntity], cited_by: [UnifiedPaperEntity]}`.

`trends`: `{year: count}` dict, sorted by year.

## JOURNAL_PRESETS (6)

| Preset | Size | Use case |
|---|---|---|
| `UTD24` | 24 | Business school academic standard (Accounting/Finance/Mgmt/Marketing/IS/Ops/Econ/OB) |
| `FT50` | 50 | Financial Times broader business research methodology |
| `nature_science` | 4 | Nature / Science / Cell / PNAS — top general science |
| `ml_top_venues` | 6 | NeurIPS / ICML / ICLR / JMLR / CVPR / ACL — ML conferences as venues |
| `medical_top` | 6 | NEJM / Lancet / JAMA / BMJ / Nature Medicine / Cell |
| `Cochrane` | 1 | Cochrane Database of Systematic Reviews — SR/MA gold standard |

Names are RESOLVED to OpenAlex source IDs at runtime (display_name filter is unreliable; SA-Z2 §4 verified).

## Empirical warnings (SA-Y2 / SA-Z2 verified)

- **per_page hard-capped at 20** — pyalex returns ~25k-token payloads when per_page>20 even though API accepts up to 200. Helper internally enforces `_PER_PAGE=20` and pages.
- **OpenAlex W-IDs drift between releases** — if you have a W-ID that 404s, retry as DOI lookup. `get` handles `10.x/y` -> `https://doi.org/10.x/y` for you.
- **Attention paper bug** (`10.48550/arxiv.1706.03762`): OpenAlex returns `cited_by_count=6543`, a data-merger bug — not a pyalex defect. Treat as known anomaly; SS gives the more accurate figure (~80k).
- **Abstract must be reconstructed** from `abstract_inverted_index` via `pyalex.invert_abstract()` — helper does this. Old papers (pre-2000) may have `null` inverted index → abstract is `None`. Fall back to SS (STEP 10) when this matters.
- **Journal preset filter requires source-ID resolution**, not display_name match. `journal-list` calls `Sources().search(name)` first, then filters Works by source id pipe — adds ~1-2 s but the only reliable approach.
- **arxiv_id lives in `locations[].landing_page_url`**, not as a top-level field. `_extract_arxiv_id` parses URLs like `arxiv.org/abs/<id>v5` and strips the `vN` suffix.
- **OpenAlex indexing lag for arXiv ~4-5 days** — for T-0~T-4 freshness, use `arxiv_helper freshness` (STEP 4); don't expect OpenAlex to have new preprints.

## 中文 query 处理 (Cross-language)

OpenAlex strongly prefers English keywords (its index is multilingual but English coverage is widest, and `relevance_score` is computed against English-language abstracts/titles for the bulk of the corpus). When the user query is in Chinese, the main agent should translate the **search terms** to English before passing to this helper. Preserve the user's original Chinese query as report metadata (`--query` value or `user_query` field), so the final HTML/MD shows what they actually asked.

```bash
# User: "青少年焦虑认知行为治疗"
# Translate search terms only; keep original for report metadata.
python3 -m scripts.openalex_helper double-sort "adolescent anxiety cognitive behavioral therapy" \
    --n 50 --year-min 2018 > raw/openalex.json
# Then in summary.md / report.md: cite the user's original "青少年焦虑认知行为治疗" verbatim.

# Tip: include both Chinese-romanized authors and English transliterations when querying by author —
# OpenAlex matches "Daniel Kahneman" but not "卡尼曼".
```

Anti-pattern: passing the Chinese string directly to `--query` produces near-zero recall on most topics (OA's Chinese index is sparse outside CN-affiliated journals). Translation is required; do not skip it.
