// Runtime translation dictionary + helpers.
//
// Strategy (1:1 port of delta3 redesign/i18n.jsx):
//   * Two dictionaries, `STRINGS.en` and `STRINGS.zh`, share an identical
//     set of keys. The English version is the source of truth and the
//     fallback for any key missing in another language.
//   * The Python pipeline injects `window.__REPORT_LANG__ = "zh"` (or "en")
//     into the bundle before the React app mounts. `installLanguage()` reads
//     that global once and points `window.S` at the right dictionary.
//   * Every component reads through `t('key')` (or the `(window.S||{}).key
//     || 'English fallback'` pattern in source-faithful spots), so a key
//     missing from the active dict gracefully falls back to English.
//
// Why a global `window.S` instead of React Context: per the delta3 design,
// a single mutable reference is set once at module load and used by all
// components — no provider boilerplate, no re-render on language switch
// (the bundle is rendered in one language; there is no in-app toggle).
// This also matches the design source exactly, simplifying audits.

const STRINGS = {
  en: {
    // Tabs
    findings: 'Findings', methods: 'Methods', auditLog: 'Audit log', audit: 'Audit',
    findingsRoman: 'I. Findings', methodsRoman: 'II. Methods', auditRoman: 'III. Audit log',

    // Hero
    result: 'Result', highlyRelevant: 'highly relevant', closelyRelated: 'closely related',
    papersScreened: 'papers screened', from: 'from', estimatedCoverage: 'Estimated coverage',
    coverageNote: 'Model estimates we surfaced {pct}% of the truly relevant literature for this query.',
    tier: 'Tier', tierLabel: 'tier', showAllTiers: 'Show all tiers', papersTotal: 'papers total',
    query: 'Query', est: 'Est. coverage', confidence: '95% confidence',
    discoveryReport: 'Discovery report',
    abstract: 'Abstract',
    composition: 'Composition',
    sentenceForm: 'Of {total} papers screened, {hr} are highly relevant and {cr} closely related — covering an estimated {cov}% of the field',
    abstractParagraph: 'We screened {total} papers and identified {hr} as highly relevant to the query, with {cr} additional closely-related works. A discovery-saturation model estimates that this set represents approximately {cov}%',
    ciClause: '(95% CI {lo}–{hi}%) ',
    relevanceClause: 'of the relevant literature. Relevance was scored by an LLM pass over each abstract and weighted by the local citation graph (RCS).',

    // Filter bar
    searchWithin: 'Search within results…', searchPlaceholder: 'Search…',
    rcsThreshold: 'RCS ≥', showingOf: 'Showing {n} of {total} papers',
    recommended: 'Recommended', all: 'All', list: 'List', cards: 'Cards', density: 'List density',

    // Tier labels & descriptions
    Foundational: 'Foundational', High: 'High', Moderate: 'Moderate',
    Emerging: 'Emerging', Peripheral: 'Peripheral',
    foundationalDesc: 'Field-defining; ≥0.85 RCS',
    highDesc: 'Strong relevance; 0.70–0.85',
    moderateDesc: 'Adjacent or methods; 0.55–0.70',
    emergingDesc: 'Newer or peripheral; 0.45–0.55',
    peripheralDesc: 'Surfaced but low signal; <0.45',

    // Paper row / card
    cites: 'cites', influential: '★ influential', noPapersMatch: 'No papers match these filters. Lower the RCS threshold or clear the search.',
    fieldDefining: 'field-defining', authorsUnspecified: 'Authors unspecified',

    // Detail Sheet
    tldrLabel: 'TL;DR — Semantic Scholar', whyThisPaper: 'Why this paper',
    abstractLabel: 'Abstract', authorsLabel: 'Authors', metadataLabel: 'Metadata',
    doi: 'DOI', sources: 'Sources', openAccess: 'Open access', yes: 'yes', no: 'no',
    influentialCites: 'Influential cites',
    expand: 'Expand', collapse: 'Collapse',
    copyDoi: 'Copy DOI', open: 'Open', openAtDoi: 'Open at doi.org',
    copyDoiToast: 'DOI copied to clipboard',
    navHint: '↑↓ navigate · Esc close',

    // Methods
    coverageKicker: '01 · Coverage', timeKicker: '02 · Time', qualityKicker: '03 · Quality',
    citationGraphKicker: '04 · Citation graph', topicsKicker: '05 · Topics',
    allocationKicker: '06 · Allocation', methodologyKicker: '07 · Methodology',

    discoveryCurveTitle: 'Discovery saturation curve',
    discoveryCurveSub: 'Model fit on (papers screened, highly-relevant found). The asymptote estimates the total relevant literature; coverage is our position on the curve.',
    publicationsTitle: 'Publications by year',
    publicationsSub: 'All screened papers (light) overlaid with highly-relevant (dark).',
    rcsDistTitle: 'RCS distribution',
    rcsDistSub: 'Distribution of relevance scores. Mean {mean} · 95% CI {lo}–{hi}.',
    citationScatterTitle: 'Top 50 papers by citation × year',
    citationScatterSub: 'Point area scales with RCS score. Hover any dot for paper details; click to open.',
    topicsTitle: 'Topical landscape of the screened set',
    topicsSub: 'Each block is a cluster discovered via topic modelling over title + abstract. Block area scales with the number of papers in that cluster. Click any block to open its top paper.',
    allocationTitle: 'Where the screened papers ended up',
    allocationSub: 'Distribution across the 5 RCS tiers. Width is proportional to count.',
    methodologyTitle: 'How these numbers are computed',
    methodologySub: 'Documented choices and tradeoffs. Click to expand.',

    coverageEstimate: 'Coverage estimate', estTotalRelevant: 'Est. total relevant',
    decayConstant: 'Decay constant τ', asymptote: 'Asymptote of the model',
    lowerTauHint: 'Lower τ = saturation reached faster',
    whatThisMeans: 'What this means',

    insightCoverageHigh: 'Coverage is high ({pct}%). Additional searches would have diminishing returns — this set is likely close to exhaustive for the given query and time budget.',
    insightCoverageGood: 'Coverage is good ({pct}%) but not exhaustive. Consider a deeper-tier search if you need higher recall.',
    insightCoverageModerate: 'Coverage is moderate ({pct}%). A meaningful share of relevant work is likely still undiscovered — escalate to audit tier for systematic-review use.',
    insightCoverageLow: 'Coverage is low ({pct}%). This is a scoping pass — treat results as exploratory, not exhaustive.',
    insightTime: 'Publication activity peaks at {peak} ({pkN} papers). {recentPct}% of the screened set is from 2020 onward.',
    insightQuality: 'Mean RCS {mean}. {hiN} paper{hiPlural} ({hiPct}%) scored ≥ 0.80, {loN} ({loPct}%) scored ≤ 0.20. Long tail of low-relevance papers is expected; they are surfaced for transparency.',

    rcsAccordion: 'Relevance Composite Score',
    coverageAccordion: 'Discovery saturation model',
    dedupAccordion: 'Federated deduplication strategy',
    themeAccordion: 'Topic clustering',

    paperScreened: 'papers screened', withRelevance: 'with relevance signal',
    papersAcross: 'papers across', topics: 'topics',
    largest: 'Largest', openTopPaper: 'Open top paper',
    papers: 'papers',

    // Audit
    auditTitle: 'Reproducibility audit log',
    auditSub: '16-step disclosure following PRISMA for Searching (PRISMA-S). Each step records what this run did or did not perform.',
    disclosure: 'Disclosure',
    stepsDocumented: 'PRISMA-S steps documented in this {tier} tier.',
    performed: 'Performed', notPerformed: 'Not performed', notQueried: 'Not queried',
    implicit: 'Implicit', skipped: 'Skipped',
    legendPerformed: 'Actively executed in this run',
    legendImplicit: 'Step occurred but no boolean flag',
    legendSkipped: 'Opted out for tier budget',
    whatNotPerformedTitle: 'What "not performed" means',
    whatNotPerformed: 'The {tier} tier intentionally skips deep-discovery steps (citation chasing, study registries, author contacts) to keep runtime bounded. Escalate to ',
    auditTierLink: 'audit',
    whatNotPerformedTail: ' tier to enable them.',
    none: 'none', stepWord: 'step', stepsWord: 'steps',

    auditPhaseQuery: 'Query', auditPhaseDiscovery: 'Discovery',
    auditPhaseStrategy: 'Strategy', auditPhaseAudit: 'Audit',

    // PRISMA step titles
    p_1: 'Database information', p_2: 'Multi-database searching',
    p_3: 'Study registries', p_4: 'Online resources browsing',
    p_5: 'Citation searching', p_6: 'Contacts', p_7: 'Other methods',
    p_8: 'Full search strategies', p_9: 'Limits and restrictions',
    p_10: 'Search filters', p_11: 'Prior work', p_12: 'Updates',
    p_13: 'Dates of searches', p_14: 'Total records',
    p_15: 'Deduplication', p_16: 'Record management',

    // Limitations
    caveatsKicker: 'Caveats',
    limitationsTitle: 'Interpretive limitations',
    limitationsSub: 'Read these before citing the discovery set.',
    lim1Title: 'Recall is estimated, not measured',
    lim1Body: 'Estimated coverage falls within {lo}–{hi} (95% CI). Treat this as a model estimate, not ground truth.',
    lim2Title: 'Not a PRISMA replacement',
    lim2Body: 'This report is a scoping aid. For systematic reviews you still need human full-text screening and independent reviewer agreement.',
    lim3Title: 'Coverage gaps',
    lim3Body: 'Chinese-language, humanities, grey literature, and CNKI-only content are under-represented relative to STEM English-language work.',
    lim4Title: 'LLM classification uncertainty',
    lim4Body: 'RCS scores reflect a single LLM pass over abstracts. Seminal papers with sparse abstracts may be underscored — use the force-include hint to lock specific DOIs.',

    // Settings popover
    heroLayout: 'Hero layout',
    listDensityLabel: 'List density',
    openAs: 'Open as',
    print: 'Print',
    printAction: 'Print or save as PDF',
    savedToBrowser: 'Saved to this browser.',
    settings: 'Settings',
    swissLabel: 'Grid', swissHint: 'Asymmetric grid · numeric focus',
    editorialLabel: 'Editorial', editorialHint: 'Narrow column · sentence-form finding',
    documentLabel: 'Document', documentHint: 'Centered preprint · abstract block',
    catalogLabel: 'Catalog', catalogHint: '2-line · title + TLDR + meta',
    indexLabel: 'Index', indexHint: 'Single-line columnar table',

    // Layout / density pill short labels (rendered in LayoutSwitcher trigger).
    // EN matches delta3 report-v2.html line 36-43 (Swiss → GRID rename);
    // ZH matches delta3 report-v2-zh.html line 49-55.
    swissShort: 'GRID', editorialShort: 'EDITORIAL', documentShort: 'DOCUMENT',
    catalogShort: 'CATALOG', indexShort: 'INDEX',

    // PRISMA-S note canonical-string → translated full-sentence (used by
    // summarizeValueV2 + renderValueV2 noteMap in audit-utils). Keys originally
    // referenced inside delta3 v2-audit.jsx without being shipped in
    // delta3/i18n.jsx — added here so the English bundle has a stable
    // pass-through value and the Chinese bundle gets the proper translation.
    pv_openalex_polite: 'OpenAlex polite pool + Semantic Scholar (supplement). Audit may add PubMed/arXiv.',
    pv_multidb_rationale: 'Multi-database search reduces single-source bias (Bramer 2018: 98.3% recall achievable with >=2 databases).',
    pv_study_registries: 'Not queried by default. Available via audit tier add-ons if user enables Cochrane/ClinicalTrials.',
    pv_online_resources: 'Out of scope for this skill; pre-supplied via user citation seeds when relevant.',
    pv_citation_search: 'OpenAlex forward+backward citation chase up to configured max_hops.',
    pv_contacts: 'Skill does not contact authors; relies on published records only.',
    pv_full_strategy: 'Strategy reproducible; same boolean expressions executed against each database.',
    pv_no_filters: 'No restrictive filters by default; tier budget bounds the number of records returned.',
    pv_no_hedges: 'No pre-validated hedges used; query plan uses LLM-decomposed terms.',
    pv_force_include: 'User-supplied force_include DOIs (config force_include) are merged into the result set.',
    pv_not_incremental: 'Not incremental within a single run; checkpoint enables manual re-run on demand.',
    pv_dedup_method: 'FederatedKG dedup: DOI (Level 1) -> arXiv ID (Level 2) -> PMID/OpenAlex/SS fallback -> (normalized_title, year) (last resort). E5b guard prevents same-title-different-DOI collapse.',
    pv_provenance: 'Provenance preserved per paper in sources[].',
    pv_queries: '{n} queries',
    pv_outputs: '{n} outputs',
    pv_records_screened: '{n} records screened',

    // PRISMA-S detail-cell field labels — lowercased mono caps in the detail
    // panel. Keys originally referenced inside delta3 v2-audit.jsx without
    // being shipped in delta3/i18n.jsx.
    fl_primary: 'Primary',
    fl_databases: 'databases',

    // Audit row labels (English-only versions of badges that need translation).
    audPerformedShort: 'Performed',
    audNotQueriedShort: 'Not queried',
    audSkippedShort: 'Skipped',

    // Caveat / limitations container — section header
    interpretiveLimitations: 'Interpretive limitations',
    readBeforeCiting: 'Read these before citing the discovery set.',
    prismaS: 'PRISMA-S',

    // Audit print button extra labels
    printOrPdf: 'Print or save as PDF',
  
    // Extras added in second sweep — keys originally only in zh; English
    // fallbacks added here so TS type inference (Strings = typeof STRINGS.en)
    // covers them and components can safely use t('key').
    filter: 'Filter',
    alsoAvailable: 'Also available',
    alsoAvailableInFolder: 'Also available in this folder:',
    selfContained: 'Self-contained · offline-capable · single file',
    docWeScreened: 'We screened ',
    docPapersAndIdentified: ' papers and identified ',
    docAsHighlyRelevant: ' as highly relevant to the query, with ',
    docAdditional: ' additional closely-related works.',
    docModelEstimates: ' A discovery-saturation model estimates that this set represents approximately ',
    docRelevanceClause: '% of the relevant literature. Relevance was scored by an LLM pass over each abstract and weighted by the local citation graph (RCS).',
    sentenceOf: 'Of ',
    papersScreenedShort: ' papers screened, ',
    areHighlyRelevant: 'are highly relevant',
    closelyRelatedCovering: 'closely related — covering an estimated',
    ofTheField: 'of the field',
    topicNotAvailable: 'Topic clustering not available for this run.',

    // Charts axis & hint labels
    yearArrow: 'year →',
    citesLog: '↑ cites (log)',
    noData: 'No data',
    clickToOpenDetail: 'Click to open detail →',

    // Methodology accordion bullets — pair label + suffix text
    foundationalBullet: 'RCS ≥ 0.85 · field-defining works',
    highBullet: '0.70 ≤ RCS < 0.85 · directly relevant',
    moderateBullet: '0.55 ≤ RCS < 0.70 · adjacent / methods',
    emergingBullet: '0.45 ≤ RCS < 0.55 · newer or peripheral',
    peripheralBullet: 'RCS < 0.45 · surfaced but low signal',
    tierCutoffs: 'Tier cutoffs:',
    rcsExplain: "Each candidate paper is scored 0–10 by an LLM pass over its title and abstract. The score is then weighted by the paper's position in the local citation graph (PageRank over within-set citations) to reward bibliographically central works.",
    coverageExplain: 'We fit the observed (papers screened, highly-relevant found) trajectory to the model y(n) = R · (1 - e^(-n/τ)); the asymptote R is our estimate of the total relevant literature, and coverage = y(n)/R. The 95% CI reflects model parameter uncertainty, not a ground-truth boundary.',
    dedupExplain: 'Papers from multiple sources (OpenAlex / Semantic Scholar / Crossref / PubMed / arXiv) are merged in four passes: Level 1 DOI exact match → Level 2 arXiv ID → Level 3 PMID / OpenAlex / SS ID fallback → Level 4 normalized-title + year. The sources of each paper are preserved in its sources[] array.',
    themeExplain: 'Themes are derived via BERTopic over concatenated title + abstract, with minimum cluster size 4 papers and manual label refinement.',

    // Threshold labels for RCS histogram footer
    periphShort: 'Periph',
    emergShort: 'Emerg',
    modShort: 'Mod',
    highShort: 'High',
    foundShort: 'Found',
    foundPlus: 'Found 0.85+',

    // Sheet nav titles
    prevTitle: 'Previous (k)',
    nextTitle: 'Next (j)',
    closeTitle: 'Close (Esc)',

    // Settings popover button titles
    settingsBtnTitle: 'Settings',
    settingsAndFilesTitle: 'Settings & files',
    printBtnTitle: 'Print or save as PDF (⌘P)',
    current: 'current',
    loading: 'Loading…',

    // Method tab titles (also covers some title= attrs on Cards)
    whatThisRunDid: 'What this run did',
    discoveryCurveSummary: 'Estimated to have found about {found} relevant papers, approximately {pct}% of the relevant set (95% CI: {lo}–{hi}%).',
  },

  zh: {
    findings: '文献结果', methods: '方法', auditLog: '审计日志', audit: '审计',
    // ASCII period after Roman numerals (academic convention) — NOT full-width 。
    // The Roman numerals themselves are language-neutral notation, so the
    // period that abbreviates them must remain ASCII regardless of UI locale.
    findingsRoman: 'I. 文献结果', methodsRoman: 'II. 方法', auditRoman: 'III. 审计日志',

    result: '结果', highlyRelevant: '高相关', closelyRelated: '密切相关',
    papersScreened: '篇文献已筛选', from: '共筛选', estimatedCoverage: '估算覆盖率',
    coverageNote: '模型估算本次检索已覆盖该查询全部相关文献的 {pct}%。',
    tier: '相关性档', tierLabel: '档级', showAllTiers: '显示所有档', papersTotal: '篇总计',
    query: '查询', est: '估算覆盖率', confidence: '95% 置信',
    discoveryReport: '检索报告',
    abstract: '摘要',
    composition: '档级分布',
    sentenceForm: '在筛选的 {total} 篇文献中，{hr} 篇高相关，{cr} 篇密切相关 —— 覆盖该领域约 {cov}% 的文献',
    abstractParagraph: '本次检索筛选了 {total} 篇文献，识别出 {hr} 篇高度相关、{cr} 篇密切相关的成果。基于检索饱和模型估算，本结果集覆盖了相关文献的约 {cov}%',
    ciClause: '(95% CI {lo}–{hi}%) ',
    relevanceClause: '。相关性由 LLM 基于摘要打分并结合局部引用图加权(RCS)。',

    searchWithin: '在结果内搜索…', searchPlaceholder: '搜索…',
    rcsThreshold: 'RCS ≥', showingOf: '显示 {n} / {total} 篇',
    recommended: '推荐', all: '全部', list: '列表', cards: '卡片', density: '列表密度',

    Foundational: '奠基性', High: '高相关', Moderate: '中等相关',
    Emerging: '新兴/边缘', Peripheral: '外围',
    foundationalDesc: '领域定义性文献 · ≥0.85 RCS',
    highDesc: '高度相关 · 0.70–0.85',
    moderateDesc: '相邻或方法类 · 0.55–0.70',
    emergingDesc: '较新或边缘 · 0.45–0.55',
    peripheralDesc: '已检索但信号弱 · <0.45',

    cites: '次引用', influential: '★ 高影响力引用',
    noPapersMatch: '没有文献符合当前筛选条件。降低 RCS 阈值或清除搜索词。',
    fieldDefining: '领域定义性', authorsUnspecified: '作者信息未提供',

    tldrLabel: '一句话摘要 · Semantic Scholar', whyThisPaper: '为何收录这篇',
    abstractLabel: '摘要', authorsLabel: '作者', metadataLabel: '元数据',
    doi: 'DOI', sources: '数据源', openAccess: '开放获取', yes: '是', no: '否',
    influentialCites: '高影响力引用',
    expand: '展开', collapse: '收起',
    copyDoi: '复制 DOI', open: '打开', openAtDoi: '在 doi.org 打开',
    copyDoiToast: 'DOI 已复制到剪贴板',
    navHint: '↑↓ 导航 · Esc 关闭',

    coverageKicker: '01 · 覆盖率', timeKicker: '02 · 时间分布', qualityKicker: '03 · 质量分布',
    citationGraphKicker: '04 · 引用图谱', topicsKicker: '05 · 主题分布',
    allocationKicker: '06 · 档级分配', methodologyKicker: '07 · 方法说明',

    discoveryCurveTitle: '检索饱和曲线',
    discoveryCurveSub: '基于"已筛选篇数 / 已发现高相关数"拟合的曲线。渐近线估算全部相关文献总量，覆盖率即当前所处位置。',
    publicationsTitle: '年度发表分布',
    publicationsSub: '所有已筛文献(浅色)叠加显示高相关(深色)。',
    rcsDistTitle: 'RCS 分布',
    rcsDistSub: '相关性得分分布。均值 {mean} · 95% CI {lo}–{hi}。',
    citationScatterTitle: '引用 × 年份(Top 50)',
    citationScatterSub: '点面积按 RCS 缩放。悬停查看详情，点击打开论文。',
    topicsTitle: '检索结果的主题图景',
    topicsSub: '每个方块表示一个由主题模型聚类(基于标题 + 摘要)发现的簇，面积按该簇文献数缩放。点击方块打开代表性论文。',
    allocationTitle: '已筛文献的最终归属',
    allocationSub: '在 5 个 RCS 档级上的分布，宽度与数量成正比。',
    methodologyTitle: '这些数字是怎么算出来的',
    methodologySub: '已记录的关键选择与权衡。点击展开。',

    coverageEstimate: '估算覆盖率', estTotalRelevant: '估算相关总量',
    decayConstant: '衰减常数 τ', asymptote: '模型渐近线',
    lowerTauHint: 'τ 越小 = 饱和越快达到',
    whatThisMeans: '这意味着什么',

    insightCoverageHigh: '覆盖率高({pct}%)。继续检索的边际收益递减 —— 在给定查询和时间预算下，本结果集已接近穷尽。',
    insightCoverageGood: '覆盖率良好({pct}%)但尚未穷尽。如需更高召回，可启用更深档级的检索。',
    insightCoverageModerate: '覆盖率中等({pct}%)。仍有相当比例的相关文献可能未被发现 —— 系统综述用途建议升级到 audit 档级。',
    insightCoverageLow: '覆盖率较低({pct}%)。本次为探索性检索 —— 结果应作为初步参考，非穷尽。',
    insightTime: '发表活动峰值在 {peak} 年({pkN} 篇)。已筛集中 {recentPct}% 为 2020 年及以后发表。',
    insightQuality: '平均 RCS {mean}。{hiN} 篇({hiPct}%)得分 ≥ 0.80，{loN} 篇({loPct}%)得分 ≤ 0.20。低相关文献长尾属于预期 —— 出于透明性也予以呈现。',

    rcsAccordion: '相关性综合评分 (RCS)',
    coverageAccordion: '检索饱和模型',
    dedupAccordion: '联合去重策略',
    themeAccordion: '主题聚类',

    paperScreened: '篇已筛选', withRelevance: '有相关性信号',
    papersAcross: '篇 · 覆盖', topics: '个主题',
    largest: '最大', openTopPaper: '打开代表性论文',
    papers: '篇',

    auditTitle: '可复现性审计日志',
    auditSub: '按 PRISMA-S(PRISMA for Searching)规范的 16 步披露。每一步记录本次运行执行或未执行的内容。',
    disclosure: '披露',
    stepsDocumented: '本次 {tier} 档级运行已记录的 PRISMA-S 步骤数。',
    performed: '已执行', notPerformed: '未执行', notQueried: '未查询',
    implicit: '隐式', skipped: '已跳过',
    legendPerformed: '本次运行主动执行',
    legendImplicit: '步骤实际发生但无布尔标记',
    legendSkipped: '档级预算下主动跳过',
    whatNotPerformedTitle: '"未执行"是什么意思',
    whatNotPerformed: '{tier} 档级会主动跳过深度发现步骤(引用追溯、研究注册库、作者联系等)以控制运行时间。如需启用，请升级到 ',
    auditTierLink: 'audit',
    whatNotPerformedTail: ' 档级。',
    none: '无', stepWord: '步', stepsWord: '步',

    auditPhaseQuery: '查询', auditPhaseDiscovery: '发现',
    auditPhaseStrategy: '策略', auditPhaseAudit: '审计',

    p_1: '数据库信息', p_2: '多数据库检索',
    p_3: '研究注册库', p_4: '在线资源浏览',
    p_5: '引用检索', p_6: '作者联系', p_7: '其他方法',
    p_8: '完整检索策略', p_9: '限制与排除',
    p_10: '检索过滤器', p_11: '前期工作', p_12: '增量更新',
    p_13: '检索日期', p_14: '记录总数',
    p_15: '去重', p_16: '记录管理',

    caveatsKicker: '注意事项',
    limitationsTitle: '解读限制',
    limitationsSub: '在引用本结果集前请阅读以下限制。',
    lim1Title: '召回率为估算值，非实测',
    lim1Body: '估算覆盖率落在 {lo}–{hi}(95% CI)。这是模型估计，而非真实事实。',
    lim2Title: '不能替代 PRISMA',
    lim2Body: '本报告为检索范围探查工具。系统综述仍需人工全文筛查与独立审稿人一致性核对。',
    lim3Title: '覆盖盲区',
    lim3Body: '中文文献、人文学科、灰色文献以及 CNKI 独家内容相对于英语 STEM 类工作存在显著欠覆盖。',
    lim4Title: 'LLM 分类不确定性',
    lim4Body: 'RCS 得分基于一次 LLM 摘要扫描。摘要稀疏的开创性论文可能被低估 —— 可使用 force-include 锁定具体 DOI。',

    heroLayout: '顶部布局',
    listDensityLabel: '列表密度',
    openAs: '其他格式',
    print: '打印',
    printAction: '打印或保存为 PDF',
    savedToBrowser: '设置保存在此浏览器。',
    settings: '设置',
    swissLabel: '网格式', swissHint: '非对称网格 · 数字主导',
    editorialLabel: '编辑式', editorialHint: '窄栏单列 · 一句话陈述结果',
    documentLabel: '学术式', documentHint: '居中文档 · 摘要段落',
    catalogLabel: '目录式', catalogHint: '两行紧凑 · 标题 + TLDR + 元数据',
    indexLabel: '索引式', indexHint: '单行表格 · 列式',

    // Layout / density pill short labels — ZH from delta3 report-v2-zh.html
    swissShort: '网格', editorialShort: '编辑', documentShort: '学术',
    catalogShort: '目录', indexShort: '索引',

    // PRISMA-S note canonical-string → ZH full-sentence (audit noteMap)
    pv_openalex_polite: 'OpenAlex polite pool + Semantic Scholar(补充)。审计档级可追加 PubMed/arXiv。',
    pv_multidb_rationale: '多数据库检索可降低单源偏倚(Bramer 2018: ≥2 个数据库可达 98.3% 召回)。',
    pv_study_registries: '默认不查询。审计档级如启用 Cochrane/ClinicalTrials 可补充。',
    pv_online_resources: '本 Skill 不在范围内；如有用户提供的引用种子则按需补充。',
    pv_citation_search: 'OpenAlex 前向 + 后向引用追溯，最多 max_hops 跳。',
    pv_contacts: '本 Skill 不联系作者，仅依据已发表记录。',
    pv_full_strategy: '检索策略可复现；同一布尔表达式对每个数据库执行。',
    pv_no_filters: '默认不施加限制性过滤；由档级预算限定返回记录数。',
    pv_no_hedges: '未使用预验证的检索 hedges;查询计划由 LLM 拆解词项生成。',
    pv_force_include: '用户提供的 force_include DOI 已合并入结果集。',
    pv_not_incremental: '单次运行内不增量；通过 checkpoint 支持按需重跑。',
    pv_dedup_method: 'FederatedKG 去重: DOI(Level 1) → arXiv ID(Level 2) → PMID/OpenAlex/SS 兜底 → (标题归一化 + 年份)(末级)。E5b 守卫避免同标题异 DOI 折叠。',
    pv_provenance: '每篇论文在 sources[] 中保留溯源。',
    pv_queries: '{n} 条查询',
    pv_outputs: '{n} 项输出',
    pv_records_screened: '已筛 {n} 条记录',

    // PRISMA-S detail-cell field labels — ZH
    fl_primary: '主要',
    fl_databases: '数据库',

    // Audit row badges
    audPerformedShort: '已执行',
    audNotQueriedShort: '未查询',
    audSkippedShort: '已跳过',

    // Caveat / limitations container
    interpretiveLimitations: '解读限制',
    readBeforeCiting: '在引用本结果集前请阅读以下限制。',
    prismaS: 'PRISMA-S',

    // Audit print button labels
    printOrPdf: '打印或保存为 PDF',

    // Extras added in second sweep
    filter: '筛选',
    alsoAvailable: '其他格式',
    alsoAvailableInFolder: '同目录下另有:',
    selfContained: '单文件 · 可离线打开',
    docWeScreened: '本次检索筛选了 ',
    docPapersAndIdentified: ' 篇文献，识别出 ',
    docAsHighlyRelevant: ' 篇高相关成果，另有 ',
    docAdditional: ' 篇密切相关。',
    docModelEstimates: ' 基于检索饱和模型估算，本结果集覆盖了相关文献的约 ',
    docRelevanceClause: '%。相关性由 LLM 基于摘要打分并结合局部引用图加权(RCS)。',
    sentenceOf: '在筛选的 ',
    papersScreenedShort: ' 篇文献中，',
    areHighlyRelevant: '为高相关',
    closelyRelatedCovering: '密切相关 — 覆盖该领域约',
    ofTheField: '的文献',
    topicNotAvailable: '本次运行未进行主题聚类。',

    // Charts axis & hint labels
    yearArrow: '年份 →',
    citesLog: '↑ 引用(对数)',
    noData: '无数据',
    clickToOpenDetail: '点击查看详情 →',

    // Methodology accordion bullets — pair label + suffix text
    foundationalBullet: 'RCS ≥ 0.85 · 领域定义性文献',
    highBullet: '0.70 ≤ RCS < 0.85 · 直接相关',
    moderateBullet: '0.55 ≤ RCS < 0.70 · 相邻或方法类',
    emergingBullet: '0.45 ≤ RCS < 0.55 · 较新或边缘',
    peripheralBullet: 'RCS < 0.45 · 已检索但信号弱',
    tierCutoffs: '档级阈值:',
    rcsExplain: '每篇候选论文先由 LLM 基于标题+摘要打 0–10 分，再结合局部引用图的 PageRank 加权，优先突出学术中心位置的工作。',
    coverageExplain: '我们将"已筛选 / 已发现高相关"轨迹拟合到模型 y(n) = R · (1 − e^(−n/τ));渐近线 R 即对相关文献总量的估计，覆盖率 = y(n)/R。95% 置信区间反映模型参数不确定性，而非真实事实边界。',
    dedupExplain: '多数据源(OpenAlex / Semantic Scholar / Crossref / PubMed / arXiv)按四级合并:Level 1 DOI 精确匹配 → Level 2 arXiv ID → Level 3 PMID/OpenAlex/SS ID 兜底 → Level 4 标题归一化 + 年份。同一论文的来源在 sources[] 数组中保留溯源。',
    themeExplain: '主题由 BERTopic 基于"标题 + 摘要"聚类生成，最小簇大小为 4 篇，聚类后手工精修标签。',

    // Threshold labels for RCS histogram footer
    periphShort: '外围', emergShort: '新兴', modShort: '中等', highShort: '高',
    foundShort: '奠基', foundPlus: '奠基 0.85+',

    // Sheet nav titles
    prevTitle: '上一篇 (k)',
    nextTitle: '下一篇 (j)',
    closeTitle: '关闭 (Esc)',

    // Settings popover button title
    settingsBtnTitle: '设置',
    settingsAndFilesTitle: '设置 & 文件',
    printBtnTitle: '打印或保存为 PDF (⌘P)',
    current: '当前',
    loading: '加载中…',

    // Method tab titles (also covers some title= attrs on Cards)
    whatThisRunDid: '本次运行做了什么',
    discoveryCurveSummary: '估算已发现约 {found} 篇相关论文，约占相关集合的 {pct}%(95% CI: {lo}–{hi}%)。',
  },
}

