# 万方 Wanfang（万方智搜，订阅）

> 语法卡 · 统一字段格式（13 spec §4）。中文原生库；深链 **B 档**（URL 有效但 Nuxt/Vue SPA 客户端渲染）。**无 `*`/`?` 通配**（靠精确 vs 模糊开关 + 英文双引号）；**无西式可爆炸叙词表 + 无位置算符** → 受控词 `not_applicable`、无邻近。语法主张附官方 URL + verified_date。

```yaml
platform: "万方 Wanfang"
host: "万方数据 / s.wanfangdata.com.cn"
database: "万方智搜（学术资源发现系统）"
access: subscription
field_tags:                          # 专业检索：字段:值 或 字段=值（: 与 = 等价、字段名大小写不敏感）
  title: "题名"                      # 别名：标题/题目/题/篇名/t/title
  title_abstract: null               # 无题摘合并标签
  abstract: "摘要"
  subject_heading: "主题"           # 非可爆炸叙词表
  keyword: "关键词"
  author: "作者"                     # 别名：Author
  journal: "刊名"
  pub_type: null                     # 资源类型可检索字段随类型不同（点『可检索字段』查看）
  subheading: null
  all: "一框式 PQ 检索表达式"
field_alias_note: "一字段多别名（题名=标题/题目/题/篇名/t/title）；每种资源类型可检索字段不同，点『可检索字段/展开』查看"
boolean:
  and: "and"                         # ★空格可代 AND（信息检索 and 本体 = 信息检索 空格 本体）
  or: "or"
  not: "not"
  case: "英文半角；字段名大小写不敏感"
  precedence: "not > and > or"
proximity:
  unordered: null                    # ★官方文档未开放位置/邻近算符
  n_family: null
  field_limit: []
  constraints: ["no_proximity_operator"]
truncation:
  multi_char: null                   # ★无 */? 词内通配（官方未开放）；* / + / ^ 检索优化后已废弃为普通检索词，非截词非算符（改用 and/or/not）
  single_char: null
  zero_or_one: null
  min_chars_before: null
  precise_vs_fuzzy: "靠『精确 vs 模糊』开关控制拆词：默认模糊(拆词)；加英文双引号转精确(不拆)"
  phrase_truncation: "n/a"
phrase:
  quote: "英文双引号 \"\""           # "信息资源检索" 整体精确匹配（不拆分）
  exception: "不加引号=模糊(拆分)；加英文半角双引号=精确(不拆)"
controlled_vocab:
  name: null                         # 无西式可爆炸叙词表
  explode: null
  no_explode: null
  major: null
  subheading: null
  interactive_expand: "高级检索提供『主题词扩展』(超级主题词表扩同义/下位) + 『中英文扩展』——属交互增强，非检索式语法"
  verification: not_applicable       # 无检索式层受控词可核
line_search:
  supported: true
  syntax: "高级检索多行逻辑组配（与/或/非）；专业检索直接写复合式；一框式支持 PQ 检索表达式"
  history_cap: null
special_chars_escape: "双引号/逻辑符须英文半角；字段名大小写不敏感"
deep_link:
  tier: "B"
  url_kind: "prefill"
  url_template: "https://s.wanfangdata.com.cn/paper?q={urlenc}"
  ui_render: "client-SPA (Nuxt/Vue, window.__NUXT__)"
  verified_http: 200
  note: "URL 有效、预填并前端拉结果；返回 window.__NUXT__ SPA 外壳，无服务器端结果 → 浏览器内可用、脚本层取不到结果。不承诺脚本层直达。"
  verified_date: "2026-07-16"
source_url:
  - "http://www.llas.cas.cn/xwzx/tzgg/202204/P020241229644157292759.pdf"
  - "https://library.zuel.edu.cn/_upload/article/files/16/da/a36893834ff8978060d5256a93b8/be1fd347-d276-49a0-8921-b25e6c17a1b8.pdf"
verified_date: "2026-07-16"
gotchas:
  - "★无 */? 词内通配（官方未开放；万方检索优化后 * / + / ^ 已废弃为普通检索词，非算符非截词，改用 and/or/not）——靠『精确 vs 模糊』开关：默认模糊(拆词)，加英文双引号转精确(不拆)"
  - "★无位置/邻近算符——跨库翻译时 NEAR 须降级为 and / 引号短语"
  - "空格可代 and；优先级 not > and > or（与西式常规一致但需注意 not 最高）"
  - "字段名大小写不敏感、一字段多别名（题名=标题/题目/篇名/t/title）；双引号/逻辑符须英文半角"
  - "深链 B 档：paper?q= 实测 200 但 Nuxt SPA 外壳，结果客户端渲染"
  - "无西式可爆炸叙词表；『主题词扩展』是交互增强非检索式语法 → 受控词 not_applicable"
```

## 证据与说明（prose）

### 范围与角色
万方智搜（万方数据，订阅）中文原生学术发现系统。深链 **B 档**：R4 §2.6 实测 `https://s.wanfangdata.com.cn/paper?q=<URL编码>` HTTP 200，返回 `window.__NUXT__` SPA 外壳（Nuxt/Vue，预填并前端拉结果）→ 浏览器内可用、脚本层取不到结果。

### 专业检索字段 / 布尔（官方说明）
字段式 `字段:值` 或 `字段=值`（`:` 与 `=` 等价、**字段名大小写不敏感**）。**一字段多别名**：`标题`/`题名`/`题目`/`题`/`篇名`/`t`/`title` 皆=题名；`作者`/`Author`；`主题`；`刊名`；`关键词`。**每种资源类型可检索字段不同**（点「可检索字段/展开」查看）。布尔 `and`（**空格可代 AND**）、`or`、`not`；**优先级 `not > and > or`**（`信息检索 and 本体` = `信息检索 空格 本体`）。

### 截词 / 短语（官方——无符号通配）
官方文档**未开放 `*`/`?` 式通配**；靠**精确 vs 模糊**开关控制拆词——默认**模糊**（拆词，`信息资源检索` 会拆），**加英文双引号 `"..."` 转精确**（整体匹配、不拆分）。双引号/逻辑符须**英文半角**。

### 邻近 / 受控词表（均无 → 降级）
**无位置/邻近算符**（proximity=null）——跨库翻译时 `NEAR` 须降级为 `and`/引号短语。**无西式可爆炸叙词表**——高级检索提供「主题词扩展」（基于超级主题词表扩同义/下位词）+「中英文扩展」，但属**交互增强非检索式语法** → 受控词状态标 `not_applicable`（同 CNKI/WoS/CT.gov 的无受控词轨）。

### 深链（B 档）
`paper?q=<URL编码>` 实测 200（Nuxt SPA 外壳，结果客户端渲染）；浏览器内可用，脚本层取不到结果；不承诺脚本层直达（C-14 天然满足）。
