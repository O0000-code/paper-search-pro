# ClinicalTrials.gov (Essie / API v2)

> 语法卡 · 统一字段格式（§13 spec §4）。免费无墙注册库；MECIR C27 对干预类 SR 强制。
> **深链/语法均 live 实测**（curl，2026-07-16，见本卡末「实测证据」表）。语法主张附官方文档 URL。

```yaml
platform: "ClinicalTrials.gov"
host: "NLM / clinicaltrials.gov"
database: "ClinicalTrials.gov 临床试验注册库（API v2 + Expert Search）"
access: free                          # 免费、无登录、无验证码
api:
  base: "https://clinicaltrials.gov/api/v2/studies"
  version: "2.0.5"                     # /api/v2/version 实测 apiVersion，dataTimestamp 2026-07-15
  format: "json (default) | csv"
  count_param: "countTotal=true"       # 返回顶层 totalCount（服务器端计数，机械可解析）
  page_param: "pageSize=N"
  fields_param: "fields=NCTId,BriefTitle,..."   # 裁剪返回字段
query_fields:                          # 每个 query.* 取一段 Essie 表达式（可布尔）
  term:    "query.term"                # Other terms / BasicSearch（跨 NCTId/标题/Condition/Intervention 等，带权重+同义词）
  cond:    "query.cond"               # Conditions or disease
  intr:    "query.intr"               # Intervention / treatment
  titles:  "query.titles"             # Title / acronym
  outc:    "query.outc"               # Outcome measure
  spons:   "query.spons"              # Sponsor / collaborator
  lead:    "query.lead"               # Lead sponsor
  id:      "query.id"                 # Study IDs (NCT number 等)
  patient: "query.patient"            # Patient / healthy-volunteer terms
  locn:    "query.locn"               # Location terms
filter_fields:                         # 结构化过滤（**非 Essie**，机制不同于 query.*）
  overallStatus: "filter.overallStatus=RECRUITING|COMPLETED|..."
  geo: "filter.geo=distance(lat,lon,radius)"
  ids: "filter.ids=NCT01234567,..."
  advanced: "filter.advanced=<Essie>"  # 结果集上再叠 Essie 过滤
field_tags:                            # Essie 不用后缀标签；字段由 query.<field> 或 AREA[] 指定
  target_field: "AREA[<SearchArea>]<term>"   # 例 AREA[ConditionSearch]diabetes
  search_areas_ref: "https://clinicaltrials.gov/api/v2/studies/search-areas"
boolean: {and: "AND", or: "OR", not: "NOT", case: "UPPERCASE-REQUIRED"}   # 实测：小写 or→1662 vs 大写 OR→35800（小写不是算符=静默错误）
precedence: ["搜索词/source算符(最高)", "NOT/context算符", "AND", "OR(最低)"]  # 官方文档；OR 结合最松→必须括号消歧
proximity:                             # Essie **无** NEAR/邻近/tilde 算符
  unordered: null
  n_family: null                       # 无位置算符 → 无 n 家族（跨卡结构一致：所有卡均暴露此键）
  note: "无位置算符；相邻用引号短语；放宽相邻用 EXPANSION[Relaxation]"
truncation:                            # Essie **无** */? 符号截词
  multi_char: null
  single_char: null
  note: "词形扩展由 EXPANSION 算符控制，非符号通配（未测出 * / ? 生效）"
phrase: {quote: "\"\"", note: "引号短语优先级高于 EXPANSION"}
essie_operators:                       # 高级算符（均 live 实测 HTTP 200，见卡末）
  AREA:      "AREA[<SearchArea>]<term>          # 限定检索区（区名见 search-areas）"
  EXPANSION: "EXPANSION[None|Term|Concept|Relaxation|Lossy]<term>   # 词扩展档；Concept=UMLS 同义词"
  COVERAGE:  "COVERAGE[FullMatch|StartsWith|EndsWith|Contains]<term>  # 字段内匹配范围"
  RANGE:     "AREA[<DateOrNumField>]RANGE[min,max]   # 数值/日期区间，支持 MIN/MAX 关键字"
  MISSING:   "AREA[<field>]MISSING              # 该区无值的记录"
  SEARCH:    "SEARCH[Location](AREA[LocationCity]X AND AREA[LocationState]Y)  # 上下文分组（同一地点内组配）"
controlled_vocab:
  name: null                           # 无 MeSH 式受控词表（自由文本注册库）
  server_side_expansion: "EXPANSION[Concept] 用 UMLS 同义词（服务器端），非用户提供受控词"
  verification: not_applicable         # 无用户端受控词需核验
line_search: {supported: false, note: "单条 Essie 表达式；无 #1 AND #2 集合行——组配写进同一表达式"}
special_chars_escape: null
deep_link:
  tier: "A"                            # A 档来自 API v2 端点（服务器端 totalCount，机械可验、可构造）
  url_kind: "api"                      # 主交付=API URL；人读 URL 见 ui_template
  api_template: "https://clinicaltrials.gov/api/v2/studies?query.cond={urlenc}&query.intr={urlenc}&query.term={urlenc}&countTotal=true"
  ui_template: "https://clinicaltrials.gov/expert-search?term={urlenc_essie}"   # 官方人读深链（粘 Essie 式）
  ui_template_alt: "https://clinicaltrials.gov/search?cond={urlenc}&intr={urlenc}&term={urlenc}"
  ui_render: "client-SPA"              # 人读 URL HTTP 200 但固定 94295B React 外壳→结果客户端渲染（严格判 B），但免费/无墙→仍作可点击链接交付
  verified_http: 200
  verified_date: "2026-07-16"
source_url:
  - "https://clinicaltrials.gov/find-studies/constructing-complex-search-queries"   # Essie 算符官方定义
  - "https://clinicaltrials.gov/data-api/api"                                        # REST API v2
  - "https://clinicaltrials.gov/api/v2/studies/search-areas"                         # 检索区/字段定义
verified_date: "2026-07-16"
gotchas:
  - "AND/OR/NOT 必须大写：小写 or 被当检索词（实测 OR=35800 vs or=1662）——静默改召回"
  - "OR 优先级最低，必须用括号：(a OR b) AND c ≠ a OR b AND c"
  - "无邻近/NEAR 算符；无 */? 符号截词（词扩展走 EXPANSION）"
  - "query.* 是 Essie 可检索字段；filter.* 是结构化过滤（两套机制，别混）"
  - "括号不配平 → HTTP 400 'inner bool query clause cannot be null'；未知 query.<field> → HTTP 400"
  - "MECIR C27：干预类 SR 强制检索本库"
  - "人读 /expert-search、/search URL 结果客户端渲染；机械取计数须走 /api/v2 端点"
```

