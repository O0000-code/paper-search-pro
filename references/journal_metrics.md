# Journal partitions & metrics (SSOT — platforms, fetch, ISSN join, naming)

Single source of truth for everything paper-search-pro reports about a paper's
**journal**: the multi-platform partitions (中科院 CAS / JCR / SJR) plus the OpenAlex
open-impact slot — all in one unified `journal_rank` record (v2.2 single-layer
collapse) — the ISSN join, attribution, and the naming rules. Read this before
showing or filtering on any journal-level number, in either the human path
(STEP 1 + STEP 10/11) or agent mode.

> **What changed in v2.2 (A-line).** The previous version of this file said JCR
> and 中科院分区 were "external-link only" and that SJR needed a Cloudflare-busting
> browser download. That is **out of date.** All three platforms are now pulled at
> runtime from public GitHub mirrors with plain `requests` (no Cloudflare, no new
> dependency) by `scripts/journal_rank.py`, joined by ISSN, and surfaced as
> partitions on every paper. The "external link only" posture is gone for these
> three; we still **never bundle or commit any ranking data** — it is fetched into
> the user's local cache and used there.

The governing rule is **R-04 (naming 铁律)**: a partition is a partition, an
Impact Factor is an Impact Factor, and they are not interchangeable words.
**Only the JCR `IF(2024)` is a real Impact Factor.** 中科院"区" and SJR quartile are
**分区 / quartile**. OpenAlex 2-year mean citedness is an **open journal-impact**
figure ("期刊影响力"), explicitly **NOT** a JIF (R-09).

---

## The three partition platforms (the A-line multi-platform layer)

| Platform | What it gives | Native taxonomy | Real IF? |
|---|---|---|---|
| **中科院 CAS** (中科院文献情报中心) | 大类分区 (区 1-4) + within-大类 rank + Top flag + up to six 小类 partitions | 区 1-4 (1 = best) | No — 区 is a PARTITION |
| **JCR** (Clarivate) | Quartile Q1-Q4 + **IF(2024)** + category rank | Q1-Q4 | **Yes** — `impact_factor` is the genuine JIF |
| **SJR** (SCImago) | SJR Best Quartile Q1-Q4 + SJR indicator value + per-category quartiles | Q1-Q4 | No — quartile/value is a PARTITION |

Every annotated paper carries **all three** (each slot independently optional — a
journal found on only one platform still yields a valid record). Filtering, when a
tier is requested, applies to **one** platform; the other two stay as labels.

### Data sources (GitHub raw mirrors — `requests`, no Cloudflare, zero new deps)

The mirror URLs live in config (`rank.sources`) so a user can swap them. All three
were curl-verified HTTP 200 on 2026-06-25.

| Platform | Default mirror file | Format | ISSN format |
|---|---|---|---|
| CAS | `FQBJCR2025-UTF8.csv` (hitfyd/ShowJCR) | comma CSV, UTF-8, 23 cols | `2053-1583/2053-1583` (slash, hyphenated) |
| JCR | `JCR2024-UTF8.csv` (hitfyd/ShowJCR) | comma CSV, UTF-8, 7 cols | ISSN + eISSN cols, hyphenated (either may be `N/A`) |
| SJR | `scimagojr 2024.csv` (zotero-sjr-ranker) | **semicolon** CSV, **European decimals**, 27 cols | `"15424863, 00079235"` (comma, **no hyphen**) |

- **Columns are resolved by name (fuzzy), never by index** — the live headers
  drift from any spec sketch (CAS uses full-width `OA Journal Index（OAJ）`; the live
  SJR 2024 file added an `SDG` column → 27 cols). By-name parsing is what keeps the
  join robust across yearly snapshots.
- CAS 大类分区 reads `3 [168/495]` → tier=3, rank="168/495"; `Top` is `是/否`; up to
  six 小类 partitions (most rows use one or two). **Default partition = 大类**; 小类
  is available for a finer pin.
- JCR `IF(2024)` is a plain US float (`232.4`); `Category` may carry several
  `;`-joined entries. **This is the only real Impact Factor in the whole system.**
- SJR `SJR` value uses a comma decimal (`145,004` = 145.004); `Categories` is
  `"Hematology (Q1); Oncology (Q1)"`.
- 2026+ CAS stops updating; an optional `XR2026-UTF8.csv` (民间 新锐 接棒) can be
  pointed to via config — but it **must be labelled non-official** if used.

### Fetch (init-once; runtime; never committed)

