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
- P (population): "adults" OR "adult"
- Condition: "type 2 diabetes" OR "T2D" OR "T2DM" — *a disease is a separate concept from the population; AND across blocks, never OR into P (see `search_export/methodology.md` §2.1)*
- I: "metformin"
- C: ("placebo" OR "sulfonylurea" OR "standard care") — often omit for OpenAlex (too restrictive)
- O: "HbA1c" OR "glycemic control"
- Study design: attach a **validated** RCT filter (Cochrane HSSS) on Boolean-library export — see `search_export/filters_library.md`. *Never self-author a `("RCT" OR "randomized")` filter — a two-word text filter misses trials whose title/abstract omit those words (methodology §4.2).*
- Combined: `("adults" OR "adult") AND ("type 2 diabetes" OR "T2D") AND metformin AND ("HbA1c" OR "glycemic control")` — append the validated RCT filter when exporting to PubMed/Ovid.

**Example 2 — IBS dietary intervention** (audit-tier from SKILL.md Example 4):
- P (population): "adults" OR "adult"
- Condition: "IBS" OR "irritable bowel syndrome" — *disease is its own block, AND'd with population*
- I: "low-FODMAP" OR "fiber" OR "dietary"
- C: any control
- O: "symptom severity" OR "quality of life" OR "abdominal pain"

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
- S: "elderly" OR "older adults" OR "long-term care residents"
- PI (phenomenon): "attachment" OR "bonding"
- PI (technology): "human-robot interaction" OR "companion robot" OR "social robot" — *the psychological phenomenon and the technology are distinct concepts → AND across, not OR within one block (methodology §2.1)*
- D: "interview" OR "ethnography" OR "case study" OR "RCT"
- E: "loneliness" OR "wellbeing" OR "social bonding"
- R: qualitative or quantitative — don't filter (mixed-method)

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
- Concept 1 — working memory (object): `("working memory" OR "WM" OR "executive function")`
- Concept 2 — training (intervention): `(training OR intervention OR program OR exercise OR "cognitive training")` — *"cognitive training" is an intervention, not a cognitive object; it belongs in the training block, not Concept 1 (methodology §2.1)*
- Concept 3 — elderly: `(elderly OR "older adults" OR aging OR geriatric OR "65+")`
- Combined: `("working memory" OR "executive function") AND (training OR intervention OR "cognitive training") AND (elderly OR "older adults")`

## Multi-strategy combination (when to use multiple strategies)

For Standard+ tiers, run 2-3 strategies. Each strategy targets a different angle:

| Strategy | Use for | OpenAlex helper CLI |
|----------|---------|---------------------|
| **By citation** | High-cited classics + foundational work | `openalex_helper deep "<q>" --sort cited_by_count:desc` |
| **By recency** | Most relevant work of the last year, then the two years before | `double-sort`'s recent leg (or `search --recent N`) — not `deep --sort publication_date:desc`, which returns the newest title/abstract matches in date order, relevant or not |
| **By relevance** | Best topical match | `openalex_helper deep "<q>" --sort relevance_score:desc` |
| **By seminal year cutoff** | Classics only (pre-2015) | `openalex_helper seminal "<topic>" --year-max 2015` |
| **By review type** | Existing reviews on the topic | `openalex_helper reviews "<topic>"` |
| **By topic ID** | OpenAlex topic ID (when known) | (no CLI; programmatic only — `Works().filter(topics__id=...)`) |
| **By journal whitelist** | Top venues only | `openalex_helper journal-list "<q>" --preset Cochrane|UTD24|...` |

For Audit tier, also add journal whitelist (e.g. `Cochrane`, `medical_top`).

The `double-sort` CLI does strategies 1/2/3 automatically and boosts rank when a paper appears in ≥ 2 strategies — this is the recommended default for Standard+.

## Cross-language query handling (中英混合 — search_language-aware)

**The language *space* is decided before you get here.** Axis 2 of the three-axis model — `search_language` ∈ `en | zh | both | auto` — is resolved earlier in **STEP 1** (the search-language-space sub-step, whose SSOT is `source_routing.md` §"Language scope"; priority: per-query flags > in-query markers > config > `auto`-then-ask), *before* you phrase the query here. (STEP 2 then routes supplemental sources *within* the fixed space — it does not decide the space either.) By the time you plan the query the space is a concrete one of **en / zh / both**. This section only says how to *phrase* the query once the space is known — it does not decide the space.

The CN→EN table below is the **English-side expansion vocabulary**: it applies whenever the English space is in play (space `en`, or the English half of `both`). It is never a mandate to translate Chinese away when the space is `zh`.

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

**Phrasing rule by space:**

