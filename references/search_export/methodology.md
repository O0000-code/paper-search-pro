# Search Strategy Methodology — 总纲 (methodology.md)

*方法学出处：Cochrane Handbook for Systematic Reviews of Interventions v6.5, Ch.4 "Searching for and selecting studies" (Lefebvre, Glanville, Briscoe et al., Sep 2024) 及其 Technical Supplement §3；PRESS 2015 (McGowan et al., J Clin Epidemiol 2016;75:40-6)；PRISMA-S 2021 (Rethlefsen et al., Syst Rev 2021;10:39)。全文引用记法：`[Hb §4.x]` / `[TS §3.x]` / `[MECIR C##]` / `[PRESS 域N]` / `[PRISMA-S item N]`。*

---

## 0. 这份文档是给谁读的 —— 执行检索的 LLM

**你（LLM）正在把一份平台无关的概念原料（`query_plan.json`：概念块 + 同义词 + 语言轨）升级成逐平台、可粘贴的专业检索式。** 这份总纲不是背景阅读，是你在 STEP 11.5「三明治层1」做每一个语义判断时的判据。每一节给你三样东西：**判断准则**（你要执行的规则）、**✅ 好示例**、**❌ 坏示例（标明为什么坏 + 怎么检测）**。坏示例大多直接取自 PSP 自己 `query_planner.md` 曾经的真实错误（R3 P1×3，OpenAlex 上实测有害）——LLM 会照抄示例，所以坏示例必须被点名。

**贯穿全文的一条分工铁律**（[00 §二.7]）：**语义判断交你、机械事实交代码**，两个方向都不许越界。

| 交给你（LLM）的语义判断 | 交给代码的机械事实 |
|---|---|
| 概念块划分、同义词/入口词扩展、受控词候选、explode 与否、档位取向、跨库语义适配、PRESS 语义域自检 | 布尔骨架拼装、字段标签映射、截词符映射、**邻近 n 值换算**、URL 构造、filter 整段照录、linter 结构校验 |

你**绝不**逐次口算邻近 n 值、绝不自造研究设计过滤器、绝不假装验证了没有免费 API 的受控词表（见 §4、§5）。这三件事是 LLM 幻觉的高发区，官方明确警告过 [TS §3.2.3]：ChatGPT/Claude 会**生成错误的 MeSH、同一 prompt 不同时间给不同词、幻觉出不存在的引用**。所以架构上把这些钉死在机械侧。

---

## 1. 先过这一关：目标是布尔库还是相关性引擎？（硬门，决定后面所有规则是否适用）

这是你**第一个**要判断的问题，因为它决定下面每一条纪律是「真错误」还是「无害松弛」。整套检索方法学（概念块、受控词、布尔/邻近、filter、PRESS）**是为布尔精确匹配的书目库设计的** [TS 全章前提]。三分类判据（[R2 §8]，PSP 实测校准 [R3 附录B]）：

| 类 | 定义 | 例 | 你的动作 |
|---|---|---|---|
| **(a) 任何引擎下都错** | 违反检索逻辑本身，布尔库和相关性引擎都错 | 概念混 OR、AND/OR 写反、括号嵌套错、截词符跨界面误用、邻近 n 搬错 | **一律修**，不分平台 |
| **(b) 相关性引擎无害、布尔库有害** | 相关性排序会兜底的松弛 | 不做 explode、不用邻近、同义词不全、不加设计 filter | 导出到 PubMed/WOS/Embase **时必须升级**；对 OpenAlex 可留 |
| **(c) 专业但可更好** | 打磨项 | 同义词深度、静态小词表 | 有余力则优化 |

**为什么这一关是硬门**（[hard-constraints-before-soft-evaluation]）：PSP 自身默认打 OpenAlex/Semantic Scholar（相关性排序引擎），而导出目标是 PubMed/Embase/WOS/CNKI（布尔库）。同一条纪律的严重度在两端不同——先判引擎类，再决定哪些规则是消除性的。

