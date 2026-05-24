// Variant B — "Catalog" — compact 2-line rhythm.
// Title (1 line) · TLDR italic muted (1 line) · meta + tier+RCS right.
// Per row ~64px. Keeps TLDR while doubling density.
// Direct port of TARGET redesign/list-variants.jsx (10-81).

import type { NormalizedPaper } from "@/lib/types"
import { fmtNum, fmtRcs } from "@/lib/format"
import { t } from "@/lib/i18n"

import { QuickJump } from "./QuickJump"
import { TierDot } from "./TierDot"

function Dot() {
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

export interface PaperRowCatalogProps {
  paper: NormalizedPaper
  index: number
  onSelect: (paper: NormalizedPaper) => void
  dim?: boolean
}

export function PaperRowCatalog({ paper, index, onSelect }: PaperRowCatalogProps) {
  const authorsNode = paper.authorsShort ? (
    <span style={{ color: "hsl(var(--foreground))", fontWeight: 500 }}>
      {paper.authorsShort}
    </span>
  ) : (
    <span
      style={{
        color: "hsl(var(--muted-foreground))",
        fontStyle: "italic",
      }}
    >
      —
    </span>
  )

  return (
    <button
      type="button"
      onClick={() => onSelect(paper)}
      className="rd-paper-row"
      style={{
        display: "grid",
        gridTemplateColumns: "34px minmax(0, 1fr) 84px",
        gap: 16,
        alignItems: "center",
        width: "100%",
        textAlign: "left",
        padding: "14px 16px",
        borderBottom: "1px solid hsl(var(--border))",
        background: "transparent",
        cursor: "pointer",
        border: 0,
        font: "inherit",
        transition: "background .12s",
        color: "hsl(var(--foreground))",
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
          fontSize: 11,
          fontWeight: 500,
          color: "hsl(var(--muted-foreground))",
          textAlign: "right",
        }}
      >
        #{String(index + 1).padStart(2, "0")}
      </span>

      {/* Center stack: title / tldr / meta */}
      <div
        style={{
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 3,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: paper.tier === "Foundational" ? 600 : 500,
            lineHeight: 1.32,
            letterSpacing: "-0.005em",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {paper.title}
        </h3>

        {paper.tldr && (
          <p
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.4,
              color: "hsl(var(--muted-foreground))",
              fontStyle: "italic",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {paper.tldr}
          </p>
        )}

        <div
          style={{
            fontSize: 11.5,
            color: "hsl(var(--muted-foreground))",
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            marginTop: 1,
          }}
        >
          {authorsNode}
          {paper.year && (
            <>
              <Dot />
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {paper.year}
              </span>
            </>
          )}
          {paper.venue && (
            <>
              <Dot />
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 280,
                }}
              >
                {paper.venue}
              </span>
            </>
          )}
          {paper.citations > 0 && (
            <>
              <Dot />
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {fmtNum(paper.citations)} {t("cites")}
              </span>
            </>
          )}
          {paper.isOpenAccess && (
            <>
              <Dot />
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  padding: "0 4px",
                  background: "hsl(var(--muted))",
                  borderRadius: 3,
                  color: "hsl(var(--foreground))",
                }}
              >
                OA
              </span>
            </>
          )}
        </div>
      </div>

      {/* Right cluster: quick-jump (inline, hover-revealed) + tier dot + RCS.
          Gap reduced from 8 → 6 to match TARGET delta2 list-variants.jsx,
          which tightens the cluster slightly when QuickJump occupies the
          left-most slot. The RCS number's horizontal position stays
          identical because the cluster is right-aligned (justifyContent
          flex-end) and QuickJump renders nothing for papers without doiUrl. */}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 6,
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <QuickJump paper={paper} />
        <TierDot tier={paper.tier} size={7} />
        <span
          style={{
            fontSize: 13.5,
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
