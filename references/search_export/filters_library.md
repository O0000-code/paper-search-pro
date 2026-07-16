# Validated Methodological Search Filters (filters_library.md)

*方法学出处：Cochrane Handbook for Systematic Reviews of Interventions v6.5, §4.4.7 "Search filters"（Box 4.4.a / 4.4.b，Sep 2024 revision）及 Technical Supplement §3.6；ISSG Search Filters Resource（InterTASC Information Specialists' Sub-Group, University of York）。下列过滤器**逐字照录自 Cochrane Handbook v6.5 原文**（2026-07-16 对 chapter4seronlinepdfv65.pdf 逐行核对），非改写、非 LLM 生成。*

---

## 铁律（生成器与 LLM 都必须遵守）

1. **只用验证过的过滤器，绝不自造。** 检索特定研究设计（RCT、SR、诊断准确性、观察性研究…）时，**必须**用已发表、经同行评审、报告了性能的过滤器；**不要 LLM 现编研究设计段** [Hb §4.4.7, MECIR C34]。反面教训：PSP `query_planner.md` 旧示例 `("RCT" OR "randomized")` 是自造两词自由文本过滤器，灵敏度极差，会漏掉大量题摘未写 "RCT/randomized" 的试验（R3 P1-2）。**过滤器内容 = 机械事实（整段照录），不是 LLM 语义判断。**
2. **CENTRAL 不加 RCT filter、不加 human filter。** CENTRAL「aims to contain only reports with study designs possibly relevant for inclusion in Cochrane Reviews, so searches of CENTRAL should not use a trials 'filter' or be limited to human studies」[Hb §4.4.7 原文]——它本身只收对照试验，加 filter 反而漏检。
3. **不在预过滤库上叠同类 filter。** CENTRAL 上不加 RCT filter；DARE 上不加 SR filter [MECIR C34]。（linter L9 抓 CENTRAL + RCT filter 共现，error。）
4. **filter 必须引用来源** [PRISMA-S item 10]——注明库、版本、revision 年份、格式。未引用 = 不可复现。
5. **filter 要评估当前准确性**——数据库界面与索引常变，旧 filter 可能失效 [MECIR C34]。若目标库内置 ML 分类器（如 Cochrane RCT Classifier），检索式**最好不要**再叠研究设计 filter。
6. **两版本选择**：Cochrane 为 MEDLINE 提供 RCT filter 的**两个版本**——sensitivity-maximizing（召回最大）与 sensitivity- and precision-maximizing（召回+精度平衡）。推荐流程：先用 sensitivity-maximizing 版；若召回记录数不可控，改用 sens+prec 版 [TS §3.6.1]。本库收录 sensitivity-maximizing 版；平衡版见 TS §3.6 / ISSG。

---

## Cochrane HSSS — MEDLINE RCT filter, sensitivity-maximizing, **PubMed format**

**来源**：Cochrane Handbook v6.5 Box 4.4.a — "Cochrane Highly Sensitive Search Strategy for identifying randomized trials in MEDLINE: sensitivity-maximizing version (2008 revision); PubMed format"。引用时写：*Cochrane HSSS 2008 sensitivity-maximizing RCT filter, PubMed format (Handbook v6.5 Box 4.4.a)*。

```
#1  randomized controlled trial [pt]
#2  controlled clinical trial [pt]
#3  randomized [tiab]
#4  placebo [tiab]
#5  drug therapy [sh]
#6  randomly [tiab]
#7  trial [tiab]
#8  groups [tiab]
#9  #1 OR #2 OR #3 OR #4 OR #5 OR #6 OR #7 OR #8
#10 animals [mh] NOT humans [mh]
#11 #9 NOT #10
```

PubMed 语法注释（原文照录）：
- `[pt]` = Publication Type term
- `[tiab]` = word in the title or abstract
- `[sh]` = subheading
- `[mh]` = Medical Subject Heading (MeSH) 'exploded'

> `#11` 是最终结果集。`#10 → #11` 的 `NOT` 是**经验证过滤器内部的动物排除段**——这是 methodology §2.3「NOT 默认禁用」的唯一白名单例外（linter L8 放行 filter 内 NOT）。

---

## Cochrane HSSS — MEDLINE RCT filter, sensitivity-maximizing, **Ovid format**