**实测锚点（不是理论，[R3 附录B]，2026-07-16 OpenAlex live）**：
- 大写 `OR` 被解析为布尔或（`metformin OR aspirin` = 两者并集 582,386）；**小写 `or` 是停用词**（仅 14,141）→ 布尔结构在 OpenAlex 上**有效**，所以「概念混 OR」在 OpenAlex 上**也是真错误 (a) 不是可原谅松弛**。
- `diabet*` 截词直接 **HTTP 报错**（OpenAlex 默认词干化，`*` 非法）→ 截词是 (b)：布尔库必需，OpenAlex 上有害。

---

## 2. 概念块纪律（Concept-Block Discipline）

整套方法学的地基。三条准则，逐条配对照。

### 2.1 块内 OR 只放同义词，块间必须 AND

**判断准则**：把研究问题拆成**主要概念**（PICO：Population/Intervention/Comparison/Outcome + 研究设计）[Hb §4.4.2]。一个概念内的所有说法（同义词、拼写变体、缩写、上下位词、受控词+自由词）用 **OR** 连接以求召回；**不同概念之间用 AND** 以保证每个概念都在结果中被代表。形式：`(c1a OR c1b …) AND (c2a OR c2b …)` [Hb §4.4.2, TS §3.4, MECIR C32]。

✅ **好示例**（正念干预 / 大学生 / 焦虑，每块单一概念）：
```
("Mindfulness"[Mesh] OR mindfulness[tiab] OR MBSR[tiab] OR MBCT[tiab])
AND ("Students"[Mesh] OR "college students"[tiab] OR undergraduates[tiab])
AND ("Anxiety"[Mesh] OR anxiety[tiab] OR anxious[tiab])
```
P/I/O 三块，每块内只有该概念的同义表达，块间 AND。✓ A-1。

❌ **坏示例**（PSP query_planner.md 旧 L27，R3 P1-1，实测有害）：
```
P: "adults" OR "type 2 diabetes" OR "T2D"
```
**为什么坏**：`adults` 是**人群**概念，`type 2 diabetes`/`T2D` 是**疾病**概念——两个概念被 OR 进同一块。本该「人群 AND 疾病」的逻辑塌缩成「人群 OR 疾病」。**实测危害**：`metformin AND ("adults" OR "type 2 diabetes" OR "T2D")` = 157,733 命中 vs 干净的 `metformin AND "type 2 diabetes"` = 125,439，**多召回 26%**，多出来的是「metformin 用于成人（PCOS/肿瘤预防等非 T2D）」的偏题文献 [R3]。**检测**：LLM 自检「这个 OR 块里的词是不是同一概念」（PRESS 域1/域3）；linter 无法判语义。**✅ 修正**：拆成两块 —— `("adults"[tiab] OR adult[tiab]) AND ("type 2 diabetes"[tiab] OR T2D[tiab] OR T2DM[tiab])`。

❌ **坏示例2**（旧 L88，认知对象混入干预）：
```
("working memory" OR "WM" OR "executive function" OR "cognitive training")
```
**为什么坏**：`working memory`/`executive function` 是**研究对象/构念**，`cognitive training` 是**干预手段**——概念污染。**实测**：污染版 109,427 vs 干净 `"working memory"` 版 60,346，**扩大 81%** [R3]。**✅ 修正**：把 `cognitive training` 剥离到独立的干预块，对象块只留 `("working memory" OR "WM" OR "executive function")`，干预另立 `(training OR intervention OR "cognitive training")`，两块 AND。

### 2.2 少而精：默认 2 概念起步，不是把 PICO 全塞进去

**判断准则**：**不是所有 PICO 元素都要进检索式** [Hb §4.4.2]。默认只用 **2 个概念（Population + Intervention）**，只有当命中数不可控时才加概念 [TS §3.4]。官方总结：「避免太多不同概念，但每个纳入概念内用大量检索词 OR 组合」[Hb Key Points]。

