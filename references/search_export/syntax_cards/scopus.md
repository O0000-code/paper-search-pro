# Scopus（Elsevier，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。订阅登录墙 → 深链 **C 档（纯粘贴）**。**无可爆炸叙词表**。`W/n` 属 gap 家族（三源交叉锁定，A1 §2.3）。**★2025 秋布尔优先级变更预告** → 一律显式加括号。语法主张附官方 URL + verified_date。

```yaml
platform: "Scopus"
host: "Elsevier / scopus.com"
database: "Scopus"
access: subscription
field_tags:                          # 字段码(值)，60+ 个
  title_abstract_keyword: "TITLE-ABS-KEY(...)"   # 默认字段集
  title: "TITLE(...)"
  abstract: "ABS(...)"
  title_abstract: "TITLE-ABS(...)"
  author_keywords: "AUTHKEY(...)"
  all: "ALL(...)"
  author: "AUTH(...)"
  author_name: "AUTHOR-NAME(...)"
  source: "SRCTITLE(...)"
  doi: "DOI(...)"
  pub_year: "PUBYEAR"                # 比较符：PUBYEAR > 1993
  affiliation: "AFFIL(...)"
  index_terms: "INDEXTERMS(...)"     # 聚合索引词（非可爆炸叙词表）
  subject_heading: null              # ★ 无 MeSH 式可爆炸叙词表
  pub_type: "DOCTYPE(...)"
  subheading: null
boolean:
  and: "AND"
  or: "OR"
  not: "AND NOT"                     # ★ 排除必须用 AND NOT，非裸 NOT
  case: "uppercase-required"
  precedence: "() > W/n,PRE/n > AND NOT > AND > OR （当前序，2026 起生效；旧序 OR 最高已弃——官方博客 2025 秋预告此变更；务必括号消歧使其抗变更）"
proximity:
  unordered: "W/{n}"                 # within，无序
  ordered: "PRE/{n}"                 # precede，有序
  n_family: "gap"                    # n = 两词间最大间隔词数；W/0 = 相邻；n 范围 0-255（A1 已核实）
  field_limit: []
  constraints: ["parentheses_required_around_operands"]
truncation:
  multi_char: "*"                    # 零或多字符（behav*）
  single_char: "?"                   # 恰一字符（wom?n）
  zero_or_one: null
  min_chars_before: null
  phrase_truncation: "loose-phrase(\" \") 允许截词；exact-phrase({ }) 禁截词"
phrase:
  quote: "\"\""                      # 松散短语：同字段、允许截词、词序较松
  exact_brace: "{ }"                 # 精确短语：严格相邻，不许截词/标点变化
  exception: "{heart attack} 与 {heart-attack} 结果不同；双引号松散 vs 花括号精确"
controlled_vocab:
  name: null                         # 无自有可爆炸叙词表（INDEXTERMS = 聚合索引词）
  explode: null
  no_explode: null
  major: null
  subheading: null
  verification: not_applicable
line_search:
  supported: true
  syntax: "#1 AND #2 （Search History -> Combine queries）"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://www.scopus.com/search/form.uri?display=advanced"
  note: "登录墙：/search/form.uri 实测 301 重定向至 SSO 登录。入口指向 Advanced document search（display=advanced）：本卡产出的 TITLE-ABS-KEY(...) 字段码只在高级检索框生效，基本检索页粘进去不工作（2026-09-30 由 display=basic 改）。URL 结构已考证，执行待机构账号；交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://elsevier.libguides.com/Scopus/topical-search"
  - "https://supportcontent.elsevier.com/RightNow%20Next%20Gen/Scopus/Files/Scopus%20Quick%20Reference%20Guide%20WEB_2023.pdf"
  - "https://blog.scopus.com/boolean-searches-in-scopus-understanding-operator-precedence-best-practices"
verified_date: "2026-07-16"
gotchas:
  - "排除必须用 'AND NOT'，非裸 NOT"
  - "★Scopus 布尔优先级 2025 秋起改为行业标准 AND NOT > AND > OR（2026 初完成）——多算符字符串务必显式加括号使其抗变更（A1 §3.6）"
  - "两种短语：\"松散\"（允许截词、词序较松）vs {精确}（严格、禁截词）；{heart attack} != {heart-attack}"
  - "字段码操作数必须加括号；括号不配对报 Syntax Error"
  - "W/n 的 n = 两词间最大间隔（gap 家族）；W/0 = 相邻；n 范围 0-255（A1 §2.3）"
  - "无可爆炸叙词表；INDEXTERMS 是聚合索引词，非 MeSH 式；排除 Medline 记录用 'AND NOT INDEX(medline)'"
```

## 证据与说明（prose）

### 范围与角色
Scopus 是 Elsevier 的跨学科文摘引文库，订阅登录墙。深链 **C 档**：R4 §2.8 实测 `/search/form.uri` 返回 301 重定向至 SSO 登录 → 交付形态是可粘贴检索式本身。

### 字段标签（官方 LibGuide + Quick Reference Guide）
`字段码(值)`，60+ 个：`TITLE-ABS-KEY(...)`（默认字段集）、`TITLE(...)`/`ABS(...)`/`AUTHKEY(...)`、`ALL(...)`、`AUTH(...)`/`AUTHOR-NAME(...)`、`SRCTITLE(...)`、`DOI(...)`、`PUBYEAR > 1993`（比较符）、`AFFIL(...)`、`INDEXTERMS(...)`。**括号必需**（`TITLE-ABS(children OR pediatrics)` 对，缺括号错）。

### 布尔 / 邻近（官方博客 + A1 §2.3 三源交叉锁定）
`AND` `OR` `AND NOT`（**排除必须用 `AND NOT`**）**须大写**。邻近 `W/n`（within，**无序**）、`PRE/n`（precede，**有序**）。W/n 的 n = "maximum number of words that separate the terms"（多个明确引用 Elsevier 官方支持页的权威指南 + Scopus 官方博客三源一致）= `max_gap`（**gap 家族**）；`W/0` = 相邻；n 范围 0-255。**★优先级警示**：官方博客预告 Scopus 布尔优先级 2025 秋起改为行业标准 `AND NOT > AND > OR`（2026 初完成）——生成器对无括号多算符务必显式加括号消歧（A1 §3.6）。

> 证据纪律（A1 §2.3 移交）：Scopus W/n 的 Elsevier 现行支持页本轮 404（改版迁移），故以三源交叉锁定（结论一致、置信高）；WOS 为 Clarivate 官方一手逐字。若 Gate 需一手补强，复抓 Elsevier 支持中心新 URL（a_id=11213）即可。

### 截词 / 短语（官方）
`*` = 零或多字符（`behav*`）；`?` = 恰一字符（`wom?n`）。两种短语：`"loose phrase"`（双引号：同字段、允许截词、词序较松）vs `{exact phrase}`（花括号：严格相邻精确，不许截词/标点变化）。**`{heart attack}` 与 `{heart-attack}` 结果不同**。

### 受控词表
**无自有可爆炸叙词表**（Scopus 不做 MeSH 类检索；`INDEXTERMS` 是聚合索引词，非可爆炸叙词表）。排除 Medline 记录：`AND NOT INDEX(medline)`。`controlled_vocab.verification = not_applicable`。

### 深链（C 档）
`https://www.scopus.com/results/results.uri?...`（会话态）；`/search/form.uri` 实测 301→SSO。URL 结构已考证，执行待机构账号；只观测不绕墙（C-14）。
