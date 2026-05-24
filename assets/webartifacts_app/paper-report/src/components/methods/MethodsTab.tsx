// Port of TARGET v2-methods.jsx MethodsTabV2 (5-204).
// 6 sections — Coverage / Time / Quality / Citation graph / Allocation /
// Methodology. All inline grid/padding/gap/marginBottom values copied from
// TARGET; chart components are 1:1 visual equivalents (Recharts for 3,
// pure SVG for DiscoveryCurve + CitationScatter — see those files for the
// rationale).

import { Check, Info } from "lucide-react"

import { KickerAlert } from "@/components/adapters/KickerAlert"
import { Card } from "@/components/ui/card"
import { fmtPct } from "@/lib/format"
import { t } from "@/lib/i18n"
import type {
  CitationNetworkNode,
  NormalizedData,
  NormalizedPaper,
} from "@/lib/types"

import { CitationScatter } from "./CitationScatter"
import { DiscoveryCurve } from "./DiscoveryCurve"
import { MethodologyAccordion } from "./MethodologyAccordion"
import { RcsHistogram } from "./RcsHistogram"
import { SectionHeader } from "./SectionHeader"
import { Stat } from "./Stat"
import { TierAllocation } from "./TierAllocation"
import { TopicsTreemap } from "./TopicsTreemap"
import { useInsights } from "./useInsights"
import { YearBarChart } from "./YearBarChart"

export interface MethodsTabProps {
  data: NormalizedData
  onSelectPaper?: (paper: NormalizedPaper) => void
}