- **C（Comparison）默认略去**——比较组在题摘描述差、常不提、受控词索引不到，强行加会漏检 [Hb §4.4.2]。
- **O（Outcome）默认略去**——除非结局在摘要里定义清晰、报告一致（不良反应检索例外，见 [Hb Ch.19]）。
- **单一概念**：复杂/未知/公共卫生干预可能只检索人群或干预其一 [Hb §4.4.2, MECIR C32]。
- **非 PICO 问题**（诊断准确性、预后、质性、方法学）用 tailored approach：拆复合概念、多股检索、对关键文献做引文追踪 [Hb §4.4.2]。

✅ **好示例**：上节正念例本可只 `(P学生) AND (I正念)` 两块；O(焦虑) 之所以纳入，是因为它是**核心限定且题摘一致报告**（A-2 例外），并显式给出**回退方案**「若命中过多回退为 P AND I」。判断被写明，不是默认硬塞。

❌ **反模式**：把 P、I、C、O 四块全 AND 起来当默认——精度看似高，实则 C/O 在题摘中报告不全，**静默漏检**。这是 LLM 的天然倾向（想「完整」），必须主动压制。

> **给 LLM 的护栏**：`query_planner.md` 里那条「不要 AND 超过 4 个概念块」是 **OpenAlex 相关性引擎的经验启发式**（[R3 P3-2]），**不要继承到布尔库导出**——布尔库常规 AND 5–8 块。导出层判断概念数时以「少而精」为准，不以那条 OpenAlex 专属阈值为准。

### 2.3 NOT 默认禁用

**判断准则**：NOT 尽量避免，防误删相关记录 [Hb §4.4.2, TS §3.4, MECIR C32]。例：检索女性用 `NOT male` 会删掉「同时讲男女」的记录。**唯一可接受场景**：经验证过滤器内部的排除段（如 RCT filter 的 `animals NOT humans`）——那是罐装验证块的一部分，不是你现写的。

✅ 好：完全不用 NOT，靠概念 AND 收窄。❌ 坏：`(anxiety) NOT (depression)` 想排除共病研究——会删掉大量同时研究焦虑的有效记录。**检测**：linter L8 抓 filter 白名单外的 NOT（warn）。

---

## 3. 受控词 + 自由词双轨

### 3.1 双轨定律：每个概念都要「受控词 OR 自由词」

**判断准则**：每个概念都应**主题词（controlled vocabulary）+ 文本词（free-text）并用** [Hb §4.4.4, MECIR C33, TS §3.2]。理由互补：受控词抓到「用不同文本表达同一概念」的记录；自由词抓到「太新、还没被索引」的记录（索引滞后数天到数月）。只靠受控词 → 最新文献漏检 + 索引员未必准；只靠自由词 → 漏掉「题摘没你的词但被正确索引」的记录。

✅ 好（每概念双轨）：`"Anxiety"[Mesh] OR anxiety[tiab] OR anxious[tiab]` —— MeSH + tiab 自由词。
❌ 坏：某概念只写 `anxiety[tiab]`（漏受控词，漏了被 `Anxiety`[Mesh] 索引但题摘用 "anxious mood" 的记录）；或只写 `"Anxiety"[Mesh]`（漏自由词，漏了刚发表未索引的）。**检测**：结构可机械检——linter 可查「每概念是否同时含受控词标签和自由词标签」（PRESS 域3末条）。

**怎么找词（你的语义主战场，[TS §3.2.1-3.2.2]）**：
- **找受控词**：浏览主题词表（MeSH Scope Note + Entry terms + 相关词）；从**已知相关记录**看它被赋了哪些主题词（PSP 优势——STEP 4 enrich 已把真实论文的真实 MeSH 回填 KG，直接复用，比凭记忆更可锚定，Yale-MeSH-Analyzer 式 grounding）；工具 MeSH on Demand（粘贴 protocol 文本→建议 MeSH）。
- **找自由词**（四类来源 checklist [TS §3.3]）：同义词（`'pressure sore' OR 'decubitus ulcer'`）、相关词（`brain OR head`）、英美拼写变体（`tumour OR tumor`）、缩写+全称（`MBSR` 与 "mindfulness-based stress reduction" 都收，[PRESS 域4]）。药物名查 PubChem（商品名/通用名）。核心提醒：自然语言允许同一概念多词表达，**每个概念都要查同义词**。

