// Port of TARGET v2-methods.jsx TierAllocation (332-411).
// Headline + proportional segmented bar + per-tier callouts — all div+flex,
// no chart library.

import { useMemo } from "react"
import { ArrowRight } from "lucide-react"

import { SimpleTooltip } from "@/components/adapters/SimpleTooltip"
import { fmtNum, TIER_DESC, TIER_ORDER } from "@/lib/format"
import { getS, t } from "@/lib/i18n"
import type { NormalizedPaper, Tier } from "@/lib/types"

// Map tier → i18n key for its description. Falls back to TIER_DESC English.
const TIER_DESC_KEY: Record<Tier, string> = {
  Foundational: "foundationalDesc",
  High: "highDesc",
  Moderate: "moderateDesc",
  Emerging: "emergingDesc",
  Peripheral: "peripheralDesc",
}

function tierLabel(tier: Tier): string {
  const dict = getS() as Record<string, string>
  return dict[tier] || tier
}

function tierDesc(tier: Tier): string {
  const dict = getS() as Record<string, string>
  return dict[TIER_DESC_KEY[tier]] || TIER_DESC[tier]
}

export interface TierAllocationProps {
  papers: NormalizedPaper[]
  totalScreened: number
  highlyRelevant: number
  closelyRelated: number
}

export function TierAllocation({
  papers,
  totalScreened,
  highlyRelevant,
  closelyRelated,
}: TierAllocationProps) {
  const counts = useMemo(() => {
    const c: Record<Tier, number> = {
      Foundational: 0,
      High: 0,
      Moderate: 0,
      Emerging: 0,
      Peripheral: 0,
    }
    for (const p of papers) {
      c[p.tier] = (c[p.tier] || 0) + 1
    }
    return c
  }, [papers])

  const total = TIER_ORDER.reduce((s, t) => s + (counts[t] || 0), 0)
  if (total === 0) return null

  const segments = TIER_ORDER.map((tier, i) => ({
    tier,
    count: counts[tier] || 0,
    color: `hsl(var(--chart-${i + 1}))`,
  })).filter((s) => s.count > 0)

  const signal = highlyRelevant + closelyRelated
  const signalPct = totalScreened
    ? Math.round((signal / totalScreened) * 100)
    : 0

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 18,
          gap: 24,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
          <span
            className="tabular-nums"
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 36,
              fontWeight: 500,
              letterSpacing: "-0.02em",
              lineHeight: 0.95,
              color: "hsl(var(--foreground))",
            }}
          >
            {fmtNum(totalScreened)}
          </span>
          <span
            style={{
              fontSize: 13,
              color: "hsl(var(--muted-foreground))",
              fontFamily: "var(--font-sans)",
            }}
          >
            {t("paperScreened")}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            fontSize: 12,
            color: "hsl(var(--muted-foreground))",
            fontFamily: "var(--font-sans)",
          }}
        >
          <ArrowRight
            style={{
              width: 13,
              height: 13,
              alignSelf: "center",
            }}
          />
          <span
            className="tabular-nums"
            style={{
              fontFamily: "var(--font-mono)",
              color: "hsl(var(--foreground))",
              fontWeight: 600,
            }}
          >
            {signal}
          </span>
          <span>{t("withRelevance")}</span>
          <span style={{ opacity: 0.5 }}>·</span>
          <span
            className="tabular-nums"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {signalPct}%
          </span>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          height: 20,
          borderRadius: 4,
          overflow: "hidden",
          gap: 2,
          marginBottom: 16,
        }}
      >
        {segments.map((s) => (
          <SimpleTooltip
            key={s.tier}
            content={`${tierLabel(s.tier)}: ${s.count} (${Math.round(
              (s.count / total) * 100,
            )}%)`}
          >
            <div
              style={{
                flex: s.count,
                background: s.color,
                minWidth: 3,
                cursor: "help",
              }}
            />
          </SimpleTooltip>
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${segments.length}, 1fr)`,
          gap: 12,
        }}
      >
        {segments.map((s) => {
          const pct = Math.round((s.count / total) * 100)
          return (
            <div
              key={s.tier}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                paddingTop: 12,
                borderTop: `2px solid ${s.color}`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  gap: 8,
                }}
              >
                <span
                  className="tabular-nums"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 18,
                    fontWeight: 600,
                    letterSpacing: "-0.01em",
                    color: "hsl(var(--foreground))",
                  }}
                >
                  {s.count}
                </span>
                <span
                  className="tabular-nums"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "hsl(var(--muted-foreground))",
                  }}
                >
                  {pct}%
                </span>
              </div>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: "hsl(var(--foreground))",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {tierLabel(s.tier)}
              </div>
              <div
                style={{
                  fontSize: 11,
                  lineHeight: 1.4,
                  color: "hsl(var(--muted-foreground))",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {tierDesc(s.tier)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
