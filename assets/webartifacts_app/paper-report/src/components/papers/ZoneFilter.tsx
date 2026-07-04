// Zone (journal-rank) filter (delta5) — pure front-end post-hoc partition filter.
// 1:1 port of TARGET redesign/app-2-papers.jsx (128-197). Same visual language
// as the relevance-tier chips (mono text chip + count); NOT a floating popover.
//
// Presets: Q1 / ≥Q2 / ≥Q3 (CAS platform → 1区 / ≥2区 / ≥3区). No "All" chip
// (redundant with the tier row's 全部). Clicking the active preset resets to All.
// Selecting a specific tier excludes unranked journals ("only Q1" = pure Q1).

import type { CSSProperties } from "react"

import type { NormalizedPaper } from "@/lib/types"
import { t } from "@/lib/i18n"

import { quartileNum } from "./JournalRank"

export type RankPlatform = "cas" | "jcr" | "sjr"

export interface ZoneFilterValue {
  platform: RankPlatform
  quartiles: number[]
  includeUnranked: boolean
}

// Default = no filtering (all quartiles + unranked), platform from the
// backend/config display default (window.__rankSource__), falling back to jcr.
export function defaultZone(): ZoneFilterValue {
  const v =
    typeof window !== "undefined"
      ? (window as { __rankSource__?: string }).__rankSource__
      : undefined
  const platform: RankPlatform = v === "cas" || v === "sjr" ? v : "jcr"
  return { platform, quartiles: [1, 2, 3, 4], includeUnranked: true }
}

// Which quartile bucket a paper falls into on the active platform: JCR/SJR map
// Q1-Q4 → 1-4, CAS uses the tier directly. No data on that platform → null.
export function passesZone(
  paper: NormalizedPaper,
  zf: ZoneFilterValue | null | undefined,
): boolean {
  if (!zf) return true
  if (zf.quartiles.length >= 4 && zf.includeUnranked) return true // no filtering
  const rank = paper.journalRank
  let q: number | null = null
  if (rank) {
    if (zf.platform === "jcr" && rank.jcr && rank.jcr.quartile)
      q = quartileNum(rank.jcr.quartile)
    else if (zf.platform === "cas" && rank.cas && rank.cas.tier)
      q = rank.cas.tier
    else if (zf.platform === "sjr" && rank.sjr && rank.sjr.best_quartile)
      q = quartileNum(rank.sjr.best_quartile)
  }
  if (q == null) return zf.includeUnranked
  return zf.quartiles.includes(q)
}

interface Preset {
  key: string
  label: string
  qs: number[]
  unranked: boolean
}

export interface ZoneFilterProps {
  value: ZoneFilterValue
  onChange: (next: ZoneFilterValue) => void
  /** Papers to count against — MUST be the tier+threshold-filtered set BEFORE
      zone filtering, so counts mirror the relevance row's totals. */
  papers: NormalizedPaper[]
  variant?: "divider" | "underline"
  style?: CSSProperties
}

export function ZoneFilter({
  value,
  onChange,
  papers,
  variant = "divider",
  style,
}: ZoneFilterProps) {
  const zf = value
  const isCas = zf.platform === "cas"
  const u = isCas ? t("tierZone") : ""
  const q = (n: number) => (isCas ? `${n}${u}` : `Q${n}`)
  const presets: Preset[] = [
    { key: "q1", label: q(1), qs: [1], unranked: false },
    { key: "q2", label: "≥" + q(2), qs: [1, 2], unranked: false },
    { key: "q3", label: "≥" + q(3), qs: [1, 2, 3], unranked: false },
  ]
  const ALL = { quartiles: [1, 2, 3, 4], includeUnranked: true }
  const cur = (() => {
    const k = [...zf.quartiles].sort().join("")
    if (zf.includeUnranked && k === "1234") return "all"
    return (
      ({ "1": "q1", "12": "q2", "123": "q3", "1234": "q3" } as Record<
        string,
        string
      >)[k] || "all"
    )
  })()
  const countFor = (pr: Preset) =>
    papers.filter((p) =>
      passesZone(p, {
        platform: zf.platform,
        quartiles: pr.qs,
        includeUnranked: pr.unranked,
      }),
    ).length
  const underline = variant === "underline"

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: underline ? 14 : 0,
        fontSize: 11.5,
        ...style,
      }}
    >
      {presets.map((pr, i) => {
        const active = cur === pr.key
        return (
          <button
            key={pr.key}
            type="button"
            onClick={() =>
              onChange(
                active
                  ? { ...zf, ...ALL }
                  : { ...zf, quartiles: pr.qs, includeUnranked: pr.unranked },
              )
            }
            style={{
              display: "inline-flex",
              alignItems: "baseline",
              gap: underline ? 5 : 6,
              padding: underline ? "4px 0" : "4px 14px",
              fontSize: 11.5,
              fontFamily: "var(--font-mono)",
              background: "transparent",
              border: 0,
              cursor: "pointer",
              color: active
                ? "hsl(var(--foreground))"
                : "hsl(var(--muted-foreground))",
              fontWeight: active ? 600 : 400,
              // divider: hairline between adjacent chips only (not after last);
              // underline: active-state bottom rule. Explicit longhand after
              // `border: 0` to avoid shorthand/longhand ordering ambiguity.
              ...(!underline && i < presets.length - 1
                ? {
                    borderRightWidth: 1,
                    borderRightStyle: "solid" as const,
                    borderRightColor: "hsl(var(--border))",
                  }
                : {}),
              ...(underline
                ? {
                    borderBottomWidth: 1,
                    borderBottomStyle: "solid" as const,
                    borderBottomColor: active
                      ? "hsl(var(--foreground))"
                      : "transparent",
                  }
                : {}),
            }}
          >
            <span>{pr.label}</span>
            <span
              className="tabular"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                opacity: 0.75,
              }}
            >
              {countFor(pr)}
            </span>
          </button>
        )
      })}
    </div>
  )
}