export function MethodsTab({ data, onSelectPaper }: MethodsTabProps) {
  const c = data.chartData || {}
  const m = data.meta
  const yearBins = c.publication_year?.bins || []
  const rcsBins = c.relevance_score?.bins || []
  const rcsMean = c.relevance_score?.mean
  const rcsCiLow = c.relevance_score?.ci_low
  const rcsCiHigh = c.relevance_score?.ci_high
  const dc = c.discovery_curve
  const nodes: CitationNetworkNode[] = c.citation_network?.nodes || []

  const insights = useInsights({
    data,
    yearBins,
    rcsBins,
    rcsMean,
    dc,
    nodes,
  })

  function clickScatterNode(node: CitationNetworkNode) {
    if (!onSelectPaper) return
    const paper = data.papers.find((p) => p.id === node.id)
    if (paper) onSelectPaper(paper)
  }

  const totalScreened = m.papersEvaluated ?? 0
  const highlyRelevant = m.highlyRelevant ?? 0
  const closelyRelated = m.closelyRelated ?? 0

  const cardStyle = {
    padding: "20px 24px",
    borderRadius: 12,
    // Flat shadcn override — TARGET design has no drop shadow on chart
    // cards; border alone provides separation. Inline style overrides the
    // default `shadow` Tailwind class baked into shadcn Card.
    boxShadow: "none",
  } as const

  return (
    <div
      className="rd-tab-methods"
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "32px 40px 80px",
        fontFamily: "var(--font-sans)",
      }}
    >
      {dc && (
        <section style={{ marginBottom: 56 }}>
          <SectionHeader
            kicker={t("coverageKicker")}
            title={t("discoveryCurveTitle")}
            sub={t("discoveryCurveSub")}
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 280px",
              gap: 32,
              alignItems: "stretch",
              marginBottom: 16,
            }}
          >
            <Card style={cardStyle}>
              <DiscoveryCurve
                tau={dc.tau}
                coverage={dc.coverage_estimate}
                ciLow={dc.ci_low}
                ciHigh={dc.ci_high}
                totalScreened={totalScreened}
                estimatedRelevant={dc.estimated_total_relevant}
                foundRelevant={highlyRelevant}
                height={260}
              />
            </Card>
            <Card
              style={{
                ...cardStyle,
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}
            >
              <Stat
                label={t("coverageEstimate")}
                value={fmtPct(dc.coverage_estimate, 1)}
                sub={`95% CI ${fmtPct(dc.ci_low)} – ${fmtPct(dc.ci_high)}`}
              />
              <Stat
                label={t("estTotalRelevant")}
                value={dc.estimated_total_relevant?.toFixed(1)}
                sub={t("asymptote")}
              />
              <Stat
                label={t("decayConstant")}
                value={dc.tau?.toFixed(1)}
                sub={t("lowerTauHint")}
              />
              <p
                style={{
                  fontSize: 11.5,
                  color: "hsl(var(--muted-foreground))",
                  lineHeight: 1.55,
                  margin: 0,
                  paddingTop: 8,
                  borderTop: "1px solid hsl(var(--border))",
                }}
              >
                {/* Prefer front-end-rendered summary built from i18n
                    `discoveryCurveSummary` template; fall back to the
                    backend-rendered `dc.summary` string (English) when
                    the dict is unavailable. Mirrors ground truth
                    v2-methods.jsx line 56. */}
                {t("discoveryCurveSummary", {
                  found: Math.round(dc.estimated_total_relevant),
                  pct: Math.round(dc.coverage_estimate * 100),
                  lo: Math.round(dc.ci_low * 100),
                  hi: Math.round(dc.ci_high * 100),
                }) || dc.summary}
              </p>
            </Card>
          </div>
          {insights.coverage && (
            <KickerAlert
              variant="success"
              Icon={Check}
              title={t("whatThisMeans")}
            >
              {insights.coverage}
            </KickerAlert>
          )}
        </section>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 32,
          marginBottom: 56,
          alignItems: "stretch",
        }}
      >
        {yearBins.length > 0 && (
          <section style={{ display: "flex", flexDirection: "column" }}>
            <SectionHeader
              kicker={t("timeKicker")}
              title={t("publicationsTitle")}
              sub={t("publicationsSub")}
            />
            <Card
              style={{
                ...cardStyle,
                flex: 1,
                display: "flex",
                flexDirection: "column",
              }}
            >
              <YearBarChart bins={yearBins} height={200} />
              <div style={{ flex: 1 }} />
            </Card>
            {insights.time && (
              <div style={{ marginTop: 14 }}>
                <KickerAlert variant="info" Icon={Info}>
                  {insights.time}
                </KickerAlert>
              </div>
            )}
          </section>
        )}

        {rcsBins.length > 0 && (
          <section style={{ display: "flex", flexDirection: "column" }}>
            <SectionHeader
              kicker={t("qualityKicker")}
              title={t("rcsDistTitle")}
              sub={t("rcsDistSub", {
                mean:
                  rcsMean !== undefined ? (rcsMean / 10).toFixed(2) : "—",
                lo:
                  rcsCiLow !== undefined ? (rcsCiLow / 10).toFixed(2) : "—",
                hi:
                  rcsCiHigh !== undefined
                    ? (rcsCiHigh / 10).toFixed(2)
                    : "—",
              })}
            />
            <Card
              style={{
                ...cardStyle,
                flex: 1,
                display: "flex",
                flexDirection: "column",
              }}
            >
              <RcsHistogram
                bins={rcsBins}
                mean={rcsMean}
                ciLow={rcsCiLow}
                ciHigh={rcsCiHigh}
                height={200}
              />
              <div
                style={{
                  marginTop: 14,
                  paddingTop: 14,
                  borderTop: "1px solid hsl(var(--border))",
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 8,
                  fontSize: 10.5,
                  color: "hsl(var(--muted-foreground))",
                }}
              >
                {(
                  [
                    [0.45, t("periphShort")],
                    [0.55, t("emergShort")],
                    [0.7, t("modShort")],
                    [0.85, t("highShort")],
                  ] as Array<[number, string]>
                ).map(([threshold, label]) => (
                  <span
                    key={threshold}
                    className="tabular-nums"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {label} {threshold.toFixed(2)}+
                  </span>
                ))}
                <span
                  className="tabular-nums"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {t("foundPlus")}
                </span>
              </div>
            </Card>
            {insights.quality && (
              <div style={{ marginTop: 14 }}>
                <KickerAlert variant="info" Icon={Info}>
                  {insights.quality}
                </KickerAlert>
              </div>
            )}
          </section>
        )}
      </div>

      {nodes.length > 0 && (
        <section style={{ marginBottom: 56 }}>
          <SectionHeader
            kicker={t("citationGraphKicker")}
            title={t("citationScatterTitle")}
            sub={t("citationScatterSub")}
          />
          <Card style={cardStyle}>
            <CitationScatter
              nodes={nodes}
              height={260}
              onSelect={clickScatterNode}
            />
          </Card>
        </section>
      )}

      {/* 05 · Topics — full-width Mosaic treemap. Renders when the payload
          includes `chart_data.theme_treemap` (object exists, even if its
          `themes` array is empty / all zero). 1:1 with delta source: the
          inner TopicsTreemap component handles the empty case itself by
          rendering a dashed "Topic clustering not available for this run."
          placeholder, so the section header stays visible and the user
          gets explicit feedback that this channel had no signal. */}
      {c.theme_treemap && (
          <section style={{ marginBottom: 56 }}>
            <SectionHeader
              kicker={t("topicsKicker")}
              title={t("topicsTitle")}
              sub={t("topicsSub")}
            />
            <Card style={{ padding: "20px 24px", borderRadius: 12, boxShadow: "none" }}>
              <TopicsTreemap
                data={c.theme_treemap}
                height={320}
                onSelect={(paperId) => {
                  if (!onSelectPaper) return
                  const p = data.papers.find(
                    (q) => q.id === paperId || q.doi === paperId,
                  )
                  if (p) onSelectPaper(p)
                }}
              />
            </Card>
          </section>
        )}

      <section style={{ marginBottom: 56 }}>
        <SectionHeader
          kicker={t("allocationKicker")}
          title={t("allocationTitle")}
          sub={t("allocationSub")}
        />
        <Card style={{ padding: "24px 28px", borderRadius: 12, boxShadow: "none" }}>
          <TierAllocation
            papers={data.papers}
            totalScreened={totalScreened}
            highlyRelevant={highlyRelevant}
            closelyRelated={closelyRelated}
          />
        </Card>
      </section>

      <section>
        <SectionHeader
          kicker={t("methodologyKicker")}
          title={t("methodologyTitle")}
          sub={t("methodologySub")}
        />
        <MethodologyAccordion />
      </section>
    </div>
  )
}
