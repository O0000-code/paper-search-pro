# Source Routing

*This file is read by the main agent in STEP 2 of `SKILL.md` to decide which L2/L3 sources to enable beyond the OpenAlex baseline. Routing rules are based on SA-V3 empirical testing: 85% accuracy across 20 ground-truth queries (24_v3_domain_signal_test.md), with 0% false-trigger on pure social science / humanities, 0% false-skip on medical or CS queries, and the only error mode being cross-domain queries silently degrading to single-source.*

## Decision flow (apply in order)

```
1. Detect medical signals → enable PubMed enricher
2. Detect arXiv/freshness signals → enable arXiv freshness sentinel
3. Cross-domain whitelist match → force BOTH PubMed + arXiv (silent upgrade)
4. Pure non-L2 signals AND no medical/CS hits → OpenAlex only
5. Ambiguous → default upgrade to "BOTH PubMed + arXiv" (Recall > Precision)
6. User CLI override (`--no-pubmed` / `--no-arxiv` / `--source=...`) wins everything
```

After deciding, **say one sentence to the user**: *"I detected [medical signal: 'RCT' + 'metformin'] — also searching PubMed. Override with `--no-pubmed` if you want OpenAlex only."*

## PubMed enable rules

### Strong signals (always enable PubMed if any present)

| Category | Keywords (any one triggers) |
|----------|-----------------------------|
| **Secondary evidence** | `RCT`, `randomized controlled trial`, `systematic review`, `meta-analysis`, `PRISMA`, `Cochrane`, `umbrella review`, `network meta-analysis`, `GRADE` |
| **Clinical research** | `clinical trial`, `cohort study`, `case-control`, `case series`, `phase I/II/III`, `dose-response`, `intention-to-treat` |
| **MeSH / medical actions** | `MeSH`, `incidence`, `prevalence`, `mortality`, `morbidity`, `screening`, `differential diagnosis`, `prophylaxis`, `intervention` (medical context) |

### Medium signals (enable PubMed; 2+ medium signals = high confidence)

| Category | Keywords |
|----------|----------|
| **Disease names** | Specific disease names (diabetes, cancer, hypertension, IBS, Alzheimer's, COVID-19, sickle cell, asthma, depression, etc.), ICD codes, medical specialties (cardiology, oncology, nephrology, pediatrics, geriatrics) |
| **Drugs / therapies** | Specific drug names (metformin, GLP-1, statin, aspirin), `receptor agonist/antagonist`, `inhibitor`, `monoclonal antibody`, `vaccine`, `gene therapy` |
| **Biomedical research** | `genomics`, `proteomics`, `metabolomics`, `epidemiology`, `pharmacology`, `pharmacokinetics`, `biomarker`, `clinical guidelines` |
| **Chinese medical** | `临床`, `医学`, `治疗`, `患者`, `疾病`, `药物`, `干预` |
| **Patient / treatment** | `patient`, `treatment`, `therapy`, `intervention` (in medical context) |

## arXiv enable rules

### Strong signals (always enable arXiv if any present)

| Category | Keywords |
|----------|----------|
| **Explicit preprint** | `arxiv`, `preprint`, latest preprint name (e.g. "arXiv 2401.12345") |
| **Freshness words** | `latest`, `recent`, `cutting-edge`, `state-of-the-art`, `SOTA`, `frontier`, `newest`, `最新` |
| **Top CS venues** | `NeurIPS`, `ICML`, `ICLR`, `CVPR`, `ECCV`, `ACL`, `EMNLP`, `AAAI`, `IJCAI`, `KDD`, `STOC`, `FOCS` |
| **Year freshness** | `2024`, `2025`, `2026` co-occurring with method words |

### Medium signals (enable arXiv)

| Category | Keywords |
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
| `citation_count` | OpenAlex | SS | — | SS undercount 20-50% vs OA |
| `influential_citation_count` | **SS only** | — | — | unique signal, no fallback exists |
| `references` | OpenAlex | CrossRef (top-N supplement) | SS | **skip arXiv DOI** in CrossRef |
| `funders` / `grants` | CrossRef | OpenAlex.grants | — | OA grants often empty |
| `license` | CrossRef | OpenAlex.primary_location.license | — | CR has `delay-in-days` + `content-version` |
| `mesh_terms` | **PubMed only** | — | — | unique signal |
| `publication_types` | PubMed (`["Clinical Trial", "Review"]`) | OpenAlex.type | — | |
| `clinical_trial_number` | CrossRef | PubMed | — | NEJM clinical CR returns empty — fall to PubMed |
| `pdf_url` / `open_access_url` | OpenAlex (`oa_url`) | arXiv (preprint) | PubMed (PMC link) | |

## Conflict resolution (E5b guard)

If two records share the same `title` + `year` but have **different DOIs**, **keep them separate**. They are likely different papers with identical titles, or a published version + preprint pair that should not be merged. See `federated_kg_resolver.py` E5b guard test cases.

## Error pitfalls (empirically verified)

- **arXiv DOI in CrossRef → 100% 404** (SA-V1 / SA-W2). Always skip CrossRef enrichment when DOI starts with `10.48550/arxiv.` or `10.48550/arXiv.`. `crossref_helper._is_arxiv_doi()` handles this.
- **arXiv DOI case drift**: arXiv emits `10.48550/arXiv.<id>` (capital X), OpenAlex normalizes to `10.48550/arxiv.<id>` (lowercase x). The resolver must lowercase before comparing. Already handled by `_strip_doi_prefix()`.
- **K&T 1979 prospect theory has `references=[]` in OpenAlex** — an OpenAlex upstream takedown for pre-2000 papers. Accept the empty list; do not retry or attempt repair. SA-Z2 F19 confirmed.
- **NEJM clinical trial papers have empty CrossRef `clinical-trial-number`** (SA-V1) — fall back to PubMed `clinical_trial_numbers` parsing.
- **OpenAlex 3-day arXiv index lag**: papers from T-0 to T-2 are 0% in OpenAlex, T-3 partial. Only run arXiv freshness sentinel for the 4-5 day window beyond OpenAlex's lag.
