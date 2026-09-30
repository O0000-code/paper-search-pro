# Stop Decision

*This file is read by the main agent in STEP 8 of `SKILL.md` after `discovery_curve.py` produces a coverage estimate. The decision combines `curve.json` (advisory) with tier budget and user intent — the main agent has final authority.*

## Inputs to the decision

| Input | Source | Meaning |
|-------|--------|---------|
| `coverage_estimate` | `curve.json` | 0.0-1.0; estimate of how much of the relevant literature you've covered |
| `ci_lower`, `ci_upper` | `curve.json` | 95% interval; it narrows as more relevant papers are re-found across searches |
| `method` | `curve.json` | `sample_coverage` = estimated from this run's searches; `prior` = nothing to measure (fewer than two searches, no relevant paper found, or too few relevant papers to tell), so the number is the Undermind median prior capped at 50%, not evidence |
| `relevance_band` | `curve.json` | The rcs floor the estimate used: 7, or 6 when the rcs ≥ 7 papers were too few (e.g. two papers, each re-found or found once, which would otherwise read as 100%) |
| `papers_evaluated` | KG length | How many papers have been classified |
| `tier_budget` | `tier_decision.md` | Quick 60 / Standard 180 / Deep 400 / Audit 1000 |
| `user_intent` | from your query understanding | Known topic (high prior) vs. exploration (low prior) |

## Decision matrix (coverage × budget remaining)

| Coverage \ Budget | **Plenty remaining** (< 50% used) | **Tight** (50-80% used) | **Exhausted** (≥ 80% used) |
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

3. method == "prior"?
   → There is no evidence yet: decide by tier budget. For Standard+, the planned
     citation hop (STEP 9) adds the second search the estimate needs; re-check after it.

4. coverage_estimate > 0.85?
   YES → Stop. Quote the interval; further expansion mostly re-finds known papers.

5. coverage_estimate in [0.6, 0.85]?
   → Expand citations 1 hop from top-rcs papers (STEP 9), then re-check.

6. coverage_estimate < 0.6?
   → Multiple options. Pick based on tier:
      - Quick: stop (curve is unreliable with <50 papers anyway)
      - Standard: expand citations + add 1 strategy (recency)
      - Deep: expand 2 hops + add strategies (seminal + reviews)
      - Audit: expand 2 hops + journal whitelist + ask user about other databases

7. None of above match?
   → Default to "expand 1 hop" if tier allows; otherwise stop.
```

## When to ask the user (coverage 0.7 - 0.85, budget around 50%)

This zone is genuinely ambiguous. Rather than guess, tell the user the numbers:

> "Coverage estimate is 0.78 (CI 0.71-0.84). You're at 95/180 papers in Standard tier (53% of budget). I can either:
>   (a) stop here and write the report — you have good coverage of the highly-cited core
>   (b) expand citations 1 hop from the top-15 papers and add ~40-80 more for a fuller picture
>
> Which do you prefer? Default is (a) since your coverage is already > 0.75."

Wait for user response. The default in the absence of response is **stop** (option a) — be conservative with budget.

## Edge cases

### User explicitly stops mid-search
- "Stop", "够了", "I have enough", "this is plenty" → stop immediately, write report from current KG state
- Do not run more expansions even if coverage < 0.5

### Approaching budget ceiling (papers_evaluated ≈ 80% of budget)
- Proactively stop without asking — say *"Approaching the Standard tier budget (170/180 papers). Stopping here and writing the report."*
- Never blow past 1.5× the tier budget (e.g. > 270 papers for Standard) — that's a different tier, requiring user re-confirmation

### Few relevant papers (a handful rated ≥ 7)
- The estimate rests on how often those few were re-found; its interval is wide
- When they are too few to tell anything, `curve.json` says so: `relevance_band: 6` (estimated over rcs ≥ 6 instead) or `method: prior`. Either way the core is thin — for Standard+, chase citations from those papers (STEP 9) rather than stop
- Quick tier often ends here — stop after retrieval, and quote the number with its interval

### curve.json missing
- Treat as low coverage (< 0.6); fall to decision branch 6
- Log a warning to the user: *"coverage estimate unavailable, proceeding by tier budget."*

## Discovery curve is advisory, not authoritative

`coverage_estimate` is the sample coverage of this run's searches: how often the separate searches in `raw/` (strategies, reviews, Chinese sources, citation hops) found the same rcs ≥ 7 papers again (rcs ≥ 6 when `relevance_band` is 6). `1 - coverage` is roughly the chance that one more search of the same kind turns up a relevant paper you do not have. Searches that are deliberately different (classics vs. recent, another language) lower it — that is real, not a bug. It is **a signal, not a verdict**. Override the curve when:

- **User intent is exploratory** ("I don't know this field at all") → the estimate may understate how much of the core you have, since the user wants breadth, not just the core. Push 1 more hop.
- **User intent is known topic** ("I just need the seminal papers on prospect theory") → curve may overestimate. Stop earlier if rcs ≥ 8 papers are well-represented.
- **Audit tier** → the curve is informational only; you must run the full Audit pipeline (journal whitelist + 2 hops) regardless of coverage. Stopping early on Audit defeats its purpose.

## What to tell the user when stopping

In your STEP 14 user-facing message, briefly justify the stop:

> "Stopped at 142 papers with coverage 0.87. The high-rcs core (15 papers ≥ 7) is well covered, and the curve confidence is tight (CI 0.84-0.91). Citation expansion past this point adds tangential papers."

For audit stopping:

> "Completed the full Audit pipeline: 487 papers evaluated, 89 with rcs ≥ 6, journal whitelist Cochrane + medical_top applied, 2-hop citation chasing on top-23 papers. coverage 0.83 (this is normal for Audit — the tail is long)."

## Common mistake to avoid

Do not loop "expand → re-classify → expand → re-classify" indefinitely chasing higher coverage. If coverage rises by < 0.05 across two expansion rounds, **stop**. You're chasing diminishing returns — the additional papers are noise.
