# Agent / headless mode (SSOT for agent callers)

**Read this when paper-search-pro is being driven by ANOTHER agent, or in any
non-interactive / headless context** — i.e. the consumer of the results is a
program (your own reasoning loop), not a human who wants an HTML report.

This file is the single source of truth for the `agent_search` structured-data
channel. The human-facing 14-STEP recipe in `SKILL.md` is a *different* path and
is unaffected by anything here (R-19).

---

## When to use agent mode (vs. the 14-STEP human recipe)

| You are… | Use |
|---|---|
| An agent feeding papers into your own judgement / a larger orchestration | **`agent_search`** (this file) |
| Want one structured JSON blob, no HTML, no PRISMA, no LLM classification | **`agent_search`** |
| A human (or driving for a human) who wants the Shadcn HTML report + exports | The 14-STEP recipe in `SKILL.md` |

**Why a separate path exists**: forensics on real sessions showed that when an
agent calls this Skill from inside an orchestration, it loads `SKILL.md` but then
only drives `openalex_helper` for raw retrieval and silently skips classification,
saturation, dedup, and HTML — every discipline step in the human recipe. A
stricter prompt does not fix this (Opus-class models skip user-defined sequences
even with CLAUDE.md + rules + hooks). The reliable fix is to **bake the discipline
into one deterministic command the agent cannot bypass** and hand back a single
self-describing envelope. That command is `agent_search`.

---

## The command

```bash
PYTHONPATH=$PSP_HOME \
  python3 -m scripts.agent_search "<query>" [flags] > result.json
```

`$PSP_HOME` is the Skill install dir (resolve it exactly as in `SKILL.md` STEP 0;
never `cd` into the Skill dir). The query supports the source's boolean operators
(OpenAlex / SS `+` = AND). **stdout is a single JSON envelope; nothing else.**

### What it does internally (the discipline you get for free)

One command runs the full deterministic core, in order, with NONE of it skippable:

1. **Source routing** — picks OpenAlex (default) or Semantic Scholar per config.
2. **Multi-strategy retrieve** — 3 strategies (cited / recent / relevance) so
   coverage does not depend on a single sort.
3. **Federated dedup** — DOI normalization, version stripping, same-title-different-DOI
   guard; merges all strategies into one unique set.
4. **Field tidy** — every paper is a full `UnifiedPaperEntity`.
5. **Heuristic relevance score** — computed for EVERY paper, always (see below).
   Cannot be silently skipped.
6. **Saturation signal** — advisory marginal-yield + score-distribution signals.
7. **Quota probe** — a single OpenAlex rate-limit snapshot.
8. **Journal rank** (the SINGLE journal layer, v2.2 collapse) — multi-platform
   partition (中科院 / JCR / SJR) per paper, each as a sub-slot, plus an `openalex`
   open-impact sub-slot (2yr mean citedness + h-index). Includes NL-intent
   recognition (`中科院一区` → filter, stripped from the query), optional tier filter,
   and adaptive deepening when a tier filter runs short (see below). The old SJR-only
   per-paper `journal_metric` step is retired — its SJR quartile + OpenAlex impact now
   live inside `journal_rank`.

It **never** renders HTML, **never** writes a PRISMA log, and **never** dispatches
an LLM classification SubAgent. Those are human-recipe concerns.

---

## JSON envelope schema (`schema_version: "1.0"`)

