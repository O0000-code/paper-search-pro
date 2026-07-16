# Embase（embase.com 宿主，Elsevier，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。**同库不同宿主**——embase.com 语法与 Embase-on-Ovid（`embase_ovid.md`）完全不通用（D-21）。订阅登录墙 → 深链 **C 档**。Emtree 无免费 API → `llm_suggest_only`。语法主张附官方 URL + verified_date。

```yaml
platform: "Embase (embase.com)"
host: "Elsevier / embase.com"
database: "Embase"
access: subscription
field_tags:                          # 后置冒号：'值':字段
  title: "':ti'"                     # 'term':ti
  title_abstract: "':ti,ab'"
  title_abstract_keyword: "':ti,ab,kw'"
  abstract: "':ab'"
  author_keyword: "':kw'"
  subject_heading: "':de'"           # Emtree 叙词
  author: "':au'"
  pub_year: "':py'"
  pub_type: null                     # embase.com 文献类型经限定项/Emtree，非本卡后缀标签
  subheading: "Emtree 副主题：/exp/mj 组合 或 floating subheading"
  all: "':de,ab,ti'  (常用宽字段组合)"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "case-insensitive"
  precedence: "括号优先；邻近算符对操作数强制括号"
proximity:
  unordered: "NEAR/{n}"              # 无序（chronic NEAR/3 pain）
  ordered: "NEXT/{n}"                # 有序（needle NEXT/3 program*）
  n_family: "gap_plus_one"          # ★ embase.com 属 gap+1 家族（proximity_table §5.1 + A1 §2.1）——与 WoS 的同名 NEAR/n（gap）不同族
  field_limit: []
  constraints: ["must_parenthesize_operands"]   # 邻近两侧词/词组必须用括号包住否则报错
truncation:
  multi_char: "*"                    # 零或多字符（pharmaco*）
  single_char: "?"                   # 恰一字符（wom?n）
  zero_or_one: "$"                   # ★ $ = 零或一字符（group$→group/groups，不含 grouping）——与 Ovid $=截词相反
  min_chars_before: null
  phrase_truncation: "forbidden"     # 短语搜索不支持截词
phrase:
  quote: "''"                        # ★ 单引号作短语：'heart failure'
  exception: "短语搜索不支持截词；单引号是 embase.com 的短语标记（区别于 WoS/Scopus 双引号）"
controlled_vocab:
  name: "Emtree"
  explode: "/exp  (爆炸，含下位词)"
  no_explode: "/de  (不爆炸，仅该词，如 'botany'/de)"
  major: "/mj  (主要主题) ; /exp/mj 组合 ; /br = as broad as possible（映射+爆炸+全字段自由词）"
  subheading: "floating subheading 或 /exp/mj 组合"
  verification: llm_suggest_only     # Emtree 无免费查表 API
line_search:
  supported: true
  syntax: "query numbers（Search History 逐行组合）"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: "https://www.embase.com/#advancedSearch"
  note: "登录墙：实测 HTTP 200 但为 hash 路由 SPA 外壳，出结果需鉴权。URL 结构已考证，执行待机构账号；交付=可粘贴检索式；绝不构造绕登录 URL。"
source_url:
  - "https://www.elsevier.support/embase/answer/how-do-i-search-in-embase"
  - "https://supportcontent.elsevier.com/RightNow%20Next%20Gen/Embase/Webinar_Embase_Intro_20170823.pdf"
verified_date: "2026-07-16"
gotchas:
  - "★同库不同宿主：embase.com（:ti / NEAR-NEXT / /exp）与 Ovid（.ti. / adjN / exp .../）语法完全不通用——见 embase_ovid.md（D-21）"
  - "★$ 在 embase.com = 零或一字符（group$→group/groups），非截词；与 Ovid $=截词相反（A-4 跨库陷阱）"
  - "邻近两侧词/词组必须用括号包住否则报错：'age AND (diabetes NEAR/5 therapy)' 对"
  - "NEAR/n 属 gap+1 家族（与 WoS 同名 NEAR/n 的 gap 不同族）——n 值必须查 proximity_table，勿手算（A-3）"
  - "短语用单引号 'heart failure'（非双引号）；短语搜索不支持截词"
  - "Emtree 无免费查表 API → 每个 :de/受控词标 llm_suggest_only，待人工核（A-6）"
hosts_note:
  summary: "Embase 有 embase.com（本卡，Elsevier 原生）与 Ovid（embase_ovid.md）两大宿主，语法迥异，须各建卡（D-21）。Emtree 受控词表两宿主共享，但字段码/邻近/截词/爆炸语法完全不同。"
  ovid: "Embase-on-Ovid 用 Ovid 点码语法（.ti./.ab./.mp.、adjN gap+1、$/#/? 、exp 词/）——见 embase_ovid.md。"
```

## 证据与说明（prose）

### 范围与角色
Embase（Elsevier）在 embase.com 原生宿主上的语法卡。订阅登录墙 → 深链 **C 档**：R4 §2.8 实测 `https://www.embase.com/#advancedSearch` HTTP 200 但 hash 路由 SPA 外壳，出结果需鉴权 → 交付=可粘贴检索式。

### 字段标签（官方 Embase Support）
后置冒号 `'值':字段`：`:ti` 题名、`:ab` 摘要、`:ti,ab` 题摘、`:kw` 作者关键词、`:ti,ab,kw` 题摘关键词、`:de` 叙词(Emtree)、`:py` 出版年。多字段逗号连（`'vaccine':ti,ab,kw`）。

### 布尔 / 邻近（官方）
`AND` `OR` `NOT` `NEAR` `NEXT`。**`NEAR/n`**（无序，`chronic NEAR/3 pain`）、**`NEXT/n`**（有序，`needle NEXT/3 program*`）。**硬约束：邻近两侧词/词组必须用括号包住否则报错**（`age AND (diabetes NEAR/5 therapy)` 对；`((hip OR back) NEAR/3 (pain OR ache)):ti,ab,kw` 可嵌套截词与字段限定）。**★邻近族归属**：embase.com 属 `gap_plus_one` 家族（proximity_table §5.1 + A1 §2.1 定点核实归 "Cochrane/Embase.com 系"）——与 WoS 同名 `NEAR/n`（gap 家族）**不同族**，n 值必须经 proximity.py 查表换算，绝不手算（A-3）。

### 截词 / 短语（官方）
`*` = 零或多字符（`pharmaco*`）；`?` = **恰一字符**（`wom?n`）；**`$` = 零或一字符**（`group$`→group/groups，不含 grouping）——**与 Ovid 的 `$`=截词含义相反**，头号跨库陷阱。短语用**单引号** `'heart failure'`（区别于 WoS/Scopus 双引号）；短语搜索不支持截词。

### 受控词表 Emtree（`llm_suggest_only`）
`/exp` 爆炸（含下位词）、`/de` 不爆炸（仅该词，`'botany'/de`）、`/mj` 主要主题、`/exp/mj` 组合、`/br`（as broad as possible：映射+爆炸+全字段自由词）。Quick Search 自动把词映射 Emtree。**Emtree 无免费查表 API** → 受控词标 `llm_suggest_only`，每词待人工核，绝不 fake-verify（A-6）。

### 深链（C 档）
`https://www.embase.com/#advancedSearch` 实测 HTTP 200（hash 路由 SPA 外壳）。URL 结构已考证，执行待机构账号；只观测不绕墙（C-14）。
