// delta6-v3 — External database search strategies panel (v2.4).
//
// Renders the `search_strategies` payload data_materialization folds into
// report_data.json as a collapsible index that reuses the Audit tab's list
// idiom (PhaseGroup + PrismaRow): mono group header with count + trailing
// hairline, one rounded bordered list per group, 1px row dividers, chevron
// on the right. Rationale + the user's Claude.design rulings this follows:
// Enhancement/Paper Search Pro/search-strategy-export/42_delta6v3_extensions_redesign.md
//
// Row = platform name · to-verify count · ONE outline action ("Copy & open":
// clipboard + new tab; copy-only when no URL resolves) · chevron. Rows start
// collapsed (the action works without expanding). The body is separated by a
// dashed rule (user ruling 2026-07-25: no grey fills) and shows the strategy
// broken at top-level concept blocks and de-noised for a professional reader:
// the strategy is shown verbatim (no paraphrase layer), search terms in ink,
// syntax (field tags, quotes, parentheses, OR) receded; AND/NOT stay heavier;
// unverified controlled-vocabulary headings underlined in place, then the
// review notes. Copy always yields the raw strategy_string, byte-for-byte.
//
// Product discipline (37 号): no internal codes in the UI — no three-state
// label text, no A/B/C tier words, no field names.
//
// R-19: returns null when the payload is absent/empty — a run without
// STEP 11.5 renders zero new DOM.

import * as React from "react"
import {
  Check,
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  Copy,
  ExternalLink,
  Info,
  TriangleAlert,
} from "lucide-react"
import { toast } from "sonner"

import { t } from "@/lib/i18n"
import type {
  NormalizedData,
  SearchStrategyEntry,
  StrategyVocabTerm,
} from "@/lib/types"

import { SectionHeader } from "./SectionHeader"

// ---------------------------------------------------------------------------
// Data helpers
// ---------------------------------------------------------------------------

const CJK_RE = /[一-鿿]/

function isZhPlatform(s: SearchStrategyEntry): boolean {
  return CJK_RE.test(String(s.platform ?? ""))
}

// Tagged review point: "[CMeSH] 社交媒体: CMeSH 无权威免费 API：须在 ... 人工确认"
const TAGGED_POINT_RE = /^\[([^\]]+)\]\s*([^:：]+?)\s*[:：]\s*(.+)$/

// Untagged points carrying internal jargon (status-stamp explanations, linter
// rule ids, three-state label fragments) never reach the UI.
const INTERNAL_NOISE_RE =
  /pending_manual|机械已核|已验·|三态|\bL\d{1,2}\b|linter|\bD-[a-z]\b|宿主|语法卡|模板化|\.md\b/i

// Known actionable message: the platform's heading syntax could not be
// generated, so the strategy carries free text only — shown in plain words.
const CV_OMITTED_RE = /受控词候选未写入检索串/

// A review message that says the heading was NOT found (suspected invalid /
// hallucinated) rather than merely "unverifiable, please confirm".
const SUSPECT_MSG_RE = /疑似非|幻觉|空结果|hallucinat/i

// A heading the generator already culled from the vocabulary clause and
// rewrote as free text (status not_found) — nothing left for the user to check.
const DOWNGRADED_MSG_RE = /已降级|downgrad/i

type FlagKind = "confirm" | "suspect"
type NoteKind = FlagKind | "info"

interface ReviewNote {
  kind: NoteKind
  vocab?: string
  terms?: string[]
  text?: string
}

interface ReviewModel {
  /** headingKey → kind, for in-place highlighting inside the strategy */
  flagged: Map<string, FlagKind>
  notes: ReviewNote[]
}

function termKind(v: StrategyVocabTerm): FlagKind | null {
  // verified: nothing to check; not_found: already downgraded to free text.
  if (v.status === "verified" || v.status === "not_found") return null
  if (v.soft_crosscheck === "empty") return "suspect"
  return "confirm"
}

/**
 * Build the review model. Structured `controlled_vocab_terms` win when
 * present (they carry the verification status + soft cross-check); otherwise
 * the tagged `review_points` strings are parsed. A heading only counts when
 * the strategy actually contains it — as a vocabulary token (then it is also
 * underlined in place) or at least as text (kept, so an unrecognised syntax
 * can never silently drop a review cue). Headings a platform omitted are not
 * this strategy's to check. Untagged human-language points pass through as
 * plain notes unless they carry internal jargon.
 */
