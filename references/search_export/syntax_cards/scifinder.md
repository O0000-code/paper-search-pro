# SciFinder-n (CAS)

> 语法卡 · 统一字段格式（§13 spec §4）。
> **范围铁律（诚实边界，13 spec §6 Wave0 要求）**：本卡**只覆盖文本参考检索（Reference / text search）**的字段与算符。
> **结构式 / 子结构 / 反应式 / Markush 检索超出本功能范围**——PSP 的检索式导出不生成、也不声称支持化学结构类检索。
> 订阅墙 + CAS 使用条款如实标注。语法主张附 CAS 官方 Quick Reference Guide URL + verified_date。

```yaml
platform: "SciFinder-n (CAS)"
host: "CAS / scifinder-n.cas.org"
database: "CAplus / CAS Content Collection + MEDLINE（References 检索区）"
access: subscription                  # 全站登录墙；须 CAS 账号 + 接受使用条款
scope:                                # ★范围声明
  in_scope: "文本参考检索（References text search）"
  out_of_scope: "结构式/子结构/相似结构/反应式/Markush 检索（本功能不覆盖）"
field_tags:                           # References 高级检索字段（下拉选，非后缀标签）
  reference_fields: ["Author Name", "Journal / Publication Name", "Organization Name",
                     "Title", "Abstract/Keywords", "Concept", "Substances",
                     "Bioactivity Data", "Publication Year", "Document Identifier",
                     "Patent Identifier", "Publisher"]
  field_combine: "算符只在字段『之间』用；单个高级字段框『内』不支持布尔算符"
  field_cap: "最多 50 个高级检索字段（若同时用主检索框则 49 个）"
boolean: {and: "AND", or: "OR", not: "NOT", precedence: "OR → AND → NOT", group: "括号 ()"}
proximity: {supported: false, n_family: null, note: "文本参考检索无 NEAR/位置算符；相邻用引号短语；语义靠 CAS Lexicon 精确检索(Precision Search)"}
truncation:
  multi_char: "*"                     # 0 到任意个字符（内嵌 + 右截均可）
  single_char: "?"                    # 0 或 1 个字符（参考检索中）
  note: "官方例：polymorph* ；benzonorbornen? ；未列最小字符数限制"
phrase: {quote: "\"\"", note: "双引号=精确短语；但即便加引号，复数形式与索引 Concept 同义词仍可能被检出（Precision Search）"}
controlled_vocab:
  name: "CAS Lexicon（Concept 概念词）"
  mechanism: "Precision Search：检索 CAS Lexicon 中的 Concept 词会自动纳入其同义词；关键词间隐含 OR"
  explode: not_applicable             # 非 MeSH 式可爆炸叙词层级
  verification: llm_suggest_only       # 无免费公共 API 核 Concept 词存在性（CAS Common Chemistry API 只覆盖物质，非参考 Concept 且非本范围）
line_search: {supported: true, syntax: "检索历史自动存为脚本(script)，无条数上限、账号存续期不过期；可『合并当前与已存集合』"}
special_chars_escape: null
deep_link:
  tier: "C"                           # 全站登录墙，无公共/无状态深链
  url_kind: "paste_only"
  url_template: null
  delivery: "交付=可粘贴进 References 检索框的文本检索式本身"
  verified_date: "2026-07-16"
source_url:
  - "https://web.cas.org/marketing/academic/academic_kc_resources-english/SCIACDENGREF101245_SciFinder-Quick-Reference-Guide-Academic-A4.pdf"   # CAS 官方 Academic Quick Reference Guide
  - "https://web.cas.org/marketing/pdf/SCIGENENGREF101245-SciFinder-Quick-Reference-Guide-Commercial-A4.pdf"                                     # CAS 官方 Commercial Quick Reference Guide
verified_date: "2026-07-16"
gotchas:
  - "关键词间隐含 OR：裸敲一串词=各词 OR，易过宽——务必对核心词显式 AND / 加引号"
  - "引号短语不完全抑制同义/复数（Precision Search 仍会扩），要纯精确需注意"
  - "布尔算符不能写在单个高级字段框『内』，只在字段间用"
  - "AI/NLP 模式下引擎会自然语言重解析查询，行为异于纯布尔"
  - "CAS 使用条款禁止自动化脚本/批量抽取，单账号保留上限 5000 条——PSP 绝不脚本化 SciFinder，交付纯人工粘贴式"
  - "结构式/反应式检索超出本功能范围，卡内不提供"
```

