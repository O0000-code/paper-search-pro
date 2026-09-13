# Report identity and scholarly title contract

This is the Harness contract for the human-facing report. Read it in STEP 1
when defining the search topic and again in STEP 11 when naming the finished
report.

The failure this contract prevents is semantic overloading: a user's message is
an instruction to the search agent, not automatically a publication-quality
title. Courtesy language, tool names, export requests, deadlines, database
choices, journal tiers, and other operating constraints must never become the
visual H1 merely because they appeared in the request.

## Four roles; never collapse them

| Field | Purpose | Authorship | Where it appears |
|---|---|---|---|
| `original_user_query` | Verbatim evidence of what the user asked | User | PRISMA-S / audit metadata; never the H1 |
| `search_topic` | Normalized semantic scope used to plan retrieval | Main agent in STEP 1 | Query plan / report metadata; not automatically the H1 |
| `display_title` | Scholarly title for the report's central narrative and visual identity | Main agent, finalized in STEP 11 after seeing the evidence | HTML and Markdown H1; browser-tab title |
| eligibility / search filters | Language, date, database, document type, tier, PICO limits, and similar constraints | User + query plan | Methods, filter summary, and audit log |

`metadata.query` remains a legacy alias of `original_user_query` for old
consumers. New renderers must not read it for a heading.

## STEP 1: write the search topic, not the report title

Build `SEARCH_TOPIC` from the concept blocks and the user's substantive research
intent. Remove material that tells the agent *how to work* rather than *what the
research is about*:

- greetings, courtesy, urgency, personal background, and conversational framing;
- “find papers”, “use this Skill”, “make a report”, “export RIS”, and similar actions;
- database names, search depth, journal tiers, language of publication, and date
  limits when they are merely eligibility rules;
- requested output counts and presentation instructions.

Keep population, exposure/intervention, outcome, setting, mechanism, and study
design only when they are part of the scientific question. `SEARCH_TOPIC` can be
in the retrieval language; it is an internal semantic scope, not visual copy.

Do not mechanically use `rank_intent.cleaned_query` as the topic. That helper
removes recognized rank phrases, but arbitrary requests still contain prose and
other constraints. Use its result as an input to semantic planning, then express
the topic from the actual concept blocks.

## STEP 11: author the final display title from the evidence

Finalize `DISPLAY_TITLE` only after classification, filtering, and enrichment,
alongside the executive summary. The title must describe the report that actually
exists, not an anticipated corpus from before retrieval.

A strong title behaves like a rigorous paper or review title:

1. **Names the substantive object.** A reader should know the field and central
   phenomenon without seeing the original prompt.
2. **Expresses the organizing relationship.** Use a precise synthesis axis such
   as mechanism, developmental stage, methodological role, intervention, tension,
   or comparison when the retained evidence supports it.
3. **Is evidence-bounded.** Do not claim causality, consensus, effectiveness,
   comprehensiveness, or a developmental process that the final papers do not
   establish.
4. **Carries the report's visual identity.** Prefer a composed academic noun
   phrase over a question, command, search string, or list of constraints.
5. **Uses the report UI language.** For `UI_LANG=zh`, write natural academic
   Chinese while preserving established English abbreviations where useful. For
   `UI_LANG=en`, write idiomatic academic English rather than translating Chinese
   syntax word for word.
6. **Stays concise enough to function as an H1.** Prefer one line or two balanced
   lines. A colon is useful only when the subtitle contributes a genuine
   conceptual axis, not a parenthetical dump of filters.

### What belongs in the title

- central construct or phenomenon;
- scientifically meaningful population or developmental period;
- intervention/exposure and outcome when they define the question;
- a synthesis frame genuinely visible in the final corpus (for example,
  “from measurement tool to interaction context”).

### What normally does not belong in the title

- “English papers”, “中科院 1–2 区”, “JCR Q1”, database names;
- Quick/Standard/Deep/Audit tier, paper count, export format;
- “latest”, a year range, or “2026” when these only describe inclusion timing;
- “find”, “search”, “help me”, “report”, “literature review” when they merely
  describe the requested operation;
- claims such as “effects”, “impact”, or “efficacy” when the retained evidence is
  qualitative, descriptive, or methodological.

An eligibility fact can enter the title only when it is also part of the
scientific meaning. Examples: “Adolescent development during the COVID-19
pandemic” legitimately keeps the historical period; “papers published after
2020” does not. “Randomized trials of…” may be valid for a methods-defined
meta-analysis; “PubMed RCT filter” is never title copy.

## Cross-language examples

### Chinese request with operational constraints

Request:

> 请用 Paper Search Pro 找 2026 年英文、中科院 1/2 区的发展心理学 AI 文献，Agent 做研究或作为研究对象都可以。

- `original_user_query`: preserve the sentence verbatim.
- `search_topic`: `developmental psychology; AI/agents as research methods or developmental contexts`
- `display_title`: `人工智能与智能体在发展心理学中的双重角色：研究工具与发展情境`
- filters: English; first-published 2026; CAS tier 1/2.

The rejected title `2026 年发展心理学中的 AI（英文，中科院 1–2 区）`
mistakes eligibility labels for the report's intellectual center.

### English exploratory request

Request:

> Could you quickly find me a few good papers about how children trust social robots? Use the deep tier and export RIS.

- `search_topic`: `children's trust in social robots`
- `display_title`: `Children’s Trust in Social Robots: Developmental Mechanisms and Interaction Cues`
- filters/workflow: Deep tier; RIS export.

Only use the subtitle about mechanisms and cues if those themes appear in the
retained evidence. Otherwise use `Children’s Trust in Social Robots`.

### Clinical PICO request

Request:

> Find English RCTs since 2015 on CBT chatbots for adolescent anxiety, JCR Q1 only.

- `search_topic`: `CBT chatbots for adolescent anxiety`
- `display_title`: `Conversational CBT for Adolescent Anxiety: Efficacy and Engagement`
- filters: English; RCT; 2015-present; JCR Q1.

If outcomes are not reported, remove `Efficacy and Engagement` rather than
promising findings the corpus cannot support.

## Failure-safe behavior

The Python and React renderers must never infer an H1 from
`original_user_query` or legacy `metadata.query`.

- Authored `display_title` present → normalize whitespace and render it.
- Authored title absent/blank → render `文献检索报告` for Chinese UI or
  `Literature Search Report` for English UI.
- Legacy payload with only `query` → preserve it as audit metadata, but still use
  the localized generic H1.

A generic but honest title is preferable to a conversational prompt presented as
scholarly copy. The user can rerun STEP 11 to author a stronger title without
re-searching or reclassifying papers.

## Pre-render acceptance check

Before STEP 12, verify all of the following:

- The title is entailed by the final retained papers and the executive summary.
- It is a declarative academic title, not a request, question, search string, or
  product instruction.
- It contains no database, tier, language, export, or routine date-filter labels.
- Any population, outcome, mechanism, comparison, or causal wording is supported.
- It is idiomatic in `UI_LANG` and preserves necessary domain terminology.
- `original_user_query`, `search_topic`, and `display_title` are three distinct
  metadata values even when a very short user query makes two strings identical.
