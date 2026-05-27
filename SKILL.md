---
name: paper-search-pro
description: "Find academic papers across 5 sources (OpenAlex / Semantic Scholar / CrossRef / PubMed / arXiv) with adjustable depth — Quick scan (5 min) to Audit prep (3 hr). Use when the user wants to find papers, run a literature search, gather references, or scope a research topic. Triggers on: search verbs ('find papers', 'literature search', 'papers about X'), review types ('scoping review', 'systematic review', 'SR prep', 'literature review', 'lit review', 'help me write a lit review'), Chinese ('找文献', '找论文', '论文搜索', '学术检索', '文献检索', '文献综述', '综述前期', '求文献'). Outputs Shadcn HTML report + BibTeX/RIS/CSV + PRISMA-S log. Do NOT use for: concept explanations ('what is X' / 'X 是什么'), writing requests ('help me write a paragraph' / '帮我写'), single-paper interpretation or PDF download with full bibliographic metadata (use paper-downloader-portable), or when the user already has a literature set ready (use literature-set-review)."
license: Apache-2.0
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
metadata:
  author: Bo
  version: 2.1.1
  vendored-from: futurehouse/paper-qa (Apache 2.0)
---

# paper-search-pro

Multi-source literature search with adjustable depth. Four tiers, five data sources orchestrated by you (the main agent). Python helpers handle deterministic work; LLM classification is delegated to parallel Inline SubAgents — no external API key required.

## When to use this skill

- User wants to find academic papers / 找文献 / 论文搜索
- User is preparing a literature review, systematic review (SR), scoping review, or meta-analysis
- User wants to scope research on a topic for a thesis / proposal / coursework / news story
- User asks "what research exists on X" / "find me papers about Y"
- User uploads a query that suggests literature gathering (PICO, SPIDER, MeSH, RCT, etc.)

## When NOT to use

- User wants to **read** a specific paper (use PDF reader / download tool)
- User wants to **summarize** a single known paper (use a summarizer)
- User wants to **download** PDFs given DOIs (use `paper-downloader-portable`)
- User already has a literature set and wants to write a review (use `literature-set-review` / `factor-outcome-review`)
- User wants concept explanation, not papers ("what is prospect theory" → just answer)

---

## 🔥 Execution discipline (read this BEFORE running anything)

These four rules govern every step below. Violating them is the dominant failure mode observed in real sessions — re-read them whenever you feel rushed.

### Rule A — NEVER `cd` into the Skill directory

**Reason**: `cd ~/.claude/skills/paper-search-pro` rebinds `./` to the Skill asset directory. Every `./paper-search-results/...` after that lands inside the Skill folder, not where the user is working. Re-installing the Skill overwrites history; the user can't find outputs in their own working directory.

**Correct pattern** — execute helpers from the user's working directory using `PYTHONPATH`:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.openalex_helper search "<query>" --limit 30 \
  > "$SEARCH_DIR/raw/openalex.json"
```

Where `$SEARCH_DIR` was set up earlier as an **absolute path under the user's PWD** (see STEP 0). Shell `cwd` remains the user's PWD; `./` paths resolve to where the user expects.

### Rule B — Parallelism is MANDATORY for SubAgent dispatch

When you launch classifier SubAgents (STEP 6), you **must** put up to 5 `Task` tool_use blocks **inside one assistant message**. Serial dispatch (one Task per message, waiting for each result) makes Standard tier take ~17 min instead of ~10. See STEP 6 worked example.

### Rule C — Tell the user every time you skip a step

If you deliberately skip any STEP (because tier budget is exhausted, data is empty, or user preference), state it explicitly:
- **What** you skipped (e.g. "STEP 10 L3 enrichment")
- **Why** (tier? data? user choice?)
- **What's lost** (e.g. "no influentialCitationCount, no funder/license fields")
- **How to recover** (e.g. "re-run at `--tier deep` to include this")

Never skip silently. Skipping is fine; surprising the user is not.

### Rule D — Read the cited references/ file BEFORE the step

Each STEP names a `references/<file>.md`. Read it before running the step's commands — the cheatsheets contain edge cases that are not duplicated in SKILL.md. Average must-read coverage across recent sessions was 5/17 — drive it higher.

---

## Architecture at a glance

```
You (main agent) drive the workflow per this SKILL.md.
Python helpers do deterministic work — NO LLM inside, NO external API key.

  L1 OpenAlex (primary)  → deep top-100 multi-strategy
  L2 PubMed (medical)    → MeSH enricher (mostly; Audit-tier can search independently)
  L2 arXiv (CS/preprint) → T-0~T-4 freshness sentinel
  L3 Semantic Scholar    → influentialCitationCount + abstract fallback
  L3 CrossRef            → funder / license / clinical-trial-number

  Classification         → Inline SubAgents (parallel, file-IPC, 5 per message)
  Output                 → HTML (Shadcn) + MD + BibTeX/RIS/CSV + PRISMA-S log
