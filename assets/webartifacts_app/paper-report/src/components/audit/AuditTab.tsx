// Port of TARGET v2-audit.jsx (5-79) — top-level AuditTabV2 layout.
//
// Layout: max-width 1240 / 32px-40px-80px padding container, SectionHeader,
// ComplianceSummary card, phase-grouped expandable rows, then a Caveats
// section with 4 KickerAlerts in a 2-column grid. The compliance counts are
// derived from the prismaLog by iterating PRISMA_TITLES keys (so the
// denominator is always 16, irrespective of how many keys exist on the
// incoming log).

import { AlertTriangle, Info } from "lucide-react"

import type { NormalizedData, PrismaStepValue } from "@/lib/types"
import {
  PHASE_ORDER,
  PRISMA_TITLES,
  parsePrismaPythonRepr,
  statusOf,
  type PrismaPhase,
} from "@/lib/prisma-titles"
import { fmtPct } from "@/lib/format"
import { t } from "@/lib/i18n"
import { KickerAlert } from "@/components/adapters/KickerAlert"
import { SectionHeader } from "@/components/methods/SectionHeader"
import { ComplianceSummary } from "./ComplianceSummary"
import { PhaseGroup, type PhaseGroupItem } from "./PhaseGroup"

export interface AuditTabProps {
  data: NormalizedData
}

const normalizeValue = (v: unknown): PrismaStepValue => {
  if (typeof v === "string" && /^\s*\{/.test(v)) {
    return parsePrismaPythonRepr(v)
  }
  if (v && typeof v === "object") return v as PrismaStepValue
  return {} as PrismaStepValue
}

export function AuditTab({ data }: AuditTabProps) {
  const log = data.prismaLog || {}

  // Group by phase, preserving PRISMA_TITLES key order within each phase.
  const byPhase: Record<PrismaPhase, PhaseGroupItem[]> = {
    Query: [],
    Discovery: [],
    Strategy: [],
    Audit: [],
  }
  for (const key of Object.keys(PRISMA_TITLES)) {
    const raw = log[key]
    if (raw === undefined) continue
    const value = normalizeValue(raw)
    const ph = PRISMA_TITLES[key].phase
    byPhase[ph].push({ stepKey: key, value })
  }

  // Compliance summary derived over the same 16 canonical keys.
  const allSteps = Object.keys(PRISMA_TITLES)
    .map((k) => ({ key: k, value: normalizeValue(log[k]) }))
    .filter(({ key }) => log[key] !== undefined)
  const performed = allSteps.filter(
    (s) => statusOf(s.value)?.positive,
  ).length
  const skipped = allSteps.filter((s) => {
    const st = statusOf(s.value)
    return st !== null && !st.positive
  }).length
  const implicit = allSteps.length - performed - skipped

  const m = data.meta
  const ciLow = m.coverageCi?.[0]
  const ciHigh = m.coverageCi?.[1]

  const limitations: Array<{
    variant: "warning" | "info"
    Icon: typeof AlertTriangle
    title: string
    detail: string
  }> = [
    {
      variant: "warning",
      Icon: AlertTriangle,
      title: t("lim1Title"),
      detail: t("lim1Body", { lo: fmtPct(ciLow), hi: fmtPct(ciHigh) }),
    },
    {
      variant: "info",
      Icon: Info,
      title: t("lim2Title"),
      detail: t("lim2Body"),
    },
    {
      variant: "warning",
      Icon: AlertTriangle,
      title: t("lim3Title"),
      detail: t("lim3Body"),
    },
    {
      variant: "info",
      Icon: Info,
      title: t("lim4Title"),
      detail: t("lim4Body"),
    },
  ]

  return (
    <div
      className="rd-tab-audit"
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "32px 40px 80px",
      }}
    >
      <div style={{ marginBottom: 24 }}>
        <SectionHeader
          kicker={t("prismaS")}
          title={t("auditTitle")}
          sub={t("auditSub")}
        />
      </div>

      {/* Compliance summary */}
      <ComplianceSummary
        total={allSteps.length}
        performed={performed}
        skipped={skipped}
        implicit={implicit}
        tier={m.tier}
      />

      {/* Phase-grouped list */}
      <div style={{ marginTop: 32 }}>
        {PHASE_ORDER.map((phase, phaseIdx) => {
          const items = byPhase[phase]
          if (!items || items.length === 0) return null
          return (
            <PhaseGroup
              key={phase}
              phase={phase}
              items={items}
              index={phaseIdx}
            />
          )
        })}
      </div>

      {/* Limitations */}
      <section style={{ marginTop: 64 }}>
        <SectionHeader
          kicker={t("caveatsKicker")}
          title={t("interpretiveLimitations")}
          sub={t("readBeforeCiting")}
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 12,
          }}
        >
          {limitations.map((l, i) => (
            <KickerAlert
              key={i}
              variant={l.variant}
              Icon={l.Icon}
              title={l.title}
            >
              {l.detail}
            </KickerAlert>
          ))}
        </div>
      </section>
    </div>
  )
}
