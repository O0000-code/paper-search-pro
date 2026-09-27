// Tier group header — mono uppercase section header with TierDot,
// count, divider rule, description and chevron.
// Direct port of TARGET redesign/app-2-papers.jsx (262-292).

import { ChevronDown, ChevronUp } from "lucide-react"

import type { Tier } from "@/lib/types"
import { TIER_DESC } from "@/lib/format"
import { getS } from "@/lib/i18n"

import { TierDot } from "./TierDot"

export interface TierHeaderProps {
  tier: Tier
  count: number
  collapsed: boolean
  onToggle: () => void
}

export function TierHeader({ tier, count, collapsed, onToggle }: TierHeaderProps) {
  // Map tier name → localized label / description via i18n dict.
  // delta3 ground truth (app-2-papers.jsx:275, 285): direct key lookup on
  // `window.S[tier]` for the label, and `window.S[tier.toLowerCase()+'Desc']`
  // for the description. Both fall back to the English baseline when the key
  // is missing.
  const S = getS() as Record<string, string>
  const tierLabel = S[tier] || tier
  const descKey = tier ? tier.toLowerCase() + "Desc" : ""
  const tierDesc = S[descKey] || TIER_DESC[tier]
  return (
    // Horizontal padding = the paper rows' padding, so the dot sits on the
    // same edge as `#01` and the chevron ends where the scores end. Centred
    // (not baseline) so the hairline and chevron sit on the label's midline.
    <div
      className="rd-tier-head"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "30px 16px 12px",
        cursor: "pointer",
      }}
      onClick={onToggle}
    >
      <TierDot tier={tier} size={9} />
      <span
        style={{
          fontSize: 11,
          fontWeight: 500,
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.14em",
          color: "hsl(var(--foreground))",
        }}
      >
        {tierLabel}
      </span>
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "hsl(var(--muted-foreground))",
          opacity: 0.7,
        }}
      >
        {count}
      </span>
      <div
        style={{
          flex: 1,
          minWidth: 12,
          height: 1,
          background: "hsl(var(--border))",
          margin: "0 4px",
        }}
      />
      {/* One line always (ellipsis on phones): a wrapped description would
          put the centred label between its two lines. */}
      <span
        title={tierDesc}
        style={{
          fontSize: 11,
          color: "hsl(var(--muted-foreground))",
          fontFamily: "var(--font-mono)",
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {tierDesc}
      </span>
      <span
        style={{
          color: "hsl(var(--muted-foreground))",
          display: "inline-flex",
          opacity: 0.6,
          // the glyph sits ~2px inside its box: pull it so its ink ends
          // on the same edge as the scores below
          marginRight: -2,
        }}
      >
        {collapsed ? (
          <ChevronDown style={{ width: 13, height: 13 }} />
        ) : (
          <ChevronUp style={{ width: 13, height: 13 }} />
        )}
      </span>
    </div>
  )
}