```

---

## The 4 tiers — pick first

| Tier | Wall-clock | Papers | When to pick |
|------|------------|--------|--------------|
| Quick | ~5-8 min | 20-60 | "查一下" / "几篇" / "before tomorrow" / fast scope |
| **Standard** (default) | ~10-17 min | 60-180 | Scope a topic / write background / general lit search |
| Deep | ~30-45 min | 180-400 | "thorough" / writing a review article / 综述写作 |
| Audit | ~2-3 hr | 400-1000+ | "systematic review" / "PRISMA" / "Cochrane" / "meta-analysis" |

📖 **BEFORE picking, read `references/tier_decision.md`.** Tell the user your choice and why. For Audit, show limitations warning + get explicit confirmation before starting.

---

## The recipe

For every literature search, follow these steps in order. Each step references a `references/` file for details. Skip files only when the step is obviously trivial for the case at hand — and announce the skip per Rule C.

### STEP 0 — Setup (PYTHONPATH + working directory)

📖 BEFORE THIS STEP, read: `references/setup.md`.

**Verify config keys** (executed from any cwd, never `cd` into the Skill dir):

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro python3 -c \
  "from scripts.config import load_config; c = load_config(); print('OK' if (c.openalex_api_key or c.openalex_email) and c.ncbi_email else 'MISSING — see references/setup.md')"
```

If "MISSING", point the user to `references/setup.md` (5 keys, all free, ~15 min total) and halt.

**Set up the working directory variable** — every subsequent step uses `$SEARCH_DIR`:

```bash
SEARCH_ID="<topic_slug>_<tier>_$(date +%Y%m%d_%H%M%S)"   # e.g. clt_education_quick_20260522_103045
SEARCH_DIR="$(pwd)/paper-search-results/$SEARCH_ID"
mkdir -p "$SEARCH_DIR/raw" "$SEARCH_DIR/batches" "$SEARCH_DIR/classifications"
echo "Outputs will land in: $SEARCH_DIR"
```

`$SEARCH_DIR` is now an **absolute path under the user's PWD**. Use `"$SEARCH_DIR/..."` (quoted, with the variable) in every helper command below — not `./paper-search-results/...`.

### STEP 1 — Plan the query (MANDATORY for all tiers)

📖 BEFORE THIS STEP, read: `references/query_planner.md`.

**Detect query language first**: if the user's query contains any CJK characters (Chinese / Japanese / Korean — Unicode ranges U+4E00–U+9FFF, U+3040–U+30FF, U+AC00–U+D7AF), set `LANG=zh`; otherwise `LANG=en`. This single boolean controls which UI language the final HTML report renders in (paper titles / abstracts / authors / venues are NEVER translated — only the report's UI chrome). Pass `--language $LANG` to STEP 12b.

```bash
# Heuristic: bash regex on the raw query.
# `一-鿿` covers U+4E00–U+9FFF (CJK Unified Ideographs, the full
# range — `一-龯` would stop at U+9FAF and miss 55 rare chars).
# `ぁ-んァ-ヶ` covers Hiragana + Katakana; `가-힣` covers Hangul.
if [[ "$USER_QUERY" =~ [一-鿿ぁ-んァ-ヶ가-힣] ]]; then
  LANG=zh
else
  LANG=en
fi
```

