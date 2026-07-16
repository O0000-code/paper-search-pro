# ERIC（IES/教育部，免费官方站 eric.ed.gov）

> 语法卡 · 统一字段格式（13 spec §4）。免费官方政府站；深链 **A 档**（`?q=` 实测 HTTP 200、服务器端渲染，最干净的开放深链之一）。受控 ERIC Descriptors 经 IES/eric.ed.gov Thesaurus 免费核验（`free_api`）。此卡记免费官方站；订阅宿主（ERIC-on-EBSCO/Ovid/ProQuest）语法见对应卡。

```yaml
platform: "ERIC"
host: "IES / eric.ed.gov"
database: "ERIC (Education Resources Information Center)"
access: free
field_tags:                          # 字段:值（前置冒号式）
  title: "title:"
  title_abstract: null               # 免费站无题摘合并标签；官方建议少用字段限定、不限定召回更全
  abstract: "abstract:"
  subject_heading: "descriptor:"      # ERIC Thesaurus 受控叙词
  subject: "subject:"
  author: "author:"
  source: "source:"
  pub_type: null                     # 文献类型经 facet 过滤，非字段标签
  subheading: null
  all: "unfielded（默认跨题名/描述符/摘要匹配并变体扩展，官方主推）"
boolean:
  and: "AND"
  or: "OR"
  not: "NOT"
  case: "uppercase-conventional"
  precedence: "括号分组（(teacher education) AND (minority)）"
proximity:
  unordered: null                    # ★ 免费站邻近算符支持弱/不稳定（行为异于 EBSCO/ProQuest 宿主）
  n_family: null
  field_limit: []
  constraints: ["free_site_proximity_unreliable_defer_to_host"]
truncation:
  multi_char: "*"                    # 词尾截词（learn*→learn/learning/learner/learned）
  single_char: null
  zero_or_one: null
  min_chars_before: null
  auto_stemming: "默认自动词干扩展（read→reading/reads/readers）"
  phrase_truncation: "n/a"
phrase:
  quote: "\"\""                      # 精确短语；描述符短语加引号 descriptor:"early childhood education"
  exception: "免费站默认自动词干扩展；引号做精确短语"
controlled_vocab:
  name: "ERIC Thesaurus Descriptors（受控叙词）"
  explode: "从 Thesaurus 页选词可 Explode（含下位描述符）"
  no_explode: "descriptor:\"single descriptor\"（字段限定，仅该词）"
  major: "Thesaurus 内可限主要描述符"
  subheading: null
  verification: free_api             # eric.ed.gov Thesaurus / IES ERIC API 核 descriptor 存在性
line_search:
  supported: false
  syntax: "免费站无经典 #1 AND #2 集合行（该能力在 EBSCO/Ovid/ProQuest 宿主）；靠单式布尔 + 二次过滤"
  history_cap: null
special_chars_escape: null
deep_link:
  tier: "A"
  url_kind: "prefill"
  url_template: "https://eric.ed.gov/?q={urlenc}"
  field_url_example: "https://eric.ed.gov/?q=author%3Ayoung"    # 亦支持字段式 ?q=author:young
  verified_http: 200
  note: "免费政府站，最干净的开放深链之一；实测页面含 'of 27,020 results'（服务器端 HTML 计数）。"
  verified_date: "2026-07-16"
source_url:
  - "https://eric.ed.gov/?searchtips"       # Advanced Search Tips
  - "https://eric.ed.gov/?ti=all"           # ERIC Thesaurus
  - "https://ospguides.ovid.com/OSPguides/ericdb.htm"   # 订阅宿主 ERIC-on-Ovid
verified_date: "2026-07-16"
gotchas:
  - "官方建议少用字段限定——不限定字段常召回更全（引擎自动跨题名/描述符/摘要匹配并变体扩展）"
  - "★免费站邻近算符支持弱/不稳定（NEAR/n 行为异于 EBSCO/ProQuest 宿主）——邻近以订阅宿主为准"
  - "* 是词尾截词；默认自动词干扩展（read→reading/reads/readers）"
  - "深链 A 档：?q= 实测 200，服务器端渲染结果计数；亦支持字段式 ?q=author%3Ayoung"
  - "受控词 ERIC Descriptors 经 IES/eric.ed.gov Thesaurus 免费核（free_api，本卡集仅 pubmed/eric 可机械核验）"
hosts_note:
  summary: "ERIC 有免费官方站（本卡，eric.ed.gov）与订阅宿主（ERIC-on-EBSCO 用 EBSCO 语法、ERIC-on-Ovid 用 Ovid 语法、ERIC-on-ProQuest 用 ProQuest 语法）。ERIC Descriptors 受控词跨宿主共享；免费站邻近弱、以订阅宿主为准（D-21）。"
  ebsco: "ERIC-on-EBSCO：前置两字母码（TI/AB/DE/SU）、Nn/Wn（gap）、*,?,# 通配、S1/S2 历史——同 psycinfo_ebsco.md 引擎。"
  ovid: "ERIC-on-Ovid：Ovid 点码（.ti./.ab./.mp.）、adjN（gap+1）、$/#/?、exp 词/——同 embase_ovid.md 引擎。"
```

## 证据与说明（prose）

### 范围与角色
ERIC（IES/美国教育部）教育学核心库；本卡记**免费官方站 eric.ed.gov**（订阅宿主 EBSCO/Ovid/ProQuest 语法见对应卡）。深链 **A 档**：R4 §2.2 实测 `https://eric.ed.gov/?q=<URL编码>` HTTP 200、页面含 "of 27,020 results"（服务器端 HTML 计数）——**最干净的开放深链之一**。

### 字段 / 布尔 / 邻近（官方）
`字段:值`（前置冒号）：`author:`、`title:`、`source:`、`descriptor:`、`abstract:`、`subject:`。**官方明确建议少用字段限定**——不限定字段常召回更全（含变体）。布尔 `AND`/`OR`/`NOT`（Advanced 支持），**官方主推简单词串**（引擎自动跨题名/描述符/摘要匹配并变体扩展）。**免费站邻近算符支持弱/不稳定**（`NEAR/n` 在 eric.ed.gov 行为异于 EBSCO/ProQuest 宿主，务必以宿主为准）→ 本卡 `proximity.unordered=null`。

### 截词 / 短语（官方）
`*` = 词尾截词（`learn*`→learn/learning/learner/learned）；**默认自动词干扩展**（`read`→reading/reads/readers）。`"..."` 精确短语；描述符短语加引号（`descriptor:"early childhood education"`）。

### 受控词表 ERIC Descriptors（`free_api` — 本卡集仅 pubmed/eric 可机械核验）
ERIC Thesaurus 的 Descriptors（受控叙词）；从 Thesaurus 页选词、可 Explode（含下位描述符）；`descriptor:` 字段限定。**受控词经 eric.ed.gov Thesaurus / IES ERIC API 免费核 descriptor 存在性**（§5.3：Count≥1→verified；Count=0→降级自由词 + 复核点）。这是本卡集除 PubMed(MeSH) 外唯一的 `free_api` 受控词轨。

### 深链（A 档）
`https://eric.ed.gov/?q=<URL编码>` 实测 200，服务器端渲染结果计数；亦支持字段式 `?q=author%3Ayoung`。deeplink.py 对 ERIC 构造并核验此 URL。
