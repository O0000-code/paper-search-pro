# Third-Party Acknowledgments

paper-search-pro stands on a generous open source ecosystem. This document
lists the major third-party projects bundled into the compiled
`bundle.html` or imported via the Python runtime, along with their licenses
and homepages.

Full license texts for each npm package live inside its own
`node_modules/<package>/LICENSE` after `npm install`; they are not
redistributed in this repository per ecosystem convention. Each project's
homepage links below carry the canonical license file.

---

## UI primitives

| Package | License | Homepage |
|---|:---:|---|
| **shadcn/ui** — 41 component files under `src/components/ui/*.tsx` are derived from shadcn/ui's copy-paste catalog | MIT | <https://ui.shadcn.com/> |
| **Radix UI** — 27 `@radix-ui/react-*` unstyled accessible primitives | MIT | <https://www.radix-ui.com/> |
| **Lucide** — icon set used throughout the report | ISC | <https://lucide.dev/> |
| **Sonner** — toast notification primitive | MIT | <https://sonner.emilkowal.ski/> |
| **Vaul** — drawer primitive | MIT | <https://vaul.emilkowal.ski/> |
| **cmdk** — command-menu primitive | MIT | <https://cmdk.paco.me/> |
| **Embla Carousel** — carousel primitive | MIT | <https://www.embla-carousel.com/> |
| **React Day Picker** — calendar primitive | MIT | <https://react-day-picker.js.org/> |
| **React Resizable Panels** — resizable-layout primitive | MIT | <https://github.com/bvaughn/react-resizable-panels> |

## Charts & visualization

| Package | License | Homepage |
|---|:---:|---|
| **Recharts** — composable chart library powering the Methods tab | MIT | <https://recharts.org/> |

## Forms & validation

| Package | License | Homepage |
|---|:---:|---|
| **React Hook Form** | MIT | <https://react-hook-form.com/> |
| **@hookform/resolvers** | MIT | <https://github.com/react-hook-form/resolvers> |
| **Zod** — schema validation | MIT | <https://zod.dev/> |

## Styling

| Package | License | Homepage |
|---|:---:|---|
| **Tailwind CSS** | MIT | <https://tailwindcss.com/> |
| **tailwindcss-animate** | MIT | <https://github.com/jamiebuilds/tailwindcss-animate> |
| **class-variance-authority** | Apache 2.0 | <https://cva.style/> |
| **clsx** | MIT | <https://github.com/lukeed/clsx> |
| **tailwind-merge** | MIT | <https://github.com/dcastil/tailwind-merge> |

## Typography (inlined as base64 in `src/index.css`)

| Font | License | Homepage |
|---|:---:|---|
| **Geist Variable** — Vercel's geometric sans (Latin) | SIL OFL 1.1 | <https://github.com/vercel/geist-font> |
| **Geist Mono Variable** — Vercel's mono | SIL OFL 1.1 | <https://github.com/vercel/geist-font> |
| **Noto Sans SC Variable** — Google's pan-Chinese sans (CJK) | SIL OFL 1.1 | <https://fonts.google.com/noto/specimen/Noto+Sans+SC> |

## React framework & build toolchain

| Package | License | Homepage |
|---|:---:|---|
| **React** + **React DOM** | MIT | <https://react.dev/> |
| **Vite** — bundler | MIT | <https://vitejs.dev/> |
| **TypeScript** | Apache 2.0 | <https://www.typescriptlang.org/> |
| **next-themes** | MIT | <https://github.com/pacocoursey/next-themes> |
| **date-fns** | MIT | <https://date-fns.org/> |
| **html-inline** — single-file HTML compile step | MIT | <https://github.com/popcorn/html-inline> |
| **PostCSS** + **autoprefixer** | MIT | <https://postcss.org/> |

## Python runtime (`scripts/requirements.txt`)

| Package | License | Homepage |
|---|:---:|---|
| **pyalex** — OpenAlex client | MIT | <https://github.com/J535D165/pyalex> |
| **semanticscholar** — Semantic Scholar client | MIT | <https://github.com/danielnsilva/semanticscholar> |
| **biopython** — PubMed via NCBI Entrez | Biopython License (BSD-like) | <https://biopython.org/> |
| **arxiv** — arXiv API client | MIT | <https://github.com/lukasschwab/arxiv.py> |
| **requests** — HTTP client | Apache 2.0 | <https://requests.readthedocs.io/> |
| **PyYAML** — YAML loader | MIT | <https://pyyaml.org/> |
| **Jinja2** — template engine | BSD-3-Clause | <https://palletsprojects.com/p/jinja/> |

## Project scaffold tooling

| Source | License / Status | Notes |
|---|:---:|---|
| **Anthropic Web Artifacts Builder** (Claude Code Skill) | Skill output owned by user | Provided the initial Vite + React + TypeScript + Tailwind + shadcn scaffold for `assets/webartifacts_app/paper-report/`; the resulting compile pattern (`vite build` + `html-inline` → single-file `bundle.html`) follows this Skill's recommended pattern |

---

## Contributors

| Name | Role |
|---|---|
| **Bo** | Original author — Skill design, 14-step recipe, Python helpers, React report renderer, dual-language UI, screenshot pipeline |
| **paper-qa** (FutureHouse / Edison Scientific) | Upstream deterministic helper patterns ([`scripts/vendored/`](scripts/vendored/README-vendored.md)) |
| **shadcn** + the **shadcn/ui** community | UI component primitives under `src/components/ui/` |
| **Anthropic** | Claude Code Skill platform, Web Artifacts Builder Skill scaffold |
| **OpenAlex · Semantic Scholar · CrossRef · NCBI / PubMed · arXiv** | Open scholarly metadata APIs — the entire premise of this Skill |

If you contribute and would like to be listed here, open a pull request
adding your name + role.

---

*This file is non-exhaustive. Transitive dependencies of the packages
listed above bring further open source libraries into the compiled bundle;
each is governed by its own license inside its npm package.*
