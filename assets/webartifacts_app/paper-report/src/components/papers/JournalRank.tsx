// Journal rank (delta5) — multi-platform partition display.
// 1:1 port of TARGET redesign/app-2-papers.jsx (108-263) + the list-row inline
// variant from redesign/list-variants.jsx (JournalRankInline, 90-103).
// Converted to shadcn TSX: window.S → t(), 'Geist Mono' → var(--font-mono), typed.
//
// Three surfaces:
//   - JournalRank        card block   (PaperCardItem)   — single primary platform
//   - JournalRankInline  list meta     (PaperRowCatalog) — single primary, inline
//   - JournalRankDetail  detail sheet  (PaperSheet)      — all three platforms
//
// R-04: only jcr.impact_factor is labelled "IF". CAS / SJR are partitions only,
// never called an impact factor. The primary platform shown on cards/rows is
// window.__rankSource__ (backend/config default), falling back to jcr.

import * as React from "react"

import type { JournalRank as JournalRankData } from "@/lib/types"
import { t } from "@/lib/i18n"

export function quartileNum(q: string | null | undefined): number | null {
  const m = /Q([1-4])/.exec(q || "")
  return m ? parseInt(m[1], 10) : null
}

type RankSource = "cas" | "jcr" | "sjr"

interface PrimaryRank {
  plat: string
  tier: string
  ifv?: number | null
  top?: boolean
}

function rankSourcePref(): RankSource {
  const v =
    typeof window !== "undefined"
      ? (window as { __rankSource__?: string }).__rankSource__
      : undefined
  return v === "cas" || v === "sjr" ? v : "jcr"
}

// Preferred display platform first, then fall through to whichever other
// platforms matched. `t('casTier', {n})` gives "Tier 1" (en) / "1区" (zh).
export function primaryRank(
  rank: JournalRankData | null | undefined,
): PrimaryRank | null {
  if (!rank) return null
  const order: Record<RankSource, RankSource[]> = {
    cas: ["cas", "jcr", "sjr"],
    jcr: ["jcr", "cas", "sjr"],
    sjr: ["sjr", "jcr", "cas"],
  }
  const seq = order[rankSourcePref()]
  for (const k of seq) {
    if (k === "cas" && rank.cas && rank.cas.tier) {
      return {
        plat: t("casName"),
        tier: t("casTier", { n: rank.cas.tier }),
        top: rank.cas.top,
      }
    }
    if (k === "jcr" && rank.jcr && rank.jcr.quartile) {
      return { plat: "JCR", tier: rank.jcr.quartile, ifv: rank.jcr.impact_factor }
    }
    if (k === "sjr" && rank.sjr && rank.sjr.best_quartile) {
      return { plat: "SJR", tier: rank.sjr.best_quartile }
    }
  }
  return null
}

// Card block — quiet mono. Platform muted, tier value emphasized. No fills.
export function JournalRank({
  rank,
}: {
  rank: JournalRankData | null | undefined
}) {
  const p = primaryRank(rank)
  if (!p) return null
  return (
    <div
      style={{
        marginTop: 10,
        display: "inline-flex",
        alignItems: "baseline",
        gap: 4,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "hsl(var(--muted-foreground))",
          letterSpacing: "0.01em",
        }}
      >
        {p.plat}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          fontWeight: 500,
          color: "hsl(var(--foreground))",
        }}
      >
        {p.tier}
      </span>
      {p.ifv !== undefined && p.ifv !== null && (
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "hsl(var(--muted-foreground))",
            marginLeft: 2,
          }}
        >
          IF&nbsp;<span style={{ color: "hsl(var(--foreground))" }}>{p.ifv}</span>
        </span>
      )}
      {p.top && (
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 8.5,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            padding: "1px 4px",
            borderRadius: 3,
            boxShadow: "inset 0 0 0 1px hsl(var(--border))",
            color: "hsl(var(--muted-foreground))",
          }}
        >
          Top
        </span>
      )}
    </div>
  )
}