### 3.2 受控词表的三个操作：explode / subheading / focus

**判断准则**（[TS §3.2.1, Hb Box 4.4.c, MECIR C33]）：
- **Explode（爆炸，`exp`/`[mh]`/`+`）**：连同树状下位词一起检索。**该 explode 处必须 explode**，否则漏检（例：不 explode `BRAIN INJURIES` 会漏掉只索引为下位词的 shaken baby syndrome）；**不该 explode 处别 explode**，免引入无关。PubMed `[Mesh]` 默认 explode。
- **Subheading（副主题词）**：`drug therapy` 等。**Floating subheading（浮动副主题词 `.fs.`）**通常更受青睐（不论挂哪个主题词都检索，避免漏检）[Hb Box 4.4.b, PRESS 域3]。
- **Major topic / focus（`*` starring / restrict to focus）**：只检索「被索引员评为主要主题」的记录。**精度最大化特性，综述检索默认关闭**——它牺牲召回 [TS §3.2.1]。

**⚠️ 载荷性陷阱 —— Publication Type vs "as Topic"**：MEDLINE 里，一篇 RCT 的**报告**索引为 Publication Type `Randomized Controlled Trial`；一篇**讨论 RCT 这件事**的文章索引为 MeSH `RANDOMIZED CONTROLLED TRIALS AS TOPIC`（TRIALS 复数）。Embase 同理：Emtree `randomized controlled trial` = 出版类型，`randomized controlled trial (topic)` = 讨论 RCT 的记录。**混用会严重伤精度**——这是 RCT filter 的核心细节。✅ RCT filter 用 PT `Randomized Controlled Trial`；❌ 误用 `...AS TOPIC` MeSH。**检测**：机械规则（E6）。

### 3.2b explode 判断的好/坏
✅ 好：`"Brain Injuries"[Mesh]`（PubMed 默认 explode，纳入下位词 shaken baby syndrome，不漏检）。
❌ 坏：需要精确「脑损伤」这个上位概念却手动 `[Mesh:noexp]` 关掉 explode——漏掉只被索引为下位词的记录（E5 漏检）；反之，对一个下位词过宽的主题词硬 explode 会引入无关记录。**检测**：LLM 语义判断「这个词的下位词是否都相关」（域3），linter 无法判。

### 3.3 MeSH ≠ Emtree：受控词表不可一一映射，禁止符号替换

**判断准则**：MeSH（MEDLINE）与 Emtree（Embase）**既不是同一套词，索引方式也不同**，非一一映射 [Hb Box 4.4.c, TS §3.2.1]。**结论：受控词必须为每个库逐一重新判定，绝不能靠符号替换机械转译。** MeSH `"Anxiety"[Mesh]` 不能符号替换成 Emtree `'anxiety'/exp`——要重新在 Emtree 里判断对应词。这正是跨库转译的公认最难点，也是质量声明的边界。

**验证分轨**（这条决定你能不能声称「已验证」）：
- **MeSH、ERIC** 有免费 API → **必须机械核验存在性**（杜绝幻觉词，见 §5.2）。
- **Emtree / CINAHL / APA Thesaurus / CMeSH** 无免费查表途径 → **LLM 建议 + 输出中标黄「待人工核对」，不得伪装已验证**（[A-6, critic 硬约束]）。

✅ 好：MeSH 词经 NCBI API 核实后标 🟩「机械已验」；Emtree 词标 🟨「语法已验·词表待核」。❌ 坏：把 LLM 猜的 Emtree 词标成「已验证」——这是欺骗性声明，硬禁。

---

