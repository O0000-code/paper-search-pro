# 知网 CNKI（中国知网，订阅；专业检索式为核心交付形态）

> 语法卡 · 统一字段格式（13 spec §4）。中文原生库；深链 **C 档**（无稳定无状态深链，kns 入口对非浏览器 302→滑块验证码）→ 核心交付=粘贴进「专业检索」框的检索式。**★中文语法不是西式布尔的翻译**（`%=` 相关匹配 + 字段内 `+`/`-` 方向反转）。无西式可爆炸叙词表 → 受控词 `not_applicable`（中文医学题受控词双轨走 SinoMed/CMeSH，见 `sinomed.md`）。

```yaml
platform: "知网 CNKI"
host: "中国知网 / kns.cnki.net"
database: "CNKI 学术期刊/学位论文等（专业检索）"
access: subscription                 # 订阅 + 验证码墙
field_tags:                          # 专业检索字段码（大写，英文半角）
  title: "TI"                        # 题名（含完整串）
  title_abstract: "TKA"              # 篇关摘=篇名+关键词+摘要（快报2.0/新版专业检索字段，CNKI 最接近 [tiab] 的合并字段；旧版详细版手册字段集无此码）；主题 SU 另覆盖宽概念
  abstract: "AB"
  keyword: "KY"                      # 关键词（精确相等）
  subject_heading: "SU"             # 主题（官方推荐 %= 相关匹配；非西式可爆炸叙词表）
  full_text: "FT"                    # 全文
  author: "AU"
  first_responsible: "FI"
  corr_author: "RP"
  affiliation: "AF"
  journal: "JN"                      # 文献来源
  reference: "RF"
  pub_year: "YE"                     # 支持 BETWEEN/>/</>=/<=
  fund: "FU"
  class_code: "CLC"                  # 分类号（可 % 前串匹配）
  issn: "SN"
  cited_freq: "CF"
  pub_type: null                     # 文献类型经界面限定，非专业检索字段码
  subheading: null
  all: "FT"
match_operators:                      # ★匹配运算符（CNKI 特有）
  exact: "=  (KY/AU/JN 精确相等；TI/AB/FT/RF 为『含完整串』)"
  contains_split: "%  (含完整串或分词，AB % 计算机教学 命中含『计算机』和『教学』不分序)"
  relevance: "%=  (相关匹配，主题 SU 官方推荐；纳入相关表达，语义≠西式精确布尔)"
  compare: "BETWEEN('a','b') / > / < / >= / <=  (YE/CF)"
boolean:
  and: "AND"                         # 字段间逻辑
  or: "OR"
  not: "NOT"
  case: "uppercase, 英文半角"
  field_internal: "字段内多值（复合运算符，官方手册 §1.2.5.6）：* = AND，+ = OR，- = NOT；算符前后须空格（★+ 直觉像 AND 实为 OR，方向反陷阱，B-12；真正的字段内 AND 是 *）"
proximity:                            # 位置/频次算符：仅 TI/AB/FT（尤 FT 全文；官方 §1.2.5.7）
  same_sentence_noN: "'#'=同句('STR1 # STR2')；'%'=同句且STR1在前('STR1 % STR2')——无N值位置描述符（官方§1.2.5.7）；% 在字段码与值之间另为匹配符（同符号异角色）"
  unordered: "/NEAR {n}"            # 同一句中、间隔 ≤n 词（官方§2.1.3.7 含「同一句」前置约束）
  ordered_prev: "/PREV {n}"         # 前词在前 ≤n
  ordered_aft: "/AFT {n}"           # STR1 在 STR2 后面且间隔＞n 个字词（官方§2.1.3.7 例5；非"≤n"）
  same_sentence: "/SEN {n}"         # 同一段中、句序号差 ≤n（官方§2.1.3.7；非"同句"）
  same_para: "/PRG {n}"             # 同段，段差 ≤n
  freq: "$N"                         # 词至少出现 N 次（FT='大数据 $5'）
  n_family: "gap"                    # n = 词间间隔（§5.1 cnki n_semantics=gap）
  field_limit: ["FT", "TI", "AB"]   # 仅这三字段内两个值限定，不接多值
  constraints: ["single_field_two_values_only", "half_width_quotes_required"]
truncation:
  multi_char: null                   # ★CNKI 无 */? 词内截词（走 %= 相关匹配 + 位置算符）；注意 * 非截词符但是字段内 AND 复合算符（见 boolean.field_internal），勿判「CNKI 出现 * 必错」
  single_char: null
  zero_or_one: null
  min_chars_before: null
  phrase_truncation: "n/a"
phrase:
  quote: "半角单引号 ''"             # 检索值+算符须用英文半角单引号包住（FT='人工智能 /SEN 1 推荐算法'）
  exception: "中文无截词/词干化；勿加 */?（A-4/B-11）"
controlled_vocab:
  name: null                         # SU 是中文分词相关匹配，非可爆炸叙词表、无免费查表 API
  explode: null
  no_explode: null
  major: null
  subheading: null
  verification: not_applicable       # 无受控词表可核（13 spec §1.2 标 🟦语法已验-无受控词表）；中文医学题受控词双轨走 SinoMed(CMeSH)
line_search:
  supported: true
  syntax: "高级检索最多 7 行条件组合；专业检索直接写复合式"
  history_cap: 7                      # 高级检索行上限
special_chars_escape: "★全英文半角铁律：括号/逗号/引号/逻辑符混入中文标点直接报『参数错误』；字段码大写"
deep_link:
  tier: "C"
  url_kind: "paste_only"
  url_template: null                 # 无稳定无状态深链
  note: "kns 入口对非浏览器客户端 302→/verify/home?captchaType=blockPuzzle（滑块验证码）。交付形态=粘贴进「专业检索」框的检索式本身，不依赖 URL（C-12/C-14 只观测不破解）。"
  verified_http: "302 -> 验证码页"
  verified_date: "2026-07-16"
source_url:
  - "https://library.sysu.edu.cn/sites/default/files/attachments/2023-10/中国知网使用手册-详细版_1.pdf"   # 详细版手册 §1.2.5.2/§1.2.5.6/§1.2.5.7（旧字段集 + 复合运算符 * / 位置描述符 # %）
  - "https://library.gzucm.edu.cn/__local/0/39/86/A976E276D464E8B25AB5A531607_579D802A_5734FC.pdf"
  - "https://wlxy.hbnu.edu.cn/_upload/article/files/c8/1e/6ee8cd4c476e80fc1d482eb9a351/a17b2405-4aac-4d1c-8130-beaa9af579a6.pdf"   # 全球学术快报2.0 Web版使用手册 §2.1.3.2（新字段集含 TKA=篇关摘, 2026-07-16 verified）
verified_date: "2026-07-16"
gotchas:
  - "★中文语法非西式布尔翻译：主题 SU 用 %=（相关匹配，纳入相关表达，语义≠精确布尔，B-11）"
  - "★字段内复合算符（官方§1.2.5.6）：* = AND、+ = OR、- = NOT，算符前后须空格——+ 方向反直觉（=OR 非 AND，B-12），真正的字段内 AND 是 *；块内同义词用字段间 OR（SU %= x OR SU %= y）"
  - "★全英文半角铁律：符号/字母混中文标点即报错；字段码大写；检索值用英文半角单引号包住"
  - "★CNKI 无词内截词/词干化：? 不支持、* 不是截词符（A-4）——但 * 是字段内 AND 复合算符（空格分隔，见 boolean.field_internal），勿因『无截词』误判 CNKI 出现 * 必错；用 % / %= 与位置算符替代截词（区别于 SinoMed 的 ?/% 词内通配）"
  - "★同符号异角色：% 在字段码与值之间=匹配符（AB % 计算机教学，含/分词），在两值之间=同句位置描述符（'STR1 % STR2' 同句且 STR1 在前，官方§1.2.5.7）；# 是同句位置描述符简写（'STR1 # STR2' 同句）；位置算符导出默认不用"
  - "位置算符 /NEAR /PREV /AFT /SEN /PRG / $N 仅对单字段（TI/AB/FT，尤 FT）内两个值限定，不接多值；n = gap"
  - "深链 C 档：无稳定无状态深链（302→验证码）→ 交付=粘贴进「专业检索」框；受控词双轨走 SinoMed(CMeSH)"
```

