// Port of TARGET v2-audit.jsx (360-419) — summarizeValueV2 / summarizeValue /
// isEmptyValue / renderValueV2.
//
// File is .tsx (not .ts) because renderValueV2 returns JSX. The master plan
// listed it as `audit-utils.ts` but the original TARGET helper returns React
// nodes, so a tsx extension is required.
//
// Added beyond TARGET: graceful tolerance for PRISMA-S step values that arrive
// as Python repr strings (e.g. `"{'performed': True, 'note': None}"`) — see
// parsePrismaPythonRepr in @/lib/prisma-titles. Both summarizeValueV2 and
// renderValueV2 first detect a `{`-prefixed string and parse it before
// delegating to the normal object path. This corner case is observed when a
// Python writer used `str(dict)` instead of `json.dumps`.

import * as React from "react"

import { fmtNum } from "@/lib/format"
import { parsePrismaPythonRepr } from "@/lib/prisma-titles"
import { fmtStr, getS, type Strings } from "@/lib/i18n"

const isPythonReprString = (v: unknown): v is string =>
  typeof v === "string" && /^\s*\{/.test(v)

/**
 * Map canonical English PRISMA notes / rationales emitted by the Python
 * pipeline → translated dict keys. Mirrors TARGET v2-audit.jsx 368-382 +
 * 435-449. Lookup is exact-string, returns the translated literal when the
 * active dict has a value, else the original English string.
 *
 * The keys (pv_*) live in src/lib/i18n.ts; STRINGS.en pass-through is set so
 * the English bundle visually matches the upstream canonical strings.
 */
const NOTE_KEY_BY_CANONICAL: Record<string, keyof Strings> = {
  "OpenAlex polite pool + Semantic Scholar (supplement). Audit may add PubMed/arXiv.":
    "pv_openalex_polite",
  "Multi-database search reduces single-source bias (Bramer 2018: 98.3% recall achievable with >=2 databases).":
    "pv_multidb_rationale",
  "Not queried by default. Available via audit tier add-ons if user enables Cochrane/ClinicalTrials.":
    "pv_study_registries",
  "Out of scope for this skill; pre-supplied via user citation seeds when relevant.":
    "pv_online_resources",
  "OpenAlex forward+backward citation chase up to configured max_hops.":
    "pv_citation_search",
  "Skill does not contact authors; relies on published records only.":
    "pv_contacts",
  "Strategy reproducible; same boolean expressions executed against each database.":
    "pv_full_strategy",
  "No restrictive filters by default; tier budget bounds the number of records returned.":
    "pv_no_filters",
  "No pre-validated hedges used; query plan uses LLM-decomposed terms.":
    "pv_no_hedges",
  "User-supplied force_include DOIs (config force_include) are merged into the result set.":
    "pv_force_include",
  "Not incremental within a single run; checkpoint enables manual re-run on demand.":
    "pv_not_incremental",
  "FederatedKG dedup: DOI (Level 1) -> arXiv ID (Level 2) -> PMID/OpenAlex/SS fallback -> (normalized_title, year) (last resort). E5b guard prevents same-title-different-DOI collapse.":
    "pv_dedup_method",
  "Provenance preserved per paper in sources[].": "pv_provenance",
}

/** Translate a canonical PRISMA note string when known; pass through otherwise. */
function translateNote(s: string): string {
  const dict = getS()
  const k = NOTE_KEY_BY_CANONICAL[s]
  if (k) {
    const v = dict[k] as string | undefined
    if (v) return v
  }
  return s
}

export interface SummarizeResult {
  text: string | React.ReactNode
  sourceKey: string | null
}

/**
 * Pick the most-useful one-line summary for a PRISMA-S step value and report
 * which key produced it (so the detail panel can skip that key to avoid
 * duplication). Priority order mirrors TARGET v2-audit.jsx (361-383).
 *
 * String-valued summaries (note / rationale / method) are routed through
 * `translateNote()` so canonical English notes appear in the active language.
 */
export function summarizeValueV2(v: unknown): SummarizeResult {
  // Tolerate Python repr strings — parse and re-enter.
  if (isPythonReprString(v)) {
    return summarizeValueV2(parsePrismaPythonRepr(v))
  }
  if (!v || typeof v !== "object") return { text: "", sourceKey: null }
  const obj = v as Record<string, unknown>
  const dict = getS()

  const tryKey = (
    k: string,
    render?: (x: unknown) => string,
  ): SummarizeResult | null => {
    const val = obj[k]
    if (isEmptyValue(val)) return null
    if (render) return { text: render(val), sourceKey: k }
    // Default path: translate canonical English notes via the noteMap.
    return { text: translateNote(String(val)), sourceKey: k }
  }

  const primaryPrefix =
    (dict.fl_primary as string | undefined) || "Primary"

  return (
    tryKey("note") ||
    tryKey("rationale") ||
    tryKey("method") ||
    tryKey("primary", (x) => `${primaryPrefix}: ${String(x)}`) ||
    tryKey("databases", (x) =>
      Array.isArray(x) ? x.join(", ") : String(x),
    ) ||
    tryKey("queries", (x) =>
      fmtStr(dict.pv_queries || "{n} queries", {
        n: Array.isArray(x) ? x.length : 0,
      }),
    ) ||
    tryKey("filters_applied", (x) =>
      Array.isArray(x) ? x.join(", ") : String(x),
    ) ||
    tryKey("methods", (x) =>
      Array.isArray(x) ? x.join(", ") : String(x),
    ) ||
    tryKey("outputs_produced", (x) =>
      fmtStr(dict.pv_outputs || "{n} outputs", {
        n: Array.isArray(x) ? x.length : 0,
      }),
    ) ||
    (obj.records_screened !== undefined
      ? {
          text: fmtStr(dict.pv_records_screened || "{n} records screened", {
            n: String(obj.records_screened),
          }),
          sourceKey: "records_screened",
        }
      : null) ||
    tryKey("tool") ||
    tryKey("format") ||
    tryKey("search_id") || { text: "", sourceKey: null }
  )
}

/** Legacy alias kept for any caller that still expects the bare string form. */
export function summarizeValue(v: unknown): string | React.ReactNode {
  return summarizeValueV2(v).text
}

export function isEmptyValue(v: unknown): boolean {
  if (v === null || v === undefined || v === "") return true
  if (Array.isArray(v) && v.length === 0) return true
  return false
}

/**
 * Detail-cell value renderer. Mirrors TARGET v2-audit.jsx (397-419) — no
 * stringified-array dumps, monospaced primitives, badge chips for arrays,
 * pretty-printed JSON for nested objects. Python repr strings are transparently
 * parsed and re-rendered.
 */
export function renderValueV2(v: unknown): React.ReactNode {
  if (isPythonReprString(v)) {
    return renderValueV2(parsePrismaPythonRepr(v))
  }
  if (v === null || v === undefined || v === "") {
    return (
      <span style={{ color: "hsl(var(--muted-foreground))" }}>—</span>
    )
  }
  if (typeof v === "boolean") {
    return (
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          color: v
            ? "hsl(var(--foreground))"
            : "hsl(var(--muted-foreground))",
        }}
      >
        {v ? "true" : "false"}
      </span>
    )
  }
  if (typeof v === "number") {
    return (
      <span
        className="tabular"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {fmtNum(v)}
      </span>
    )
  }
  if (Array.isArray(v)) {
    if (v.length === 0) {
      return (
        <span
          style={{
            color: "hsl(var(--muted-foreground))",
            fontStyle: "italic",
          }}
        >
          {getS().none || "none"}
        </span>
      )
    }
    return (
      <span style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        {v.map((x, i) => (
          <span
            key={i}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              padding: "2px 7px",
              borderRadius: 4,
              background: "hsl(var(--muted))",
              color: "hsl(var(--foreground))",
            }}
          >
            {String(x)}
          </span>
        ))}
      </span>
    )
  }
  if (typeof v === "string") {
    // Mirror TARGET v2-audit.jsx (432-450): when a canonical PRISMA-S note
    // string is rendered as a stand-alone detail value (not via summarizeValueV2),
    // translate it through the same noteMap so detail and summary stay
    // consistent. Unknown strings fall through to the generic <span> below.
    const translated = translateNote(v)
    if (translated !== v) return <span>{translated}</span>
  }
  if (typeof v === "object") {
    return (
      <pre
        style={{
          margin: 0,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          background: "hsl(var(--muted))",
          padding: 8,
          borderRadius: 4,
          overflow: "auto",
        }}
      >
        {JSON.stringify(v, null, 2)}
      </pre>
    )
  }
  return <span>{String(v)}</span>
}
