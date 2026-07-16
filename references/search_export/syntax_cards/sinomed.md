# SinoMed / CBM（中国生物医学文献服务系统）

> 语法卡 · 统一字段格式（§13 spec §4）。中文原生医学库；**CMeSH 主题检索**为核心特色。
> 与 `chinese_methodology.md` 耦合最深（CMeSH 机制在此写透，供中文方法学专节引用）。语法主张附官方/馆方文档 URL + verified_date。

```yaml
platform: "SinoMed / CBM（中国生物医学文献服务系统）"
host: "中国医学科学院医学信息研究所·图书馆 / www.sinomed.ac.cn"
database: "CBM 中国生物医学文献数据库（+ WBM 西文·CBMCI 引文·PUMCD 协和博硕论文·CPM 科普）"
access: subscription                  # IP 段自动登录 或 账号登录；根域 302→LoginServlet
search_modes: ["快速检索(智能，跨库/常用字段)", "高级检索(逻辑组配+限定检索)", "主题检索(CMeSH)", "分类检索", "期刊检索", "单篇检索", "引文检索"]
field_tags:                           # 基本检索 18 字段；缺省组合字段=题目/文摘/关键词/主题词/刊名
  title: "中文标题"
  abstract: "摘要"
  keyword: "关键词"
  subject_cn: "中文主题词"           # 中文主题词（CMeSH）
  subject_en: "英文主题词"           # 英文主题词（MeSH）
  subject_heading: "中文主题词"       # §4 强制别名（= subject_cn）
  title_abstract: null               # 无单一题摘组合标签；缺省组合字段含题目+文摘+关键词+主题词+刊名
  author: "作者"
  first_author: "第一作者"
  corr_author: "通讯作者"
  affiliation: "机构"
  journal: "刊名"
  pub_year: "出版年"
  fund: "基金"
  class_code: "分类号"
  feature_word: "特征词"
  pub_type: null                     # 文献类型经『限定检索』而非字段标签
  subheading: "副主题词（CMeSH 组配：主题词/副主题词）"
  all: "缺省组合字段（题目/文摘/关键词/主题词/刊名）"
boolean: {and: "AND", or: "OR", not: "NOT", case: "uppercase, 英文半角"}   # 字段间逻辑
truncation:                           # ★与 CNKI 不同：SinoMed **有**通配符
  single_char: "?"                    # 单字通配（血?动力 → 血液动力/血流动力）
  multi_char: "%"                     # 任意字通配（肝炎%疫苗 → 肝炎疫苗/肝炎病毒基因疫苗…）
  note: "内嵌/右截均可；勿套用『中文一律无截词』——那是 CNKI，不是 SinoMed"
phrase: {quote: "半角双引号 \"\"", use: "含 ()、- 等特殊字符的短语须加半角引号（例：\"邻苯二甲酸二(2-乙基)酯\"）"}
proximity: {supported: false, n_family: null, note: "无西式 NEAR/位置算符；快速检索自动同义扩展"}
controlled_vocab:                     # —— CMeSH 主题检索（本卡核心）——
  name: "CMeSH"
  basis: ["《医学主题词表 MeSH》中译本", "《中国中医药学主题词表》"]
  version: "CMeSH 2017 版（SinoMed 3.0，2019-05 上线）"
  combine: "主题词–副主题词组配（例：糖尿病并发症/治疗）"
  weighted: "加权检索：仅命中『主要概念主题词/带星号主题词』→ 提精度（默认关，须手动勾）"
  explode: "扩展检索：纳入该主题词的下位词（树形结构）→ 提召回（默认开）"
  subheading_explode: "副主题词默认『扩展副主题词』（选『治疗』含药物疗法等 14 个下位副主题词）"
  machine_expr: "\"<主题词>/全部树/全部副主题词\"   # 官方检索式写法=爆炸+全副主题词，半角双引号包住"
  multi_term: "支持多主题词，用 AND/OR/NOT 组配"
  verification: llm_suggest_only       # 默认：LLM 建议 + 黄旗『待人工核』（须 UI 内确认准确主题词+副主题词）
  free_crosscheck:                     # ★实测发现（2026-07-16）：存在免费无登录 autocomplete，可做存在性交叉核
    endpoint: "GET https://www.sinomed.ac.cn/suggest.do?dbtype=mt_&q=<中文词>"
    behavior: "返回 CMeSH 中文主题词候选；命中→有候选，无命中→HTTP 200 空体（size 0）"
    caveats: ["autocomplete（子串匹配），非权威描述符 API", "只返回词串，无 descriptor UI/树号/副主题词", "未公开文档的内部 AJAX，可能变更/失效", "仅中文主题词（英文 dbtype 实测空）"]
    verdict: "可作『空即疑幻觉』的免费交叉核，但不足以升级为机械已验；默认状态仍 llm_suggest_only"
line_search: {supported: true, syntax: "检索历史 #1 AND #2；二次检索(与前式 AND)；检索表达式实时编辑窗口"}
limits:                               # 限定检索（sticky，取消前一直有效）
  fields: ["年代", "文献类型", "年龄组", "性别", "研究对象(人/动物)", "妊娠状态", "体外研究"]
  logic: "同组内 OR，组间 AND；表达式中以 -限定:... 追加"
special_chars_escape: "全英文半角铁律：逻辑符/引号/括号混入中文标点即报错"
deep_link:
  tier: "C"                           # 登录墙（根域 302→LoginServlet），主题检索为会话态
  url_kind: "paste_only"
  url_template: null                  # 无稳定无状态深链
  delivery: "交付=可粘贴进高级/主题检索『检索表达式』框的 CMeSH/字段检索式本身"
  verified_http: "302 (root→LoginServlet)"
  verified_date: "2026-07-16"
source_url:
  - "https://www.sinomed.ac.cn/zh/subjectSearch.html"     # 官方主题检索页
  - "https://baike.baidu.com/item/中国生物医学文献服务系统/9588775"   # 版本/资源/CMeSH 2017 佐证
  - "https://lib.cmc.edu.cn/cbm.pdf"                        # 馆方使用指南（主题检索/副主题词组配步骤）
verified_date: "2026-07-16"
gotchas:
  - "★SinoMed 有通配符 ?（单字）/ %（任意字）——别套用 CNKI 的『无截词』"
  - "全英文半角：逻辑符、双引号、括号混中文标点→报错"
  - "加权检索默认关（要精度须手动勾）；扩展检索默认开；副主题词默认扩展"
  - "快速检索=智能检索会自动同义扩展（艾滋病→获得性免疫缺陷综合征），可能超范围放大"
  - "CMeSH=中文，可与 MeSH 对照，但『中国中医药学主题词』部分为 CMeSH 独有、无英文对应"
  - "CMeSH 无权威免费 API；suggest.do 仅作存在性交叉核（见 free_crosscheck），默认状态维持待人工核"
```

