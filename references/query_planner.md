# Query Planner

*This file is read by the main agent in STEP 1 of `SKILL.md` to convert a user request into 1-3 search strategies before retrieving anything. Choose the framework based on query intent — applying the wrong framework wastes a strategy slot.*

## Framework selection

| Framework | When to use | Outputs |
|-----------|-------------|---------|
| **PICO** | Clinical / quantitative comparison ("does X improve outcome Y vs Z?") | 4 concept blocks: P, I, C, O |
| **SPIDER** | Qualitative or mixed-method ("how do people experience X?") | 5 concept blocks: S, PI, D, E, R |
| **PEO** | Scoping / observational ("what is the relationship between exposure and outcome?") | 3 concept blocks: P, E, O |
| **Open-ended** | Curiosity / theory / non-clinical ("what research exists on X") | 2-4 concept blocks with synonyms |

## PICO — Population, Intervention, Comparator, Outcome

Use for: drug trials, behavioral interventions, surgical comparisons, dietary studies, anything with a hypothesized causal effect.

| Block | Question |
|-------|----------|
| **Population** | Who is studied? (e.g. "adults ≥18 with type 2 diabetes") |
| **Intervention** | What is given? (e.g. "metformin 500-2000mg/day") |
| **Comparator** | Compared to? (placebo / sulfonylurea / standard care / nothing) |
| **Outcome** | Measured how? (HbA1c reduction, weight loss, adverse events) |

**Example 1 — diabetes RCT search**:
- P: "adults" OR "type 2 diabetes" OR "T2D"
- I: "metformin"
- C: ("placebo" OR "sulfonylurea" OR "standard care") — often omit for OpenAlex (too restrictive)
- O: ("HbA1c" OR "glycemic control") AND ("RCT" OR "randomized")
- Combined: `metformin AND "type 2 diabetes" AND ("HbA1c" OR "glycemic control") AND ("RCT" OR "randomized")`

**Example 2 — IBS dietary intervention** (audit-tier from SKILL.md Example 4):
- P: "adults" + "IBS" + "irritable bowel syndrome"
- I: "low-FODMAP" OR "fiber" OR "dietary"
- C: any control
- O: "symptom severity" + "quality of life" + "abdominal pain"

**Example 3 — telehealth elderly hypertension**:
- P: "elderly" OR "older adults" OR "geriatric"
- I: "telehealth" OR "telemedicine" OR "remote monitoring"
- C: "in-person" OR "usual care"
- O: "blood pressure" OR "hypertension control"

## SPIDER — Sample, Phenomenon of Interest, Design, Evaluation, Research type

Use for: qualitative studies, mixed methods, user-experience research, psychological phenomena.

| Block | Question |
|-------|----------|
| **Sample** | Who? (less rigid than PICO P) |
| **Phenomenon of Interest** | What is being studied? (experience, attitude, perception) |
| **Design** | How? (interviews, focus groups, ethnography, surveys) |
| **Evaluation** | What outcomes? (themes, attitudes, satisfaction) |
| **Research type** | Qualitative / quantitative / mixed |

