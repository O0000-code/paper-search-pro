// Adapter for TARGET <Alert variant icon title>{children}</Alert>
// (lib.jsx 519-546).
//
// TARGET's Alert is intentionally not the shadcn cva variant; it is a
// monochrome left-border-marker callout used for non-critical notices
// (caveats, info, etc.). The four "variants" all render the same neutral
// muted treatment (TARGET assigns identical bg/border across variants —
// the differentiation lives only in the icon callers pass in). We keep the
// variant prop on the API for parity even though it is currently visually
// inert.

import type { ComponentType, ReactNode } from "react"

export type KickerAlertVariant = "default" | "info" | "warning" | "success"

export interface KickerAlertProps {
  variant?: KickerAlertVariant
  Icon?: ComponentType<{ className?: string }>
  title?: string
  children?: ReactNode
  className?: string
}

export function KickerAlert({
  Icon,
  title,
  children,
  className,
}: KickerAlertProps) {
  const cls =
    "flex gap-3 px-3.5 py-3 bg-muted/50 border-l-2 border-border rounded-r-md" +
    (className ? " " + className : "")
  return (
    <div className={cls}>
      {Icon && <Icon className="h-3.5 w-3.5 text-foreground mt-0.5 shrink-0" />}
      <div className="flex-1 min-w-0">
        {title && (
          <div className="text-[12.5px] font-semibold text-foreground mb-0.5">
            {title}
          </div>
        )}
        {children && (
          <div className="text-[12.5px] leading-relaxed text-muted-foreground">
            {children}
          </div>
        )}
      </div>
    </div>
  )
}