// `as const` is intentionally NOT applied to STRINGS — we want widened
// `string` types so that en and zh (which share keys but hold different
// literal values) both satisfy `Strings`. Otherwise typeof STRINGS.en and
// typeof STRINGS.zh become unrelated literal-union types and TS rejects
// `window.S = STRINGS.zh`.
export type Strings = { readonly [K in keyof typeof STRINGS.en]: string }
export type LangCode = "en" | "zh"

// Augment global Window so TS knows about our injected fields.
declare global {
  interface Window {
    /** Active translation dictionary. Mutated by `installLanguage()`. */
    S?: Strings
    /** Set by Python pipeline before bundle execution. */
    __REPORT_LANG__?: LangCode
    /** Full dictionary map, exposed for debugging and ad-hoc inspection. */
    STRINGS?: typeof STRINGS
    /** Convenience helper. */
    fmtStr?: typeof fmtStr
  }
}

/**
 * Format a template with `{placeholder}` substitutions.
 * - Missing variables leave the placeholder in place (`{n}` stays `{n}`).
 * - Numbers and booleans are coerced to strings.
 */
export function fmtStr(
  template: string | undefined,
  vars?: Record<string, string | number | boolean | null | undefined>,
): string {
  if (!template) return ""
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (_, k) =>
    vars[k] !== undefined && vars[k] !== null ? String(vars[k]) : `{${k}}`,
  )
}