## 4. 算符体系与验证过滤器（语义你判、机械代码拼）

算符的**机械拼装**（字段标签、截词符、邻近 n 换算、行式组合）交给代码——逐库语法卡（`syntax_cards/<host>.md`）+ 换算表（`proximity_table.json`）是它们的数据源。你（LLM）只需知道**哪些跨库差异会静默出错**，好在语义层不做危险假设：

- **截词/通配不可移植**：`$` 在 WOS/Embase.com = 零或一字符、在 Ovid = 截词；`*` 在 OpenAlex 直接报错；`*` 在 CNKI/万方**不作截词符**——但含义不同：CNKI 的 `*` 是**字段内 AND 复合算符**（空格分隔，非截词，见 `chinese_methodology.md` §1），万方的 `*` 已废弃为**普通检索词**（用 and/or/not 替代）。**符号在某些界面含义相反** [TS §3.8]——绝不假设通用。查卡，翻错无报错。
- **邻近算符 n 值语义跨宿主差 1**：同一个 n 在 Cochrane/Ovid/Embase.com = 「间隔词数 + 1」，在 EBSCO/ProQuest/Scopus/WOS = 「间隔词数」[TS §3.5]。即 Ovid `adj2` ≈ EBSCO `N1`（都 ≤1 间隔词）。**照搬 n 会系统性放大/缩小邻近范围、静默改召回**——这是最隐蔽的错误源，**做成确定性换算表，绝不 LLM 口算**。
- **PubMed 邻近额外约束**：`"terms"[tiab:~N]` 不能与截词 `*` 同用、不能与短语检索同用、field 限 Title 或 Title/Abstract。冲突时机械回退（拆 `~0` 短语或改 AND）并记录降级。

> 示例纪律：**保守正确不炫技**。§2.1 好示例**故意不用邻近算符**——避开整类静默错误。只有当召回/精度确实需要邻近、且目标平台的 n 语义已由换算表锁定时才用。

### 4.2 验证过滤器：只用罐装的，绝不自造

**判断准则**：检索特定研究设计（如 RCT）时**必须用已发表、经同行评审、报告了性能的验证过滤器**，**不要自己现编研究设计段** [Hb §4.4.7-4.4.8, MECIR C34]。权威库：**Cochrane HSSS** 与 **ISSG Search Filters Resource**（详见 `filters_library.md`，含 PubMed+Ovid 两格式原文照录）。

**铁律**：
- **CENTRAL 不用 RCT filter、不用 human filter**——它本身只收对照试验，加 filter 反而漏检 [Hb §4.4.7, MECIR C34]。不在预过滤库上叠同类 filter（CENTRAL 不加 RCT、DARE 不加 SR filter）。
- filter 必须**引用来源** [PRISMA-S item 10]。

✅ 好：需要限 RCT → 挂 `filters_library.md` 里的 CHSSS（整段照录）+ 引用「Cochrane HSSS 2008 sensitivity-maximizing, PubMed format」。
❌ **坏示例**（PSP query_planner.md 旧 L29-30，R3 P1-2）：
```
O: ("HbA1c" OR "glycemic control") AND ("RCT" OR "randomized")
```
**为什么坏**：两处错。① 一个标注为 O（结局）的块里内嵌 AND、混入「研究设计」概念——结局与研究设计是两个 facet，不该塞进同一标注块用内部 AND（结构错误，A-1）。② `("RCT" OR "randomized")` 是**自造的两词自由文本 RCT 过滤器，灵敏度极差**——会漏掉大量题摘未写 "RCT/randomized" 的试验。Cochrane 的 CHSSS 是含 `randomized controlled trial[pt]`、`placebo[tiab]`、`randomly[tiab]`、`groups[tiab]`、`drug therapy[sh]` 的多行验证块。**✅ 修正**：结局与设计分块；研究设计块**挂 CHSSS 验证过滤器，不自造**。**检测**：linter L9 抓 CENTRAL+filter 共现；自造过滤器需 LLM 判断（域6）。

