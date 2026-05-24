// Port of TARGET v2-methods.jsx useInsights (209-245).
// Returns auto-extracted plain-language captions for the Coverage / Time /
// Quality sections, computed from chart data + meta.

import { useMemo } from "react"

import { t } from "@/lib/i18n"
import type {
  CitationNetworkNode,
  DiscoveryCurve,
  NormalizedData,
  RcsBin,
  YearBin,
} from "@/lib/types"

export interface UseInsightsArgs {
  data: NormalizedData
  yearBins: YearBin[]
  rcsBins: RcsBin[]
  rcsMean?: number
  dc?: DiscoveryCurve
  nodes: CitationNetworkNode[]
}

export interface Insights {
  coverage?: string
  time?: string
  quality?: string
}

export function useInsights({
  data,
  yearBins,
  rcsBins,
  rcsMean,
  dc,
  nodes,
}: UseInsightsArgs): Insights {
  return useMemo(() => {
    const out: Insights = {}

    if (dc) {
      const c = dc.coverage_estimate
      const pct = Math.round(c * 100)
      if (c >= 0.95) {
        out.coverage = t("insightCoverageHigh", { pct })
      } else if (c >= 0.8) {
        out.coverage = t("insightCoverageGood", { pct })
      } else if (c >= 0.5) {
        out.coverage = t("insightCoverageModerate", { pct })
      } else {
        out.coverage = t("insightCoverageLow", { pct })
      }
    }

    if (yearBins && yearBins.length > 0) {
      const valid = yearBins.filter((b) => b.total > 0)
      if (valid.length > 0) {
        const peak = valid.reduce((a, b) => (b.total > a.total ? b : a))
        const total = valid.reduce((sum, b) => sum + b.total, 0)
        const recent = valid
          .filter((b) => b.year >= 2020)
          .reduce((s, b) => s + b.total, 0)
        out.time = t("insightTime", {
          peak: peak.year,
          pkN: peak.total,
          recentPct: Math.round((recent / total) * 100),
        })
      }
    }

    if (rcsBins && rcsBins.length > 0 && rcsMean !== undefined) {
      const highCount = rcsBins
        .filter((b) => b.rcs >= 8)
        .reduce((s, b) => s + b.count, 0)
      const lowCount = rcsBins
        .filter((b) => b.rcs <= 2)
        .reduce((s, b) => s + b.count, 0)
      const total = rcsBins.reduce((s, b) => s + b.count, 0)
      out.quality = t("insightQuality", {
        mean: (rcsMean / 10).toFixed(2),
        hiN: highCount,
        hiPlural: highCount === 1 ? "" : "s",
        hiPct: Math.round((highCount / total) * 100),
        loN: lowCount,
        loPct: Math.round((lowCount / total) * 100),
      })
    }

    return out
    // data + nodes kept in deps for API parity with TARGET, even though only
    // shape-derived values are consumed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, yearBins, rcsBins, rcsMean, dc, nodes])
}
