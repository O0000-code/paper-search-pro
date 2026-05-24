# Error handling manual

Referenced by `SKILL.md` STEP 3, 4, 5, 6, 10, 12 — wherever an external call or LLM-out can fail. Numbered for direct quoting in user messages ("E3 SS rate limit — backing off 60s").

## Error catalog

### E1 — Config missing required keys

| | |
|---|---|
| **Symptom** | `RuntimeError: Call pubmed_helper.init(config) first` OR `openalex_email or openalex_api_key` empty OR setup check from SKILL.md prints `MISSING — see references/setup.md` |
| **Trigger** | First run; user skipped `setup.md` |
| **Action** | Halt. Don't try to run anything. Tell user: `Setup is required: please see references/setup.md (5 keys, all free, ~15 min total). I've stopped here so we don't waste effort.` |

### E2 — OpenAlex rate limit / 429

| | |
|---|---|
| **Symptom** | `pyalex` raises `HTTPError 429` OR returns empty list with stderr `rate exceeded` |
| **Trigger** | Burst >10 req/s without polite-pool credentials; or polite pool 429 (rare) |
| **Action** | Helper retries 3× via SDK. If persistent, halt the current strategy. `double-sort` makes 3 strategies × 5 pages = 15 calls — break between strategies if 429. Tell user: `OpenAlex is rate limiting. Waiting 60 s before retry — please ensure openalex_email or openalex_api_key is set in config.` |

### E3 — Semantic Scholar 429 / rate limit

| | |
|---|---|
| **Symptom** | `semanticscholar.SemanticScholarException` containing "429" OR slow timeouts |
| **Trigger** | >1 RPS sustained. NO PAID TIER exists; API key gives auth-shape only, not throughput. |
| **Action** | Helper's per-paper fallback uses `time.sleep(1.1)`. If batch `get_papers` fails, switch to per-paper loop automatically — no user action. If 429s persist across both, drop SS enrichment for this run and proceed without `influential_citation_count`. Tell user: `SS is rate limiting persistently. Skipping influential-citation enrichment; the report will use citation_count only. You can re-run enrichment later via: python3 -m scripts.ss_helper --input-file kg_classified.json --mode enrich.` |

### E4 — NCBI 429 / PubMed rate limit

| | |
|---|---|
| **Symptom** | Biopython `HTTPError 429` OR empty efetch when records expected |
| **Trigger** | Wrong / expired `ncbi_api_key`; or >10/s (with key) / >3/s (anonymous) |
| **Action** | First, verify key is valid: `curl 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=cancer&api_key=YOUR_KEY'`. If invalid: re-issue at https://account.ncbi.nlm.nih.gov/settings/. If valid: helper's `_RATE_LIMIT_SLEEP=0.2` should hold; persistent 429 suggests another process is sharing the key — back off 60s. |

### E5 — arXiv 429

