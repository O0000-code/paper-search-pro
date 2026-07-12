# Source Routing

*This file is read by the main agent across STEP 1-2 of `SKILL.md`. The two phases are ordered: **STEP 1 decides the language space** — §"Language scope" below is its SSOT (which ocean to fish in, **including the one first-time question** on an ambiguous Chinese query). **STEP 2 then routes the L2/L3 supplemental sources *within* that already-fixed space** (the rest of this file — which nets to cast); STEP 2 does NOT re-decide the space. Both phases are done the same way: **you (the LLM) make the semantic judgment; the tables are calibration examples, not a mechanical keyword match; and deterministic facts (CJK detection, explicit `--flags`) stay code.***

*Source-routing rules are based on SA-V3 empirical testing: 85% accuracy across 20 ground-truth queries (24_v3_domain_signal_test.md), with 0% false-trigger on pure social science / humanities, 0% false-skip on medical or CS queries, and the only error mode being cross-domain queries silently degrading to single-source.*

## How to read every signal table in this file (semantic judgment, not string match)

The keyword tables below (medical / CS / language markers) exist to **calibrate your judgment**, not to be grepped. **You decide** whether a query is medical, CS, social-science, or wants Chinese literature — using the examples as anchors for what each domain looks like. A query with none of the listed words can still be clearly medical; a query that happens to contain a listed word (e.g. "attention" in a psychology context, not "attention mechanism") may not be. Judge meaning, not tokens.

Three things stay **mechanical / deterministic** (never LLM-guessed):

- **CJK detection** — whether the query contains Chinese characters is a code fact (`detect_language.py`), the entry condition for the `auto`→ask branch below.
- **Explicit user flags / overrides** — `--lang en|zh|both`, `--no-pubmed`, `--no-nssd`, `--source …`, and an explicit persisted `config` value are honoured verbatim; they win over any judgment (see priority ladder). *(On the human path these `--flag` spellings are **natural-language override notation** — shorthand for what the user says, interpreted by you, not tokens any script parses. The only script-parsed flags are on the `agent_search` path, where Chinese-source control is opt-**in** — `--with-nssd` / `--with-yiigle`, never `--no-nssd` / `--source`. See `agent_mode.md`.)*
- **The `federate → dedup` step** downstream is deterministic; routing only decides *which* sources feed it.

When in doubt on a *semantic* call, prefer recall (add the source) — L2/L3 boosters only add candidates and are individually removable with a flag.

## Language scope (axis 2 — decided in STEP 1, BEFORE STEP 2 source routing)

*(v2.3, additive. This is axis 2 of the **three-axis model**: **engine** `primary_source` = who runs the primary retrieval; **language** `search_language` = which ocean to search; **boosters** = per-discipline nets auto-routed inside the chosen ocean. **Axis 3 has three interchangeable names for one concept — `boosters` = `补充源` = `supplemental sources` — used interchangeably across SKILL.md / this file / `agent_mode.md`; they never denote anything different.** The default `search_language: auto` reproduces v2.2 behavior exactly for English queries — R-19. The interaction scripts / 话术 for the human path live in `SKILL.md` STEP 1-2; this section is the SSOT for the **parsing logic**.)*

### Resolution priority (mirrors rank platform's `flags > intent > default`)

Apply top-down; the first level that fires wins, and level 1 always wins:

```
1. Explicit per-query instruction  — CLI flag (--lang en|zh|both) or NL wording
                                      ("这次只要英文" / "中英都查" / "找中文的")
                                      → transient, NEVER auto-persisted.
2. In-query language marker         — §"Language markers" hit → follow it, don't ask.
3. Persisted config value           — search_language ∈ {en, zh, both} → adopt silently.
4. auto fallback:
   4a. no CJK and no explicit "want Chinese" wording → en  (don't ask; v2.2 behavior)
   4b. query contains CJK (or an English query explicitly asks for Chinese lit) →
        · human path : ask ONE question (SKILL.md STEP 1, 22 §6.1), offer to persist
        · agent/headless path : pass the query through as-is (query language = space),
          add NO boosters, mark ambiguity in meta — never ask, never guess
```

