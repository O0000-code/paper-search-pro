// Document / Preprint Top — 1:1 port of TARGET tops/top-3-document.jsx.
//
// arXiv-style title page: 780px centered column, bordered preprint badge,
// 32px sans H1, abstract-style paragraph with inline mono numerics, italic
// composition footnote with tier breakdown. Tabs use small-caps Roman
// numerals ("I. Findings", "II. Methods", "III. Audit log").

import { SearchInput } from "@/components/adapters/SearchInput"
import { ZoneFilter, type ZoneFilterValue } from "@/components/papers/ZoneFilter"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { NormalizedData, NormalizedPaper, Tier } from "@/lib/types"

import type { TierFilter } from "../TierStrip"

export interface DocumentTopProps {
  data: NormalizedData
  tab: string
  setTab: (next: string) => void
  search: string
  setSearch: (next: string) => void
  tierFilter: TierFilter
  setTierFilter: (next: TierFilter) => void
  tierCounts: Partial<Record<Tier, number>>
  zoneFilter: ZoneFilterValue
  setZoneFilter: (next: ZoneFilterValue) => void
  papersForZone: NormalizedPaper[]
  hasAnyRank: boolean
}

const TIER_PILLS: ("all" | Tier)[] = [
  "all",
  "Foundational",
  "High",
  "Moderate",
  "Emerging",
  "Peripheral",
]

