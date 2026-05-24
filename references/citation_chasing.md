# Citation Chasing

*This file is read by the main agent in STEP 9 of `SKILL.md` when the saturation curve / tier budget signals that citation expansion is warranted. Citation expansion is OPTIONAL — Quick tier always skips it; Standard does 1 hop conditionally; Deep does 1-2; Audit does 2.*

## When to expand (per tier × saturation matrix)

| Tier | Default hops | Trigger conditions |
|------|--------------|--------------------|
| Quick | **0** | Never expand. Keep results tight. |
| Standard | **1** | saturation < 0.6 AND papers_evaluated < 60% of budget |
| Deep | **1-2** | saturation < 0.7 OR user explicitly wants "thorough"; do 2 hops if rcs ≥ 8 papers cluster around 3-5 seminal works |
| Audit | **2 + venue whitelist** | Always do 2 hops; also enrich each hop with `openalex_helper journal-list` (Cochrane / medical_top) |

## Backward (references) vs forward (cited_by)

| Direction | Strength | Use for |
|-----------|----------|---------|
| **Backward** (references that this paper cites) | Finds the foundational lineage — what built this paper | Tracing the theoretical genealogy; finding the original construct paper; "what did this paper rely on" |
| **Forward** (papers that cite this paper) | Finds the descendant network — who used this work | Tracking how a method spread; finding replications / extensions / counter-evidence |

For most queries, **do both in one call** — that's what `openalex_helper citation-network` returns. The cost difference is small (one API call instead of two), and the recall gain from forward+backward together is meaningful.

```bash
# One call returns both directions
python3 -m scripts.openalex_helper citation-network <openalex_id> \
    --refs-limit 30 --cited-by-limit 50 \
    > ./paper-search-results/<id>/raw/citations_<openalex_id>.json
```

## Top-RCS filter (only expand from high-relevance papers)

**Rule**: only chase citations of papers with **rcs ≥ 7**. Lower-RCS papers, by definition, are tangential to the query — their citation networks are even more tangential.

For each rcs ≥ 7 paper in the current KG:
1. Call `citation-network`
2. Federate the resulting refs + cited_by into the KG
3. Re-classify only the NEW papers (skip already-classified ones)

If the top-RCS cluster is very small (< 3 papers with rcs ≥ 7), drop the threshold to rcs ≥ 6 for citation chasing — otherwise the expansion will be too narrow.

## Anti-explosion guards

Citation expansion can balloon a 100-paper KG to 5000+ papers if unchecked. Constrain via:

1. **Top-RCS gating** (above) — at most ~10 papers per hop trigger expansion
2. **Refs/cited limits** in the helper call: `--refs-limit 30 --cited-by-limit 50`
3. **Dedup before re-classify** — `federated_kg_resolver` already deduplicates by `paper_id`; papers already in the KG are not re-classified
4. **Stop after 1 hop unless user explicitly wants 2** — second-hop expansion typically adds 5-15× the paper count, mostly noise

If after 1 hop you've added > 200 papers and saturation jumped to > 0.85, **stop**. The diminishing returns are real.

## Federate + re-classify cycle

After each citation expansion:

```bash
# Step 1: Federate new citations into the existing KG
python3 -m scripts.federated_kg_resolver \
    --input-files ./.../kg_classified.json ./.../raw/citations_*.json \
    --output ./.../kg.json

# Step 2: Re-classify ONLY the new papers (already-classified papers keep their RCS)
# (the rcs_parser skips papers that already have a non-null rcs field)
python3 -m scripts.rcs_parser \
    --input-dir ./.../classifications/round_2/ \
    --kg ./.../kg.json \
    --output ./.../kg_classified.json

# Step 3: Recompute saturation
python3 -m scripts.discovery_curve \
    --kg ./.../kg_classified.json \
    --output ./.../curve.json
```

Loop until saturation stabilizes or budget exhausts (see `stop_decision.md`).

## Empirical warnings

- **K&T 1979 has `references=[]` in OpenAlex** (SA-Z2 F19 confirmed). Pre-2000 papers are systematically missing reference lists due to upstream OpenAlex takedowns. Accept the empty list — do not retry, do not try CrossRef (which won't help for old papers either). Forward `cited_by` for K&T 1979 still works (~46,625 papers cite it). For backward chasing on classics, you'll get nothing — that's the data, not a bug.
- **arXiv preprints have no `references` from OpenAlex by default** — they're in the locations[] field but not parsed. Forward `cited_by` works.
- **Audit tier**: combine citation chasing with `openalex_helper journal-list --preset Cochrane` after hop 1 to backfill systematic-review venues. This catches papers that exist in Cochrane Database but were under-ranked in the initial OpenAlex query.

## Forward-citation special case: tracking method spread

If the user query is methodology-focused (e.g. "BERT applications in clinical text"), the most valuable signal is **forward citations of the method paper**, not refs. Override the default:

```bash
python3 -m scripts.openalex_helper citation-network <BERT_paper_oa_id> \
    --refs-limit 5 --cited-by-limit 100
```

`refs-limit 5` cuts noise; `cited-by-limit 100` gives you the spread. Then filter the cited_by results by topic/year before re-classifying.