## 证据与说明（prose）

### 平台与访问
SinoMed 由中国医学科学院医学信息研究所/图书馆研制，整合 CBM（中国生物医学文献，1978 以来 1800 余种中文期刊题录）、WBM（西文）、CBMCI（引文）、PUMCD（协和博硕论文）、CPM（科普）。访问 `www.sinomed.ac.cn`，IP 段内自动登录或账号登录——**根域实测 302 跳 `ids.sinomed.ac.cn/ids/LoginServlet`（登录墙）**，故深链为 C 档（粘贴式）。检索模式：快速（智能，跨库/常用字段）、高级（逻辑组配 + 限定检索）、**主题（CMeSH）**、分类、期刊、单篇、引文。

### CMeSH 主题检索（本卡核心，写透供 chinese_methodology 引用）
主题标引依据 **《医学主题词表（MeSH）》中译本 + 《中国中医药学主题词表》**（现行 **CMeSH 2017 版**，随 SinoMed 3.0 于 2019-05 上线）。主题检索六步：选「中文主题词/英文主题词」入口 → 输词「查找」→ 浏览款目词/主题词列表选定主题词 → 点开显示**可组配副主题词 + 注释 + 树形结构** → 设定**加权 / 扩展** → 选副主题词 → 「主题检索」。四个 CMeSH 独有机制：

1. **主题词–副主题词组配**：如「糖尿病并发症的治疗」= 主题词`糖尿病并发症` / 副主题词`治疗`（写作 `糖尿病并发症/治疗`）。组配须有必然逻辑关系（因果/应用等）。
2. **加权检索（weighted）**：仅检出该词为**主要概念主题词（带星号/主要主题）**的文献 → 提相关性/精度。**默认关闭**，须手动勾选。
3. **扩展检索（explode）**：纳入该主题词的**下位词**（树形结构中的 narrower terms）→ 提召回。**默认开启**。
4. **副主题词扩展**：系统默认「扩展副主题词」——选主副主题词`治疗`会自动含`药物疗法`等 14 个下位副主题词。

