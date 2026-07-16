```yaml
platform: "EconLit"
host: "EBSCOhost (search.ebscohost.com)"
database: "EconLit / EconLit with Full Text (American Economic Association)"
access: subscription
field_tags:
  # EBSCOhost two-letter codes, UPPERCASE, prefix style: "TI term" or "TI (a OR b)"
  title: "TI"
  title_abstract: "TI(...) OR AB(...)"   # EconLit-on-EBSCO has no single ti+ab tag (cf. CINAHL's XB)
  abstract: "AB"
  subject_heading: "DE"                    # exact EconLit Subject Descriptor (JEL) ; SU = broader subject field
  subject_broad: "SU"
  keyword: "KW"
  author: "AU"
  author_affiliation: "AF"
  journal_source: "SO"                     # source/publication name ; JN = exact journal name
  pub_type: "PT"
  language: "LA"
  all_text: "TX"                           # all text / full text where available
  named_person: "PS"                       # Named Person (EconLit person-as-subject limiter)
  geographic: "GE"                          # Geographic Descriptor (regional interest)
  subheading: null                          # EconLit descriptors have no MeSH-style subheading structure
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-required"
proximity:
  unordered: "N{n}"                         # Near — any order ; e.g. tax N5 reform
  ordered: "W{n}"                           # Within — entered order ; e.g. hiking W5 trails
  n_family: "gap"                           # n = max words BETWEEN the two terms (see proximity_table.json)
  field_limit: []                           # not field-restricted; works in TI/AB/TX etc.
  constraints: ["truncation_allowed_inside_proximity"]   # unlike PubMed, EBSCO allows * within N/W
  bare_operator_note: "unqualified adjacent-word default varies by host/interface/version (some EBSCO guides say ANDed, others N5); generator always adds an explicit operator, so output is unaffected"
truncation:
  multi_char: "*"                           # zero-or-more; end or mid-word (organi*ation)
  single_char: "?"                          # EXACTLY ONE character, NOT zero (wom?n -> woman/women)
  zero_or_one: "#"                          # zero-or-one character (colo#r -> color/colour)
  min_chars_before: null                    # EBSCO imposes no documented 4-char floor (cf. PubMed)
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""                             # "perceived stress scale" = exact ordered phrase
  exception: "EBSCO auto-expands plurals/variants; quotes force exact string"
controlled_vocab:
  name: "EconLit Subject Descriptors = JEL Classification codes (AEA)"
  explode: "Thesaurus 'Explode' option (browse Subjects/Indexes -> Subject Codes)"
  no_explode: "default (single descriptor, no narrower terms)"
  major: null                               # EconLit descriptors have no major/minor split
  subheading: null
  code_format: "4-digit = JEL 3-char code + trailing 0 (J16 -> J160); browse via DE or the Subject Codes index"
  verification: llm_suggest_only            # no free EconLit-thesaurus/JEL lookup API
line_search:
  supported: true
  syntax: "S1 AND S2"                        # EBSCO Search History (S1, S2, ...)
  history_cap: null
special_chars_escape: null                    # *, ?, # are wildcards; no backslash-escape scheme documented
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://search.ebscohost.com/login.aspx?authtype=ip&profile=ehost&defaultdb=eoh"
  note: "EBSCOhost addresses are bound to institution customer-id/profile; execution requires institutional login. No public stateless deep link. Do not construct any login-bypassing URL."
source_url:
  - "https://www.aeaweb.org/econlit/search-hints"                                   # AEA official: JEL descriptors, 4-digit code rule
  - "https://www.aeaweb.org/econlit/jelCodes.php?view=jel"                          # AEA official: full JEL code list
  - "https://about.ebsco.com/products/research-databases/econlit-full-text"         # EBSCO official product page
  - "https://about.ebsco.com/sites/default/files/acquiadam-assets/Top-Five-Searching-Strategies-Handout.pdf"  # EBSCO official: N/W, wildcards
  - "https://ospguides.ovid.com/OSPguides/econdb.htm"                               # Ovid EconLit guide (hosts_note: CC field)
verified_date: "2026-07-16"
gotchas:
  - "JEL subject codes must be searched as 4 digits on EconLit (J160, not J16); a trailing 0 is added to every JEL code."
  - "EBSCO field codes must be UPPERCASE (lowercase 'de' is treated as the literal word, not the DE field)."
  - "Wildcard trap: '?' = exactly one char (never zero); '#' = zero-or-one. They are NOT interchangeable."
  - "Subscription login wall (C-tier): deliver the paste-ready string; do not promise a clickable stateless deep link."
  - "EconLit-on-EBSCO has no single title+abstract tag — expand to TI(...) OR AB(...)."
  - "JEL/EconLit descriptors are LLM-suggested only — no free lookup API; flag every controlled-vocab term for manual verification in the target host."
hosts_note:
  summary: "EconLit is licensed by the AEA to multiple hosts; EBSCOhost is the most common academic host and is the primary card. JEL descriptors are the SAME everywhere (4-digit codes); only the field-code syntax and the classification-field mechanics differ by host."
  ovid: "Ovid EconLit uses point-code syntax (.ti./.ab./.mp.; default .mp. = ab,ti,ct), adjN proximity (gap+1 family, adj2 = max 1 word between), $ or * truncation. JEL codes have a DEDICATED field: CC (Classification Codes), searchable with wildcards, e.g. A2$.cc or A2*.cc retrieves all A2* codes; post-1991 uses 3-char alphanumeric (C13), pre-1991 4-digit numeric. Source: ospguides.ovid.com/OSPguides/econdb.htm."
  proquest: "ProQuest EconLit uses ProQuest field codes (SU/IF etc.) and NEAR/n (N/n), PRE/n (P/n) proximity (gap family). Descriptor field differs; consult ProQuest help."
  note: "Also on OCLC FirstSearch. Truncation symbols are provider-specific (AEA explicitly warns of this) — always re-check the target host's wildcard chars before pasting."
```