Data is pulled **at runtime** into `~/.paper-search-pro/ranks/` (`rank.cache_dir`)
and **never enters the repo / git history** (R-02 / R-03). First use needs a
one-time fetch; thereafter it is cache-first and only re-pulls when explicitly
forced or the cache is stale (>365 days).

```bash
# One-time (or after a year). All three platforms:
PYTHONPATH=$PSP_HOME python3 -m scripts.journal_rank fetch
# A single platform: --platform cas | jcr | sjr ; force re-pull: --force
PYTHONPATH=$PSP_HOME python3 -m scripts.journal_rank fetch --platform cas

# Inspect what's cached / look one journal up:
PYTHONPATH=$PSP_HOME python3 -m scripts.journal_rank info
PYTHONPATH=$PSP_HOME python3 -m scripts.journal_rank lookup 0028-0836
```

A failed network / 404 degrades gracefully (that platform is absent; the others
still load; the run never crashes). When nothing is cached, `journal_rank.load()`
returns `None` and the whole partition layer silently no-ops — the report is
byte-for-byte unchanged (R-19), exactly as if the feature were off.

### Annotate + filter (the logic layer)

```python
from scripts import journal_rank, rank_filter
lk = journal_rank.load()                    # RankLookup | None (None → graceful degrade)
rank_filter.annotate_papers(papers, lk)     # stamps paper.journal_rank (三家全标), once
kept, dropped, nodata = rank_filter.filter_by_rank(
        papers, platform, tiers=[1], quartiles=["Q1"], top=False)
```

- **annotate is platform-blind** — it labels all three platforms in one pass. Do it
  once per result set.
- **filter is a re-filter of the annotated pool** — switching platform/tier is just
  calling `filter_by_rank` again on the same candidates (**no re-search**; the
  "切换 = 重筛不重搜" contract, see Flow below).
- **`no_platform_data` is reported, never silently dropped** — journals not on the
  chosen platform are partitioned out and counted so the gap stays visible.

---

## Default / ask / filter / report / switch flow (spec §7)

This is the human-path interaction contract (agent mode surfaces the same facts in
`meta.rank` instead of asking):

- **Factory default standard = JCR** (`rank.default_platform`, user-settable to
  `cas`/`sjr`). The default platform only **LABELS**; it never filters on its own.
- **No partition mentioned → do not filter.** Show all three labels; let the user
  refine.
- **A tier was requested → filter this once.** From STEP 1 intent
  (`parse_rank_intent`) or the user this round. The per-request tier filter is
  **transient — never auto-persisted** to config.
- **Ambiguous bare "Q1" (no platform, no persistent default) → ask one short
  question**: *"按 JCR 还是 SJR?顺带设默认吗?"* The recogniser never guesses a
  platform for a bare quartile.
- **Always report what the run did**: *"本次按 {platform} 筛(留 N / 滤 M)"* + a light
  offer to switch standard/tier or set a persistent default. Attach the platform's
  attribution string.
- **Switching standard/tier = RE-FILTER the annotated pool, NOT a re-search.** Only
  when too few survivors remain do you go back to STEP 3 and deepen.
- **Persist the default only on an explicit "以后都用 X"** → set
  `rank.default_platform` in `~/.paper-search-pro/config.yaml`. Tier档位 is never
  persisted, only the platform default.

For the headless flags that mirror this (`--rank-platform`, `--keep-tiers`,
`--rank-category`, `--deepen-target`, the `meta.rank` block, adaptive deepening),
see `references/agent_mode.md`.

---

## Attribution (per-platform, exact — corrects the old SJR mislabel)

Whenever a partition is shown, the matching attribution MUST travel with it. The
canonical strings live in `journal_rank.ATTRIBUTION` so callers cannot drift; the
display layer attaches them automatically (`journal_rank_attribution` in the MD
report, `meta.rank.attribution` in agent mode).

| Platform | Attribution / licence reality |
|---|---|
| **CAS** | 中科院文献情报中心期刊分区表. For personal / non-commercial use; **勿公开传播**. |
| **JCR** | Journal Citation Reports (Clarivate). IF / quartile **© Clarivate**; for reference only. |
| **SJR** | SCImago Journal Rank, scimagojr.com — **non-commercial use as long as it is cited (SCImago custom terms; NOT a Creative Commons / "CC BY-NC" licence)**. |