export function DocumentTop({
  data,
  tab,
  setTab,
  search,
  setSearch,
  tierFilter,
  setTierFilter,
  tierCounts,
  zoneFilter,
  setZoneFilter,
  papersForZone,
  hasAnyRank,
}: DocumentTopProps) {
  const m = data.meta
  const date = (m.generatedAt || "").slice(0, 10)
  const coverage = m.coverage
  const ciLow = m.coverageCi?.[0]
  const ciHigh = m.coverageCi?.[1]

  // Tab labels are i18n-bound (computed at runtime via `t()`).
  const TAB_ITEMS = [
    { value: "findings", label: t("findingsRoman") },
    { value: "methods", label: t("methodsRoman") },
    { value: "audit", label: t("auditRoman") },
  ]

  const compositionEntries: [Tier, number][] = (
    [
      ["Foundational", tierCounts.Foundational],
      ["High", tierCounts.High],
      ["Moderate", tierCounts.Moderate],
      ["Emerging", tierCounts.Emerging],
      ["Peripheral", tierCounts.Peripheral],
    ] as [Tier, number | undefined][]
  )
    .filter(([, n]) => (n ?? 0) > 0)
    .map(([tierName, n]) => [tierName, n as number])

  return (
    <>
      <header
        className="rd-hero-document"
        style={{
          borderBottom: "1px solid hsl(var(--border))",
          background: "hsl(var(--background))",
        }}
      >
        <div
          style={{
            maxWidth: 780,
            margin: "0 auto",
            padding: "64px 40px 56px",
            textAlign: "left",
          }}
        >
          {/* preprint-style ID badge */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0,
              fontSize: 10.5,
              fontFamily: "var(--font-mono)",
              color: "hsl(var(--muted-foreground))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 4,
              padding: "4px 10px",
              marginBottom: 32,
            }}
          >
            <span style={{ color: "hsl(var(--foreground))", fontWeight: 600 }}>
              {t("discoveryReport")}
            </span>
            <span style={{ margin: "0 8px", opacity: 0.5 }}>·</span>
            <span>{m.searchId || m.skillVersion}</span>
          </div>

          {/* Big title */}
          <h1
            style={{
              margin: 0,
              fontSize: 32,
              fontWeight: 500,
              lineHeight: 1.22,
              letterSpacing: "-0.014em",
              color: "hsl(var(--foreground))",
              fontFamily: "var(--font-sans)",
            }}
          >
            {m.query}
          </h1>

          {/* Abstract block */}
          <div
            style={{
              marginTop: 36,
              paddingTop: 24,
              borderTop: "1px solid hsl(var(--border))",
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.14em",
                color: "hsl(var(--foreground))",
                marginBottom: 12,
              }}
            >
              {t("abstract")}
            </div>
            <p
              style={{
                margin: 0,
                fontSize: 14.5,
                lineHeight: 1.7,
                color: "hsl(var(--foreground))",
                fontFamily: "var(--font-sans)",
              }}
            >
              {t("docWeScreened")}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}
              >
                {fmtNum(m.papersEvaluated)}
              </span>
              {t("docPapersAndIdentified")}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}
              >
                {m.highlyRelevant}
              </span>
              {t("docAsHighlyRelevant")}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}
              >
                {m.closelyRelated}
              </span>
              {t("docAdditional")}
              {t("docModelEstimates")}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}
              >
                {coverage !== undefined ? Math.round(coverage * 100) : "—"}%
              </span>
              {ciLow !== undefined && ciHigh !== undefined && (
                <>
                  {" "}
                  (95% CI {Math.round(ciLow * 100)}–{Math.round(ciHigh * 100)}%){" "}
                </>
              )}
              {/* Strip the leading '%' from docRelevanceClause — we already
                  rendered '%' inline on the coverage number so it sits next
                  to it (EN: "99%"; ZH: "99%"). The dict keeps the '%' at the
                  start of docRelevanceClause for callers that render the
                  coverage number as a bare digit; we override that here to
                  preserve the original EN typography. */}
              {t("docRelevanceClause").replace(/^%\s*/, "")}
            </p>

            {/* Composition footnote */}
            <p
              style={{
                margin: "14px 0 0",
                fontSize: 12,
                lineHeight: 1.7,
                color: "hsl(var(--muted-foreground))",
                fontStyle: "italic",
              }}
            >
              {t("composition")}:{" "}
              {compositionEntries.map(([tierName, n], i, arr) => (
                <span key={tierName}>
                  <span
                    className="tabular"
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontStyle: "normal",
                    }}
                  >
                    {n}
                  </span>{" "}
                  {t(tierName).toLowerCase()}
                  {i < arr.length - 1 ? ", " : "."}
                </span>
              ))}
              {" · "}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontStyle: "normal" }}
              >
                {m.skillVersion}
              </span>
              {" · "}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", fontStyle: "normal" }}
              >
                {date}
              </span>
            </p>
          </div>
        </div>
      </header>

      {/* Tabs — small-caps academic */}
      <nav
        className="rd-hero-document"
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
            padding: "0 40px",
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
                  padding: "14px 18px",
                  fontSize: 13,
                  fontWeight: active ? 600 : 400,
                  color: active
                    ? "hsl(var(--foreground))"
                    : "hsl(var(--muted-foreground))",
                  borderBottom: active
                    ? "2px solid hsl(var(--foreground))"
                    : "2px solid transparent",
                  marginBottom: -1,
                  fontVariant: "small-caps",
                  background: "transparent",
                  border: 0,
                  borderBottomWidth: 2,
                  borderBottomStyle: "solid",
                  borderBottomColor: active
                    ? "hsl(var(--foreground))"
                    : "transparent",
                  cursor: "pointer",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {it.label}
              </button>
            )
          })}
          <div style={{ flex: 1 }} />
          <span
            style={{
              alignSelf: "center",
              fontSize: 11,
              color: "hsl(var(--muted-foreground))",
              fontFamily: "var(--font-mono)",
              padding: "0 0 0 18px",
            }}
          >
            §I · n={data.papers.length}
          </span>
        </div>
      </nav>

      {/* Findings toolbar */}
      {tab === "findings" && (
        <div
          className="rd-hero-document"
          style={{
            borderBottom: "1px solid hsl(var(--border))",
            background: "hsl(var(--background))",
          }}
        >
          <div
            style={{
              maxWidth: 1240,
              margin: "0 auto",
              padding: "14px 40px",
              display: "flex",
              alignItems: "center",
              gap: 0,
            }}
          >
            {/* Tier group — label + relevance-tier chips (left cluster).
                1:1 with TARGET top-3-document.jsx: tier group + zone filter on
                the left, search pushed to the far right by a flex spacer. */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  color: "hsl(var(--muted-foreground))",
                  fontFamily: "var(--font-mono)",
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  marginRight: 22,
                }}
              >
                {t("tier")}
              </span>
              {TIER_PILLS.map((tier) => {
                const count =
                  tier === "all"
                    ? data.papers.length
                    : tierCounts[tier as Tier] || 0
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
                      gap: 5,
                      fontSize: 12,
                      color: active
                        ? "hsl(var(--foreground))"
                        : "hsl(var(--muted-foreground))",
                      fontWeight: active ? 600 : 400,
                      borderBottom: active
                        ? "1px solid hsl(var(--foreground))"
                        : "none",
                      background: "transparent",
                      border: 0,
                      borderBottomWidth: active ? 1 : 0,
                      borderBottomStyle: "solid",
                      borderBottomColor: active
                        ? "hsl(var(--foreground))"
                        : "transparent",
                      cursor: "pointer",
                      padding: 0,
                      // Inherit the sans family WITHOUT the `font:` shorthand —
                      // `font: inherit` would reset the explicit fontSize:12
                      // above to the body's 16px (same trap as PaperSheet /
                      // TierStrip). The design uses 12px sans here.
                      fontFamily: "inherit",
                    }}
                  >
                    <span>
                      {tier === "all" ? t("all").toLowerCase() : t(tier).toLowerCase()}
                    </span>
                    <span
                      className="tabular"
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 10.5,
                        opacity: 0.7,
                      }}
                    >
                      {count}
                    </span>
                  </button>
                )
              })}
            </div>
            {/* Journal-rank zone filter — sibling after the tier group,
                marginLeft 34 (TARGET top-3-document.jsx). R-19 gated. */}
            {hasAnyRank && (
              <ZoneFilter
                variant="underline"
                value={zoneFilter}
                onChange={setZoneFilter}
                papers={papersForZone}
                style={{ marginLeft: 34 }}
              />
            )}
            <div style={{ flex: 1 }} />
            {/* Search — right-aligned (TARGET top-3-document.jsx) */}
            <div style={{ flex: "0 0 240px" }}>
              <SearchInput
                placeholder={t("searchWithin")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
        </div>
      )}
    </>
  )
}
