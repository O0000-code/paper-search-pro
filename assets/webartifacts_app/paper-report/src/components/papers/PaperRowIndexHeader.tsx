// Column header for Index variant.
// Direct port of TARGET redesign/list-variants.jsx (164-185).

export function PaperRowIndexHeader() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns:
          "34px minmax(0, 2.4fr) minmax(0, 1fr) 52px minmax(0, 1.1fr) 80px 90px",
        gap: 14,
        alignItems: "center",
        padding: "10px 16px 8px",
        borderBottom: "1px solid hsl(var(--border))",
        fontSize: 10,
        fontWeight: 500,
        color: "hsl(var(--muted-foreground))",
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
      }}
    >
      <span style={{ textAlign: "right" }}>#</span>
      <span>Title</span>
      <span>Authors</span>
      <span>Year</span>
      <span>Venue</span>
      <span style={{ textAlign: "right" }}>Cites</span>
      <span style={{ textAlign: "right" }}>RCS</span>
    </div>
  )
}
