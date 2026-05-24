// PRISMA-S step metadata and status helpers, ported 1:1 from TARGET
// redesign/app-3-tabs.jsx (lines 157-182).

import type { PrismaStepValue } from "./types"

export type PrismaPhase = "Query" | "Discovery" | "Strategy" | "Audit"

export interface PrismaTitleMeta {
  phase: PrismaPhase
  title: string
}

export const PRISMA_TITLES: Record<string, PrismaTitleMeta> = {
  "1_database_information": { phase: "Query", title: "Database information" },
  "2_multi_database_searching": { phase: "Query", title: "Multi-database searching" },
  "3_study_registries": { phase: "Query", title: "Study registries" },
  "4_online_resources_browsing": { phase: "Discovery", title: "Online resources browsing" },
  "5_citation_searching": { phase: "Discovery", title: "Citation searching" },
  "6_contacts": { phase: "Discovery", title: "Contacts" },
  "7_other_methods": { phase: "Discovery", title: "Other methods" },
  "8_full_search_strategies": { phase: "Strategy", title: "Full search strategies" },
  "9_limits_and_restrictions": { phase: "Strategy", title: "Limits and restrictions" },
  "10_search_filters": { phase: "Strategy", title: "Search filters" },
  "11_prior_work": { phase: "Strategy", title: "Prior work" },
  "12_updates": { phase: "Strategy", title: "Updates" },
  "13_dates_of_searches": { phase: "Audit", title: "Dates of searches" },
  "14_total_records": { phase: "Audit", title: "Total records" },
  "15_deduplication": { phase: "Audit", title: "Deduplication" },
  "16_record_management": { phase: "Audit", title: "Record management" },
}

export const PHASE_ORDER: readonly PrismaPhase[] = [
  "Query",
  "Discovery",
  "Strategy",
  "Audit",
] as const

export interface StatusOf {
  label: string
  positive: boolean
}

export function statusOf(value: PrismaStepValue | undefined | null): StatusOf | null {
  if (!value || typeof value !== "object") return null
  if ("performed" in value) {
    const positive = value.performed === true
    return { label: positive ? "Performed" : "Not performed", positive }
  }
  if ("queried" in value) {
    const positive = value.queried === true
    return { label: positive ? "Queried" : "Not queried", positive }
  }
  return null
}

/**
 * Best-effort parser for PRISMA log values that arrive as Python repr strings
 * (e.g. `"{'performed': True, 'note': None}"`) instead of JSON. Converts the
 * three differing literals (`'` → `"`, `True` → `true`, `False` → `false`,
 * `None` → `null`) and then JSON.parse-es. Returns `{}` on failure and emits a
 * console warning so the issue surfaces.
 *
 * This guards the corner case where Python's `json.dumps` was bypassed in
 * favor of `str(dict)`; the rest of the normalize pipeline expects real
 * objects.
 */
export function parsePrismaPythonRepr(s: string): PrismaStepValue {
  try {
    return JSON.parse(
      s
        .replace(/'/g, '"')
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false")
        .replace(/\bNone\b/g, "null"),
    ) as PrismaStepValue
  } catch (e) {
    // eslint-disable-next-line no-console
    console.warn("parsePrismaPythonRepr failed", e, s.slice(0, 200))
    return {}
  }
}