## 证据与说明（prose）

### 范围与角色
ClinicalTrials.gov 是 NLM 运营的临床试验注册库，**免费、无登录、无验证码**。在 SR 语境下由 **MECIR C27** 规定为干预类系统综述的强制检索源（13 spec §1.1 补充建议 + C-17）。它同时提供 **REST API v2**（机器路径）与 **Expert Search**（人读 Essie 检索）两个入口，二者共享 Essie 检索引擎。

### Essie 布尔语法（官方文档 + live 实测）
- **布尔算符** `AND` / `OR` / `NOT`，**大小写敏感、必须大写**。实测：`diabetes OR metformin`（大写）→ totalCount 35800；`diabetes or metformin`（小写）→ 1662——小写 `or` 不被当算符，语义完全错位（静默降召回）。这是 linter L2 的实弹依据。
- **优先级**（官方，高→低）：搜索词/source 算符 → `NOT`/context 算符 → `AND` → `OR`。因 `OR` 结合最松，多概念组配**必须用括号**：`(metformin OR insulin) AND diabetes` 实测 13092，与无括号语义不同。
- **括号分组** + **引号短语**（`"diabetes mellitus"` 实测 32538；引号短语优先级高于 EXPANSION）。
- Essie **没有邻近/NEAR/tilde 算符**（官方文档全篇无 proximity；相邻由引号短语表达，放宽相邻用 `EXPANSION[Relaxation]`）；也**没有 `*`/`?` 符号截词**（词形扩展交给 `EXPANSION` 算符）。

### 字段区（query.* 与 AREA[]）
两种指定字段的方式：① API 参数 `query.cond`（Condition/疾病）、`query.intr`（干预）、`query.term`（Other terms，跨标题/Condition/Intervention 等加权检索）、`query.outc`/`query.spons`/`query.titles`/`query.locn`/`query.id`/`query.lead`/`query.patient`；② Essie 内 `AREA[<SearchArea>]<term>`（检索区清单见官方 `search-areas` 端点，实测返回 `BasicSearch` 区跨 NCTId/BriefTitle/OfficialTitle/Condition/InterventionName… 的权重定义）。字段区检索实测：`query.cond=diabetes` 24112；叠加 `query.intr=metformin` → 1834（字段区组配收窄，符合预期）。

**注意**：`query.*` 走 Essie 检索引擎；`filter.*`（`filter.overallStatus=RECRUITING` 实测 1957）是结果集上的**结构化过滤**，机制不同，勿把状态/地理过滤写进 Essie 布尔。