Each level is overridable by the level above it (level 1 beats everything, exactly like `--no-pubmed`). Once asked within a session, reuse the answer for later Chinese queries in the same session (report one line, don't re-ask).

### Language markers (semantic judgment — examples, not a match list)

**→ zh space** (any one; may appear in a Chinese *or* an English query):

| Category | Example markers |
|---|---|
| Explicit language ask | `中文文献` `中文论文` `中文期刊` `中文的研究` `国内研究` `国内文献` `Chinese-language papers` `literature in Chinese` |
| Chinese journal-quality systems | `CSSCI` `C刊` `北大核心` `中文核心` `CSCD` (these systems index **only** Chinese journals — naming one = wanting Chinese) |
| Chinese database named | `知网` `CNKI` `万方` `维普` `NSSD` (triggers zh **plus** the compliance note in SKILL.md STEP 4, 22 §6.5) |
| Chinese journal named | `中华××杂志` `心理学报` `经济研究` and other specific Chinese journal titles |

**→ en space** (appearing inside a Chinese query; any one):

| Category | Example markers |
|---|---|
| Explicit language ask | `英文文献` `英文论文` `外文文献` `只要英文` |
| English-index systems | `SSCI` `SCI收录` (JCR/SJR wording is rank_intent's job, NOT a language signal — see below) |

**→ both**: `中英都要` `中英文` `both Chinese and English` and other explicit conjunctions.

Markers are **routing/filter conditions, not search terms** — once a marker selects the space, strip it from the topic before retrieval (same discipline as rank_intent: `CSSCI 情绪调节` searches *情绪调节* with CSSCI as a zh signal + quality tag; never send the letters "CSSCI" to the engine). CSSCI/北大核心 carry a dual identity (language signal + quality tier), handled exactly like "中科院一区"'s dual identity (platform + tier).

### Non-signals — never infer language from these (anti-patterns)

| Wording | Why it is NOT a language signal |
|---|---|
| `中科院一区/二区…` | rank platform signal (CAS mainly covers international SCI journals); handled by `rank_intent`, **zero** language meaning |
| `顶刊` `top journal` | rank-tier wording, language-independent |
| Topic is about China (`中国` `China` `乡村振兴` `中国大学生`…) | topic geography ≠ literature-language preference; there is a vast English literature *about* China |
| The query happens to be in Chinese | only the trigger to *enter the 4b ask*, **not** a licence to enable Chinese sources (a 中英-bilingual grad student often describes a topic in Chinese but wants SSCI) |
| `JCR/SJR` wording | keep the axes orthogonal — rank is rank, language is language; coupling them would make "an SJR-Q1 Chinese management study" inexpressible |

### Hard boundaries (the negative face — as binding as the positive rules)

1. **English query with no zh marker → Chinese sources do not exist this run.** Don't probe, don't suggest, don't "also search Chinese". This is the interaction face of R-19.
2. **Persisted `search_language: en` + a Chinese query → still don't enable Chinese sources**, but report one line (SKILL.md STEP 4, 22 §6.4) — never a silent translation; a per-query level-1 instruction can still override for that one run.
3. **Agent/headless path never asks and never guesses** — boosters honour only explicit flags + config; ambiguity is written to `meta`, handed up to the caller (see `agent_mode.md`).
4. **A single choice is never auto-persisted** — only an explicit "以后都…" writes config (the rank-platform discipline, reused verbatim).
5. **Engineering gate:** the CJK-safe dedup fix (Phase 0) must be in place before the zh space opens — without it a Chinese result set silently collapses to one row. (Phase 0 is landed on this branch, so the gate is open.)

## Decision flow (apply in order — you judge; these are steps, not string matches)

```
1. Detect medical signals → enable PubMed enricher
2. Detect arXiv/freshness signals → enable arXiv freshness sentinel
3. Cross-domain whitelist match → force BOTH PubMed + arXiv (silent upgrade)
4. Pure non-L2 signals AND no medical/CS hits → OpenAlex only
5. Ambiguous → default upgrade to "BOTH PubMed + arXiv" (Recall > Precision)
6. User CLI override (`--no-pubmed` / `--no-arxiv` / `--source=...`) wins everything
```

After deciding, **say one sentence to the user**: *"I detected [medical signal: 'RCT' + 'metformin'] — also searching PubMed. Override with `--no-pubmed` if you want OpenAlex only."*

## Primary source selection & quota fallback

*(v2.2, additive. **Default behaviour is unchanged: OpenAlex is the primary source and STEP 3 runs exactly as written above.** This section only applies when the user has set `primary_source` in `~/.paper-search-pro/config.yaml`, or has asked for quota-driven fallback. It governs the **human 14-STEP path**; the headless `agent_search` path consumes the same config automatically — see `references/agent_mode.md`.)*

`config.primary_source` (in `~/.paper-search-pro/config.yaml`) selects which source serves the **primary retrieval** in STEP 3:

| Value | Behaviour |
|---|---|
| `openalex` *(default)* | STEP 3 runs OpenAlex exactly as written. Nothing below changes. |
| `semantic_scholar` | STEP 3 retrieves from Semantic Scholar instead. **Requires `semantic_scholar_api_key`** (SS 429s instantly on the shared pool without a key — R-06). |
| `auto` | STEP 3 normally uses OpenAlex, but if the OpenAlex daily USD budget is low, this run stickily falls back to SS (needs the SS key + `quota_fallback: true`). |

### AI / CS queries → consider Semantic Scholar as primary (your judgment)

Beyond the config knob above, **you may raise the primary source to Semantic Scholar for a run when you judge the query to be core AI / CS.** SS's corpus covers the AI/CS + arXiv-preprint literature more completely than OpenAlex on these topics — empirically, "attention mechanism" / "Qwen2.5"-class queries surface their canonical preprints and citation structure on SS that OpenAlex under-weights (OpenAlex's 3-day arXiv lag + preprint under-indexing). This is a **semantic judgment** — *is this query about LLMs / transformers / CS systems / ML methods?* — calibrated by the arXiv signal tables below, not a mechanical rule.

Preconditions (deterministic — all must hold, else you stay on OpenAlex):

- **An SS API key is configured.** Without it SS 429s instantly on the shared pool (R-06), so a keyless run silently stays on OpenAlex — announce the skip per Rule C ("no SS key, so staying on OpenAlex for this AI query; add `semantic_scholar_api_key` for fuller preprint coverage").
- **The user hasn't pinned `primary_source`** (or `--lang`-style engine choice) for this run — an explicit config/flag always wins over your judgment.

When you do switch, run STEP 3 against SS exactly as the "### If switching to Semantic Scholar for this run" flow below (same `ss_helper --search`, same `raw/openalex.json` sink, same OpenAlex single-lookup backfill of OA-only fields) — the switch is engine-only and capability-neutral. Tell the user one line: *"Core-AI query — using Semantic Scholar as the primary source for fuller preprint coverage; OpenAlex single-lookups backfill the OA-only fields."*

### When to run the pre-STEP-3 quota check

Run a quota check **before STEP 3** only when `primary_source: auto` **or** the user explicitly asks for quota-aware fallback. (For plain `primary_source: openalex` or `semantic_scholar`, skip it.)

```bash
PYTHONPATH=$PSP_HOME \
  python3 -m scripts.quota_guard --mode run
```

`--mode run` reads OpenAlex's `X-RateLimit-Remaining-USD` header and emits a sticky verdict: `should_switch: true` when remaining USD is at/below `quota_fallback_threshold_usd` (default `0.05`). **A failed probe (`ok: false`) means "stay on OpenAlex" — absence of evidence is not exhaustion; never switch on a failed probe.**

### If switching to Semantic Scholar for this run

When `primary_source: semantic_scholar`, or `auto` resolved to a switch, run STEP 3 against SS instead of OpenAlex:

```bash
PYTHONPATH=$PSP_HOME \
  python3 -m scripts.ss_helper --search "<query>" \
    --year-min 2018 --n 50 \
    > "$SEARCH_DIR/raw/openalex.json"
```

`ss_helper --search` emits the same `UnifiedPaperEntity[]` shape as `openalex_helper`, so STEP 4-13 are unchanged (write it to the same `raw/*.json` you would have written OpenAlex to and federate as usual).

### Backfill OpenAlex-only fields after switching to SS (do NOT lose capability)

SS records lack several fields OpenAlex provides (`institution` / `funder` / `topics` / `fwci` / journal ISSN for the SJR join / `openalex_2yr_mean_citedness`). After an SS-primary run, recover them with **free single-paper OpenAlex lookups** — one cheap `get` per paper that has a DOI:

```bash
PYTHONPATH=$PSP_HOME \
  python3 -m scripts.openalex_helper get "<doi>"   # free single-work lookup, repeat per DOI
```

This keeps the switch capability-neutral: SS provides the primary result set, OpenAlex single-lookups refill the OA-only fields (institution / funder / topics / fwci / ISSN→SJR join / open impact). Papers with no DOI stay un-backfilled — that gap is expected and visible, not silently joined. (R-08: the missing-ISSN backfill is exactly what `agent_search` automates on its own path; on the human path you do the same `get`-per-DOI recovery.)

### Naming / compliance reminder

The OpenAlex open impact figure (`openalex_2yr_mean_citedness`) is **NOT** the JCR Impact Factor and SJR quartiles are **NOT** JCR/中科院 (R-04/R-09). See `references/journal_metrics.md`.

## PubMed enable rules

**Judgment, not string-match** (the top-of-file rule applies here in full): the tables below are **calibration examples of what a clearly-medical query looks like** — *you* decide whether the query is medical and enable the PubMed enricher accordingly. A query carrying none of these words can still be clearly medical; one that merely contains a listed word (`intervention` in a pure-education context) may not be. When genuinely torn, prefer recall (enable it) — the enricher only adds candidates.

### Strong medical signals — the surest tells (any one usually means "medical")

| Category | Example markers |
|----------|-----------------------------|
| **Secondary evidence** | `RCT`, `randomized controlled trial`, `systematic review`, `meta-analysis`, `PRISMA`, `Cochrane`, `umbrella review`, `network meta-analysis`, `GRADE` |
| **Clinical research** | `clinical trial`, `cohort study`, `case-control`, `case series`, `phase I/II/III`, `dose-response`, `intention-to-treat` |
| **MeSH / medical actions** | `MeSH`, `incidence`, `prevalence`, `mortality`, `morbidity`, `screening`, `differential diagnosis`, `prophylaxis`, `intervention` (medical context) |

### Medium medical signals — softer cues (a couple together read as clearly medical)

| Category | Example markers |
|----------|----------|
| **Disease names** | Specific disease names (diabetes, cancer, hypertension, IBS, Alzheimer's, COVID-19, sickle cell, asthma, depression, etc.), ICD codes, medical specialties (cardiology, oncology, nephrology, pediatrics, geriatrics) |
| **Drugs / therapies** | Specific drug names (metformin, GLP-1, statin, aspirin), `receptor agonist/antagonist`, `inhibitor`, `monoclonal antibody`, `vaccine`, `gene therapy` |
| **Biomedical research** | `genomics`, `proteomics`, `metabolomics`, `epidemiology`, `pharmacology`, `pharmacokinetics`, `biomarker`, `clinical guidelines` |
| **Chinese medical** | `临床`, `医学`, `治疗`, `患者`, `疾病`, `药物`, `干预` |
| **Patient / treatment** | `patient`, `treatment`, `therapy`, `intervention` (in medical context) |

## arXiv enable rules

**Judgment, not string-match** (same rule): the tables below **calibrate what a CS/AI or freshness-driven query looks like** — *you* decide whether the query wants the arXiv freshness sentinel and enable it accordingly. Meaning over tokens: `attention` in a psychology query is not the `attention mechanism` of a CS one. When torn, prefer recall.

### Strong CS/AI-or-freshness signals — the surest tells (any one usually means "run arXiv")

| Category | Example markers |
|----------|----------|
| **Explicit preprint** | `arxiv`, `preprint`, latest preprint name (e.g. "arXiv 2401.12345") |
| **Freshness words** | `latest`, `recent`, `cutting-edge`, `state-of-the-art`, `SOTA`, `frontier`, `newest`, `最新` |
| **Top CS venues** | `NeurIPS`, `ICML`, `ICLR`, `CVPR`, `ECCV`, `ACL`, `EMNLP`, `AAAI`, `IJCAI`, `KDD`, `STOC`, `FOCS` |
| **Year freshness** | `2024`, `2025`, `2026` co-occurring with method words |

### Medium CS/AI signals — softer cues

| Category | Example markers |
|----------|----------|
| **CS / AI core** | `LLM`, `large language model`, `transformer`, `attention mechanism`, `BERT`, `GPT`, `diffusion model`, `GAN`, `VAE`, `RLHF`, `RAG`, `agent`, `tool use`, `prompt engineering`, `chain-of-thought`, `MoE`, `speculative decoding`, `KV cache`, `quantization` |
| **AI interpretability / safety** | `mechanistic interpretability`, `sparse autoencoder`, `feature circuits`, `alignment`, `red teaming`, `jailbreak`, `RLAIF` |
| **Classic ML** | `deep learning`, `reinforcement learning`, `unsupervised learning`, `self-supervised`, `contrastive learning`, `representation learning`, `meta-learning`, `few-shot`, `zero-shot`, `transfer learning` |
| **Physics / math / theory CS** | `quantum computing`, `tensor network`, `category theory`, `lattice cryptography`, `homomorphic encryption` |

## Cross-domain whitelist (force BOTH PubMed + arXiv)

Per SA-V3 §5.1 Rule C, when a medical signal co-occurs with a CS signal — OR the query matches one of the patterns below — silently enable both. This rescues the 3/5 Class-C queries (Q12 Q13 Q15) that single-source heuristics fail on.

| Whitelist pattern | Example matches |
|-------------------|------------------|
| **Medical imaging AI** | `radiology image` + AI, `medical imaging` + AI, `CT scan` + AI, `MRI` + DL, `ultrasound` + ML, `pathology image` + DL, `histopathology` + AI |
| **Drug discovery ML** | `drug discovery` + (transformers/GNN/DL), `molecular design` + ML, `protein-ligand` + DL, `ADMET prediction` |
| **Bioinformatics DL** | `protein structure prediction`, `genomics` + DL, `single-cell` + ML, `RNA folding` + DL |
| **Clinical NLP** | `clinical notes` + NLP, `electronic health records` + LLM, `EHR` + transformer, `medical chatbot` |
| **Neuro ML** | `fMRI` + (DL/ML), `EEG` + (DL/ML), `MEG` + DL, `brain decoding`, `brain-computer interface` |
| **Precision medicine ML** | `personalized medicine` + (RL/ML), `precision oncology` + DL, `treatment recommendation` + RL |
| **Epidemic ML** | `epidemic forecasting` + ML, `disease prediction` + DL, `outbreak` + neural network |

## Pure non-L2 (negative triggers — OpenAlex only)

If the query has **no** medical signal AND **no** CS signal, default to OpenAlex only. Typical patterns:

| Pure domain | Signal words |
|-------------|--------------|
| **Psychology (non-clinical)** | attachment theory, prospect theory, self-construal, social identity, prejudice, intergroup, attitude change |
| **Economics / business** | behavioral economics, market design, game theory, mechanism design, monetary policy, fiscal, supply chain |
| **Sociology / political science** | inequality, mobility, populism, democracy, authoritarianism, social movements |
| **History / literature / philosophy** | postcolonial, literary criticism, historiography, hermeneutics, phenomenology, ethics theory, Said, Spivak |
| **Education / linguistics** | curriculum design, pedagogy, second language acquisition, sociolinguistics |
| **Law / public policy** | constitutional law, legal theory, public administration (NOT health policy — health policy → PubMed) |

## Field priority table (federated merge)

When a paper exists in multiple sources, the federated KG resolver picks fields by this priority. This is the canonical version, replacing earlier drafts in 22_/23_/25_ synthesis docs.

| Field | Primary | Fallback 1 | Fallback 2 | Notes |
|-------|---------|------------|------------|-------|
| `title` | OpenAlex | PubMed | SS | OA most consistent |
| `abstract` | OpenAlex (reconstructed) | SS (direct) | PubMed (medical only) | SA-V1: SS abstract fallback covers ~67% of old papers OA leaves empty |
| `year` | OpenAlex | CrossRef (`created.date-time`) | PubMed | OA reliable |
| `authors` | OpenAlex | PubMed | SS | OA has ORCID + affiliation |
| `doi` | OpenAlex (lowercased) | CrossRef | PubMed | normalize: lowercase + strip URL prefix |
| `pmid` | PubMed | OpenAlex.ids.pmid | — | |
| `pmcid` | PubMed | OpenAlex.ids.pmcid | — | |
| `arxiv_id` | arXiv (strip version) | OpenAlex.locations[].landing_page_url | — | strip "vN" suffix |
| `citation_count` | OpenAlex | SS | — | SS undercount 20-50% vs OA **for journal papers**; **reversed for CS / arXiv preprints** (OpenAlex under-indexes arXiv, so SS is the higher/more-complete count there) — don't treat OA as authoritative for preprint citation counts |
| `influential_citation_count` | **SS only** | — | — | unique signal, no fallback exists |
| `references` | OpenAlex | CrossRef (top-N supplement) | SS | **skip arXiv DOI** in CrossRef |
| `funders` / `grants` | CrossRef | OpenAlex.grants | — | OA grants often empty |
| `license` | CrossRef | OpenAlex.primary_location.license | — | CR has `delay-in-days` + `content-version` |
| `mesh_terms` | **PubMed only** | — | — | unique signal |
| `publication_types` | PubMed (`["Clinical Trial", "Review"]`) | OpenAlex.type | — | |
| `clinical_trial_number` | CrossRef | PubMed | — | NEJM clinical CR returns empty — fall to PubMed |
| `pdf_url` / `open_access_url` | OpenAlex (`oa_url`) | arXiv (preprint) | PubMed (PMC link) | |

### Chinese-native records (NSSD / yiigle) — preserve the Chinese original

For a paper whose provenance includes a native Chinese source (`sources` contains `nssd` or `yiigle`), the **Chinese-original `title` / `abstract` / `authors` / `venue` take priority — they must not be overwritten by an English OpenAlex value.** The zh space exists to return Chinese literature *in Chinese*; clobbering a Chinese title with OpenAlex's English rendering defeats the point and breaks the report's Chinese display. Concretely, the priority for a zh-native record is:

| Field | Primary (zh-native record) | Notes |
|-------|----------------------------|-------|
| `title` | NSSD / yiigle (Chinese original) | never replace with an English OpenAlex title |
| `abstract` | NSSD / yiigle (Chinese original) | Chinese abstract is the whole point of the zh source |
| `authors` | NSSD / yiigle (Chinese names) | keep the Chinese author strings, don't Latinise |
| `venue` | NSSD / yiigle (Chinese journal name) | e.g. `心理学报`, not an English exonym |

- **The common case is automatic.** Most NSSD/yiigle records carry no DOI, so they get their own `("native", source_native_id)` canonical key (federated_kg_resolver 0.2) and never collide with an OpenAlex record — no merge can touch their Chinese fields.
- **The DOI-collision case is the one that was at risk.** When a Chinese-native record *does* carry a DOI that also exists in OpenAlex, the two merge on `("doi", …)`, and the general rule above prefers OpenAlex for `title`/`authors` — which for this record would replace the Chinese original with English, the wrong outcome in a zh result set. **This is now enforced (#4, landed on this branch):** `merge_paper_fields` special-cases Chinese provenance via a `_has_chinese_source` check, so native-Chinese `title`/`abstract`/`authors`/`venue` win over an English OpenAlex value on a DOI collision (both a Chinese `existing` blocking an English `new`, and a Chinese `new` overriding an English `existing`). Every English-only merge keeps both flags `False`, so those paths stay byte-identical to before (R-19). The "must not overwrite" contract in the table above is therefore a live guarantee, not an aspiration.

## Conflict resolution (E5b guard)

If two records share the same `title` + `year` but have **different DOIs**, **keep them separate**. They are likely different papers with identical titles, or a published version + preprint pair that should not be merged. See `federated_kg_resolver.py` E5b guard test cases.

## Error pitfalls (empirically verified)

- **arXiv DOI in CrossRef → 100% 404** (SA-V1 / SA-W2). Always skip CrossRef enrichment when DOI starts with `10.48550/arxiv.` or `10.48550/arXiv.`. `crossref_helper._is_arxiv_doi()` handles this.
- **arXiv DOI case drift**: arXiv emits `10.48550/arXiv.<id>` (capital X), OpenAlex normalizes to `10.48550/arxiv.<id>` (lowercase x). The resolver must lowercase before comparing. Already handled by `_strip_doi_prefix()`.
- **K&T 1979 prospect theory has `references=[]` in OpenAlex** — an OpenAlex upstream takedown for pre-2000 papers. Accept the empty list; do not retry or attempt repair. SA-Z2 F19 confirmed.
- **NEJM clinical trial papers have empty CrossRef `clinical-trial-number`** (SA-V1) — fall back to PubMed `clinical_trial_numbers` parsing.
- **OpenAlex 3-day arXiv index lag**: papers from T-0 to T-2 are 0% in OpenAlex, T-3 partial. Only run arXiv freshness sentinel for the 4-5 day window beyond OpenAlex's lag.