### Success

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": [ { <UnifiedPaperEntity fields>,
              "relevance":     { "score": 0.0, "label": "high|medium|low",
                                 "method": "heuristic_v1", "is_llm_rcs": false,
                                 "components": { "title_coverage": 0.0,
                                                 "abstract_coverage": 0.0,
                                                 "citation_signal": 0.0,
                                                 "recency_signal": 0.0 } },
              "journal_rank":   { "cas": { "tier": 1, "rank": "5/100", "top": true,  /* THE single journal layer */
                                           "minor": [{"category","tier","rank"}], "source_year": 2025 },
                                  "jcr": { "quartile": "Q1", "impact_factor": 48.5,  /* the ONLY real IF */
                                           "rank": "2/135", "category": "…", "source_year": 2024 },
                                  "sjr": { "best_quartile": "Q1", "sjr": 14.5,
                                           "per_category": [{"category","quartile"}], "source_year": 2024 },
                                  "openalex": { "mean_citedness_2yr": 0.0, "h_index": 0 },  /* OPEN impact, NOT an IF (R-04/R-09) */
                                  "matched_issn": "0028-0836",
                                  "matched_platforms": ["cas","jcr","sjr"] }  /* or null; each slot independently null */,
              "verify":         { … } /* only with --verify */ },
            … ],
  "meta": {
    "query":      { "topic", "search_query", "year_min", "year_max", "per_strategy", "terms": [] },
    "counts":     { "retrieved_raw", "after_dedup", "after_relevance_filter",
                    "after_journal_filter", "after_rank_filter", "returned" },
    "relevance":  { "method": "heuristic_v1", "is_llm_rcs": false,
                    "min_relevance", "weights": {}, "note" },
    "enrichment": { "enriched", "impact_source", "impact_attached",
                    "filter_quartiles", "filter_min_impact", "category",
                    "issn_backfill_enabled", "issn_backfill_attempted",
                    "issn_backfilled", "note" },  /* single journal_rank layer audit */
    "rank":       { "platform", "platform_source", "keep_tiers", "keep_quartiles",
                    "top_only", "category", "applied_filter", "ambiguous",
                    "candidate_platforms", "kept", "filtered", "no_platform_data",
                    "data_loaded", "loaded_platforms", "switchable_platforms",
                    "switch_is_refilter_not_research", "stripped_phrases",
                    "deepen": { "active", "rounds", "saturated", "final_per_strategy" },
                    "attribution", "note", "keep_tiers_note", "naming" },  /* journal_rank partition-filter decision */
    "saturation": { "method": "heuristic_v1", "advisory": true, "looks_saturated",
                    "per_strategy_new_papers": [], "last_strategy_marginal_yield",
                    "score_distribution": { "high", "medium", "low" }, "note" },
    "ratelimit":  { <quota probe snapshot>, "switched_source": false },
    "source_used": "openalex" | "semantic_scholar",
    "warnings":   [ … ],
    "verify_summary": { … }  /* only with --verify */
  }
}
```

`data` is a **flat list of papers**, sorted by relevance score (desc), tie-broken
by citation_count (desc). Analysis lives entirely in `meta`.

### Failure

```json
{ "ok": false, "schema_version": "1.0",
  "error": { "code": "E_*", "message": "…", "retryable": bool },
  "meta": { … } }
