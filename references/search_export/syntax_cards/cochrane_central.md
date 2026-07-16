# Cochrane Library / CENTRAL（Wiley，混合：摘要免费/全文订阅）

> 语法卡 · 统一字段格式（13 spec §4）。**★转换修正：深链 tier=B**（主 Agent 亲测 419 推翻 R4 的 200，12 号 E 组；13 spec §1.1/§5.4）——不进 A 档 deeplink 构造器，build 轮浏览器实测通过再升 A。受控词 MeSH，但本卡集受控词核验轨仅 pubmed/eric 标 free_api → 本卡 `llm_suggest_only`。语法主张附官方 URL + verified_date。

```yaml
platform: "Cochrane Library / CENTRAL"
host: "Wiley / cochranelibrary.com"
database: "CENTRAL (Cochrane Central Register of Controlled Trials) + CDSR"
access: mixed                        # 摘要免费 / 全文订阅
field_tags:                          # 后置冒号：词:码
  title: ":ti"
  title_abstract: ":ti,ab"
  keyword: ":kw"                     # 含 MeSH 但不爆炸
  subject_heading: "[mh]"           # Search Manager 中 MeSH 检索式必须放方括号
  author: ":au"
  source: ":so"
  pub_type: ":pt"                    # 仅 CENTRAL
  accession: ":an"                   # 入藏号，可 (Pubmed):an / (Embase):an 按来源库限定
  doi: ":doi"
  cochrane_topic: ":tp"
  subheading: "MeSH 副主题（MeSH 浏览器内选定副主题码）"
  all: "缺省 = Title/Abstract/Keywords"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "case-insensitive"
  precedence: "括号嵌套"
proximity:
  unordered: "NEAR/{n}"             # 无序，间隔 ≤n
  ordered_adjacent: "NEXT"          # 相邻同序
  n_family: "gap_plus_one"         # ★ Cochrane 属 gap+1 家族（proximity_table §5.1 + A1 §2.1 归 "Cochrane/Embase.com 系"）
  field_limit: []
  constraints: ["phrase_no_truncation: 需变体时改用 NEXT"]
truncation:
  multi_char: "*"                    # 零或多字符
  single_char: "?"                   # 恰一字符（wom?n）
  zero_or_one: null
  min_chars_before: null
  phrase_truncation: "forbidden"     # 精确短语不支持通配/截词
phrase:
  quote: "\"\""                      # 精确短语（不支持通配/截词）
  exception: "短语不支持截词——需要变体时改用 NEXT"
controlled_vocab:
  name: "MeSH (via Search Manager)"
  explode: "MeSH 浏览器选词后可 explode（含下位）；:kw 含 MeSH 但不允许爆炸"
  no_explode: "单个 MeSH（不勾 explode）"
  major: "MeSH 浏览器内可限主要主题"
  subheading: "MeSH 副主题（浏览器内选定副主题码）"
  verification: llm_suggest_only     # 见 prose：MeSH 存在性可经 NCBI 免费交叉核，但本卡集核验轨仅 pubmed/eric 标 free_api；且 CENTRAL 的 MeSH 覆盖不完整（存在≠有效）
line_search:
  supported: true
  syntax: "#1 AND #2  (Search Manager 专家多行检索，每行成集合编号；支持插入行/Append/孤儿行检测)"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "B"                          # ★修正：R4 记 200(A)，主 Agent 亲测 419 → 降 B 待浏览器验证
  url_kind: "prefill"
  url_template: "https://www.cochranelibrary.com/search?q={urlenc}"    # 用 /search?q=，不带 /en/
  verified_http: "非 200（curl 层 419/302 皆时点观测到，Bot 拦截/会话预检）；B 档，build 轮浏览器实测再议升 A"
  note: "★转换修正（12 号 E 组）：R4 §2.3 记 /search?q= HTTP 200（服务器端渲染，判 A），但主 Agent 亲测返回 419 → 13 spec §1.1/§5.4 降 B 档、不进 A 档 deeplink 构造器，build 轮浏览器实测通过再升 A。另坑：/en/search?...&cookiesEnabled 触发 412 cookie 预检环——须用 /search?q= 不带 /en/。摘要免费/全文订阅，浏览器内可用。"
  verified_date: "2026-07-16"
source_url:
  - "https://www.cochrane.org/products-and-services/cochrane-library"
  - "https://www.cochrane.de/sites/cochrane.de/files/uploads/CochraneLibrary_NewSearchGuide.pdf"
  - "https://epoc.cochrane.org/sites/epoc.cochrane.org/files/uploads/Resources-for-authors2017/database_syntax_guide.pdf"
verified_date: "2026-07-16"
gotchas:
  - "★深链 B 档（非 A）：主 Agent 亲测 419 推翻 R4 的 200；/en/search 路径另触发 412 cookie 墙——用 /search?q= 不带 /en/"
  - "A-7：CENTRAL 禁叠加 RCT / 研究设计过滤器（CENTRAL 本身即对照试验库，加设计过滤器徒损召回）"
  - "NEAR/n 属 gap+1 家族（与 WoS 同名 NEAR/n 的 gap 不同族）——n 值查 proximity_table，勿手算（A-3）"
  - "MeSH 检索式在 Search Manager 中必须放方括号 [mh]；:kw 含 MeSH 但不允许爆炸"
  - "CENTRAL 记录常来自 PubMed/Embase，MeSH 覆盖不完整 → 必须叠自由词（存在≠有效）"
  - "精确短语不支持截词；需要词形变体时改用 NEXT"
hosts_note:
  summary: "Cochrane Library 是 Wiley 平台，含 CENTRAL（对照试验注册）与 CDSR（系统综述）。Search Manager 是专家多行检索界面。深链混合访问（摘要免费/全文订阅），本轮判 B 档待浏览器验证。"
```