## 证据与说明（prose）

### 范围与角色
知网 CNKI（订阅 + 验证码墙）。深链 **C 档**：R4 §2.7 实测 `kns.cnki.net/kns8s/defaultresult/index?...` 返回 **302 → `/verify/home?captchaType=blockPuzzle`**（滑块验证码 + 会话 cookie），对非浏览器客户端强制验证 → **核心交付 = 粘贴进「专业检索」框的检索式本身**，不依赖 URL（仅观测验证码存在，未研究绕过，C-12/C-14）。

### 专业检索字段 / 匹配符（官方手册）
表达式一般式 `<字段><匹配运算符><检索值>`。字段（详细版手册字段集）：`SU`=主题、`TI`=题名、`KY`=关键词、`AB`=摘要、`FT`=全文、`AU`=作者、`FI`=第一责任人、`RP`=通讯作者、`AF`=机构、`JN`=文献来源、`RF`=参考文献、`YE`=年、`FU`=基金、`CLC`=分类号、`SN`=ISSN、`CN`=统一刊号、`IB`=ISBN、`CF`=被引频次。**新版/快报2.0 专业检索另补 `TKA`=篇关摘（=篇名+关键词+摘要，CNKI 最接近 `[tiab]` 的合并字段）**，官方例 `SU %= '知识管理' OR TKA = '知识管理'`（快报2.0 手册 §2.1.3.2；旧详细版字段集无此码）。匹配符：`=`（KY/AU/JN 精确相等；TI/AB/FT/RF 含完整串）、`%`（含完整串或分词，`AB % 计算机教学` 命中含「计算机」和「教学」不分序）、**`%=`（相关匹配，主题 `SU` 官方推荐）**；比较符 `BETWEEN('2010','2018')`/`>`/`<`/`>=`/`<=`（YE/CF）。

