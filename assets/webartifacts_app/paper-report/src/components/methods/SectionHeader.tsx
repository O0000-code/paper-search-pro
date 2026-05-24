// Port of TARGET app-3-tabs.jsx (142-152) — kicker (mono uppercase 10.5px
// 0.1em) + h2 (17px Geist 600 -0.005em) + sub (12.5px muted max-w-72ch leading-1.55)

export interface SectionHeaderProps {
  kicker: string
  title: string
  sub?: string
}

export function SectionHeader({ kicker, title, sub }: SectionHeaderProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          fontSize: 10.5,
          fontWeight: 500,
          color: "hsl(var(--muted-foreground))",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          marginBottom: 5,
          fontFamily: "var(--font-mono)",
        }}
      >
        {kicker}
      </div>
      <h2
        style={{
          margin: 0,
          fontSize: 17,
          fontWeight: 600,
          letterSpacing: "-0.005em",
          fontFamily: "var(--font-sans)",
        }}
      >
        {title}
      </h2>
      {sub && (
        <p
          style={{
            margin: "4px 0 0",
            fontSize: 12.5,
            color: "hsl(var(--muted-foreground))",
            maxWidth: "72ch",
            lineHeight: 1.55,
            fontFamily: "var(--font-sans)",
          }}
        >
          {sub}
        </p>
      )}
    </div>
  )
}
