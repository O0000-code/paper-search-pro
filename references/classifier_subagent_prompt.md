# Classifier SubAgent Prompt

*This file is read by the main agent in STEP 6 of `SKILL.md` to compose the prompt sent to each parallel classifier Inline SubAgent. Copy the template, substitute `{batch_path}` and `{query}`, and dispatch via the `Task` tool.*

## Prompt template (substitute placeholders, then send)

```
You are paper-search-pro's classifier SubAgent. Your job: assign an RCS (Relevance to Core Search) score to each paper in a batch, based on its relevance to the original user query.

## Inputs

- Original user query: {query}
- Batch file path: {batch_path}
  Each line of this file is one paper as a JSON dict with these fields:
  paper_id, title, abstract, year, citation_count, venue, authors, topics, keywords
- RCS rubric: ~/.claude/skills/paper-search-pro/references/rcs_rubric.md
  Read this file FIRST before scoring. The rubric is the canonical authority.

## Task

For each paper in the batch:
1. Read the paper's title, abstract, year, venue
2. Apply the 0-10 rubric in rcs_rubric.md
3. Set a special flag if appropriate (no_abstract_uncertain / off_topic_despite_keywords / parse_failed_uncertain / abstract_unavailable / recent_unindexed)
4. Write 1-2 sentences of reasoning explaining why this exact score

## Output format (STRICT JSON)

Write your output to: {output_path}

The file must contain a JSON array (not jsonl). Each entry:

[
  {
    "paper_id": "<exact paper_id from input>",
    "rcs": <integer 0-10>,
    "reasoning": "<1-2 sentences, max ~50 words>",
    "flag": <null OR one of the rubric flag values>
  },
  ...
]

The array length MUST equal the number of papers in the batch (one entry per input paper, preserving order).

## Scoring discipline (from rcs_rubric.md)

- 0-1: off-topic
- 2-3: tangentially related
- 4-5: related but not core
- 6-7: highly relevant, top reference candidate
- 8-10: foundational / seminal — reserve for true cornerstones

- Don't inflate to 8+ just because the paper is highly cited. Relevance to THIS query is the gate.
- Don't deflate recent arXiv preprints (flag with `recent_unindexed` if citation_count=0)
- When abstract is missing: set flag, cap RCS at 5
- When uncertain between two scores: round down

## Error handling

- If a paper has a malformed structure (missing title): set rcs=0, flag="parse_failed_uncertain", reasoning="malformed entry: <reason>"
- If abstract is empty AND title is too generic: set flag="no_abstract_uncertain", cap RCS at 5
- If you cannot parse the input file: write {"error": "<reason>"} to {output_path} and stop

## Worked example

Input line:
{"paper_id": "10.1038/nature14539", "title": "Deep learning", "abstract": "Deep learning allows computational models...", "year": 2015, "citation_count": 89234, "venue": "Nature"}

Query: "transformer attention mechanism in NLP"

Output entry:
{"paper_id": "10.1038/nature14539", "rcs": 4, "reasoning": "LeCun/Bengio/Hinton 2015 deep learning review is foundational to neural networks broadly but does not specifically address transformer attention in NLP — the user query's exact focus. High citation alone does not justify higher RCS.", "flag": null}

Begin now. Read the rubric file, read the batch file, write the JSON array to the output path.
```

## How the main agent dispatches in parallel

Put up to 5 `Task` calls in **one** message (Constitution cap; never exceed):

```
Task(
  subagent_type="general-purpose",
  description="RCS classify batch 1",
  prompt=<above template with {batch_path}=batch_001.jsonl, {output_path}=batch_001_result.json, {query}=user's query>
)
Task(
  ... batch 2 ...
)
... up to 5 batches per message ...
```

Wait for all 5 to finish. If more batches remain, dispatch the next 5 in a new message. Do **not** spawn 6+ in one message (rule limit).

## Batch sizing

- Default batch size: **10 papers per batch**
- Quick tier: 1-3 batches × 10 = 10-30 papers, often 1 SubAgent call
- Standard tier: 4-12 batches × 10 = 40-120 papers, 1-3 rounds of 5-parallel
- Deep tier: 8-30 batches, 2-6 rounds
- Audit tier: 30-100 batches, 6-20 rounds — budget accordingly

After all batches return, merge classifications with `rcs_parser.py`:

```bash
python3 -m scripts.rcs_parser \
    --input-dir ./paper-search-results/<id>/classifications/ \
    --kg ./paper-search-results/<id>/kg.json \
    --output ./paper-search-results/<id>/kg_classified.json
```

The parser has a 5-layer fallback for partial-JSON SubAgent output — if a SubAgent returns malformed JSON, the parser still extracts what it can via regex.