- **`en` space — and the `auto`→en branch, which is the default for every English query:** in your search query, use the **English** terms (OpenAlex indexes English-language metadata most reliably). Keep Chinese in your understanding of the user's intent but translate before retrieval. Mention this to the user in one sentence: *"I'll search in English since 'working memory training' has more OpenAlex coverage than '工作记忆训练'."* **This branch is byte-for-byte the v2.2 behavior (R-19)** — a pure-English query never leaves it, and a Chinese query only reaches it when the space resolved to `en`.
- **`zh` space:** do **NOT** translate. Keep the **Chinese terms** as the retrieval query — OpenAlex has a multilingual base and NSSD/yiigle consume Chinese directly. You may still normalise wording (strip stopwords, split into concept blocks) but the retrieval terms stay Chinese. The CN→EN table is not applied here.
- **`both` space:** build **two** query sets — one English (per the `en` rule) and one Chinese (per the `zh` rule) — and run each in its own space; STEP 5 federates the union. The PRISMA-S logger already records multiple strategy sets, so both are logged.

**Markers that selected the space are not search terms.** Phrases that routed the space (`CSSCI`, `中文文献`, `SSCI`, `知网`, …) are filter/routing conditions — strip them from the topic before retrieval, exactly like `rank_intent` strips "中科院一区" (see `source_routing.md` §"Language scope"). Searching for the literal string "CSSCI" would return papers *about* CSSCI, not papers *on* your topic.

## How OpenAlex reads a query

This decides recall more than any other choice in STEP 1, and it fails silently.

- **Every bare word is required.** `short video college students attention concentration` means short AND video AND college AND students AND attention AND concentration. Synonyms written as words therefore *exclude* each paper that uses only one of them.
- **Write concept blocks: synonyms in OR, blocks in AND, phrases in quotes.** `("short video" OR "short-form video" OR TikTok OR Douyin) AND (attention OR concentration OR procrastination)`. Two or three blocks for retrieval; exports to Boolean libraries can carry more (`search_export/methodology.md`).
- **Leave the population / setting block out of at least one strategy.** "college students" drops every paper that says "young adults" or "undergraduates"; the classifier can judge the population afterwards.
- **Keep generic words out of OR groups** (interest, effect, use, role, development, exploration). One of them in a block lets thousands of loosely related papers match and buries the ones you want.
- The search matches title, abstract and — where OpenAlex has it — full text. The cited and recent legs match title and abstract only, so a well-formed query matters most there.

| Measured 2026-10-01, a user's own searches | Title+abstract matches in the window | Known on-topic papers retrieved |
|---|---|---|
| `short-form video use college university students attention attentional control sustained attention concentration` (11 bare words, 2021–26) | 1 | 2 of 6 |
| `("short video" OR "short-form video" OR TikTok OR Douyin) AND (attention OR attentional OR concentration OR procrastination OR burnout)` | 5,014 | 4 of 6 |
| `curiosity interest epistemic emotions development children` (2025–26) | 1 | 0 of 3 |
| `(curiosity OR "epistemic emotion" OR "information seeking") AND (child OR children OR infant OR infants OR toddler)` | 2,220 | 2 of 3 |

The OpenAlex helpers print a warning for six or more bare terms without OR, and STEP 3's `count` says when fewer than 30 works match — both mean: restructure before classifying. arXiv also requires every bare word (the helper sends `all:` terms); OpenReview does not parse Boolean syntax, so its helper sends the words alone.

## Year filter heuristics

When to ask and what to say: SKILL.md STEP 1 "Time scope". The windows:

- Specific range ("2010-2024", "近两年", "2023 年以后"): `year_min` / `year_max`; relative ranges count back from the current year
- "Recent" / "最新" with no number: ask (or use `config.recent_years`); never silently assume five years
- "Last decade": `year_min = current_year - 10`
- "Classics": no year filter; add `seminal`
- Nothing said: no year filter at any tier. The recent leg (double-sort, or `search --recent` at Quick) still brings the last year and the two years before, so new work is present without a window
- Audit tier: respect the protocol's explicit `IC: 2010-present` etc.

Why a window alone is not enough: relevance ranking leans on citations, so inside a five-year window the relevance leg still favours the oldest years. The recent leg is what finds this year's papers.

## Anti-patterns

- Don't filter by `language=english` at the OpenAlex level — too restrictive, drops Chinese-Japanese-Korean studies that have English abstracts.
- Don't add `AND "human"` to medical queries — half the relevant papers don't have "human" in title/abstract; rely on OpenAlex topic clustering instead.
- Don't combine more than 4 AND blocks — recall craters. Bare words count as blocks: see "How OpenAlex reads a query". If you have 5+ concepts, split into 2 strategies and merge. **This ceiling is an OpenAlex relevance-engine heuristic, not a Boolean-library rule** — Boolean-library exports routinely AND 5–8 concept blocks (see `search_export/methodology.md` §2.2); do not inherit this ≤4 cap when exporting a professional search string, and it does not constrain the 5-block SPIDER example above.