> **The "CC BY-NC" label was wrong.** The previous file and the legacy `sjr_helper`
> called SJR "CC BY-NC". SCImago's site carries no Creative Commons text; the actual
> term is a custom "non-commercial use as long as cited" condition (legal review
> §2.4). This file and `journal_rank.ATTRIBUTION` carry the corrected wording.

A longer footer note is available as `journal_rank.LEGAL_NOTICE` (emphasises the
runtime-fetch / no-redistribution posture and the "only JCR IF is a real IF" rule).
Official portals for "verify at source" external links live in
`journal_rank.PORTAL_URL` (CAS → fenqubiao.com, JCR → jcr.clarivate.com,
SJR → scimagojr.com).

### Compliance posture: we do not distribute data; we fetch it at runtime

The ranking CSVs are **never committed to the repo and never redistributed**. They
are pulled at runtime from public mirrors into the user's own local cache and used
there. This is the "user-side fetch + runtime join + external link" posture the
legal review settled on. The residual grey-area risk is a user's informed choice;
the tool itself ships only **code + source URLs**, never data.

---

## ISSN join (the link key)

Partitions are joined to a paper by its journal **ISSN**:

- **Normalisation** — every platform's ISSN is normalised onto one
  `XXXX-XXXX` upper-case key (8 digits, `X` upper-cased). JCR/CAS arrive hyphenated;
  SJR arrives hyphen-free; they meet on the same canonical key. A journal's print +
  electronic ISSN both index to one record, so an eISSN also joins.
- **OpenAlex path** — `source.issn_l` (preferred) else the first of `source.issn[]`.
- **Semantic Scholar path** — ISSN from `publicationVenue.issn`, present only ~2/3 of
  the time (R-08). Agent mode **best-effort** backfills the missing ones via a free
  OpenAlex single-paper DOI lookup so the join is not silently lost (measured: 16 of
  21 recovered on one SS run); the human path reuses the same backfilled ISSN before
  annotating. Backfill is **not guaranteed**: a record with no DOI — or whose
  OpenAlex DOI record itself carries no ISSN, as happens with some old classics (e.g.
  Kahneman & Tversky 1979) — stays unjoinable. The residual gap stays visible via
  the `meta.enrichment.issn_backfill_*` audit (agent mode).

---

## The OpenAlex open journal-impact slot (`journal_rank.openalex`)

Alongside the three partition platforms, the unified `journal_rank` record carries
an `openalex` open-impact slot drawn from OpenAlex `summary_stats` (CC0). In v2.2
this **replaced** the old single-platform SJR-only `journal_metric`: the SJR quartile
now lives in `journal_rank.sjr.best_quartile`, and the open-impact figures live in
`journal_rank.openalex`. There is **no separate per-paper `journal_metric` key** in
the agent envelope any more, and the human display renders the unified record.

| Figure | Where it lives now | Notes |
|---|---|---|
| **SJR quartile** (Q1–Q4) | `journal_rank.sjr.best_quartile` | From the SJR mirror CSV; attribution mandatory. |
| **OpenAlex 2yr mean citedness** | `journal_rank.openalex.mean_citedness_2yr` | CC0. An OPEN impact figure, **NOT** a JIF (R-09). |
| **OpenAlex journal h-index** | `journal_rank.openalex.h_index` | Same source, open. |

R-09 is load-bearing: `mean_citedness_2yr` ≠ the Clarivate JIF (measured: JPSP ≈
2.72 here vs a JCR JIF of ~7–8 — different corpus, different window). Use it for
relative ranking within your result set, never as an absolute IF threshold, and
never label it "Impact Factor".

The agent `--quartile` / `--min-impact` flags filter on this unified record
(`journal_rank.sjr.best_quartile` and `journal_rank.openalex.mean_citedness_2yr`
respectively) — they no longer read the retired SJR-only path. (The legacy
`sjr_helper` module and a dormant MD-display block survive in the tree only for
backward-compat with old cached `kg.json` files; nothing in the live envelope or
the filters depends on them.)

**Filtering contract (signal-as-knob):** the partition / impact is always computed
and attached to every paper; filtering is opt-in and only decides what is
**returned / kept**. With no filter and no cached data, every paper is returned
exactly as before — journal data is a pure additive layer (R-19).
`meta.counts.after_journal_filter` (survivors after `--quartile` / `--min-impact`)
and `meta.counts.after_rank_filter` (survivors after the `--rank-platform` tier
filter) keep the counts auditable.

For agent-mode flags and the full envelope shape, see `references/agent_mode.md`.
