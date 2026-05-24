// Port of TARGET v2-audit.jsx (170-205) — phase header + bordered list of
// PrismaRow children. The header is `PHASE` mono uppercase 10.5px 0.14em +
// count mono 10.5px opacity 0.6 + flex-1 hairline; the list is wrapped in an
// inset 1px shadow with rounded corners and overflow hidden so the last row's
// dividers don't bleed out.

import type { PrismaStepValue } from "@/lib/types"
import { PHASE_ORDER, type PrismaPhase } from "@/lib/prisma-titles"
import { t, type Strings } from "@/lib/i18n"
import { PrismaRow } from "./PrismaRow"

// Phase name (Query | Discovery | Strategy | Audit) → translated dict key.
// Built once at module load. EN dict gives back the English literal so the
// fallback path remains identity.
const PHASE_LABEL_KEY: Record<PrismaPhase, keyof Strings> = {
  Query: "auditPhaseQuery",
  Discovery: "auditPhaseDiscovery",
  Strategy: "auditPhaseStrategy",
  Audit: "auditPhaseAudit",
}

export interface PhaseGroupItem {
  stepKey: string
  value: PrismaStepValue
}

export interface PhaseGroupProps {
  phase: PrismaPhase
  items: PhaseGroupItem[]
  index: number
}

export function PhaseGroup({ phase, items, index }: PhaseGroupProps) {
  return (
    <section
      style={{
        marginBottom: index === PHASE_ORDER.length - 1 ? 0 : 36,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 0,
          padding: "14px 4px",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            fontWeight: 500,
            color: "hsl(var(--muted-foreground))",
            textTransform: "uppercase",
            letterSpacing: "0.14em",
          }}
        >
          {t(PHASE_LABEL_KEY[phase])}
        </span>
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "hsl(var(--muted-foreground))",
            opacity: 0.6,
          }}
        >
          {items.length}
        </span>
        <div
          style={{
            flex: 1,
            height: 1,
            background: "hsl(var(--border))",
          }}
        />
      </div>
      <div
        style={{
          boxShadow: "inset 0 0 0 1px hsl(var(--border))",
          borderRadius: "var(--radius)",
          overflow: "hidden",
        }}
      >
        {items.map((it, i) => (
          <PrismaRow
            key={it.stepKey}
            stepKey={it.stepKey}
            value={it.value}
            divider={i < items.length - 1}
          />
        ))}
      </div>
    </section>
  )
}