/**
 * Install the active dictionary on `window.S` based on `window.__REPORT_LANG__`
 * (set by Python injection) or an explicit override. Idempotent — safe to call
 * multiple times. Must be called BEFORE any component reads `window.S`.
 *
 * Default = English. Unknown lang codes fall back to English with a console warn.
 */
export function installLanguage(override?: LangCode): LangCode {
  if (typeof window === "undefined") return "en"
  const lang: LangCode =
    override ||
    (window.__REPORT_LANG__ === "zh" || window.__REPORT_LANG__ === "en"
      ? window.__REPORT_LANG__
      : "en")
  if (lang !== "en" && lang !== "zh") {
    // eslint-disable-next-line no-console
    console.warn(`[i18n] unknown lang code "${lang}", falling back to en`)
    window.S = STRINGS.en
    return "en"
  }
  window.S = STRINGS[lang]
  // Expose for debugging + ad-hoc grep
  window.STRINGS = STRINGS
  window.fmtStr = fmtStr
  return lang
}

/**
 * Lookup helper with English fallback. Components that don't want to write
 * the verbose `(window.S||{}).key || "fallback"` pattern can use `t('key')`
 * — but the fallback semantics are identical: missing key returns the English
 * literal from `STRINGS.en`.
 */
export function t<K extends keyof Strings>(
  key: K,
  vars?: Record<string, string | number | boolean | null | undefined>,
): string {
  const dict: Strings = (typeof window !== "undefined" && window.S) || STRINGS.en
  const tmpl = (dict[key] as string | undefined) || (STRINGS.en[key] as string)
  return vars ? fmtStr(tmpl, vars) : tmpl
}

/**
 * Direct accessor for the active dict. Useful in places where the component
 * needs to feed a translated string to another component as a string prop
 * (rather than computing it inline).
 */
export function getS(): Strings {
  return (typeof window !== "undefined" && window.S) || STRINGS.en
}

/**
 * Read the active language code at any time. Useful for non-component code
 * paths (like normalize.ts) that need to pick between language-paired
 * fields without going through `t()`. Returns "en" when window is absent
 * or `__REPORT_LANG__` is unset/invalid.
 */
export function getLang(): LangCode {
  if (typeof window === "undefined") return "en"
  return window.__REPORT_LANG__ === "zh" ? "zh" : "en"
}

export { STRINGS }