export function buildReviewModel(s: SearchStrategyEntry): ReviewModel {
  const raw = s.strategy_string ?? ""
  const inVocab = new Set(
    segmentStrategy(raw)
      .filter((g) => g.kind === "cv")
      .map((g) => g.key as string),
  )
  const rawLower = raw.toLowerCase()

  const pending: Array<{ term: string; vocab: string; kind: FlagKind }> = []
  const structured = (s.controlled_vocab_terms ?? []).filter((v) => v && v.term)
  for (const v of structured) {
    const kind = termKind(v)
    if (kind) pending.push({ term: String(v.term), vocab: String(v.vocab ?? ""), kind })
  }

  const extra: ReviewNote[] = []
  for (const rawPoint of s.review_points ?? []) {
    const point = String(rawPoint ?? "").trim()
    if (!point) continue
    const m = TAGGED_POINT_RE.exec(point)
    if (m) {
      const [, vocab, term, msg] = m
      if (structured.length === 0 && !DOWNGRADED_MSG_RE.test(msg)) {
        pending.push({ term, vocab, kind: SUSPECT_MSG_RE.test(msg) ? "suspect" : "confirm" })
      }
      continue
    }
    if (CV_OMITTED_RE.test(point)) {
      extra.push({ kind: "info", text: t("strategyNoteCvOmitted") })
      continue
    }
    if (INTERNAL_NOISE_RE.test(point)) continue
    extra.push({ kind: "info", text: point })
  }

  const flagged = new Map<string, FlagKind>()
  const groups = new Map<string, ReviewNote>()
  for (const p of pending) {
    const key = headingKey(p.term)
    if (!key || flagged.has(key)) continue
    if (!inVocab.has(key) && !rawLower.includes(key)) continue
    flagged.set(key, p.kind)
    const gk = `${p.kind}|${p.vocab}`
    const g = groups.get(gk)
    if (g) g.terms!.push(p.term)
    else groups.set(gk, { kind: p.kind, vocab: p.vocab, terms: [p.term] })
  }
  // Suspects first — they are the ones most likely to need an edit.
  const notes = [
    ...[...groups.values()].filter((n) => n.kind === "suspect"),
    ...[...groups.values()].filter((n) => n.kind === "confirm"),
    ...extra,
  ]
  return { flagged, notes }
}

/**
 * Resolve the "open" href, three data-driven rungs (mirrors the MD renderer):
 *  1. deep_link.url — a ready-to-run link (query rides along), unless it
 *     still carries an unfilled `{placeholder}`;
 *  2. deep_link.url_template with `{urlenc}` filled from the URL-encoded
 *     strategy string. A template with any *unfilled* placeholder must never
 *     leak into a clickable link — fall through;
 *  3. the platform's entry page derived from the `host` field ("中国知网 /
 *     kns.cnki.net" → https://kns.cnki.net) — same rule as generate.py's
 *     `_host_entry_url`: the page opens, the user pastes.
 */
export function resolveOpenHref(s: SearchStrategyEntry): string | null {
  const link = s.deep_link ?? {}
  if (link.url && !link.url.includes("{")) return link.url
  const tpl = link.url_template
  if (tpl) {
    const filled = s.strategy_string
      ? tpl.replace(/\{urlenc\}/g, encodeURIComponent(s.strategy_string))
      : tpl
    if (!filled.includes("{")) return filled
  }
  const m = /[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}/.exec(String(s.host ?? ""))
  return m ? `https://${m[0]}` : null
}

/** Human reason for a withheld platform — strips the generic "rejected,
 *  withheld:" preamble and any parenthesised internal field names. */
function withheldReason(s: SearchStrategyEntry): string {
  const first = (s.review_points ?? [])
    .map((p) => String(p ?? "").trim())
    .find(Boolean)
  if (!first) return t("strategyWithheld")
  return first
    .replace(/^[^：:]*扣发[：:]\s*/, "")
    .replace(/\s*[（(][A-Za-z0-9_]+[）)]/g, "")
    .trim() || t("strategyWithheld")
}

