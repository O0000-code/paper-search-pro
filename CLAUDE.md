# paper-search-pro — notes for sessions modifying this repo

Published Agent Skill (Apache 2.0). Edit the **git repo** here; the running copy
is separate at `~/.claude/skills/paper-search-pro/` — sync to it (rsync
`scripts/` `references/` `assets/` + `SKILL.md`) for changes to take effect.

## Invariants — do not break
- **R-04 naming**: OpenAlex / SJR / 中科院(CAS) journal metrics are *partitions / open impact*, **never "Impact Factor"**. Only JCR `IF(YYYY)` is a real Impact Factor.
- **R-19 human-path preservation**: the human 14-STEP flow — especially **STEP 6** (parallel classification SubAgents) and **STEP 12** (HTML render) — must stay **byte-identical** when the agent/headless, source-switch, and journal-rank features are unused. Every new capability is opt-in additive; default = current behavior.
- **Journal-rank data is never committed** (Clarivate/SCImago/CAS copyright). It is runtime-fetched from public GitHub mirrors into `~/.paper-search-pro/ranks/`. `scripts/journal_rank.py` is the single canonical rank layer; `scripts/sjr_helper.py` is superseded (kept for back-compat, not the wired source).
- **Zero new hard dependencies** for v2.2 (GitHub-raw fetch uses `requests`) — keep it that way: no playwright, no heavyweight libs.
- **One coverage estimator**: `scripts/discovery_curve.py` (sample coverage over the run's `raw/` retrieval files, bootstrap interval, labelled `prior` fallback). `data_materialization` only renders it — never add a second fit there: an improvised τ=80 fallback once became the only path and showed ~99% on every run.

## Test
Offline, reproducible: a uv venv from `scripts/requirements.lock` plus `pytest pytest-socket`, then
`HOME=<empty dir> PYTHONPATH=. python -m pytest tests -q -p no:cacheprovider --disable-socket --allow-unix-socket` — 672 pass (2026-09-28). Live checks are marked `live` and deselected by default.

## Building the HTML report (`bundle.html`)
The report is TypeScript + Vite in `assets/webartifacts_app/paper-report/`. `node_modules` lives only
in the **installed** copy (`~/.claude/skills/paper-search-pro/...`) — the repo gitignores it — so build
there: `rsync -a <repo>/…/src/ <inst>/…/src/` → `cd <inst>/…/paper-report && pnpm exec vite build` →
`npx html-inline -i dist/index.html -o bundle.html` → copy `bundle.html` back here (it's committed).
**Use `vite build`, NOT `pnpm build`** — the `tsc -b` gate is pre-existingly broken (React19/TS6 drift:
`baseUrl` deprecation + unused `calendar.tsx`/`resizable.tsx` type errors + an `App.tsx` union-props
strictness); none affect the runtime, and `bundle.html` has always been a vite+inline product.

## Design record
Full v2.2 research + the **HTML design-sync maintenance playbook** (delta method, build recipe, and the
misunderstandings to avoid) live outside the repo:
`~/Documents/Claude Code/Skills/Enhancement/Paper Search Pro/` → `00_maintenance_playbook.md` +
`CLAUDE.md`; delta plans in `../01_working/NN_deltaN_sync_plan.md`; backend work in `v2.2-evolution/`.
