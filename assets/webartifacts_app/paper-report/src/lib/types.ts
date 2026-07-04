// Domain types for the normalized report data consumed by every zone.
//
// Two upstream shapes feed `normalize()`:
//   (a) Raw shape — what the Python pipeline (or sample-standard.json) emits:
//       { metadata, papers (with authors_full / paper_id / rcs as 0-10 int),
//         chart_data, prisma_log }
//   (b) Post-materialization shape — what the previous TEMPLATE used internally:
//       { reportMeta, papers (with id / rcsScore as 0-1 float), chart_data,
//         prismaLog }
//
// All downstream components consume only `NormalizedData`.

export type Tier =
  | "Foundational"
  | "High"
  | "Moderate"
  | "Emerging"
  | "Peripheral"

export interface NormalizedMeta {
  query?: string
  searchId?: string
  /** 'quick' | 'standard' | 'deep' | 'audit' */
  tier?: string
  generatedAt?: string
  skillVersion?: string
  papersEvaluated?: number
  papersInKg?: number
  highlyRelevant?: number
  closelyRelated?: number
  /** 0-1 fraction */
  coverage?: number
  /** [low, high] both 0-1 fractions */
  coverageCi?: [number, number]
  wallClockS?: number
  stopReason?: string | null
}

export interface AuthorRef {
  name: string
  affiliation?: string
}

// Multi-platform journal partition / rank (delta5). Mirrors the Python
// `rank_filter.rank_metric_dict` SSOT shape emitted by
// data_materialization._journal_rank_render(). Every platform sub-object is
// nullable (a journal may match on some platforms and not others); the whole
// `journalRank` is null/absent when the paper matched no platform. R-04: only
// `jcr.impact_factor` is a true Impact Factor — CAS/SJR are partitions only.
export interface CasRank {
  tier: number
  rank?: string | null
  top?: boolean
  minor?: Array<{ category: string; tier: number; rank?: string | null }>
  source_year?: number | null
}
export interface JcrRank {
  quartile: string
  impact_factor?: number | null
  rank?: string | null
  category?: string | null
  source_year?: number | null
}
export interface SjrRank {
  best_quartile: string
  sjr?: number | null
  per_category?: Array<{ category: string; quartile: string }>
  source_year?: number | null
}
export interface OpenAlexImpact {
  mean_citedness_2yr?: number | null
  h_index?: number | null
}
export interface JournalRank {
  cas?: CasRank | null
  jcr?: JcrRank | null
  sjr?: SjrRank | null
  openalex?: OpenAlexImpact | null
  matched_issn?: string | null
  matched_platforms?: string[]
}

export interface NormalizedPaper {
  id: string
  title: string
  /** Display-only short form ("Smith et al."); null when no authors */
  authorsShort: string | null
  authorsFull: string[]
  year: number | null
  venue: string | null
  doi: string | null
  doiUrl: string | null
  abstract: string | null
  tldr: string | null
  /** 0-10 integer (raw shape) or 0-10 number (post-mat); fmtRcs divides by 10 */
  rcs: number
  rcsReasoning: string | null
  rcsFlag: string | null
  tier: Tier
  citations: number
  influentialCitations: number
  discoveryPath: string | null
  /** Provenance source identifiers, e.g. "openalex", "semantic_scholar" */
  sources: string[]
  isOpenAccess?: boolean
  /** Multi-platform journal partition (delta5); null when no platform matched */
  journalRank?: JournalRank | null
  /** Legally-required attribution string for whichever platforms matched */
  journalRankAttribution?: string | null
}

export interface YearBin {
  year: number
  total: number
  highly_relevant: number
}

export interface RcsBin {
  rcs: number
  count: number
}

export interface DiscoveryCurvePoint {
  papers_screened: number
  found: number
}

export interface DiscoveryCurve {
  /** Decay constant of the saturation fit (lower → faster saturation) */
  tau: number
  /** 0-1 fraction */
  coverage_estimate: number
  /** 0-1 fraction */
  ci_low: number
  /** 0-1 fraction */
  ci_high: number
  estimated_total_relevant: number
  summary?: string
  points?: DiscoveryCurvePoint[]
}

export interface CitationNetworkNode {
  id: string
  year: number
  /** Some pipelines emit `citation_count`, older fixtures `count` */
  citation_count: number
  rcs: number
  title: string
  authors_short?: string
  venue?: string
  doi_url?: string
  is_seed?: boolean
}

export interface CitationNetworkEdge {
  source: string
  target: string
  [key: string]: unknown
}

export interface CitationNetwork {
  nodes: CitationNetworkNode[]
  edges?: CitationNetworkEdge[]
  node_count?: number
  edge_count?: number
}

// Per-theme tile in the treemap. Matches the shape emitted by
// `scripts/data_materialization.py::_build_themes()`: each theme has a
// human-readable `name` (title-cased keyword), a `value` (paper count in
// the cluster), and `paper_ids` (DOIs/internal ids of papers in the
// cluster, top-N). The `[key: string]: unknown` index signature stays so
// future Python schema extensions don't require a TS sync.
export interface ThemeTreemapNode {
  name: string
  value: number
  paper_ids?: string[]
  [key: string]: unknown
}

export interface ThemeTreemap {
  themes: ThemeTreemapNode[]
  total_papers?: number
}

export interface ChartDataBins {
  publication_year?: {
    bins: YearBin[]
    year_min?: number
    year_max?: number
  }
  relevance_score?: {
    bins: RcsBin[]
    mean?: number
    ci_low?: number
    ci_high?: number
    n?: number
  }
  discovery_curve?: DiscoveryCurve
  citation_network?: CitationNetwork
  theme_treemap?: ThemeTreemap
}

/** PRISMA step values are open-shape — every step keeps different fields */
export type PrismaStepValue = Record<string, unknown>

/** Keyed by '1_database_information' ... '16_record_management' (+ '_meta') */
export type PrismaLog = Record<string, PrismaStepValue>

export interface NormalizedData {
  meta: NormalizedMeta
  papers: NormalizedPaper[]
  chartData: ChartDataBins
  prismaLog: PrismaLog
}
