# Embase（Ovid 宿主，Wolters Kluwer，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。**同库不同宿主**——Ovid 语法与 embase.com（`embase_com.md`）完全不通用（D-21）。**此卡 Ovid 语法同样适用于 MEDLINE-on-Ovid、PsycINFO-on-Ovid、ERIC/CAB/EconLit-on-Ovid**（受控词表按库替换）。订阅登录墙+会话态 → 深链 **C 档**。Emtree 无免费 API → `llm_suggest_only`。

```yaml
platform: "Embase (Ovid)"
host: "Wolters Kluwer / ovidsp.ovid.com"
database: "Embase (Ovid host)"
access: subscription
field_tags:                          # 后置点码：词.码.
  title: ".ti."
  title_abstract: ".tw."             # text word = 题名+摘要
  abstract: ".ab."
  keyword: ".kw."                    # 或 .kf.
  multi_purpose: ".mp."              # multi-purpose：默认题名+摘要+主题词等多字段
  subject_heading: ".sh."            # 精确主题词（爆炸用 'exp 主题词/'）
  heading_word: ".hw."               # 主题词字段内词
  subheading: ".fs."                 # 浮动副主题
  pub_type: ".pt."
  author: ".au."
  journal: ".jn."
  all: ".mp."                        # 无纯 all 标签；.mp. 为默认多字段
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "case-insensitive"
  precedence: "括号优先；集合区间 or/1-5 and/1-3"
proximity:
  unordered: "adj{n}"                # 无序（primary adj3 care；n=1..99）
  ordered_adjacent: "adj"            # adj（无数字）= 严格相邻同序；adj1 = 相邻任意序
  n_family: "gap_plus_one"          # ★ Ovid adjN 属 gap+1：adj2 = 最多 1 间隔词（等式 Ovid adj2 ≡ EBSCO N1）
  field_limit: []
  constraints: ["freq_modifier: '词.mp. /freq=5'（该词至少出现 5 次）"]
truncation:
  multi_char: "$"                    # ★ $ 或 * = 零或多字符（Ovid 截词；therap$ = therap*）——与 WoS/embase.com $=零或一相反
  multi_char_alt: "*"
  single_char: "#"                   # # = 恰一字符（词中/尾，wom#n）
  zero_or_one: "?"                   # ? = 零或一字符（colo?r）
  min_chars_before: null
  bounded_truncation: "$n（限定最多 n 字符截词）"
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""                      # 引号或多词直接相邻按短语处理
  exception: "多词相邻默认按短语处理"
controlled_vocab:
  name: "Emtree (Embase-on-Ovid) ; MEDLINE-on-Ovid 用 MeSH ; PsycINFO-on-Ovid 用 APA Thesaurus"
  explode: "exp 主题词/  (爆炸)"
  no_explode: "主题词/  (不爆炸)"
  major: "*主题词/  或 focus 勾选（主要主题）"
  subheading: "主题词/副主题码（例 主题词/de）"
  verification: llm_suggest_only     # Emtree 无免费 API（本卡=Embase-on-Ovid）
line_search:
  supported: true
  syntax: "Search History 每行编号：1 and 2 ; or/1-5（合并 1 到 5 行）; and/"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: null                 # ovidsp.ovid.com 全程会话态，无无状态深链
  note: "登录墙 + 全程会话态（ovidsp.ovid.com 会话绑定），无无状态深链。交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://ospguides.ovid.com/OSPguides/embdb.htm"
  - "https://ospguides.ovid.com/OSPguides/medline.htm"
  - "https://library-guides.ucl.ac.uk/OvidSP/textword-searching"
  - "https://epoc.cochrane.org/sites/epoc.cochrane.org/files/uploads/Resources-for-authors2017/database_syntax_guide.pdf"
verified_date: "2026-07-16"
gotchas:
  - "★$ 在 Ovid = 截词（零或多，therap$=therap*），与 WoS/embase.com 的 $=零或一字符相反——头号跨库陷阱（A-4）"
  - "★Ovid 单字符/零或一符号也翻转：# = 恰一字符、? = 零或一字符（与 EBSCO/embase.com 的 ? 语义不同）"
  - "adj（无数字）= 严格相邻同序；adjN 无序；adjN 属 gap+1 家族（adj2 = 最多 1 间隔词），等式 Ovid adj2 ≡ EBSCO N1（A1 §2.4）"
  - "同库不同宿主：Ovid（.ti./adjN/exp 词/）与 embase.com（:ti/NEAR/de）完全不通用（D-21）"
  - "集合区间语法 or/1-5、and/1-3 是 Ovid 特色，非通用"
  - "本卡=Embase-on-Ovid（Emtree，llm_suggest_only）；MEDLINE-on-Ovid 换 MeSH、PsycINFO-on-Ovid 换 APA Thesaurus，均按各库受控词处理"
hosts_note:
  summary: "Ovid 是多库共享宿主（Embase/MEDLINE/PsycINFO/ERIC/CAB/EconLit 等 on Ovid）。语法体系（点码/adjN/$#?/exp 词/）一致，仅受控词表按库不同：Embase→Emtree、MEDLINE→MeSH、PsycINFO→APA Thesaurus。本卡以 Embase-on-Ovid 为主体。"
  medline_ovid: "MEDLINE-on-Ovid 语法同此卡，受控词换 MeSH（MeSH 存在性可经 NCBI 免费 API 核，但本卡集受控词核验轨仅在 pubmed/eric 卡上标 free_api；MEDLINE-on-Ovid 的 MeSH 仍按本卡的 host 语法生成）。"
```

