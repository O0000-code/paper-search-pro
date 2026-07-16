# PubMed（NLM，免费）

> 语法卡 · 统一字段格式（13 spec §4）。免费无墙；深链 **A 档**（`?term=` + E-utilities `esearch`，均实测 HTTP 200）。受控词 MeSH 经 NCBI 免费 API 核验（`free_api`）。语法主张附官方文档 URL + verified_date。

```yaml
platform: "PubMed"
host: "NLM / pubmed.ncbi.nlm.nih.gov"
database: "MEDLINE/PubMed"
access: free
field_tags:                          # 后置方括号：词[标签]
  title: "[ti]"
  title_abstract: "[tiab]"
  text_word: "[tw]"
  subject_heading: "[mh]"            # MeSH（默认爆炸）
  subject_heading_major: "[majr]"    # MeSH 主要主题
  subheading: "[sh]"                 # MeSH 副主题
  pub_type: "[pt]"
  author: "[au]"
  first_author: "[1au]"
  last_author: "[lastau]"
  journal: "[ta]"
  pub_date: "[dp]"
  language: "[la]"
  affiliation: "[ad]"
  all: "[all]"
  pmid: "[pmid]"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-required"
  precedence: "left-to-right (no standard precedence) — use parentheses"
proximity:
  unordered: "\"{terms}\"[{field}:~{n}]"   # 必须加引号、词序无关
  n_family: "gap"                    # n = 词间最大间隔词数（§5.1 pubmed n_semantics=gap）
  field_limit: ["ti", "tiab", "ad"]
  constraints: ["quotes_required", "phrase_exclusive", "no_truncation", "closes_ATM"]
truncation:
  multi_char: "*"                    # 零或多字符
  single_char: null
  zero_or_one: null
  min_chars_before: 4                # 截词前至少 4 字符（colo* 可，co* 不可）
  phrase_truncation: "discouraged"   # * 会关闭邻近与自动词映射(ATM)
phrase:
  quote: "\"\""
  exception: "短语不在短语索引中则引号被忽略（'Quoted phrase not found in phrase index'）；引号短语不触发含 MeSH 的自动映射"
controlled_vocab:
  name: "MeSH"
  explode: "[mh]  (默认爆炸，含下位 MeSH)"
  no_explode: "[mh:noexp]"
  major: "[majr]"
  subheading: "\"term/subheading\"  (例 \"zika virus/analysis\")"
  verification: free_api             # NCBI E-utilities esearch.fcgi?db=mesh 核存在性
line_search:
  supported: true
  syntax: "#1 AND #2"                # Advanced Search History
  history_cap: 100
special_chars_escape: null
deep_link:
  tier: "A"
  url_kind: "prefill"
  url_template: "https://pubmed.ncbi.nlm.nih.gov/?term={urlenc}"       # 方括号编码为 %5B%5D
  api_template: "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={urlenc}"
  verified_http: 200
  verified_date: "2026-07-16"
source_url:
  - "https://pubmed.ncbi.nlm.nih.gov/help/"
  - "https://pubmed.ncbi.nlm.nih.gov/help/#search-tags"
  - "https://www.ncbi.nlm.nih.gov/books/NBK25501/"     # E-utilities
verified_date: "2026-07-16"
gotchas:
  - "AND/OR/NOT 必须大写；PubMed 左到右处理、无标准优先级 → 靠括号"
  - "截词 * 前至少 4 字符；* 会关闭自动词映射(ATM)：colo* 被译为 \"colo*\"[All Fields]，不映射 MeSH（实测）"
  - "邻近 [tiab:~N] 必须加引号、与截词互斥、词序无关；引号内布尔词/停用词按检索词处理"
  - "引号短语不触发 MeSH 自动映射；短语不在索引中则引号被忽略"
  - "[mh] 默认爆炸；不爆炸用 [mh:noexp]；仅主要主题 [majr]"
```

## 证据与说明（prose）

### 范围与角色
PubMed 是 NLM 运营的 MEDLINE/PubMed 免费检索入口，**免费、无登录、无验证码**。深链 **A 档**：既有网页 `?term=` 深链，也有 E-utilities `esearch.fcgi` 编程端点，两者均服务器端返回结果/计数，可机械构造与复测。

### 字段标签（官方）
后置方括号 `词[标签]`。核心：`[tiab]` 题名+摘要、`[ti]` 题名、`[tw]` text word、`[mh]` MeSH、`[majr]` MeSH 主要主题、`[sh]` MeSH 副主题、`[au]`/`[1au]`/`[lastau]` 作者、`[ta]` 期刊、`[dp]` 出版日期、`[pt]` 文献类型、`[la]` 语言、`[ad]` 单位、`[all]` 全字段、`[pmid]`。标签必须放方括号内；字段标签大小写不敏感。

### 布尔 / 邻近（官方 + live 实测）
`AND` `OR` `NOT` **必须大写**；**左到右处理**（不遵循标准优先级，靠括号）。邻近 `"词1 词2"[字段:~N]`：字段限 `[ti]`/`[tiab]`/`[ad]`，N=词间最大间隔（**gap 家族**），**词序无关、必须加引号、与截词互斥**。实测（R4 §2.1C）：`"sleep therapy"[tiab:~3]` → Count 3974 vs 精确短语 `"sleep therapy"[tiab]` → 526，邻近版召回更大，证明按文档生效且词序无关。

### 截词 / 短语（官方 + live 实测）
`*` = 零或多字符；**截词前至少 4 字符**（`colo*` 可、`co*` 不可）；可多截词（`organi*ation*`）。实测（R4 §2.1D）：`colo*` → QueryTranslation `"colo*"[All Fields]`，即 **`*` 关闭自动词映射 ATM**（不再映射 MeSH）。无单字符通配。短语 `"kidney allograft"`：若不在短语索引中，引号被忽略并提示 "Quoted phrase not found in phrase index"；引号短语不触发含 MeSH 的自动映射。

### 受控词表 MeSH（`free_api` — 本卡集仅 pubmed/eric 可机械核验）
`[mh]` 默认爆炸（含下位 MeSH）；`[mh:noexp]` 不爆炸；`[majr]` 仅主要主题；副主题 `"zika virus/analysis"`。**受控词经 NCBI E-utilities `esearch.fcgi?db=mesh&term="<label>"[MeSH Terms]` 免费核存在性**（Count≥1 且有 `<Id>` → verified + descriptor_ui；Count=0 → 降级为 `[tiab]` 自由词 + 复核点）。优先复用 KG 已回填的真实论文 MeSH（Yale-MeSH-Analyzer 式 grounding），比凭记忆更可锚定。

### 深链（A 档，实测）
- 网页：`https://pubmed.ncbi.nlm.nih.gov/?term=<URL编码>`（方括号→`%5B%5D`）——R4 §2.1A 实测 HTTP 200 size 256265，返回完整结果页。
- 编程（最可靠）：`esearch.fcgi?db=pubmed&term=<URL编码>` → 返回 `<Count>` 与 `<QueryTranslation>`。R4 §2.1B 实测 `"working memory"[tiab] AND children[mh]` → Count 6359，`children[mh]` 被自动映射为规范 `"child"[MeSH Terms]`，证明字段标签生效。deeplink.py 构造并对计数做核验。
