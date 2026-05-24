// Bottom-right floating settings picker.
//
// 1:1 port of TARGET redesign/footers/footer-variants.jsx::LayoutSwitcherWithFiles.
// Renders a pill-shaped trigger anchored to the viewport's bottom-right corner;
// clicking opens a panel above containing four sections:
//   1. Hero layout (from groups[0])
//   2. List density (from groups[1])
//   3. OPEN AS — 5 anchor links to companion files (report.md / papers.csv /
//      bibtex.bib / ris.ris / papers.json) produced by STEP 12 generators in
//      the same directory as report.html
//   4. PRINT — one row invoking window.print() with ⌘P hint
//
// The `rd-layout-switcher` className lets the print stylesheet hide this
// floating chrome on paper (see src/index.css `@media print` block).
//
// Click-outside dismisses the panel. Multi-group mode only.

import { Fragment, useEffect, useRef, useState } from "react"
import { FileText, Printer } from "lucide-react"

import { t } from "@/lib/i18n"
import { SwitcherThumb } from "./thumbs/Thumbs"

// Companion files — same names + order as generate_exports.py + md_report.py
// drop into $SEARCH_DIR alongside report.html (see references/output_files.md).
const COMPANION_FILES: ReadonlyArray<{ name: string; label: string }> = [
  { name: "report.md", label: "Markdown" },
  { name: "papers.csv", label: "CSV" },
  { name: "bibtex.bib", label: "BibTeX" },
  { name: "ris.ris", label: "RIS" },
  { name: "papers.json", label: "JSON" },
]

export interface LayoutSwitcherOption {
  value: string
  /** Short label rendered in the trigger pill */
  short: string
  /** Full label rendered in the panel item */
  label: string
  hint: string
}

export interface LayoutSwitcherGroup {
  label: string
  value: string
  onChange: (next: string) => void
  options: LayoutSwitcherOption[]
  thumb: "layout" | "list"
}

export interface LayoutSwitcherProps {
  groups: LayoutSwitcherGroup[]
}

