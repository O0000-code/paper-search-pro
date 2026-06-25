# Journal metrics (SSOT — quartiles, impact, naming rules)

Single source of truth for everything paper-search-pro reports about a paper's
**journal**: SJR quartile, OpenAlex open impact, and the external metrics we
deliberately do **not** bundle. Read this before showing or filtering on any
journal-level number, in either the human path (STEP 10/11) or agent mode.

The governing rule is **R-04 (naming铁律)**: our open metrics are **never** called
"影响因子 / Impact Factor / JCR / 中科院分区 / 新锐分区". Those are proprietary or
copyright-restricted and we neither bundle nor impersonate them.

---

## What we provide vs. what we only link out to

| Metric | Status in this Skill | Why |
|---|---|---|
| **SJR quartile** (Q1–Q4) | ✅ Provided — from a user-cached SCImago CSV (CC BY-NC, attribution mandatory) | Openly licensed for non-commercial cited use; safe to compute + display. |
| **OpenAlex 2yr mean citedness** | ✅ Provided — `source.summary_stats` (CC0) | Open, free, zero-dependency. An OPEN impact figure, **NOT** a JIF (R-09). |
| **OpenAlex journal h-index** | ✅ Provided — `source.summary_stats` (CC0) | Same source, open. |
| **JCR Impact Factor / JCR quartile** | ❌ External link only | Clarivate proprietary; WoS Journals API returns 403; bundling/redistribution is prohibited (R-01). |
| **中科院分区 (CAS) / 新锐分区** | ❌ External link only | Copyright + official enforcement notice + batch-export ban (R-02). |
| **CWTS SNIP** | Reserved field (`cwts_snip`), not yet populated | journalindicators.com has no CF gate → a future optional cross-field check. |

For the external-only metrics, the report/agent gives the user the **official
query URL** so they can look it up themselves — we never inline the data:

- JCR Impact Factor / quartile → <https://jcr.clarivate.com>
- 中科院分区 (CAS journal tiers) → <https://www.fenqubiao.com>
- 新锐 / cross-check tiers → <https://www.xr-scholar.com> (or the journal's own site)

---

## SJR quartile — acquisition (R-03 / R-05)

The SJR CSV is **never committed to the repo and never redistributed** (R-03). It
lives in the user's local cache: `~/.paper-search-pro/sjr/` (`DEFAULT_CACHE_DIR`).
The Skill is cache-first — `sjr_helper.load()` reads the newest `*.csv` there; if
none exists, quartiles are simply unavailable and the run still succeeds (impact
is still attached where reachable). No CSV is never an error.

Getting the CSV into the cache, two ways:

```bash
# (a) Best-effort automated download — uses a real browser context (Playwright)
#     because a bare HTTP GET is blocked by Cloudflare ("Just a moment", 403, R-05).
PYTHONPATH=$PSP_HOME python3 -m scripts.sjr_helper download --year 2024
#     If Playwright is not installed or CF does not clear, it prints a clear
#     manual-download instruction + the official URL and exits gracefully.

# (b) Manual — download from the portal and drop the file in the cache dir:
#     https://www.scimagojr.com/journalrank.php  (Download data → CSV)
#     save to  ~/.paper-search-pro/sjr/scimagojr-2024.csv

# Inspect what's cached / look one journal up:
PYTHONPATH=$PSP_HOME python3 -m scripts.sjr_helper info
PYTHONPATH=$PSP_HOME python3 -m scripts.sjr_helper lookup 0022-3514 --category "Social Psychology"
```

The CSV is a **26-column, semicolon-separated, European-decimal** file (`145,004`
means 145.004). It is parsed by **column name**, not position, so a future yearly
snapshot that reorders columns will not silently mis-map.

### Mandatory attribution (CC BY-NC)

Any time an SJR quartile is shown, the attribution string MUST travel with it:

```
Data: SCImago Journal Rank (SCImago, https://www.scimagojr.com), CC BY-NC
```

- Agent mode: `meta.journal_metric.attribution` + per-metric `sjr_attribution`.
- Human report: a conditional methodology footnote (auto-added when any paper has
  an SJR quartile).
- A longer legal note (`SJR_LEGAL_NOTICE`, includes the explicit "SJR is NOT the
  Clarivate JCR Impact Factor" disclaimer) is available for report footers.

---

## OpenAlex open impact (CC0; R-09 — NOT a JIF)

From the journal's OpenAlex `source.summary_stats` (free, CC0, zero extra deps):

- `openalex_2yr_mean_citedness` — mean citations to the journal's last-2-years docs.
- `h_index` — the journal's OpenAlex h-index.

**R-09 is load-bearing**: `2yr_mean_citedness` ≠ the Clarivate JIF (measured
example: JPSP ≈ 2.72 here vs. a JCR JIF of ~7–8 — different corpus, different
window). Use it for **relative ranking / percentiles within your result set
only**, never as an absolute IF threshold, and never label it "Impact Factor".

OpenAlex impact is enabled on the OpenAlex path automatically. On the SS-primary
path it is enabled for any paper whose ISSN was recovered by backfill (below).

---

## ISSN join (the link key)

Quartile + impact are joined to a paper by its journal **ISSN**:

- **Normalization** — both sides strip hyphens, upper-case `X`, gate to 8 chars.
  OpenAlex emits hyphenated (`0022-3514`); SJR stores hyphen-free (`00223514`);
  they meet on the same 8-char key. A journal's print + e-ISSN both index to one
  record, so an eISSN also joins.
- **OpenAlex path** — `source.issn_l` (preferred, the linking ISSN) else the first
  of `source.issn[]`, populated onto the entity during retrieval.
- **Semantic Scholar path** — ISSN comes from `publicationVenue.issn`, present only
  ~2/3 of the time (R-08). For the rest, agent mode does a **free OpenAlex
  single-paper DOI lookup** to backfill `source.issn` so the SJR join is not
  silently lost; `meta.journal_metric.issn_backfilled` / `issn_backfill_attempted`
  report the recovery. A paper with no DOI cannot be backfilled — its metric
  carries `issn_backfill_needed: true` so the gap stays visible rather than
  vanishing.

---

## Multi-category quartiles

A journal often sits in several Scopus categories with different quartiles, e.g.
JPSP = `Social Psychology (Q1); Sociology and Political Science (Q2)`. We expose:

- `sjr_quartile` — the journal's **best** quartile across its categories (or the
  category you pinned with `--journal-category` / the `--category` lookup flag).
- `sjr_category_quartiles` — the full `{category: Qn}` map, so a consumer can see
  exactly which field earns which tier and avoid being misled by a marginal
  category inflating the headline quartile.

When a quartile filter is applied (`--quartile Q1,Q2`), it tests `sjr_quartile`
(the pinned/best value). Pin a category when you need the quartile to mean "Q1 in
*this* field", not "Q1 in its easiest field".

---

## Filtering contract (signal-as-knob)

Journal metrics follow the same rule as relevance scoring: **the metric is always
computed and attached to every paper; filtering is opt-in and only decides what is
returned.** `--quartile` and `--min-impact` are the gates; `meta.counts.after_journal_filter`
keeps the count auditable. With no filter and no cached CSV, every paper is
returned exactly as before — journal metrics are a pure additive layer (R-19).

For agent-mode flags and envelope shape, see `references/agent_mode.md`.
