// Recharts port of TARGET v2-methods.jsx InteractiveScatter (250-325).
//
// Architecture:
//   • Recharts ScatterChart with native isAnimationActive entrance — same
//     pattern as YearBarChart / RcsHistogram (charts 1-3). Recharts handles
//     the dots' fade-in via its built-in animation pipeline; we don't try
//     to drive entrance ourselves. Hover/leave state changes glide via a
//     CSS transition declared on the inline style.
//   • Hover state lives in a single `useState<string | null>` — when the
//     user mouses over a dot, React re-renders only the Dot shape with
//     darker stroke + outer pulse ring + scaled-up transform.
//   • Tooltip uses shadcn ChartTooltipContent styling (rounded-lg border
//     bg-background shadow-xl text-xs) with custom rich card children.
//
// History note (2026-05-23): an earlier revision drove entrance via Web
// Animations API in a useEffect that fired on every render. Hover →
// re-render → Recharts rebuilt all <circle> DOM → entrance replayed
// indefinitely → infinite flicker. The fix is to NOT custom-orchestrate
// entrance at all — Recharts already does it cleanly via isAnimationActive.

import { useEffect, useState } from "react"

import {
  CartesianGrid,
  Scatter,
  ScatterChart,
  XAxis,
  YAxis,
} from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  type ChartConfig,
} from "@/components/ui/chart"

import { getS } from "@/lib/i18n"
import type { CitationNetworkNode } from "@/lib/types"

export interface CitationScatterProps {
  nodes: CitationNetworkNode[]
  height?: number
  onSelect?: (node: CitationNetworkNode) => void
}

function tierForRcs(rcs: number): 1 | 2 | 3 | 4 | 5 {
  if (rcs >= 8.5) return 1
  if (rcs >= 7) return 2
  if (rcs >= 5.5) return 3
  if (rcs >= 4.5) return 4
  return 5
}

function sizeForRcs(rcs: number): number {
  return 4 + (rcs / 10) * 8
}

// config.scatter.label is unused at render time (we use a custom
// TooltipContent that ignores the series label) — keep English literal as
// the Recharts contract requires a label string and this string is never
// shown to the user.
const config = {
  scatter: { label: "Paper", color: "hsl(var(--chart-3))" },
} satisfies ChartConfig

interface DotProps {
  cx?: number
  cy?: number
  payload: CitationNetworkNode
}

interface TooltipPayloadItem {
  payload: CitationNetworkNode
}

interface TooltipContentProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
}

// Material Design "standard" easing — used for hover transitions only.
const EASING_STD = "cubic-bezier(0.4, 0, 0.2, 1)"
const TRANS_HOVER =
  `transform 220ms ${EASING_STD}, stroke 220ms ${EASING_STD}, stroke-width 220ms ${EASING_STD}, fill-opacity 220ms ${EASING_STD}`

