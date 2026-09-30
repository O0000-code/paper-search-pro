# Web of Science Core Collection（Clarivate，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。订阅登录墙 → 深链 **C 档（纯粘贴）**。**无受控词表**（纯自由词）。`NEAR/n` 属 gap 家族（Clarivate 官方一手逐字核实，A1 §2.2）。语法主张附官方 URL + verified_date。

```yaml
platform: "Web of Science Core Collection"
host: "Clarivate / webofscience.com"
database: "Web of Science Core Collection"
access: subscription
field_tags:                          # 标签=(值) 形式
  topic: "TS="                       # 题名+摘要+作者关键词+Keywords Plus
  title: "TI="
  title_abstract: "TS="              # WoS 无纯题摘标签；TS 最接近（另含关键词）
  abstract: "AB="
  author_keywords: "AK="
  keywords_plus: "KP="
  author: "AU="
  source: "SO="
  pub_year: "PY="
  address: "AD="
  organization: "OG="
  doi: "DO="
  research_area: "SU="               # WoS 研究方向宽类（非叙词表）
  wos_category: "WC="
  issn: "IS="
  all_fields: "AF="
  subject_heading: null              # ★ WoS 无受控主题词表
  pub_type: null                     # 基础字段集无专用文献类型标签
  subheading: null
  all: "ALL="
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "case-insensitive"           # 算符大小写不敏感（仍建议大写以跨库一致）
  precedence: "NEAR/x > SAME > NOT > AND > OR  (括号覆盖)"
proximity:
  unordered: "NEAR/{n}"
  same_address: "SAME"               # 仅地址检索，同一地址行内
  n_family: "gap"                    # n = 两词间最大间隔词数；NEAR/0 = 相邻（A1 已核实）
  bare_near_default_gap: 15          # 裸 NEAR（无 /n）= NEAR/15
  field_limit: []
  constraints: ["no_AND_inside_NEAR_parentheses", "all_fields_operator_cap_49"]
truncation:
  multi_char: "*"                    # 零或多字符
  single_char: "?"                   # 恰一字符
  zero_or_one: "$"                   # ★ $ 在 WoS = 零或一字符（colo$r→color/colour），非截词——头号跨库陷阱
  min_chars_before: null
  phrase_truncation: "allowed"
phrase:
  quote: "\"\""                      # 精确短语，关闭词形还原(lemmatization)
  exception: "引号内关闭 lemmatization，做精确短语"
controlled_vocab:
  name: null                         # WoS 无主题词表（纯自由词库）
  explode: null
  no_explode: null
  major: null
  subheading: null
  verification: not_applicable       # 无受控词需核验
line_search:
  supported: true
  syntax: "#1 AND #2"                # Advanced Search 的 Session Query 编号
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://www.webofscience.com/wos/woscc/advanced-search"
  note: "登录墙：advanced-search 页实测 HTTP 200 但仅加载 Angular 外壳（2026-09-30 由 basic-search 改：本卡产出的 TS= 字段标签只在 Advanced Search 生效），出结果需机构鉴权；Advanced Search 有会话内可分享 query 链接但绑定会话、非无状态预填。URL 结构已考证，执行待机构账号；交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://webofscience.zendesk.com/hc/en-us/articles/20016122409105-Search-Operators"
  - "https://webofscience.zendesk.com/hc/en-us/articles/26916347018257-Web-of-Science-Core-Collection-Advanced-Search-Field-Tags"
  - "https://webofscience.zendesk.com/hc/en-us/articles/20130361503249-Advanced-Search-Query-Builder"
verified_date: "2026-07-16"
gotchas:
  - "★$ 在 WoS = 零或一字符（colo$r→color/colour），不是截词；同符号在 Ovid = 截词——头号跨库陷阱（A-4）"
  - "含 NEAR 的查询不能在同一括号内用 AND（'Germany NEAR/10 (monetary AND union)' 非法）"
  - "裸 NEAR（无 /n）默认 = NEAR/15；务必写 /n 避免静默宽窗"
  - "NEAR/n 的 n = 两词间最大间隔（gap 家族）；NEAR/0 = 相邻（Clarivate 官方一手核实，A1 §2.2）"
  - "WoS 无主题词表 → 靠同义词穷举 + 截词；SU= 是研究方向宽类，非 MeSH 式叙词"
  - "WoS 无法在单个字符串组合多字段 → 多字段须 OR 连多个 TAG=(...) 串"
```

## 证据与说明（prose）

### 范围与角色
WoS Core Collection 是 Clarivate 的跨学科引文索引，订阅登录墙。深链 **C 档**：R4 §2.8 实测 basic-search 页 HTTP 200 但仅加载 SPA 外壳，出结果需机构鉴权 → 交付形态是可粘贴检索式本身。

### 字段标签（官方 Zendesk 帮助）
`标签=(值)` 形式：`TS=`（题名+摘要+作者关键词+Keywords Plus）、`TI=`/`AB=`/`AK=`/`KP=`、`AU=`/`SO=`/`PY=`/`AD=`/`OG=`/`DO=`、`SU=`（研究方向）、`WC=`（WoS 类目）、`IS=`、`AF=`（All Fields）。**WoS 无法在单个字符串组合多字段**——多字段须 OR 连多个 `标签=(...)` 串。

### 布尔 / 邻近（Clarivate 官方一手，A1 §2.2 定点核实）
`AND` `OR` `NOT` `NEAR` `SAME`（大小写不敏感）。**优先级（实测确认）：`NEAR/x` > `SAME` > `NOT` > `AND` > `OR`**，括号覆盖。**`NEAR/n`**：两词间隔 ≤n、**词序无关**；裸 `NEAR` 默认 15 词；`NEAR/0` = 相邻。Clarivate 官方帮助中心逐字："Replace the x with a number to specify the **maximum number of words that separate the terms** … `NEAR/0` means words joined by the operator should be adjacent." → n = `max_gap`（**gap 家族**，`NEAR/0`=相邻是铁证：若 gap+1 则相邻应为 NEAR/1）。**硬约束：含 `NEAR` 的查询不能同括号用 `AND`**；隐式 AND（相邻词等价 AND）；All Fields 检索布尔/邻近算符上限 49。

### 截词 / 短语（官方）
`*` = 零或多字符；`?` = 恰一字符；**`$` = 零或一字符**（`colo$r`→color/colour）——**非截词**，与 Ovid 的 `$`=截词含义相反，是头号跨库陷阱。`"exact phrase"` 关闭词形还原做精确短语。

### 受控词表
**无**（WoS 无主题词表）→ 靠同义词穷举 + 截词；`SU=` 是 WoS 自造的研究方向宽类，非可爆炸叙词表。`controlled_vocab.verification = not_applicable`（无受控词可核）。

### 深链（C 档）
`https://www.webofscience.com/wos/woscc/advanced-search` — 实测 HTTP 200（仅 SPA 外壳，出结果需鉴权；2026-09-30 复测）。检索式用 TS= 字段标签，只能粘进 Advanced Search，所以入口指向它而不是 basic-search。Advanced Search 有「会话内可分享 query 链接」（链条图标复制），但绑定会话、非无状态预填。URL 结构已考证，执行待机构账号；只观测不绕墙（C-14）。
