# ACM Digital Library（ACM，混合：检索免费/全文订阅）

> 语法卡 · 统一字段格式（13 spec §4）。检索对公众免费；深链 **B 档**（官方端点，curl 被 Cloudflare 拦，浏览器可用）。**★无邻近算符** → 跨库翻译时降级为 AND/短语。CCS 分类是过滤 facet，非可爆炸叙词表 → 受控词 `not_applicable`。语法主张附官方 URL + verified_date。

```yaml
platform: "ACM Digital Library"
host: "ACM / dl.acm.org"
database: "ACM Full-Text Collection + ACM Guide to Computing Literature"
access: mixed                        # 检索免费 / 全文订阅
field_tags:                          # Edit Query 语法：字段:(值)
  title: "Title"
  title_abstract: null               # Title 与 Abstract 分列，无合并标签
  abstract: "Abstract"
  keyword: "Keyword"
  author: "Author"
  subject_heading: null              # CCS 分类是 facet，非检索式层叙词
  pub_type: null
  subheading: null
  all: "AllField"                    # 全字段（深链参数名 AllField=）
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-required"
  precedence: "默认词间 AND；括号分组"
proximity:
  unordered: null                    # ★ ACM UI 实质不提供邻近算符
  n_family: null
  fallback: "AND_or_phrase"          # 跨库翻译：ACM 无邻近 → 降级为 AND / 引号短语
  field_limit: []
  constraints: ["no_proximity_operator"]
truncation:
  multi_char: "*"                    # 无限字符截词（词尾/词中，不可词首）
  single_char: "?"                   # 单字符
  zero_or_one: null
  min_chars_before: null
  phrase_truncation: "forbidden"     # 引号短语内通配无效
phrase:
  quote: "\"\""                      # 精确短语；通配在引号内失效
  exception: "默认已开复数+词干；引号短语内通配无效"
controlled_vocab:
  name: "ACM CCS（Computing Classification System，分类 facet，非可爆炸叙词表）"
  explode: null                      # 检索式层无爆炸叙词语法
  no_explode: null
  major: null
  subheading: null
  verification: not_applicable       # 检索式层无受控词；CCS 仅作 facet 过滤
line_search:
  supported: false
  syntax: "无经典集合行；Advanced 多行 + Edit Query 手改布尔"
  history_cap: null
special_chars_escape: "反斜杠转义：+ - && || ! ( ) { } [ ] ^ \" ~ * ? : /（如 web \\-based 才字面搜连字符，否则 - 被当 NOT）"
deep_link:
  tier: "B"
  url_kind: "prefill"
  url_template: "https://dl.acm.org/action/doSearch?AllField={urlenc}"
  verified_http: "403（curl，Cloudflare bot 拦截）；真实浏览器内该 URL 可用"
  note: "官方文档化端点；curl 被 Cloudflare 拦（403），但浏览器内公开可用（检索免费，全文订阅）。不承诺脚本层直达。"
  verified_date: "2026-07-16"
source_url:
  - "https://libraries.acm.org/binaries/content/assets/libraries/new_acm-digital-library-user-guide.pdf"
  - "https://library-guides.ucl.ac.uk/ACM-Digital-Library/techniques-for-searching"
  - "https://refhunter.org/en/database_sheets/acm-digital-library"
verified_date: "2026-07-16"
gotchas:
  - "★ACM 无邻近算符（UI 未开放）→ 跨库翻译时 NEAR 须降级为 AND / 引号短语（proximity_table acm.fallback）"
  - "特殊字符须反斜杠转义：+ - && || ! ( ) { } [ ] ^ \" ~ * ? : /；未转义的 - 被当 NOT"
  - "通配 * 可词尾/词中、不可词首；引号短语内通配无效"
  - "布尔须大写；默认词间 AND；多字段靠 Advanced 多行 + Edit Query 手改布尔"
  - "深链 B 档：doSearch?AllField= 官方端点，curl 403（Cloudflare），浏览器内可用"
  - "CCS 分类是 facet 过滤，非检索式层可爆炸叙词 → 受控词 not_applicable"
```

## 证据与说明（prose）

### 范围与角色
ACM Digital Library（ACM）计算机核心库。检索对公众免费、全文订阅。深链 **B 档**：R4 §2.5 实测 `doSearch?AllField=` HTTP 403（Cloudflare bot 拦截），但真实浏览器内该官方端点可用。

### 字段 / 布尔 / 邻近（官方 + 权威转录）
Advanced Search 下拉选字段；Edit Query 语法 `字段:(值)`：`Title:(...)`、`Abstract:(...)`、`Keyword:(...)`、全字段 `AllField`（深链参数名）。多行自动 AND，可 Edit Query 改 OR。布尔 `AND`/`OR`/`NOT` **须大写**。**★邻近算符 UI 实质不提供**（Radboud 官方指引明记 "Proximity search is not available"；底层 Lucene 类引擎的 `~` 为特殊字符但 UI 未开放邻近）→ **跨库翻译时 ACM 无邻近，须降级为 AND/短语**（proximity_table `acm.fallback="AND_or_phrase"`）。

### 截词 / 短语 / 特殊字符转义（官方）
`*` = 无限字符截词；`?` = 单字符。**可用于词尾或词中，不可用于词首；引号短语内通配无效**。默认已开复数+词干。**特殊字符须反斜杠转义**：`+ - && || ! ( ) { } [ ] ^ " ~ * ? : /`（如 `web \-based` 才字面搜连字符，否则 `-` 被当 NOT）。

### 受控词表（`not_applicable`）
CCS（ACM Computing Classification System）分类可作过滤 facet，但**检索式层无爆炸叙词语法** → 生成器不向 ACM 检索串写入受控词，受控词状态标 `not_applicable`（同 WoS/Scopus/CT.gov 的无受控词轨）。

### 深链（B 档）
`https://dl.acm.org/action/doSearch?AllField=<URL编码>` — 官方端点，curl 403（Cloudflare），浏览器内可用；不承诺脚本层直达（C-14 天然满足：检索免费无墙）。
