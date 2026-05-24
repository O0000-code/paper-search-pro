// Port of TARGET v2-methods.jsx Methodology Accordion content (138-201).
// Wraps KickerAccordion with the 4 documented methodology entries; each
// content body preserves TARGET's <p>/<ul>/<li>/<code> structure verbatim.

import { Card } from "@/components/ui/card"
import { KickerAccordion } from "@/components/adapters/KickerAccordion"
import { t } from "@/lib/i18n"

export function MethodologyAccordion() {
  return (
    <Card style={{ padding: "0 24px", borderRadius: 12, boxShadow: "none" }}>
      <KickerAccordion
        type="multiple"
        items={[
          {
            value: "rcs",
            kicker: "RCS",
            title: t("rcsAccordion"),
            content: (
              <>
                <p style={{ margin: "0 0 8px" }}>{t("rcsExplain")}</p>
                <p style={{ margin: "0 0 8px" }}>{t("tierCutoffs")}</p>
                <ul style={{ margin: "0 0 0 18px", padding: 0 }}>
                  <li>
                    <strong style={{ color: "hsl(var(--foreground))" }}>
                      {t("Foundational")}
                    </strong>{" "}
                    · {t("foundationalBullet")}
                  </li>
                  <li>
                    <strong style={{ color: "hsl(var(--foreground))" }}>
                      {t("High")}
                    </strong>{" "}
                    · {t("highBullet")}
                  </li>
                  <li>
                    <strong style={{ color: "hsl(var(--foreground))" }}>
                      {t("Moderate")}
                    </strong>{" "}
                    · {t("moderateBullet")}
                  </li>
                  <li>
                    <strong style={{ color: "hsl(var(--foreground))" }}>
                      {t("Emerging")}
                    </strong>{" "}
                    · {t("emergingBullet")}
                  </li>
                  <li>
                    <strong style={{ color: "hsl(var(--foreground))" }}>
                      {t("Peripheral")}
                    </strong>{" "}
                    · {t("peripheralBullet")}
                  </li>
                </ul>
              </>
            ),
          },
          {
            value: "coverage",
            kicker: "Coverage",
            title: t("coverageAccordion"),
            content: <p style={{ margin: 0 }}>{t("coverageExplain")}</p>,
          },
          {
            value: "dedup",
            kicker: "Dedup",
            title: t("dedupAccordion"),
            content: <p style={{ margin: 0 }}>{t("dedupExplain")}</p>,
          },
          {
            value: "theme",
            kicker: "Themes",
            title: t("themeAccordion"),
            content: <p style={{ margin: 0 }}>{t("themeExplain")}</p>,
          },
        ]}
      />
    </Card>
  )
}
