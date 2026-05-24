// Thin convenience wrapper around shadcn Tooltip that matches the TARGET
// `<Tooltip content="...">...</Tooltip>` single-component shape.
//
// Always carries its own TooltipProvider so callers do not have to remember to
// mount one at the app root for ad-hoc tooltips.

import type { ReactNode } from "react"

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export interface SimpleTooltipProps {
  content: ReactNode
  children: ReactNode
  side?: "top" | "right" | "bottom" | "left"
  /** When false, no tooltip wrapper is rendered. Convenient for conditional tips. */
  enabled?: boolean
}

export function SimpleTooltip({
  content,
  children,
  side = "top",
  enabled = true,
}: SimpleTooltipProps) {
  if (!enabled || content === undefined || content === null || content === "") {
    return <>{children}</>
  }
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent side={side} className="text-xs px-2 py-1.5">
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
