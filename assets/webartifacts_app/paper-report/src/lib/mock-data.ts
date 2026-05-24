// MOCK_RAW — fallback dataset used when no window.__REPORT_DATA__ is injected.
//
// Shape matches the raw pipeline output (sample-standard.json schema):
//   { metadata, papers, chart_data, prisma_log }
//
// Theme: "Working memory training in older adults" — chosen so the data feels
// real (it is the kind of query the Skill is built to answer) without
// pulling the entire 696 KB sample-standard fixture into the bundle.

export const MOCK_RAW = {
  metadata: {
    search_id: "mock_20260522_wm_training_older_adults",
    query:
      "Working memory training in older adults — transfer effects, neural plasticity, and longitudinal RCT evidence",
    // `query_zh` paired translation — used by normalize() when window.__REPORT_LANG__
    // is "zh" (set by Python `--language zh` in real runs, or by bundle-zh-preview.html
    // for local preview). Real production payloads never set this; their `query`
    // field already carries the user's original-language text. Demo-only mechanism
    // so mock data previews coherently under either UI language.
    query_zh:
      "老年人工作记忆训练 — 迁移效应、神经可塑性与纵向 RCT 证据",
    tier: "standard",
    wall_clock_total_s: 412,
    papers_evaluated: 187,
    papers_in_kg: 142,
    highly_relevant_count: 12,
    closely_related_count: 24,
    coverage_estimate: 0.91,
    coverage_ci: [0.83, 0.96],
    generated_at: "2026-05-22T10:14:08.523000",
    skill_version: "paper-search-pro/2.0",
    stop_reason: null,
  },

  papers: [
    // --- Foundational (rcs >= 9) — 3 papers
    {
      paper_id: "10.1126/science.1230579",
      title:
        "Putting Brain Training to the Test: Adaptive Working Memory Training in Healthy Older Adults",
      authors_short: "Owen et al.",
      authors_full: [
        "Adrian M. Owen",
        "Adam Hampshire",
        "Jessica A. Grahn",
        "Robert Stenton",
        "Said Dajani",
        "Alistair S. Burns",
      ],
      year: 2014,
      venue: "Science",
      doi: "10.1126/science.1230579",
      doi_url: "https://doi.org/10.1126/science.1230579",
      abstract:
        "Cognitive training has been touted as a means to slow age-related decline. We report a large-scale, multi-site, adaptive working memory training trial with 11,430 older adults randomized to one of three intervention arms and a no-contact control. Adaptive n-back training produced robust gains on the trained task but did not transfer to untrained tests of working memory, fluid reasoning, or everyday function over a six-month follow-up.",
      tldr:
        "Working memory training improves the trained task but does not produce far transfer to other cognitive abilities in healthy older adults.",
      rcs: 10,
      rcs_reasoning:
        "Field-defining adaptive WM training RCT in older adults (Science, n=11,430). The canonical null-transfer reference cited in every meta-analysis since 2014.",
      rcs_flag: null,
      citation_count: 1842,
      influential_citation_count: 187,
      discovery_path: "seed",
      sources: ["openalex", "semantic_scholar"],
      is_oa: true,
    },
    {
      paper_id: "10.1037/a0028228",
      title:
        "The cognitive plasticity of adaptive working memory training: a meta-analysis",
      authors_short: "Melby-Lervåg & Hulme",
      authors_full: ["Monica Melby-Lervåg", "Charles Hulme"],
      year: 2013,
      venue: "Developmental Psychology",
      doi: "10.1037/a0028228",
      doi_url: "https://doi.org/10.1037/a0028228",
      abstract:
        "We meta-analyzed 23 studies of adaptive working memory training across the lifespan. Effects on the trained tasks were large and reliable; near-transfer effects to similar untrained tasks were small; and far-transfer effects to fluid reasoning, attention control, or academic achievement were not detectable after correcting for active-control comparison and selective reporting.",
      tldr:
        "WM training reliably improves the trained task but produces no detectable far transfer once active controls and reporting bias are accounted for.",
      rcs: 9,
      rcs_reasoning:
        "The canonical meta-analysis of WM training transfer; required reading for any review and cited in every subsequent transfer debate.",
      rcs_flag: null,
      citation_count: 1410,
      influential_citation_count: 142,
      discovery_path: "seed",
      sources: ["openalex"],
      is_oa: false,
    },
    {
      paper_id: "10.1073/pnas.0801268105",
      title:
        "Improving fluid intelligence with training on working memory",
      authors_short: "Jaeggi et al.",
      authors_full: [
        "Susanne M. Jaeggi",
        "Martin Buschkuehl",
        "John Jonides",
        "Walter J. Perrig",
      ],
      year: 2008,
      venue: "PNAS",
      doi: "10.1073/pnas.0801268105",
      doi_url: "https://doi.org/10.1073/pnas.0801268105",
      abstract:
        "We trained young adults on a dual n-back working memory task and observed dose-dependent gains on Raven's Advanced Progressive Matrices, a measure of fluid intelligence (Gf). Improvements scaled with training duration across four groups (8, 12, 17, and 19 days).",
      tldr:
        "Adaptive n-back training improved fluid intelligence in a dose-dependent fashion in young adults.",
      rcs: 9,
      rcs_reasoning:
        "The original positive-transfer claim that catalyzed the entire WM-training literature; foundational regardless of subsequent replication failures.",
      rcs_flag: "Original positive claim — replication-contested",
      citation_count: 2103,
      influential_citation_count: 264,
      discovery_path: "seed",
      sources: ["openalex", "semantic_scholar"],
      is_oa: true,
    },

    // --- High (7 <= rcs < 8.5) — 3 papers
    {
      paper_id: "10.1037/a0029082",
      title:
        "Is working memory training effective? A meta-analytic review",
      authors_short: "Shipstead, Redick, & Engle",
      authors_full: [
        "Zach Shipstead",
        "Thomas S. Redick",
        "Randall W. Engle",
      ],
      year: 2012,
      venue: "Psychological Bulletin",
      doi: "10.1037/a0029082",
      doi_url: "https://doi.org/10.1037/a0029082",
      abstract:
        "We critically reviewed published evaluations of working memory training programs. We found weak support for transfer to general fluid abilities; most apparently-supportive studies suffered from passive-control designs and weak measurement of the construct purportedly transferred-to.",
      tldr:
        "WM training shows weak evidence of transfer; many positive studies are confounded by methodological choices.",
      rcs: 8,
      rcs_reasoning:
        "Influential critical methodological review of the early WM-training literature; central in any high-tier discussion of construct validity.",
      rcs_flag: null,
      citation_count: 901,
      influential_citation_count: 75,
      discovery_path: "openalex_search",
      sources: ["openalex"],
      is_oa: false,
    },
    {
      paper_id: "10.1037/a0035144",
      title:
        "The role of individual differences in cognitive training and transfer",
      authors_short: "Jaeggi, Buschkuehl, Shah, & Jonides",
      authors_full: [
        "Susanne M. Jaeggi",
        "Martin Buschkuehl",
        "Priti Shah",
        "John Jonides",
      ],
      year: 2014,
      venue: "Memory & Cognition",
      doi: "10.1037/a0035144",
      doi_url: "https://doi.org/10.1037/a0035144",
      abstract:
        "Across four training studies, we examined how baseline performance, motivation, expectancy, and personality predict cognitive training gains and transfer. Individual differences accounted for substantial variance in transfer outcomes, suggesting one-size-fits-all training is unlikely to succeed.",
      tldr:
        "Transfer depends heavily on individual differences in baseline performance, motivation, and expectations.",
      rcs: 8,
      rcs_reasoning:
        "Pivotal paper reframing the transfer debate around moderators; highly cited in the contemporary individual-differences turn of the field.",
      rcs_flag: null,
      citation_count: 487,
      influential_citation_count: 42,
      discovery_path: "openalex_search",
      sources: ["openalex", "semantic_scholar"],
      is_oa: true,
    },
    {
      paper_id: "10.1016/j.tics.2013.05.009",
      title:
        "Working memory training in healthy older adults: a longitudinal MRI study",
      authors_short: "Brehmer, Westerberg, & Bäckman",
      authors_full: ["Yvonne Brehmer", "Helena Westerberg", "Lars Bäckman"],
      year: 2013,
      venue: "Trends in Cognitive Sciences",
      doi: "10.1016/j.tics.2013.05.009",
      doi_url: "https://doi.org/10.1016/j.tics.2013.05.009",
      abstract:
        "We followed 80 healthy older adults across 5 weeks of adaptive WM training plus a 6-month follow-up. Behavioral gains were accompanied by changes in fronto-parietal activation patterns measured with fMRI, suggesting neural correlates of training-related plasticity.",
      tldr:
        "WM training in older adults produces both behavioral and fronto-parietal neural changes that persist 6 months.",
      rcs: 7,
      rcs_reasoning:
        "Directly on-target longitudinal MRI study; combines the neural plasticity and transfer themes asked by the query.",
      rcs_flag: null,
      citation_count: 318,
      influential_citation_count: 28,
      discovery_path: "openalex_search",
      sources: ["openalex"],
      is_oa: false,
    },

    // --- Moderate (5.5 <= rcs < 7) — 3 papers
    {
      paper_id: "10.1037/a0030986",
      title:
        "Mediators of training-related transfer: a five-month randomized trial in older adults",
      authors_short: "Karbach et al.",
      authors_full: [
        "Julia Karbach",
        "Maximilian Mang",
        "Jutta Kray",
      ],
      year: 2015,
      venue: "Psychology and Aging",
      doi: "10.1037/a0030986",
      doi_url: "https://doi.org/10.1037/a0030986",
      abstract:
        "We tested 120 older adults (60-80y) in a 5-month adaptive WM training RCT against an active control. Modest near-transfer effects emerged for tasks tapping similar processing demands; far transfer to everyday function was not detected.",
      tldr:
        "WM training in older adults yields modest near transfer but not far transfer to daily function.",
      rcs: 6,
      rcs_reasoning:
        "Sound longitudinal RCT that informs the moderate-effect range debate; adjacent rather than central to the canonical foundational set.",
      rcs_flag: null,
      citation_count: 156,
      influential_citation_count: 12,
      discovery_path: "openalex_search",
      sources: ["openalex"],
      is_oa: false,
    },
    {
      paper_id: "10.1037/aap0000094",
      title:
        "Active versus passive control comparisons in cognitive training research",
      authors_short: "Boot, Simons, & Stothart",
      authors_full: [
        "Walter R. Boot",
        "Daniel J. Simons",
        "Cary Stothart",
        "Cassie Stutts",
      ],
      year: 2013,
      venue: "Perspectives on Psychological Science",
      doi: "10.1037/aap0000094",
      doi_url: "https://doi.org/10.1037/aap0000094",
      abstract:
        "We argue that placebo-control deficits explain a substantial portion of apparent transfer effects in the cognitive training literature, including studies on WM training. We outline minimum design standards to disentangle real training effects from expectancy and demand effects.",
      tldr:
        "Many reported training transfer effects may reflect placebo effects rather than genuine cognitive change.",
      rcs: 6,
      rcs_reasoning:
        "Influential methodological critique relevant to interpreting most WM training findings; not on-query directly but consequential.",
      rcs_flag: null,
      citation_count: 612,
      influential_citation_count: 51,
      discovery_path: "citation_search",
      sources: ["semantic_scholar"],
      is_oa: false,
    },
    {
      paper_id: "10.3389/fnagi.2014.00063",
      title:
        "Computerized cognitive training in healthy older adults: a systematic review and meta-analysis",
      authors_short: "Lampit, Hallock, & Valenzuela",
      authors_full: [
        "Amit Lampit",
        "Harry Hallock",
        "Michael Valenzuela",
      ],
      year: 2014,
      venue: "Frontiers in Aging Neuroscience",
      doi: "10.3389/fnagi.2014.00063",
      doi_url: "https://doi.org/10.3389/fnagi.2014.00063",
      abstract:
        "We meta-analyzed 51 RCTs of computerized cognitive training in healthy older adults (mean age 71). Small-to-moderate effect sizes emerged across multiple cognitive domains including WM. Effects were stronger for training that was supervised, of moderate intensity, and delivered <3 sessions per week.",
      tldr:
        "Computerized cognitive training in older adults yields small-to-moderate gains; supervision and moderate dose matter.",
      rcs: 6,
      rcs_reasoning:
        "On-target meta-analysis in older adults specifically; provides effect-size benchmarks for the moderate-effect range.",
      rcs_flag: null,
      citation_count: 542,
      influential_citation_count: 41,
      discovery_path: "openalex_search",
      sources: ["openalex"],
      is_oa: true,
    },

    // --- Emerging (4.5 <= rcs < 5.5) — 2 papers
    {
      paper_id: "10.1038/nrn3884",
      title:
        "Aging, cognitive reserve, and the architecture of working memory",
      authors_short: "Reuter-Lorenz & Park",
      authors_full: [
        "Patricia A. Reuter-Lorenz",
        "Denise C. Park",
      ],
      year: 2014,
      venue: "Nature Reviews Neuroscience",
      doi: "10.1038/nrn3884",
      doi_url: "https://doi.org/10.1038/nrn3884",
      abstract:
        "We review the architecture of working memory across the adult lifespan and consider how cognitive reserve interacts with training-related plasticity. We outline a scaffolding theory linking compensation processes to potential intervention targets.",
      tldr:
        "Cognitive reserve and scaffolding processes shape who benefits from WM training in late life.",
      rcs: 5,
      rcs_reasoning:
        "Adjacent theoretical review on WM architecture and aging; relevant context but not direct intervention evidence.",
      rcs_flag: null,
      citation_count: 423,
      influential_citation_count: 18,
      discovery_path: "citation_search",
      sources: ["openalex"],
      is_oa: false,
    },
    {
      paper_id: "10.1037/0894-4105.22.5.567",
      title:
        "Working memory and aging: a review of the literature on capacity, complexity, and control",
      authors_short: "Park & Reuter-Lorenz",
      authors_full: ["Denise C. Park", "Patricia A. Reuter-Lorenz"],
      year: 2008,
      venue: "Neuropsychology",
      doi: "10.1037/0894-4105.22.5.567",
      doi_url: "https://doi.org/10.1037/0894-4105.22.5.567",
      abstract:
        "We review behavioral and neuroimaging evidence on age-related changes in WM capacity, processing complexity, and cognitive control. We propose specific interfaces where targeted intervention could rebuild lost capacity.",
      tldr:
        "Aging alters WM capacity and control; specific interfaces may be the targets for intervention.",
      rcs: 5,
      rcs_reasoning:
        "Older theoretical review of WM aging; useful context but not on the intervention/RCT axis the query emphasizes.",
      rcs_flag: null,
      citation_count: 287,
      influential_citation_count: 14,
      discovery_path: "citation_search",
      sources: ["openalex"],
      is_oa: false,
    },

    // --- Peripheral (rcs < 4.5) — 1 paper
    {
      paper_id: "10.1038/nature11704",
      title:
        "Visual short-term memory and the operation of attention",
      authors_short: "Vogel & Awh",
      authors_full: ["Edward K. Vogel", "Edward Awh"],
      year: 2012,
      venue: "Nature",
      doi: "10.1038/nature11704",
      doi_url: "https://doi.org/10.1038/nature11704",
      abstract:
        "We review the literature on visual short-term memory and its interaction with selective attention. We argue that VSTM capacity reflects flexible attentional weighting rather than fixed storage slots.",
      tldr:
        "VSTM capacity is shaped by attentional weighting rather than fixed slots.",
      rcs: 4,
      rcs_reasoning:
        "Surfaced via citation snowballing; mostly about young-adult VSTM mechanisms — peripheral to the older-adults intervention query.",
      rcs_flag: null,
      citation_count: 198,
      influential_citation_count: 9,
      discovery_path: "citation_search",
      sources: ["semantic_scholar"],
      is_oa: false,
    },
  ],

  chart_data: {
    publication_year: {
      bins: [
        { year: 2008, total: 4, highly_relevant: 1 },
        { year: 2009, total: 6, highly_relevant: 0 },
        { year: 2010, total: 8, highly_relevant: 0 },
        { year: 2011, total: 9, highly_relevant: 0 },
        { year: 2012, total: 14, highly_relevant: 1 },
        { year: 2013, total: 18, highly_relevant: 2 },
        { year: 2014, total: 23, highly_relevant: 3 },
        { year: 2015, total: 21, highly_relevant: 1 },
        { year: 2016, total: 19, highly_relevant: 1 },
        { year: 2017, total: 16, highly_relevant: 0 },
        { year: 2018, total: 14, highly_relevant: 1 },
        { year: 2019, total: 11, highly_relevant: 1 },
        { year: 2020, total: 9, highly_relevant: 0 },
        { year: 2021, total: 7, highly_relevant: 1 },
        { year: 2022, total: 4, highly_relevant: 0 },
        { year: 2023, total: 3, highly_relevant: 0 },
        { year: 2024, total: 1, highly_relevant: 0 },
      ],
      year_min: 2008,
      year_max: 2024,
    },
    relevance_score: {
      bins: [
        { rcs: 0, count: 28 },
        { rcs: 1, count: 22 },
        { rcs: 2, count: 18 },
        { rcs: 3, count: 21 },
        { rcs: 4, count: 19 },
        { rcs: 5, count: 17 },
        { rcs: 6, count: 14 },
        { rcs: 7, count: 11 },
        { rcs: 8, count: 8 },
        { rcs: 9, count: 5 },
        { rcs: 10, count: 4 },
      ],
      mean: 4.5,
      ci_low: 3.1,
      ci_high: 5.8,
      n: 167,
    },
    discovery_curve: {
      tau: 24.3,
      coverage_estimate: 0.91,
      ci_low: 0.83,
      ci_high: 0.96,
      estimated_total_relevant: 13.5,
      summary:
        "Saturation reached by ~150 screened papers; remaining yield is < 1 highly-relevant paper per 25 screened.",
      points: [
        { papers_screened: 10, found: 2 },
        { papers_screened: 25, found: 4 },
        { papers_screened: 50, found: 7 },
        { papers_screened: 80, found: 9 },
        { papers_screened: 110, found: 10 },
        { papers_screened: 140, found: 11 },
        { papers_screened: 170, found: 12 },
        { papers_screened: 187, found: 12 },
      ],
    },
    citation_network: {
      nodes: [
        {
          id: "10.1126/science.1230579",
          year: 2014,
          citation_count: 1842,
          rcs: 10,
          title:
            "Putting Brain Training to the Test",
          authors_short: "Owen et al.",
          venue: "Science",
        },
        {
          id: "10.1037/a0028228",
          year: 2013,
          citation_count: 1410,
          rcs: 9,
          title: "Cognitive plasticity meta-analysis",
          authors_short: "Melby-Lervåg & Hulme",
          venue: "Developmental Psychology",
        },
        {
          id: "10.1073/pnas.0801268105",
          year: 2008,
          citation_count: 2103,
          rcs: 9,
          title: "Improving fluid intelligence",
          authors_short: "Jaeggi et al.",
          venue: "PNAS",
        },
        {
          id: "10.1037/a0029082",
          year: 2012,
          citation_count: 901,
          rcs: 8,
          title: "Is WM training effective?",
          authors_short: "Shipstead et al.",
          venue: "Psychological Bulletin",
        },
        {
          id: "10.1037/a0035144",
          year: 2014,
          citation_count: 487,
          rcs: 8,
          title: "Individual differences in training",
          authors_short: "Jaeggi et al.",
          venue: "Memory & Cognition",
        },
        {
          id: "10.1016/j.tics.2013.05.009",
          year: 2013,
          citation_count: 318,
          rcs: 7,
          title: "Longitudinal MRI study",
          authors_short: "Brehmer et al.",
          venue: "Trends in Cognitive Sciences",
        },
        {
          id: "10.1037/a0030986",
          year: 2015,
          citation_count: 156,
          rcs: 6,
          title: "Mediators of training transfer",
          authors_short: "Karbach et al.",
          venue: "Psychology and Aging",
        },
        {
          id: "10.1037/aap0000094",
          year: 2013,
          citation_count: 612,
          rcs: 6,
          title: "Active vs passive controls",
          authors_short: "Boot et al.",
          venue: "Perspectives on Psychological Science",
        },
        {
          id: "10.3389/fnagi.2014.00063",
          year: 2014,
          citation_count: 542,
          rcs: 6,
          title: "Meta-analysis of computerized training",
          authors_short: "Lampit et al.",
          venue: "Frontiers in Aging Neuroscience",
        },
        {
          id: "10.1038/nrn3884",
          year: 2014,
          citation_count: 423,
          rcs: 5,
          title: "Cognitive reserve and WM",
          authors_short: "Reuter-Lorenz & Park",
          venue: "Nature Reviews Neuroscience",
        },
        {
          id: "10.1037/0894-4105.22.5.567",
          year: 2008,
          citation_count: 287,
          rcs: 5,
          title: "WM and aging review",
          authors_short: "Park & Reuter-Lorenz",
          venue: "Neuropsychology",
        },
        {
          id: "10.1038/nature11704",
          year: 2012,
          citation_count: 198,
          rcs: 4,
          title: "VSTM and attention",
          authors_short: "Vogel & Awh",
          venue: "Nature",
        },
      ],
      node_count: 12,
      edge_count: 0,
    },
    // Topic clusters (delta2 change 5, 2026-05-24). Matches the shape emitted by
    // `scripts/data_materialization.py::_build_themes()`: each theme has
    // a title-cased `name`, a `value` (paper count), and `paper_ids` (top-N
    // DOIs of papers in that cluster). Slice-and-dice carves the largest
    // cluster off as a full-edge strip so the visual hierarchy is obvious.
    theme_treemap: {
      themes: [
        {
          name: "Working Memory Training",
          value: 6,
          paper_ids: [
            "10.1126/science.1230579",
            "10.1037/a0028228",
            "10.1073/pnas.0801268105",
          ],
        },
        {
          name: "Cognitive Plasticity",
          value: 4,
          paper_ids: ["10.1037/a0029082", "10.1037/a0035144"],
        },
        {
          name: "Older Adults Cognition",
          value: 3,
          paper_ids: ["10.1037/0882-7974.16.4.529"],
        },
        {
          name: "Meta Analysis",
          value: 3,
          paper_ids: ["10.1037/a0028228"],
        },
        {
          name: "Fluid Intelligence",
          value: 2,
          paper_ids: ["10.1073/pnas.0801268105"],
        },
        {
          name: "N-Back Tasks",
          value: 2,
          paper_ids: ["10.1073/pnas.0801268105"],
        },
      ],
      total_papers: 12,
    },
  },

  prisma_log: {
    "1_database_information": {
      databases: ["openalex", "semantic_scholar"],
      primary: "OpenAlex",
      note:
        "OpenAlex polite pool + Semantic Scholar (supplement). PubMed not queried at standard tier.",
    },
    "2_multi_database_searching": {
      performed: true,
      rationale:
        "Two databases queried in parallel to reduce single-source bias (Bramer 2018).",
      databases: ["openalex", "semantic_scholar"],
    },
    "3_study_registries": {
      queried: false,
      note:
        "Not queried at standard tier. Available via audit-tier add-on (Cochrane, ClinicalTrials.gov).",
    },
    "4_online_resources_browsing": {
      performed: false,
      rationale:
        "Skipped at standard tier; included in audit tier when grey-literature surfacing is required.",
    },
    "5_citation_searching": {
      performed: true,
      method: "forward + backward via OpenAlex referenced_works / cited_by",
      depth: 2,
      seeds: 3,
    },
    "6_contacts": {
      performed: false,
      note: "Author/expert contact not part of automated pipeline.",
    },
    "7_other_methods": {
      methods: ["LLM-assisted query expansion", "iterative re-ranking"],
      note:
        "Two passes of LLM expansion produced 14 additional queries; final relevance scoring used a single Sonnet 4 pass.",
    },
    "8_full_search_strategies": {
      queries: [
        "working memory training older adults RCT",
        "n-back training transfer aging",
        "cognitive training fluid intelligence elderly",
        "computerized brain training older adults systematic review",
      ],
      query_count: 4,
    },
    "9_limits_and_restrictions": {
      filters_applied: ["year:>=2008", "lang:en", "type:article OR review"],
      rationale:
        "Year floor reflects post-Jaeggi-2008 inflection in WM training literature.",
    },
    "10_search_filters": {
      filters_applied: ["peer-reviewed", "English"],
      note: "Preprints from arXiv not included at standard tier.",
    },
    "11_prior_work": {
      performed: true,
      tool: "OpenAlex citation graph",
      seeds: 3,
      rationale:
        "Seeded with canonical Owen 2014, Melby-Lervåg 2013, and Jaeggi 2008 to anchor the snowball.",
    },
    "12_updates": {
      performed: false,
      note:
        "Single-shot run. Re-run scheduling not part of standard tier; available via audit tier.",
    },
    "13_dates_of_searches": {
      search_date: "2026-05-22",
      cutoff: "2026-05-20",
    },
    "14_total_records": {
      records_screened: 187,
      records_in_kg: 142,
      highly_relevant: 12,
      closely_related: 24,
    },
    "15_deduplication": {
      performed: true,
      tool: "DOI + title cosine similarity (≥ 0.92)",
      duplicates_removed: 23,
    },
    "16_record_management": {
      format: "JSON + HTML report",
      outputs_produced: ["report.html", "papers.json", "audit_log.json"],
      search_id: "mock_20260522_wm_training_older_adults",
    },
  },
}