```

| `error.code` | Exit | retryable | Meaning |
|---|---|---|---|
| `E_NO_RESULTS` | 2 | false | Search ran but returned nothing — broaden the query. |
| `E_CONFIG` | 4 | false | Misconfiguration (e.g. empty query, or SS-primary with no key). |
| `E_RATE_LIMITED` | 7 | true | Upstream throttled / quota gone — back off and retry. |
| `E_INTERNAL` | 6 | false | Unexpected failure (a traceback is never leaked to stdout). |

Process **exit code mirrors `error.code`** so a non-LLM caller can branch on `$?`.

---

## Flags (full reference, verified against argparse)

| Flag | Type / default | Effect |
|---|---|---|
| `<query>` | positional, required | Search topic; boolean ops per source. |
| `--year-min N` | int / none | Minimum publication year (inclusive). |
| `--year-max N` | int / none | Maximum publication year (inclusive). |
| `--per-strategy N` | int / `50` | Papers per retrieval strategy before dedup. |
| `--limit N` | int / all | Max papers returned after scoring + filtering. |
| `--min-relevance X` | float / `0.0` | Drop papers scoring below `X` (0..1). Scoring is ALWAYS computed; this only filters what is RETURNED. |
| `--verify` | flag / off | Attach per-paper existence + abstract + cross-source consistency markers (see below). |
| `--quartile Q1,Q2` | csv / none | OPT-IN filter on `journal_rank.sjr.best_quartile` (the single layer); keep only these SJR quartiles. The partition is always attached. Needs cached journal-rank data (`journal_rank fetch` → `ranks/`). SJR分区, **NOT** JCR (R-04). For 区/category control use `--rank-platform`. |
| `--min-impact X` | float / none | Drop papers whose OPEN journal impact (`journal_rank.openalex.mean_citedness_2yr`, OpenAlex 2yr mean citedness) is below `X`. **NOT** the JCR Impact Factor (R-09); relative use only. |
| `--journal-category NAME` | str / none | **DEPRECATED** (legacy SJR-only layer). Use `--rank-platform sjr --rank-category` to pin a per-category quartile in the single layer. |
| `--sjr-csv PATH` | str / none | **DEPRECATED / ignored** — the legacy sjr_helper SJR-only path is retired. Cache SJR data with `journal_rank fetch --platform sjr` (→ `ranks/`) instead. |
| `--no-journal-metric` | flag / off | Skip journal-rank enrichment entirely (`journal_rank` stays `null`: no partition labels, no OpenAlex open impact). |
| `--rank-platform {cas,jcr,sjr}` | choice / none | **Multi-platform layer** (the A-line partition feature). The platform to FILTER on this run: `cas` (中科院 区) / `jcr` / `sjr`. Omit to take the platform from the query's NL intent (`中科院一区` → cas), else config `rank.default_platform` (which only LABELS, never filters). CAS 区 & SJR quartile are PARTITIONS; only JCR is a real IF (R-04). |
| `--keep-tiers 1,2` | csv / none | **Multi-platform layer.** Tiers/quartiles to KEEP, mapped onto the chosen platform: CAS uses 区 numbers (`1,2`); JCR/SJR use quartiles (`Q1,Q2`). OPT-IN: with none given every paper is labelled with all three platforms but nothing is filtered. With a tier filter the search ADAPTIVELY DEEPENS to meet the target count. |
| `--rank-category NAME` | str / none | **Multi-platform layer.** Pin the partition to a specific sub-category instead of the journal's best/大类: CAS reads the **小类 tier** for that category, SJR reads the **per-category quartile**, JCR (no per-category quartile in the source) treats it as a **category-membership gate**. A journal not present in the pinned category is filtered out. Category match is case-insensitive substring. |
| `--deepen-target N` | int / `--limit` or 10 | **Multi-platform layer.** Target survivor count adaptive deepening aims for when a tier filter is active. Deepening re-retrieves at greater depth and RE-FILTERS the same annotated pool — switching platform/tier afterwards is a re-filter, not a re-search. |
| `--no-issn-backfill` | flag / off (backfill ON by default) | **SS-primary path only.** By default, SS records missing an ISSN but with a DOI get a free OpenAlex single-paper lookup to recover the ISSN so the `journal_rank` join is not silently lost. Pass this to skip those per-paper lookups on large SS result sets — papers then stay unjoinable (the `meta.enrichment.issn_backfill_*` audit keeps the gap visible). No effect on the OpenAlex path. `meta.enrichment.issn_backfill_enabled` reports the gate. |
| `--verify-refs FILE.json` | path / none | **Anti-hallucination mode** (instead of a topic search): verify whether a list of references actually EXIST. The positional query is omitted. See the dedicated section below. |

All filters follow one contract: **signal-as-knob.** The underlying value
(relevance score, journal rank / open impact) is always computed and attached to
every paper; the flag only decides which papers are returned. `meta.counts` exposes
the count at each stage (`after_relevance_filter`, `after_journal_filter` for
`--quartile`/`--min-impact`, `after_rank_filter` for the `--rank-platform` tier
filter) so the filtering is fully auditable.

---

## Relevance scoring — what `relevance` means (and what it is NOT)

`agent_search` computes a **deterministic, query-grounded heuristic** for every
paper. It is explicitly **NOT** the human recipe's LLM-based RCS (Relevance &
Contribution Score) — `method` is always `"heuristic_v1"` and `is_llm_rcs` is
always `false`. No LLM is involved; nothing is fabricated; the formula is open:

```
score =  0.50 · title_coverage      # query terms found in the title (strongest precision signal)
       + 0.25 · abstract_coverage   # query terms found in the abstract (broader, noisier)
       + 0.15 · citation_signal     # log10(cites+1)/log10(2001), capped at 1 (quality prior)
       + 0.10 · recency_signal      # 25-year linear window; this year = 1, ≥25 yrs ago = 0
