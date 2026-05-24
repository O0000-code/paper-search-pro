// Port of TARGET charts.jsx RcsHistogram (49-114) to Recharts.
// Bars colored by tier (Cell per bar), mean line (ReferenceLine), 95% CI band
// (ReferenceArea), tier threshold tick markers (short ReferenceLine
// segments at the x-axis baseline).
//
// Polish (Wave E): shadcn-native ChartTooltip + ChartTooltipContent with
// bin-range label (RCS 0.45 – 0.55 style) + "N papers" formatter, plus
// explicit Bar animation (1100ms ease-out). Cell tier colors preserved.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceArea,
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
import type { RcsBin } from "@/lib/types"

const config = {
  count: { label: "Papers", color: "hsl(var(--chart-3))" },
} satisfies ChartConfig

function tierForRcs(rcs: number): 1 | 2 | 3 | 4 | 5 {
  if (rcs >= 8.5) return 1
  if (rcs >= 7) return 2
  if (rcs >= 5.5) return 3
  if (rcs >= 4.5) return 4
  return 5
}

export interface RcsHistogramProps {
  bins: RcsBin[]
  mean?: number
  ciLow?: number
  ciHigh?: number
  height?: number
}

export function RcsHistogram({
  bins,
  mean,
  ciLow,
  ciHigh,
  height = 200,
}: RcsHistogramProps) {
  if (!bins || bins.length === 0) return null

  return (
    <ChartContainer
      config={config}
      className="!aspect-auto w-full"
      style={{ height, width: "100%" }}
    >
      <BarChart
        data={bins}
        margin={{ top: 12, right: 8, left: 8, bottom: 4 }}
        barCategoryGap="14%"
      >
        <CartesianGrid
          stroke="hsl(var(--border))"
          strokeDasharray="3 3"
          strokeOpacity={0.7}
          vertical={false}
        />
        <XAxis
          dataKey="rcs"
          type="number"
          domain={[-0.5, 10.5]}
          ticks={[0, 2, 4, 6, 8, 10]}
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          tickLine={false}
          axisLine={{ stroke: "hsl(var(--border))" }}
          tickFormatter={(v: number) => (v / 10).toFixed(2)}
          tickMargin={4}
        />
        <YAxis
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          tickLine={false}
          axisLine={false}
          width={32}
          tickCount={4}
        />

        <ChartTooltip
          cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
          content={
            <ChartTooltipContent
              labelFormatter={(label) =>
                `RCS ${(Number(label) / 10).toFixed(2)} – ${(Number(label) / 10 + 0.1).toFixed(2)}`
              }
              formatter={(value) => [`${value} ${getS().papers || "papers"}`, ""]}
              indicator="dot"
            />
          }
        />

        {ciLow !== undefined && ciHigh !== undefined && (
          <ReferenceArea
            x1={ciLow}
            x2={ciHigh}
            fill="hsl(var(--primary))"
            fillOpacity={0.06}
            ifOverflow="visible"
          />
        )}

        {mean !== undefined && (
          <ReferenceLine
            x={mean}
            stroke="hsl(var(--primary))"
            strokeWidth={1}
            strokeDasharray="3 3"
            label={{
              value: `μ ${(mean / 10).toFixed(2)}`,
              position: "top",
              fill: "hsl(var(--foreground))",
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              offset: 4,
            }}
          />
        )}

        {[4.5, 5.5, 7, 8.5].map((t) => (
          <ReferenceLine
            key={t}
            x={t}
            stroke="hsl(var(--muted-foreground))"
            strokeWidth={1}
            segment={[
              { x: t, y: 0 },
              { x: t, y: 0 },
            ]}
          />
        ))}

        <Bar
          dataKey="count"
          fill="var(--color-count)"
          isAnimationActive={true}
          animationDuration={1100}
          animationEasing="ease-out"
        >
          {bins.map((b, i) => (
            <Cell key={i} fill={`hsl(var(--chart-${tierForRcs(b.rcs)}))`} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}
