# Summary Writer Guide

*This guide is read by the main agent in STEP 11 of `SKILL.md` to author the executive summary at `summary.md` for the current paper-search-pro run. The executive summary is composed by the main agent directly (not outsourced to a SubAgent) because your reading of the field is the deliverable.*

## Length & structure

- **Target**: ~300 words
- **Hard cap**: 500 words
- **Format**: plain Markdown; 1-3 short paragraphs OR ~6 bullet points; no headings inside the summary (the file is a section, not a document)

## Required structure

```
[1 opening sentence]: "This search returned N papers on <query>, with M classified as highly relevant (RCS >= 7)."

[2-3 sentences on field consensus]: What the field broadly agrees on -- what the dominant theoretical / empirical position is.

[1-2 sentences on key methods or frameworks]: How researchers in this area typically study the question (RCT? cohort study? specific model? PICO-defined approach? mechanistic experiment?).

[2-3 sentences on the most influential 3-5 papers]: Name and 1-line characterization of each. Use the influential_citation_count field where available (from SS enrichment) to rank, with citation_count as fallback. Spell out why each paper is influential -- not just that it is.

[1-2 sentences on open questions / unresolved tensions]: Where the field disagrees, what's missing, what the user should be aware of.

[OPTIONAL: 1 sentence on caveats]: If the search has known limitations (PubMed not queried, OpenAlex 3-day arXiv lag, etc.), mention briefly.
```

## What to include (required)

| Element | Why |
|---------|-----|
| **Main consensus / convergent finding** | The dominant answer in the field -- useful for orientation |
| **Key methods / theoretical frameworks** | Tells the user how to interpret the literature |
| **Top 3-5 highly cited / influential papers** | Concrete starting points for deep reading |
| **At least one open question or disagreement** | Avoids monolithic framing; flags where new research could contribute |

## What to avoid

- **AI-flavored language**: avoid "interesting", "important", "comprehensive", "significant", "various", "numerous", "a multitude of"
- **Em-dash overuse / "not just X, but Y" parallelism**: read your draft and remove these
- **Empty hedging**: "may", "could", "potentially" -- use specific claims with evidence
- **Lazy patterns**: "Papers cover topics ranging from A to Z" -- instead, *name* the topics
- **Generic praise**: "These papers represent significant contributions" -- say *what* makes them significant
- **Failure to commit**: "There are many perspectives" -- pick the major two or three and name them
- **Vague references**: "as several studies show" -- name the specific studies

## Ranking papers for the top-3-5 mention

Priority order for which papers to call out:

1. **rcs >= 9** papers that are also high `influential_citation_count` (SS field). These are the seminal works.
2. **rcs >= 8** papers with high `citation_count`. Foundational but slightly broader.
3. **rcs >= 7** recent papers (year >= current_year - 3) with high `cited_by_percentile_year`. The "hot" current work.

Mix: 2-3 from priority 1-2 + 1-2 from priority 3 = a good balance of classic + current.

## Worked example (prospect theory query)

**Query**: "find 5-6 high-impact papers on prospect theory in decision making, classics + a couple recent ones"

**Generated example output** (~298 words):

> This search returned 24 papers on prospect theory in decision making, with 11 classified as highly relevant (RCS >= 7). The field's central consensus, established by Kahneman and Tversky (1979), is that human decision-making systematically violates expected utility theory in two ways: people are more sensitive to losses than to equivalent gains (loss aversion), and they weight probabilities nonlinearly (overweighting small probabilities). This account replaced the dominant rational-actor framework in behavioral economics and decision science.
>
> Methodologically, the foundational work uses laboratory choice tasks with monetary gambles; cumulative prospect theory (Tversky & Kahneman, 1992) generalized the framework to continuous outcomes. Recent extensions employ neuroimaging (e.g., De Martino et al., 2006, Science) to localize loss aversion to amygdala-prefrontal circuits, and field studies (e.g., Camerer et al., 1997 on NYC taxi drivers) to test predictions outside the lab.
>
> The most influential papers are: Kahneman & Tversky (1979, Econometrica) -- the original framework, 46,000+ citations; Tversky & Kahneman (1992) -- cumulative prospect theory; Thaler (1980) -- early consumer choice application; De Martino et al. (2006) -- neural correlates; and Sokol-Hessner et al. (2009) -- loss-aversion modulation.
>
> Open questions remain on: (1) cross-cultural generalizability -- most evidence is WEIRD-sample; (2) whether loss aversion is a stable trait or context-dependent; and (3) the relationship between prospect-theory parameters and real-world consumer behavior, where recent meta-analyses report mixed effect sizes.
>
> *Caveat: PubMed was not queried (no medical signals detected); coverage focuses on OpenAlex.*

## Quick self-check before saving

- [ ] Under 500 words?
- [ ] Contains "highly relevant" or RCS counts?
- [ ] Names at least 3 specific papers by author + year?
- [ ] At least one specific method or framework named?
- [ ] At least one open question / disagreement called out?
- [ ] No "interesting" / "important" / "significant" / "comprehensive" / "various"?
- [ ] No more than 2 em-dashes total?
- [ ] No "not just X, but Y" structure?

If any check fails, revise.
