// Port of TARGET app-3-tabs.jsx (128-140) — label (10px uppercase 0.08em mono)
// + value (22px Geist Mono 600 leading 1.1) + sub (11px muted)

import type { ReactNode } from "react"

export interface StatProps {
  label: string
  value: ReactNode
  sub?: ReactNode
}

export function Stat({ label, value, sub }: StatProps) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "hsl(var(--muted-foreground))",
          marginBottom: 6,
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </div>
      <div
        className="tabular-nums"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 22,
          fontWeight: 600,
          lineHeight: 1.1,
          color: "hsl(var(--foreground))",
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontSize: 11,
            color: "hsl(var(--muted-foreground))",
            marginTop: 4,
            fontFamily: "var(--font-sans)",
          }}
        >
          {sub}
        </div>
      )}
    </div>
  )
}