```

The four weights sum to 1.0, so the max score is 1.0. `components` returns each
term, so the score is fully transparent, never a black box. `label`:
`high ≥ 0.6`, `medium ≥ 0.35`, else `low`.

Key property: an off-topic paper (zero coverage) can score at most 0.25 from
citation + recency alone, so **a hugely-cited but off-topic paper never outranks a
genuinely on-topic one.** Use the score as a *signal to build on* (you may apply
your own judgement on top), but you never receive data without a score.

Term handling: lowercase → strip boolean punctuation (`+`, parentheses) → drop
stopwords (incl. academic-noise words like `study/review/effect/role`) → keep
length ≥ 3 → dedupe. Coverage is by **token-set membership** (not substring), so
`cat` does not match `category`.

**Caveat under SS-primary: the default order under-ranks abstract-less classics.**
The 0.25 abstract weight assumes records carry an abstract. On OpenAlex they almost
always do; on the **Semantic Scholar** path they often do not — the SS bulk endpoint
returns abstracts for only a minority of records (measured ≈40% on "prospect
theory"), and the gap concentrates on **highly-cited foundational works** (old
classics come back with `abstract=None`). For those papers the abstract term scores
0, the total collapses toward `title(0.50)+recency(0.10)`, and recent low-cited
papers that *do* carry an abstract can outrank the seminal ones — measured: under
SS-primary, Kahneman & Tversky 1979 (36,671 cites) fell to rank #7 (score 0.65,
`abstract_coverage:0.0`) behind 2022/2026 papers at ≈0.87. This is a known
`heuristic_v1` × SS-data-shape interaction, **not a bug**: every signal is still
present and transparent (`components` and `citation_count` are returned per paper).
So when `meta.source_used == "semantic_scholar"`, do **not** trust the default
relevance order for finding canonical work — **re-rank by `citation_count` (or fold
it into your own ranking)** before deciding what to read. (Compounding factor: these
same old classics often also lack a backfillable ISSN, so they miss the
`journal_rank` join too — see `references/journal_metrics.md`.)

---

## `--verify` — existence & consistency markers (no extra network)

`--verify` is the capability agents most need and most often get wrong (fabricated
citations). Each paper gets a `verify` block derived ENTIRELY from the already-
fetched record — **zero extra API calls, impossible to fabricate**:

| Field | Meaning |
|---|---|
| `exists` | True when the paper has a DOI or an OpenAlex/SS/PubMed/arXiv id (it came back from a real source query → exists by construction). |
| `has_doi` / `has_abstract` | Explicit booleans so you know if the metadata you want to cite is missing. |
| `multi_source` / `source_count` | Hit by ≥2 sources = stronger existence evidence. |
| `title_year_present` | Cross-source consistency proxy: flags records missing title/year (the two fields agents cite most). |
| `flags[]` | Any of `no_doi` / `no_abstract` / `no_title` / `no_year` / `single_source`. |

`meta.verify_summary` aggregates: total / with_doi / with_abstract / multi_source /
missing_title_or_year. (This verify does NOT HTTP-resolve each DOI — "came from a
real source query" is already strong existence evidence; resolving per-DOI would
add latency + a new failure surface for no contract gain.)

**`multi_source` has little discriminative power in this mode.** `agent_search`
retrieves from a *single* primary source, so a paper is almost never hit by ≥2
sources in one run — `multi_source` is `false` and `flags` carries `single_source`
for essentially every paper (measured: 5/5). Read it as an artifact of single-source
retrieval, **not** as a reliability red flag. For genuine **cross-source existence**
verification (the anti-hallucination use case), use `--verify-refs` below, which
actually queries OpenAlex → CrossRef → SS per reference.

---

## `--verify-refs FILE.json` — direct existence check (the anti-hallucination entry)

`--verify` above only annotates papers a topic search **just returned**. But the
most valuable thing an agent needs from this Skill is the *inverse*: **"I already
have a list of papers I intend to cite — tell me which ones actually EXIST so I
never cite a hallucinated reference."** `--verify-refs` is that direct entry point.
It does **not** run a topic search; you hand it the refs and it resolves each one.

```bash
PYTHONPATH=$PSP_HOME \
  python3 -m scripts.agent_search --verify-refs refs.json > rulings.json