// ---------------------------------------------------------------------------
// Strategy typesetting (display only — copy uses the raw string)
// ---------------------------------------------------------------------------

interface QuotePart {
  text: string
  quoted: boolean
  /** an unterminated quote and everything after it — never read as syntax */
  inert?: boolean
}

const WORD_CH_RE = /[\p{L}\p{N}]/u

/** Split a line into quoted / unquoted parts. Lossless (parts join back to the
 *  input). `"` always delimits; `'` only opens after a non-word character and
 *  only closes before one, so apostrophes (crohn's, women's) stay text. A
 *  quoted part keeps a trailing vocabulary suffix (`'student'/exp`). */
function splitQuoted(line: string): QuotePart[] {
  const out: QuotePart[] = []
  let plainStart = 0
  let i = 0
  while (i < line.length) {
    const c = line[i]
    const opens = c === '"' || (c === "'" && !WORD_CH_RE.test(line[i - 1] ?? ""))
    if (!opens) {
      i++
      continue
    }
    let j = i + 1
    while (j < line.length) {
      if (line[j] === c && !(c === "'" && WORD_CH_RE.test(line[j + 1] ?? ""))) break
      j++
    }
    if (plainStart < i) out.push({ text: line.slice(plainStart, i), quoted: false })
    if (j >= line.length) {
      out.push({ text: line.slice(i), quoted: false, inert: true })
      return out
    }
    let end = j + 1
    const suffix = /^\/[A-Za-z]+/.exec(line.slice(end))
    if (suffix) end += suffix[0].length
    out.push({ text: line.slice(i, end), quoted: true })
    i = plainStart = end
  }
  if (plainStart < line.length) out.push({ text: line.slice(plainStart), quoted: false })
  return out
}

/** Split a one-line strategy at top-level AND/and so each concept block
 *  starts its own line. Strings that already carry line breaks are kept as
 *  authored (WOS/Scopus nest their blocks inside a field tag). Parentheses
 *  and the AND are only read outside quotes. */
