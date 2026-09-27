// Line breaking for the report H1 (used inside each top's own <h1>).
//
// Browsers may break between any two Han characters, so a title like
// "…双重角色：研究工具与发展情境" wrapped as "…：研 / 究工具…" at 1440 px. Two
// local measures, H1 only:
//   1. A "main: subtitle" title prefers its break right after the colon: each
//      part is an inline-block, so the subtitle moves down as a whole when the
//      two do not fit on one line.
//   2. Inside a part, words from Intl.Segmenter do not break internally, and the
//      part's lines are balanced. Without Intl.Segmenter the text is left as is.

import { useMemo, type CSSProperties } from "react"

// First main/subtitle delimiter, kept with the main part.
const SUBTITLE_DELIMITER = /(：|: |——| — )/

// Longer segments are left breakable so one long token cannot overflow.
const MAX_UNBREAKABLE = 12

interface Segmenter {
  segment(text: string): Iterable<{ segment: string; isWordLike?: boolean }>
}

function words(text: string): string[] {
  const Ctor = (Intl as unknown as { Segmenter?: new (l: string, o: object) => Segmenter })
    .Segmenter
  if (!Ctor) return [text]
  const out: string[] = []
  for (const s of new Ctor("zh", { granularity: "word" }).segment(text)) {
    // Punctuation rides with the preceding word so it never starts a line.
    if (!s.isWordLike && !/^\s+$/.test(s.segment) && out.length) {
      out[out.length - 1] += s.segment
    } else {
      out.push(s.segment)
    }
  }
  return out
}

function Part({ text }: { text: string }) {
  const segs = useMemo(() => words(text), [text])
  return (
    <span style={{ display: "inline-block", textWrap: "balance" } as CSSProperties}>
      {segs.map((w, i) =>
        w.length <= MAX_UNBREAKABLE && !/^\s+$/.test(w) ? (
          <span key={i} style={{ whiteSpace: "nowrap" }}>
            {w}
          </span>
        ) : (
          w
        ),
      )}
    </span>
  )
}

export function ReportTitle({ text }: { text: string }) {
  const parts = useMemo(() => {
    const m = SUBTITLE_DELIMITER.exec(text)
    if (!m || m.index === 0) return [text]
    const cut = m.index + m[0].length
    const rest = text.slice(cut).trim()
    return rest ? [text.slice(0, cut).trimEnd(), rest] : [text]
  }, [text])
  // A space between the parts keeps the Latin "Title: Subtitle" spacing when
  // both fit on one line; CJK colons are full-width and need none.
  const joiner = /(：|——)$/.test(parts[0]) ? "" : " "
  return parts.length === 1 ? (
    <Part text={parts[0]} />
  ) : (
    <>
      <Part text={parts[0]} />
      {joiner}
      <Part text={parts[1]} />
    </>
  )
}
