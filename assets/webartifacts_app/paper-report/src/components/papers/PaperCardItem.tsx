// Paper card — detailed.
// Direct port of TARGET redesign/app-2-papers.jsx (107-257)
// including embedded RcsInstrument (236-257).
//
// Visual rules locked by master plan §3.4:
//   - Minimal kicker (#01 only); no tier name repeat
//   - TLDR uses 13.5px foreground color + left hairline rule
//   - Meta line in 4 groups (authors / year+venue / cites+influential / OA)
//   - Right RCS column = label + big number, no micro bar / no chevron
//   - Foundational card: bg-muted/0.5 + 22px padding + 18px title
//   - Hover: inset 1px foreground/0.4 + 4px subtle drop shadow

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

import type { NormalizedPaper } from "@/lib/types"
import { fmtNum, fmtRcs } from "@/lib/format"
import { t, getS } from "@/lib/i18n"

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

function RcsInstrument({ paper }: { paper: NormalizedPaper }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        paddingLeft: 20,
        borderLeft: "1px solid hsl(var(--border))",
        minWidth: 76,
        flexShrink: 0,
      }}
    >
      <span
        style={{
          fontSize: 9.5,
          color: "hsl(var(--muted-foreground))",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          fontFamily: "var(--font-mono)",
          fontWeight: 500,
          marginBottom: 2,
        }}
      >
        RCS
      </span>
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          lineHeight: 1,
          color: "hsl(var(--foreground))",
        }}
      >
        {fmtRcs(paper.rcs)}
      </span>
    </div>
  )
}

export interface PaperCardItemProps {
  paper: NormalizedPaper
  index: number
  onSelect: (paper: NormalizedPaper) => void
}

export function PaperCardItem({ paper, index, onSelect }: PaperCardItemProps) {
  const isFound = paper.tier === "Foundational"

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
      {t("authorsUnspecified")}
    </span>
  )

  return (
    <Card
      onClick={() => onSelect(paper)}
      style={{
        cursor: "pointer",
        padding: 0,
        position: "relative",
        background: isFound ? "hsl(var(--muted) / 0.5)" : "hsl(var(--card))",
        transition: "box-shadow .14s, background .14s, transform .14s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow =
          "inset 0 0 0 1px hsl(var(--foreground) / 0.4), 0 4px 14px rgba(0,0,0,0.04)"
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "inset 0 0 0 1px hsl(var(--border))"
      }}
    >
      <div
        style={{
          padding: isFound ? "22px 24px" : "18px 22px",
          display: "flex",
          alignItems: "flex-start",
          gap: 24,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Minimal kicker — just the index, tier is implied by section header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 8,
              fontSize: 11,
            }}
          >
            <span
              className="tabular"
              style={{
                fontFamily: "var(--font-mono)",
                fontWeight: 500,
                color: "hsl(var(--muted-foreground))",
              }}
            >
              #{String(index + 1).padStart(2, "0")}
            </span>
            {paper.rcsFlag && (
              <>
                <Dot />
                <Badge variant="outline">{paper.rcsFlag}</Badge>
              </>
            )}
          </div>

          {/* Title */}
          <h3
            style={{
              fontSize: isFound ? 18 : 15.5,
              fontWeight: 600,
              lineHeight: 1.32,
              margin: 0,
              letterSpacing: "-0.008em",
              color: "hsl(var(--foreground))",
            }}
          >
            {paper.title}
          </h3>

          {/* TLDR — promoted as primary readable content */}
          {paper.tldr && (
            <div
              style={{
                marginTop: 12,
                paddingLeft: 12,
                borderLeft: "1px solid hsl(var(--border))",
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: 13.5,
                  lineHeight: 1.6,
                  color: "hsl(var(--foreground))",
                  maxWidth: "72ch",
                }}
              >
                {paper.tldr}
              </p>
            </div>
          )}
          {!paper.tldr && paper.abstract && (
            <p
              style={{
                marginTop: 10,
                fontSize: 12.5,
                lineHeight: 1.55,
                color: "hsl(var(--muted-foreground))",
                maxWidth: "72ch",
                overflow: "hidden",
                textOverflow: "ellipsis",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              {paper.abstract}
            </p>
          )}

          {/* Meta line — grouped, not flat */}
          <div
            style={{
              marginTop: 14,
              fontSize: 12,
              color: "hsl(var(--muted-foreground))",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "4px 0",
            }}
          >
            {/* Group 1: authors */}
            {authorsNode}

            {/* Group 2: year · venue */}
            {(paper.year || paper.venue) && (
              <>
                <Dot />
                {paper.year && (
                  <span
                    className="tabular"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {paper.year}
                  </span>
                )}
                {paper.year && paper.venue && (
                  <span style={{ margin: "0 6px", opacity: 0.5 }}>·</span>
                )}
                {paper.venue && <span>{paper.venue}</span>}
              </>
            )}

            {/* Group 3: citation metrics */}
            {(paper.citations > 0 || paper.influentialCitations > 0) && (
              <>
                <Dot />
                {paper.citations > 0 && (
                  <span
                    className="tabular"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {fmtNum(paper.citations)} {t("cites")}
                  </span>
                )}
                {paper.influentialCitations > 0 && (
                  <>
                    <span style={{ margin: "0 6px", opacity: 0.5 }}>·</span>
                    <TooltipProvider>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span
                            className="tabular"
                            style={{
                              fontFamily: "var(--font-mono)",
                              cursor: "help",
                            }}
                          >
                            {paper.influentialCitations} {t("influential")}
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          {(getS() as Record<string, string>)
                            .influentialCitesTooltip ||
                            "Influential citations (Semantic Scholar)"}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </>
                )}
              </>
            )}

            {/* Group 4: OA */}
            {paper.isOpenAccess && (
              <>
                <Dot />
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    padding: "1px 5px",
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

        {/* RCS instrument column */}
        <RcsInstrument paper={paper} />
      </div>
    </Card>
  )
}
