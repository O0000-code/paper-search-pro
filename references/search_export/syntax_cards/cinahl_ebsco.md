```yaml
platform: "CINAHL"
host: "EBSCOhost (search.ebscohost.com)"
database: "CINAHL / CINAHL Plus with Full Text / CINAHL Complete (EBSCO)"
access: subscription
field_tags:
  # EBSCOhost two-letter codes, UPPERCASE, prefix style: "TI term" or "TI (a OR b)"
  title: "TI"
  title_abstract: "XB"                      # CINAHL-specific combo tag: Title OR Abstract
  abstract: "AB"
  subject_heading: "MH"                     # CINAHL Subject Heading (exact; major+minor)
  major_subject_heading: "MM"               # Major-concept subject heading only
  word_in_major_heading: "MJ"               # word in major subject heading or subheading
  word_in_heading: "MW"                     # word in subject heading or subheading
  subject_field: "SU"                       # broad subject fields (heading + KW + others)
  keyword: "KW"
  author: "AU"
  author_affiliation: "AF"
  journal_source: "JN"                      # exact publication name ; SO = words in pub name
  pub_type: "PT"
  all_text: "TX"                            # all text (full text where licensed)
  subheading: "two-letter subheading code"   # attach to heading: MH \"Hypertension/DT\"  (DT = drug therapy)
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-required"
proximity:
  unordered: "N{n}"                          # Near — any order ; e.g. (decision* N3 (aid* OR support*))
  ordered: "W{n}"                            # Within — entered order ; e.g. primary W3 care
  n_family: "gap"                            # n = max words BETWEEN the two terms (McGill: "up to n words between")
  field_limit: []                            # works across fields
  constraints: ["truncation_allowed_inside_proximity", "uncheck_suggest_subject_headings_or_specify_TI_AB"]
  bare_operator_note: "unqualified adjacent-word default varies by host/interface/version; generator always adds an explicit operator, so output is unaffected"
truncation:
  multi_char: "*"                            # zero-or-more (therap*)
  single_char: "?"                           # EXACTLY ONE character, not zero (ne?t -> neat/nest/next); not at word-end
  zero_or_one: "#"                           # zero-or-one (colo#r -> color/colour)
  min_chars_before: null
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""                              # "perceived stress scale" = exact ordered phrase
  exception: "EBSCO auto-expands variants; quotes force exact string"
controlled_vocab:
  name: "CINAHL Subject Headings (CINAHL Headings)"
  explode: "+ suffix inside the heading tag: (MH \"Pregnancy in Diabetes+\") -> heading + all narrower headings"
  no_explode: "(MH \"Pregnancy in Diabetes\") -> that heading only, no narrower terms"
  major: "use MM instead of MH: (MM \"Pregnancy in Diabetes\") -> major-concept only; combinable with explode (MM \"...+\")"
  subheading: "attach with / : (MH \"Hypertension/DT\") ; free-floating: (MW \"DI\" OR \"US\")"
  verification: llm_suggest_only             # no free CINAHL-Headings lookup API
line_search:
  supported: true
  syntax: "S1 AND S2"                         # EBSCO Search History (S1, S2, ...)
  history_cap: null
special_chars_escape: null                     # *, ?, # are wildcards; no backslash-escape scheme documented
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://search.ebscohost.com/login.aspx?authtype=ip&profile=ehost&defaultdb=ccm"
  note: "EBSCOhost addresses bind to institution customer-id/profile; execution requires institutional login. No public stateless deep link. Never construct a login-bypassing URL."
source_url:
  - "https://libraryguides.mcgill.ca/c.php?g=477164&p=5387366"                      # McGill: CINAHL MH/MM/MJ/MW field codes + explode +
  - "https://libraryguides.mcgill.ca/epib629/search-tips"                           # McGill: CINAHL Nn/Wn proximity + suggest-subject-headings note
  - "https://about.ebsco.com/sites/default/files/acquiadam-assets/Top-Five-Searching-Strategies-Handout.pdf"  # EBSCO official: N/W, wildcards
  - "https://connect.ebsco.com/"                                                     # EBSCO Connect help hub (CINAHL/MeSH Headings, field codes)
  - "https://guides.library.manoa.hawaii.edu/cinahl/cinahlhdgs"                      # CINAHL Explode / Major Concept / Subheadings (EBSCO-transcribed)
verified_date: "2026-07-16"
gotchas:
  - "Explode is the '+' SUFFIX on the heading, INSIDE the tag: (MH \"Heading+\") — not a separate operator."
  - "Major concept is a DIFFERENT tag (MM), not a modifier of MH; MM narrows, MH = major+minor."
  - "To run a proximity/keyword search, uncheck 'Suggest Subject Headings' or qualify with TI/AB — otherwise CINAHL intercepts terms as heading lookups."
  - "Wildcard trap: '?' = exactly one char (not zero, and not usable at word-end); '#' = zero-or-one."
  - "CINAHL Headings are LLM-suggested only — no free API; flag every MH/MM term for manual verification (risk A-6)."
  - "Subscription login wall (C-tier): deliver the paste-ready string, not a clickable stateless deep link."
hosts_note:
  summary: "CINAHL is EBSCO-exclusive — EBSCOhost is the ONLY production host (EBSCO owns CINAHL). There is no Ovid/ProQuest CINAHL. This card therefore has a single host; R4's generic EBSCO card previously proxied CINAHL, but the CINAHL Headings vocabulary (MH/MM/explode-+/subheadings) is CINAHL-specific and is documented here as an independent card."
  note: "The EBSCOhost engine is shared with PsycINFO-on-EBSCO, MEDLINE-on-EBSCO, ERIC-on-EBSCO, EconLit-on-EBSCO (same N/W operators, same *,?,# wildcards, same S1/S2 history). What is CINAHL-specific is the controlled vocabulary (CINAHL Subject Headings) and the XB (Title OR Abstract) combo tag."
```