export function CitationScatter({
  nodes,
  height = 280,
  onSelect,
}: CitationScatterProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  // Entrance — group-level opacity fade-in. Recharts `isAnimationActive` on
  // <Scatter> only animates built-in shapes (Bar, Pie, etc.); custom
  // `shape={fn}` is rendered as-is with no wrapper animation. Bar charts
  // (1-3) get per-bar grow animation natively; for the scatter we wrap
  // the chart in a div whose opacity flips 0 → 1 on mount via CSS
  // transition. Once `mounted=true`, the opacity doesn't change on
  // re-render (hover, etc.) so the transition never re-fires — no
  // flicker risk like the prior WAAPI orchestration.
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    // 1-frame defer so the initial commit lands with opacity=0,
    // then re-render flips to opacity=1 and CSS transition kicks in.
    const t = window.setTimeout(() => setMounted(true), 50)
    return () => window.clearTimeout(t)
  }, [])

  const data = nodes.filter((n) => n.year && n.citation_count)
  if (data.length === 0) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 180,
          fontSize: 12,
          color: "hsl(var(--muted-foreground))",
          border: "1px dashed hsl(var(--border))",
          borderRadius: "var(--radius)",
          fontFamily: "var(--font-sans)",
        }}
      >
        {getS().noData || "No data"}
      </div>
    )
  }

  const years = data.map((n) => n.year)
  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)
  const maxCites = Math.max(...data.map((n) => n.citation_count))

  // Year ticks every 5 years, aligned to multiples of 5
  const yearTicks: number[] = []
  for (let y = Math.ceil(minYear / 5) * 5; y <= maxYear; y += 5) {
    yearTicks.push(y)
  }
  if (yearTicks[0] !== minYear) yearTicks.unshift(minYear)
  if (yearTicks[yearTicks.length - 1] !== maxYear) yearTicks.push(maxYear)

  const citationTicks = [1, 10, 100, 1000].filter((v) => v <= maxCites)

  // Custom dot shape — Recharts passes cx/cy already scaled; we paint the
  // tier color, RCS-derived radius, baseline opacity, hover overlay (outer
  // pulse ring + darker stroke + scale to full maxR), and wire onClick.
  // The entrance animation is owned by Recharts (<Scatter isAnimationActive>).
  const Dot = (props: DotProps) => {
    const { cx, cy, payload } = props
    if (cx == null || cy == null || !payload) return <g />
    const tier = tierForRcs(payload.rcs)
    const baseR = sizeForRcs(payload.rcs)
    const maxR = baseR + 3 // rendered SVG r — also the hover-state size
    const isHovered = hoveredId === payload.id
    const baseOpacity = payload.rcs >= 5.5 ? 0.9 : 0.55

    // Resting scale = baseR/maxR; hover scale = 1.0 (full maxR rendered).
    const targetScale = isHovered ? 1 : baseR / maxR
    const ringOpacity = isHovered ? 0.35 : 0

    return (
      <g>
        {/* Outer pulse ring — always rendered, opacity-only toggling so the
            ring fades in/out smoothly instead of popping. No entrance
            animation; it only appears on hover. */}
        <circle
          cx={cx}
          cy={cy}
          r={baseR + 6}
          fill="none"
          stroke={`hsl(var(--chart-${tier}))`}
          strokeWidth={1}
          opacity={ringOpacity}
          style={{
            transition: `opacity 260ms ${EASING_STD}`,
            pointerEvents: "none",
          }}
        />
        {/* Main dot — Recharts handles entrance; CSS transition handles
            hover. Hover triggers React re-render which flips stroke +
            strokeWidth + transform values; transition glides them. */}
        <circle
          cx={cx}
          cy={cy}
          r={maxR}
          fill={`hsl(var(--chart-${tier}))`}
          fillOpacity={baseOpacity}
          stroke={
            isHovered ? "hsl(var(--foreground))" : "hsl(var(--background))"
          }
          strokeWidth={isHovered ? 2 : 1.5}
          style={{
            cursor: "pointer",
            transform: `scale(${targetScale})`,
            transformBox: "fill-box",
            transformOrigin: "center",
            transition: TRANS_HOVER,
          }}
          onClick={() => onSelect?.(payload)}
          onMouseEnter={() => setHoveredId(payload.id)}
          onMouseLeave={() => setHoveredId(null)}
        />
      </g>
    )
  }

  // Tooltip outer uses the exact shadcn ChartTooltipContent styling
  // (border-border/50 + bg-background + rounded-lg + px-2.5 py-1.5 + text-xs
  // + shadow-xl) so it matches YearBarChart / RcsHistogram tooltips visually.
  // Children stay as the rich card layout (tier dot + mono meta + title +
  // authors·venue + click hint) — shadcn-native shell, custom content.
  const TooltipContent = (props: TooltipContentProps) => {
    const { active, payload } = props
    if (!active || !payload || payload.length === 0) return null
    const n = payload[0].payload
    const tier = tierForRcs(n.rcs)
    const S = getS()
    return (
      <div className="border-border/50 bg-background grid min-w-[8rem] max-w-[320px] items-start gap-1 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
        <div className="flex items-center gap-1.5">
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: `hsl(var(--chart-${tier}))`,
              display: "inline-block",
              flexShrink: 0,
            }}
          />
          <span
            className="tabular-nums text-muted-foreground"
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            {n.year} · {n.citation_count} {S.cites || "cites"} · RCS{" "}
            {(n.rcs / 10).toFixed(2)}
          </span>
        </div>
        <div className="font-medium text-foreground leading-snug">
          {n.title}
        </div>
        {(n.authors_short || n.venue) && (
          <div className="text-muted-foreground leading-tight">
            {n.authors_short}
            {n.authors_short && n.venue ? " · " : ""}
            {n.venue}
          </div>
        )}
        <div
          className="text-muted-foreground opacity-70 pt-0.5"
          style={{ fontSize: 11 }}
        >
          {S.clickToOpenDetail || "Click to open detail →"}
        </div>
      </div>
    )
  }

  return (
    <div
      style={{
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(6px)",
        transition: `opacity 700ms ${EASING_STD}, transform 700ms ${EASING_STD}`,
      }}
    >
    <ChartContainer
      config={config}
      className="!aspect-auto w-full"
      style={{ height, width: "100%" }}
    >
      <ScatterChart margin={{ top: 18, right: 24, left: 8, bottom: 24 }}>
        <CartesianGrid
          stroke="hsl(var(--border))"
          strokeDasharray="3 3"
          strokeOpacity={0.7}
        />
        <XAxis
          type="number"
          dataKey="year"
          name="Year"
          domain={[minYear, maxYear]}
          ticks={yearTicks}
          allowDecimals={false}
          tickLine={false}
          axisLine={{ stroke: "hsl(var(--border))" }}
          tick={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          tickMargin={8}
        />
        <YAxis
          type="number"
          dataKey="citation_count"
          name="Citations"
          scale="log"
          domain={[1, maxCites]}
          ticks={citationTicks}
          allowDataOverflow={false}
          tickLine={false}
          axisLine={false}
          tick={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          width={36}
        />
        <ChartTooltip
          cursor={{
            stroke: "hsl(var(--muted-foreground))",
            strokeWidth: 1,
            strokeDasharray: "3 3",
          }}
          content={<TooltipContent />}
        />
        {/* `isAnimationActive={false}` because Recharts's built-in animation
            wrapper only animates its own shapes (Bar/Line/Pie); with a custom
            `shape={Dot}` it's a no-op. Entrance is owned by the wrapper <div>
            opacity transition above. */}
        <Scatter data={data} shape={Dot as never} isAnimationActive={false} />
      </ScatterChart>
    </ChartContainer>
    </div>
  )
}
