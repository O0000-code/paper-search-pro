// Port of TARGET v2-audit.jsx (210-343) — single PRISMA-S step row.
//
// 6-column grid: status dot | #step | title | one-line summary | status badge |
// chevron. Click to toggle a detail panel that re-uses the same 6-column grid
// template (dt in col 3, dd spans col 4-7) so the dt/dd columns visually align
// with the row above.

import * as React from "react"
import { ChevronDown } from "lucide-react"

import type { PrismaStepValue } from "@/lib/types"
import {
  PRISMA_TITLES,
  parsePrismaPythonRepr,
  statusOf,
} from "@/lib/prisma-titles"
import { getS, t, type Strings } from "@/lib/i18n"
import {
  isEmptyValue,
  renderValueV2,
  summarizeValueV2,
} from "./audit-utils"
import { StatusDot } from "./StatusDot"

const GRID_TEMPLATE =
  "36px 40px minmax(0, 1.1fr) minmax(0, 2fr) 90px 24px"

export interface PrismaRowProps {
  stepKey: string
  value: PrismaStepValue
  divider: boolean
}

export function PrismaRow({ stepKey, value, divider }: PrismaRowProps) {
  const meta = PRISMA_TITLES[stepKey]
  const [open, setOpen] = React.useState(false)

  if (!meta) return null

  // If the value is a Python repr string, normalize once so all downstream
  // computations (statusOf / summarizeValueV2 / detailEntries) work uniformly.
  const normalizedValue: PrismaStepValue =
    typeof value === "string" && /^\s*\{/.test(value)
      ? parsePrismaPythonRepr(value)
      : value

  const stepNum = stepKey.split("_")[0]
  const step = stepNum.padStart(2, "0")
  const status = statusOf(normalizedValue)
  const isPerformed = !!status?.positive
  const isSkipped = !!(status && !status.positive)
  // Implicit: no boolean flag at all, but has data
  // (kept as a derived constant for clarity even though not directly used)
  const summary = summarizeValueV2(normalizedValue)
  const oneLine = summary.text

  // Translated title via `p_N` keys (e.g. `p_1` → "Database information" /
  // "数据库信息"). Fall back to PRISMA_TITLES.title when the dict has no
  // matching entry (defensive only — STRINGS.en owns all 16 p_* keys).
  const titleKey = `p_${stepNum}` as keyof Strings
  const dict = getS()
  const titleI18n = (dict[titleKey] as string | undefined) || meta.title

  const detailEntries = Object.entries(normalizedValue || {}).filter(
    ([k]) => {
      if (k === "performed" || k === "queried") return false
      if (k === summary.sourceKey) return false
      return true
    },
  )
  const hasDetail = detailEntries.some(([, v]) => !isEmptyValue(v))

  return (
    <div
      style={{
        borderBottom: divider ? "1px solid hsl(var(--border))" : "none",
      }}
    >
      <button
        onClick={() => hasDetail && setOpen((o) => !o)}
        disabled={!hasDetail}
        style={{
          display: "grid",
          gridTemplateColumns: GRID_TEMPLATE,
          gap: 16,
          alignItems: "center",
          width: "100%",
          textAlign: "left",
          padding: "13px 18px",
          background: "transparent",
          border: 0,
          cursor: hasDetail ? "pointer" : "default",
          font: "inherit",
          color: "hsl(var(--foreground))",
          transition: "background .1s",
        }}
        onMouseEnter={(e) => {
          if (hasDetail) {
            e.currentTarget.style.background =
              "hsl(var(--muted) / 0.4)"
          }
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent"
        }}
      >
        {/* Status indicator */}
        <span style={{ display: "flex", justifyContent: "center" }}>
          <StatusDot
            kind={
              isPerformed
                ? "performed"
                : isSkipped
                  ? "skipped"
                  : "implicit"
            }
          />
        </span>

        {/* Step number */}
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            fontWeight: 500,
            color: "hsl(var(--muted-foreground))",
          }}
        >
          #{step}
        </span>

        {/* Title */}
        <span
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: isSkipped
              ? "hsl(var(--muted-foreground))"
              : "hsl(var(--foreground))",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {titleI18n}
        </span>

        {/* One-line summary */}
        <span
          style={{
            fontSize: 12,
            color: "hsl(var(--muted-foreground))",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {oneLine || (isSkipped ? "—" : "")}
        </span>

        {/* Status badge */}
        <span style={{ display: "flex", justifyContent: "flex-end" }}>
          {isPerformed && (
            <span
              style={{
                fontSize: 10.5,
                fontFamily: "var(--font-mono)",
                color: "hsl(var(--foreground))",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                fontWeight: 500,
              }}
            >
              {t("performed")}
            </span>
          )}
          {isSkipped && (
            <span
              style={{
                fontSize: 10.5,
                fontFamily: "var(--font-mono)",
                color: "hsl(var(--muted-foreground))",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              {status?.label === "Not queried" ? t("notQueried") : t("skipped")}
            </span>
          )}
        </span>

        {/* Chevron */}
        <span
          style={{
            color: "hsl(var(--muted-foreground))",
            display: "flex",
            justifyContent: "center",
            opacity: hasDetail ? 1 : 0.25,
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform .15s",
          }}
        >
          <ChevronDown size={14} />
        </span>
      </button>

      {open && hasDetail && (
        <div
          style={{
            padding: "14px 18px 16px 18px",
            background: "hsl(var(--muted) / 0.35)",
            borderTop: "1px solid hsl(var(--border))",
          }}
        >
          <dl
            style={{
              margin: 0,
              display: "grid",
              gridTemplateColumns: GRID_TEMPLATE,
              columnGap: 16,
              rowGap: 10,
              alignItems: "baseline",
              fontSize: 12,
            }}
          >
            {detailEntries
              .filter(([, v]) => !isEmptyValue(v))
              .map(([k, v]) => {
                // Translated field label via `fl_<k>` (e.g. `fl_databases`).
                // If the dict has no matching entry, fall back to the
                // underscore-to-space transform that TARGET v2-audit.jsx
                // line 331 ships as default.
                const flKey = `fl_${k}` as keyof Strings
                const labelTxt =
                  (dict[flKey] as string | undefined) || k.replace(/_/g, " ")
                return (
                <React.Fragment key={k}>
                  <dt
                    style={{
                      gridColumn: "3 / 4",
                      color: "hsl(var(--muted-foreground))",
                      fontFamily: "var(--font-mono)",
                      fontSize: 10.5,
                      fontWeight: 500,
                      textTransform: "lowercase",
                      letterSpacing: "0.02em",
                    }}
                  >
                    {labelTxt}
                  </dt>
                  <dd
                    style={{
                      gridColumn: "4 / 7",
                      margin: 0,
                      color: "hsl(var(--foreground))",
                      lineHeight: 1.55,
                      wordBreak: "break-word",
                    }}
                  >
                    {renderValueV2(v)}
                  </dd>
                </React.Fragment>
                )
              })}
          </dl>
        </div>
      )}
    </div>
  )
}
