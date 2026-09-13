// normalize(raw) — port of TARGET redesign/app-1-hero.jsx (lines 19-91).
//
// Accepts two shapes:
//   (a) Raw pipeline shape — { metadata, papers, chart_data, prisma_log }
//       (matches sample-standard.json).
//   (b) Post-materialization fallback — { reportMeta, papers (with id/rcsScore
//       on a 0-1 scale), chart_data, prismaLog }.
//
// Output is always NormalizedData; downstream zones never see raw fields.

import { rcsTier, shortAuthors } from "./format"
import { getLang, t } from "./i18n"
import type {
  AuthorRef,
  ChartDataBins,
  JournalRank,
  NormalizedData,
  NormalizedPaper,
  PrismaLog,
  SearchStrategiesPayload,
} from "./types"

interface RawPaper {
  paper_id?: string
  id?: string
  title?: string
  authors_short?: string | null
  authors_full?: string[] | null
  authors?: Array<AuthorRef | { name?: string }> | null
  year?: number | null
  venue?: string | null
  doi?: string | null
  doi_url?: string | null
  abstract?: string | null
  tldr?: string | null
  rcs?: number
  rcsScore?: number
  rcs_reasoning?: string | null
  reasoning?: string | null
  rcs_flag?: string | null
  citation_count?: number
  citations?: number
  influential_citation_count?: number
  discovery_path?: string | null
  sources?: string[] | null
  is_oa?: boolean
  isOpenAccess?: boolean
  journal_rank?: JournalRank | null
  journal_rank_attribution?: string | null
}

interface RawMetadata {
  /** Legacy verbatim-request field. Never use directly as a visual title. */
  query?: string
  /**
   * Optional language-paired legacy request used only by the bilingual mock.
   * Production payloads preserve one verbatim `original_user_query`.
   */
  query_zh?: string
  original_user_query?: string
  search_topic?: string
  search_topic_zh?: string
  display_title?: string
  display_title_zh?: string
  search_id?: string
  tier?: string
  generated_at?: string
  skill_version?: string
  papers_evaluated?: number
  papers_in_kg?: number
  highly_relevant_count?: number
  closely_related_count?: number
  coverage_estimate?: number
  coverage_ci?: [number, number]
  wall_clock_total_s?: number
  stop_reason?: string | null
}

interface RawShape {
  metadata?: RawMetadata
  reportMeta?: Record<string, unknown>
  papers?: RawPaper[]
  chart_data?: ChartDataBins
  prisma_log?: PrismaLog
  prismaLog?: PrismaLog
  /** delta6 — additive: folded in by data_materialization when STEP 11.5 ran */
  search_strategies?: SearchStrategiesPayload
}

