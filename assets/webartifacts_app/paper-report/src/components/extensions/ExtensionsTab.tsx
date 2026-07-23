// delta6-v2 — the Extensions tab (「拓展」): the report's dedicated container
// for capability panels beyond the core findings/methods/audit story. Every
// future feature that needs an HTML surface mounts here as another section
// (same stacking rhythm as MethodsTab: <section marginBottom 56> blocks),
// keeping the three core tabs stable.
//
// Current content: the external-database search-strategy panel. The tab
// itself is conditional — the hero Tops only render the "extensions" tab
// item when extension content exists, so a run without it shows the
// original three-tab report pixel-identical (R-19).

import type { NormalizedData } from "@/lib/types"

import { SearchStrategies } from "@/components/methods/SearchStrategies"

export function ExtensionsTab({ data }: { data: NormalizedData }) {
  return (
    <div
      className="rd-tab-extensions"
      style={{
        maxWidth: 1240,
        margin: "0 auto",
        padding: "32px 40px 80px",
        fontFamily: "var(--font-sans)",
      }}
    >
      <SearchStrategies data={data} />
    </div>
  )
}