# CINAHL — EBSCOhost (single host; independent card)

**Why an independent card.** CINAHL (Cumulative Index to Nursing and Allied Health Literature) is EBSCO-owned and exists ONLY on EBSCOhost — there is no Ovid or ProQuest CINAHL. R4 previously proxied CINAHL with the generic EBSCO (PsycINFO) card, but CINAHL's controlled vocabulary — **CINAHL Subject Headings** with `MH`/`MM`, explode via `+`, and subheadings — is CINAHL-specific and must be modeled as its own card (Wave-0 requirement, risk D-21 library×host modeling).

**Signature feature — CINAHL Subject Headings.** A MeSH-structured controlled thesaurus for nursing/allied-health. Official EBSCO wording on explode:

> "In a database with a tree, such as MeSH or CINAHL Headings, exploding retrieves all documents containing any of the subject terms below the term you selected. … If a plus sign (+) appears next to a narrower or related term, there are narrower terms below it."
> — EBSCO Help (Thesaurus), verified 2026-07-16

Concrete syntax (McGill, transcribing EBSCO CINAHL):

> "**Explode** — Represented by the + sign at the end of the subject heading … e.g., `(MH "Pregnancy in Diabetes+")` will search for records indexed with 'Pregnancy in Diabetes' OR 'Diabetes Mellitus, Gestational' OR 'Fetal Macrosomia'. **Major concept** — Represented by MM (instead of MH) … e.g., `(MM "Pregnancy in Diabetes")`; can be combined with Explode, e.g., `(MM "Pregnancy in Diabetes+")`."
> — https://libraryguides.mcgill.ca/c.php?g=477164&p=5387366

Heading-family field codes:
- `MH` = Subject Heading (exact; returns **major + minor** indexing).
- `MM` = Major Subject Heading only (indexer-designated main focus → higher precision, fewer hits).
- `MJ` = word in a major subject heading or subheading.
- `MW` = word in a subject heading or subheading.
- **Subheadings**: two-letter codes attached to a heading with `/`, e.g. `(MH "Hypertension/DT")` (DT = drug therapy); free-floating subheadings via `(MW "DI" OR "US")` (diagnosis / ultrasonography).
- `XB` = **Title OR Abstract** (a CINAHL-convenient combo tag; note EconLit-on-EBSCO lacks this).

**Critical execution note (official CINAHL behavior).** CINAHL's default unqualified box runs a *subject-heading lookup* ("Suggest Subject Headings" on). To run a raw keyword/proximity search you must uncheck it or qualify the field:

> "To use proximity operators in CINAHL, uncheck 'Suggest Subject Headings' if entering an unqualified search … or specify the TI OR AB fields in your search query."
> — https://libraryguides.mcgill.ca/epib629/search-tips

**Proximity / Boolean / wildcards.** Identical EBSCOhost engine as the other EBSCO databases: `Nn` (near, any order), `Wn` (within, ordered), `n` = **words BETWEEN** the terms (gap family; McGill: *"up to n words between them"*). Boolean UPPERCASE. Wildcards `*` (zero-or-more), `?` (exactly one char, not at word-end), `#` (zero-or-one, e.g. `colo#r`). Truncation is allowed inside proximity. Search History uses `S1`, `S2`, … combined as `S1 AND S2`.

**Controlled-vocab verification.** CINAHL Headings are **`llm_suggest_only`** — no free CINAHL-Headings lookup API exists. Every `MH`/`MM` term must be flagged for manual verification in CINAHL; never fake-verify (risk A-6).