export function normalize(raw: RawShape | null | undefined): NormalizedData {
  if (!raw) {
    return {
      meta: { displayTitle: t("reportDefaultTitle") },
      papers: [],
      chartData: {},
      prismaLog: {},
    }
  }

  // (a) Raw pipeline shape — has top-level `metadata`.
  if (raw.metadata) {
    const md = raw.metadata
    const lang = getLang()
    // Keep audit identity and visual identity separate. Older payloads may
    // carry only `query`; that value is retained as the original request, but
    // it is never promoted to the H1. Missing authored titles fall back to a
    // localized neutral report name.
    const resolvedOriginalQuery =
      lang === "zh" && md.query_zh
        ? md.query_zh
        : (md.original_user_query ?? md.query)
    const resolvedSearchTopic =
      lang === "zh" && md.search_topic_zh
        ? md.search_topic_zh
        : md.search_topic
    const resolvedDisplayTitle =
      (lang === "zh" && md.display_title_zh
        ? md.display_title_zh
        : md.display_title
      )?.trim() || t("reportDefaultTitle")
    return {
      meta: {
        displayTitle: resolvedDisplayTitle,
        originalUserQuery: resolvedOriginalQuery,
        searchTopic: resolvedSearchTopic,
        query: resolvedOriginalQuery,
        searchId: md.search_id,
        tier: md.tier,
        generatedAt: md.generated_at,
        skillVersion: md.skill_version,
        papersEvaluated: md.papers_evaluated,
        papersInKg: md.papers_in_kg,
        highlyRelevant: md.highly_relevant_count,
        closelyRelated: md.closely_related_count,
        coverage: md.coverage_estimate,
        coverageCi: md.coverage_ci,
        wallClockS: md.wall_clock_total_s,
        stopReason: md.stop_reason,
      },
      papers: (raw.papers ?? [])
        .map((p): NormalizedPaper => {
          const authorsFull = p.authors_full ?? []
          const rcs = typeof p.rcs === "number" ? p.rcs : 0
          return {
            id: p.paper_id ?? p.id ?? "",
            title: p.title ?? "",
            authorsShort: shortAuthors(authorsFull),
            authorsFull,
            year: p.year ?? null,
            venue: p.venue ?? null,
            doi: p.doi ?? null,
            doiUrl: p.doi_url ?? null,
            abstract: p.abstract ?? null,
            tldr: p.tldr ?? null,
            rcs,
            rcsReasoning: p.rcs_reasoning ?? null,
            rcsFlag: p.rcs_flag ?? null,
            tier: rcsTier(rcs),
            citations: p.citation_count ?? 0,
            influentialCitations: p.influential_citation_count ?? 0,
            discoveryPath: p.discovery_path ?? null,
            sources: p.sources ?? [],
            isOpenAccess: p.is_oa,
            journalRank: p.journal_rank ?? null,
            journalRankAttribution: p.journal_rank_attribution ?? null,
          }
        })
        .sort((a, b) => b.rcs - a.rcs),
      chartData: raw.chart_data ?? {},
      prismaLog: raw.prisma_log ?? {},
      searchStrategies: raw.search_strategies ?? undefined,
    }
  }

  // (b) Post-materialization fallback — degraded path; do our best.
  const legacyMeta = (raw.reportMeta ?? {}) as Partial<NormalizedData["meta"]>
  const meta: NormalizedData["meta"] = {
    ...legacyMeta,
    displayTitle:
      (legacyMeta.displayTitle || "").trim() || t("reportDefaultTitle"),
    originalUserQuery: legacyMeta.originalUserQuery ?? legacyMeta.query,
  }
  return {
    meta,
    papers: (raw.papers ?? []).map((p): NormalizedPaper => {
      const authorObjs = (p.authors ?? []) as Array<{ name?: string }>
      const authorsFull = authorObjs
        .map((a) => (typeof a?.name === "string" ? a.name : ""))
        .filter(Boolean)
      const rawRcs =
        typeof p.rcsScore === "number" ? p.rcsScore * 10 : (p.rcs ?? 0)
      return {
        id: p.id ?? p.paper_id ?? "",
        title: p.title ?? "",
        authorsShort: shortAuthors(authorsFull),
        authorsFull,
        year: p.year ?? null,
        venue: p.venue ?? null,
        doi: p.doi ?? null,
        doiUrl: p.doi ? `https://doi.org/${p.doi}` : null,
        abstract: p.abstract ?? null,
        tldr: p.tldr ?? null,
        rcs: rawRcs,
        rcsReasoning: p.reasoning ?? p.rcs_reasoning ?? null,
        rcsFlag: null,
        tier: rcsTier(rawRcs),
        citations: p.citations ?? 0,
        influentialCitations: 0,
        discoveryPath: null,
        sources: p.sources ?? [],
        isOpenAccess: p.isOpenAccess,
        journalRank: p.journal_rank ?? null,
        journalRankAttribution: p.journal_rank_attribution ?? null,
      }
    }),
    chartData: raw.chart_data ?? {},
    prismaLog: raw.prismaLog ?? raw.prisma_log ?? {},
    searchStrategies: raw.search_strategies ?? undefined,
  }
}