export function logicalLines(raw: string): string[] {
  if (raw.includes("\n")) return raw.split("\n")
  const cuts: number[] = []
  let depth = 0
  let pos = 0
  for (const part of splitQuoted(raw)) {
    if (!part.quoted && !part.inert) {
      const tx = part.text
      for (let k = 0; k < tx.length; k++) {
        const c = tx[k]
        if (c === "(") depth++
        else if (c === ")") depth = Math.max(0, depth - 1)
        else if (depth === 0 && c === " " && /^ (AND|and) \(/.test(tx.slice(k)) && pos + k > 0) {
          cuts.push(pos + k)
        }
      }
    }
    pos += part.text.length
  }
  const lines: string[] = []
  let start = 0
  for (const cut of cuts) {
    lines.push(raw.slice(start, cut))
    start = cut + 1 // the space before AND; display only
  }
  lines.push(raw.slice(start))
  return lines
}

// A strategy line as typed segments. Quote-aware, and lossless: joining the
// segments' text reproduces the input exactly.
interface Seg {
  text: string
  kind: "text" | "strong" | "soft" | "cv"
  /** headingKey of a controlled-vocabulary heading (kind "cv" only) */
  key?: string
}

const OP_SPLIT_RE = /\b(AND|OR|NOT|and|or|not)\b/
const STRONG_OP_RE = /^(AND|NOT|and|not)$/
// Context that makes a quoted phrase a heading rather than free text:
//   (MH "x+")  DE "x"  descriptor:"x"   — prefix;   "x"[mh]  — suffix.
const CV_PREFIX_RE = /(?:^|[\s(])(?:MH|MM|MJ|DE)\s$|descriptor:$/
const CV_SUFFIX_RE = /^\[(?:mh|mesh|majr)(?::noexp)?\]/i
// Ovid heading, unquoted: `exp nursing student/` or `Mindfulness/`. The
// heading may contain spaces but never a boolean operator.
const OVID_RE =
  /(^|[\s(])((?:exp\s+)?((?!(?:AND|OR|NOT|and|or|not)\b)[^()\s"'/](?:(?!\s(?:AND|OR|NOT|and|or|not)\b)[^()"'/\n])*?)\/)(?=[\s)]|$)/g

export function headingKey(term: string): string {
  return term.trim().replace(/\+$/, "").trim().toLowerCase()
}

/** Heading carried by a quoted token, or null when it is free text.
 *  `'student'/exp` · `"社交媒体/全部树/全部副主题词"` · `"Students"[mh]` ·
 *  `(MH "Students, Nursing+")` · `DE "College Students"` · `descriptor:"x"` */
function quotedHeading(tok: string, prev: string, next: string): string | null {
  const suffix = /\/[A-Za-z]+$/.exec(tok)
  const body = suffix ? tok.slice(0, suffix.index) : tok
  const inner = body.slice(1, -1)
  if (suffix) return inner
  // SinoMed CMeSH has one machine form: "<heading>/全部树/全部副主题词"
  const cmesh = /^([^/]+)\/全部(?:树|副主题词)(?:\/|$)/.exec(inner)
  if (tok[0] === '"' && cmesh) return cmesh[1]
  if (CV_SUFFIX_RE.test(next) || CV_PREFIX_RE.test(prev)) return inner
  return null
}

function pushOps(out: Seg[], text: string) {
  text.split(OP_SPLIT_RE).forEach((part, i) => {
    if (!part) return
    if (i % 2 === 1) out.push({ text: part, kind: STRONG_OP_RE.test(part) ? "strong" : "soft" })
    else out.push({ text: part, kind: "text" })
  })
}

function pushPlain(out: Seg[], text: string) {
  let last = 0
  for (const m of text.matchAll(OVID_RE)) {
    const start = (m.index ?? 0) + m[1].length
    pushOps(out, text.slice(last, start))
    out.push({ text: m[2], kind: "cv", key: headingKey(m[3]) })
    last = start + m[2].length
  }
  pushOps(out, text.slice(last))
}

export function segmentStrategy(line: string): Seg[] {
  const out: Seg[] = []
  const parts = splitQuoted(line)
  parts.forEach((part, i) => {
    if (part.inert) {
      out.push({ text: part.text, kind: "text" })
      return
    }
    if (!part.quoted) {
      pushPlain(out, part.text)
      return
    }
    const prev = parts[i - 1] && !parts[i - 1].quoted ? parts[i - 1].text : ""
    const next = parts[i + 1] && !parts[i + 1].quoted ? parts[i + 1].text : ""
    const heading = quotedHeading(part.text, prev, next)
    if (heading) out.push({ text: part.text, kind: "cv", key: headingKey(heading) })
    else out.push({ text: part.text, kind: "text" })
  })
  return out
}

// Syntax a professional reads past: field tags, field-scope wrappers,
// parentheses, CNKI's SU %=, EBSCO's MH/DE prefixes, ERIC's descriptor:.
const SYNTAX_RE =
  /(\[[^\]]*\]|:(?:ti|ab|kw)(?:,(?:ti|ab|kw))*|\.(?:ti|ab|kw|sh|mp|tw)(?:,(?:ti|ab|kw|sh|mp|tw))*\.|TITLE-ABS-KEY\(|\b[A-Z]{2,}=\(?|%=|\bSU\b|\b(?:MH|MM|MJ|DE)\b|descriptor:|[()])/

const INK = "hsl(var(--foreground))"

/** Terms in ink; everything syntactic inherits the block's muted colour.
 *  Lossless — it only wraps text, never rewrites it. */
function inkTerms(text: string, keyBase: string): React.ReactNode[] {
  if (text[0] === '"' || text[0] === "'") {
    const close = text.lastIndexOf(text[0])
    if (close > 0) {
      return [
        text[0],
        <span key={keyBase + "i"} style={{ color: INK }}>
          {text.slice(1, close)}
        </span>,
        text.slice(close),
      ]
    }
  }
  return text.split(SYNTAX_RE).flatMap((part, i) => {
    if (!part) return []
    if (i % 2 === 1) return [part]
    return part.split(/(\s+)/).map((w, j) =>
      /\S/.test(w) ? (
        <span key={`${keyBase}-${i}-${j}`} style={{ color: INK }}>
          {w}
        </span>
      ) : (
        w
      ),
    )
  })
}

function renderLine(line: string, flagged: Map<string, FlagKind>): React.ReactNode[] {
  return segmentStrategy(line).map((g, i) => {
    // Weight follows structure, not frequency: AND/NOT join concept blocks
    // (few, landmarks) → heavier; OR joins synonyms inside a block (dozens)
    // → recedes so the terms stay the readable layer.
    if (g.kind === "strong") {
      return (
        <span key={i} style={{ fontWeight: 600, color: INK }}>
          {g.text}
        </span>
      )
    }
    if (g.kind === "soft") {
      return (
        <span key={i} style={{ opacity: 0.75 }}>
          {g.text}
        </span>
      )
    }
    // Only a vocabulary token is underlined — the same words used as free
    // text ('nursing student') are not headings.
    const kind = g.kind === "cv" && g.key ? flagged.get(g.key) : undefined
    if (kind) {
      return (
        <span
          key={i}
          title={t(kind === "suspect" ? "strategyFlagSuspectTitle" : "strategyFlagTitle")}
          style={{
            color: "hsl(var(--foreground))",
            textDecorationLine: "underline",
            textDecorationStyle: "dashed",
            textDecorationColor: "hsl(var(--foreground) / 0.55)",
            textDecorationThickness: 1,
            textUnderlineOffset: 4,
            cursor: "help",
          }}
        >
          {g.text}
        </span>
      )
    }
    if (g.kind === "cv") {
      return (
        <span key={i} style={{ color: INK }}>
          {g.text}
        </span>
      )
    }
    return <React.Fragment key={i}>{inkTerms(g.text, `t${i}`)}</React.Fragment>
  })
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Same failure branch as PaperSheet's copy-DOI (non-secure context /
    // clipboard permission) — surface an error toast, never throw.
    toast.error(t("strategyCopyErrorToast"))
    return false
  }
}

const actionStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 30,
  padding: "0 11px",
  borderRadius: "calc(var(--radius) - 2px)",
  border: "1px solid hsl(var(--border))",
  background: "hsl(var(--background))",
  color: "hsl(var(--foreground))",
  fontFamily: "var(--font-sans)",
  fontSize: 12,
  fontWeight: 500,
  lineHeight: 1,
  whiteSpace: "nowrap",
  textDecoration: "none",
  cursor: "pointer",
  flexShrink: 0,
  transition: "background .12s, border-color .12s",
}

function ActionButton({ s }: { s: SearchStrategyEntry }) {
  const href = resolveOpenHref(s)
  const [done, setDone] = React.useState(false)
  const [hover, setHover] = React.useState(false)
  const timer = React.useRef<number | undefined>(undefined)
  React.useEffect(() => () => window.clearTimeout(timer.current), [])

  const onCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (await writeClipboard(s.strategy_string ?? "")) {
      setDone(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setDone(false), 2000)
    }
  }

  const style: React.CSSProperties = {
    ...actionStyle,
    background: hover ? "hsl(var(--accent))" : actionStyle.background,
    borderColor: hover ? "hsl(var(--foreground) / 0.25)" : "hsl(var(--border))",
  }
  const icon = done ? (
    <Check size={13} strokeWidth={2.25} />
  ) : href ? (
    <ExternalLink size={13} />
  ) : (
    <Copy size={13} />
  )
  const label = done ? t("strategyCopied") : href ? t("strategyCopyOpen") : t("strategyCopy")
  const common = {
    style,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    className: "rd-strategy-action",
  }

  // The anchor's default navigation keeps the user gesture (no popup
  // blocking); the copy runs in onClick before the tab switches.
  return href ? (
    <a
      {...common}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => void onCopy(e)}
    >
      {icon}
      {label}
    </a>
  ) : (
    <button {...common} type="button" onClick={(e) => void onCopy(e)}>
      {icon}
      {label}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

const mutedMono: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10.5,
  fontWeight: 500,
  color: "hsl(var(--muted-foreground))",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  whiteSpace: "nowrap",
}

function NoteLine({ n }: { n: ReviewNote }) {
  const Icon = n.kind === "suspect" ? TriangleAlert : Info
  const message =
    n.kind === "suspect"
      ? t("strategyNoteSuspect", { vocab: n.vocab ?? "" })
      : n.kind === "confirm"
        ? t("strategyNoteConfirm", { vocab: n.vocab ?? "" })
        : n.text
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <Icon
        size={13}
        strokeWidth={2}
        style={{
          flexShrink: 0,
          marginTop: 3,
          color:
            n.kind === "suspect"
              ? "hsl(var(--foreground))"
              : "hsl(var(--muted-foreground))",
        }}
      />
      <p style={{ margin: 0, fontSize: 12, lineHeight: 1.6, color: "hsl(var(--muted-foreground))" }}>
        {n.terms && n.terms.length > 0 && (
          <>
            <span style={{ fontWeight: 500, color: "hsl(var(--foreground))" }}>
              {n.terms.join(" · ")}
            </span>
            {" — "}
          </>
        )}
        {message}
      </p>
    </div>
  )
}

function StrategyRow({
  s,
  id,
  open,
  onToggle,
  divider,
}: {
  s: SearchStrategyEntry
  id: string
  open: boolean
  onToggle: () => void
  divider: boolean
}) {
  const [hover, setHover] = React.useState(false)
  const raw = s.strategy_string ?? ""
  const review = React.useMemo(() => buildReviewModel(s), [s])
  const lines = React.useMemo(() => logicalLines(raw), [raw])
  const toVerify = review.flagged.size
  const hasSuspect = [...review.flagged.values()].includes("suspect")

  return (
    <div style={{ borderBottom: divider ? "1px solid hsl(var(--border))" : "none" }}>
      <div
        onClick={onToggle}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "12px 14px 12px 18px",
          cursor: "pointer",
        }}
      >
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={(e) => {
            e.stopPropagation()
            onToggle()
          }}
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            alignItems: "baseline",
            gap: 12,
            padding: 0,
            border: 0,
            background: "transparent",
            textAlign: "left",
            cursor: "pointer",
            fontFamily: "var(--font-sans)",
            color: "hsl(var(--foreground))",
          }}
        >
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              letterSpacing: "-0.005em",
              textDecorationLine: hover ? "underline" : "none",
              textDecorationThickness: 1,
              textUnderlineOffset: 4,
              textDecorationColor: "hsl(var(--foreground) / 0.3)",
            }}
          >
            {s.platform}
          </span>
          {/* Rows start collapsed, so this count is the only review cue a
              user sees before copying — foreground ink + the same icon the
              expanded notes use (warning when any heading looks invalid). */}
          {toVerify > 0 && (
            <span
              className="tabular"
              style={{
                ...mutedMono,
                color: "hsl(var(--foreground))",
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                alignSelf: "center",
              }}
            >
              {hasSuspect ? (
                <TriangleAlert size={12} strokeWidth={2} />
              ) : (
                <Info size={12} strokeWidth={2} />
              )}
              {t("strategyToVerify", { n: toVerify })}
            </span>
          )}
        </button>
        <ActionButton s={s} />
        <ChevronDown
          size={14}
          aria-hidden
          style={{
            flexShrink: 0,
            color: hover ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))",
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform .15s, color .12s",
          }}
        />
      </div>

      {open && (
        <div
          id={id}
          style={{
            borderTop: "1px dashed hsl(var(--border))",
            margin: "0 18px",
            padding: "14px 0 16px",
          }}
        >
          <pre
            style={{
              margin: 0,
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.8,
              color: "hsl(var(--muted-foreground))",
              whiteSpace: "pre-wrap",
              overflowWrap: "break-word",
              tabSize: 2,
            }}
          >
            {lines.map((ln, i) => (
              <span
                key={i}
                style={{ display: "block", paddingLeft: "4ch", textIndent: "-4ch" }}
              >
                {renderLine(ln, review.flagged)}
              </span>
            ))}
          </pre>
          {review.notes.length > 0 && (
            <div
              style={{
                display: "grid",
                gap: 6,
                marginTop: 14,
                paddingTop: 12,
                borderTop: "1px dashed hsl(var(--border))",
              }}
            >
              {review.notes.map((n, i) => (
                <NoteLine key={i} n={n} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WithheldRow({ s, divider }: { s: SearchStrategyEntry; divider: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 14,
        padding: "13px 18px",
        borderBottom: divider ? "1px solid hsl(var(--border))" : "none",
      }}
    >
      <span
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: "hsl(var(--muted-foreground))",
          flexShrink: 0,
        }}
      >
        {s.platform}
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: 12,
          lineHeight: 1.6,
          color: "hsl(var(--muted-foreground))",
        }}
      >
        {withheldReason(s)}
      </span>
      <span style={mutedMono}>{t("strategyWithheldStatus")}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Group + section
// ---------------------------------------------------------------------------

function GroupHeader({ label, count }: { label: string; count: number }) {
  // Same header as the Audit tab's PhaseGroup: mono label + count + hairline.
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "14px 4px" }}>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          fontWeight: 500,
          color: "hsl(var(--muted-foreground))",
          textTransform: "uppercase",
          letterSpacing: "0.14em",
        }}
      >
        {label}
      </span>
      <span
        className="tabular"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "hsl(var(--muted-foreground))",
          opacity: 0.6,
        }}
      >
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: "hsl(var(--border))" }} />
    </div>
  )
}

