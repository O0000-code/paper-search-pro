// Top-level shell. Owns layout/density switcher state + persists to
// localStorage, hydrates from `window.__REPORT_DATA__` when injected by the
// Python pipeline (falls back to MOCK_RAW for the standalone Vite demo), then
// delegates to ReportShell which is a 1:1 port of TARGET app-3-tabs.jsx
// AppLoaded (382-472).
//
// All zone implementations live under @/components/{hero,papers,methods,audit}
// — this file only wires them.

import { useEffect, useMemo, useState } from "react"

import { Toaster } from "@/components/ui/sonner"

import { normalize } from "@/lib/normalize"
import { MOCK_RAW } from "@/lib/mock-data"
import { t } from "@/lib/i18n"
import type { NormalizedData, NormalizedPaper, Tier } from "@/lib/types"

import { SwissTop } from "@/components/hero/tops/SwissTop"
import { EditorialTop } from "@/components/hero/tops/EditorialTop"
import { DocumentTop } from "@/components/hero/tops/DocumentTop"
import { LayoutSwitcher } from "@/components/chrome/LayoutSwitcher"

import {
  PaperList,
  type PaperRowComponent,
} from "@/components/papers/PaperList"
import { PaperRowCatalog } from "@/components/papers/PaperRowCatalog"
import { PaperRowIndex } from "@/components/papers/PaperRowIndex"
import { PaperRowIndexHeader } from "@/components/papers/PaperRowIndexHeader"
import { PaperSheet } from "@/components/papers/PaperSheet"
import { MethodsTab } from "@/components/methods/MethodsTab"
import { AuditTab } from "@/components/audit/AuditTab"

// ---------------------------------------------------------------------------
// Data hydration — __REPORT_DATA__ overrides MOCK_RAW. normalize() handles
// both raw (pipeline) and post-materialization shapes.
// ---------------------------------------------------------------------------
const __EXT: unknown =
  typeof window !== "undefined"
    ? (window as { __REPORT_DATA__?: unknown }).__REPORT_DATA__
    : undefined
const RAW = (__EXT ?? MOCK_RAW) as Parameters<typeof normalize>[0]

// ---------------------------------------------------------------------------
// Layout / density options (port of TARGET report-v2.html 32-44).
//
// `short` / `label` / `hint` are dict-keyed (translated at render time inside
// App via t(); see useLayoutOptions() / useDensityOptions() below) so the same
// React bundle can be shipped under both EN and ZH report HTMLs. `Component`
// / `Row` / `value` are language-agnostic and remain on the module-scope
// canonical list so refactoring stays minimal.
// ---------------------------------------------------------------------------
type TopComponent = typeof SwissTop | typeof EditorialTop | typeof DocumentTop

const LAYOUT_OPTION_DEFS: ReadonlyArray<{
  value: string
  Component: TopComponent
}> = [
  { value: "swiss", Component: SwissTop },
  { value: "editorial", Component: EditorialTop },
  { value: "document", Component: DocumentTop },
]

const DENSITY_OPTION_DEFS: ReadonlyArray<{
  value: string
  Row: PaperRowComponent
}> = [
  { value: "catalog", Row: PaperRowCatalog },
  { value: "index", Row: PaperRowIndex },
]

const STORAGE_LAYOUT = "psp-layout-v1"
const STORAGE_DENSITY = "psp-density-v1"

function readStored(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback
  } catch {
    return fallback
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* ignore quota / privacy mode */
  }
}

// Per-option dict-key tables (value → key fragment). The full key is built
// by string concat with the type prefix (swiss/editorial/...). Kept inline so
// adding a new variant is a 3-line change (def entry + Short / Label / Hint
// fragments) instead of a multi-file hunt.
const LAYOUT_DICT_FRAGMENT: Record<string, "swiss" | "editorial" | "document"> = {
  swiss: "swiss",
  editorial: "editorial",
  document: "document",
}
const DENSITY_DICT_FRAGMENT: Record<string, "catalog" | "index"> = {
  catalog: "catalog",
  index: "index",
}