---

## 5. 敏感度 vs 精确度：档位哲学（quick→audit 映射）

**定义**（[Hb §4.4.3, Table 4.4.a]）：**Sensitivity（召回）**= 检出相关数 / 库中全部相关数 = a/(a+b)；**Precision（精度）**= 检出相关数 / 检出全部数 = a/(a+c)。**铁的权衡**：提高召回（更多更宽的词）必然降低精度。

**综述取向**：SR 默认**追求最大召回、容忍较低精度**（"maximize sensitivity whilst striving for reasonable precision" [Hb Key Points, MECIR C32]）——理由算得过来：摘要筛查很快（60–120 篇/小时），高召回的额外筛查量相对整个综述工时不可怕。但**不是无脑最大召回**：档位随综述类型/决策确定性需求变。

**PSP 档位 → 召回/精度参数映射**：

| 档位 | 取向 | 概念数 | 同义词深度 | 双轨受控词 | 验证过滤器 | PRESS 自检 | PRISMA-S |
|---|---|---|---|---|---|---|---|
| **Quick / scoping** | 偏精度 | 2 块，少 | 浅（点到即止） | 可省 | 省 | 省 | 省 |
| **Standard** | 平衡 | 2–3 块 | 中 | 建议 | 按需 | 轻 | 部分 |
| **Deep** | 偏召回 | 2–4 块 | 深 | 是 | 按研究设计 | 是 | 大部分 |
| **Audit（SR-prep）** | 最大召回 | 逐库定制 | 穷尽（拼写/缩写/entry terms） | 强制双轨 | 挂验证过滤器 | 六域全查 | item 8 全填 |

**何时停**（[Hb §4.4.11]）：迭代探索，难有客观终点。停止规则示例：加一批新词若不再带来新记录、或精度跌破阈值就停；或「移除某些词会漏相关记录」时判定已足够。证据稀少的主题更谨慎地停。**这是你的语义判断，不是机械阈值。**

---

## 6. 错误分类学 E1–E14（含检测方式）

QA gate 的直接原型。综合 PRESS 六域 [PRESS] 与 Hb/TS 告诫。**「检测」列告诉你这条能否被 linter 机械抓、还是要 LLM 语义判断**；**「类」列**接 §1 的 a/b/c（决定是否分平台）。

| # | 错误类型 | 典型表现 | 后果 | 检测 | 类 |
|---|---|---|---|---|---|
| E1 | **概念混块** | 不同概念放进同一 OR 块（人群 OR 疾病；对象 OR 干预） | AND 逻辑塌缩，精度崩+召回污染 | LLM（域1/3） | a |
| E2 | **布尔逻辑写反** | 该 AND 用了 OR、括号嵌套错、孤儿行 | 结果集完全错 | 机械（域2/5） | a |
| E3 | **NOT 误伤** | `NOT male` 删掉男女混合记录 | 静默漏检 | 机械+LLM（域2） | a |
| E4 | **只用自由词或只用受控词** | 某概念缺主题词或缺自由词 | 漏检（新文献/异表达） | 机械可检结构（域3末条） | b |
| E5 | **explode 缺失/过度** | 该 explode 未 explode / 不该却 explode | 漏检 / 引入无关 | LLM（域3） | b |
| E6 | **PT vs "as Topic" 混用** | RCT filter 误用 `...AS TOPIC` MeSH | 严重伤精度 | 机械规则（§3.2） | a |
| E7 | **截词错误** | 截太宽（`cat*`→category）/太窄/位置错/用了别界面符号 | 精度崩 或 漏检 或 语法失效 | 机械(符号)+LLM(宽窄)（域4/5） | a |
| E8 | **邻近 n 值搬错** | 跨库照搬 n，未做 x vs x+1 换算 | 静默放大/缩小邻近范围 | 机械换算表（§4） | a |
| E9 | **同义词/拼写变体不全** | 漏英美拼写、漏缩写全称、漏近义 | 系统性漏检 | LLM+机械补齐（域4） | b/c |
| E10 | **受控词表跨库错译** | 把 MeSH 符号替换当 Emtree | 受控词检索失效 | LLM+映射表（§3.3） | a |
| E11 | **filter 误用** | CENTRAL 用 RCT filter / 用失效旧 filter / 未引用来源 | 漏检 或 不可复现 | 机械规则+引用检查（§4.2） | a |
| E12 | **过度限制** | 无理由的语言/日期/文献类型限制 | 语言偏倚/漏检 | 规则+LLM（下文） | a |
| E13 | **字段标签错配** | 目标平台不支持的字段 / 标签拼错 | 语法失效或字段错 | 机械（语法卡） | a |
| E14 | **语法错误** | 拼写、系统语法、长串未拆 | 检索报错或静默错 | 机械（域5） | a |

