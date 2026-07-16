# IEEE Xplore（IEEE，混合：基础检索免费/全文订阅）

> 语法卡 · 统一字段格式（13 spec §4）。基础检索对公众免费；深链 **B 档**（URL 有效但结果客户端渲染，`/rest/search` API 拒爬虫）。受控 Index Terms 无免费 API → `llm_suggest_only`。语法主张附官方 URL + verified_date。

```yaml
platform: "IEEE Xplore"
host: "IEEE / ieeexplore.ieee.org"
database: "IEEE Xplore Digital Library"
access: mixed                        # 基础检索免费 / 全文订阅
field_tags:                          # Command Search："字段名":值（字段名带引号+冒号）
  title: "\"Document Title\":"
  title_abstract: null               # Command Search 无题摘合并标签（Title 与 Abstract 分列）
  abstract: "\"Abstract\":"
  subject_heading: "\"Index Terms\":"   # IEEE controlled terms + author keywords
  author: "\"Authors\":"
  publication_title: "\"Publication Title\":"
  full_text: "\"Full Text Only\":"
  pub_type: null                     # 内容类型经 facet 过滤，非 command 标签
  subheading: null
  all: "default (Full Text .AND. Metadata)"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-conventional"
  precedence: "NEAR/ONEAR > NOT > AND > OR （括号覆盖；裸相邻词按 AND）"
proximity:
  unordered: "NEAR/{n}"              # 仅 Global 搜索栏与 Command Search 可用；Advanced 页不支持
  ordered: "ONEAR/{n}"              # 有序，前词须在前
  n_family: "gap"                    # 文档默认读法（terms within # words）；★未 payload 实测，见 gotchas
  field_limit: []
  constraints: ["command_search_only", "no_wildcard_with_NEAR", "advanced_page_unsupported"]
truncation:
  multi_char: "*"                    # 零/一/多字符（词首/中/尾）
  single_char: "?"                   # 单字符
  zero_or_one: null
  min_chars_before: 3                # 通配符至少 3 字符
  wildcard_cap: 8                    # 最多 8 个通配符；每串最多 25 个未用布尔分隔的词
  phrase_truncation: "n/a (引号内通配无效)"
phrase:
  quote: "\"\""                      # "exact phrase"；未加引号的多词按 AND
  exception: "默认词干扩展(stemming)+自动英美拼写；加引号关闭"
controlled_vocab:
  name: "IEEE Thesaurus / Index Terms（IEEE controlled terms + author keywords）"
  explode: null                      # 非强爆炸叙词表
  no_explode: "\"Index Terms\":<term>"
  major: null
  subheading: null
  verification: llm_suggest_only     # IEEE Thesaurus 无免费查表 API
line_search:
  supported: false
  syntax: "Command Search 用括号分组表达优先级；无经典 #1 AND #2 集合行"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "B"
  url_kind: "prefill"
  url_template: "https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={urlenc}"
  ui_render: "client-SPA (Angular)"
  verified_http: "200 (SPA 外壳)；/rest/search API -> 418（拒爬虫）"
  note: "URL 有效、预填检索式并触发搜索，但结果由前端 Angular 拉取；浏览器内公开可用（基础检索免费），脚本层取不到结果。不承诺脚本层直达。"
  verified_date: "2026-07-16"
source_url:
  - "https://ieeexplore.ieee.org/Xplorehelp/searching-ieee-xplore/command-search"
  - "https://ieeexplore.ieee.org/Xplorehelp/searching-ieee-xplore/"
verified_date: "2026-07-16"
gotchas:
  - "邻近 NEAR/# 与 ONEAR/# 仅 Global 搜索栏 / Command Search 可用，Advanced 页不支持"
  - "★* 不能用于全文检索、也不能与 NEAR/ONEAR 共用；通配须显式匹配全部字符（cable*→cabled 不→cabling）"
  - "通配约束：最多 8 个通配符、每串最多 25 个未用布尔分隔的词、通配符至少 3 字符"
  - "★NEAR/# 的 n 语义为文档默认读法（within # words = gap 家族），本轮未做 payload 实测；精度关键时 build 轮实测复核"
  - "深链 B 档：searchresult.jsp?queryText= 实测 200 但 SPA 外壳，结果客户端渲染；/rest/search 返回 418"
  - "Index Terms 无免费 API → llm_suggest_only，待人工核（A-6）"
```

## 证据与说明（prose）

### 范围与角色
IEEE Xplore（IEEE）计算机/电子/工程核心库。基础检索对公众免费、全文订阅。深链 **B 档**：R4 §2.4 实测 `searchresult.jsp?queryText=` HTTP 200 但返回 Angular SPA 外壳（预填检索式、结果前端拉取），`/rest/search` API 返回 418（拒爬虫）→ 浏览器内可用、脚本层取不到结果。

### Command Search 字段 / 布尔 / 邻近（官方）
**Command Search** 用 `"字段名":值`（字段名带引号+冒号）：`"Document Title":`、`"Authors":`、`"Abstract":`、`"Publication Title":`、`"Index Terms":`、`"Full Text Only":`。布尔 `AND`/`OR`/`NOT`；**`NEAR/#`（无序）、`ONEAR/#`（有序，前词须在前）仅 Global 搜索栏与 Command Search 可用，Advanced 页不支持**。优先级 `NEAR/ONEAR` > `NOT` > `AND` > `OR`，括号覆盖。**★n 语义**：文档默认读法为 "terms within # words"（gap 家族），但本轮未做 payload 实测（IEEE 非 proximity_table 家族成员）——精度关键时 build 轮实测复核。

### 截词 / 短语（官方，约束密集）
`*` = 零/一/多字符（词首/中/尾）；`?` = 单字符。**约束：`*` 不能用于全文检索、也不能与 `NEAR`/`ONEAR` 共用**；**通配须显式匹配全部字符**（`cable*`→cabled 不→cabling，因无 e 可匹配）；**最多 8 个通配符、每串最多 25 个未用布尔分隔的词、通配符至少 3 字符**。`"exact phrase"` 关闭默认词干扩展；未加引号多词按 AND。

### 受控词表（`llm_suggest_only`）
IEEE Thesaurus / `"Index Terms"`（含 IEEE controlled terms + author keywords），非强爆炸叙词表。**无免费查表 API** → `llm_suggest_only`，待人工核（A-6）。

### 深链（B 档）
`searchresult.jsp?queryText=<URL编码>` 实测 200（SPA 外壳）；`/rest/search` 418。浏览器内公开可用（基础检索免费），脚本层取不到结果；不承诺脚本层直达。
