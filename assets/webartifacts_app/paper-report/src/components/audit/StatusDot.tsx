// Port of TARGET v2-audit.jsx (346-355). Three kinds:
//   performed → 9px solid foreground disc
//   skipped   → 9px hollow disc (inset 1.5px muted-foreground/0.5 border)
//   implicit  → 9px × 1.5px dash bar (muted-foreground/0.6)

export type StatusDotKind = "performed" | "skipped" | "implicit"

export interface StatusDotProps {
  kind: StatusDotKind
}

export function StatusDot({ kind }: StatusDotProps) {
  if (kind === "performed") {
    return (
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          background: "hsl(var(--foreground))",
          display: "inline-block",
        }}
      />
    )
  }
  if (kind === "skipped") {
    return (
      <span
        style={{
          width: 9,
          height: 9,
          borderRadius: "50%",
          boxShadow: "inset 0 0 0 1.5px hsl(var(--muted-foreground) / 0.5)",
          display: "inline-block",
        }}
      />
    )
  }
  // implicit
  return (
    <span
      style={{
        width: 9,
        height: 1.5,
        background: "hsl(var(--muted-foreground) / 0.6)",
        display: "inline-block",
        borderRadius: 1,
      }}
    />
  )
}
