// Port of TARGET charts.jsx YearBars (4-46) to Recharts.
// TARGET visual: total bar (light) full height + highly_relevant overlay
// (dark) at the base. Recharts equivalent: two <Bar> at the same x without
// stackId — both anchor to baseline, the second renders on top of the first.
//
// Polish (Wave E): shadcn-native ChartTooltip + ChartTooltipContent for
// hover popover (black bg / white text / 8-12px) with cursor-follow muted
// highlight, plus explicit Bar animation (1100ms ease-out, second Bar
// staggered 200ms for a layered entrance).

import {
  Bar,
  BarChart,
  CartesianGrid,
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
import type { YearBin } from "@/lib/types"

export interface YearBarChartProps {
  bins: YearBin[]
  height?: number
}

export function YearBarChart({ bins, height = 200 }: YearBarChartProps) {
  // Recharts series labels appear in the hover tooltip. Read via getS()
  // with a soft fallback so the bundle continues working when the dict has
  // not been extended with these keys (graceful degrade to English literals,
  // matching the (window.S||{}).key || "fallback" pattern in ground truth).
  const S = getS() as Record<string, string>
  const config = {
    total: {
      label: S.allScreenedSeries || "All screened",
      color: "hsl(var(--chart-4))",
    },
    highly_relevant: {
      label: S.highlyRelevantSeries || "Highly relevant",
      color: "hsl(var(--chart-1))",
    },
  } satisfies ChartConfig

  const data = bins.filter((b) => b.total > 0)
  if (data.length === 0) return <EmptyChart />

  return (
    <ChartContainer
      config={config}
      className="!aspect-auto w-full"
      style={{ height, width: "100%" }}
    >
      <BarChart
        data={data}
        margin={{ top: 8, right: 8, left: 8, bottom: 4 }}
        barCategoryGap="20%"
      >
        <CartesianGrid
          stroke="hsl(var(--border))"
          strokeDasharray="3 3"
          strokeOpacity={0.7}
          vertical={false}
        />
        <XAxis
          dataKey="year"
          interval={Math.max(0, Math.floor(data.length / 6))}
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "hsl(var(--muted-foreground))",
          }}
          tickLine={false}
          axisLine={{ stroke: "hsl(var(--border))" }}
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
              labelKey="year"
              indicator="dot"
            />
          }
        />
        <ReferenceLine y={0} stroke="hsl(var(--border))" />
        <Bar
          dataKey="total"
          fill="var(--color-total)"
          isAnimationActive={true}
          animationDuration={1100}
          animationEasing="ease-out"
        />
        <Bar
          dataKey="highly_relevant"
          fill="var(--color-highly_relevant)"
          isAnimationActive={true}
          animationDuration={1100}
          animationBegin={200}
          animationEasing="ease-out"
        />
      </BarChart>
    </ChartContainer>
  )
}

function EmptyChart() {
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