```

**Input** (`refs.json`) — a JSON list of refs, each with a `doi` and/or `title`.
A top-level `{"references": [...]}` or `{"refs": [...]}` object is also accepted,
and a bare string item is treated as a title:

```json
[ { "doi": "10.2307/1914185", "title": "Prospect Theory" },
  { "title": "Attention Is All You Need" },
  { "doi": "10.9999/this-was-hallucinated" } ]
```

**What it does per ref** — cross-checks existence against the **free authoritative
sources** (OpenAlex → CrossRef → Semantic Scholar), at runtime over the network:

- **Has a DOI** → tries OpenAlex `get_work`, then CrossRef (`_fetch_doi`, the DOI
  registry of record), then SS single-paper lookup. The first hit confirms
  existence; a resolved DOI is the strongest proof there is.
- **Title only** → an OpenAlex title search; a candidate is accepted only when its
  significant-token set overlaps the requested title at or above the
  `title_match_threshold` (default 0.85). A weak match is reported but **not**
  accepted (anti false-positive — we err toward "not found").
- **DOI fails but the title resolves** → verified via title, with a note that the
  supplied DOI is probably wrong and `canonical.doi` is the one to use.
- **Resolves nowhere** → `exists: false`, with a note. We never invent a
  "probably real" verdict — catching fabrications is the whole point.

**Output** — `{ ok, schema_version, data: [<ruling>...], meta: {...} }` where each
ruling is:

```json
{ "ref":            { ...the input ref, echoed... },
  "exists":         true,
  "matched_source": "openalex" | "crossref" | "semantic_scholar" | null,
  "canonical":      { "title": "...", "year": 1979, "doi": "...", "venue": "..." } | null,
  "note":           "DOI resolved in OpenAlex." }
