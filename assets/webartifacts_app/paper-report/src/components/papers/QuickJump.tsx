// Hover-revealed external-link icon for PaperRowCatalog + PaperRowIndex.
// 1:1 port of TARGET redesign/list-variants.jsx::QuickJump (lines 90-118).
//
// Inline-before-tier-dot placement keeps the RCS number's horizontal
// position identical to before — it lives in the right cluster's empty
// gap that would otherwise be unused when the row isn't hovered.
//
// CSS visibility is driven by .rd-paper-row:hover .rd-jump in index.css.
// `pointer-events: none` in the default state so the row's onClick fires
// reliably; switched to `auto` on hover so the icon itself is clickable.
//
// Click + Enter/Space trigger window.open with stopPropagation so the
// row's own onClick (which opens the PaperSheet) does not also fire. We
// use <span role="link"> (not <button>) so this element is not a nested
// interactive child of the row's <button> — that combination breaks HTML
// validity + accessibility tree.

import { ExternalLink } from "lucide-react"

import type { NormalizedPaper } from "@/lib/types"
import { t } from "@/lib/i18n"

export interface QuickJumpProps {
  paper: NormalizedPaper
}

export function QuickJump({ paper }: QuickJumpProps) {
  if (!paper.doiUrl) return null

  const openInNewTab = () => {
    window.open(paper.doiUrl as string, "_blank", "noopener,noreferrer")
  }

  return (
    <span
      role="link"
      tabIndex={0}
      title={`${t("open")} ${paper.doiUrl}`}
      className="rd-jump"
      style={{
        width: 22,
        height: 22,
        marginRight: 4,
        flexShrink: 0,
      }}
      onClick={(e) => {
        e.stopPropagation()
        openInNewTab()
      }}
      onMouseDown={(e) => {
        // Prevent the row's mousedown handler from also firing (button
        // elements treat mousedown as the start of a click cycle).
        e.stopPropagation()
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.stopPropagation()
          e.preventDefault()
          openInNewTab()
        }
      }}
    >
      <ExternalLink size={12} strokeWidth={1.75} />
    </span>
  )
}
