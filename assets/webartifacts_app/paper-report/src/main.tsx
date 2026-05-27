import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { installLanguage } from './lib/i18n'
import { detectSafari } from './lib/safari-detect'
import App from './App.tsx'

// Install translation dictionary on window.S before React mounts so every
// component sees the right strings on its first render. Python's
// html_renderer_webartifacts.py injects window.__REPORT_LANG__ above the
// React bundle; when absent (standalone mock preview), this defaults to
// English. See src/lib/i18n.ts for the dictionary itself.
installLanguage()

// Tag <html> with `.is-safari` when running in Safari (macOS or iOS) so the
// print stylesheet can apply a single Safari-only `zoom` compensation to the
// SwissTop hero — Safari ignores `@page { size: 1240px 1754px }` and falls
// back to A4, making the hero print 1.57x larger than Chrome. Read
// src/lib/safari-detect.ts header for the full rationale + the matching CSS
// rule in src/index.css under `@media print { .is-safari ... }`.
detectSafari()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
