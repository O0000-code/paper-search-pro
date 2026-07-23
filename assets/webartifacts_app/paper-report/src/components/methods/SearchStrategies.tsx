// delta6 — External database search strategies panel (v2.4).
//
// Renders the `search_strategies` payload data_materialization folds into
// report_data.json: one flat card per platform (name + copy / open buttons +
// the paste-ready strategy in a mono block + merged ⚠️ review points), with
// conditional EN/ZH group dividers mirroring the v3 markdown rule (a group
// label only appears when BOTH language groups are present — 37 号契约).
//
// Product discipline (37 号 / 40_delta6 plan): no internal codes in the UI —
// no three-state label text, no A/B/C tier words, no linter/status field
// names. Repetitive per-term vocabulary flags are merged into ONE bullet per
// (vocab, message) family, mirroring generate.py's markdown body bullets.
//
// R-19: the component returns null when the payload is absent/empty — a run
// without STEP 11.5 renders zero new DOM (same gating idiom as delta5's
// hasAnyRank).

import { Copy, ExternalLink } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { t } from "@/lib/i18n"
import type { NormalizedData, SearchStrategyEntry } from "@/lib/types"

import { SectionHeader } from "./SectionHeader"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CJK_RE = /[一-鿿]/

function isZhPlatform(s: SearchStrategyEntry): boolean {
  return CJK_RE.test(String(s.platform ?? ""))
}

// Tagged review point: "[CMeSH] 社交媒体: CMeSH 无权威免费 API：须在 ... 人工确认"
// (tag = vocabulary name, term = the suggested heading, msg = shared suffix).
const TAGGED_POINT_RE = /^\[([^\]]+)\]\s*([^:：]+?)\s*[:：]\s*(.+)$/

// Untagged points carrying internal jargon (status-stamp explanations, linter
// rule ids, three-state label fragments) never reach the UI — same negative
// space as the v3 markdown body (37 号契约验收 4).
const INTERNAL_NOISE_RE =
  /pending_manual|机械已核|已验·|三态|\bL\d{1,2}\b|linter/i

/**
 * Merge raw review_points into user-facing bullets:
 *  - tagged points sharing (vocab, message) → ONE bullet via the
 *    `strategyVocabMerged` template ("式中 'X' 等 N 个 CMeSH 主题词为建议值…"),
 *  - singleton tagged points (e.g. the suspected-hallucination term) →
 *    "'term'（vocab）：message",
 *  - untagged human-language points pass through unless they contain
 *    internal jargon.
 */
export function mergeReviewPoints(points: string[]): string[] {
  const families = new Map<string, { vocab: string; terms: string[]; msg: string }>()
  const out: string[] = []
  const order: Array<{ kind: "family"; key: string } | { kind: "raw"; text: string }> = []

  for (const raw of points) {
    const point = String(raw ?? "").trim()
    if (!point) continue
    const m = TAGGED_POINT_RE.exec(point)
    if (m) {
      const [, vocab, term, msg] = m
      const key = `${vocab}|${msg}`
      const fam = families.get(key)
      if (fam) {
        fam.terms.push(term)
      } else {
        families.set(key, { vocab, terms: [term], msg })
        order.push({ kind: "family", key })
      }
      continue
    }
    if (INTERNAL_NOISE_RE.test(point)) continue
    order.push({ kind: "raw", text: point })
  }

  for (const item of order) {
    if (item.kind === "raw") {
      out.push(item.text)
      continue
    }
    const fam = families.get(item.key)
    if (!fam) continue
    if (fam.terms.length >= 2) {
      out.push(
        t("strategyVocabMerged", {
          first: fam.terms[0],
          n: fam.terms.length,
          vocab: fam.vocab,
        }),
      )
    } else {
      out.push(`'${fam.terms[0]}'（${fam.vocab}）：${fam.msg}`)
    }
  }
  return out
}

/**
 * Resolve the "open" href: prefer the constructed deep_link.url; otherwise
 * fill the card's url_template — `{urlenc}` takes the URL-encoded strategy
 * string (that is exactly what a browser-tier template expects). A template
 * with any *unfilled* placeholder left must never leak into a clickable
 * link (found live: 万方 rendered `?q={urlenc}` verbatim) — return null.
 */
export function resolveOpenHref(s: SearchStrategyEntry): string | null {
  const link = s.deep_link ?? {}
  if (link.url) return link.url
  const tpl = link.url_template
  if (!tpl) return null
  const filled = s.strategy_string
    ? tpl.replace(/\{urlenc\}/g, encodeURIComponent(s.strategy_string))
    : tpl
  return filled.includes("{") ? null : filled
}

