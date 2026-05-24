// Paper detail sheet — right-side slide-in with TLDR · Why · Abstract · Authors · Metadata.
// Direct port of TARGET redesign/app-2-papers.jsx (376-529).
//
// shadcn Sheet provides the Radix-backed slide animation, overlay click and
// Esc-to-close behavior. The default close button (top-right X) is suppressed
// because the TARGET layout places ↑/↓/✕ together in the header row. j/k
// navigation is handled by the parent (ReportShell) at the document level.
// Copy-DOI uses sonner toast per master plan §D3.

import * as React from "react"
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp, Copy, ExternalLink, X } from "lucide-react"
import { toast } from "sonner"

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"

import type { NormalizedPaper } from "@/lib/types"
import { fmtNum, fmtRcs } from "@/lib/format"
import { t, getS } from "@/lib/i18n"

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

export interface PaperSheetProps {
  paper: NormalizedPaper | null
  onClose: () => void
  onPrev: () => void
  onNext: () => void
  hasPrev: boolean
  hasNext: boolean
}

export function PaperSheet({
  paper,
  onClose,
  onPrev,
  onNext,
  hasPrev,
  hasNext,
}: PaperSheetProps) {
  const open = !!paper
  const [absExpanded, setAbsExpanded] = React.useState(false)
  React.useEffect(() => {
    setAbsExpanded(false)
  }, [paper?.id])

  async function copyDoi() {
    if (!paper?.doi) return
    try {
      await navigator.clipboard.writeText(paper.doi)
      toast.success(t("copyDoiToast"), { description: paper.doi })
    } catch {
      // Fallback for missing key — there is no explicit dict entry for the
      // failure-mode toast; delta3 ground truth doesn't surface this branch
      // either (it used the legacy window.toast helper). Keep the English
      // literal as the user-facing failure message until a key is added.
      const S = getS() as Record<string, string>
      toast.error(S.copyDoiErrorToast || "Could not copy DOI")
    }
  }
  function openDoi() {
    if (paper?.doiUrl) window.open(paper.doiUrl, "_blank", "noopener,noreferrer")
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        // - Suppress default shadcn close button (we render our own X in the header
        //   so the ↑/↓/✕ trio sits together per TARGET layout).
        // - Override default p-6 + gap-4 + shadow-lg to match TARGET zero padding
        //   and rely on inner sections for spacing.
        className="w-[680px] sm:max-w-[680px] p-0 gap-0 flex flex-col [&>button.absolute]:hidden"
        style={{
          background: "hsl(var(--card))",
          // Gate the drop shadow on open state so the offscreen sheet
          // doesn't leave a vertical grey band at the right viewport edge
          // during/after the slide-out animation (delta change 3).
          boxShadow: open ? "-12px 0 32px rgba(0,0,0,0.08)" : "none",
        }}
      >
        {paper && (
          <>
            {/* a11y: Radix Dialog requires Title + Description for screen readers.
                Visually hidden — the visible title is in the body section below.
                A11y-only fallback strings ("Paper detail" / "year unknown") have
                no dict keys; they default to English via getS() lookup so a
                future dict add will pick them up automatically. */}
            <SheetTitle className="sr-only">
              {paper.title ||
                (getS() as Record<string, string>).paperDetailA11y ||
                "Paper detail"}
            </SheetTitle>
            <SheetDescription className="sr-only">
              {paper.authorsShort || t("authorsUnspecified")} ·{" "}
              {paper.year ||
                (getS() as Record<string, string>).yearUnknownA11y ||
                "year unknown"}{" "}
              · RCS {((paper.rcs ?? 0) / 10).toFixed(2)}
            </SheetDescription>
            {/* Header row — tier pill + nav buttons */}
            <div
              style={{
                padding: "20px 24px 16px",
                borderBottom: "1px solid hsl(var(--border))",
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 7,
                  padding: "4px 8px",
                  borderRadius: 5,
                  boxShadow: "inset 0 0 0 1px hsl(var(--border))",
                }}
              >
                <TierDot tier={paper.tier} />
                <span style={{ fontSize: 11.5, fontWeight: 500 }}>
                  {(getS() as Record<string, string>)[paper.tier] || paper.tier}
                </span>
                <Separator orientation="vertical" className="h-4" />
                <span
                  className="tabular"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                    fontWeight: 600,
                  }}
                >
                  {fmtRcs(paper.rcs)}
                </span>
              </div>
              <div style={{ flex: 1 }} />
              <Button
                variant="ghost"
                size="icon"
                onClick={onPrev}
                disabled={!hasPrev}
                title={t("prevTitle")}
              >
                <ArrowUp style={{ width: 14, height: 14 }} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onNext}
                disabled={!hasNext}
                title={t("nextTitle")}
              >
                <ArrowDown style={{ width: 14, height: 14 }} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                title={t("closeTitle")}
              >
                <X style={{ width: 15, height: 15 }} />
              </Button>
            </div>

            {/* Scrollable body */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "24px 24px 100px",
              }}
            >
              <h2
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  lineHeight: 1.3,
                  letterSpacing: "-0.005em",
                  margin: 0,
                  color: "hsl(var(--foreground))",
                }}
              >
                {paper.title}
              </h2>

              <div
                style={{
                  marginTop: 12,
                  fontSize: 12.5,
                  color: "hsl(var(--muted-foreground))",
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    color: "hsl(var(--foreground))",
                    fontWeight: 500,
                  }}
                >
                  {paper.authorsShort}
                </span>
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
                    {paper.venue}
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

              {/* TL;DR — most important */}
              {paper.tldr && (
                <section
                  style={{
                    marginTop: 24,
                    padding: 16,
                    background: "hsl(var(--muted) / 0.5)",
                    borderRadius: 6,
                  }}
                >
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 500,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      color: "hsl(var(--muted-foreground))",
                      marginBottom: 8,
                    }}
                  >
                    {t("tldrLabel")}
                  </div>
                  <p
                    style={{
                      margin: 0,
                      fontSize: 13.5,
                      lineHeight: 1.6,
                      color: "hsl(var(--foreground))",
                    }}
                  >
                    {paper.tldr}
                  </p>
                </section>
              )}

              {/* Why this paper */}
              {paper.rcsReasoning && (
                <section style={{ marginTop: 24 }}>
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 500,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      color: "hsl(var(--muted-foreground))",
                      marginBottom: 8,
                    }}
                  >
                    {t("whyThisPaper")}
                  </div>
                  <p
                    style={{
                      margin: 0,
                      fontSize: 13,
                      lineHeight: 1.65,
                      color: "hsl(var(--foreground))",
                    }}
                  >
                    {paper.rcsReasoning}
                  </p>
                </section>
              )}

              {/* Abstract — collapsed */}
              {paper.abstract && (
                <section
                  style={{
                    marginTop: 24,
                    borderTop: "1px solid hsl(var(--border))",
                    paddingTop: 20,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 8,
                    }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 500,
                        textTransform: "uppercase",
                        letterSpacing: "0.08em",
                        color: "hsl(var(--muted-foreground))",
                      }}
                    >
                      {t("abstractLabel")}
                    </span>
                    <button
                      type="button"
                      onClick={() => setAbsExpanded((v) => !v)}
                      style={{
                        fontSize: 11,
                        color: "hsl(var(--muted-foreground))",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        background: "transparent",
                        border: 0,
                        cursor: "pointer",
                        padding: 0,
                        // fontFamily inherits Geist; using `font: inherit`
                        // shorthand here would overwrite the explicit
                        // fontSize: 11 above and inflate the button to
                        // body text size (16px+). Same trap fixed in
                        // TierStrip + LayoutSwitcher.
                        fontFamily: "inherit",
                      }}
                    >
                      {absExpanded ? t("collapse") : t("expand")}{" "}
                      {absExpanded ? (
                        <ChevronUp style={{ width: 12, height: 12 }} />
                      ) : (
                        <ChevronDown style={{ width: 12, height: 12 }} />
                      )}
                    </button>
                  </div>
                  <p
                    style={{
                      margin: 0,
                      fontSize: 13,
                      lineHeight: 1.65,
                      color: "hsl(var(--muted-foreground))",
                      overflow: absExpanded ? "visible" : "hidden",
                      display: absExpanded ? "block" : "-webkit-box",
                      WebkitLineClamp: absExpanded ? "unset" : 3,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {paper.abstract}
                  </p>
                </section>
              )}

              {/* Authors */}
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
                  {t("authorsLabel")} · {paper.authorsFull.length}
                </div>
                <ul
                  style={{
                    margin: 0,
                    padding: 0,
                    listStyle: "none",
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                  }}
                >
                  {paper.authorsFull.map((name, i) => (
                    <li
                      key={i}
                      style={{
                        fontSize: 13,
                        color: "hsl(var(--foreground))",
                      }}
                    >
                      {name}
                    </li>
                  ))}
                </ul>
              </section>

              {/* Metadata */}
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
                  {t("metadataLabel")}
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
                  <dt style={{ color: "hsl(var(--muted-foreground))" }}>{t("doi")}</dt>
                  <dd
                    style={{
                      margin: 0,
                      fontFamily: "var(--font-mono)",
                      fontSize: 11.5,
                      wordBreak: "break-all",
                    }}
                  >
                    {paper.doi || "—"}
                  </dd>
                  <dt style={{ color: "hsl(var(--muted-foreground))" }}>
                    {t("sources")}
                  </dt>
                  <dd
                    style={{
                      margin: 0,
                      display: "flex",
                      gap: 5,
                      flexWrap: "wrap",
                    }}
                  >
                    {paper.sources.length === 0 && (
                      <span style={{ color: "hsl(var(--muted-foreground))" }}>
                        —
                      </span>
                    )}
                    {paper.sources.map((s) => (
                      <Badge
                        key={s}
                        variant="outline"
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 10,
                        }}
                      >
                        {s}
                      </Badge>
                    ))}
                  </dd>
                  <dt style={{ color: "hsl(var(--muted-foreground))" }}>
                    {t("openAccess")}
                  </dt>
                  <dd
                    style={{
                      margin: 0,
                      fontFamily: "var(--font-mono)",
                      fontSize: 11.5,
                    }}
                  >
                    {paper.isOpenAccess ? t("yes") : t("no")}
                  </dd>
                  {paper.influentialCitations > 0 && (
                    <>
                      <dt style={{ color: "hsl(var(--muted-foreground))" }}>
                        {t("influentialCites")}
                      </dt>
                      <dd
                        style={{
                          margin: 0,
                          fontFamily: "var(--font-mono)",
                          fontSize: 11.5,
                        }}
                      >
                        {paper.influentialCitations}
                      </dd>
                    </>
                  )}
                </dl>
              </section>
            </div>

            {/* Footer actions */}
            <div
              style={{
                padding: "12px 24px",
                borderTop: "1px solid hsl(var(--border))",
                display: "flex",
                gap: 8,
                background: "hsl(var(--background))",
                flexShrink: 0,
                alignItems: "center",
              }}
            >
              <Button
                variant="outline"
                size="sm"
                onClick={copyDoi}
                disabled={!paper.doi}
                style={{ whiteSpace: "nowrap" }}
              >
                <Copy style={{ width: 13, height: 13 }} /> {t("copyDoi")}
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={openDoi}
                disabled={!paper.doiUrl}
                style={{ whiteSpace: "nowrap" }}
              >
                <ExternalLink style={{ width: 13, height: 13 }} /> {t("open")}
              </Button>
              <div style={{ flex: 1 }} />
              <span
                style={{
                  fontSize: 11,
                  color: "hsl(var(--muted-foreground))",
                }}
              >
                {t("navHint")}
              </span>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