interface Item {
  s: SearchStrategyEntry
  key: string
}

function StrategyList({
  items,
  openKeys,
  toggle,
}: {
  items: Item[]
  openKeys: Set<string>
  toggle: (k: string) => void
}) {
  return (
    <div
      style={{
        boxShadow: "inset 0 0 0 1px hsl(var(--border))",
        borderRadius: "var(--radius)",
        overflow: "hidden",
      }}
    >
      {items.map(({ s, key }, i) => {
        const divider = i < items.length - 1
        return s.strategy_string ? (
          <StrategyRow
            key={key}
            id={`strategy-${key}`}
            s={s}
            open={openKeys.has(key)}
            onToggle={() => toggle(key)}
            divider={divider}
          />
        ) : (
          <WithheldRow key={key} s={s} divider={divider} />
        )
      })}
    </div>
  )
}

export function SearchStrategies({ data }: { data: NormalizedData }) {
  const all = data.searchStrategies?.strategies ?? []
  const items: Item[] = all.map((s, i) => ({ s, key: `${i}` }))
  const expandable = items.filter((it) => it.s.strategy_string).map((it) => it.key)
  // Default: every row collapsed — the page opens as an index of databases;
  // each row's action works without expanding (user ruling 2026-09-27).
  const [openKeys, setOpenKeys] = React.useState<Set<string>>(() => new Set())

  if (all.length === 0) return null

  const toggle = (k: string) =>
    setOpenKeys((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })
  const anyOpen = openKeys.size > 0
  const toggleAll = () => setOpenKeys(anyOpen ? new Set() : new Set(expandable))

  const en = items.filter((it) => !isZhPlatform(it.s))
  const zh = items.filter((it) => isZhPlatform(it.s))
  // Group headers only when BOTH language groups are present (37 号规则:
  // a header that distinguishes nothing must not exist).
  const grouped = en.length > 0 && zh.length > 0

  return (
    <section style={{ marginBottom: 56 }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <SectionHeader title={t("strategiesTitle")} sub={t("strategiesSub")} />
        {expandable.length >= 4 && (
          <button
            type="button"
            onClick={toggleAll}
            className="rd-strategy-toggle-all"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 16,
              padding: "4px 2px",
              border: 0,
              background: "transparent",
              cursor: "pointer",
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              color: "hsl(var(--muted-foreground))",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
          >
            {anyOpen ? <ChevronsDownUp size={13} /> : <ChevronsUpDown size={13} />}
            {anyOpen ? t("strategiesCollapseAll") : t("strategiesExpandAll")}
          </button>
        )}
      </div>

      {grouped ? (
        <>
          <GroupHeader label={t("strategyGroupEn")} count={en.length} />
          <StrategyList items={en} openKeys={openKeys} toggle={toggle} />
          <div style={{ height: 22 }} />
          <GroupHeader label={t("strategyGroupZh")} count={zh.length} />
          <StrategyList items={zh} openKeys={openKeys} toggle={toggle} />
        </>
      ) : (
        <StrategyList items={items} openKeys={openKeys} toggle={toggle} />
      )}
    </section>
  )
}
