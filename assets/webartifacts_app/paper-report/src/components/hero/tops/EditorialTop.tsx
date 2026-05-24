// Editorial Top — 1:1 port of TARGET tops/top-1-editorial.jsx.
//
// Magazine restraint: 940px narrow column, 36px confident H1 with no icon,
// finding expressed as a single sentence (mono numerics inline). Tabs are
// text-link style (medium weight, underlined active). Findings toolbar uses
// text-link Tier chips and a Cards/List ToggleGroup.

import { FileText, Layers } from "lucide-react"

import { SearchInput } from "@/components/adapters/SearchInput"
import { SegmentedToggle } from "@/components/adapters/SegmentedToggle"
import { fmtNum } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { NormalizedData, Tier } from "@/lib/types"

import type { TierFilter } from "../TierStrip"

export interface EditorialTopProps {
  data: NormalizedData
  tab: string
  setTab: (next: string) => void
  search: string
  setSearch: (next: string) => void
  view: string
  setView: (next: string) => void
  tierFilter: TierFilter
  setTierFilter: (next: TierFilter) => void
  tierCounts: Partial<Record<Tier, number>>
}

export function EditorialTop({
  data,
  tab,
  setTab,
  search,
  setSearch,
  view,
  setView,
  tierFilter,
  setTierFilter,
  tierCounts,
}: EditorialTopProps) {
  const m = data.meta
  const date = (m.generatedAt || "").slice(0, 10)
  const coverage = m.coverage
  const ciLow = m.coverageCi?.[0]
  const ciHigh = m.coverageCi?.[1]

  // Tab labels are i18n-bound (computed at runtime via `t()`).
  const TAB_ITEMS = [
    { value: "findings", label: t("findings") },
    { value: "methods", label: t("methods") },
    { value: "audit", label: t("auditLog") },
  ]

  const tierChips: { tier: TierFilter; label: string; count: number }[] = [
    { tier: "all", label: t("all"), count: data.papers.length },
    { tier: "Foundational", label: t("Foundational"), count: tierCounts.Foundational || 0 },
    { tier: "High", label: t("High"), count: tierCounts.High || 0 },
    { tier: "Moderate", label: t("Moderate"), count: tierCounts.Moderate || 0 },
    { tier: "Emerging", label: t("Emerging"), count: tierCounts.Emerging || 0 },
    { tier: "Peripheral", label: t("Peripheral"), count: tierCounts.Peripheral || 0 },
  ]

  return (
    <>
      <header
        className="rd-hero-editorial"
        style={{
          borderBottom: "1px solid hsl(var(--border))",
          background: "hsl(var(--background))",
        }}
      >
        <div style={{ maxWidth: 940, margin: "0 auto", padding: "64px 40px 56px" }}>
          {/* Meta strip — single line, single weight */}
          <div
            style={{
              fontSize: 10.5,
              color: "hsl(var(--muted-foreground))",
              fontFamily: "var(--font-mono)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              display: "flex",
              gap: 22,
              marginBottom: 36,
              flexWrap: "wrap",
            }}
          >
            <span style={{ whiteSpace: "nowrap" }}>
              {m.skillVersion || "paper-search-pro"}
            </span>
            <span style={{ whiteSpace: "nowrap" }}>{date}</span>
            <span style={{ whiteSpace: "nowrap" }}>{m.tier || "standard"} {t("tierLabel")}</span>
            {m.searchId && (
              <span style={{ whiteSpace: "nowrap", opacity: 0.55 }}>{m.searchId}</span>
            )}
          </div>

          {/* Query — confident H1, no chrome */}
          <h1
            style={{
              margin: 0,
              fontSize: 36,
              fontWeight: 500,
              lineHeight: 1.18,
              letterSpacing: "-0.018em",
              color: "hsl(var(--foreground))",
              maxWidth: "24ch",
              fontFamily: "var(--font-sans)",
            }}
          >
            {m.query}
          </h1>

          {/* Finding — one sentence, no boxes */}
          <p
            style={{
              margin: "36px 0 0",
              fontSize: 17,
              lineHeight: 1.55,
              color: "hsl(var(--foreground))",
              maxWidth: "60ch",
              fontWeight: 400,
              fontFamily: "var(--font-sans)",
            }}
          >
            {t("sentenceOf")}
            <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
              {fmtNum(m.papersEvaluated)}
            </span>
            {t("papersScreenedShort")}
            <strong style={{ fontWeight: 600 }}>
              {m.highlyRelevant} {t("areHighlyRelevant")}
            </strong>{" "}
            <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
              {m.closelyRelated}
            </span>{" "}
            {t("closelyRelatedCovering")}{" "}
            <strong style={{ fontWeight: 600 }}>
              {coverage !== undefined ? Math.round(coverage * 100) : "—"}%
            </strong>{" "}
            {t("ofTheField")}
            {ciLow !== undefined && ciHigh !== undefined && (
              <span style={{ color: "hsl(var(--muted-foreground))" }}>
                {" "}
                (CI {Math.round(ciLow * 100)}–{Math.round(ciHigh * 100)}%)
              </span>
            )}
            .
          </p>
        </div>
      </header>

      {/* Text-link tabs */}
      <nav
        className="rd-hero-editorial"
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
                  padding: "14px 0",
                  marginRight: 28,
                  fontSize: 13.5,
                  fontWeight: active ? 600 : 500,
                  whiteSpace: "nowrap",
                  color: active
                    ? "hsl(var(--foreground))"
                    : "hsl(var(--muted-foreground))",
                  borderBottom: active
                    ? "1.5px solid hsl(var(--foreground))"
                    : "1.5px solid transparent",
                  marginBottom: -1,
                  transition: "color .12s, border-color .12s",
                  background: "transparent",
                  border: 0,
                  borderBottomWidth: 1.5,
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
            }}
          >
            {m.skillVersion} · {date}
          </span>
        </div>
      </nav>

      {tab === "findings" && (
        <div
          className="rd-hero-editorial"
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
              gap: 18,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 11.5 }}>
              {tierChips
                .filter((t) => t.count > 0)
                .map(({ tier, label, count }) => {
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
                        padding: "4px 0",
                        color: active
                          ? "hsl(var(--foreground))"
                          : "hsl(var(--muted-foreground))",
                        fontWeight: active ? 600 : 400,
                        borderBottom: active
                          ? "1px solid hsl(var(--foreground))"
                          : "1px solid transparent",
                        background: "transparent",
                        border: 0,
                        borderBottomWidth: 1,
                        borderBottomStyle: "solid",
                        borderBottomColor: active
                          ? "hsl(var(--foreground))"
                          : "transparent",
                        cursor: "pointer",
                        font: "inherit",
                      }}
                    >
                      <span>{label}</span>
                      <span
                        className="tabular"
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10.5,
                          opacity: 0.8,
                        }}
                      >
                        {count}
                      </span>
                    </button>
                  )
                })}
            </div>
            <div style={{ flex: 1 }} />
            <div style={{ flex: "0 0 220px" }}>
              <SearchInput
                placeholder={t("searchPlaceholder")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <SegmentedToggle
              value={view}
              onValueChange={setView}
              items={[
                { value: "compact", label: t("list"), Icon: FileText },
                { value: "card", label: t("cards"), Icon: Layers },
              ]}
            />
          </div>
        </div>
      )}
    </>
  )
}
