// Browser sniffer used purely to opt into a Safari-only PRINT compensation —
// not for runtime feature dispatch. Adds an `.is-safari` class to <html>
// when the page is loaded in Safari (macOS or iOS).
//
// Why this exists: Safari WebKit silently ignores `@page { size: <length> }`
// (WebKit Bug #250685, MDN BCD issue #28626). The Skill's SwissTop hero
// is designed for a 1240 CSS-px viewport and relies on Chrome / Firefox
// honoring our @page directive to give the PDF a matching MediaBox. Safari
// falls back to A4 default, the hero (maxWidth:1240) overflows the ~793px
// print viewport, and the result is a hero that prints 1.57x larger than
// Chrome's. We compensate with a single Safari-scoped CSS rule in
// `@media print` (see src/index.css `.is-safari .rd-hero-swiss ...`).
//
// Detection rule:
//   UA contains "Safari" AND lacks "Chrome|Chromium|CriOS|FxiOS|Edge|EdgiOS"
// This matches both desktop Safari and iOS Safari, and excludes other
// browsers that ship a "Safari" token in their UA (Chrome / Edge / Chrome-iOS /
// Firefox-iOS) because they piggy-back the WebKit token.
//
// Side-effect only: no return value. Safe to call multiple times — repeated
// classList.add is a no-op. SSR-safe (early-returns when window absent).
export function detectSafari(): void {
  if (typeof window === "undefined") return
  const ua = window.navigator.userAgent
  const looksLikeSafari =
    /Safari/.test(ua) &&
    !/Chrome|Chromium|CriOS|FxiOS|Edge|EdgiOS/.test(ua)
  if (looksLikeSafari) {
    document.documentElement.classList.add("is-safari")
  }
}
