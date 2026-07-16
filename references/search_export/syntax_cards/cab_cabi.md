```yaml
platform: "CAB Abstracts"
host: "CABI Digital Library (cabidigitallibrary.org) — Atypon/Literatum engine"
database: "CAB Abstracts (product code sc:CA) — publisher-native platform"
access: subscription
field_tags:
  # CABI Digital Library uses lowercase field tags, prefix style with colon: tag:term
  title: "title"                            # compound: searches ET (English title) + AT (additional title)
  english_title: "et"
  abstract: "ab"
  author: "author"                          # compound: AU + ED + CA
  author_affiliation: "aa"
  descriptor: "de"                          # CABI Thesaurus topic descriptor (controlled)
  organism_descriptor: "od"                 # controlled organism/taxonomic names
  geographic: "gl"                          # controlled geographic location
  broad_term: "up"                          # controlled broader taxonomic/geographic term
  identifier: "id"                          # non-controlled / emerging terms + US-spelling variants
  indexing_term: "indexingterm"             # SUPER field: searches DE + ID + OD + UP + GL at once
  cabicode: "cc"                            # CABICODE subject-classification code
  publication_title: "do"                   # source publication (phrase-indexed; use full title)
  pub_type: "it"                            # Item Type (journal article, conference, etc.)
  product: "sc"                             # Sequence/product code; CAB Abstracts = sc:ca
  year: "yr"
  language_of_text: "la"                    # ISO 639-1 codes, not language names
  doi: "oi"
  issn: "sn"
  isbn: "bn"
  subject_heading: "de"                     # (alias of descriptor for cross-card consistency)
  subheading: null                          # CABI has no MeSH-style subheading structure
  all: "n/a (default 'All fields' searches everything)"
boolean:
  and: "AND"                                # also &&
  or: "OR"                                  # also ||
  not: "NOT"                                # also !!
  case: "uppercase-required"                # lowercase and/or/not are parsed as SEARCH TERMS, not operators
proximity:
  unordered: "\"{term1} {term2}\"~{n}"      # Lucene phrase-slop: quotes + tilde + n ; e.g. "metabolic mechanism"~3
  ordered: null                             # no ordered/adjacency operator (slop is unordered)
  n_family: "gap"                           # n = max words SEPARATING the terms (official CABI wording)
  field_limit: []                           # any text field
  constraints: ["phrase_exclusive", "no_truncation_inside_quotes", "proximity_ignored_if_inside_quotes"]
truncation:
  multi_char: "*"                           # any number of chars (duoden* ; p*diatric -> pediatric/paediatric)
  single_char: null
  zero_or_one: "?"                          # ? matches 0 OR any single character (l?st -> last/lest/list)
  min_chars_before: null
  phrase_truncation: "forbidden"            # * and ? are IGNORED inside quotes and CAUSE A SEARCH ERROR
  leading_wildcard: "forbidden"             # wildcard cannot start a term (error)
phrase:
  quote: "\"\""                             # disables stemming + forces exact word/phrase
  exception: "inside quotes AND/OR/NOT become literal words; wildcards & proximity are ignored/error"
controlled_vocab:
  name: "CABI Thesaurus (Descriptors, Organism Descriptors, Geographic Location, Broad Terms, Identifiers)"
  explode: "search a Broad Term (up:) to auto-include narrower terms below it in the CAB hierarchy"
  no_explode: "search the exact Descriptor (de:) for that term only"
  major: null
  subheading: null
  index_field_stemming: "OFF — index fields require precise spelling; use truncation (de:colo?r) or the CABI Thesaurus for variants (British spelling)"
  verification: llm_suggest_only            # no free CABI-Thesaurus lookup API
line_search:
  supported: true
  syntax: "Recent Searches -> Combine Searches (session set combination)"
  history_cap: 10                            # last 10 searches per session (session expires after 30 min idle)
special_chars_escape: null                    # wildcards *,? ; quotes toggle stemming; no backslash-escape scheme
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://www.cabidigitallibrary.org/action/doSearch?AllField={urlenc}"
  note: "CAB Abstracts is subscription on every host; execution requires institutional login. URL structure noted only; not HTTP-verified this round, no login-bypass. Deliver the paste-ready professional string."
source_url:
  - "https://help.cabi.org/cabi-digital-library-help/"                                       # CABI official help hub
  - "https://help.cabi.org/cabi-digital-library-help/search/instructions-for-recreating-saved-searches-from-cab-direct"  # official: proximity ~n, wildcards, boolean, index-field stemming
  - "https://www.cabi.org/cabithesaurus/"                                                    # CABI Thesaurus (controlled vocab browse)
  - "https://ospguides.ovid.com/OSPguides/cabadb.htm"                                        # Ovid CAB Abstracts guide (hosts_note)
verified_date: "2026-07-16"
gotchas:
  - "CABI Digital Library REPLACED CAB Direct — syntax changed (Atypon/Literatum engine); do NOT reuse old CAB Direct MyCABI strings verbatim."
  - "Proximity is Lucene phrase-slop: \"a b\"~n. n = max words separating. Truncation (* / ?) INSIDE quotes is ignored AND errors — expand truncations to explicit variants before quoting."
  - "Boolean must be UPPERCASE; lowercase and/or/not are searched as literal words."
  - "Index fields (de/od/gl/up/id) are NOT stemmed — spelling must be exact; use CABI Thesaurus or de:colo?r style truncation. CABI uses British spellings."
  - "'?' here = zero-or-one character (not exactly-one); '*' = any number. Leading wildcards error."
  - "CABI Thesaurus terms are LLM-suggested only — no free API; flag every de:/od:/gl: term for manual verification (risk A-6)."
hosts_note:
  summary: "CAB Abstracts (CABI, agriculture/veterinary/environment/global-health) is hosted on the publisher-native CABI Digital Library (primary card), plus Ovid, EBSCOhost, and Web of Science. Syntax differs sharply by host; the CABI Thesaurus controlled vocabulary is the constant. Primary host = CABI Digital Library (current native platform, replacing CAB Direct)."
  ovid: "Ovid CAB Abstracts uses Ovid point-code syntax (.ti./.ab./.mp.), adjN proximity (gap+1 family: adj2 = max 1 word between), $ or * truncation, exp heading/ for thesaurus explode. Distinct title fields ET (Every Title) / OT (Original Title). Source: ospguides.ovid.com/OSPguides/cabadb.htm."
  ebsco: "EBSCOhost CAB Abstracts uses EBSCO syntax (UPPERCASE two-letter codes, Nn/Wn proximity = gap family, *,?,# wildcards, S1/S2 history) — mechanics identical to the CINAHL/EconLit EBSCO cards, but with the CABI Thesaurus vocabulary."
  wos: "Web of Science CAB Abstracts uses WoS syntax (TS=(), NEAR/n = gap family, *,$,? wildcards). No CABI-Thesaurus explode on the WoS platform."
  note: "CAB Direct (legacy) is being retired in favour of CABI Digital Library; treat CAB Direct saved searches as needing conversion."
```

