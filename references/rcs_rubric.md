# RCS Rubric

*This file is read by classifier Inline SubAgents in STEP 6 of `SKILL.md`. It is referenced by `classifier_subagent_prompt.md`. Apply the rubric consistently across batches so the main agent can compare scores.*

RCS = **Relevance to Core Search**, an integer 0-10. Higher = more relevant to the user's query.

## Scoring scale

### 0-1: Off-topic

The paper does not address the query topic. Keywords may overlap superficially, but the substance is unrelated.

- **0** = no apparent relation at all
- **1** = mentions a query keyword but the paper is about something else

*Example (query: "prospect theory in decision making")*
- Title: "Future prospects for renewable energy in developing economies" → **0**
- Title: "Theory of computation: a primer" → **1** (just "theory" overlap)

### 2-3: Tangentially related

The paper touches on the topic but only as background, side reference, or in a very different context.

- **2** = topic mentioned once, not central
- **3** = related domain but a different sub-area

*Example (query: "working memory training in elderly")*
- "Cognitive aging: a broad review" mentioning WM as one of 12 cognitive domains → **2**
- "Visual working memory training in college students" (same intervention, wrong population) → **3**

### 4-5: Related but not core

The paper substantially addresses part of the query but misses the central question or population.

- **4** = covers 1 of 2-3 query dimensions
- **5** = relevant but old / weak design / pilot / non-empirical

*Example (query: "GLP-1 receptor agonist for obesity")*
- "Mechanism of action of GLP-1 in pancreatic β cells" (mechanism only, no obesity) → **4**
- "Liraglutide and weight loss: a 2016 pilot study n=20" (relevant but pilot) → **5**

### 6-7: Highly relevant — top reference candidates

The paper directly addresses the query with appropriate population, intervention, and methodology. These are the papers the user will most likely cite in their write-up.

- **6** = relevant, recent, decent method, would be cited
- **7** = direct hit on query, well-cited (>100 citations) OR landmark recent paper

*Example (query: "GLP-1 receptor agonist for obesity")*
- "Semaglutide 2.4mg once-weekly in adults with overweight or obesity: RCT, n=1961" (NEJM 2021) → **7**
- "Tirzepatide for chronic weight management" (NEJM 2022 RCT) → **7**

### 8-10: Foundational / Seminal

The paper is a foundational reference in the field — work that defines the construct, introduces the method, or is the most cited paper on this exact topic.

- **8** = clearly foundational but not the single defining work
- **9** = top-3 most-cited / most-influential on the exact query
- **10** = THE defining paper — original construct, Nobel-worthy method introduction, the paper everyone cites

*Example (query: "prospect theory in decision making")*
- Kahneman & Tversky 1979 "Prospect theory: an analysis of decision under risk" → **10**
- Tversky & Kahneman 1992 "Advances in prospect theory: cumulative representation of uncertainty" → **9**
- Thaler 1980 "Toward a positive theory of consumer choice" → **8**

*Example (query: "transformer architecture")*
- Vaswani et al. 2017 "Attention is all you need" → **10**
- Devlin et al. 2018 "BERT" → **9**

## Special flags (set `flag` field when applicable)

| Flag value | When to set | Effect on RCS |
|------------|-------------|---------------|
| `no_abstract_uncertain` | Abstract is empty/null AND title is the only signal | Drop RCS by 1 (cap at 5 unless title is overwhelming) |
| `off_topic_despite_keywords` | Title/keywords match query but abstract shows paper is about something else | Set RCS = 1-2 with reasoning |
| `parse_failed_uncertain` | Paper data is malformed (missing title, garbled abstract) | Set RCS = 0, flag for human review |
| `abstract_unavailable` | Abstract field exists but is "N/A" / "[paywalled]" / extremely short (< 20 chars) | Same as no_abstract_uncertain |
| `recent_unindexed` | arXiv T-0 to T-4 paper without citation_count yet (don't penalize freshness) | Score by title/abstract only; do not penalize for citation_count=0 |

## Scoring discipline

### Avoid RCS inflation
- Default to 4-5 for related-but-not-core papers; reserve 6-7 for papers that directly hit the query
- Reserve 8-10 for true foundational work — if you give 5 papers RCS≥8 in a batch of 10, you are inflating
- A paper with 50,000+ citations is **not automatically RCS=10**; relevance to the user's exact query is the gate
- A famous author is not RCS=10; the specific paper must be foundational

### Avoid RCS deflation
- Don't penalize papers for being recent (no citation_count yet) — judge by abstract/title
- Don't penalize papers for being in a different language (OpenAlex includes Chinese / Japanese / Korean / Russian abstracts) — judge by content
- Don't penalize preprints / arXiv papers — if the science is on-target, the venue doesn't determine RCS

### When uncertain
- If torn between two adjacent scores, **round down** (5 vs 6 → 5)
- If torn between flagging and not flagging, **flag it** — main agent benefits from seeing uncertainty signal
- If abstract is missing but title strongly suggests relevance, set RCS = 5 max with `no_abstract_uncertain` flag

## JSON output schema (per paper)

```json
{
  "paper_id": "10.1126/science.aaa5760",
  "rcs": 7,
  "reasoning": "Directly addresses query on GLP-1 for obesity; phase 3 RCT in NEJM with n>1900 and clinical-trial number; well-suited as primary citation. Not foundational (semaglutide is post-liraglutide work).",
  "flag": null
}
```

- `paper_id`: must match the `paper_id` from the batch input (use `paper_id` field from `UnifiedPaperEntity`)
- `rcs`: integer 0-10 (no decimals)
- `reasoning`: 1-2 sentences, max ~50 words. Mention specifically why this score, not generic praise
- `flag`: one of the values in the Special Flags table, or `null` if no flag applies

## Worked example outputs

**Input batch entry (excerpt)**:
```json
{
  "paper_id": "10.1056/nejmoa2032183",
  "title": "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
  "abstract": "BNT162b2 is a lipid nanoparticle-formulated...",
  "year": 2020,
  "citation_count": 14523,
  "venue": "New England Journal of Medicine"
}
```

**Query: "BNT162b2 COVID-19 vaccine efficacy"**:
```json
{
  "paper_id": "10.1056/nejmoa2032183",
  "rcs": 10,
  "reasoning": "The Pfizer-BioNTech BNT162b2 phase 3 trial paper — original efficacy report in NEJM, foundational to the query topic; cannot be ranked lower.",
  "flag": null
}
```

**Query: "mRNA vaccine technology for cancer"**:
```json
{
  "paper_id": "10.1056/nejmoa2032183",
  "rcs": 4,
  "reasoning": "BNT162b2 is mRNA but for COVID-19, not cancer. Tangentially relevant as a platform-validation reference but not addressing the cancer mRNA vaccine question.",
  "flag": null
}
```