| | |
|---|---|
| **Symptom** | SDK retries 3×, then raises `arxiv.UnexpectedEmptyPageError` or HTTP 429 |
| **Trigger** | Calling arxiv helper from multiple processes; or a previous run left the IP banned (24h cool-down possible) |
| **Action** | Helper uses `delay_seconds=4` (1 s buffer above ToU's 3 s minimum) — never override below this. Don't parallelize arXiv calls at user level. If banned: wait 1 hour, then resume. Drop arxiv freshness for this run; OpenAlex covers ≥T-5 already. |

### E6 — CrossRef 404 with text/plain "Resource not found."

| | |
|---|---|
| **Symptom** | `requests.get` returns 404 with `Content-Type: text/plain` body "Resource not found." |
| **Trigger** | DOI not in CrossRef (typical for arXiv DOIs, some pre-2000 papers, takedowns) |
| **Action** | Already handled — `_fetch_doi()` checks `application/json` content type before `.json()`. Plain-text 404 → returns None silently. Paper just doesn't get crossref enrichment. No user action needed. |

### E7 — SubAgent classifier returns invalid JSON

| | |
|---|---|
| **Symptom** | `batch_NNN_result.json` is malformed JSON OR a single object instead of array OR has stray prose |
| **Trigger** | LLM emitted extra commentary, markdown fences, or repeated the schema instead of filling it |
| **Action** | `rcs_parser.py` has 5-layer fallback: (1) strict `json.loads`; (2) strip ```` ``` markdown ```` fences then retry; (3) regex-extract `[{...}, ...]` substring; (4) per-object regex extraction yielding partial records with `flag=parse_failed_uncertain` and `rcs=0`; (5) skip the batch entirely if even per-object parse fails. Main agent does NOT need to re-run the batch unless ≥50% of papers in batch hit level 5 — if so, fix the SubAgent prompt template and re-dispatch. |

### E8 — (removed 2026-05-23) HTML size fallback eliminated

The Skill no longer has a "fallback to a leaner jinja2 renderer when HTML
exceeds N MB" path. Rationale: it produced inconsistent UX (same Skill,
different visual report depending on data size) and modern browsers handle
10+ MB self-contained HTML files cleanly. The webartifacts renderer is the
only path and always ships the full Shadcn bundle. If a pathological run
produces a 20+ MB file, log it for follow-up but ship as-is.

### E9 — Zero papers found

| | |
|---|---|
| **Symptom** | `kg.json` is `{}` after STEP 5 — federation produced no entries |
| **Trigger** | Query too narrow / mis-translated; or all sources 429'd |
| **Action** | DO NOT generate an empty report. Tell user explicitly: `No papers matched the query "X" across the data sources. Possible causes: (1) query too narrow — try removing year filter or adding synonyms; (2) wrong domain detection — was PubMed/arXiv unnecessarily enabled? (3) rate-limit collapse — re-run in 5 min. I haven't generated a report.` Suggest 2-3 concrete query rewrites based on `references/query_planner.md` concept-block analysis. |

### E10 — User interrupt (KeyboardInterrupt mid-classification)

| | |
|---|---|
| **Symptom** | SIGINT during a parallel SubAgent batch |
| **Trigger** | User pressed Ctrl-C |
| **Action** | The currently-running batches complete (cannot abort SubAgents). Already-classified `classifications/batch_NNN_result.json` files are kept; partial `kg_classified.json` may be missing the last few batches. Tell user: `Stopped at batch N of M. Partial KG saved at kg_classified.json — re-run rcs_parser.py to merge what's there, or re-run from batch N to continue.` |

### E11 — Pre-2000 paper missing references (acceptable)

| | |
|---|---|
| **Symptom** | `K&T 1979` returns `referenced_works_count=0` from OpenAlex; SS also returns `references=[]` |
| **Trigger** | Upstream metadata gap — OpenAlex / SS do not have full reference lists for pre-2000 high-impact papers |
| **Action** | Accept as data limitation. Don't try CrossRef as last resort — it has the same gap for old papers. Mark `flag=null` (this is not a parse error, it's missing upstream data). Mention in PRISMA-S item 14 note. |

### E12 — arXiv DOI case normalization

| | |
|---|---|
| **Symptom** | `10.48550/arXiv.1706.03762` from OA appears as duplicate of `10.48550/arxiv.1706.03762` from SS after federation |
| **Trigger** | Case-insensitive DOI matching not applied |
| **Action** | Already handled — `federated_kg_resolver.normalize_doi()` lowercases everything before keying. If you're seeing duplicates, check that all helpers were invoked through the federation step, not directly via Python. |

### E13 — SS DOI not found / takedown

| | |
|---|---|
| **Symptom** | `sch.get_paper(sid)` returns None OR `abstract` is empty string OR ` paperId` is None for a known-valid DOI |
| **Trigger** | Publisher takedown request (some Elsevier / Springer papers post-2020); or DOI not indexed by SS yet (very recent papers) |
| **Action** | Gracefully skip — paper keeps OA-only fields. No `influential_citation_count`. Marked `sources=["openalex"]` only. No user-facing error. |

## Triage flowchart for the main agent

When a helper command produces unexpected output:

1. **Check stderr first** — most failures emit stack trace there
2. **Identify the error code** above
3. **Apply the listed Action** — most are automatic / silent
4. **Tell the user** in the case of E1 (config), E2-E5 (persistent rate limits), E8 (renderer switch), E9 (no results)
5. **Don't retry blindly** — if the action says "drop X for this run," do that, don't try X again. Stuck-retry loops are worse than degraded reports.

## Telling the user

Format: `[error_code] short_description: what_I_did. <one suggested user action if applicable>`. Examples:

- `[E2] OpenAlex rate-limited. Waiting 60 s, then retrying. (None for you — automatic.)`
- `[E3] Semantic Scholar persistent 429. Skipping influential-citation enrichment; report will use citation_count only.`
- `[E9] No papers matched. I suggest broadening the year range or removing the "elderly" filter. Want me to retry with: <query rewrite>?`