export function LayoutSwitcher({ groups }: LayoutSwitcherProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  if (groups.length === 0) return null
  const primary = groups[0]
  const primaryCur = primary.options.find((o) => o.value === primary.value)
  const secondary = groups[1]
  const secondaryCur = secondary?.options.find((o) => o.value === secondary.value)

  return (
    <div
      ref={ref}
      className="rd-layout-switcher"
      style={{
        position: "fixed",
        right: 24,
        bottom: 24,
        zIndex: 30,
        fontFamily: "var(--font-sans)",
      }}
    >
      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            bottom: "calc(100% + 8px)",
            background: "hsl(var(--background))",
            boxShadow:
              "0 12px 32px rgba(0,0,0,0.12), 0 0 0 1px hsl(var(--border))",
            borderRadius: 8,
            padding: 4,
            minWidth: 260,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {groups.map((g, gi) => (
            <Fragment key={g.label}>
              {gi > 0 && (
                <div
                  style={{
                    height: 1,
                    background: "hsl(var(--border))",
                    margin: "4px 0",
                  }}
                />
              )}
              <div
                style={{
                  padding: "8px 12px 6px",
                  fontSize: 10,
                  fontWeight: 500,
                  color: "hsl(var(--muted-foreground))",
                  textTransform: "uppercase",
                  letterSpacing: "0.12em",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {g.label}
              </div>
              {g.options.map((opt) => {
                const active = opt.value === g.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => g.onChange(opt.value)}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      width: "100%",
                      textAlign: "left",
                      padding: "8px 12px",
                      borderRadius: 5,
                      background: active ? "hsl(var(--muted))" : "transparent",
                      cursor: "pointer",
                      border: 0,
                      font: "inherit",
                      transition: "background .1s",
                    }}
                    onMouseEnter={(e) => {
                      if (!active)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "hsl(var(--muted) / 0.5)"
                    }}
                    onMouseLeave={(e) => {
                      if (!active)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "transparent"
                    }}
                  >
                    <SwitcherThumb kind={g.thumb} variant={opt.value} active={active} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: 12.5,
                          fontWeight: 500,
                          color: "hsl(var(--foreground))",
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        {opt.label}
                        {active && (
                          <span
                            style={{
                              fontSize: 10,
                              color: "hsl(var(--muted-foreground))",
                            }}
                          >
                            · {t("current")}
                          </span>
                        )}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: "hsl(var(--muted-foreground))",
                          marginTop: 2,
                          lineHeight: 1.4,
                        }}
                      >
                        {opt.hint}
                      </div>
                    </div>
                  </button>
                )
              })}
            </Fragment>
          ))}

          {/* OPEN AS — companion file links (relative href to sibling files).
              Match delta footer-variants.jsx LayoutSwitcherWithFiles. */}
          <div
            style={{
              height: 1,
              background: "hsl(var(--border))",
              margin: "4px 0",
            }}
          />
          <div
            style={{
              padding: "8px 12px 6px",
              fontSize: 10,
              fontWeight: 500,
              color: "hsl(var(--muted-foreground))",
              textTransform: "uppercase",
              letterSpacing: "0.12em",
              fontFamily: "var(--font-mono)",
            }}
          >
            {t("openAs")}
          </div>
          {COMPANION_FILES.map((f) => (
            <a
              key={f.name}
              href={f.name}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 12px",
                borderRadius: 5,
                textDecoration: "none",
                color: "hsl(var(--foreground))",
                background: "transparent",
                transition: "background .1s",
              }}
              onMouseEnter={(e) => {
                ;(e.currentTarget as HTMLAnchorElement).style.background =
                  "hsl(var(--muted) / 0.6)"
              }}
              onMouseLeave={(e) => {
                ;(e.currentTarget as HTMLAnchorElement).style.background =
                  "transparent"
              }}
            >
              <FileText size={12} strokeWidth={1.75} />
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
              >
                {f.name}
              </span>
              <span style={{ flex: 1 }} />
              <span
                style={{
                  fontSize: 11,
                  color: "hsl(var(--muted-foreground))",
                }}
              >
                {f.label}
              </span>
            </a>
          ))}

          {/* PRINT — invokes window.print() with ⌘P hint. Match delta
              footer-variants.jsx LayoutSwitcherWithFiles. */}
          <div
            style={{
              height: 1,
              background: "hsl(var(--border))",
              margin: "4px 0",
            }}
          />
          <button
            type="button"
            onClick={() => window.print()}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 12px",
              borderRadius: 5,
              background: "transparent",
              border: 0,
              cursor: "pointer",
              fontFamily: "inherit",
              color: "hsl(var(--foreground))",
              textAlign: "left",
              transition: "background .1s",
            }}
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.background =
                "hsl(var(--muted) / 0.6)"
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLButtonElement).style.background =
                "transparent"
            }}
          >
            <Printer size={12} strokeWidth={1.75} />
            <span style={{ fontSize: 12.5, fontWeight: 500 }}>
              {t("printAction")}
            </span>
            <span style={{ flex: 1 }} />
            <span
              style={{
                fontSize: 11,
                color: "hsl(var(--muted-foreground))",
                fontFamily: "var(--font-mono)",
              }}
            >
              ⌘P
            </span>
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen(!open)}
        title={t("settingsAndFilesTitle")}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px 8px 10px",
          background: "hsl(var(--background))",
          color: "hsl(var(--foreground))",
          boxShadow: "0 4px 16px rgba(0,0,0,0.08), 0 0 0 1px hsl(var(--border))",
          borderRadius: 999,
          fontSize: 12,
          fontWeight: 500,
          cursor: "pointer",
          border: 0,
          fontFamily: "inherit",
          transition: "box-shadow .14s, transform .14s",
        }}
        onMouseEnter={(e) => {
          ;(e.currentTarget as HTMLButtonElement).style.boxShadow =
            "0 6px 20px rgba(0,0,0,0.12), 0 0 0 1px hsl(var(--foreground) / 0.4)"
        }}
        onMouseLeave={(e) => {
          ;(e.currentTarget as HTMLButtonElement).style.boxShadow =
            "0 4px 16px rgba(0,0,0,0.08), 0 0 0 1px hsl(var(--border))"
        }}
      >
        <SwitcherThumb kind={primary.thumb} variant={primary.value} active small />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "hsl(var(--muted-foreground))",
          }}
        >
          {primaryCur?.short || primary.label}
          {secondary && (
            <span style={{ opacity: 0.5 }}>
              {" "}
              · {secondaryCur?.short || ""}
            </span>
          )}
        </span>
      </button>
    </div>
  )
}
