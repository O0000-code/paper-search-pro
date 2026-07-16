# PRESS Six-Domain Self-Review Checklist (press_checklist.md)

*方法学出处：PRESS 2015 Evidence-Based Checklist — McGowan J, Sampson M, Salzwedel DM, Cogo E, Foerster V, Lefebvre C. "PRESS Peer Review of Electronic Search Strategies: 2015 Guideline Statement." J Clin Epidemiol 2016;75:40-6. 同行评审强度依据 [Hb §4.4.8, MECIR peer-review expectation]。逐条照录自 PRESS 六域。*

## 这份清单怎么用（generate-then-self-review gate）

检索式**运行前**应由合格馆员同行评审 [Hb §4.4.8]。PSP 无真人馆员，故内建为**生成后的自动 self-review pass**：STEP 11.5 层1 生成检索式后，**以全新 LLM 视角**（角色隔离 [00 §五]——self-review 不是生成者「记得自己的意图」，而是只看文本）逐平台跑本清单。每条给 **verdict：`pass` / `⚠️`** + 一句话。所有 `⚠️` 汇入该平台 `review_points[]` 与全局复核点清单，兑现「专业初稿 + 标注复核点」声明；本 gate 的存在本身回填 **PRISMA-S item 14（peer review）**。

**两类检查分列**（每域内）：
- **🔧 机械可查**（linter.py 可自动判定，见 `methodology.md` §6 / linter L1–L11）——这些若 linter 已 error/warn，self-review 直接采信，不重判。
- **🧠 LLM 判断**（语义，只能新视角 LLM 判）——这是 self-review pass 的真正工作面。

verdict 规则：任一 🔧 项 linter 报 error → 该域 `⚠️` 且必须修（error 不能带病交付）；🧠 项存疑 → `⚠️` + 复核点（可带疑点交付，因已标注）。

---

## 域1 — Translation of the research question（研究问题转译）
> 全部 🧠 LLM 判断（语义域，linter 无法判）。
- [ ] 🧠 检索式是否匹配研究问题 / PICO？
- [ ] 🧠 检索概念是否清晰？每个 OR 块是否只含**同一概念**的词（← 直接对应 E1 概念混块；这是本域最高频错误）？
- [ ] 🧠 PICO 元素是否过多或过少（默认 2 概念 P+I，C/O 慎入，见 methodology §2.2）？
- [ ] 🧠 检索概念是否过窄或过宽？
- [ ] 🧠 检索召回是否过多或过少？（有命中数则每行给命中数）
- [ ] 🧠 非常规 / 复杂策略是否有解释？

## 域2 — Boolean and proximity operators（布尔与邻近算符，随检索服务而变）
- [ ] 🔧 布尔算符大小写正确（PubMed/Scopus/EBSCO 须大写 AND/OR/NOT；OpenAlex 小写 or/and=停用词）？（linter L2）
- [ ] 🔧 括号 / 引号配平、嵌套恰当有效（OR 块用括号包住再 AND）？（linter L1）
- [ ] 🔧 邻近 n 值家族正确（gap vs gap+1，未跨库照搬）？WOS `NEAR` 未与 `AND` 同括号？（linter L4）
- [ ] 🧠 若用了 NOT，是否可能导致意外排除（E3 误伤）？
- [ ] 🧠 能否用邻近 / 短语替代 AND 以提升精度？
- [ ] 🧠 邻近宽度是否合适（adj5 比 adj2 抓更多变体）？

## 域3 — Subject headings（主题词，库特定）
- [ ] 🔧 每个概念是否**同时用了主题词和自由词**（双轨，methodology §3.1）？（linter L11 可查结构）
- [ ] 🔧 受控词是否带验证状态戳（MeSH/ERIC 机械已验；Emtree/CINAHL/APA/CMeSH 标黄「待人工核」，未伪装已验）？（linter L11）
- [ ] 🧠 主题词是否相关？是否漏了相关主题词（如旧的索引词）？
- [ ] 🧠 主题词过宽或过窄？该 explode 处是否 explode、反之亦然（E5）？
- [ ] 🧠 是否用了 major heading / focus？若用，是否有充分理由（默认关，伤召回）？
- [ ] 🧠 是否漏副主题词？副主题词是否挂对主题词（浮动副主题词可能更佳）？
- [ ] 🧠 是否混用 Publication Type 与 "as Topic" 受控词（E6，严重伤精度）？