### 高级 Essie 算符（官方定义 + 逐个 live 实测 HTTP 200）
- `AREA[ConditionSearch]diabetes`（限定检索区）→ 24112
- `EXPANSION[Concept]"heart attack"`（UMLS 同义词扩展）→ 12538；`EXPANSION[None]cancer`（精确、不扩展）→ 77861。官方五档：**None**（原样，区分大小写/重音）/ **Term**（+复数、所有格、连字符、复合词变体）/ **Concept**（+UMLS 同义词，带轻微评分惩罚）/ **Relaxation**（放宽相邻，允许部分词匹配）/ **Lossy**。
- `COVERAGE[FullMatch]"diabetes mellitus"` → 21804。官方四档：**FullMatch**（须匹配字段全文）/ **StartsWith** / **EndsWith** / **Contains**。
- `AREA[StudyFirstPostDate]RANGE[2020-01-01,2021-01-01]` → 36720（数值/日期区间，支持 `MIN`/`MAX`）。
- `AREA[<field>]MISSING`（该区无值的记录）；`SEARCH[Location](AREA[LocationCity]Portland AND AREA[LocationState]Maine)`（上下文分组：把城市+州约束限定在同一个地点内）。

### 深链档位判定（实测定档 — 与 R4/13 spec 的精化）
**A 档判定成立，但 A 性来自 API v2 端点，不是人读网页**（此点区别于 PubMed/ERIC，后者人读网页本身即服务器端渲染）：
- **API v2 端点**：`GET /api/v2/studies?query.term=...&countTotal=true` → HTTP 200 + 顶层 `totalCount`（服务器端 JSON，完全机械可解析、可复测）。这是**真正的 A 档可构造/可验证深链**，等价于 PubMed 的 E-utilities `esearch`。deeplink.py 应构造并对其计数做核验。
- **人读 URL**：官方 `https://clinicaltrials.gov/expert-search?term=<Essie>`（及 `/search?cond=&intr=&term=`）→ HTTP 200，携带查询、浏览器内可用（免费/无登录/无验证码），**但返回固定 94295 字节 React SPA 外壳**（对 "diabetes AND metformin" 与 "cancer" 两查询字节完全相同）→ 结果**客户端渲染**。按 13 spec §1.1 严格定义属 **B 档**（URL 有效、结果客户端渲染）；因其免费无墙，仍作**可点击链接**交付给人读报告。
- **交付形态**：人读报告给可点击 `/expert-search?term=` 链接；机器/计数核验走 `/api/v2` 端点。合规：全程官方 URL，无墙可绕（C-14 天然满足）。

### 错误行为（linter/健壮性参考）
- 括号不配平 `(diabetes AND` → **HTTP 400** `Error parsing query in Other terms: inner bool query clause cannot be null`。
- 未知字段 `query.badfield=...` → **HTTP 400** ``query.badfield` is unknown parameter``。
- 合法查询恒 HTTP 200 + `totalCount`，便于机械判空/判错。

### 实测证据（curl，2026-07-16，全部 HTTP 200 除标注）
| # | 表达式 | 结果 | 证明 |
|---|---|---|---|
| 1 | `query.cond=diabetes` | totalCount 24112 | 基础连通 + countTotal |
| 2 | `query.term=diabetes AND metformin` | 2390 | AND 收窄 |
| 3 | `query.term=diabetes OR metformin` | 35800 | OR 扩召回 |
| 4 | `query.term=metformin NOT insulin` | 1913 | NOT 排除 |
| 5 | `query.term=(metformin OR insulin) AND diabetes` | 13092 | 括号分组 |
| 6 | `query.term="diabetes mellitus"` | 32538 | 引号短语 |
| 7 | `query.cond=diabetes & query.intr=metformin` | 1834 | 字段区组配 |
| 8 | 小写 `diabetes or metformin` | 1662 | **算符须大写**（vs #3 的 35800） |
| 9 | `AREA[ConditionSearch]diabetes` | 24112 | AREA |
| 10 | `EXPANSION[Concept]"heart attack"` | 12538 | EXPANSION |
| 11 | `COVERAGE[FullMatch]"diabetes mellitus"` | 21804 | COVERAGE |
| 12 | `AREA[StudyFirstPostDate]RANGE[2020-01-01,2021-01-01]` | 36720 | RANGE |
| 13 | `filter.overallStatus=RECRUITING`（+cond=diabetes） | 1957 | filter 独立于 query |
| 14 | `(diabetes AND`（不配平） | **HTTP 400** | 错误可判 |
| 15 | `query.badfield=diabetes` | **HTTP 400** | 未知字段可判 |

（以上为实测证据表；完整 curl 命令与响应存于开发档案。）
