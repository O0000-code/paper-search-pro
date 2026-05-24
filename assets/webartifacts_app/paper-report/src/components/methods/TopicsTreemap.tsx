// Mosaic treemap of `chart_data.theme_treemap`. 1:1 port of TARGET
// redesign/treemap-variants.jsx::ThemeTreemapMosaic + sliceAndDice +
// TreemapHoverCard + BaselineCaption (lines 6-475).
//
// Why slice-and-dice (not squarified): the real-world CBT dataset has the
// top three clusters within ~15% of each other; squarified would render
// them as three similar-sized squares with no visible hierarchy. Slice-
// and-dice carves the largest item off as a full-edge strip first, so #1
// is guaranteed visual dominance regardless of how close the runners-up
// are. The trade-off is that low-rank tiles may be thin — acceptable
// because the bottom of the rank list is where readability matters least.
//
// Why absolute-positioned DIVs (not SVG <rect>): SVG `text` with
// preserveAspectRatio="none" stretches the typography horizontally when
// the container aspect doesn't match the viewBox. DIV tiles keep text
// natural at every container width. The ResizeObserver measures the
// container so the layout re-runs on resize.
//
// HoverCard glides between adjacent tiles via translate3d + cubic-bezier
// — never remounts, so the transition is physical, not snappy.

import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowRight } from "lucide-react"

import { getS } from "@/lib/i18n"
import type { ThemeTreemap, ThemeTreemapNode } from "@/lib/types"

export interface TopicsTreemapProps {
  data?: ThemeTreemap | null
  height?: number
  /** Called with the first paper_id in the clicked tile's cluster. */
  onSelect?: (paperId: string) => void
}

interface RankedTheme extends ThemeTreemapNode {
  rank: number
}

interface Tile extends RankedTheme {
  x: number
  y: number
  w: number
  h: number
}

const EASING_POP = "cubic-bezier(0.16, 1, 0.3, 1)"
const EASING_STD = "cubic-bezier(0.4, 0, 0.2, 1)"

// Slice-and-dice with orientation chosen by aspect ratio — alternates
// horizontal / vertical based on which axis is longer at each step. The
// FIRST item is split off as a full-edge strip; recursion lays out the
// remainder in the remaining rectangle.
function sliceAndDice(
  items: RankedTheme[],
  x: number,
  y: number,
  w: number,
  h: number,
): Tile[] {
  if (items.length === 0) return []
  if (items.length === 1) return [{ ...items[0], x, y, w, h }]
  const total = items.reduce((s, t) => s + t.value, 0)
  if (total <= 0) return [{ ...items[0], x, y, w, h }]
  const first = items[0]
  const firstShare = first.value / total
  const horizontal = w >= h
  if (horizontal) {
    const firstW = w * firstShare
    return [
      { ...first, x, y, w: firstW, h },
      ...sliceAndDice(items.slice(1), x + firstW, y, w - firstW, h),
    ]
  } else {
    const firstH = h * firstShare
    return [
      { ...first, x, y, w, h: firstH },
      ...sliceAndDice(items.slice(1), x, y + firstH, w, h - firstH),
    ]
  }
}