async function copyStrategy(s: SearchStrategyEntry): Promise<void> {
  const text = s.strategy_string ?? ""
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    toast.success(t("strategyCopiedToast"), {
      description: s.platform ?? undefined,
    })
  } catch {
    // Same failure branch as PaperSheet's copy-DOI (non-secure context /
    // clipboard permission) — surface an error toast, never throw.
    toast.error(t("strategyCopyErrorToast"))
  }
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function GroupLabel({ children }: { children: string }) {
  // Same voice as SectionHeader's kicker (mono uppercase 10.5px 0.1em) —
  // a quiet divider, not a heading.
  return (
    <div
      style={{
        fontSize: 10.5,
        fontWeight: 500,
        color: "hsl(var(--muted-foreground))",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        fontFamily: "var(--font-mono)",
        margin: "6px 0 0",
      }}
    >
      {children}
    </div>
  )
}

function StrategyCard({ s }: { s: SearchStrategyEntry }) {
  const href = resolveOpenHref(s)
  const bullets = mergeReviewPoints(s.review_points ?? [])

  return (
    <Card style={{ padding: "20px 24px", borderRadius: 12, boxShadow: "none" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "var(--font-sans)",
            letterSpacing: "-0.005em",
            minWidth: 0,
          }}
        >
          {s.platform}
        </div>
        {/* delta6-v2 — ONE primary action per card. With a resolvable URL the
            solid button copies the strategy AND opens the search page in a new
            tab (anchor default navigation keeps the user gesture, so no popup
            blocking; the copy happens in onClick before the tab switches).
            Without a URL (e.g. CNKI's captcha wall) it degrades to a quiet
            outline copy-only button. */}
        {href ? (
          <Button
            variant="default"
            size="sm"
            asChild
            style={{ fontSize: 12, height: 30, flexShrink: 0 }}
          >
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => void copyStrategy(s)}
            >
              <ExternalLink style={{ width: 13, height: 13 }} />
              {t("strategyCopyOpen")}
            </a>
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void copyStrategy(s)}
            style={{ fontSize: 12, height: 30, flexShrink: 0 }}
          >
            <Copy style={{ width: 13, height: 13 }} />
            {t("strategyCopy")}
          </Button>
        )}
      </div>

      <pre
        style={{
          margin: 0,
          padding: "12px 14px",
          background: "hsl(var(--muted) / 0.5)",
          border: "1px solid hsl(var(--border))",
          borderRadius: 8,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          lineHeight: 1.6,
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          color: "hsl(var(--foreground))",
        }}
      >
        {s.strategy_string}
      </pre>

      {bullets.length > 0 && (
        <div style={{ marginTop: 10, display: "grid", gap: 5 }}>
          {bullets.map((b, i) => (
            <p
              key={i}
              style={{
                margin: 0,
                fontSize: 11.5,
                lineHeight: 1.55,
                color: "hsl(var(--muted-foreground))",
                fontFamily: "var(--font-sans)",
              }}
            >
              {"⚠️ "}
              {b}
            </p>
          ))}
        </div>
      )}
    </Card>
  )
}

function WithheldRow({ s }: { s: SearchStrategyEntry }) {
  const reason =
    (s.review_points ?? []).map((p) => String(p ?? "").trim()).find(Boolean) ||
    t("strategyWithheld")
  return (
    <p
      style={{
        margin: 0,
        padding: "2px 4px",
        fontSize: 12,
        lineHeight: 1.55,
        color: "hsl(var(--muted-foreground))",
        fontFamily: "var(--font-sans)",
      }}
    >
      {s.platform} — {reason}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Section
// ---------------------------------------------------------------------------

export function SearchStrategies({ data }: { data: NormalizedData }) {
  const all = data.searchStrategies?.strategies ?? []
  if (all.length === 0) return null

  const en = all.filter((s) => !isZhPlatform(s))
  const zh = all.filter((s) => isZhPlatform(s))
  // Group dividers only when BOTH language groups are present (37 号规则:
  // a header that distinguishes nothing must not exist).
  const grouped = en.length > 0 && zh.length > 0

  function renderList(list: SearchStrategyEntry[]) {
    return list.map((s, i) =>
      s.strategy_string ? (
        <StrategyCard key={`${s.platform}-${i}`} s={s} />
      ) : (
        <WithheldRow key={`${s.platform}-${i}`} s={s} />
      ),
    )
  }

  return (
    <section style={{ marginBottom: 56 }}>
      <SectionHeader
        kicker={t("strategiesKicker")}
        title={t("strategiesTitle")}
        sub={t("strategiesSub")}
      />
      <div style={{ display: "grid", gap: 12 }}>
        {grouped && en.length > 0 && (
          <GroupLabel>{t("strategyGroupEn")}</GroupLabel>
        )}
        {renderList(en)}
        {grouped && zh.length > 0 && (
          <GroupLabel>{t("strategyGroupZh")}</GroupLabel>
        )}
        {renderList(zh)}
      </div>
      <p
        style={{
          margin: "12px 0 0",
          paddingTop: 10,
          borderTop: "1px solid hsl(var(--border))",
          fontSize: 11.5,
          lineHeight: 1.55,
          color: "hsl(var(--muted-foreground))",
          fontFamily: "var(--font-sans)",
        }}
      >
        {t("strategiesFootnote")}
      </p>
    </section>
  )
}