Apply PICO / SPIDER / PEO depending on domain:
- Medical/clinical → PICO (Population/Intervention/Comparator/Outcome)
- Qualitative → SPIDER
- Scoping → PEO (Population/Exposure/Outcome)
- Open-ended → just extract 2-4 concept blocks + 2-5 synonyms each

Even Quick tier needs a lightweight version of this step — never skip silently. Output: 1-3 search strategies (concept blocks + year range + work type filter). Write to `"$SEARCH_DIR/query_plan.json"` so PRISMA-S logger can pick it up later (STEP 13).

### STEP 2 — Detect source routing

📖 BEFORE THIS STEP, read: `references/source_routing.md`.

Decide which L2/L3 sources to enable beyond OpenAlex baseline:
- Medical signals (RCT, PRISMA, MeSH, clinical, disease names) → enable PubMed
- CS/preprint signals (preprint, arXiv, NeurIPS, transformer, "最新", 2024+) → enable arXiv
- Cross-domain (e.g. "AI in radiology") → enable both
- Pure social science / humanities → OpenAlex only

Tell the user what you decided ("I detected medical + CS signals — also searching PubMed and arXiv"). User can override with explicit instruction.

### STEP 3 — Retrieve from OpenAlex (deep)

📖 BEFORE THIS STEP, read: `references/openalex_helper_cheatsheet.md`.

Always run OpenAlex first. For Standard+ tiers, use multi-strategy deep crawl:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.openalex_helper double-sort "<query>" \
    --n 50 --year-min 2018 \
    > "$SEARCH_DIR/raw/openalex.json"
```

For Quick tier, single-strategy is fine:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.openalex_helper search "<query>" \
    --limit 30 --year-min 2018 \
    > "$SEARCH_DIR/raw/openalex.json"
```

Subcommand parameter reference (verified against argparse):
- `search` → `--limit`, `--year-min`, `--year-max`, `--type` (positional `query`)
- `double-sort` → `--n` (per-strategy), `--year-min` (positional `query`)
- `seminal` → `--year-max`, `--limit` (positional `topic`) — for classic high-cited
- `reviews` → `--limit`, `--year-min` (positional `topic`)
- `journal-list` → `--preset Cochrane|UTD24|nature_science|medical_top`, `--limit` (positional `query`)
- `citation-network` → `--refs-limit`, `--cited-by-limit` (positional `openalex_id`) — used in STEP 9

For Deep+Audit, also call topic-specific subcommands (e.g. `seminal`, `reviews`, `journal-list`). Append outputs to `$SEARCH_DIR/raw/openalex_*.json` and federate them all together in STEP 5.

### STEP 4 — Run L2 boosters (if enabled by STEP 2)

📖 BEFORE THIS STEP, read: `references/pubmed_helper_cheatsheet.md` and `references/arxiv_helper_cheatsheet.md`.

**PubMed — default mode is `enrich`, NOT `search`**:

- **Standard / Deep tier**: enrich OA-found papers with MeSH terms (mutates the openalex.json file in place):
  ```bash
  PYTHONPATH=~/.claude/skills/paper-search-pro \
    python3 -m scripts.pubmed_helper enrich \
      --input-file "$SEARCH_DIR/raw/openalex.json" \
      --output-file "$SEARCH_DIR/raw/openalex.json"
  ```
- **Audit tier with explicit MeSH query**: independent MeSH search (produces a new file to federate later):
  ```bash
  PYTHONPATH=~/.claude/skills/paper-search-pro \
    python3 -m scripts.pubmed_helper search-mesh "Diabetes Mellitus, Type 2" \
      --year-min 2020 --limit 30 --pub-type "Randomized Controlled Trial" \
      > "$SEARCH_DIR/raw/pubmed.json"
  ```
- Generic `pubmed_helper search` is a fallback when no MeSH term is known — prefer `enrich` or `search-mesh` whenever possible.

**arXiv — only if query contains freshness signals (preprint, 最新, 2024+):**

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.arxiv_helper freshness "<query>" \
    --days 4 --limit 30 \
    > "$SEARCH_DIR/raw/arxiv.json"