export function TopicsTreemap({ data, height = 320, onSelect }: TopicsTreemapProps) {
  const [hover, setHover] = useState<Tile | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(1100)

  useEffect(() => {
    if (!containerRef.current) return
    const update = () => {
      setWidth(containerRef.current?.offsetWidth || 1100)
    }
    update()
    const obs = new ResizeObserver(update)
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  const themes = useMemo<RankedTheme[]>(() => {
    const raw = (data?.themes || []) as ThemeTreemapNode[]
    return raw
      .filter((t) => typeof t.value === "number" && t.value > 0)
      .sort((a, b) => (b.value as number) - (a.value as number))
      .map((t, i) => ({ ...t, rank: i + 1 }))
  }, [data])

  if (themes.length === 0) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height,
          fontSize: 12,
          color: "hsl(var(--muted-foreground))",
          border: "1px dashed hsl(var(--border))",
          borderRadius: "var(--radius)",
          fontFamily: "var(--font-sans)",
        }}
      >
        {getS().topicNotAvailable ||
          "Topic clustering not available for this run."}
      </div>
    )
  }

  const tiles = sliceAndDice(themes, 0, 0, width, height)
  const total = themes.reduce((s, t) => s + t.value, 0)
  const N = themes.length
  const alphaFor = (rank: number) =>
    N === 1 ? 0.7 : 0.92 - ((rank - 1) / (N - 1)) * 0.64

  return (
    <div>
      <div
        ref={containerRef}
        style={{
          position: "relative",
          width: "100%",
          height,
          borderRadius: 6,
          background: "hsl(var(--muted) / 0.4)",
          overflow: "hidden",
        }}
      >
        {tiles.map((t) => {
          const isHover = hover && hover.name === t.name
          const alpha = alphaFor(t.rank)
          const lightText = alpha > 0.55
          const pct = Math.round((t.value / total) * 100)
          const fill = `hsl(var(--chart-1) / ${
            isHover ? Math.min(1, alpha + 0.06) : alpha
          })`
          const paperIds = (t.paper_ids || []) as string[]
          const clickable = !!(onSelect && paperIds.length > 0)
          const compact = t.w <= 110 || t.h <= 64
          const tiny = t.w <= 56 || t.h <= 32
          const textColor = lightText
            ? "hsl(var(--background))"
            : "hsl(var(--foreground))"
          const subTextColor = lightText
            ? "hsl(var(--background) / 0.72)"
            : "hsl(var(--muted-foreground))"
          const subLabelColor = lightText
            ? "hsl(var(--background) / 0.75)"
            : "hsl(var(--muted-foreground))"

          return (
            <div
              key={t.name}
              onMouseEnter={() => setHover(t)}
              onMouseLeave={() => setHover(null)}
              onClick={
                clickable ? () => onSelect?.(paperIds[0]) : undefined
              }
              style={{
                position: "absolute",
                left: t.x,
                top: t.y,
                width: t.w,
                height: t.h,
                background: fill,
                cursor: clickable ? "pointer" : "default",
                transition: `background .3s ${EASING_STD}, box-shadow .2s ${EASING_STD}`,
                boxShadow: isHover
                  ? "inset 0 0 0 2px hsl(var(--background)), inset 0 0 0 3.2px hsl(var(--foreground) / 0.55)"
                  : "inset 0 0 0 2px hsl(var(--background))",
                display: "flex",
                flexDirection: "column",
                padding: tiny ? 4 : "12px 14px",
                overflow: "hidden",
                willChange: "background, box-shadow",
              }}
            >
              {isHover && (
                <div
                  style={{
                    position: "absolute",
                    inset: 2,
                    boxShadow: "inset 0 0 0 1.2px hsl(var(--foreground))",
                    pointerEvents: "none",
                    animation: `rd-treemap-tile-in .18s ${EASING_POP}`,
                  }}
                />
              )}
              {!tiny && (
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 500,
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.08em",
                    color: subLabelColor,
                    marginBottom: compact ? 2 : 6,
                  }}
                >
                  #{t.rank}
                </div>
              )}
              {!compact && (
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    letterSpacing: "-0.005em",
                    color: textColor,
                    lineHeight: 1.25,
                    marginBottom: 6,
                    overflow: "hidden",
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    fontFamily: "var(--font-sans)",
                  }}
                >
                  {t.name}
                </div>
              )}
              {compact && !tiny && (
                <div
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    letterSpacing: "-0.005em",
                    color: textColor,
                    lineHeight: 1.2,
                    marginBottom: 2,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontFamily: "var(--font-sans)",
                  }}
                >
                  {t.name}
                </div>
              )}
              {!tiny && (
                <div
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: compact ? 10.5 : 12,
                    fontVariantNumeric: "tabular-nums",
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                  }}
                >
                  <span style={{ fontWeight: 600, color: textColor }}>
                    {t.value}
                  </span>
                  <span style={{ color: subTextColor }}>{pct}%</span>
                </div>
              )}
              {tiny && t.w > 28 && t.h > 16 && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    fontWeight: 600,
                    color: textColor,
                  }}
                >
                  {t.value}
                </div>
              )}
            </div>
          )
        })}
        {hover && (
          <TreemapHoverCard
            hover={hover}
            total={total}
            onSelect={onSelect}
            container={{ w: width, h: height }}
          />
        )}
      </div>
      <BaselineCaption themes={themes} total={total} />
    </div>
  )
}

interface HoverCardProps {
  hover: Tile
  total: number
  onSelect?: (paperId: string) => void
  container: { w: number; h: number }
}

