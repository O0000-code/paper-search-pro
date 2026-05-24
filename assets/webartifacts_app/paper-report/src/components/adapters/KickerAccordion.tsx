// Adapter for TARGET <Accordion items kicker /> (lib.jsx 452-514).
//
// Wraps real shadcn Accordion with the TARGET visual treatment:
//   * Optional Geist-Mono "kicker" badge before the title (e.g. "01" / "02")
//   * Top + bottom hairline borders bracketing each row
//   * Open chevron animation is handled by shadcn AccordionTrigger
//
// Use `type="single"` for at-most-one-open behavior, "multiple" for
// independent toggles.

import type { ReactNode } from "react"

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"

export interface KickerAccordionItem {
  value: string
  kicker?: string
  title: string
  content: ReactNode
}

export interface KickerAccordionProps {
  items: KickerAccordionItem[]
  type?: "single" | "multiple"
  /** Only meaningful when type="single"; default closes all. */
  defaultValue?: string
  className?: string
}

export function KickerAccordion({
  items,
  type = "multiple",
  defaultValue,
  className,
}: KickerAccordionProps) {
  // shadcn Accordion type discriminates the prop union; the two branches differ
  // only in `type` / `defaultValue` shape. Render explicitly to keep TS happy.
  if (type === "single") {
    return (
      <Accordion
        type="single"
        collapsible
        defaultValue={defaultValue}
        className={className}
      >
        {items.map((it) => (
          <KickerRow key={it.value} item={it} />
        ))}
      </Accordion>
    )
  }
  return (
    <Accordion type="multiple" className={className}>
      {items.map((it) => (
        <KickerRow key={it.value} item={it} />
      ))}
    </Accordion>
  )
}

function KickerRow({ item }: { item: KickerAccordionItem }) {
  // shadcn AccordionItem default is `border-b` (separator below each row).
  // We override `last:border-b-0` so the final row doesn't draw a bottom
  // border that would overlap with the parent Card's own bottom border.
  // No `border-t` anywhere — the Card's top border serves as the cap.
  return (
    <AccordionItem
      value={item.value}
      className="border-t-0 last:border-b-0"
    >
      <AccordionTrigger className="py-3.5 hover:no-underline">
        <span className="inline-flex items-center gap-2 text-[13px] font-medium">
          {item.kicker && (
            <span className="font-mono text-[10px] font-medium text-muted-foreground px-1.5 py-0.5 rounded border">
              {item.kicker}
            </span>
          )}
          <span>{item.title}</span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="text-[13px] leading-relaxed text-muted-foreground pb-4">
        {item.content}
      </AccordionContent>
    </AccordionItem>
  )
}