```

Subcommand reference:
- `arxiv_helper freshness <query> --days N --limit M [--all-cats]`
- `arxiv_helper search <query> --limit M --sort submitted|relevance|lastUpdated [--all-cats]`
- `arxiv_helper get <arxiv_id>`

### STEP 5 — Federate (dedup + merge)

📖 BEFORE THIS STEP, read: `references/source_routing.md` §"Field priority table".

Combine all retrieval results into a single deduped KG. **Default output is a dict keyed by canonical_key** — that's what `rcs_parser` expects later, so do NOT pass `--as-list`:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.federated_kg_resolver \
    --input-files "$SEARCH_DIR/raw/openalex.json" \
                  "$SEARCH_DIR/raw/pubmed.json" \
                  "$SEARCH_DIR/raw/arxiv.json" \
    --output "$SEARCH_DIR/kg.json"
```

Pass only the input files you actually produced — skip ones that were not enabled by STEP 2. This handles DOI normalization (arXiv X→x case), version stripping, E5b guard (same title+year but different DOIs are kept separate), and field-priority merge.

`--as-list` exists but is only for consumers that want a sorted list (by citation_count); do not use it in this pipeline.

### STEP 6 — Classify in parallel batches (LLM happens here — main agent + SubAgents)

📖 BEFORE THIS STEP, read: `references/classifier_subagent_prompt.md` and `references/rcs_rubric.md`.

Split the KG into batches of 10 papers each. Write to `"$SEARCH_DIR/batches/batch_NNN.jsonl"`.

🔥 **PARALLELISM IS MANDATORY** (Rule B):

You MUST dispatch up to **5 classifier SubAgents in a single assistant message** using multiple `Task` tool_use blocks. Serial dispatch (one Task per message, waiting for each result) is the single biggest performance failure observed — it inflates Standard tier from ~10 min to ~17 min.

✅ **CORRECT — in ONE assistant message:**

```
Task tool_use #1  → subagent_type="general-purpose", prompt="<classifier prompt for batch_001.jsonl>"
Task tool_use #2  → subagent_type="general-purpose", prompt="<classifier prompt for batch_002.jsonl>"
Task tool_use #3  → subagent_type="general-purpose", prompt="<classifier prompt for batch_003.jsonl>"
Task tool_use #4  → subagent_type="general-purpose", prompt="<classifier prompt for batch_004.jsonl>"
Task tool_use #5  → subagent_type="general-purpose", prompt="<classifier prompt for batch_005.jsonl>"
```

All five tool_use blocks live in the same `<assistant>` message. The harness fires them in parallel; you receive five tool_result blocks back together.

❌ **WRONG — five separate messages (this is what serial dispatch looks like):**

```
Message N:    Task tool_use #1 ─→ wait for result
Message N+1:  Task tool_use #2 ─→ wait for result   ← SERIAL, makes Standard run 70% slower
Message N+2:  Task tool_use #3 ─→ wait for result
...
```

If you have more than 5 batches, send 5-at-a-time across multiple messages — each message still contains 5 parallel Task blocks.

Each SubAgent reads its batch file, applies the RCS rubric, and writes `"$SEARCH_DIR/classifications/batch_NNN_result.json"`. Then merge classifications into the KG:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.rcs_parser \
    --input-dir "$SEARCH_DIR/classifications/" \
    --kg "$SEARCH_DIR/kg.json" \
    --output "$SEARCH_DIR/kg_classified.json"
```

### STEP 7 — Compute saturation curve (MANDATORY for all tiers)

📖 BEFORE THIS STEP, read: `references/stop_decision.md`.

This step is NOT optional, even for Quick. The curve.json drives both STEP 8 stop decision and STEP 12 HTML chart rendering. If you skip it, the report shows an empty curve and PRISMA-S transparency suffers.

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.discovery_curve \
    --kg "$SEARCH_DIR/kg_classified.json" \
    --output "$SEARCH_DIR/curve.json"
```

The curve has `saturation_estimate` (0-1) + `ci_low` + `ci_high`. Optional `--prior-snapshots` lets you chain curves across iterations; `--papers-evaluated` overrides the auto-count.

### STEP 8 — Decide next action (MANDATORY)

📖 BEFORE THIS STEP, read: `references/stop_decision.md`.

