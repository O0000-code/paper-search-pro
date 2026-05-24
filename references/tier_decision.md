# Tier Decision

*This file is read by the main agent in STEP 0 of `SKILL.md` to pick one of the four tiers before any retrieval starts.*

## The four tiers

| Tier | Wall-clock (ideal) | Wall-clock (realistic) | Papers | OpenAlex strategy | L2 boosters | L3 enrich | Citation hops |
|------|-----------:|-----------:|-------:|-------------------|-------------|-----------|--------------:|
| Quick | ~5 min | **~7-9 min** | 20-60 | single-strategy, top-30 | usually skip | skip | 0 |
| **Standard** (default) | ~10 min | **~14-18 min** | 60-180 | `double-sort` 3-strategy top-50 | per source_routing | top-N rcs≥6 | 1 |
| Deep | ~30 min | **~40-50 min** | 180-400 | `double-sort` top-100 + seminal + reviews | per source_routing | top-N rcs≥6 | 1-2 |
| Audit | ~2-3 hr | **~3-4 hr** | 400-1000+ | full multi-strategy + journal whitelist | independent PubMed search allowed | full top-N | 2 + venue whitelist |

> **Time-budget reality check** — the "ideal" column is the pure API + compute lower bound. Real-world adds ~50-70% overhead for: diagnostic round-trips (CLI argparse drift), classifier SubAgent scheduling latency (parallel dispatch is not free), HTML rendering on large bundles, and main-agent reasoning between steps. **Quote the realistic column when telling the user "this will take ~X min"** — quoting the ideal sets the user up for a 1.7×-1.9× overrun (E3 Session-#1 / Session-#2 empirical).

## Trigger signals (per tier)

**Quick** — short query, 5-10 papers requested, time-boxed
- "查一下" / "几篇" / "扫一眼"
- "5-6 papers" / "a handful" / "high-impact only"
- "before tomorrow" / "in 5 min" / "fast scope"
- "classics" + low number / "just the seminal ones"
- "I'm not writing a review, just exploring"
- explicit "quick" / "fast" / "short"

**Standard** — default for unspecified literature search, scope-a-topic
- "find papers on X" without depth specifier
- "I'm writing background / 综述 / introduction"
- "老板让我看一下" / "scope this topic"
- "what's been published on Y"
- "我对这块完全不懂"
- "lit review for proposal / class paper / thesis chapter"

**Deep** — review-article writing, 30+ min budget, real depth
- "I'm writing a proper literature review article"
- "thorough" / "real depth" / "comprehensive"
- "submission" / "for publication"
- "review for journal X"
- "综述写作" / "深度文献综述"
- "I need to cite every important paper"

**Audit** — systematic review / PRISMA / meta-analysis preparation
- "systematic review" / "SR" / "Cochrane"
- "PRISMA" / "PRISMA-S" / "PRISMA flow diagram"
- "meta-analysis" / "网络元分析" / "umbrella review"
- "inclusion criteria" / "exclusion criteria" listed
- explicit PICO with hard population/intervention bounds
- "preparing a SR for [journal X]" / "Cochrane Library protocol"

## Decision tree (apply in order, first match wins)

```
1. Audit signals present?
   YES → Audit tier (show limitations warning, get user confirmation)
2. Deep signals present?
   YES → Deep tier
3. Quick signals present?
   YES → Quick tier
4. Otherwise:
   → Standard tier (default)
```

The default is **Standard** — never pick Quick or Deep silently. If you pick anything other than Standard, **state your reasoning to the user in one sentence** before retrieving.

## Real example mapping (from SKILL.md §Examples)

| Example | Trigger | Picked tier |
|---------|---------|-------------|
| "find 5-6 high-impact papers on prospect theory, classics + recent" | "5-6", "high-impact", short, single-topic | **Quick** |
| "用 paper-search-pro 帮我找一些工作记忆训练干预文献 老板让我看 我对这块完全不懂" | "找一些", "老板让我看", "完全不懂" → default Standard | **Standard** |
| "I'm writing a proper literature review on attachment + HRI in elderly care, need real depth" | "literature review article", "real depth", "submission" | **Deep** |
| "preparing a systematic review on dietary interventions for IBS in adults. IC: RCTs, ≥18, low-FODMAP/fiber, English, 2010-present" | "systematic review", explicit PICO + IC list | **Audit** |

## Audit-tier limitations warning (paste verbatim before starting)

```
This is NOT a PRISMA-compliant systematic review replacement.

paper-search-pro Audit tier is SR-prep assist — it helps you:
- Cover OpenAlex deep + PubMed MeSH + journal whitelist
- Generate PRISMA-S 16-item log for transparency
- Produce BibTeX/RIS for citation manager import

It does NOT replace:
- Cochrane Library / Embase / CINAHL (specialized SR databases)
- PROSPERO protocol registration
- Dual independent screening (you still need human screeners)
- Hand-searching reference lists of included studies (we do 2-hop max)
- Grey literature / clinical trial registries beyond NCT numbers

If you're submitting to Cochrane / a journal demanding PRISMA 2020 compliance,
treat our output as PHASE 1 SCOPING, not the final SR. You still need:
1. Cochrane/Embase searches alongside ours
2. PROSPERO registration
3. Dual-reviewer screening with conflict resolution
4. Risk-of-bias tool (RoB 2 / ROBINS-I) per included study

Confirm you understand and want to proceed with Audit tier? (yes/no)
```

Wait for explicit "yes" before retrieving.
