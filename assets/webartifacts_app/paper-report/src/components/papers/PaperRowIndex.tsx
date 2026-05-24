// Variant C — "Index" — single-row table, max density.
// One line per paper. Columnar. ~44px per row.
// No TLDR (use detail sheet for it). Best for scanning 100+ papers.
// Direct port of TARGET redesign/list-variants.jsx (88-161).

import type { NormalizedPaper } from "@/lib/types"
import { fmtNum, fmtRcs } from "@/lib/format"

import { QuickJump } from "./QuickJump"
import { TierDot } from "./TierDot"

export interface PaperRowIndexProps {
  paper: NormalizedPaper
  index: number
  onSelect: (paper: NormalizedPaper) => void
  dim?: boolean
}

export function PaperRowIndex({ paper, index, onSelect }: PaperRowIndexProps) {
  const authorsNode = paper.authorsShort || "—"
  return (
    <button
      type="button"
      onClick={() => onSelect(paper)}
      className="rd-paper-row"
      style={{
        display: "grid",
        // # · title · authors · year · venue · cites · tier+rcs
        gridTemplateColumns:
          "34px minmax(0, 2.4fr) minmax(0, 1fr) 52px minmax(0, 1.1fr) 80px 90px",
        gap: 14,
        alignItems: "center",
        width: "100%",
        textAlign: "left",
        padding: "10px 16px",
        borderBottom: "1px solid hsl(var(--border))",
        background: "transparent",
        cursor: "pointer",
        border: 0,
        font: "inherit",
        transition: "background .12s",
        color: "hsl(var(--foreground))",
        fontSize: 12.5,
      }}
      onMouseEnter={(e) =>
        (e.currentTarget.style.background = "hsl(var(--muted) / 0.4)")
      }
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {/* Index */}
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          fontWeight: 500,
          color: "hsl(var(--muted-foreground))",
          textAlign: "right",
        }}
      >
        #{String(index + 1).padStart(2, "0")}
      </span>

      {/* Title */}
      <span
        style={{
          fontWeight: paper.tier === "Foundational" ? 600 : 500,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          letterSpacing: "-0.005em",
        }}
      >
        {paper.title}
      </span>

      {/* Authors */}
      <span
        style={{
          color: "hsl(var(--muted-foreground))",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {authorsNode}
      </span>

      {/* Year */}
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          color: "hsl(var(--muted-foreground))",
        }}
      >
        {paper.year || "—"}
      </span>

      {/* Venue */}
      <span
        style={{
          color: "hsl(var(--muted-foreground))",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontSize: 11.5,
        }}
      >
        {paper.venue || "—"}
      </span>

      {/* Cites */}
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11.5,
          color: "hsl(var(--muted-foreground))",
          textAlign: "right",
        }}
      >
        {paper.citations > 0 ? fmtNum(paper.citations) : "—"}
      </span>

      {/* Quick-jump (inline, hover-revealed) + Tier dot + RCS.
          alignItems shifted baseline → center so the 22×22 QuickJump
          square doesn't push the cluster's baseline. */}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 6,
        }}
      >
        <QuickJump paper={paper} />
        <TierDot tier={paper.tier} size={7} />
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 600,
            letterSpacing: "-0.01em",
          }}
        >
          {fmtRcs(paper.rcs)}
        </span>
      </span>
    </button>
  )
}
