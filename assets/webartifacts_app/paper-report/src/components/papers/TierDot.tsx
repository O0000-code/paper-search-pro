// Tier dot — solid circle in tier color. Ported 1:1 from TARGET
// redesign/app-2-papers.jsx (3-26).

import type { Tier } from "@/lib/types"

const TIER_TO_CHART: Record<Tier, number> = {
  Foundational: 1,
  High: 2,
  Moderate: 3,
  Emerging: 4,
  Peripheral: 5,
}

export interface TierDotProps {
  tier: Tier
  size?: number
}

export function TierDot({ tier, size = 8 }: TierDotProps) {
  return (
    <span
      title={tier}
      aria-label={tier + " tier"}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: `hsl(var(--chart-${TIER_TO_CHART[tier]}))`,
        flexShrink: 0,
      }}
    />
  )
}
