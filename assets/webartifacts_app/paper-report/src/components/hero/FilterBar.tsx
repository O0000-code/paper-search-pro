// Filter bar (sticky) — 1:1 port of TARGET redesign/app-1-hero.jsx FilterBar (255-321).
//
// Search-within-results input + RCS threshold slider (with tier zones)
// + Focus toggle (Recommended/All) + View toggle (List/Cards).
// Sticky top with translucent backdrop blur. A short results-line sits
// below the row at reduced padding so it doesn't crowd the toolbar.

import { FileText, Layers, Sliders, Sparkles } from "lucide-react"

import { SearchInput } from "@/components/adapters/SearchInput"
import { SegmentedToggle } from "@/components/adapters/SegmentedToggle"
import { t } from "@/lib/i18n"

import { SliderWithZones } from "./SliderWithZones"

export interface FilterBarProps {
  threshold: number
  setThreshold: (next: number) => void
  search: string
  setSearch: (next: string) => void
  view: string
  setView: (next: string) => void
  focus: string
  setFocus: (next: string) => void
  resultsCount: number
  total: number
}

export function FilterBar({
  threshold,
  setThreshold,
  search,
  setSearch,
  view,
  setView,
  focus,
  setFocus,
  resultsCount,
  total,
}: FilterBarProps) {
  return (
    <div
      style={{
        position: "sticky",
        top: 0,
        zIndex: 20,
        background: "hsl(var(--background) / 0.95)",
        backdropFilter: "saturate(180%) blur(8px)",
        WebkitBackdropFilter: "saturate(180%) blur(8px)",
        borderBottom: "1px solid hsl(var(--border))",
      }}
    >
      <div
        style={{
          maxWidth: 1240,
          margin: "0 auto",
          padding: "14px 40px",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        {/* Search */}
        <div style={{ flex: "0 0 280px" }}>
          <SearchInput
            placeholder={t("searchWithin")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* RCS slider with tier zones */}
        <div
          style={{
            flex: "1 1 auto",
            display: "flex",
            alignItems: "center",
            gap: 14,
            minWidth: 0,
          }}
        >
          <span
            style={{
              fontSize: 11.5,
              color: "hsl(var(--muted-foreground))",
              whiteSpace: "nowrap",
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            <Sliders className="h-3 w-3" />
            {t("rcsThreshold")}
          </span>
          <span
            className="tabular"
            style={{
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              fontSize: 13,
              minWidth: 36,
              textAlign: "right",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {(threshold / 10).toFixed(2)}
          </span>
          <div style={{ flex: 1, minWidth: 100 }}>
            <SliderWithZones
              value={threshold}
              onValueChange={setThreshold}
              min={0}
              max={10}
              step={0.1}
              zones={[
                { start: 0, end: 4.5, color: "hsl(var(--chart-5))" },
                { start: 4.5, end: 5.5, color: "hsl(var(--chart-4))" },
                { start: 5.5, end: 7, color: "hsl(var(--chart-3))" },
                { start: 7, end: 8.5, color: "hsl(var(--chart-2))" },
                { start: 8.5, end: 10, color: "hsl(var(--chart-1))" },
              ]}
            />
          </div>
        </div>

        {/* Focus toggle */}
        <SegmentedToggle
          value={focus}
          onValueChange={setFocus}
          items={[
            { value: "recommended", label: t("recommended"), Icon: Sparkles },
            { value: "all", label: t("all") },
          ]}
        />

        {/* View mode */}
        <SegmentedToggle
          value={view}
          onValueChange={setView}
          items={[
            { value: "compact", label: t("list"), Icon: FileText },
            { value: "card", label: t("cards"), Icon: Layers },
          ]}
        />
      </div>
      {/* Results line */}
      <div
        style={{
          maxWidth: 1240,
          margin: "0 auto",
          padding: "0 40px 12px",
          fontSize: 11.5,
          color: "hsl(var(--muted-foreground))",
        }}
      >
        {t("showingOf", { n: resultsCount, total })}
      </div>
    </div>
  )
}