## 域4 — Text word searching（自由词）
- [ ] 🧠 是否含所有拼写变体（英美：tumour/tumor）？
- [ ] 🧠 是否含所有同义词 / 反义词（PRESS 原文 synonyms and antonyms，如适用）？
- [ ] 🧠 缩写 / 简称用得当否、全称是否也收（MBSR 与全称都要）？会否抓到无关材料？
- [ ] 🧠 关键词是否够 specific 或过宽？是否用了 stop words（← 对 OpenAlex 尤其致命：小写 or/and 是停用词）？
- [ ] 🔧 截词是否到位、位置正确、未用错界面的符号（`$`/`*`/`?` 跨库，E7）？（linter L3）
- [ ] 🧠 是否搜了恰当字段（题摘 `[tiab]` vs 全字段 `.af.` 的选择是否合适）？

## 域5 — Spelling, syntax and line numbers（拼写、语法、行号）
> 几乎全部 🔧 机械可查——这是 linter 的主场。
- [ ] 🔧 长串是否该拆成几条短检索式（行式）？
- [ ] 🔧 是否有拼写错误 / 非法字段标签（目标宿主不支持或拼错，E13）？（linter L5）
- [ ] 🔧 是否有系统语法错误（用了别界面的截词符）？（linter L3）
- [ ] 🔧 是否有错误的行组合或**孤儿行**（未被最终汇总引用的行号 → AND/OR 写错的信号）？（linter L10）
- [ ] 🔧 中文源半角检测（无混入中文标点）+ 字段内 `*`/`+`/`-` vs 字段间方向正确（B-12，CNKI：`*`=AND / `+`=OR / `-`=NOT）？（linter L7）

## 域6 — Limits and filters（限制与过滤器）
- [ ] 🧠 所有 limits/filters 是否用得当、切合研究问题（E12 过度限制：默认不限语言/日期/文献类型）？
- [ ] 🔧 所有 limits/filters 是否切合该数据库（跨库日期字段各异 PubMed DP≠Ovid YR）？
- [ ] 🔧 filter 是否**引用了来源**（PRISMA-S item 10；未引用 = 不可复现）？（linter 可查引用字段存在性）
- [ ] 🔧 研究设计过滤器是否为**验证过的罐装块**（CHSSS/ISSG），而非自造两词过滤器（← E11，直接对应 query_planner 旧 P1-2 教训）？
- [ ] 🔧 CENTRAL / 预过滤库上是否误加了同类 filter（CENTRAL 不加 RCT filter，A-7）？（linter L9）
- [ ] 🧠 是否漏了有用的 limit/filter？filter 是否过宽或过窄？

---

## verdict 汇总模板（写进 `strategies[].press_check`）
```jsonc
"press_check": {
  "d1_translation":  {"verdict":"pass", "note":"P/I/O 覆盖研究问题；每块单一概念"},
  "d2_boolean":      {"verdict":"pass", "note":"括号配平；未用 NOT；未用邻近"},
  "d3_subject_headings": {"verdict":"⚠️",  "note":"Emtree 词为 LLM 建议，标黄待人工核"},
  "d4_text_words":       {"verdict":"pass", "note":"含缩写 MBSR+全称；英美拼写齐"},
  "d5_spelling_syntax":  {"verdict":"pass", "note":"无孤儿行；标签合法"},
  "d6_limits_filters":   {"verdict":"pass", "note":"未加语言/日期限制；filter 已引用来源"}
}
```
任一域 `⚠️` → 该项进 `review_points[]` + 全局复核点清单。六域全 `pass` 也不改变质量声明上限（仍是「专业初稿 + 标注复核点」，见 methodology §7）。