**Example — attachment + HRI in elderly care** (from SKILL.md Example 3):
- S: "elderly" + "older adults" + "long-term care residents"
- PI: "attachment" + "human-robot interaction" + "companion robot"
- D: ("interview" OR "ethnography" OR "case study" OR "RCT")
- E: "loneliness" + "wellbeing" + "social bonding"
- R: qualitative + quantitative (don't filter)

## PEO — Population, Exposure, Outcome

Use for: epidemiology, observational studies, environmental health, lifestyle factors. Lighter than PICO when there's no intervention.

| Block | Question |
|-------|----------|
| **Population** | Cohort being observed |
| **Exposure** | Factor being studied (not assigned) |
| **Outcome** | Measured endpoint |

**Example — air pollution + cognitive decline**:
- P: "older adults" OR "aging population" OR "60+"
- E: "PM2.5" OR "air pollution" OR "particulate matter"
- O: "cognitive decline" OR "dementia" OR "Alzheimer's" OR "MMSE"

## Open-ended — concept block + synonym expansion

When the user's intent is exploratory ("what research exists on prospect theory?" "find papers about working memory training"), drop the structured framework and just extract concept blocks.

**Steps**:
1. Identify 2-4 core concepts in the query
2. For each, list 2-5 synonyms / acronyms / related terms
3. Combine via OR within block, AND across blocks

**Example — "working memory training in elderly"**:
- Concept 1 — working memory: `("working memory" OR "WM" OR "executive function" OR "cognitive training")`
- Concept 2 — training: `(training OR intervention OR program OR exercise)`
- Concept 3 — elderly: `(elderly OR "older adults" OR aging OR geriatric OR "65+")`
- Combined: `(working memory OR cognitive training) AND (training OR intervention) AND (elderly OR older adults)`

## Multi-strategy combination (when to use multiple strategies)

For Standard+ tiers, run 2-3 strategies. Each strategy targets a different angle:

| Strategy | Use for | OpenAlex helper CLI |
|----------|---------|---------------------|
| **By citation** | High-cited classics + foundational work | `openalex_helper deep "<q>" --sort cited_by_count:desc` |
| **By recency** | Latest published in the area | `openalex_helper deep "<q>" --sort publication_date:desc` |
| **By relevance** | Best topical match | `openalex_helper deep "<q>" --sort relevance_score:desc` |
| **By seminal year cutoff** | Classics only (pre-2015) | `openalex_helper seminal "<topic>" --year-max 2015` |
| **By review type** | Existing reviews on the topic | `openalex_helper reviews "<topic>"` |
| **By topic ID** | OpenAlex topic ID (when known) | (no CLI; programmatic only — `Works().filter(topics__id=...)`) |
| **By journal whitelist** | Top venues only | `openalex_helper journal-list "<q>" --preset Cochrane|UTD24|...` |

For Audit tier, also add journal whitelist (e.g. `Cochrane`, `medical_top`).

The `double-sort` CLI does strategies 1/2/3 automatically and boosts rank when a paper appears in ≥ 2 strategies — this is the recommended default for Standard+.

## Cross-language query handling (中英混合)

When the user writes in Chinese or mixes Chinese + English, expand both directions:

| Chinese term | English mapping |
|--------------|-----------------|
| 工作记忆 | working memory |
| 工作记忆训练 | working memory training |
| 老年人 / 老年 | elderly / older adults / aging |
| 干预 | intervention |
| 综述 | review / literature review |
| 元分析 / 荟萃分析 | meta-analysis |
| 随机对照试验 | randomized controlled trial / RCT |
| 临床试验 | clinical trial |
| 认知训练 | cognitive training |
| 注意力 | attention |
| 抑郁 | depression |
| 焦虑 | anxiety |
| 心理治疗 | psychotherapy |
| 神经影像 | neuroimaging |

**Rule**: in your search query, use the **English** terms (OpenAlex indexes English-language metadata most reliably). Keep Chinese in your understanding of the user's intent but translate before retrieval. Mention this to the user in one sentence: *"I'll search in English since 'working memory training' has more OpenAlex coverage than '工作记忆训练'."*

## Year filter heuristics

- Specific year range (e.g. "2010-2024"): use `year_min` / `year_max`
- "Recent" / "latest" (no year): default `year_min = current_year - 5`
- "Last decade": `year_min = current_year - 10`
- "Classics": no year filter, sort by citation_count
- Audit tier: respect user's explicit `IC: 2010-present` etc.
- Quick tier without year: no filter, sort relevance

## Anti-patterns

- Don't filter by `language=english` at the OpenAlex level — too restrictive, drops Chinese-Japanese-Korean studies that have English abstracts.
- Don't add `AND "human"` to medical queries — half the relevant papers don't have "human" in title/abstract; rely on OpenAlex topic clustering instead.
- Don't combine more than 4 AND blocks — recall craters. If you have 5+ concepts, split into 2 strategies and merge.
