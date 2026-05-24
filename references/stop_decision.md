# Stop Decision

*This file is read by the main agent in STEP 8 of `SKILL.md` after `discovery_curve.py` produces a saturation estimate. The decision combines `curve.json` (advisory) with tier budget and user intent — the main agent has final authority.*

## Inputs to the decision

| Input | Source | Meaning |
|-------|--------|---------|
| `saturation_estimate` | `curve.json` | 0.0-1.0; estimate of how much of the relevant literature you've covered |
| `ci_low`, `ci_high` | `curve.json` | 95% confidence interval — tight interval = high confidence in saturation |
| `papers_evaluated` | KG length | How many papers have been classified |
| `tier_budget` | `tier_decision.md` | Quick 60 / Standard 180 / Deep 400 / Audit 1000 |
| `user_intent` | from your query understanding | Known topic (high prior) vs. exploration (low prior) |

## Decision matrix (saturation × budget remaining)

| Saturation \ Budget | **Plenty remaining** (< 50% used) | **Tight** (50-80% used) | **Exhausted** (≥ 80% used) |
|---------------------|-----------------------------------|--------------------------|----------------------------|
| **High** (> 0.85) | Stop — diminishing returns | Stop | Stop |
| **Medium** (0.6 - 0.85) | Expand 1 citation hop | Stop or 1 hop (check user intent) | Stop |
| **Low** (< 0.6) | Expand citations, broaden strategy | 1 more strategy then stop | Stop |

## Decision tree (apply top to bottom, first match wins)

```
1. User explicitly said "enough" / "stop" / "I have what I need"?
   YES → Stop. Write report. (Honor explicit user requests above all.)

2. papers_evaluated >= 80% of tier_budget?
   YES → Stop. Budget protection: never blow past 1.5× budget.

3. saturation_estimate > 0.85 AND ci_high - ci_low < 0.15?
   YES → Stop. Curve is confident; further expansion adds noise.

4. saturation_estimate > 0.85 BUT ci is wide (> 0.15)?
   → Run 1 more strategy (recency or topic-id) to tighten estimate, then re-check.

5. saturation_estimate in [0.6, 0.85]?
   → Expand citations 1 hop from top-rcs papers (STEP 9), then re-check.

6. saturation_estimate < 0.6?
   → Multiple options. Pick based on tier:
      - Quick: stop (curve is unreliable with <50 papers anyway)
      - Standard: expand citations + add 1 strategy (recency)
      - Deep: expand 2 hops + add strategies (seminal + reviews)
      - Audit: expand 2 hops + journal whitelist + ask user about other databases

7. None of above match?
   → Default to "expand 1 hop" if tier allows; otherwise stop.
```

## When to ask the user (saturation 0.7 - 0.85, budget around 50%)

This zone is genuinely ambiguous. Rather than guess, tell the user the numbers:

> "Saturation estimate is 0.78 (CI 0.71-0.84). You're at 95/180 papers in Standard tier (53% of budget). I can either:
>   (a) stop here and write the report — you have good coverage of the highly-cited core
>   (b) expand citations 1 hop from the top-15 papers and add ~40-80 more for a fuller picture
>
> Which do you prefer? Default is (a) since your saturation is already > 0.75."

Wait for user response. The default in the absence of response is **stop** (option a) — be conservative with budget.

## Edge cases

### User explicitly stops mid-search
- "Stop", "够了", "I have enough", "this is plenty" → stop immediately, write report from current KG state
- Do not run more expansions even if saturation < 0.5

### Approaching budget ceiling (papers_evaluated ≈ 80% of budget)
- Proactively stop without asking — say *"Approaching the Standard tier budget (170/180 papers). Stopping here and writing the report."*
- Never blow past 1.5× the tier budget (e.g. > 270 papers for Standard) — that's a different tier, requiring user re-confirmation

### Saturation curve unreliable (< 30 papers)
- discovery_curve needs at least ~30 classified papers to give a meaningful estimate
- Below that, ignore saturation; just check budget and continue retrieval
- Quick tier often finishes below 30 — just stop after retrieval is done, skip the curve

### Saturation NaN or curve.json missing
- Treat as low saturation (< 0.6); fall to decision branch 6
- Log a warning to the user: *"saturation curve unavailable, proceeding by tier budget."*

## Discovery curve is advisory, not authoritative

The `saturation_estimate` is computed from the rate of new high-rcs paper discovery vs. papers evaluated. It is **a signal, not a verdict**. Override the curve when:

- **User intent is exploratory** ("I don't know this field at all") → curve may underestimate true saturation since the user wants breadth, not just the core. Push 1 more hop.
- **User intent is known topic** ("I just need the seminal papers on prospect theory") → curve may overestimate. Stop earlier if rcs ≥ 8 papers are well-represented.
- **Audit tier** → the curve is informational only; you must run the full Audit pipeline (journal whitelist + 2 hops) regardless of saturation. Stopping early on Audit defeats its purpose.

## What to tell the user when stopping

In your STEP 14 user-facing message, briefly justify the stop:

> "Stopped at 142 papers with saturation 0.87. The high-rcs core (15 papers ≥ 7) is well covered, and the curve confidence is tight (CI 0.84-0.91). Citation expansion past this point adds tangential papers."

For audit stopping:

> "Completed the full Audit pipeline: 487 papers evaluated, 89 with rcs ≥ 6, journal whitelist Cochrane + medical_top applied, 2-hop citation chasing on top-23 papers. saturation 0.83 (this is normal for Audit — the tail is long)."

## Common mistake to avoid

Do not loop "expand → re-classify → expand → re-classify" indefinitely chasing higher saturation. If saturation rises by < 0.05 across two expansion rounds, **stop**. You're chasing diminishing returns — the additional papers are noise.