# CAB Abstracts — CABI Digital Library (primary, publisher-native host)

**Host decision.** CAB Abstracts (CABI's flagship applied-life-sciences database: agriculture, forestry, veterinary, human health/nutrition, environment) is accessible on four hosts — the publisher-native **CABI Digital Library**, Ovid, EBSCOhost, and Web of Science. This card takes **CABI Digital Library** as the primary host because (1) it is the current publisher-native platform, consistent with the card-set's native-first pattern (PubMed=NLM, ERIC=native, CNKI=native, Wanfang=native); (2) it has comprehensive official documentation (the 60-page CABI Digital Library Search Guide); and (3) it hosts the native CABI Thesaurus. It **replaced CAB Direct** (Atypon/Literatum engine), so legacy CAB Direct strings need conversion. Ovid / EBSCO / WoS differences are captured in `hosts_note` (Ovid is the common systematic-review alternative). CAB Abstracts is subscription on every host → deep-link tier **C (paste-only)**.

**Signature feature — the CABI Thesaurus (five controlled index families).** Official definitions:

> "**Descriptor** – topic based terms … part of CABI's controlled vocabulary. **Organism Descriptor** – plant and animal names and scientific names … **Identifier** – new concepts or organisms that are not already in CABI's controlled vocabulary … **Geographic location** – Location where the research took place … **Broad term** – Terms which exist above a search term in the taxonomic or geographic hierarchy … Searching with Broader Terms will automatically find all relevant narrower terms immediately below that term."
> — CABI Digital Library Search Guide (help.cabi.org), verified 2026-07-16

Field tags: `de:` (descriptor), `od:` (organism descriptor), `gl:` (geographic), `up:` (broad term → the "explode"-equivalent), `id:` (identifier), and the super-field `indexingterm:` which searches DE+ID+OD+UP+GL together. Phrases must be quoted for exact parsing: `indexingterm:"disease prevention"` (unquoted it splits into `indexingterm:disease` AND `prevention`). CABI recommends thesaurus-anchored searching to cut string length: `de:"complementary and alternative medicine"`.

**Boolean (official).** `AND` / `OR` / `NOT` **must be capitalised** (symbols `&&` / `||` / `!!` also work, space-padded): *"Boolean operators must be capitalised, otherwise they are parsed as search terms not as Boolean operators."* Automatic AND between adjacent words. Use parentheses for 3+ mixed operators.

**Proximity (official) — Lucene phrase-slop.**

> "To do a proximity search, use quotation marks around terms you wish to specify followed by a tilde ~ and a number indicating the **maximum number of words separating the terms**. For example, `"metabolic mechanism"~3` searches for the words metabolic and mechanism within 3 words of each other. Please note that Proximity operators are ignored within quotation marks."
> — CABI Digital Library Search Guide

So `n` = **max words separating** = gap family (same family as PubMed's `[tiab:~N]`, WOS, Scopus). It is phrase-exclusive (must be quoted) and **truncation is forbidden inside the quotes** — expand truncations to explicit variants first.

**Truncation / wildcards / stemming (official).** `*` = any number of characters (`duoden*`, `p*diatric` → pediatric/paediatric); `?` = **zero OR any single character** (`l?st` → last/lest/list). Leading wildcards error. Wildcards inside double quotes are ignored and **cause a search error**. Word stemming is auto-ON for text fields (title/abstract/full text and the `indexingterm` super-field) but **OFF for the individual index fields** (`de`/`od`/`gl`/`up`/`id`), which require exact spelling — use truncation (`de:colo?r`) or the CABI Thesaurus (British spellings) for variants. Double quotes disable stemming.

**Set combination.** No classic `#1 AND #2` line syntax; instead **Recent Searches → Combine Searches** (last 10 searches per session; 30-min idle expiry).

**Controlled-vocab verification.** CABI Thesaurus terms are **`llm_suggest_only`** — no free CABI-Thesaurus lookup API. Flag every `de:`/`od:`/`gl:` term for manual verification in the CABI Thesaurus; never fake-verify (risk A-6).
