# Output directory layout & file conventions

Referenced by `SKILL.md` STEP 5 onwards — every helper writes into this layout. Main agent MUST create `<search_id>/raw/`, `<search_id>/batches/`, `<search_id>/classifications/` before running.

> ## ⚠️ Output Path Convention
>
> **All `./paper-search-results/<search_id>/` paths in this skill are relative to the USER'S CURRENT WORKING DIRECTORY (PWD), NOT the skill install directory.**
>
> This means:
> - If the user invokes the skill from `/Users/alice/projects/thesis/`, outputs land in `/Users/alice/projects/thesis/paper-search-results/<id>/`
> - The skill directory (`~/.claude/skills/paper-search-pro/`) is a READ-ONLY asset bundle and must NEVER contain search outputs.
> - Never `cd ~/.claude/skills/paper-search-pro` before running helpers — that re-anchors `./` to the skill directory and pollutes the install.
> - Use `PYTHONPATH=~/.claude/skills/paper-search-pro python3 -m scripts.<helper> ...` from the user's cwd instead.
>
> See `SKILL.md` and `references/setup.md` for the `PYTHONPATH=` invocation pattern that preserves cwd.

## search_id naming rule

Format: `YYYYMMDD_HHMMSS_<slug>` where `<slug>` is the first 3 query content-words, lowercased + hyphenated, length ≤30.

| Example query | search_id |
|---|---|
| `prospect theory decision making` | `20260521_143052_prospect-theory-decision` |
| `工作记忆训练老年` | `20260521_143052_working-memory-training` (Chinese romanized) |
| `dietary interventions IBS` | `20260521_143052_dietary-interventions-ibs` |

Main agent generates this once at start, never changes mid-search.

## Full tree

```
./paper-search-results/<search_id>/
├── report.html                  # Main deliverable, opens in browser
├── report.md                    # Markdown variant for citation managers / pandoc
├── papers.csv                   # Spreadsheet export — Excel / pandas friendly
├── bibtex.bib                   # BibTeX import (Zotero / Mendeley / LaTeX)
├── ris.ris                      # RIS — EndNote / Papers / older managers
├── papers.json                  # Full structured paper list (UnifiedPaperEntity[])
├── kg_classified.json           # Internal KG: papers + RCS + flags + sources
├── kg.json                      # Pre-classification KG (federated dedup output)
├── summary.md                   # Executive summary written by main agent
├── execution_log.json           # PRISMA-S 16-item + stop reason + errors
├── curve.json                   # Discovery curve + saturation estimate + CI
├── raw/                         # Per-source raw dumps (for re-runs / forensics)
│   ├── openalex.json
│   ├── pubmed.json              # only if PubMed enabled
│   ├── arxiv.json               # only if arXiv enabled
│   └── citations.json           # appended by citation-network calls (STEP 9)
├── batches/                     # Classifier input shards (10 papers each)
│   ├── batch_001.jsonl
│   ├── batch_002.jsonl
│   └── ...
├── classifications/             # SubAgent output (one file per batch)
│   ├── batch_001_result.json
│   ├── batch_002_result.json
│   └── ...
└── report_data.json             # data_materialization output, intermediate
```

## File producers + purposes + schema

| File | Producer | Purpose | Schema (top-level) |
|---|---|---|---|
| `report.html` | `html_renderer_webartifacts.py` | Main user-facing deliverable | Shadcn React bundle (~990 KB pristine; ~1.7 MB hydrated with 250 papers) |
| `report.md` | `md_report.py` | Citation-manager / pandoc-friendly markdown | YAML frontmatter + sections + bibliography |
| `papers.csv` | `generate_exports.py` | Excel / pandas review | `doi,title,authors,year,venue,citation_count,influential,rcs,abstract,...` |
| `bibtex.bib` | `generate_exports.py` | LaTeX / Zotero / Mendeley | BibTeX `@article{` entries keyed by DOI/arxiv |
| `ris.ris` | `generate_exports.py` | EndNote / Papers | RIS tagged format |
| `papers.json` | `generate_exports.py` | Programmatic re-use | `UnifiedPaperEntity[]` |
| `kg_classified.json` | `rcs_parser.py` (STEP 6) | Post-classification KG with rcs/reasoning/flag | `{<canonical_key>: UnifiedPaperEntity}` dict |
| `kg.json` | `federated_kg_resolver.py` (STEP 5) | Deduped multi-source merge | `{<canonical_key>: UnifiedPaperEntity}` dict |
| `summary.md` | Main agent (STEP 11) | Executive summary in main agent's voice | ~300 words plain markdown |
| `execution_log.json` | `prisma_s_logger.py` (STEP 13) | PRISMA-S compliance / audit trail | `{prisma_s: {1-16 items}, discovery_curve_snapshots, agent_invocations, errors, stop_reason, search_id, user_query, tier, generated_at}` |
| `curve.json` | `discovery_curve.py` (STEP 7) | Saturation tracking | `{points, tau, saturation_estimate, ci_low, ci_high, estimated_total_relevant}` |
| `raw/openalex.json` | `openalex_helper double-sort` or `deep` (STEP 3) | OpenAlex retrieval raw | `UnifiedPaperEntity[]` |
| `raw/pubmed.json` | `pubmed_helper search-mesh` or `enrich` (STEP 4) | PubMed raw / enriched | parsed dict[] or UnifiedPaperEntity[] |
| `raw/arxiv.json` | `arxiv_helper freshness` (STEP 4) | arXiv freshness raw | `UnifiedPaperEntity[]` |
| `raw/citations.json` | `openalex_helper citation-network` (STEP 9) | Citation expansion seeds | `{references, cited_by}` per seed, appended |
| `batches/batch_NNN.jsonl` | Main agent (STEP 6) | Classifier input shard | One paper per line: `{paper_id, title, abstract, year, venue}` |
| `classifications/batch_NNN_result.json` | Inline SubAgent (STEP 6) | RCS classification output | `[{paper_id, rcs, reasoning, flag}]` |
| `report_data.json` | `data_materialization.py` (STEP 12) | Intermediate for HTML/MD renderers | `{chart_data, paper_list, metadata, prisma_log}` |

## HTML renderer

- **One renderer, always**: `webartifacts` (Shadcn React bundle). No size-driven
  fallback — earlier "jinja2 lightweight fallback" was removed because it
  produced inconsistent UX (same Skill, two visually different reports
  depending on data size). All modern browsers handle 10+ MB self-contained
  HTML cleanly; the bundle is ~990 KB pristine and ~1.7 MB hydrated for a
  typical 250-paper report.
- No per-render config flag — `html_renderer_webartifacts.py` is the only path.

## Cleanup convention

Intermediate `batches/` and `classifications/` are kept for debugging. To purge after success:

```bash
rm -rf ./paper-search-results/<id>/batches/ ./paper-search-results/<id>/classifications/
# Keep raw/ (forensics) + all top-level files (deliverables + audit).
```

Don't auto-delete — users sometimes want to re-classify with a refined rubric without re-fetching from APIs.

## File-IPC integrity

Main agent uses single-writer pattern (no concurrent writes to the same file). When parallel SubAgents classify batches, each writes its own `batch_NNN_result.json`. The merge step (`rcs_parser.py`) is sequential.

If a SubAgent crashes mid-write, the file may be partial JSON. `rcs_parser.py` has 5-layer fallback (regex parse → recover salvageable entries → mark unparseable with `flag=parse_failed_uncertain`). See `error_handling.md` §E7.