This step is NOT optional. Make the decision **explicitly** — based on curve.json + tier budget + intent — and state the reasoning to the user. Do not skip based on intuition.

Decision tree:
- saturation < 0.6 AND budget remaining AND tier in {standard, deep, audit} → expand citations (STEP 9)
- saturation > 0.85 OR budget exhausted → stop, write report (STEP 10+)
- ambiguous → tell user the numbers and ask

### STEP 9 — Expand citations (if applicable)

📖 BEFORE THIS STEP, read: `references/citation_chasing.md`.

For top-rcs papers (rcs >= 7), get the citation network:

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.openalex_helper citation-network <openalex_id> \
    --refs-limit 25 --cited-by-limit 25 \
    >> "$SEARCH_DIR/raw/citations.json"
```

Then loop back to STEP 5 (federate the new papers into the KG, then re-classify only the new entries in STEP 6).

### STEP 10 — Enrich top-N papers (L3, optional but recommended)

📖 BEFORE THIS STEP, read: `references/ss_helper_cheatsheet.md` and `references/crossref_helper_cheatsheet.md`.

For papers with rcs >= 6, enrich with SS (influentialCitationCount + abstract fallback + tldr) and CrossRef (funder/license/clinical-trial-number). Both helpers consume a JSON **list** — the KG is currently dict-shaped. Convert first, enrich, then federate back; or supply a paper_list.json produced by data_materialization in STEP 12.

For Quick tier, skipping STEP 10 is acceptable — but **announce the skip** per Rule C ("Skipped L3 enrichment → no influentialCitationCount or funder fields; re-run at `--tier standard` to include this").

```bash
# Semantic Scholar — adds influentialCitationCount + abstract fallback + tldr
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.ss_helper \
    --input-file "$SEARCH_DIR/paper_list.json" \
    --mode enrich \
    --output-file "$SEARCH_DIR/paper_list.json"

# CrossRef — adds funder + license + refs + clinical_trial_number in one fetch
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.crossref_helper \
    --input-file "$SEARCH_DIR/paper_list.json" \
    --mode all \
    --output-file "$SEARCH_DIR/paper_list.json"
```

This adds ~135-170s for 100 papers — only do it on top-N, not the full set.

### STEP 11 — Write the executive summary

📖 BEFORE THIS STEP, read: `references/summary_writer.md`.

Write a ~300-word executive summary in your own words based on the classified papers:
- The field's main consensus
- Key methods / theoretical frameworks
- Notable disagreements or open questions
- Top 3-5 most influential papers (by `influential_citation_count` when available)

Save to `"$SEARCH_DIR/summary.md"`.

### STEP 12 — Render the report

📖 BEFORE THIS STEP, read: `references/output_files.md`.

```bash
# 12a. Materialize data for the renderer (also writes sibling chart_data / paper_list / metadata / prisma_log)
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.data_materialization \
    --kg "$SEARCH_DIR/kg_classified.json" \
    --summary "$SEARCH_DIR/summary.md" \
    --query "<original query>" \
    --tier "<quick|standard|deep|audit>" \
    --search-id "$SEARCH_ID" \
    --snapshots "$SEARCH_DIR/curve.json" \
    --output "$SEARCH_DIR/report_data.json"

# 12b. Render HTML (Shadcn webartifacts — only renderer; no size cap)
#      --language $LANG selects EN vs ZH UI; the bundle ships with both
#      dictionaries inlined, $LANG just picks which one mounts. Resolution
#      order inside the renderer is: explicit --language > metadata.language > en.
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.html_renderer_webartifacts \
    --data "$SEARCH_DIR/report_data.json" \
    --output "$SEARCH_DIR/report.html" \
    --query "<original query>" \
    --language "$LANG"

# 12c. MD report (uses materialized-dir for speed)
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.md_report \
    --materialized-dir "$SEARCH_DIR" \
    --query "<original query>" \
    --tier "<quick|standard|deep|audit>" \
    --output "$SEARCH_DIR/report.md"

# 12d. Exports (BibTeX / RIS / CSV / papers.json — only rcs >= 5 by default)
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.generate_exports \
    --kg "$SEARCH_DIR/kg_classified.json" \
    --output-dir "$SEARCH_DIR/" \
    --min-rcs 5