**来源**：Cochrane Handbook v6.5 Box 4.4.b — "…sensitivity-maximizing version (2023 revision); Ovid format"。引用时写：*Cochrane HSSS 2023 sensitivity-maximizing RCT filter, Ovid format (Handbook v6.5 Box 4.4.b)*。

```
1  exp randomized controlled trial/
2  controlled clinical trial.pt.
3  randomized.ab.
4  placebo.ab.
5  drug therapy.fs.
6  randomly.ab.
7  trial.ab.
8  groups.ab.
9  1 or 2 or 3 or 4 or 5 or 6 or 7 or 8
10 exp animals/ not humans.sh.
11 9 not 10
```

Ovid 语法注释（原文照录）：
- `exp` = Medical Subject Heading (MeSH) 'exploded'
- `/` = Medical Subject Heading (MeSH)
- `.pt.` = Publication Type term
- `.ab.` = word in the abstract
- `.fs.` = 'floating' subheading（不论挂在哪个 MeSH 上都检索该副主题词）
- `.sh.` = MeSH term not 'exploded'

> **PubMed 版 vs Ovid 版不是符号替换关系**——两版是不同 revision（2008 vs 2023）、不同宿主语法，逐字维护。导出到 PubMed 用 Box 4.4.a，导出到 Ovid MEDLINE 用 Box 4.4.b，**不要拿一版机械改符号充当另一版**（呼应 methodology §3.3 受控词禁符号替换）。

---

## 其他验证过滤器（本库未展开，指向权威源）

- **Embase RCT filter (2023 revision)**：Cochrane Handbook Box 4.4.c（Embase.com 格式）/ 4.4.d（Ovid 格式），adapted from Glanville et al (2019)，35 行完整策略（含 `random*:ti,ab,tt`、`(double OR single …) NEXT/1 (blind …)`、`(assign* OR match …) NEAR/6 (…)`，末段排除非随机研究）。导出到 Embase 时**整段照录 Box 4.4.c/4.4.d**，勿从 MEDLINE 版改写。
- **MEDLINE 平衡版（sensitivity- and precision-maximizing）**：见 TS §3.6 / ISSG——命中数不可控时替换 sensitivity-maximizing 版。
- **CINAHL Plus RCT filter**：Cochrane 为 CINAHL 开发的 CENTRAL 用过滤器 [Hb §4.4.7]；EBSCOhost 宿主，具体式见 ISSG。

## ISSG Search Filters Resource（filter 权威索引）

**URL**：`https://sites.google.com/a/york.ac.uk/issg-search-filters-resource`（RCT filter 直达页：`.../home/rcts`）。由 InterTASC Information Specialists' Sub-Group 维护，**收录并批判性评价**了 SR / RCT / 非随机研究 / 诊断准确性 / 质性等过滤器，跨多个库和服务商 [Hb §4.4.7]。

**LLM 用法**：需要某研究设计过滤器而本库未收录时，**指向 ISSG 取验证过的过滤器 + 引用**，而非自造。ISSG 页面对每个 filter 附有性能评价（sensitivity/precision/specificity），选型时读它。Cochrane Handbook 明确说这些过滤器「there are also launch links for them on the ISSG Search Filter Resource website」。

---

## 生成器落法（机械挂载，非 LLM 现写）

| 环节 | 归属 |
|---|---|
| 是否需要研究设计过滤器 | **LLM 判断 + 规则**：综述纳入标准是否限定研究设计？护栏：CENTRAL 不加、有 ML 分类器时不叠 |
| 选哪个过滤器、哪个版本（sens vs sens+prec） | **LLM/规则 + 引用 ISSG**：按档位哲学（methodology §5）与目标库选 |
| **过滤器内容** | **机械模板（整段照录本库/ISSG）**——绝不 LLM 现编 RCT 段 |
| 过滤器语法适配到目标宿主 | **机械转译**（用语法卡的字段/算符映射；PubMed 版 vs Ovid 版是两套罐装块，非改符号） |
| filter 引用来源写入 PRISMA-S item 10 | **机械填充** |

---

*溯源：验证过滤器纪律、CENTRAL 不加 filter、两版本选择、ISSG、评估当前准确性、ML 分类器 [Hb §4.4.7, MECIR C34, TS §3.6.1]｜Box 4.4.a/4.4.b 逐字照录 [Cochrane Handbook v6.5，2026-07-16 对原 PDF 核对]｜filter 引用 [PRISMA-S item 10]｜自造过滤器反面教训 [R3 P1-2]。禁读任何既有 SR/综述 Skill。*
