// RCS slider with tier zone backdrop.
//
// Composes shadcn Slider (Radix) with absolute-positioned zone overlays drawn
// on top of the track but below the thumb. Mirrors TARGET lib.jsx Slider
// (372-418): 5 tier colour bands at opacity 0.18 stretched across the track.
//
// The shadcn Slider's own filled Range fights the zones visually, so we hide
// it via CSS and let the zones stand alone — matching the TARGET behaviour
// where the thumb position is the only "current value" affordance.

import { Slider } from "@/components/ui/slider"

export interface SliderZone {
  start: number
  end: number
  /** Any CSS colour string — typically `hsl(var(--chart-N))` */
  color: string
}

export interface SliderWithZonesProps {
  value: number
  onValueChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  zones?: SliderZone[]
  className?: string
}

export function SliderWithZones({
  value,
  onValueChange,
  min = 0,
  max = 10,
  step = 0.1,
  zones,
  className,
}: SliderWithZonesProps) {
  const span = max - min
  return (
    <div
      className={className}
      style={{ position: "relative", height: 28, display: "flex", alignItems: "center" }}
    >
      {/* Zone overlay — sits at the same vertical position as the Radix track */}
      {zones && (
        <div
          aria-hidden
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            transform: "translateY(-50%)",
            height: 6,
            borderRadius: 3,
            background: "hsl(var(--muted))",
            overflow: "hidden",
            pointerEvents: "none",
            zIndex: 1,
          }}
        >
          {zones.map((z, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: ((z.start - min) / span) * 100 + "%",
                width: ((z.end - z.start) / span) * 100 + "%",
                background: z.color,
                opacity: 0.18,
              }}
            />
          ))}
        </div>
      )}
      <Slider
        value={[value]}
        onValueChange={(v) => onValueChange(v[0])}
        min={min}
        max={max}
        step={step}
        // Track is transparent so the zone overlay shows through; Range hidden
        // via inline child styling on the data-orientation slot.
        className="relative z-[2] [&_[data-orientation=horizontal]>span]:bg-transparent [&_span[data-radix-slider-range]]:bg-transparent"
      />
    </div>
  )
}
