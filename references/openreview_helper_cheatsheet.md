# openreview_helper CLI cheatsheet

**Role**: AI-topic booster that sits next to arXiv. Its value is **acceptance status**, not extra recall. OpenAlex and Semantic Scholar list the current year's ICLR / ICML / COLM papers as arXiv preprints. OpenReview is the review platform those venues use, so it knows the same paper is "ICLR 2026 Oral". Most papers it returns are already in OpenAlex or arXiv under the same title. The resolver merges them by title and the accepted venue replaces "arXiv".

**Only for AI / ML topics.** OpenReview hosts ML, AI, CV, NLP and robotics venues (ICLR, NeurIPS, ICML, COLM, CoRL, TMLR, ACL via ARR, CVPR, AAAI, KDD). A psychology, medicine or social-science query returns only imported copies of papers OpenAlex / PubMed already have, and the whitelist drops those. Routing (when to call it) lives in `source_routing.md`.

**Entry point**: `python3 -m scripts.openreview_helper --search "<q>" [--n 30] [--year-min Y] [--year-max Y] [--max-pages 8] [--output-file F]`.
No key and no login. stdout is one JSON list (`UnifiedPaperEntity` dicts, same shape as `yiigle_helper`). The attribution line and one diagnostics line go to stderr.

## Syntax + examples

```bash
# Recent accepted papers on an AI topic (typical: 3 pages, about 7 s)
PYTHONPATH=$PSP_HOME python3 -m scripts.openreview_helper \
    --search "diffusion language model" --n 30 --year-min 2025 \
    --output-file "$SEARCH_DIR/raw/openreview.json"

# stderr, e.g.:
#   Data: OpenReview (openreview.net), metadata CC0 | kept only papers accepted by a main conference track or TMLR (...)
#   openreview: 3 page(s), 75 records seen, 22 accepted, 20 kept; stopped: n_reached
```

```python
from scripts import openreview_helper
papers = openreview_helper.search("diffusion language model", n=30, year_min=2025)
openreview_helper.last_search_stats   # {'pages_fetched', 'records_seen', 'accepted_seen', 'kept', 'stopped', 'query'}
```

`search()` **never raises**. On any failure it returns what it had already collected, which may be `[]`. Read `last_search_stats["stopped"]` to tell "OpenReview blocked us" (`challenge`, `http_403`, `http_429`, `timeout`, `network_error`, `bad_json`, `bad_shape`) from "the topic has no accepted papers here" (`end_of_results`, `max_pages`, `n_reached`). Say which one it was in the PRISMA-S log.

## What is kept: the acceptance whitelist

About 83% of search hits are **not** accepted papers. They are workshops, rejected papers (the venue string literally reads "Submitted to ICLR 2026"), withdrawn and under-review papers (including anonymous ACL ARR drafts), and profile imports of papers published elsewhere (`dblp.org/…`, `OpenReview.net/Public_Article`, `OpenReview.net/Archive`). The code keeps a note only when `content.venueid` is **exactly**:

| venueid | Example | Kept as |
|---|---|---|
| `<org>[/<more>]/<YYYY>/Conference` | `ICLR.cc/2026/Conference`, `colmweb.org/COLM/2026/Conference`, `EMNLP/2023/Conference` | main-track accepted paper |
| `TMLR` | `TMLR` ("Accepted by TMLR") | accepted journal paper |

Everything else is dropped, including `…/Rejected_Submission`, `…/Withdrawn_Submission`, `…/Submission`, `…/Workshop/…`, `TMLR/Rejected`, `TMLR/Under_Review`, `TMLR/Decision_Pending` and every import. This is a whitelist on purpose, because each venue names its non-accepted states differently. The `venue` string is never used to decide status: it is free text, and an imported record's reads exactly like an accepted one ("NeurIPS 2024").

## Output fields

```jsonc
{
  "source_native_id": "openreview:g88nt4ieTG",       // forum id; also the paper_id (no DOI / arXiv id on venue papers)
  "title": "Diffusion Language Model Knows the Answer Before It Decodes",
  "abstract": "...",
  "authors": [{"name": "Pengxiang Li"}, ...],
  "year": 2026,                                     // conference: from venueid; TMLR: pdate, else cdate
  "venue": "ICLR 2026 Oral",                        // never the bare word "OpenReview"
  "type": "article",
  "keywords": ["diffusion language model", "discrete"],
  "tldr": "...",                                    // content.TLDR when the authors gave one
  "pdf_url": "https://openreview.net/pdf?id=g88nt4ieTG",   // only when the note has a PDF
  "oa_locations": ["https://openreview.net/forum?id=g88nt4ieTG"],  // reviews and discussion live here
  "sources": ["openreview"],
  "discovery_path": null                            // left unset on purpose
}
```

**Venue label** = `<Name> <YYYY>[ <Tier>]`.
- **Name**: the venue string's first word when the venueid's year follows it ("NeurIPS 2025 poster" gives "NeurIPS"). Otherwise the venueid segment just before the year, with any domain suffix stripped (`ICLR.cc` gives "ICLR", `colmweb.org/COLM/…` gives "COLM").
- **Year**: always the venueid's year.
- **Tier**: whole words only, case-normalised. `oral` → Oral, `spotlight` or ICML's `spotlightposter` → Spotlight, `poster` → Poster, `findings` → Findings. Findings wins over the others, so an EMNLP Findings paper never reads as a main-track paper.
- **No tier word**: ICML's "regular", ICLR 2023's "notable top 5%", "EMNLP 2023 Main" and "COLM 2026" get no tier ("ICML 2026").
- **Compound words**: "KSMI 2026 ShortOralPoster" is one word, so it does **not** become "Oral".

## Known limits

- **Only the search endpoint works.** `GET /notes?content.venueid=…` (list a whole venue) answers anonymous clients with 403 `ChallengeRequiredError`. The helper uses only `GET https://api2.openreview.net/notes/search?…&limit=25&offset=k`. OpenReview has been tightening automated access since late 2025, so the search endpoint may get the same wall. The helper then returns `[]` with `stopped: challenge`. Treat this source as optional; nothing may depend on it.
- **Politeness**: pages of 25, at least 1 s between pages, 20 s timeout, at most `--max-pages` (default 8) pages. OpenReview publishes no rate limit. Keep calls to one or two per run and never run them in parallel.
- **`count` is always 10000** (a cap). It cannot estimate the hit total, so do not feed it to coverage.
- **Relevance is keyword-based and noisy.** The first hits can be off-topic (a Romansh language-ID paper for "diffusion language model"). Downstream RCS scoring handles this; do not treat rank as relevance.
- **No DOI, no arXiv id** on venue papers. Merging with OpenAlex / arXiv is by normalised title only, and a title changed between arXiv and camera-ready will not merge.
- **The whitelist admits every venue's main track**, small ones included (e.g. KSMI 2026, a Korean music-informatics conference). Venue prestige comes from the rank layer, not from this helper.
- **Accepted-paper tracks outside `…/Conference` are dropped**: NeurIPS Datasets & Benchmarks uses `NeurIPS.cc/<YYYY>/Datasets_and_Benchmarks_Track` or `NeurIPS.cc/2023/Track/Datasets_and_Benchmarks`. Admitting them means adding one pattern to `_accepted_kind` and a label for the track.
- **Which rejected papers are visible depends on the venue.** ICLR publishes every rejected and withdrawn paper, while ICML, COLM and KDD publish only accepted ones. So rejected hits come mostly from ICLR, and the whitelist drops them all anyway.
- **English only**: translate a Chinese query into English terms before calling, as for arXiv.
