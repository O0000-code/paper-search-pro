// Column header for Index variant.
// Direct port of TARGET redesign/list-variants.jsx (164-185).

import { t } from "@/lib/i18n"

export function PaperRowIndexHeader() {
  return (
    <div
      className="rd-list-head"
      style={{
        display: "grid",
        gridTemplateColumns:
          "34px minmax(0, 2.4fr) minmax(0, 1fr) 52px minmax(0, 1.1fr) 80px 90px",
        gap: 14,
        alignItems: "center",
        // margin (not padding) 16: the underline stays on the content edges
        padding: "10px 0 8px",
        margin: "0 16px",
        whiteSpace: "nowrap",
        borderBottom: "1px solid hsl(var(--border))",
        fontSize: 10,
        fontWeight: 500,
        color: "hsl(var(--muted-foreground))",
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
      }}
    >
      <span>#</span>
      <span>{t("idxColTitle")}</span>
      <span>{t("idxColAuthors")}</span>
      <span>{t("idxColYear")}</span>
      <span>{t("idxColVenue")}</span>
      <span style={{ textAlign: "right" }}>{t("idxColCites")}</span>
      <span style={{ textAlign: "right" }}>RCS</span>
    </div>
  )
}
