// Formatting + tier helpers, ported 1:1 from TARGET redesign/lib.jsx (76-112).
//
// Raw RCS values are integers on a 0-10 scale; tier thresholds reflect the
// canonical fraction cutoffs (0.85 / 0.70 / 0.55 / 0.45) used by every other
// surface in the report.

import type { Tier } from "./types"

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  return new Intl.NumberFormat("en-US").format(n)
}

export function fmtPct(
  n: number | null | undefined,
  digits = 0,
): string {
  if (n === null || n === undefined) return "—"
  return (n * 100).toFixed(digits) + "%"
}

/** raw rcs is on a 0-10 scale → display as 0.00-1.00 */
export function fmtRcs(rcs: number | null | undefined): string {
  if (rcs === null || rcs === undefined) return "—"
  return (rcs / 10).toFixed(2)
}

/** Tier from raw rcs (0-10 scale). */
export function rcsTier(rcs: number): Tier {
  if (rcs >= 8.5) return "Foundational"
  if (rcs >= 7.0) return "High"
  if (rcs >= 5.5) return "Moderate"
  if (rcs >= 4.5) return "Emerging"
  return "Peripheral"
}

/**
 * Display-only short author form:
 *   1 author  → full name
 *   2 authors → "First1 First2 LastN1 & LastN2"   (uses last name of #2)
 *   3+ authors → "First1 Last1 et al."  (non-breaking spaces)
 */
export function shortAuthors(full: string[] | null | undefined): string | null {
  if (!full || full.length === 0) return null
  const lastName = (n: string): string => {
    const parts = n.replace(/\.$/, "").split(/\s+/)
    return parts[parts.length - 1] || n
  }
  if (full.length === 1) return full[0]
  if (full.length === 2) return `${full[0]} & ${lastName(full[1])}`
  return `${full[0]} et al.`
}

export const TIER_ORDER: Tier[] = [
  "Foundational",
  "High",
  "Moderate",
  "Emerging",
  "Peripheral",
]

export const TIER_DESC: Record<Tier, string> = {
  Foundational: "Field-defining; ≥0.85 RCS",
  High: "Strong relevance; 0.70–0.85",
  Moderate: "Adjacent or methods; 0.55–0.70",
  Emerging: "Newer or peripheral; 0.45–0.55",
  Peripheral: "Surfaced but low signal; <0.45",
}
