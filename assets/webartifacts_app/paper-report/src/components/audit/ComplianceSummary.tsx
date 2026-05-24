// Port of TARGET v2-audit.jsx (84-165) — ComplianceSummary + LegendItem.
//
// Left column: DISCLOSURE eyebrow + big number (Geist 56px 500 −0.03em) + "/ 16"
// + tier-tagged caption. Right column: 28px-tall segmented bar with up to three
// flex-weighted segments (performed / implicit / skipped) and a legend below.
//
// Note: the `hsl(var(--muted-foreground) / 0.5)` opacity syntax used for the
// implicit segment / legend swatch is CSS-side HSL alpha (legal in inline
// `background` / `box-shadow`). It is NOT the same as the banned
// `text-muted-foreground/50` Tailwind utility, so it stays as inline CSS.

import { Card } from "@/components/ui/card"
import { SimpleTooltip } from "@/components/adapters/SimpleTooltip"
import { t } from "@/lib/i18n"

export interface ComplianceSummaryProps {
  total: number
  performed: number
  skipped: number
  implicit: number
  tier?: string
}

export function ComplianceSummary({
  total,
  performed,
  skipped,
  implicit,
  tier,
}: ComplianceSummaryProps) {
  const segments = [
    {
      count: performed,
      color: "hsl(var(--foreground))",
      label: t("performed"),
    },
    {
      count: implicit,
      color: "hsl(var(--muted-foreground) / 0.5)",
      label: t("implicit"),
    },
    {
      count: skipped,
      color: "hsl(var(--muted))",
      label: t("skipped"),
    },
  ]

  return (
    <Card style={{ padding: "24px 28px", boxShadow: "none" }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)",
          gap: 40,
          alignItems: "center",
        }}
      >
        {/* Left — the big number */}
        <div>
          <div
            style={{
              fontSize: 10.5,
              color: "hsl(var(--muted-foreground))",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              fontFamily: "var(--font-mono)",
              marginBottom: 14,
            }}
          >
            {t("disclosure")}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 10,
              marginBottom: 4,
            }}
          >
            <span
              className="tabular"
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 56,
                fontWeight: 500,
                letterSpacing: "-0.03em",
                lineHeight: 0.95,
              }}
            >
              {total}
            </span>
            <span
              style={{
                fontSize: 18,
                color: "hsl(var(--muted-foreground))",
                fontFamily: "var(--font-mono)",
              }}
            >
              / 16
            </span>
          </div>
          <div
            style={{
              fontSize: 13,
              color: "hsl(var(--muted-foreground))",
              marginTop: 8,
              lineHeight: 1.55,
            }}
          >
            {t("stepsDocumented", { tier: "<<TIER>>" })
              .split("<<TIER>>")
              .flatMap((part, i, arr) =>
                i < arr.length - 1
                  ? [
                      part,
                      <span
                        key={i}
                        style={{
                          fontFamily: "var(--font-mono)",
                          color: "hsl(var(--foreground))",
                          fontSize: 12,
                        }}
                      >
                        {tier || "standard"}
                      </span>,
                    ]
                  : [part],
              )}
          </div>
        </div>

        {/* Right — segmented bar + legend */}
        <div>
          <div
            style={{
              display: "flex",
              height: 28,
              borderRadius: 4,
              overflow: "hidden",
              gap: 2,
            }}
          >
            {segments.map((s, i) =>
              s.count > 0 ? (
                <SimpleTooltip
                  key={i}
                  content={`${s.label}: ${s.count}`}
                >
                  <div
                    style={{
                      flex: s.count,
                      background: s.color,
                      minWidth: 6,
                      cursor: "help",
                    }}
                  />
                </SimpleTooltip>
              ) : null,
            )}
          </div>
          <div
            style={{
              marginTop: 14,
              display: "flex",
              gap: 24,
              fontSize: 11.5,
              color: "hsl(var(--muted-foreground))",
            }}
          >
            <LegendItem
              swatch="hsl(var(--foreground))"
              count={performed}
              label={t("performed")}
              hint={t("legendPerformed")}
            />
            <LegendItem
              swatch="hsl(var(--muted-foreground) / 0.5)"
              count={implicit}
              label={t("implicit")}
              hint={t("legendImplicit")}
            />
            <LegendItem
              swatch="hsl(var(--muted))"
              count={skipped}
              label={t("skipped")}
              hint={t("legendSkipped")}
              swatchBorder
            />
          </div>
        </div>
      </div>
    </Card>
  )
}

interface LegendItemProps {
  swatch: string
  count: number
  label: string
  hint: string
  swatchBorder?: boolean
}

function LegendItem({
  swatch,
  count,
  label,
  hint,
  swatchBorder,
}: LegendItemProps) {
  return (
    <SimpleTooltip content={hint}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 7,
          cursor: "help",
        }}
      >
        <span
          style={{
            width: 9,
            height: 9,
            borderRadius: 2,
            background: swatch,
            boxShadow: swatchBorder
              ? "inset 0 0 0 1px hsl(var(--border))"
              : "none",
          }}
        />
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            color: "hsl(var(--foreground))",
            fontWeight: 500,
          }}
        >
          {count}
        </span>
        <span>{label}</span>
      </span>
    </SimpleTooltip>
  )
}
