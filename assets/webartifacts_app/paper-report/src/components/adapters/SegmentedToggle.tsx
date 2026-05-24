// Adapter for TARGET <ToggleGroup value onChange items={[]} /> (lib.jsx 342-369).
//
// Wraps real shadcn ToggleGroup/ToggleGroupItem (single-select). Each item
// becomes a button cell with a left divider after the first; active state
// matches the TARGET visual (secondary bg + secondary-foreground).

import type { ComponentType } from "react"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

export interface SegmentedToggleItem {
  value: string
  label: string
  Icon?: ComponentType<{ className?: string }>
}

export interface SegmentedToggleProps {
  value: string
  onValueChange: (value: string) => void
  items: SegmentedToggleItem[]
  className?: string
}

export function SegmentedToggle({
  value,
  onValueChange,
  items,
  className,
}: SegmentedToggleProps) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      // ToggleGroup emits "" when the active item is clicked again; the TARGET
      // contract treats the group as always-on, so swallow empty values.
      onValueChange={(v) => {
        if (v) onValueChange(v)
      }}
      className={cn(
        "border rounded-md overflow-hidden gap-0 h-auto p-0 inline-flex w-auto",
        className,
      )}
    >
      {items.map((it, i) => (
        <ToggleGroupItem
          key={it.value}
          value={it.value}
          className={cn(
            "text-xs font-medium px-2.5 py-1.5 rounded-none inline-flex items-center gap-1.5",
            i > 0 && "border-l",
            "data-[state=on]:bg-secondary data-[state=on]:text-secondary-foreground",
            "text-muted-foreground",
          )}
        >
          {it.Icon && <it.Icon className="h-3 w-3" />}
          {it.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