## 证据与说明（prose）

### 范围与角色（诚实边界）
SciFinder-n（CAS，Chemical Abstracts Service）是化学/生物化学/材料/纳米等学科的核心库，含 References（CAplus + MEDLINE）、Substances（CAS REGISTRY）、Reactions（CASREACT）等检索区。**本卡只覆盖 References 文本检索**——即用关键词/字段检索文献题录的部分。SciFinder-n 的招牌能力「画结构式/子结构/相似结构/反应式/Markush 检索」**明确超出本功能范围**：PSP 的检索式导出是文本布尔检索式的跨库适配，不生成化学结构查询，也不声称能替代 SciFinder 的结构检索。此边界须在导出交付时如实标注（13 spec §6 Wave0）。

### 文本参考检索语法（CAS 官方 Quick Reference Guide）
- **布尔算符** `AND` / `OR` / `NOT`，**处理顺序 OR → AND → NOT**；用**括号**分组（官方例：`(flavor or odor) and menthol not cigarette`；`"pollution monitoring" and (polyethylene or polypropylene)`）。同义词通常用括号 + OR 分组。
- **通配符/截词**（reference searching）：`*` = 0 到任意个字符（内嵌与右截均可，官方例 `polymorph*`）；`?` = 0 或 1 个字符（官方例 `benzonorbornen?`）。官方指南未列最小字符数限制。
- **短语**：双引号 = 精确短语（官方例 `"ethanol fermentation"`）。**注意**：即便加引号，复数形式与索引的 Concept 同义词仍可能被检出——这是 CAS 的 **Precision Search** 行为（检索 CAS Lexicon 概念词会自动扩同义词）。**关键词之间存在隐含 OR**：裸敲一串词等于各词 OR，容易过宽，须对核心概念显式 `AND` 或加引号收窄（OSU/MIT 馆方指引一致强调）。
- **高级 References 字段**（下拉选择，非 PubMed 式后缀标签）：Author Name、Journal/Publication Name、Organization Name、Title、Abstract/Keywords、Concept、Substances、Bioactivity Data、Publication Year、Document Identifier、Patent Identifier、Publisher。**算符只在字段之间用，单个字段框内不支持布尔**；最多 **50 个高级字段**（若同时用主检索框则 49 个）。
- **无邻近算符**：文本参考检索没有 NEAR/位置算符；相邻靠引号短语，语义相关靠 CAS Lexicon 的 Precision Search（Concept 词自动扩同义）。
- **检索历史**：SciFinder-n 自动把检索存为**脚本（script）**，无条数上限、账号存续期内不过期；可「合并当前集合与已存集合」。

### 受控词（CAS Lexicon / Concept）
CAS Lexicon 的 **Concept** 词在 Precision Search 下会自动纳入同义词，功能上类似受控概念，但**不是 MeSH 式可爆炸的层级叙词表**。**无免费公共 API 核验 Concept 词存在性**（CAS Common Chemistry 有开放 API，但只覆盖物质/CAS 号，不覆盖参考文献 Concept，且不在本卡范围）→ 受控词状态标 `llm_suggest_only`（LLM 建议 + 黄旗待人工核）。

### 深链与合规（订阅墙 + 使用条款）
SciFinder-n **全站登录墙**，无公共/无状态深链 → **C 档**，交付形态 = 可粘贴进 References 检索框的文本检索式本身。**CAS 使用条款**明确禁止任何自动化程序/脚本抽取或系统性下载 CAS 数据，单账号保留上限 5000 条、禁止代他人检索、禁商用。故 PSP **绝不脚本化访问 SciFinder**——导出仅生成给用户在自己已登录会话内手动粘贴的检索式（C-14 合规基因延续，且额外受 CAS ToS 约束）。