### ★布尔方向反转（B-12）+ 半角铁律
- **字段间逻辑** `AND`/`OR`/`NOT`（`KY=知识管理 AND AU=邱均平`）。
- **字段内多值（复合运算符，官方手册 §1.2.5.6）** `*`=AND、`+`=OR、`-`=NOT，**算符前后须空格**（官方例：`FT = 催化剂 * 反应率`=同时含两词；`KY = 铝合金 + 钛合金`；`KY = 大数据 - 人工智能`）。官方组合例：`SU=('经济发展'+'可持续发展')*'转变'-'污染'`（=「经济发展 OR 可持续发展」**AND**「转变」**NOT**「污染」）。**方向陷阱**：`+` 直觉像「加/AND」实为 OR——把该 AND 的概念误用 `+` 会塌缩成 OR（B-12）；**真正的字段内 AND 是 `*`**（不是「相邻引号串」——官方从无「裸相邻=AND」规则，AND 一律要显式 `*` 且前后空格；「相邻引号串=AND」是官方引文转录中 `*` 被吞后的误读，已废止）。**推荐块内同义词用字段间 OR**（`SU %= x OR SU %= y`）、**块间 AND**，回避字段内算符（方向反直觉、`*` 与截词符同形易误读，字段间算符可读性与可校验性都更好）。
- **★全英文半角铁律**：所有符号与英文字母必须英文半角输入（括号/逗号/引号混入中文标点直接报「参数错误/服务器不存在此用户」）；字段码大写；检索值+算符须用**英文半角单引号**包住（`FT='人工智能 /SEN 1 推荐算法'`）。

### 位置 / 频次算符（仅 TI/AB/FT，尤 FT 全文；官方 §1.2.5.7）
`#`（`'STR1 # STR2'` 同句简写）、`%`（`'STR1 % STR2'` 同句且 STR1 在前——**值间位置描述符，≠字段匹配符 `%`，同符号异角色**）、`/NEAR N`（**同一句中**、间隔≤N词——官方含「同一句」前置约束）、`/PREV N`（前词在前≤N）、`/AFT N`（**STR1 在 STR2 后面且间隔＞N 个字词**——官方§2.1.3.7 例5「间隔超过 N 个字词」，语义是"超过 N"非"≤N"，且方向为后词在前词之后）、`/SEN N`（**同一段中、句序号差≤N**——官方语义是"同段句序号差"，非"同句"）、`/PRG N`（同段、段差≤N）、`$N`（词至少出现 N 次）。**这些仅对单字段内两个值限定，不接多值**；`/NEAR`家族 n = gap（§5.1）；`#`/`%` 无 N 值。

### 受控词表（`not_applicable`）
CNKI 主题 `SU` 走中文主题/分词相关匹配（`%=`），**非西式可爆炸叙词表、无免费查表 API** → 不做机械核验，13 spec §1.2 标 🟦 语法已验(无受控词表)。**中文无词内截词/词干化**：`?` 不支持、`*` 不是截词符，勿把 `*`/`?` 当词内通配加在词上（A-4/B-11）——但注意 `*` 在 CNKI 是**字段内 AND 复合算符**（空格分隔，见上「布尔方向反转」），非「无意义/非法字符」；这也与 SinoMed 的 `?`/`%` 词内通配不同，两套中文语法勿平移。若走 **SinoMed**，则用 CMeSH 受控词双轨（🟨 词表待核，`llm_suggest_only`，见 `sinomed.md`）。

### 深链（C 档）
无稳定无状态深链（302→验证码）→ 交付=粘贴进「专业检索」框的检索式本身；只观测不破解（C-14）。
