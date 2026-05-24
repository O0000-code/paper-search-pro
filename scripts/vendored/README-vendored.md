# Vendored / Adapted Code — Attribution & Provenance

This directory contains code and design patterns adapted from the
[paper-qa](https://github.com/Future-House/paper-qa) project by FutureHouse
(originally licensed under Apache License 2.0). Per Apache 2.0 §4.b, we
preserve attribution and document modifications below.

## Upstream Source

- **Project**: paper-qa (also known as PaperQA / PaperQA2)
- **Repository**: https://github.com/Future-House/paper-qa
- **License**: Apache License 2.0 (full text in `LICENSE-paperqa.txt`)
- **Reviewed at commit**: main branch as of 2026-05-19 (Wave 3 research snapshot)
- **Maintainer**: FutureHouse / Edison Scientific

## v2.0 Refactor Note (2026-05-21)

paper-search-pro v2.0 dropped the state-machine / LLM-classification path in
favour of a deterministic main-agent recipe. As a result, three of the five
patterns originally borrowed from paper-qa are **no longer in the codebase**:

| Original target file | Status in v2.0 | Replacement |
|---|---|---|
| `scripts/state_machine.py` | **Removed** | Main Claude Code agent drives recipe directly via SKILL.md |
| `scripts/prompt_templates.py` | **Removed** | Classification is done by SubAgents reading `references/classifier_subagent_prompt.md` |
| `scripts/checkpoint_jsonl.py` | **Removed** | No durable state needed — each helper is one-shot |

The Apache 2.0 attribution below covers only the patterns **still present in
v2.0**. The removed-pattern lineage is preserved here for traceability —
their upstream source remains acknowledged even though the borrowed code is
no longer shipped.

## Patterns Currently Borrowed (v2.0 — 2 active)

Each row lists what we borrowed, where the upstream source lives, where our
adaptation lives in `paper-search-pro`, and what we changed.

### 1. RCS scoring resilience: multi-layer fallback parser

- **Upstream**: `src/paperqa/core.py:178-380` — `map_fxn_summary()` does
  retrieve + contextualize + score in one LLM call returning structured
  `Context(score, citation, …)` objects; JSON-parse failures fall back to
  partial extraction.
- **Our adaptation**: `scripts/rcs_parser.py` — 5-layer fallback parser with
  strict quantity / ID / range validation (`_validate_strict`).
- **Modifications**:
  - Scale: we use 0-10 (paper-qa uses an internal score-on-scale string).
  - Fallback ladder: paper-qa retries the same LLM call; we ladder through
    5 layers (direct JSON → fence → array regex → per-paper regex →
    tolerant regex). v1's 8-layer ladder (with `repair_call` / `shrink_batch`
    / `mark_uncertain`) was simplified to 5 layers in v2.0 because LLM
    repair calls were removed (no external LLM dependency).
  - Strict gate: we reject parses that fail ID / quantity / range checks
    even when they look "JSON-y". paper-qa accepts looser shapes.
  - We never silently `zip()` input/output — count mismatch always
    triggers a fallback layer (per Wave 4 Gemini/Codex review).
  - The classification prompt itself (`references/classifier_subagent_prompt.md`)
    is original to paper-search-pro; only the high-level "single-call RCS"
    structure is borrowed.

### 2. Federated metadata resolver with deterministic source priority

- **Upstream**: `src/paperqa/clients/__init__.py:84-263` — `DocMetadataClient`
  uses nested `asyncio.gather` over (provider × postprocessor) pairs and
  short-circuits when a complete record is found.
- **Our adaptation**: `scripts/federated_kg_resolver.py` — main-agent
  single-writer merge across (OpenAlex × Semantic Scholar × CrossRef × arXiv ×
  PubMed) with deterministic source priority.
- **Modifications**:
  - Single-writer pattern (no async race) per Wave 4 Codex review for
    concurrency safety.
  - DOI is Primary Key; year + title + first-author are secondary
    deduplication keys.
  - Field-level merging: OpenAlex priority for `doi / year / venue / fwci /
    topics`, SS priority for `tldr / influential_citation_count`, CrossRef
    priority for `funder / license / clinical_trial_number`, common fields
    take `max(citation_count)` and `longer(abstract)`.
  - Sanity-check gate (v2.0 addition, post-audit P1-1): merged fields are
    validated (e.g. `year < current_year + 1`, author non-empty) before
    being committed; failing fields fall back to next-priority source.

### 3. Tenacity-style retry without the tenacity dependency

