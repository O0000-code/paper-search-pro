# arxiv_helper CLI cheatsheet

Referenced by `SKILL.md` STEP 4 (L2 booster) — primary use: T-0~T-4 freshness window for preprints OpenAlex hasn't indexed yet (OA lags 4-5 days for arXiv ingestion).

**Role**: L2 Freshness Sentinel. arXiv's killer feature is the recent-preprint window; beyond ~4 days, 39/40 (98%) of arXiv papers are also in OpenAlex (SA-V2 24_v2_l2_booster_test §4 verified). Don't use arXiv for retrospective search — use OA.

**Entry point**: `python3 -m scripts.arxiv_helper <subcmd> [args]`.
**No key required**. Rate limit: 1 req per 3 s (arXiv ToU enforced). Helper SDK uses `delay_seconds=4` (1 s safety margin) + `page_size=100`.

## Three subcommands

| Cmd | Use | Tier |
|---|---|---|
| `freshness` | T-0~T-N day window (default 4 = OA lag) | Standard+ when freshness signal in query |
| `search` | General arXiv search by submitted/relevance | Audit |
| `get` | Single paper by arxiv_id | Diagnostic |

## Syntax + examples

```bash
# freshness — primary use: recent preprints OA can't yet see
python3 -m scripts.arxiv_helper freshness "LLM reasoning" --days 4 --limit 30 \
    > ./paper-search-results/<id>/raw/arxiv.json
# Returns preprints with published >= now - 4 days. arXiv returns date-desc, so this
# truncates cleanly once we drop below cutoff.

# freshness with all categories (include physics/astro/cond-mat for physical-science queries)
python3 -m scripts.arxiv_helper freshness "neutron star merger" --days 7 --limit 20 --all-cats

# search — Audit-tier general search
python3 -m scripts.arxiv_helper search "diffusion model robustness" --limit 30 --sort submitted
# Valid --sort: submitted (default, newest first) | relevance | lastUpdated

# get — single paper lookup
python3 -m scripts.arxiv_helper get 1706.03762            # bare id
python3 -m scripts.arxiv_helper get 1706.03762v5          # version-suffixed
python3 -m scripts.arxiv_helper get https://arxiv.org/abs/2401.12345
python3 -m scripts.arxiv_helper get hep-th/9707234         # legacy form
```

## Categories — DEFAULT vs --all-cats

`DEFAULT_CATEGORIES` (used unless `--all-cats`):

| Cat | Field |
|---|---|
| `cs.*` | Computer Science (CL/AI/LG/CV/etc.) |
| `math.*` | Mathematics |
| `stat.*` | Statistics |
| `q-bio.*` | Quantitative Biology |
| `q-fin.*` | Quantitative Finance |
| `econ.*` | Economics |

`--all-cats` adds: `physics.*`, `astro-ph.*`, `cond-mat.*`, `hep-th/ph/ex/lat`, `gr-qc`, `nlin.*`, `nucl-th/ex`, `quant-ph`, `eess.*`.

**WHY DEFAULT EXCLUDES PHYSICS**: Q4 实测 (SA-V2 §3.4) — query "prospect theory" without category filter returned reactor experiments named "PROSPECT". The cat filter is the only defense for social-science queries. Opt into physics explicitly.

## Output JSON fields

Per-paper (`UnifiedPaperEntity`):

```jsonc
{
  "doi": "10.48550/arxiv.2401.12345",      // canonical lowercase, no version
  "arxiv_id": "2401.12345",
  "title": "...",
  "abstract": "...",                        // arXiv always has full abstract
  "authors": [{"name": "Yann LeCun"}],
  "year": 2024,
  "venue": "arXiv",
  "type": "preprint",
  "arxiv_categories": ["cs.CL", "cs.AI"],
  "arxiv_comment": "Accepted at NeurIPS 2024",   // submitter's note; often empty
  "pdf_url": "https://arxiv.org/pdf/2401.12345v3",
  "sources": ["arxiv"],
  "discovery_path": "arxiv:freshness"
}
```

## Helper utilities (Python API)

| Function | Use |
|---|---|
| `normalize_arxiv_doi(doi)` | `10.48550/arXiv.1706.03762v5` → `10.48550/arxiv.1706.03762` |
| `extract_arxiv_id(s)` | URL / version-suffixed → bare id (handles new + legacy form) |
| `search_freshness_window(q, days, limit, categories)` | Programmatic freshness search |

## Empirical warnings (SA-V2 24_v2_l2_booster_test, 25_round2_synthesis)

- **arXiv DOI case chaos** — arXiv emits `10.48550/arXiv.<id>` (capital X), OpenAlex emits `10.48550/arxiv.<id>` (lowercase). `normalize_arxiv_doi` lowercases and strips version suffix. `federated_kg_resolver.normalize_doi` does the same — both required for dedup.
- **Rate limit 1 req per 3 s STRICT** — SDK uses 4s default. Going faster = 429 + temporary ban. Don't parallelize calls.
- **Relevance ranking is weak on arXiv** — SA-V2 §1.5: top-5 for "attention is all you need" did NOT contain 1706.03762 itself. Use OpenAlex for relevance; arXiv only for `submitted` sort (newest first) or specific id lookup.
- **OpenAlex lags ~4-5 days indexing arXiv** — T-0 / T-1 / T-2 produce 0 hits on OpenAlex; T-3 starts trickling; T-4+ stable. This is the only window where arXiv has unique value.
- **Cross-listed categories**: a paper can list `cs.LG` AND `stat.ML` AND `physics.bio-ph`. DEFAULT cat filter is OR'd, so any-match suffices. Be careful with `--all-cats` on social-science queries — physics noise enters.
- **Abstract always present** on arXiv (unlike OA's reconstruction or SS's takedown gaps) — arXiv is a useful abstract source for very recent papers that other databases haven't indexed.
- **Version suffix stripped everywhere** — `arxiv_id` is always bare (no `vN`). DOI normalized too. If you need a specific version, query the source URL directly; the helper de-versions for dedup safety.

## 中文 query 处理 (Cross-language)

arXiv is an English-only preprint server — titles, abstracts, and search are all English. Chinese queries on `freshness` / `search` return ~0 hits even when relevant Chinese-authored papers exist on the server (those papers are submitted in English). The main agent must translate search terms to English before calling this helper; the user's Chinese query is preserved only as report metadata.

```bash
# User: "扩散模型鲁棒性"  (diffusion model robustness)
python3 -m scripts.arxiv_helper search "diffusion model robustness" --limit 30 --sort submitted

# User: "大语言模型推理 最新"  (LLM reasoning, recent)
python3 -m scripts.arxiv_helper freshness "LLM reasoning" --days 4 --limit 30 \
    > ./paper-search-results/<id>/raw/arxiv.json
```

For pure social-science / humanities Chinese queries with no English equivalent on arXiv, skip the arXiv booster entirely (source_routing already handles this — arXiv is only enabled for CS / freshness signals).
