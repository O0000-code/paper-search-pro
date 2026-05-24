import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { installLanguage } from './lib/i18n'
import App from './App.tsx'

// Install translation dictionary on window.S before React mounts so every
// component sees the right strings on its first render. Python's
// html_renderer_webartifacts.py injects window.__REPORT_LANG__ above the
// React bundle; when absent (standalone mock preview), this defaults to
// English. See src/lib/i18n.ts for the dictionary itself.
installLanguage()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