- **Upstream**: `src/paperqa/utils.py:453-516` (`is_retryable` + `_get_with_retrying`)
  and `src/paperqa/clients/semantic_scholar.py:118-135` (`_s2_get_with_retrying`).
- **Our adaptation**: `scripts/vendored/tenacity_retry.py` —
  `@retryable_api_call(provider=...)` decorator with provider-specific RPS
  limits and exception classification.
- **Modifications**:
  - Provider-specific RPS budget (OpenAlex 10 RPS, Semantic Scholar 1 RPS,
    NCBI 10 RPS with key / 3 without, CrossRef 50 RPS polite-pool, arXiv
    1 req / 3 s) enforced via a lightweight token-bucket inside the decorator.
  - Exception classification: 429 / 5xx / network errors retry with
    exponential backoff (10 s → 30 s → 90 s, 3 attempts); 4xx (except 429)
    never retry.
  - We use `wait_exponential` rather than paper-qa's `wait_incrementing(0.1, 0.1)`
    — paper-qa's linear backoff assumes a single async client; we may be
    invoked from parallel SubAgents and need stronger thundering-herd
    protection (matches paper-qa's own `wait_random_exponential` choice for
    Tantivy lock contention).
  - **No tenacity third-party dependency** — we implement the small subset
    we need in pure stdlib for Skill portability.

## Changes List (Apache 2.0 §4.b — "stating that You changed the files")

Files in `scripts/` that contain adapted patterns prominently note their
upstream lineage in module docstrings. The complete list of changes from
upstream paper-qa **as it applies to code shipped in v2.0**:

1. RCS scoring uses 0-10 integer scale with explicit `flag` field for
   `abstract_unavailable` / `off_topic_despite_keywords` / `parse_failed_uncertain`.
2. 5-layer fallback parser (simplified from v1's 8-layer; LLM-repair layers
   removed in v2.0) replaces paper-qa's single-retry parser.
3. Strict `_validate_strict()` gate at every parse layer.
4. Main-agent single-writer concurrency model replaces paper-qa's async
   nested-gather concurrency.
5. Federated resolver covers 5 sources (paper-qa covers OpenAlex + SS +
   CrossRef + arXiv + Google Scholar); paper-search-pro substitutes PubMed
   for Google Scholar for medical-MeSH support.
6. Sanity-check gate at merge time (year / author / venue validation).
7. Provider-specific RPS limits + 3-attempt exponential backoff replace
   paper-qa's 5-attempt linear-increment backoff.
8. No tenacity third-party dependency — stdlib-only retry helpers.
9. Prompts (`classifier_subagent_prompt.md`, etc.) are original; only the
   high-level "single-call RCS" structure is borrowed.

### Patterns Borrowed in v1 but Removed in v2.0

For traceability, the following paper-qa patterns were borrowed in v1
(Waves 3-5) but no longer ship in v2.0. Their upstream lineage remains
acknowledged here:

- **Tool-based state machine (agent loop)** — was adapted into
  `scripts/state_machine.py` (`Tool` dataclass + `StateMachine.step()`).
  Removed in v2.0; replaced by main-agent recipe in SKILL.md.
- **Single-call classification prompts** — was adapted into
  `scripts/prompt_templates.py` (`CLASSIFICATION_SYSTEM` / `CLASSIFICATION_USER`
  / `CLASSIFICATION_REPAIR_USER`). Removed in v2.0; classification prompt
  moved to `references/classifier_subagent_prompt.md`, executed by SubAgents.
- **Tantivy SearchIndex with file lock + reference counting** — never
  directly implemented; the *intent* (durable, resumable state) was
  borrowed into `scripts/checkpoint_jsonl.py` (append-only JSONL). Removed
  in v2.0 because helpers are one-shot and need no durable state.

## License Summary

paper-qa is Apache 2.0 licensed. This skill is also Apache 2.0 licensed
(see `LICENSE.txt` at skill root). Per Apache 2.0 §4:

- §4.a — License copy preserved (`LICENSE-paperqa.txt` here, plus our own
  `LICENSE.txt` at skill root).
- §4.b — Modifications stated above ("Changes List").
- §4.c — Copyright notices preserved — paper-qa carries no per-file
  copyright headers; the LICENSE file is authoritative.
- §4.d — NOTICE preservation — paper-qa has no NOTICE file at the reviewed
  commit. If a NOTICE is added upstream in the future, this directory
  must be updated to mirror it.

When adding new code adapted from paper-qa or any other Apache 2.0
project, append a new pattern row above and update the Changes List.
