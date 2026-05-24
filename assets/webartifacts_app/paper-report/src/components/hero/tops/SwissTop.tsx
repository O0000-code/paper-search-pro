// Swiss / Numeric Top — 1:1 port of TARGET tops/top-2-swiss.jsx.
//
// Asymmetric 12-col grid: query on the left (28px H1), two massive 96px
// numerics on the right (Highly Relevant + Est. Coverage). Eyebrow strip
// shows search_id + dotted-date as the only meta. Below the header:
// bordered Tabs row (with mono uppercase labels), and a slim Findings-only
// Tier filter strip with vertical dividers between tier cells.

import { SearchInput } from "@/components/adapters/SearchInput"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { NormalizedData, Tier } from "@/lib/types"

import type { TierFilter } from "../TierStrip"

export interface SwissTopProps {
  data: NormalizedData
  tab: string
  setTab: (next: string) => void
  search: string
  setSearch: (next: string) => void
  tierFilter: TierFilter
  setTierFilter: (next: TierFilter) => void
  tierCounts: Partial<Record<Tier, number>>
  resultsCount: number
}

const TIER_PILLS: ("all" | Tier)[] = [
  "all",
  "Foundational",
  "High",
  "Moderate",
  "Emerging",
  "Peripheral",
]

export function SwissTop({
  data,
  tab,
  setTab,
  search,
  setSearch,
  tierFilter,
  setTierFilter,
  tierCounts,
  resultsCount,
}: SwissTopProps) {
  const m = data.meta
  const date = (m.generatedAt || "").slice(0, 10)
  const coverage = m.coverage
  const ciLow = m.coverageCi?.[0]
  const ciHigh = m.coverageCi?.[1]

  // Tab labels are i18n-bound, so they must be computed at runtime
  // (not at module load) — `t()` reads `window.S` which is set by
  // `installLanguage()` in main.tsx.
  const TAB_ITEMS = [
    { value: "findings", label: t("findings") },
    { value: "methods", label: t("methods") },
    { value: "audit", label: t("audit") },
  ]

  return (
    <>
      <header
        className="rd-hero-swiss"
        style={{
          borderBottom: "1px solid hsl(var(--border))",
          background: "hsl(var(--background))",
        }}
      >
        <div style={{ maxWidth: 1240, margin: "0 auto", padding: "40px 56px 56px" }}>
          {/* Top rule — tiny mono single line */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 10.5,
              color: "hsl(var(--muted-foreground))",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.06em",
              paddingBottom: 14,
              borderBottom: "1px solid hsl(var(--border))",
              marginBottom: 60,
            }}
          >
            <span>{m.searchId || m.skillVersion}</span>
            <span>{date.replace(/-/g, ".")}</span>
          </div>

          {/* 12-col grid: query | gutter | 16 | 96% */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "minmax(0, 6fr) 1fr minmax(0, 2.2fr) minmax(0, 2.2fr)",
              gap: 0,
              alignItems: "start",
            }}
          >
            {/* Query */}
            <div>
              <div
                style={{
                  fontSize: 10.5,
                  color: "hsl(var(--muted-foreground))",
                  textTransform: "uppercase",
                  letterSpacing: "0.14em",
                  fontFamily: "var(--font-mono)",
                  marginBottom: 18,
                  lineHeight: 1,
                  height: 12,
                }}
              >
                {t("query")}
              </div>
              <h1
                style={{
                  margin: 0,
                  fontSize: 28,
                  fontWeight: 500,
                  lineHeight: 1.22,
                  letterSpacing: "-0.014em",
                  color: "hsl(var(--foreground))",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {m.query}
              </h1>
            </div>

            <div />

            {/* 16 — highly relevant */}
            <div style={{ borderLeft: "1px solid hsl(var(--border))", paddingLeft: 24 }}>
              <div
                style={{
                  fontSize: 10.5,
                  color: "hsl(var(--muted-foreground))",
                  textTransform: "uppercase",
                  letterSpacing: "0.14em",
                  fontFamily: "var(--font-mono)",
                  marginBottom: 18,
                  lineHeight: 1,
                  height: 12,
                }}
              >
                {t("highlyRelevant")}
              </div>
              <div
                className="tabular"
                style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 96,
                  fontWeight: 500,
                  letterSpacing: "-0.035em",
                  lineHeight: 0.92,
                  color: "hsl(var(--foreground))",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {m.highlyRelevant}
              </div>
              <div
                style={{
                  marginTop: 18,
                  fontSize: 11.5,
                  color: "hsl(var(--muted-foreground))",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.02em",
                }}
              >
                +{m.closelyRelated} {t("closelyRelated")}
                <br />
                {t("from")} {fmtNum(m.papersEvaluated)} {t("papersScreened")}
              </div>
            </div>

            {/* 96% — coverage */}
            <div style={{ borderLeft: "1px solid hsl(var(--border))", paddingLeft: 24 }}>
              <div
                style={{
                  fontSize: 10.5,
                  color: "hsl(var(--muted-foreground))",
                  textTransform: "uppercase",
                  letterSpacing: "0.14em",
                  fontFamily: "var(--font-mono)",
                  marginBottom: 18,
                  lineHeight: 1,
                  height: 12,
                }}
              >
                {t("est")}
              </div>
              <div
                className="tabular"
                style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 96,
                  fontWeight: 500,
                  letterSpacing: "-0.035em",
                  lineHeight: 0.92,
                  color: "hsl(var(--foreground))",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {coverage !== undefined ? Math.round(coverage * 100) : "—"}
                {coverage !== undefined && (
                  <span style={{ fontSize: 56, marginLeft: 2 }}>%</span>
                )}
              </div>
              <div
                style={{
                  marginTop: 18,
                  fontSize: 11.5,
                  color: "hsl(var(--muted-foreground))",
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.02em",
                }}
              >
                {ciLow !== undefined && ciHigh !== undefined && (
                  <>
                    CI {Math.round(ciLow * 100)}–{Math.round(ciHigh * 100)}%
                    <br />
                  </>
                )}
                {t("confidence")}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Combined Tabs + filter in one slim row */}
      <nav
        className="rd-hero-swiss"
        style={{
          borderBottom: "1px solid hsl(var(--border))",
          background: "hsl(var(--background))",
          position: "sticky",
          top: 0,
          zIndex: 22,
        }}
      >
        <div
          style={{
            maxWidth: 1240,
            margin: "0 auto",
            padding: "0 56px",
            display: "flex",
            alignItems: "stretch",
            gap: 0,
          }}
        >
          {TAB_ITEMS.map((it) => {
            const active = it.value === tab
            return (
              <button
                key={it.value}
                type="button"
                onClick={() => setTab(it.value)}
                style={{
                  padding: "16px 0",
                  marginRight: 32,
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: "var(--font-mono)",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: active
                    ? "hsl(var(--foreground))"
                    : "hsl(var(--muted-foreground))",
                  borderBottom: active
                    ? "1.5px solid hsl(var(--foreground))"
                    : "1.5px solid transparent",
                  marginBottom: -1,
                  background: "transparent",
                  border: "none",
                  borderBottomWidth: 1.5,
                  borderBottomStyle: "solid",
                  borderBottomColor: active
                    ? "hsl(var(--foreground))"
                    : "transparent",
                  cursor: "pointer",
                }}
              >
                {it.label}
              </button>
            )
          })}
          <div style={{ flex: 1 }} />
          {tab === "findings" && (
            <>
              <span
                style={{
                  alignSelf: "center",
                  fontSize: 11,
                  color: "hsl(var(--muted-foreground))",
                  fontFamily: "var(--font-mono)",
                  marginRight: 20,
                }}
              >
                {resultsCount} / {data.papers.length}
              </span>
              <div style={{ alignSelf: "center", flex: "0 0 200px" }}>
                <SearchInput
                  placeholder={t("searchPlaceholder")}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </>
          )}
        </div>
      </nav>

      {/* Tier strip — only on findings */}
      {tab === "findings" && (
        <div
          className="rd-hero-swiss"
          style={{
            borderBottom: "1px solid hsl(var(--border))",
            background: "hsl(var(--background))",
          }}
        >
          <div
            style={{
              maxWidth: 1240,
              margin: "0 auto",
              padding: "14px 56px",
              display: "flex",
              alignItems: "center",
              gap: 0,
            }}
          >
            <div
              style={{
                fontSize: 10.5,
                fontFamily: "var(--font-mono)",
                color: "hsl(var(--muted-foreground))",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                marginRight: 28,
              }}
            >
              {t("filter")}
            </div>
            {TIER_PILLS.map((tier) => {
              const count =
                tier === "all" ? data.papers.length : tierCounts[tier as Tier] || 0
              if (count === 0 && tier !== "all") return null
              const active = tierFilter === tier
              return (
                <button
                  key={tier}
                  type="button"
                  onClick={() => setTierFilter(tier)}
                  style={{
                    display: "inline-flex",
                    alignItems: "baseline",
                    gap: 6,
                    padding: "4px 14px",
                    fontSize: 11.5,
                    fontFamily: "var(--font-mono)",
                    color: active
                      ? "hsl(var(--foreground))"
                      : "hsl(var(--muted-foreground))",
                    fontWeight: active ? 600 : 400,
                    borderRight: "1px solid hsl(var(--border))",
                    background: "transparent",
                    border: 0,
                    borderRightWidth: 1,
                    borderRightStyle: "solid",
                    borderRightColor: "hsl(var(--border))",
                    cursor: "pointer",
                  }}
                >
                  <span>{tier === "all" ? t("all") : t(tier)}</span>
                  <span
                    className="tabular"
                    style={{
                      fontSize: 10.5,
                      opacity: 0.7,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {count}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}