## 证据与说明（prose）

### 范围与角色
Cochrane Library（Wiley）的 CENTRAL 是对照试验注册库，SR 检索必备。混合访问（摘要免费/全文订阅）。**深链档位——本卡集的转换修正点**：R4 §2.3 实测 `https://www.cochranelibrary.com/search?q=` HTTP 200 size 101250、服务器端渲染含 `search-results-template`，据此 R4 判 A 档；**但主 Agent 亲测该 URL 返回 419**（12 号 E 组已证伪防回潮），故 13 spec §1.1 深链表 + §5.4 将 Cochrane **降为 B 档、不进 A 档 deeplink 构造器**，build 轮浏览器实测通过再升 A。另一路径坑：`/en/search?...&cookiesEnabled` 触发 **412** cookie 预检重定向环——须用 `/search?q=` 不带 `/en/`。

### 字段标签（官方 Search Guide）
后置冒号 `词:码`：`:ti`/`:ab`/`:kw`（含 MeSH 但不爆炸）/`:au`/`:so`/`:pt`（仅 CENTRAL）/`:doi`/`:an`（入藏号，可 `(Pubmed):an`/`(Embase):an` 按来源库限定）/`:tp`（Cochrane 主题）。

### 布尔 / 邻近（官方）
`AND` `OR` `NOT`；**`NEAR/n`**（无序，间隔 ≤n）、**`NEXT`**（相邻同序）。**★邻近族**：Cochrane 属 `gap_plus_one` 家族（proximity_table §5.1 + A1 §2.1 定点核实归 "Cochrane/Embase.com 系"）——与 WoS 同名 `NEAR/n`（gap）**不同族**，n 值经 proximity.py 查表换算，勿手算（A-3）。**短语搜索不支持截词——需要变体时改用 `NEXT`**。

### 截词 / 短语
`*` = 零或多字符；`?` = 恰一字符。`"..."` 精确短语（不支持通配/截词）。

### 受控词表 MeSH（`llm_suggest_only`——见下）
Search Manager 里 **MeSH 检索式必须放方括号** `[mh]`；`:kw` 含 MeSH 但不允许爆炸；MeSH 按钮进 MeSH 浏览器选词加入 Search Manager。**为何标 `llm_suggest_only` 而非 `free_api`**：(1) 本卡集受控词核验轨按设计仅在 **pubmed/eric** 卡标 `free_api`（MeSH 存在性技术上可经 NCBI E-utilities 免费交叉核，可作 vocab_verify.py 的可选软交叉核，但本卡默认状态不 fake-verify）；(2) **CENTRAL 记录常来自 PubMed/Embase，MeSH 覆盖不完整**——即便某 MeSH 存在，也未必被 CENTRAL 记录标引，故存在≠有效，**必须叠自由词**。

### 关键方法学约束（A-7）
**CENTRAL 禁叠加 RCT / 研究设计过滤器**——CENTRAL 本身即对照试验库，再加设计过滤器只损召回不增精度（linter L9 抓 CENTRAL+filter 共现）。

### 行式检索 / 深链（B 档）
**Search Manager**（专家多行检索）支持逻辑算符、字段标签、嵌套、通配；每行成集合编号，`#1 AND #2` 组合；支持插入行、Append、孤儿行检测。深链 B 档：`/search?q=` 亲测 419（待浏览器验证），免费摘要/浏览器内可用；只观测不绕墙（C-14）。
