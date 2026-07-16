# APA PsycINFO（EBSCOhost 宿主，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。**同库双宿主**——EBSCOhost（本卡）与 Ovid（`psycinfo_ovid.md`）语法不通用（D-21）。此 EBSCO 语法引擎同 CINAHL/EconLit/ERIC-on-EBSCO/MEDLINE-on-EBSCO。订阅登录墙 → 深链 **C 档**。APA Thesaurus 无免费 API → `llm_suggest_only`。

```yaml
platform: "APA PsycINFO (EBSCOhost)"
host: "EBSCOhost (search.ebscohost.com)"
database: "APA PsycINFO"
access: subscription
field_tags:                          # 前置两字母码 + 空格：码 值
  title: "TI"
  title_abstract: "TI(...) OR AB(...)"   # EBSCO PsycINFO 无单一题摘标签
  abstract: "AB"
  subject_heading: "DE"              # 精确主题词描述符（APA Thesaurus）
  major_subject_heading: "MM"        # 仅 major 主题词
  subject_heading_all: "MH"          # PsycINFO 主题词（含 major+minor）
  subject_field: "SU"                # 广主题字段（注意同搜 KW+MA 多字段，非纯叙词）
  keyword: "KW"
  test_measure: "TM"                 # 测验/量表名
  author: "AU"
  source: "SO"                       # 来源刊
  author_affiliation: "AF"
  all_text: "TX"                     # 全文
  pub_type: "PT"
  subheading: null                   # APA 描述符无 MeSH 式副主题结构
  all: "TX"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-required"
proximity:
  unordered: "N{n}"                  # Near，无序（tax N5 reform；最多 255 词）
  ordered: "W{n}"                    # Within，有序（hiking W5 trails）
  n_family: "gap"                    # n = 词间最大间隔词数（EBSCO 引擎，同 CINAHL/EconLit）
  field_limit: []
  constraints: ["truncation_allowed_inside_proximity"]
truncation:
  multi_char: "*"                    # 零或多字符（therap*）
  single_char: "?"                   # 恰一字符（ne?t→neat/nest/next），不能用于词尾
  zero_or_one: "#"                   # 零或一字符（colo#r→color/colour）
  min_chars_before: null
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""                      # "perceived stress scale" 精确短语
  exception: "EBSCO 默认自动检索复数/所有格等变体；引号强制精确串（单词也建议加引号）"
controlled_vocab:
  name: "APA Thesaurus of Psychological Index Terms (PsycINFO)"
  explode: "Thesaurus 内 Explode（爆炸下位词）"
  no_explode: "DE \"exact descriptor\"（单个描述符，不含下位）"
  major: "MM（仅 major 概念）或 Thesaurus 内 Major concept 限定"
  subheading: null
  verification: llm_suggest_only     # APA Thesaurus 无免费查表 API
line_search:
  supported: true
  syntax: "S1 AND S2"                # EBSCO Search History（S1, S2, ...）
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://search.ebscohost.com/login.aspx?authtype=ip&profile=ehost&defaultdb=psyh"
  note: "EBSCOhost 按机构 customer-id/profile 定址，执行需机构登录，无公众无状态深链。交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://www.apa.org/pubs/databases/training/ebsco.pdf"
  - "https://about.ebsco.com/sites/default/files/acquiadam-assets/Top-Five-Searching-Strategies-Handout.pdf"
  - "https://connect.ebsco.com/"
verified_date: "2026-07-16"
gotchas:
  - "同库双宿主：EBSCO（TI/DE/Nn、前置码+空格）与 Ovid（.ti./exp 词//adjN）不通用（D-21）——见 psycinfo_ovid.md"
  - "★EBSCO SU 同时搜 KW 与 MA 三个字段，非纯叙词——精确受控词用 DE"
  - "布尔与字段码须大写；字段码是前置两字母 + 空格（TI teaching AND AB anxiety）"
  - "通配陷阱：? = 恰一字符（不能用于词尾）；# = 零或一字符；* = 零或多"
  - "Nn/Wn 属 gap 家族（n = 词间间隔），与 Ovid adjN(gap+1) 不同族——跨宿主翻邻近须查表（A-3）"
  - "APA Thesaurus 无免费 API → 每 DE/MH/MM 标 llm_suggest_only，待人工核（A-6）"
hosts_note:
  summary: "PsycINFO 同库双宿主：EBSCOhost（本卡）与 Ovid（psycinfo_ovid.md），语法不通用。APA Thesaurus 受控词两宿主共享，但字段码/邻近/截词语法完全不同（D-21）。"
  ovid: "PsycINFO-on-Ovid 用 Ovid 点码（.ti./.ab./.mp./.hw.、adjN gap+1、$/#/?、exp 词/、*词/ focus）——见 psycinfo_ovid.md。跨宿主翻译陷阱：EBSCO HW 无 Ovid 精确等价，最近似 SU，但 EBSCO SU 会同时搜 KW/ID+MA/MF，译时须放宽为 SU=HW,ID,MF。"
  shared_ebsco_engine: "EBSCOhost 引擎与 CINAHL/EconLit/ERIC-on-EBSCO/MEDLINE-on-EBSCO 共享（同 Nn/Wn、同 *,?,# 通配、同 S1/S2 历史）；PsycINFO 特有的是 APA Thesaurus 受控词。"
```

## 证据与说明（prose）

### 范围与角色
APA PsycINFO 在 EBSCOhost 宿主上的语法卡。**同库双宿主**：与 PsycINFO-on-Ovid（`psycinfo_ovid.md`）语法不通用（D-21）。此 EBSCO 语法亦适用于 ERIC-on-EBSCO、CINAHL、MEDLINE-on-EBSCO（引擎共享，仅受控词表按库不同）。订阅登录墙 → 深链 **C 档**：R4 卡7 记 EBSCOhost 按机构 customer ID/profile 定址，非公众无状态深链。

### 字段标签 / 布尔 / 邻近（官方 APA×EBSCO + EBSCO Top-5）
**前置两字母码 + 空格** `码 值`：`TI`/`AB`/`SU`(主题)/`DE`(精确描述符)/`KW`/`AU`/`SO`/`MH`(major+minor)/`MM`(仅 major)/`TM`(测验量表)/`TX`(全文)/`AF`。示例 `TI teaching AND AB anxiety`。布尔 `AND`/`OR`/`NOT` 须大写。邻近 `Nn`（Near，无序，最多 255 词）、`Wn`（Within，有序）——**gap 家族**（n = 词间间隔，同 CINAHL/EconLit EBSCO 引擎），可与截词/括号嵌套（`mindfulness N5 (anxiety OR depression)`）。

### 截词 / 短语（官方）
`*` = 零或多字符；`?` = **恰一字符**（`ne?t`→neat/nest/next，**不能用于词尾**）；`#` = 零或一字符。单词也建议加引号——EBSCO 默认会自动检索复数/所有格等变体，`"teach"` 只匹配精确串。

### 受控词表（APA Thesaurus，`llm_suggest_only`）
`DE "exact descriptor"` 精确描述符；`SU` 主题字段（**注意 EBSCO 的 `SU` 同时搜 KW 与 MA 三个字段，非纯叙词** → 精确受控词用 `DE`）；主题词从 Thesaurus 选、可 Explode（爆炸下位词）、可 Major concept 限定（`MM`）。**APA Thesaurus 无免费查表 API** → `llm_suggest_only`，每词待人工核（A-6）。

### 深链（C 档）
EBSCOhost 机构定址（`search.ebscohost.com/login.aspx?...`），无公众无状态深链；交付=可粘贴检索式（C-14 只观测不绕墙）。
