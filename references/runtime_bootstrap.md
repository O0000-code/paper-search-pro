# Runtime bootstrap — `$PSP_HOME` resolution + UI-language routing

Detailed reference for two deterministic setup concerns that STEP 0 / STEP 1 keep
minimal in `SKILL.md`. Read this only if the compact in-body version is not enough
for your situation (e.g. env injection failed, or you want the cross-agent path
list, or you need to reason about a non-English/Chinese query).

---

## 1. `$PSP_HOME` — the Skill install directory

Every helper is invoked as `PYTHONPATH=$PSP_HOME python3 -m scripts.<name> …`, so
`$PSP_HOME` must point at the directory that contains this `SKILL.md`. It is
resolved **once** in STEP 0 and reused everywhere.

### Why a three-layer chain

The Skill ships as a portable SKILL.md package, and different agents install it at
different paths. The chain tries the cheapest, most authoritative source first:

- **Layer 1 — explicit injection.** If your harness already exposed the absolute
  path of this `SKILL.md`, set `export PSP_HOME="<that directory>"` and skip the
  rest. This is the most reliable source — it is the ground truth.
- **Layer 2 — agent-injected env var.** Claude Code / CodeBuddy populate
  `CLAUDE_SKILL_DIR` / `CODEBUDDY_SKILL_DIR`. The compact STEP 0 snippet reads
  these automatically.
- **Layer 3 — filesystem walk.** If neither of the above is set, scan the known
  cross-agent install locations (below) and take the first that actually contains
  a `SKILL.md`. This is the fallback the in-body snippet runs; it is reproduced
  here in full so you can reason about / extend it.

```bash
PSP_HOME="${PSP_HOME:-${CLAUDE_SKILL_DIR:-${CODEBUDDY_SKILL_DIR:-}}}"
if [ -z "$PSP_HOME" ]; then
  for d in \
    "$HOME/.claude/skills/paper-search-pro" \
    "$HOME/.codex/skills/paper-search-pro" \
    "$HOME/.agents/skills/paper-search-pro" \
    "$HOME/.config/opencode/skills/paper-search-pro" \
    "$HOME/.codeium/windsurf/skills/paper-search-pro" \
    "$HOME/.config/goose/skills/paper-search-pro" \
    "$HOME/.cline/skills/paper-search-pro" \
    "$HOME/.roo/skills/paper-search-pro" \
    "$HOME/.copilot/skills/paper-search-pro" \
    "./.claude/skills/paper-search-pro" \
    "./.codex/skills/paper-search-pro" \
    "./.agents/skills/paper-search-pro" \
    "./.cursor/skills/paper-search-pro" \
    "./.opencode/skills/paper-search-pro" \
    "./.windsurf/skills/paper-search-pro"; do
    [ -f "$d/SKILL.md" ] && PSP_HOME="$d" && break
  done
fi
[ -z "$PSP_HOME" ] && { echo "ERROR: paper-search-pro install not found. Set PSP_HOME to the directory containing SKILL.md."; exit 1; }
export PSP_HOME
echo "Using Skill install: $PSP_HOME"
```

### Why this lives in the body, not a script

`$PSP_HOME` is the path you need *in order to find any script* — so the resolution
cannot itself be a script (chicken-and-egg). It also has to `export` into the
agent's working shell, which a subshell script cannot do. Hence STEP 0 keeps a
compact, self-contained version inline; this file holds the explanation and the
full path list.

### Relationship to "never `cd` into the Skill directory" (Rule A)

Resolving `$PSP_HOME` is what *lets* you avoid `cd`. You run every helper from the
user's PWD with `PYTHONPATH=$PSP_HOME`, so `./paper-search-results/...` keeps
resolving to the user's working directory instead of the Skill asset folder.

---

## 2. UI-language routing (`UI_LANG` for the HTML report)

STEP 1 sets `UI_LANG` to `en` or `zh`; this single boolean only controls which UI
language the final HTML report renders in. Paper titles / abstracts / authors /
venues are **never** translated — only the report's UI chrome.

The deterministic detector is `scripts/detect_language.py`:

```bash
UI_LANG=$(PYTHONPATH=$PSP_HOME python3 -m scripts.detect_language "$USER_QUERY")
```

### The routing rule (first match wins)

1. **Japanese kana present** (hiragana U+3041–U+309F or katakana U+30A0–U+30FF)
   → `en`. Japanese kanji share the CJK Unified Ideographs block with Chinese Han,
   so a kanji-only query like `東京大学の最新研究` looks identical to Chinese at the
   codepoint level. Detecting kana first routes real Japanese text to EN reliably.
2. **CJK Unified Ideograph present** (U+4E00–U+9FFF), no kana → `zh` (Chinese).
3. **Everything else** (Latin, Hangul/Korean, Cyrillic, digits) → `en`.

### Why non-Chinese CJK routes to English

The bundle ships only English and Chinese dictionaries. Japanese / Korean /
European queries all route to **English**, the international academic default — a
Korean researcher reading an English UI is friendlier than the same researcher
confronting a Chinese UI they cannot parse. (Routing Japanese / Korean to Chinese
was the previous heuristic; it was changed because "CJK readers can read Chinese
UI" does not hold.)

`UI_LANG` is passed to STEP 12b as `--language $UI_LANG`. Resolution order inside
the renderer is: explicit `--language` > `metadata.language` > `en`.
