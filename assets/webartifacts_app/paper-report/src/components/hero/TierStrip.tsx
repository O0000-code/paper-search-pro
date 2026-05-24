// Tier breakdown strip — sits under Hero.
//
// 1:1 port of TARGET redesign/app-1-hero.jsx TierStrip (209-250).
// Faint muted background with hairline bottom border; pill buttons for each
// non-empty tier (mono number + tier label) with an "active" highlight
// (subtle background + inset border). Trailing right-aligned text
// toggles between total-count and "Show all tiers" affordance.

import { TIER_ORDER } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { Tier } from "@/lib/types"

export type TierFilter = "all" | Tier

export interface TierStripProps {
  counts: Partial<Record<Tier, number>>
  total: number
  active: TierFilter
  onPick: (next: TierFilter) => void
}

export function TierStrip({ counts, total, active, onPick }: TierStripProps) {
  return (
    <div
      style={{
        background: "hsl(var(--muted) / 0.4)",
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
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "hsl(var(--muted-foreground))",
            fontWeight: 500,
          }}
        >
          {t("tier")}
        </div>
        {TIER_ORDER.map((tier) => {
          const n = counts[tier] || 0
          if (n === 0) return null
          const isActive = active === tier
          const isAll = active === "all"
          return (
            <button
              key={tier}
              type="button"
              onClick={() => onPick(isActive ? "all" : tier)}
              style={{
                display: "inline-flex",
                alignItems: "baseline",
                gap: 7,
                padding: "6px 10px",
                borderRadius: 5,
                background: isActive ? "hsl(var(--background))" : "transparent",
                boxShadow: isActive ? "inset 0 0 0 1px hsl(var(--border))" : "none",
                opacity: isAll || isActive ? 1 : 0.55,
                transition: "background .12s, opacity .12s",
                border: 0,
                cursor: "pointer",
                font: "inherit",
                color: "hsl(var(--foreground))",
              }}
            >
              <span
                style={{
                  fontSize: 17,
                  fontWeight: 600,
                  fontFamily: "var(--font-mono)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {n}
              </span>
              <span style={{ fontSize: 12, color: "hsl(var(--muted-foreground))" }}>
                {t(tier)}
              </span>
            </button>
          )
        })}
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => onPick("all")}
          style={{
            fontSize: 11.5,
            color: "hsl(var(--muted-foreground))",
            padding: "4px 8px",
            borderRadius: 4,
            background: "transparent",
            border: 0,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {active === "all" ? `${total} ${t("papersTotal")}` : t("showAllTiers")}
        </button>
      </div>
    </div>
  )
}