function TreemapHoverCard({
  hover,
  total,
  onSelect,
  container,
}: HoverCardProps) {
  const S = getS()
  // Edge-clamped placement: prefer right of anchor; fall back to left;
  // then above; then below. Always keep an 8px gap from container edges.
  const CARD_W = 260
  const CARD_H = 130
  const GAP = 8
  let pos = { x: 0, y: 0 }
  if (hover.x + hover.w + GAP + CARD_W <= container.w) {
    pos = {
      x: hover.x + hover.w + GAP,
      y: Math.min(Math.max(8, hover.y), container.h - CARD_H - 8),
    }
  } else if (hover.x - GAP - CARD_W >= 0) {
    pos = {
      x: hover.x - GAP - CARD_W,
      y: Math.min(Math.max(8, hover.y), container.h - CARD_H - 8),
    }
  } else {
    const above = hover.y - GAP - CARD_H >= 0
    pos = above
      ? {
          x: Math.min(Math.max(8, hover.x), container.w - CARD_W - 8),
          y: hover.y - GAP - CARD_H,
        }
      : {
          x: Math.min(Math.max(8, hover.x), container.w - CARD_W - 8),
          y: Math.min(hover.y + hover.h + GAP, container.h - CARD_H - 8),
        }
  }

  const paperIds = (hover.paper_ids || []) as string[]
  const pct = Math.round((hover.value / total) * 100)

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        transform: `translate3d(${pos.x}px, ${pos.y}px, 0)`,
        width: CARD_W,
        padding: "12px 14px",
        background: "hsl(var(--popover))",
        color: "hsl(var(--popover-foreground))",
        boxShadow:
          "0 10px 32px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.04), 0 0 0 1px hsl(var(--border))",
        borderRadius: 8,
        fontSize: 12,
        lineHeight: 1.5,
        pointerEvents: "none",
        transition: `transform .28s ${EASING_POP}`,
        willChange: "transform",
        animation: `rd-treemap-card-in .18s ${EASING_POP} both`,
        fontFamily: "var(--font-sans)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 10,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fontWeight: 500,
            letterSpacing: "0.06em",
            padding: "2px 6px",
            borderRadius: 4,
            background: "hsl(var(--muted))",
            color: "hsl(var(--muted-foreground))",
          }}
        >
          #{hover.rank}
        </span>
        <span
          style={{
            fontWeight: 600,
            color: "hsl(var(--foreground))",
            letterSpacing: "-0.005em",
            minWidth: 0,
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {hover.name}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          fontFamily: "var(--font-mono)",
          fontVariantNumeric: "tabular-nums",
          color: "hsl(var(--muted-foreground))",
        }}
      >
        <span
          style={{
            color: "hsl(var(--foreground))",
            fontWeight: 600,
            fontSize: 22,
            letterSpacing: "-0.015em",
            lineHeight: 1,
          }}
        >
          {hover.value}
        </span>
        <span style={{ fontSize: 11 }}>{S.papers || "papers"}</span>
        <span style={{ opacity: 0.4 }}>·</span>
        <span style={{ fontSize: 11 }}>{pct}%</span>
      </div>
      <div
        style={{
          marginTop: 10,
          height: 3,
          background: "hsl(var(--muted))",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "hsl(var(--foreground))",
            transition: `width .32s ${EASING_POP}`,
          }}
        />
      </div>
      {paperIds.length > 0 && onSelect && (
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: "1px solid hsl(var(--border))",
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            color: "hsl(var(--muted-foreground))",
          }}
        >
          <span>{S.openTopPaper || "Open top paper"}</span>
          <ArrowRight size={11} strokeWidth={1.75} />
        </div>
      )}
    </div>
  )
}

interface BaselineCaptionProps {
  themes: RankedTheme[]
  total: number
}

function BaselineCaption({ themes, total }: BaselineCaptionProps) {
  const largest = themes[0]
  const largestPct = Math.round((largest.value / total) * 100)
  const S = getS()
  return (
    <div
      style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: "1px solid hsl(var(--border))",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
        fontSize: 11.5,
        color: "hsl(var(--muted-foreground))",
        fontFamily: "var(--font-sans)",
      }}
    >
      <span>
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            color: "hsl(var(--foreground))",
            fontWeight: 600,
          }}
        >
          {total}
        </span>
        <span style={{ margin: "0 6px" }}>{S.papersAcross || "papers across"}</span>
        <span
          className="tabular"
          style={{
            fontFamily: "var(--font-mono)",
            color: "hsl(var(--foreground))",
            fontWeight: 600,
          }}
        >
          {themes.length}
        </span>
        <span style={{ marginLeft: 4 }}>{S.topics || "topics"}</span>
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
        }}
      >
        {S.largest || "Largest"}:{" "}
        <span style={{ color: "hsl(var(--foreground))", fontWeight: 600 }}>
          {largest.name}
        </span>
        <span style={{ marginLeft: 6 }}>{largestPct}%</span>
      </span>
    </div>
  )
}
