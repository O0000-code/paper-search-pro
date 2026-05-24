// Recharts port of TARGET charts.jsx DiscoveryCurve (118-189).
//
// Wave E rewrite — replaces the Wave B3 pure-SVG implementation, whose
// `viewBox="0 0 100 H"` + `preserveAspectRatio="none"` stretched text into
// long ribbons inside the >1000px Methods card. This file:
//   • uses ChartContainer + ComposedChart so X scaling is pixel-correct,
//   • renders the saturation curve as <Line> with shadcn ease-out animation,
//   • places the asymptote via <ReferenceLine y={estimatedRelevant}>,
//   • draws the drop line via <ReferenceLine segment={[(x,0),(x,foundRelevant)]}>
//     so Recharts's own y-axis scale clips it exactly at baseline,
//   • renders the marker (3 concentric circles + label tag) via a
//     <ReferenceDot shape={...}> at (totalScreened, foundRelevant).
//
// Visual numbers (outer ring 9 / inner 5.5 / center 2.5 / label tag 96×18) are
// the pixel-scale equivalents of the original SVG unit values (3 / 1.8 / 0.9 /
// 22×5 in a viewBox=100 system, ~3x scaled up).

import {
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts"

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

import { getS } from "@/lib/i18n"

export interface DiscoveryCurveProps {
  tau: number
  coverage: number
  ciLow: number
  ciHigh: number
  totalScreened: number
  estimatedRelevant: number
  foundRelevant: number
  height?: number
}

interface MarkerShapeProps {
  cx?: number
  cy?: number
}

export function DiscoveryCurve({
  tau,
  totalScreened,
  estimatedRelevant,
  foundRelevant,
  height = 260,
}: DiscoveryCurveProps) {
  // Series label appears in the hover tooltip header. Read at render time so
  // language switches reflect in the tooltip; defined inside the function
  // body since `config` cannot be a module constant if it must read getS().
  const S = getS() as Record<string, string>
  const config = {
    y: {
      label: S.discoveryCurveSeriesLabel || "Highly-relevant found",
      color: "hsl(var(--primary))",
    },
  } satisfies ChartConfig
  const xMax = Math.max(totalScreened * 1.25, totalScreened + 100)
  const data = Array.from({ length: 101 }, (_, i) => {
    const n = (i / 100) * xMax
    return {
      n: Math.round(n),
      y: estimatedRelevant * (1 - Math.exp(-n / tau)),
    }
  })

  const yDomainMax = estimatedRelevant * 1.1
  const xMaxRounded = Math.round(xMax)
  // Anchor the "we are here" marker on the curve itself — not at the observed
  // `foundRelevant` count. The curve is the model's prediction at each x; the
  // marker's purpose is to show our position ON the curve. Drawing it at
  // `foundRelevant` (which may differ from the model prediction at the same x)
  // creates a visual where the marker floats above/below the line. Anchoring
  // at the curve value guarantees marker + dropline intersect the curve
  // cleanly. The label still reports `found` so observed value isn't lost.
  const curveYAtX = estimatedRelevant * (1 - Math.exp(-totalScreened / tau))
  // labelText "n={N} · found {F}" — chart-overlay annotation; mirrors
  // ground truth charts.jsx line 177 which is hard-coded English. The
  // `n` symbol and `found` keyword are kept English as chart-internal
  // mathematical/data labels (consistent with charts.jsx ground truth).
  const labelText = `n=${totalScreened} · found ${foundRelevant}`
  // Approximate text width for the white tag (mono font, ~6px per glyph at 10.5px)
  const tagWidth = Math.max(72, labelText.length * 6.2 + 12)

  // Custom marker shape — receives (cx, cy) already scaled to pixel coords by
  // Recharts. Returns the full marker assembly anchored at that point.
  const MarkerShape = (props: MarkerShapeProps) => {
    const { cx, cy } = props
    if (cx == null || cy == null) return <g />

    // Tag flips left if it would overflow the right edge. Since we don't have
    // chart width here, we use the simple heuristic: if marker is in the right
    // 25% of the curve (totalScreened close to xMax), flip the tag to the left.
    const flipTag = totalScreened / xMax > 0.7
    const tagX = flipTag ? -tagWidth - 10 : 10
    const tagY = -28

    return (
      <g>
        {/* Outer pulse ring */}
        <circle
          cx={cx}
          cy={cy}
          r={9}
          fill="none"
          stroke="hsl(var(--primary))"
          strokeWidth={1}
          opacity={0.35}
        />
        {/* Inner ring */}
        <circle
          cx={cx}
          cy={cy}
          r={5.5}
          fill="none"
          stroke="hsl(var(--primary))"
          strokeWidth={1.5}
        />
        {/* Center dot */}
        <circle cx={cx} cy={cy} r={2.5} fill="hsl(var(--primary))" />
        {/* Label tag — anchored above-right (or above-left if near edge) */}
        <g transform={`translate(${cx + tagX}, ${cy + tagY})`}>
          <rect
            x={0}
            y={0}
            width={tagWidth}
            height={18}
            fill="hsl(var(--background))"
            stroke="hsl(var(--primary))"
            strokeWidth={1}
            rx={3}
          />
          <text
            x={6}
            y={12.5}
            fontSize={10.5}
            fill="hsl(var(--foreground))"
            style={{ fontFamily: "var(--font-mono)" }}
            fontWeight={600}
          >
            {labelText}
          </text>
        </g>
      </g>
    )
  }

  return (
    <ChartContainer
      config={config}
      className="!aspect-auto w-full"
      style={{ height, width: "100%" }}
    >
      <ComposedChart
        data={data}
        margin={{ top: 12, right: 24, left: 8, bottom: 22 }}
      >
        <XAxis
          dataKey="n"
          type="number"
          domain={[0, xMax]}
          tickLine={false}
          axisLine={{ stroke: "hsl(var(--border))" }}
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          ticks={[0, Math.round(xMax / 2), xMaxRounded]}
          tickFormatter={(v: number) =>
            v === 0
              ? "0"
              : v === xMaxRounded
                ? `${v} ${S.paperScreened || "papers screened"}`
                : `${v}`
          }
          tickMargin={6}
        />
        <YAxis
          type="number"
          domain={[0, yDomainMax]}
          tickLine={false}
          axisLine={false}
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          tickCount={5}
          tickFormatter={(v: number) => Math.round(v).toString()}
          width={32}
        />
        <ChartTooltip
          cursor={{
            stroke: "hsl(var(--muted-foreground))",
            strokeWidth: 1,
            strokeDasharray: "3 3",
          }}
          content={
            <ChartTooltipContent
              labelFormatter={(label) => `n = ${label}`}
              indicator="line"
            />
          }
        />
        {/* Asymptote — estimated_total_relevant */}
        <ReferenceLine
          y={estimatedRelevant}
          stroke="hsl(var(--primary))"
          strokeWidth={1}
          strokeDasharray="5 4"
          label={{
            // "asymptote ≈ R" — chart-overlay annotation; mirrors ground
            // truth charts.jsx line 156 which is hard-coded English.
            value: `asymptote ≈ ${estimatedRelevant.toFixed(1)}`,
            position: "insideTopRight",
            fill: "hsl(var(--primary))",
            fontSize: 10.5,
            fontFamily: "var(--font-mono)",
            offset: 6,
          }}
        />
        <Line
          type="monotone"
          dataKey="y"
          stroke="var(--color-y)"
          strokeWidth={1.75}
          dot={false}
          isAnimationActive
          animationDuration={1100}
          animationEasing="ease-out"
        />
        {/* Drop line from (totalScreened, curveYAtX) down to baseline.
            The endpoint sits ON the curve so the marker + dropline intersect
            the line visually. ReferenceLine with segment uses Recharts's own
            y-axis scale, so the line stops exactly at y=0 — no manual clip
            needed. */}
        <ReferenceLine
          stroke="hsl(var(--primary))"
          strokeWidth={1}
          strokeDasharray="3 3"
          segment={[
            { x: totalScreened, y: 0 },
            { x: totalScreened, y: curveYAtX },
          ]}
        />
        {/* "we are here" marker — anchored at (totalScreened, curveYAtX) so
            the dot always sits exactly on the saturation curve. */}
        <ReferenceDot
          x={totalScreened}
          y={curveYAtX}
          r={0}
          isFront
          shape={MarkerShape}
          ifOverflow="visible"
        />
      </ComposedChart>
    </ChartContainer>
  )
}