function InlineDot() {
  return (
    <span
      style={{
        color: "hsl(var(--muted-foreground))",
        opacity: 0.7,
        margin: "0 6px",
      }}
    >
      ·
    </span>
  )
}

// List-row inline variant (Catalog meta line) — leads with its own dot so it
// appends cleanly after the OA chip.
export function JournalRankInline({
  rank,
}: {
  rank: JournalRankData | null | undefined
}) {
  const p = primaryRank(rank)
  if (!p) return null
  return (
    <>
      <InlineDot />
      <span
        style={{
          display: "inline-flex",
          alignItems: "baseline",
          gap: 3,
          whiteSpace: "nowrap",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "hsl(var(--muted-foreground))",
          }}
        >
          {p.plat}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            fontWeight: 500,
            color: "hsl(var(--foreground))",
          }}
        >
          {p.tier}
        </span>
        {p.top && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 8,
              fontWeight: 600,
              color: "hsl(var(--muted-foreground))",
              letterSpacing: "0.04em",
            }}
          >
            TOP
          </span>
        )}
      </span>
    </>
  )
}

// Detail Sheet — all three platforms, rows ALWAYS shown (missing = N/A muted),
// localized attribution line built from whichever platforms matched. Matches
// the Metadata dl pattern (same label style / row rhythm).
export function JournalRankDetail({
  rank,
}: {
  rank: JournalRankData | null | undefined
}) {
  const r = rank || {}
  const none = t("rankNone")
  const hasCas = !!(r.cas && r.cas.tier)
  const hasJcr = !!(r.jcr && r.jcr.quartile)
  const hasSjr = !!(r.sjr && r.sjr.best_quartile)

  const casVal = hasCas
    ? t("casTier", { n: r.cas!.tier }) + (r.cas!.top ? " · Top" : "")
    : none
  const jcrVal = hasJcr
    ? r.jcr!.quartile +
      (r.jcr!.impact_factor != null ? ` · IF ${r.jcr!.impact_factor}` : "")
    : none
  const sjrVal = hasSjr
    ? r.sjr!.best_quartile + (r.sjr!.sjr != null ? ` · ${r.sjr!.sjr}` : "")
    : none

  const rows: Array<[string, string, boolean]> = [
    [t("casName"), casVal, hasCas],
    ["JCR", jcrVal, hasJcr],
    ["SJR", sjrVal, hasSjr],
  ]

  const owners: string[] = []
  if (hasCas) owners.push(t("ownerCas"))
  if (hasJcr) owners.push("Clarivate")
  if (hasSjr) owners.push("SCImago")
  const hasAny = owners.length > 0

  return (
    <section
      style={{
        marginTop: 24,
        borderTop: "1px solid hsl(var(--border))",
        paddingTop: 20,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "hsl(var(--muted-foreground))",
          marginBottom: 10,
        }}
      >
        {t("journalRankLabel")}
      </div>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "120px 1fr",
          gap: "6px 16px",
          fontSize: 12.5,
        }}
      >
        {rows.map(([k, v, has], i) => (
          <React.Fragment key={i}>
            <dt style={{ color: "hsl(var(--muted-foreground))" }}>{k}</dt>
            <dd
              style={{
                margin: 0,
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                color: has
                  ? "hsl(var(--foreground))"
                  : "hsl(var(--muted-foreground) / 0.6)",
              }}
            >
              {v}
            </dd>
          </React.Fragment>
        ))}
      </dl>
      {hasAny ? (
        <p
          style={{
            marginTop: 10,
            fontSize: 10.5,
            lineHeight: 1.5,
            color: "hsl(var(--muted-foreground))",
          }}
        >
          {t("rankCopyrightPre")}
          {owners.join(" / ")}
          {t("rankCopyrightPost")}
        </p>
      ) : (
        <p
          style={{
            marginTop: 10,
            fontSize: 10.5,
            lineHeight: 1.5,
            color: "hsl(var(--muted-foreground) / 0.7)",
          }}
        >
          {t("rankNoneNote")}
        </p>
      )}
    </section>
  )
}
