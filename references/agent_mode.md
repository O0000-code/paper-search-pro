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
8. **Journal metric** — SJR quartile + OpenAlex open impact per paper (Feature A).

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
              "journal_metric": { "sjr_quartile": "Q1|Q2|Q3|Q4|null",
                                  "sjr_category_quartiles": { "<category>": "Qn" },
                                  "openalex_2yr_mean_citedness": 0.0,
                                  "h_index": 0,
                                  "sjr_attribution": "…CC BY-NC…|null",
                                  "issn_backfill_needed": false }  /* or null */,
              "verify":         { … } /* only with --verify */ },
            … ],
  "meta": {
    "query":      { "topic", "year_min", "year_max", "per_strategy", "terms": [] },
    "counts":     { "retrieved_raw", "after_dedup", "after_relevance_filter",
                    "after_journal_filter", "returned" },
    "relevance":  { "method": "heuristic_v1", "is_llm_rcs": false,
                    "min_relevance", "weights": {}, "note" },
    "journal_metric": { "enriched", "sjr_loaded", "sjr_source", "impact_source",
                        "filter_quartiles", "filter_min_impact", "category",
                        "issn_backfill_attempted", "issn_backfilled",
                        "attribution", "note" },
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
| `--quartile Q1,Q2` | csv / none | Keep only these SJR quartiles. OPT-IN filter; metric is always attached. Needs a cached SJR CSV. SJR分区, **NOT** JCR (R-04). |
| `--min-impact X` | float / none | Drop papers whose OPEN journal impact (OpenAlex 2yr mean citedness) is below `X`. **NOT** the JCR Impact Factor (R-09); relative use only. |
| `--journal-category NAME` | str / none | Pin the SJR quartile to one category (else the journal's best). Avoids a marginal category inflating to Q1. |
| `--sjr-csv PATH` | str / none | Explicit SJR CSV path (else newest in `~/.paper-search-pro/sjr/`). |
| `--no-journal-metric` | flag / off | Skip journal_metric enrichment entirely (slots stay `null`). |
| `--no-issn-backfill` | flag / off (backfill ON by default) | **SS-primary path only.** By default, SS records missing an ISSN but with a DOI get a free OpenAlex single-paper lookup to recover the ISSN so the SJR join is not silently lost. Pass this to skip those per-paper lookups on large SS result sets — papers then stay unjoinable (`journal_metric.issn_backfill_needed` stays visible). No effect on the OpenAlex path. `meta.journal_metric.issn_backfill_enabled` reports the gate. |
| `--verify-refs FILE.json` | path / none | **Anti-hallucination mode** (instead of a topic search): verify whether a list of references actually EXIST. The positional query is omitted. See the dedicated section below. |

All filters follow one contract: **signal-as-knob.** The underlying value
(relevance score, journal metric) is always computed and attached to every paper;
the flag only decides which papers are returned. `meta.counts` exposes the count
at each stage (`after_relevance_filter`, `after_journal_filter`) so the filtering
is fully auditable.

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
  so the SJR join is not silently lost (`meta.journal_metric.issn_backfilled`
  reports how many were recovered). Papers with no DOI stay unjoinable, and the
  gap stays visible (`journal_metric.issn_backfill_needed`).
- `auto` — OpenAlex normally, but a run-level quota probe stickily falls back to
  SS when the OpenAlex USD budget runs low (`quota_fallback`,
  `quota_fallback_threshold_usd`). `meta.ratelimit.switched_source` reports it.

`meta.source_used` always tells you which source actually served the run.

For journal metrics (SJR acquisition, ISSN join, naming rules, the "never call it
Impact Factor" rule), see `references/journal_metrics.md`.
