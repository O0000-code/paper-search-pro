// SVG thumbnail glyphs for LayoutSwitcher.
//
// 1:1 port of TARGET layout-switcher.jsx LayoutThumbShapes (132-165)
// and ListThumbShapes (167-200). Exact rect/line coords preserved.

import { Fragment } from "react"

export interface SwitcherThumbProps {
  kind: "layout" | "list"
  variant: string
  active?: boolean
  small?: boolean
}

export function SwitcherThumb({ kind, variant, active, small }: SwitcherThumbProps) {
  const sz = small ? 18 : 32
  const stroke = active ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))"
  const fill = active ? "hsl(var(--foreground))" : "hsl(var(--muted-foreground))"
  return (
    <svg
      width={sz}
      height={sz}
      viewBox="0 0 32 32"
      style={{ flexShrink: 0, opacity: active ? 1 : 0.65 }}
    >
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="3"
        fill="none"
        stroke={stroke}
        strokeWidth="1"
        opacity="0.4"
      />
      {kind === "layout" && (
        <LayoutThumbShapes variant={variant} fill={fill} stroke={stroke} />
      )}
      {kind === "list" && (
        <ListThumbShapes variant={variant} fill={fill} stroke={stroke} />
      )}
    </svg>
  )
}

interface ShapeProps {
  variant: string
  fill: string
  stroke: string
}

export function LayoutThumb(props: SwitcherThumbProps) {
  return <SwitcherThumb {...props} kind="layout" />
}

export function ListThumb(props: SwitcherThumbProps) {
  return <SwitcherThumb {...props} kind="list" />
}

function LayoutThumbShapes({ variant, fill, stroke }: ShapeProps) {
  if (variant === "editorial") {
    return (
      <>
        <rect x="6" y="6" width="8" height="1.5" fill={fill} opacity="0.5" />
        <rect x="6" y="10" width="20" height="3" fill={fill} />
        <rect x="6" y="15" width="18" height="1.8" fill={fill} opacity="0.6" />
        <rect x="6" y="18" width="20" height="1.8" fill={fill} opacity="0.6" />
        <rect x="6" y="21" width="14" height="1.8" fill={fill} opacity="0.6" />
      </>
    )
  }
  if (variant === "swiss") {
    return (
      <>
        <rect x="4" y="6" width="12" height="2" fill={fill} opacity="0.7" />
        <rect x="4" y="10" width="10" height="1.5" fill={fill} opacity="0.5" />
        <rect x="4" y="13" width="11" height="1.5" fill={fill} opacity="0.5" />
        <line
          x1="17.5"
          y1="6"
          x2="17.5"
          y2="22"
          stroke={stroke}
          strokeWidth="0.5"
          opacity="0.4"
        />
        <rect x="19" y="8" width="5" height="10" fill={fill} />
        <line
          x1="25"
          y1="6"
          x2="25"
          y2="22"
          stroke={stroke}
          strokeWidth="0.5"
          opacity="0.4"
        />
        <rect x="26.5" y="8" width="4.5" height="10" fill={fill} />
      </>
    )
  }
  if (variant === "document") {
    return (
      <>
        <rect x="11" y="5" width="10" height="1.6" fill={fill} opacity="0.5" />
        <rect x="7" y="9" width="18" height="2.5" fill={fill} />
        <line
          x1="6"
          y1="15"
          x2="26"
          y2="15"
          stroke={stroke}
          strokeWidth="0.4"
          opacity="0.4"
        />
        <rect x="6" y="17" width="20" height="1.2" fill={fill} opacity="0.55" />
        <rect x="6" y="19.5" width="20" height="1.2" fill={fill} opacity="0.55" />
        <rect x="6" y="22" width="14" height="1.2" fill={fill} opacity="0.55" />
      </>
    )
  }
  return null
}

function ListThumbShapes({ variant, fill, stroke }: ShapeProps) {
  if (variant === "catalog") {
    return (
      <>
        <rect x="5" y="6" width="14" height="1.4" fill={fill} />
        <rect x="5" y="8.5" width="10" height="1" fill={fill} opacity="0.5" />
        <rect x="24" y="6" width="3" height="3.4" fill={fill} opacity="0.7" />
        <line
          x1="5"
          y1="12"
          x2="27"
          y2="12"
          stroke={stroke}
          strokeWidth="0.3"
          opacity="0.4"
        />

        <rect x="5" y="14" width="12" height="1.4" fill={fill} />
        <rect x="5" y="16.5" width="13" height="1" fill={fill} opacity="0.5" />
        <rect x="24" y="14" width="3" height="3.4" fill={fill} opacity="0.7" />
        <line
          x1="5"
          y1="20"
          x2="27"
          y2="20"
          stroke={stroke}
          strokeWidth="0.3"
          opacity="0.4"
        />

        <rect x="5" y="22" width="15" height="1.4" fill={fill} />
        <rect x="5" y="24.5" width="9" height="1" fill={fill} opacity="0.5" />
        <rect x="24" y="22" width="3" height="3.4" fill={fill} opacity="0.7" />
      </>
    )
  }
  if (variant === "index") {
    return (
      <>
        {[6, 11, 16, 21, 26].map((y) => (
          <Fragment key={y}>
            <rect x="4" y={y} width="2" height="1" fill={fill} opacity="0.5" />
            <rect x="7.5" y={y} width="10" height="1" fill={fill} />
            <rect x="19" y={y} width="4" height="1" fill={fill} opacity="0.5" />
            <rect x="24.5" y={y} width="3" height="1" fill={fill} opacity="0.7" />
          </Fragment>
        ))}
      </>
    )
  }
  return null
}
