# APA PsycINFO（Ovid 宿主，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。**同库双宿主**——Ovid（本卡）与 EBSCOhost（`psycinfo_ebsco.md`）语法不通用（D-21）。Ovid 通用语法体系见 `embase_ovid.md`；本卡记 PsycINFO-on-Ovid 特有点。订阅登录墙+会话态 → 深链 **C 档**。APA Thesaurus 无免费 API → `llm_suggest_only`。

```yaml
platform: "APA PsycINFO (Ovid)"
host: "Wolters Kluwer / ovidsp.ovid.com"
database: "APA PsycINFO (Ovid host)"
access: subscription
field_tags:                          # Ovid 点码：词.码.
  title: ".ti."
  title_abstract: ".tw."             # text word = 题名+摘要
  abstract: ".ab."
  multi_purpose: ".mp."
  heading_word: ".hw."               # 主题词字段词（PsycINFO 特有强调）
  key_concepts: ".id."               # ID = Key Concepts（作者关键词）
  mesh_word: ".mf."                  # MF = MeSH word（Ovid PsycINFO 记法）
  subject_heading: ".sh."            # 精确主题词（爆炸用 'exp 词/'）
  pub_type: ".pt."
  author: ".au."
  journal: ".jn."
  subheading: ".fs."                 # 浮动副主题
  all: ".mp."
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "case-insensitive"
proximity:
  unordered: "adj{n}"                # 无序（primary adj3 care；n=1..99）
  ordered_adjacent: "adj"            # adj（无数字）= 严格相邻同序；adj1 = 相邻任意序
  n_family: "gap_plus_one"          # Ovid adjN 属 gap+1（adj2 = 最多 1 间隔词；Ovid adj2 ≡ EBSCO N1）
  field_limit: []
  constraints: ["freq_modifier: '词.mp. /freq=5'"]
truncation:
  multi_char: "$"                    # ★ $ 或 * = 零或多字符（Ovid 截词）——与 EBSCO/WoS $ 语义相反
  multi_char_alt: "*"
  single_char: "#"                   # # = 恰一字符
  zero_or_one: "?"                   # ? = 零或一字符（与 EBSCO ?=恰一相反）
  min_chars_before: null
  bounded_truncation: "$n"
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""
  exception: "多词相邻默认按短语处理"
controlled_vocab:
  name: "APA Thesaurus of Psychological Index Terms (via Ovid)"
  explode: "exp 词/  (爆炸)"
  no_explode: "词/  (不爆炸)"
  major: "*词/  或 focus 勾选（主要主题）"
  subheading: "词/副主题码"
  verification: llm_suggest_only     # APA Thesaurus 无免费查表 API
line_search:
  supported: true
  syntax: "1 and 2 ; or/1-3（合并区间）; and/"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: null                 # ovidsp.ovid.com 全程会话态，无无状态深链
  note: "登录墙 + 全程会话态（ovidsp.ovid.com），无深链。交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://ospguides.ovid.com/OSPguides/psycdb.htm"
  - "https://library-guides.ucl.ac.uk/OvidSP/textword-searching"
  - "https://pmc.ncbi.nlm.nih.gov/articles/PMC12527542"      # EBSCO↔Ovid PsycInfo 字段码翻译表
verified_date: "2026-07-16"
gotchas:
  - "同库双宿主：Ovid（.ti./adjN/exp 词/）与 EBSCO（TI/Nn/DE）不通用（D-21）——见 psycinfo_ebsco.md"
  - "★跨宿主翻译陷阱（APA 官方翻译研究）：EBSCO 的 HW 在 EBSCO PsycInfo 无精确等价，最近似 SU，但 EBSCO SU 会同时搜 KW/ID+MA/MF——译时须放宽为 SU=HW,ID,MF"
  - "★Ovid $ = 截词（零或多），与 WoS/EBSCO 的 $=零或一相反；Ovid ?=零或一、#=恰一，与 EBSCO ?=恰一也相反（A-4）"
  - "adjN 属 gap+1 家族（adj2 = 最多 1 间隔词），Ovid adj2 ≡ EBSCO N1；跨宿主翻邻近须查 proximity_table（A-3）"
  - "APA Thesaurus 无免费 API → llm_suggest_only，待人工核（A-6）"
hosts_note:
  summary: "PsycINFO 同库双宿主：Ovid（本卡）与 EBSCOhost（psycinfo_ebsco.md），语法不通用。Ovid 通用点码/adjN/$#?/exp 词/ 体系见 embase_ovid.md（多库共享宿主）。"
  ebsco: "PsycINFO-on-EBSCO 用前置两字母码 + 空格（TI/AB/DE/MH/MM/SU）、Nn/Wn（gap）、*,?,# 通配、S1/S2 历史——见 psycinfo_ebsco.md。"
  field_translation: "EBSCO↔Ovid 字段码非一一映射（APA 官方翻译表 PMC12527542）：HW→SU(放宽 SU=HW,ID,MF)、ID(Key Concepts)→.id.、MF(MeSH word)→.mf.。"
```

## 证据与说明（prose）

### 范围与角色
APA PsycINFO 在 Ovid 宿主上的语法卡。语法体系同 Ovid 通用（`.ti./.ab./.mp.`、`adjN`、`$`/`#`/`?`、`exp .../`——完整机制见 `embase_ovid.md`）；本卡记 PsycINFO-on-Ovid 的特有点。订阅登录墙 + 会话态 → 深链 **C 档**（无深链）。

### PsycINFO-on-Ovid 特有字段
`.hw.` 主题词字段词、`ID`（Key Concepts 作者关键词，Ovid 记 `.id.`）、`MF`（MeSH word）、`HW`（Heading Word）。**跨宿主翻译陷阱**（据 APA 官方翻译研究 PMC12527542）：EBSCO 的 `HW` 在 EBSCO PsycInfo 无精确等价，最近似是 `SU`，但 EBSCO `SU` 会同时搜 `KW/ID` + `MA/MF`——**译时须放宽为 `SU=HW,ID,MF`**。

### 布尔 / 邻近 / 截词
同 Ovid：`adjN` 邻近（无序，**gap+1 家族**，`adj2`=最多 1 间隔词，Ovid adj2 ≡ EBSCO N1）；截词 `$`/`*`=零或多（**Ovid 截词，与 WoS/EBSCO 的 `$`=零或一相反**）、`#`=恰一、`?`=零或一（与 EBSCO `?`=恰一相反）。括号嵌套。n 值经 proximity.py 查表，勿手算（A-3）。

### 受控词表（APA Thesaurus，`llm_suggest_only`）
APA Thesaurus（叙词表），`exp 词/` 爆炸、`*词/` 或 focus 限定主要主题、`词/副主题码`。**无免费查表 API** → `llm_suggest_only`，待人工核（A-6）。

### 行式检索 / 深链
Ovid Search History 编号 + `or/1-3`、`and/` 集合运算。深链 **C 档**：`ovidsp.ovid.com` 会话态，无深链；交付=可粘贴检索式（C-14）。