**机器可写的 CMeSH 检索式形态**（官方馆方指南实例）：
```
#1  脑外伤 OR 脑损伤 OR "脑损伤/全部树/全部副主题词"        49039 篇
#2  生长激素 OR "生长激素/全部树/全部副主题词"              5859 篇
#3  #1 AND #2                                              51 篇
#4  #1 AND #2 -限定:儿童,学龄前;儿童;青少年;人类            3 篇
```
即 `"<主题词>/全部树/全部副主题词"`（半角双引号包住）= **爆炸 + 全副主题词**；主题词与自由词用 `OR` 并轨；块间 `AND`；`-限定:...` 在表达式尾追加限定检索。这是导出给 SinoMed 的核心交付形态。

### 中文检索特性（半角、通配符——纠正一个常见误判）
- **全英文半角铁律**：逻辑符 `AND/OR/NOT`、双引号、括号必须英文半角，混入中文标点直接报错。含 `()`、`-` 等特殊字符的短语须加**半角双引号**（例：`"邻苯二甲酸二(2-乙基)酯"`）。
- **★通配符：SinoMed 有 `?`（单字）与 `%`（任意字）**——`血?动力`→血液动力/血流动力；`肝炎%疫苗`→肝炎疫苗/肝炎病毒基因疫苗/肝炎减毒活疫苗…。这与 CNKI 显著不同（CNKI 不用 `*`/`?`、走 `%=` 相关匹配与位置算符）。**13 spec/12 号 B-11 的『中文无截词』是 CNKI 的特性，不可平移到 SinoMed。**（来源：馆方 CBM 检索方法指南；linter 层对 SinoMed 不应报 `%`/`?` 为非法。）
- **限定检索**：年代/文献类型/年龄组/性别/研究对象/妊娠/体外，同组 OR、组间 AND，一经设置 sticky 直到取消。

### CMeSH 免费查询途径 —— 实测发现（回应任务的高价值问题）
既有结论：CMeSH 无免费查表 API → 主题词标 `llm_suggest_only` + 黄旗。**本轮实测部分推翻这一结论**：

- 端点 `GET https://www.sinomed.ac.cn/suggest.do?dbtype=mt_&q=<中文词>` **无需登录**即返回 CMeSH 中文主题词候选。实测：
  - `q=糖尿病` → `"糖尿病, 实验性" / "糖尿病, 1型" / "糖尿病, 胰岛素依赖型" …`（HTTP 200，size 245）
  - `q=高血压` → `"高血压, 肺动脉" / "高血压, 恶性" / "高血压, 肾性" …`（HTTP 200，size 230）
  - `q=randomzzz9999`（无义拉丁）/ `q=阿斯顿xyz乱码`（无义中文）→ **HTTP 200，空体 size 0**
- 即：**命中 CMeSH 主题词库→有候选；不命中→空**，构成一个真实的**存在性信号**——可免费交叉核「某中文候选词是否对应 CMeSH 主题词」，空结果≈该词非 CMeSH 主题词（很可能是 LLM 幻觉）。

**诚实边界（为何不升级为机械已验）**：这是 **autocomplete/子串建议**端点，非权威描述符 API——只回词串，无 descriptor UI / 树号 / 副主题词 / 定义；是**未公开文档的内部 AJAX**（可能变更或失效）；且为子串匹配，会带回款目词/宽松匹配噪声（如 `高血压蛋白原`），命中≠保证是规范描述符。英文 `dbtype=en_/mt_en` 实测返回空，故仅覆盖**中文主题词**。

**建议落地**：默认状态维持 `llm_suggest_only`（不 fake-verify，尊重 §5.3 critic 缝隙3 硬约束）；但把 `suggest.do` 作为 `vocab_verify.py` 的**可选软交叉核**——命中提升置信、**空结果标『疑似非 CMeSH 词，请人工确认』**，用于抓 LLM 幻觉中文主题词。这既不违反「无权威免费 API」的硬约束，又把发现的免费途径用起来。（suggest.do 实测记录见本节上方列表。）

### 深链与合规
根域登录墙（302→LoginServlet），主题检索为会话态（构建后「发送到检索框」）。**无稳定无状态深链** → C 档，交付形态 = 可粘贴进高级/主题检索「检索表达式」框的 CMeSH/字段检索式本身。合规：只观测登录跳转，不研究绕过（C-14）。