```

`meta.summary` = `{ total, verified, not_found, by_source }`;
`meta.sources_available` reports which resolvers initialised (a source whose init
fails is skipped, not fatal — DOI refs can still verify via the others).
Exit codes follow the same table as search (`E_CONFIG` for a missing/bad input
file, `E_NO_RESULTS` for an empty ref list).

> Use this before writing any citation list: feed your drafted references in, drop
> every `exists: false` ruling, and correct titles/years/DOIs from `canonical`.

---

## Source selection (config-driven)

Routing is set in `~/.paper-search-pro/config.yaml` (`primary_source`):

- `openalex` (default) — unchanged v2.0/2.1 behavior.
- `semantic_scholar` — SS as primary. **Requires `semantic_scholar_api_key`**
  (SS 429s instantly on the shared pool without a key, R-06). SS-primary records
  often lack an ISSN; `agent_search` backfills it via a free OpenAlex DOI lookup
  so the `journal_rank` join is not silently lost (`meta.enrichment.issn_backfilled`
  reports how many were recovered). Papers with no DOI stay unjoinable, and the
  gap stays visible (`meta.enrichment.issn_backfill_*`).
- `auto` — OpenAlex normally, but a run-level quota probe stickily falls back to
  SS when the OpenAlex USD budget runs low (`quota_fallback`,
  `quota_fallback_threshold_usd`). `meta.ratelimit.switched_source` reports it.

`meta.source_used` always tells you which source actually served the run.

---

## Multi-platform journal partitions (中科院 / JCR / SJR) — the A-line `rank` layer

This is **the** journal layer (v2.2 single-layer collapse): it labels every paper
with **all three** platforms (plus an `openalex` open-impact sub-slot) and, when a
tier was requested, filters on **one**. The opt-in `--quartile` / `--min-impact`
filters also read this record (`journal_rank.sjr.best_quartile` /
`journal_rank.openalex.mean_citedness_2yr`); there is no separate per-paper
`journal_metric` any more. The data is fetched at runtime from public mirrors into the user's local
cache (`~/.paper-search-pro/ranks/`) by `scripts/journal_rank.py` — **never bundled
in the repo**. First use needs a one-time `journal_rank fetch` (see
`references/journal_metrics.md`); until then this layer degrades gracefully
(`meta.rank.data_loaded: false`, slots stay `null`, the run still succeeds — it
**never** fetches inline).

**NL intent recognition (the bug fix).** Before retrieval, `agent_search` parses the
query for partition phrasing and **strips it from the topic**, so `中科院一区 情绪调节`
searches for 情绪调节 *filtered to* CAS tier 1, not for papers *about* 中科院一区.
`meta.query.search_query` shows the cleaned topic actually sent to the engine
(`== meta.query.topic` when no rank phrasing was present — R-19 default path).

**Platform resolution priority** (`meta.rank.platform_source`):
1. **`flags`** — explicit `--rank-platform`.
2. **`intent`** — NL phrasing (`中科院一区` → cas).
3. **`default`** — config `rank.default_platform` (factory `jcr`) — this only
   **LABELS**, it does **not** filter ("no partition asked → no filter").
A bare `Q1` with no platform → `meta.rank.ambiguous: true` + `candidate_platforms`;
the run does **not** filter (the recogniser never guesses a platform) — the calling
agent should ASK the user which platform (the CLI is non-interactive).

**The `meta.rank` block** reports the run's partition decision:

| Field | Meaning |
|---|---|
| `platform` / `platform_source` | The platform filtered on + how it was chosen (`flags`/`intent`/`default`/`none`). |
| `keep_tiers` / `keep_quartiles` / `top_only` / `category` | The requested filter. |
| `applied_filter` | True only when a tier filter actually ran. |
| `ambiguous` / `candidate_platforms` | Bare-quartile case: ask the user. |
| `kept` / `filtered` / `no_platform_data` | Three-way split; journals not on the platform are counted, **never silently dropped**. |
| `data_loaded` / `loaded_platforms` | Whether ranking data was cached, and which platforms. |
| `switchable_platforms` / `switch_is_refilter_not_research` | Switching standard/tier is a **re-filter of the already-annotated pool** — no re-search. |
| `stripped_phrases` | The partition phrases removed from the query (transparency). |
| `deepen` | `{active, rounds, saturated, final_per_strategy}` — adaptive-deepening state. |
| `keep_tiers_note` | Set when bare numeric `--keep-tiers` was passed with no `--rank-platform`: the digits were read as the default platform's quartiles (factory JCR `Q1,Q2…`); tells the caller to add `--rank-platform cas` for 中科院 区. `None` otherwise. |
| `attribution` / `note` / `naming` | Platform attribution, degrade note, R-04 reminder. |

**Adaptive deepening** (only when a tier filter is active, data is loaded, the query
is not ambiguous, and `source_used == openalex`): the first retrieval is annotated +
filtered; if survivors fall short of `--deepen-target`, the search re-retrieves at
greater depth and re-filters the **same** annotated pool, until the target is met,
`max_deepen_rounds` (3) is reached, or a deeper round adds no new uniques
(saturated). With a tier filter active the ranking prefers **citation** order (high
区 ↔ high cites, r≈0.96, so high tiers surface faster with less over-fetching);
without a filter the default relevance order is unchanged. The cost is only in the
retrieval segment — no extra LLM classification (headless never classifies). The SS
path has no depth knob, so SS-primary does not deepen (`meta.rank.deepen.active`
reflects this).

**Counts.** `meta.counts.after_rank_filter` is the survivor count after the
multi-platform `--rank-platform` tier filter; `after_journal_filter` is the survivor
count after the `--quartile` / `--min-impact` opt-in filters (both now sourced from
`journal_rank`). Both are present and independent.

For sources, the ISSN join, attribution, fetch, and the "never call it an Impact
Factor" rule, see `references/journal_metrics.md`.

---

For the journal partition platforms (CAS / JCR / SJR acquisition, the OpenAlex
open-impact slot, ISSN join, naming rules), see `references/journal_metrics.md`.