```

`data_materialization` accepts `--wall-clock-seconds` if you tracked elapsed time yourself; otherwise the helper computes it from session timestamps when available.

### STEP 13 — Write PRISMA-S log

📖 BEFORE THIS STEP, read: `references/prisma_s_checklist.md`.

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro \
  python3 -m scripts.prisma_s_logger \
    --search-id "$SEARCH_ID" \
    --kg "$SEARCH_DIR/kg_classified.json" \
    --user-query "<original query>" \
    --tier "<quick|standard|deep|audit>" \
    --query-plan "$SEARCH_DIR/query_plan.json" \
    --snapshots "$SEARCH_DIR/curve.json" \
    --output "$SEARCH_DIR/execution_log.json"
```

This captures the 16 PRISMA-S items for transparency / audit.

### STEP 14 — Open the report + report to user

**First**, auto-open the HTML report in the user's default browser (do NOT wait for the user to ask). Platform-aware Bash:

```bash
# macOS — most common dev setup
open "$SEARCH_DIR/report.html"
# Linux fallback — xdg-open "$SEARCH_DIR/report.html"
# Windows fallback — start "" "$SEARCH_DIR/report.html"
```

Use `open` on macOS by default. If it fails (rare — only bare Linux containers), fall through to `xdg-open` then `start`. **Do NOT skip this step** — the user just waited 5-30 minutes for the report; they should see it the moment it's ready.

**Then** tell the user:
- "Opened report in your default browser." (1 line confirmation)
- Where the report is on disk (absolute path: `$SEARCH_DIR/report.html`) — so the user can find it later
- Top findings (3-5 sentences from your executive summary)
- Any caveats — including any steps you skipped per Rule C (e.g. "PubMed wasn't queried because no medical signals were detected", "Skipped STEP 10 L3 enrichment because Quick tier; re-run at standard to include funder/license fields")

Done.

---

## Output convention

📖 See `references/output_files.md` for the full directory layout. All paths below are **relative to the user's working directory (PWD)** — never the Skill asset directory.

```
$(pwd)/paper-search-results/<search_id>/
├── report.html              # Main deliverable (Shadcn style)
├── report.md                # Markdown copy
├── papers.csv               # Spreadsheet export
├── papers.bib               # Citation manager import (BibTeX)
├── papers.ris               # Alternative citation format
├── papers.json              # Full structured data
├── kg_classified.json       # Internal KG with RCS scores
├── summary.md               # Your executive summary
├── execution_log.json       # PRISMA-S 16-item log
├── report_data.json         # Renderer bundle
├── chart_data.json          # Sibling: chart series
├── paper_list.json          # Sibling: per-paper list
├── metadata.json            # Sibling: run metadata
├── prisma_log.json          # Sibling: PRISMA log JSON view
├── curve.json               # Saturation snapshot
├── query_plan.json          # STEP 1 output
├── raw/                     # Raw per-source dumps (openalex.json, pubmed.json, arxiv.json, citations.json)
├── batches/                 # batch_NNN.jsonl files
└── classifications/         # batch_NNN_result.json files
```

---

## Error handling

📖 See `references/error_handling.md`. Common cases:

| Error | What to do |
|-------|-----------|
| Config missing keys | Direct user to `references/setup.md`, halt |
| Rate limit (SS 429 / NCBI 429) | Helper auto-retries; if persistent, drop that enricher |
| OpenAlex 404 on DOI | Use title search fallback (helper handles) |
| L2 booster returns 0 papers | Skip silently, note in PRISMA-S log via STEP 13 |
| SubAgent classifier returns invalid JSON | `rcs_parser.py` has 5-layer fallback (regex parse) |
| HTML output size | No size cap or fallback — `html_renderer_webartifacts` always produces the full Shadcn bundle. Typical 250-paper report is ~1.7 MB; pathological 1000+ paper Audit may reach 5-10 MB. All modern browsers handle 10+ MB HTML cleanly. |

---

## References (load on demand — Rule D)