## 证据与说明（prose）

### 范围与角色
Embase-on-Ovid（Wolters Kluwer Ovid 宿主）语法卡。**同库不同宿主**：与 embase.com（`embase_com.md`）语法完全不通用（`:ti` vs `.ti.`、`NEAR/n` vs `adjN`、`/exp` vs `exp .../`、`$`=零或一 vs `$`=截词）——宿主是一等建模维度（D-21）。订阅登录墙 + 全程会话态 → 深链 **C 档**（无无状态深链）。

### 字段标签（Ovid 官方 OSP Guides）
后置点码 `词.码.`：`.ti.` 题名、`.ab.` 摘要、`.tw.` text word（题名+摘要）、`.kw./.kf.` 关键词、`.mp.`（**multi-purpose**：默认题名+摘要+主题词等多字段）、`.sh.` 精确主题词、`.hw.` 主题词字段内词、`.fs.` 浮动副主题、`.pt.` 文献类型、`.au.`、`.jn.`。多字段逗号连（`social media.ti,ab.`）。

### 布尔 / 邻近（官方）
`AND` `OR` `NOT`。邻近 `adjN`（**无序**，`primary adj3 care`；n=1..99）；**`adj`（无数字）= 严格相邻同序，`adj1` = 相邻任意序**。频次修饰 `词.mp. /freq=5`（该词至少出现 5 次）。**★邻近族**：Ovid `adjN` 属 `gap_plus_one` 家族（`adj2` = 最多 1 间隔词）——校验等式 **Ovid `adj2` ≡ EBSCO `N1`**（均 ≤1 间隔词，A1 §2.4 官方旁证）。n 值经 proximity.py 查表换算（给定 canonical k=max_gap，gap+1 家族输出 n=k+1）。

### 截词 / 短语（官方 —— 跨库陷阱高发区）
`$` 或 `*` = 零或多字符（`therap$` = `therap*`，**Ovid 截词**）；`#` = **恰一字符**（词中/尾，`wom#n`）；`?` = **零或一字符**（`colo?r`）；`$n` = 限定最多 n 字符截词。**⚠️ `$` 在 Ovid 是截词，与 WoS/embase.com 的 `$`=零或一字符含义相反——头号跨库陷阱**；且 Ovid `?`=零或一、`#`=恰一，与 EBSCO/embase.com 的 `?`=恰一语义也相反，翻错静默改召回。

### 受控词表（Emtree，`llm_suggest_only`）
`exp 主题词/` = 爆炸；`主题词/` = 不爆炸；`*主题词/` 或 focus 勾选 = 主要主题；副主题 `主题词/副主题码`。映射（map term）交互式。本卡=Embase-on-Ovid，受控词=Emtree，**无免费 API → `llm_suggest_only`**，待人工核（A-6）。（MEDLINE-on-Ovid 换 MeSH、PsycINFO-on-Ovid 换 APA Thesaurus。）

### 行式检索 / 深链
Search History 每行编号，`1 and 2`、`or/1-5`（合并 1 到 5 行）等集合运算（Ovid 特色 `or/`、`and/` 区间语法）。深链 **C 档**：`ovidsp.ovid.com` 全程会话态，无无状态深链；交付=可粘贴检索式（C-14 只观测不绕墙）。