# EconLit — EBSCOhost (primary host)

**Coverage / role.** EconLit is the American Economic Association's authoritative index to economics literature (journal articles, books, collective-volume articles, dissertations, working papers, and full-text JEL book reviews). EBSCOhost is the most common academic access host; this is the primary card. EconLit is subscription-only on every host → deep-link tier **C (paste-only)**; deliver the paste-ready professional search string, not a clickable URL.

**Signature feature — the JEL classification code field.** EconLit's controlled vocabulary is the **Journal of Economic Literature (JEL) Classification System** (a.k.a. AEA Classification System), the field-standard subject scheme for economics. Official AEA wording:

> "The EconLit subject descriptors are the same as the Journal of Economic Literature (JEL) classifications also known as the American Economic Association Classification System. On EconLit, a zero has been added to the JEL classification to make a four-digit descriptor code. For example, the JEL classification 'A11 - Role of Economics; Role of Economists' appears on EconLit as Role of Economics; Role of Economists (A110). **When searching by subject code on EconLit, it is necessary to use all four digits, i.e. A110, or a truncation symbol.**"
> — AEA, *EconLit Search Hints*, https://www.aeaweb.org/econlit/search-hints (verified 2026-07-16)

Practical consequence for the generated string: a subject-code block is more precise than free-text (AEA's own example: `Country and Industry Studies of Trade (F140)` is narrower than the word `trade`). On EBSCOhost, browse **Subjects / Indexes → Subject Codes** to pick a descriptor, or search the exact descriptor with `DE`. The dedicated numeric classification field code exists on **Ovid** (`CC`, e.g. `A2$.cc`); on EBSCOhost the codes are searched through the descriptor/subject field. Truncation symbols are provider-specific — the AEA note explicitly flags this, so re-check the host before pasting.

**Boolean / field codes (official EBSCO).** `AND` / `OR` / `NOT` must be UPPERCASE. Field codes are UPPERCASE two-letter prefixes (`TI teaching AND AB anxiety`). EBSCO's own guidance: *"each code must be entered in UPPER case … Otherwise your codes could be interpreted as simple text"* (EBSCO Connect / library transcription). Use parentheses to reuse one code across an OR block: `DE (J160 OR "economics of gender")`.

**Proximity (official EBSCO Top-5 Searching Strategies handout).**

> "Near Operator (N) finds results in which search terms are within a specified number of words of one another in any order. Example: tax N5 reform … Within Operator (W) finds results in which search terms are within a specified number of words of one another and in the order in which you entered them. Example: hiking W5 trails."
> — https://about.ebsco.com/sites/default/files/acquiadam-assets/Top-Five-Searching-Strategies-Handout.pdf

The `n` is the **maximum number of words BETWEEN the two terms** (gap family — same family as WOS/Scopus/ProQuest; see `proximity_table.json`). Truncation IS permitted inside EBSCO proximity (unlike PubMed).

**Truncation / wildcards (official EBSCO Top-5 handout).**

> "Use an asterisk (*) when you want to search for results containing various forms of a word … Use wildcards (? or #) … ? stands for one additional character, but not for zero characters. # stands for zero or one character. A search for wom?n will find … woman and women. A search of colo#r will find … color or colour."

So `*` = zero-or-more, `?` = **exactly one** character (never zero), `#` = zero-or-one. These are not interchangeable — the single most common EBSCO wildcard error.

**Controlled-vocab verification.** EconLit descriptors / JEL codes are **`llm_suggest_only`** — there is no free EconLit-thesaurus or JEL lookup API. Every proposed descriptor/code must carry a "manual-verify in target host" flag; never fake-verify (risk A-6).