| File | When to read |
|------|---------|
| `setup.md` | STEP 0 — config + 5-key acquisition |
| `tier_decision.md` | Tier picking (before STEP 0) |
| `source_routing.md` | STEP 2 + STEP 5 field-priority |
| `query_planner.md` | STEP 1 — PICO / SPIDER / PEO frameworks |
| `openalex_helper_cheatsheet.md` | STEP 3 + STEP 9 |
| `pubmed_helper_cheatsheet.md` | STEP 4 (mandatory if PubMed enabled) |
| `arxiv_helper_cheatsheet.md` | STEP 4 (mandatory if arXiv enabled) |
| `classifier_subagent_prompt.md` | STEP 6 — SubAgent prompt template |
| `rcs_rubric.md` | STEP 6 — RCS 0-10 classification rubric |
| `stop_decision.md` | STEP 7 + STEP 8 |
| `citation_chasing.md` | STEP 9 — 1-hop / 2-hop expansion |
| `ss_helper_cheatsheet.md` | STEP 10 |
| `crossref_helper_cheatsheet.md` | STEP 10 |
| `summary_writer.md` | STEP 11 |
| `output_files.md` | STEP 12 — output directory layout (PWD-relative) |
| `prisma_s_checklist.md` | STEP 13 |
| `error_handling.md` | Anytime an unexpected error surfaces |

---

## Examples

### Example 1: Quick scan (5-8 min)

User: "find 5-6 high-impact papers on prospect theory in decision making, classics + a couple recent ones"

You: Pick Quick tier (signals: "5-6", "high-impact", short query). Run STEP 0-2 lightweight. In STEP 3 use `openalex_helper seminal` for classics + `openalex_helper search` for recent (year >= 2020). No L2 boosters in STEP 4 (pure social science). In STEP 6 classify 20-30 papers via 2 parallel SubAgents in one message. STEP 7 + 8 still run (curve renders in the report). Announce skip of STEP 9 + STEP 10 per Rule C. Render report.

### Example 2: Standard ZH (10-17 min)

User: "用 paper-search-pro 帮我找一些关于工作记忆训练干预的文献 老板让我看 我对这块完全不懂 要给老年人群体的最好 谢谢🙏"

You: Pick Standard tier (default; signals: "找一些", "老板让我看"). Detect medical signal ("干预" + "老年") in STEP 2 → enable PubMed enricher. Query plan: PICO (P=elderly, I=working memory training, O=cognitive outcomes). OpenAlex `double-sort` top-100 in STEP 3. PubMed `enrich` of openalex.json in STEP 4. Federate in STEP 5 (dict output). Classify 60-180 papers via 4 batches × 5 SubAgents — **all 5 Tasks in one message** (Rule B). STEP 7 curve, STEP 8 expand if saturation < 0.6. Render report.

### Example 3: Deep × Lit review writing (30-45 min)

User: "I'm writing a proper literature review article on attachment and human-robot interaction in elderly care contexts. Need real depth..."

You: Pick Deep tier ("proper literature review article" + "real depth"). Cross-domain (psychology + CS) in STEP 2 → enable arXiv freshness sentinel. SPIDER plan in STEP 1. OpenAlex `double-sort` top-200 + `reviews` subcommand in STEP 3. Classify 200+ papers via 8 batches in STEP 6 — dispatch 5 parallel Tasks per message, two waves. STEP 9 expand citations 2 hops. STEP 10 enrich top-50 with SS + CrossRef. Render report with PRISMA-S log.

### Example 4: Audit × SR-prep (2-3 hr)

User: "Need help — preparing a systematic review on dietary interventions for IBS in adults. Inclusion criteria: RCTs, adult populations (≥18), low-FODMAP or fiber-based interventions, English-language, published 2010-present."

You: Pick Audit tier ("systematic review" + PICO + IC). **Show limitations warning first** ("This is not a PRISMA replacement — it's SR-prep assist. Cochrane Library + Embase still needed for full SR rigor."). Get user confirmation. STEP 4 use `pubmed_helper search-mesh "Irritable Bowel Syndrome" --pub-type "Randomized Controlled Trial"` for independent MeSH search. STEP 3 also call `openalex_helper journal-list --preset Cochrane`. STEP 10 add CrossRef enrichment for funder + clinical-trial-number. Render with PRISMA flow chart in STEP 12.