export default function App() {
  const data: NormalizedData = useMemo(() => normalize(RAW), [])

  const [layout, setLayout] = useState<string>(() =>
    readStored(STORAGE_LAYOUT, "swiss"),
  )
  const [density, setDensity] = useState<string>(() =>
    readStored(STORAGE_DENSITY, "catalog"),
  )

  function changeLayout(v: string): void {
    setLayout(v)
    writeStored(STORAGE_LAYOUT, v)
  }
  function changeDensity(v: string): void {
    setDensity(v)
    writeStored(STORAGE_DENSITY, v)
  }

  const TopComponent =
    (LAYOUT_OPTION_DEFS.find((o) => o.value === layout) ??
      LAYOUT_OPTION_DEFS[0]).Component
  const RowComponent =
    (DENSITY_OPTION_DEFS.find((o) => o.value === density) ??
      DENSITY_OPTION_DEFS[0]).Row

  // Translated option lists built at render time (inside App so t() sees the
  // installed window.S dict). The dict-key naming convention follows TARGET
  // delta3 i18n.jsx: `${fragment}Short` / `${fragment}Label` / `${fragment}Hint`.
  const layoutOptions = LAYOUT_OPTION_DEFS.map(({ value }) => {
    const frag = LAYOUT_DICT_FRAGMENT[value]
    return {
      value,
      short: t(`${frag}Short` as `${typeof frag}Short`),
      label: t(`${frag}Label` as `${typeof frag}Label`),
      hint: t(`${frag}Hint` as `${typeof frag}Hint`),
    }
  })
  const densityOptions = DENSITY_OPTION_DEFS.map(({ value }) => {
    const frag = DENSITY_DICT_FRAGMENT[value]
    return {
      value,
      short: t(`${frag}Short` as `${typeof frag}Short`),
      label: t(`${frag}Label` as `${typeof frag}Label`),
      hint: t(`${frag}Hint` as `${typeof frag}Hint`),
    }
  })

  return (
    <>
      <ReportShell
        data={data}
        TopComponent={TopComponent}
        RowComponent={RowComponent}
      />
      <LayoutSwitcher
        groups={[
          {
            label: t("heroLayout"),
            value: layout,
            onChange: changeLayout,
            options: layoutOptions,
            thumb: "layout",
          },
          {
            label: t("listDensityLabel"),
            value: density,
            onChange: changeDensity,
            options: densityOptions,
            thumb: "list",
          },
        ]}
      />
      {/* `rd-toaster` className lets the print stylesheet hide the toast
          container on paper (see src/index.css `@media print` block). */}
      <Toaster
        className="rd-toaster"
        richColors={false}
        closeButton={false}
        position="bottom-left"
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// ReportShell — port of TARGET AppLoaded (app-3-tabs.jsx 382-472).
// Owns tab + filter + active-paper state; passes a uniform props bag to
// every TopComponent (each Top destructures only what it needs — Swiss
// ignores threshold/view/focus, Editorial/Document accept view, etc.).
// ---------------------------------------------------------------------------
function ReportShell({
  data,
  TopComponent,
  RowComponent,
}: {
  data: NormalizedData
  TopComponent: TopComponent
  RowComponent: PaperRowComponent
}) {
  const [tab, setTab] = useState<"findings" | "methods" | "audit">("findings")
  const [threshold, setThreshold] = useState<number>(0)
  const [search, setSearch] = useState<string>("")
  const [view, setView] = useState<string>("compact")
  const [active, setActive] = useState<NormalizedPaper | null>(null)
  const [tierFilter, setTierFilter] = useState<"all" | Tier>("all")
  // NOTE (2026-05-23): `focus` state was previously a "Recommended" (Foundational+High)
  // vs "All" toggle. The toggle UI lives in `components/hero/FilterBar.tsx` but FilterBar
  // is never imported by any active Top (Swiss/Editorial/Document each embed their own
  // tab+filter row). The result: `focus` was hardcoded to "recommended" with no way for
  // the user to switch it off, so clicking TierStrip on Moderate/Emerging/Peripheral
  // produced an empty list (focus=recommended AND tier=Moderate = ∅). Killing the state
  // restores the natural mental model: TierStrip click drills into that tier; "All" is the
  // default. If a Recommended quick-filter is ever wanted again, wire FilterBar into a
  // Top and reintroduce the state with a real UI toggle.

  const filtered = useMemo(() => {
    const out = data.papers.filter((p) => p.rcs >= threshold)
    return tierFilter === "all"
      ? out
      : out.filter((p) => p.tier === tierFilter)
  }, [data.papers, threshold, tierFilter])

  function go(delta: number): void {
    if (!active) return
    const i = filtered.findIndex((p) => p.id === active.id)
    const ni = i + delta
    if (ni >= 0 && ni < filtered.length) setActive(filtered[ni])
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (!active) return
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault()
        go(1)
      }
      if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault()
        go(-1)
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  })

  const tierCounts = useMemo(() => {
    const c: Partial<Record<Tier, number>> = {}
    for (const p of data.papers) c[p.tier] = (c[p.tier] || 0) + 1
    return c
  }, [data.papers])

  // Results counter just reflects the current tier+threshold filter — no
  // hidden "recommended" overlay. Header "16 / 249" now matches the list below.
  const resultsCount = filtered.length

  const activeIndex = active
    ? filtered.findIndex((p) => p.id === active.id)
    : -1

  return (
    <>
      <TopComponent
        data={data}
        tab={tab}
        setTab={setTab as (next: string) => void}
        threshold={threshold}
        setThreshold={setThreshold}
        search={search}
        setSearch={setSearch}
        view={view}
        setView={setView}
        tierFilter={tierFilter}
        setTierFilter={setTierFilter}
        tierCounts={tierCounts}
        resultsCount={resultsCount}
      />

      {tab === "findings" && view === "compact" && RowComponent === PaperRowIndex && (
        <div style={{ maxWidth: 1240, margin: "0 auto", padding: "0 40px" }}>
          <PaperRowIndexHeader />
        </div>
      )}

      {tab === "findings" && (
        <PaperList
          papers={filtered}
          view={view}
          threshold={threshold}
          search={search}
          onSelect={setActive}
          RowComponent={RowComponent}
        />
      )}

      {tab === "methods" && (
        <MethodsTab data={data} onSelectPaper={setActive} />
      )}
      {tab === "audit" && <AuditTab data={data} />}

      <PaperSheet
        paper={active}
        onClose={() => setActive(null)}
        onPrev={() => go(-1)}
        onNext={() => go(1)}
        hasPrev={!!active && activeIndex > 0}
        hasNext={!!active && activeIndex >= 0 && activeIndex < filtered.length - 1}
      />

      {/* No footer — delta change 2 (2026-05-23) removed the two-row footer
          (companion files + meta) entirely. The meta strip duplicated the Hero
          eyebrow's skillVersion / date / search-id; the companion-files row
          fought the "zero-chrome content rectangle" aesthetic. Both payloads
          (Open as / Print) moved into the bottom-right LayoutSwitcher popover. */}
    </>
  )
}