**E12 过度限制的方法学底线**（[Hb §4.4.5, MECIR C35]）：**语言**——默认不限语言（限语言引入偏倚；证据显示排除非英文对多数 SR 影响小，但 CAM/精神/风湿/骨科例外）；若限，应在**筛选阶段**作纳入标准限，而非检索式里限。**日期**——只有当「相关研究只可能在某时段发表」才限，且必须报告+给理由；跨库日期字段各异（PubMed DP ≠ Ovid YR），转译格外小心。**文献类型**——SR 检索不加文献格式限制（不排除 letters/comments/preprints）。

---

## 7. PRISMA-S item 8 对接 + 质量声明上限

**导出物 = PRISMA-S item 8 的交付级实现。** PRISMA 2020 已强化为「**呈现所有数据库/注册库/网站的完整检索式，不止一个库**」[Hb §4.5, PRISMA-S item 8]。对 Cochrane 检索式，应**原样复制粘贴、连同行号与每条命中数，不要重打**（重打会引入错误）[Hb §4.5]。

生成器落法（机械填充，[R2 §6]）：`strategies[].prisma_s.item8_boolean_expression` → 灌进 `execution_log.json` 的 `8_full_search_strategies.boolean_expressions[]`（现字段已存在）；item 1（库+平台）、item 9（限制+理由）、item 10（filter 引用）、item 13（检索日期）同步机械填。item 5/6/11（引文检索/联系/复用）是叙事性，交 LLM 描述。

**质量声明上限锁死为「专业初稿 + 标注复核点」**（[A-15]）：禁止「可署名直用 / 等同馆员级成品」。每份检索式带**三态验证状态标签**（🟩机械已验 / 🟨语法已验·词表待核 / 🟦结构参考），所有未机械验证的受控词、邻近降级、订阅墙未验执行都进「全局复核点」清单。这个声明由 §3.3 的验证分轨支撑——你能声称「已验证」的只有 MeSH/ERIC，其余如实标黄。**官方对 LLM 生成检索式的立场是「可作传统方法之外的补充，但应审慎使用」** [TS §3.2.3]——这份工具的质量声明与官方立场对齐。

---

*溯源：概念块/少而精/NOT [Hb §4.4.2, TS §3.4, MECIR C32]｜双轨/explode/PT-vs-Topic/MeSH≠Emtree [Hb §4.4.4, TS §3.2/3.2.1, MECIR C33]｜算符/截词/邻近跨库 [TS §3.3/3.5/3.8]｜验证过滤器/CENTRAL [Hb §4.4.7, MECIR C34]｜档位/何时停 [Hb §4.4.3/4.4.11, Table 4.4.a]｜限制底线 [Hb §4.4.5, MECIR C35]｜PRESS 六域 [McGowan et al 2016]｜PRISMA-S item 8 [Rethlefsen et al 2021]｜LLM 审慎立场 [TS §3.2.3]｜实测锚点 [R3 附录B, 2026-07-16 OpenAlex live]。禁读任何既有 SR/综述 Skill——本文第一性原理，只从原始文献 + R2 蒸馏。*
