// Icon-prefixed Input adapter — TARGET <Input icon="search" /> equivalent.
//
// shadcn Input doesn't accept a leading icon slot; this adapter prefixes a
// Search icon and pads the input. Pass any normal <input> props through.

import { Search } from "lucide-react"
import type { InputHTMLAttributes } from "react"

import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

export type SearchInputProps = InputHTMLAttributes<HTMLInputElement>

export function SearchInput({ className, ...rest }: SearchInputProps) {
  return (
    <div className="relative inline-flex items-center w-full">
      <Search className="absolute left-3 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
      <Input
        {...rest}
        className={cn("pl-9 h-[34px] text-[13px]", className)}
      />
    </div>
  )
}
