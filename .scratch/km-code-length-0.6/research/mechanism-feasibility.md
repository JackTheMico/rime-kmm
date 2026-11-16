# 票 03 — 降码长新机制在 librime 上的可行性

> 研究代理：机制　读取/抓取日期：**2026-11-16**
> Context pointer：`../issues/03-mechanism-feasibility.md`；地图 `../map.md`
> 标注规则：一手源码/文档标 `[来源: URL, 抓取 2026-11-16]`；项目内文件标 `[来源: 项目文件 xxx, 读取 2026-11-16]`；推断标「我的分析」；无法确认标「未确认」。**配置键与源码文件名均亲自抓取核对，未凭训练记忆。**

---

## ① 结论先行：可行性排序表

排序依据 = 技术可行性 × 是否守住「纯原生零 Lua」 × 对**并击击/字**口径的真实贡献（而非仅物理键/字口径的账面降幅）。

| 排名 | 机制 | 落地代价 | 破「零 Lua」? | 对并击码长口径的真实贡献 | 一句话判据 |
| :-- | :--- | :--- | :--- | :--- | :--- |
| 1 | **扩充长词简码**（纯词库/编码，不动引擎） | 改词库 + 跑现有 `km_*` 工具 | 否 | **高**（一词一击 → `cw/L` 极小）但受一击槽位总量硬约束 | 天花板是**码位**，不是词库；与票 01 强耦合 |
| 2 | **顶功参数微调**（`auto_select_pattern`/`max_code_length`/`auto_clear`） | 改 schema 几行 | 否 | **存疑/偏低**：省的是物理空格键，并击口径里空格选词本不算一击 | 原生键确实存在，但 auto_select 要求「唯一候选 + 到达输入末尾」，对「有延伸码」无能为力 |
| 3 | **`table_translator/enable_sentence` 整句上屏** | 改 schema 一行 | 否 | 中（提升 `L`、打词率）但**重码/口径失真风险高** | 原生可开；恢复 `sentence` 候选，与 auto_select 语义冲突需实测 |
| 4 | **`contextual_suggestions` 上下文联想** | 改 schema + 装 grammar 插件 | 否（但需外部插件） | 低 + **口径失真** | 核心有开关无 grammar 实现（`grammar.cc` 未确认存在），开箱不即用 |
| 5 | **Lua 预测联想**（`lua_translator`） | 写 Lua + 词库/模型 | **是** | 低 + 口径失真 | 技术上最灵活，但直接违背项目红线 |
| 6 | **改引擎写 predictor / commit processor** | 编译 librime fork | 否（但失「原生」） | 取决于实现 | 最重；且 gear 源码无 predictor 骨架可继承 |

**总判断**：真正能低成本推进 0.6–0.7 的是**排名 1（词库/编码）**；「新机制」里只有排名 2、3 勉强原生可行，且对**并击口径**的贡献远不如对 52dazi 物理键口径那么直观；联想/预测（排名 4–6）会引入**口径失真**——预测出的字若不计费，账面码长会虚假下降。详见 ④。

---

## ② 逐机制分析

### 2.1 顶功 / 自动上屏

#### 2.1.1 一手确认的配置键（`speller.cc`）

抓取官方 `src/rime/gear/speller.cc`，构造函数逐字读取以下键 `[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/speller.cc, 抓取 2026-11-16]`：

| 配置键 | 类型 | 语义（源码依据） |
| :--- | :--- | :--- |
| `speller/alphabet` | string | 参与拼写的字符集合 |
| `speller/delimiter` | string | 分隔符 |
| `speller/initials` / `finals` | string | 声母/韵母类判定（用于 `expecting_an_initial`） |
| `speller/max_code_length` | int | 最大码长；>0 时启用定长顶屏 |
| `speller/auto_select` | bool | 唯一候选自动确认 |
| `speller/use_space` | bool | 空格是否参与拼写 |
| `speller/auto_select_pattern` | string(regex) | 自动上屏的**额外正则约束** |
| `speller/auto_clear` | string | `auto`/`manual`/`max_length`，无候选时清输入 |

#### 2.1.2 `auto_select` 的精确语义（关键，纠正一个常见误解）

`AutoSelectUniqueCandidate()` 的逻辑（源码逐字要点）`[来源: 同上, 抓取 2026-11-16]`：

```
bool unique_candidate = seg.menu->Prepare(2) == 1;   // 必须"只有一个候选"
if (!unique_candidate) return false;
...
if (auto_select_pattern_.empty())
  matches = (max_code_length_ == 0) || reached_max_code_length(cand, max_code_length_);
else {
  string code(input.substr(cand->start(), cand->end()));
  matches = boost::regex_match(code, auto_select_pattern_);   // 正则匹配完整编码
}
if (matches && is_auto_selectable(cand, input, delimiters_))
  ctx->ConfirmCurrentSelection();
```

而 `is_auto_selectable()` 要求三条同时成立：`cand->end() == input.length()`（候选到输入末尾）、候选类型为 `table/user_table/simple_candidate`、输入从候选起点起**无分隔符**。`[来源: 同上, 抓取 2026-11-16]`

**结论（我的分析）**：
- `auto_select_pattern` **不是「放宽唯一性」的开关，反而是「限定哪些编码才允许自动上屏」的闸门**——它在唯一候选基础上再加一层 regex 匹配。用它做「顶功」= 只对匹配 pattern 的码自动上屏，并不能让多候选强制上首选。
- 项目 `jianma_reference.md` 写「用 `auto_select: true` 且没有 `auto_select_pattern`，librime 只在候选唯一、且输入无法再延伸时才顶屏」——**与源码一致**。`[来源: 项目文件 docs/reference/jianma_reference.md §2, 读取 2026-11-16]`
- 对空明码的「有延伸码」（`jianma_reference` §5 的 2411 个码，必须按空格/继续打才上屏）：auto_select 的三条件里「到达输入末尾」和「唯一候选」都不成立，**原生 auto_select 无法让这类码免空格顶屏**。这正是空明码「一击上屏率」的天花板所在。

#### 2.1.3 更激进的原生顶功路径（可挖点）

1. **`speller/max_code_length`（定长顶屏）**：`AutoSelectAtMaxCodeLength()` 在输入新 initial **之前**调用；当已选候选达到最大码长且 `is_auto_selectable` 时 `ConfirmCurrentSelection()`。源码注释即为「handles input beyond max_code_length when auto_select is false」。`[来源: 同上, 抓取 2026-11-16]`——这是原生唯一的「非唯一候选也可顶屏」机制，但**要求码长固定**，空明码是变长编码，套用会截断长词（我的分析：不适用）。
2. **内部 option `_auto_commit`**：`AutoSelectPreviousMatch()` / `FindEarlierMatch()` 里检查 `ctx->get_option("_auto_commit")`，为真时自动选择后立即 `ctx->Commit()`（真正上屏并清空输入），否则只 `ConfirmCurrentSelection`。`[来源: 同上, 抓取 2026-11-16]`——这是「顶功真正 commit」的隐藏开关，但它是**下划线前缀的 schema-local 内部 option，非公开配置键**；能否通过 `key_binder/set_option` 稳定触发**未确认**，需实测。
3. **`speller/auto_clear`**：只负责无候选时清空，不产生上屏，非顶功键。`[来源: 同上, 抓取 2026-11-16]`

#### 2.1.4 chord_composer 与 key_binder 侧

- `chord_composer` 配置键（本地源码副本 + 抓取交叉一致）：`alphabet`、`use_control/alt/shift/super/caps`、`finish_chord_on_first_key_release`、`algebra`、`output_format`、`prompt_format`、`speller/delimiter`、`bindings`（经 `KeyBindingProcessor::LoadConfig`）。唯一 commit 类 action 是 **`commit_raw_input`**（把 raw_sequence 直接 `set_input` + `Commit`）。`[来源: 项目内本地副本 chord_composer.cc, 读取 2026-11-16; 与 https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/chord_composer.cc 配置键交叉一致, 抓取 2026-11-16]`
- `finish_chord_on_first_key_release`：默认 false（所有键松开才结算并击）；设 true 首个键松开即结算——影响手感/手速，**不改变码元数与击数**（我的分析）。
- `key_binder` 的 when 条件含 **`predicting`**（显示预测候选时）、`paging`、`has_menu`、`composing`、`always`；动作仅有 `send`/`send_sequence`/`toggle`/`set_option`/`unset_option`/`select`，**没有 `commit`/`commit_text` 动作**。`[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/key_binder.cc, 抓取 2026-11-16]` 要上屏只能 `send: space` 交给 selector。

> ⚠️ 来源可靠性：抓取的 `chord_composer.cc` / `key_binder.cc` 正文中混入了疑似第三方 fork 片段（`ProcessSyntheticKey`、`StreamingChordProcessor`、`ReinterpretPagingKey`、繁体中文注释），这些**不在干净抓取的 `speller.cc` 和官方 gear 目录清单中**。本报告只采信两份源码**一致的配置键集**；上述 fork 片段标「未确认」，不作结论依据。

#### 2.1.5 有没有现成方案？

空明码自身即现成方案：`kongmingmas.schema.yaml` 已用 `speller.auto_select: true` + `chord_composer/algebra` 把空格并击映射为唯一码，实现「一简字/一简词打完即上屏」。项目 `docs/kongmingma-space-chord-research.md` 已用真实 librime（1.17.0）实测 `a=`→「地」、`a_=`→「等」自动上屏。`[来源: 项目文件 docs/kongmingma-space-chord-research.md §3, 读取 2026-11-16]` 即：**顶功机制项目已在用，剩余空间是「扩大零延伸唯一候选的覆盖面」，本质是词库/编码工作，不是新配置键。**

---

### 2.2 短语 / 整句一键上屏（扩充长词简码）

#### 2.2.1 现状盘点（项目文件一手）

- 词库 `kongmingmas.dict.yaml` 1,661,029 条；`≤3 码元独立词条` 4,895，其中「一击上屏」1,396 码、`零延伸·多候选` 196 码、`有延伸` 2,411 码。`[来源: 项目文件 docs/reference/jianma_reference.md §1, 读取 2026-11-16]`
- 长词简码实例：`*Q`=这是一个、`*B`=绝大多数、`8b`=中华人民共和国、`@J`=最重要的是、`Ue`=毛泽东思想等（多为 3–7 字，2 码元=1 击）。`[来源: 同上 §3, 读取 2026-11-16]`
- `*X` 族 21 个、`@X` 族 34 个，是已用的「符号前缀 + 一字母」一击槽位。`[来源: 同上 §3, 读取 2026-11-16]`

#### 2.2.2 靠扩充长词简码能推进到什么程度

**模型**（外部报告估算）：`K = (1-p)·c1 + p·cw/L`，`cw=⌈m/2⌉`，`m`=词平均码元数。`[来源: 项目文件 docs/reports/52dazi_code_length_research.md §4, 读取 2026-11-16]`

- 长词简码一旦做到「一词一击」（`m≤2` → `cw=1`），摊到每字仅 `cw/L`：7 字词 1 击 → 0.14 击/字。**理论上扩充长词简码同时抬高打词率 `p` 与词长 `L`，是对 `K` 最有效的杠杆**（我的分析，代入 §4 模型）。
- 但模型同时给出硬前提：**词平均码元数必须 ≤2**，否则 `cw≥2`、即使 100% 打词率 `K` 也 ≥1，永远到不了 0.6–0.7。`[来源: 同上 §4.4, 读取 2026-11-16]`

#### 2.2.3 瓶颈：是码位，不是词库

**结论（我的分析）：瓶颈是一击槽位的总量与分配，不是词库规模。** 依据：

1. 一次并击 = 左右手各一码元，`chord_composer/algebra` 把物理并击映射到有限码元集；一击可表达的独立编码总数有上限（60 码元的两两组合，再受左手/右手规则与 algebra 约束）。**这正是票 01「一击码面容量」的题**——本票不重复计算，但明确：长词简码与单字、二字词**抢同一批一击槽位**。
2. 现状一击上屏 1,396 码 + 多候选 196 + 有延伸 2,411，`≤3 码元` 槽位已用 4,003/4,895；`*X`（21）、`@X`（34）等族也基本铺满。新增一个高价值长词，必须**置换**一个现 occupant——零和博弈。
3. 词库有 166 万条，长词素材不缺；缺的是「能让长词一击上屏且零延伸唯一」的编码位。把长词挂到「有延伸」码上，反而会因需按空格而多一击（或至少不自动上屏）。

**可推进到的程度（我的估算）**：在不改引擎、不突破一击槽位总量的前提下，「扩充长词简码」能把已有高频长词尽量换成一击码，但边际收益递减；其上限由票 01 给出的一击码容量决定。它是**已达收益较多、剩余提升有限**的手段——性价比仍高于任何引擎改造。

---

### 2.3 联想 / 预测

#### 2.3.1 librime 有没有 predictor/联想组件？

一手核对结果：

- **gear 目录无 `predictor.cc`、无 `auto_select.cc`**：GitHub API 列目录返回完整文件名清单，含 `speller.cc`/`chord_composer.cc`/`script_translator.cc`/`table_translator.cc`/`poet.cc`/`key_binder.cc`/`history_translator.cc` 等，但**没有 predictor、没有 commit 专用 processor**。`[来源: https://api.github.com/repos/rime/librime/contents/src/rime/gear, 抓取 2026-11-16]`
- **有 `poet.cc`**（造句）+ `contextual_suggestions`（上下文联想加权），但都在 translator 层，不是独立 predictor processor。`[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/poet.cc, 抓取 2026-11-16]`
- **有 `grammar.h` 抽象接口**（`Grammar::Require("grammar")`、`Evaluate()`），但整棵源码树只找到 `grammar.h`，**未找到 `grammar.cc` 实现**——即核心 librime 没有 grammar 组件实现，需插件提供。`[来源: https://api.github.com/repos/rime/librime/git/trees/master?recursive=1, 抓取 2026-11-16（返回被截断，结论限于可见条目）]` → grammar 实现位置：**未确认**。
- `Context` API 有 `Commit()`、`GetCommitText()`、`ConfirmCurrentSelection()`、`commit_history()`、`GetCandidatePreview()` 等，**无 predictor/prediction 专用接口**。`[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/context.h, 抓取 2026-11-16]`
- 候选类型：`completion`/`user_table`/`table`/`sentence`，**未见 `prediction` 候选类型**；`key_binder` 的 `when:predicting` 依赖 segment tag `prediction`，该 tag 由谁打**未确认**（疑为第三方组件）。`[来源: table_translator.cc / key_binder.cc, 抓取 2026-11-16]`

**小结（我的分析）**：librime 核心**没有开箱即用的「智能预测上屏」processor**。最接近的是 `translator` 层的整句（`enable_sentence`）和上下文加权（`contextual_suggestions`），且后者还依赖核心缺失的 grammar 插件。社区存在第三方 predictor 插件（如 rime-predict），但本次抓取 `hchhwtW/rime-predict` 返回 404，**未取到一手实现，标未确认**。

#### 2.3.2 原生联想的配置键（一手确认）

`translator_commons.cc` 的 `TranslatorOptions` 读取 `[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/translator_commons.cc, 抓取 2026-11-16]`：

- `translator/contextual_suggestions`（bool）、`enable_completion`、`strict_spelling`、`initial_quality`、`max_sentences`（钳制 1–100）、`sentence_cutoff_threshold`、`delimiter`、`tag`/`tags`、`preedit_format`/`comment_format`、`disable_user_dict_for_patterns`、`dictionary_exclude`。

`table_translator.cc` 另读 `[来源: https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/table_translator.cc, 抓取 2026-11-16]`：

- `translator/enable_charset_filter`、`enable_sentence`、`sentence_over_completion`、`enable_encoder`、`encode_commit_history`、`max_phrase_length`、`max_homographs`。

`contextual_suggestions` 的生效链：`Query()` 里 `if (contextual_suggestions_) return poet_->ContextualWeighted(...)`；而 `Poet::ContextualWeighted` 首行 `if (!translator->contextual_suggestions() || !grammar_) return translation;`——**没有 grammar 组件则联想直接空转**。`[来源: poet.h / script_translator.cc, 抓取 2026-11-16]`

#### 2.3.3 接入代价分级

| 级别 | 手段 | 能否实现联想/预测 | 备注 |
| :--- | :--- | :--- | :--- |
| 零配置 | 无 | 否 | 默认无预测上屏 |
| 改 schema | `enable_sentence: true` | 部分（整句，靠词频造句） | 原生可用，但与 auto_select/重码冲突需实测 |
| 改 schema + 插件 | `contextual_suggestions: true` + grammar 插件 | 是（上下文加权） | 核心无 grammar 实现，需外部组件；破坏「纯原生」边界 |
| 写 Lua | `lua_translator` + 自研联想/用户词模型 | 是（最灵活） | **破坏零 Lua** |
| 改引擎源码 | 新增 predictor processor / commit processor | 是（最深） | 需 fork + 编译；无现成骨架 |

#### 2.3.4 关键：预测上屏的字算不算「击」？会不会让码长口径失真？

**这是本票最重要的风险提示（我的分析）：**

- 空明码口径铁律：一次并击 = 1 击，`击数 = ⌈码元数/2⌉`，任何击数判断以 `km_chord_model.py` 为准。`[来源: 项目文件 map.md §Notes / tools/README.md §1, 读取 2026-11-16]`
- 预测/联想产生的字，其「击」来自**前文已打的码**，本身通常只需一个确认键（甚至自动上屏）。若按现有口径统计：
  - **方案 A（不计击）**：预测字增加分母「字数」但不增加分子「击数」→ 平均码长**账面下降**。这是**口径失真**：降的是统计量，不是编码效率；用户并没少做并击动作。
  - **方案 B（计一击）**：把确认预测候选的按键算 1 击 → 多个预测字可共摊 1 击（如一次确认上屏 5 字词 → 0.2 击/字），此时确为**真实**效率提升，但也意味着「预测上屏」必须按一次物理/并击动作计费，与 52dazi「打词率/效率」口径才自洽。
- 52dazi 侧有旁证：其「打词率 = 打词的字数 / (总字数 + 回改)」，「效率 = 文段字数 / 上屏次数」（20 字 10 词 → 200%）。`[来源: 项目文件 docs/reports/52dazi_code_length_research.md §2.3, 读取 2026-11-16]` 说明**多字一次上屏本就被该口径承认为效率提升**——但前提是那「一次上屏」确实发生了一次输入动作。
- **结论**：预测上屏是否计「击」必须在验收协议（票 04）里**先定口径再谈机制**。若不计击而直接用现口径报码长，任何联想方案都会给出「达标」的假象。这是引入新机制的**首要破坏面**。

---

### 2.4 代价与破坏面（汇总到 ③）

逐机制的纯原生/反查/简繁/平台影响见下节矩阵。要点先列：

- **反查链**：拼音反查走 `recognizer` 捕获 `` ` `` 前缀 + `chord_composer/FinishChord` 重发 + `reverse_lookup_translator`，注释列查繁体镜像 `kongmingmas_t_rev`。`[来源: 项目文件 kongmingmas.schema.yaml §62–89, 读取 2026-11-16]` 任何改 `chord_composer/algebra`、`speller/alphabet`、translator 链的机制都**必须回归测试反查**。
- **简繁镜像**：词库改动需 `--with-trad` 同步 `kongmingmas_t.dict.yaml`；`simplifier@reverse_t2s`（tag=`reverse_lookup`）负责候选繁→简。`[来源: 项目文件 tools/README.md / kongmingmas.schema.yaml §80–85, 读取 2026-11-16]`
- **零 Lua 红线**：项目虽有个别 `lua_translator@date_translator`，但核心并击/反查/简繁均为纯内置；新机制若引入 `lua_translator` 联想，会**扩大 Lua 依赖面**，与「拼音反查也是纯内置」的立场冲突。`[来源: 项目文件 kongmingmas.schema.yaml §40–60, 读取 2026-11-16]`
- **平台**：项目只保证 Linux；`contextual_suggestions` 依赖的 grammar 插件、第三方 predictor 插件在 Linux(fcitx5-rime) 的可用性与编译链**未确认**。纯配置/词库方案跨平台无碍。

---

## ③ 代价分级矩阵

| 机制 | 零配置 | 改 schema | 写 Lua | 改引擎源码 | 破零 Lua | 影响反查 | 影响简繁镜像 | 平台限制 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 扩充长词简码 | — | ✓（无需改，纯词库） | — | — | 否 | 需回归 | 需 `--with-trad` 同步 | 无 |
| `auto_select_pattern` / `max_code_length` 微调 | — | ✓ | — | — | 否 | 低（`speller` 层） | 否 | 无 |
| `enable_sentence` 整句 | — | ✓ | — | — | 否 | 需回归 | 否 | 无 |
| `contextual_suggestions` 联想 | — | ✓ | — | —（但需 grammar 插件，偏离「纯原生」） | 否 | 需回归 | 否 | grammar 插件 Linux 可用性未确认 |
| Lua 预测联想 | — | — | ✓ | — | **是** | 需回归 | 否 | Lua 组件需随发行版 |
| 改引擎 predictor/commit processor | — | — | — | ✓ | 否（但失原生） | 高（需重测全链） | 需重测 | 需自建编译链，Linux 为主 |

图例：✓=该级别可落地。「需回归」=不必然破坏，但必须跑反查/简繁回归测试。

---

## ④ 口径影响（专章）

| 机制 | 在 52dazi「物理键/字」口径 | 在本项目「并击击/字」口径 | 是否口径失真 |
| :--- | :--- | :--- | :--- |
| 顶功（免空格自动上屏） | 省 1 个物理空格键 → 账面码长下降 | 空格选词/空格并击在 `km_chord_model` 里不额外增加「击」（`a=` 与 `a` 同为 1 击）→ **几乎不降击数** | 若用物理键口径报「码长达标」，会与并击口径目标错位 |
| 长词简码（一词一击） | 多字一次上屏 → 效率↑ | `cw/L` 随 `L` 增大而减小 → **真实降击数** | 否（前提：该词确为 1 击且零延伸唯一） |
| 联想/预测上屏 | 确认键计入「键数」则效率↑ | 若不把确认动作计为「击」，预测字白送 → **账面虚低** | **是（高风险）**，须在票 04 先定「预测字是否计击」 |

**铁律重申**：map.md 要求「任何击数判断以 `km_chord_model.py` 为准，勿凭肉眼」。`[来源: 项目文件 map.md §Notes, 读取 2026-11-16]` 新机制若改变上屏字的数量但不改变并击动作，必须用该模型重新核算，禁止直接引用 52dazi 的物理键口径数字。

---

## ⑤ 来源清单与未确认项

### ⑤.1 一手来源（均抓取/读取 2026-11-16）

1. `speller.cc`（配置键、auto_select 精确语义、max_code_length、auto_select_pattern、_auto_commit）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/speller.cc
2. gear 目录完整文件清单（无 predictor.cc / auto_select.cc）— https://api.github.com/repos/rime/librime/contents/src/rime/gear
3. 源码树递归清单（仅 `grammar.h`，无 `grammar.cc`）— https://api.github.com/repos/rime/librime/git/trees/master?recursive=1
4. `chord_composer.cc`（配置键、commit_raw_input；正文含疑似 fork 片段，见可靠性声明）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/chord_composer.cc
5. `key_binder.cc`（when:predicting、动作集无 commit）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/key_binder.cc
6. `context.h`（Commit/ConfirmCurrentSelection/commit_history，无 predictor API）— https://raw.githubusercontent.com/rime/librime/master/src/rime/context.h
7. `translator_commons.cc` / `.h`（contextual_suggestions 等配置键）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/translator_commons.cc
8. `table_translator.cc`（enable_sentence 等配置键、候选类型）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/table_translator.cc
9. `script_translator.cc`（contextual_suggestions 生效链）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/script_translator.cc
10. `poet.cc` / `poet.h`（造句、ContextualWeighted 需 grammar）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/poet.cc
11. `grammar.h`（Grammar 抽象接口）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/grammar.h
12. `history_translator.cc`（历史候选，非预测）— https://raw.githubusercontent.com/rime/librime/master/src/rime/gear/history_translator.cc

项目内文件（读取 2026-11-16）：`kongmingmas.schema.yaml`、`docs/reference/jianma_reference.md`、`docs/reports/52dazi_code_length_research.md`、`docs/kongmingma-space-chord-research.md`、`tools/README.md`、`tools/km_chord_model.py`、`map.md`、`issues/03-mechanism-feasibility.md`。

### ⑤.2 来源可靠性声明

- 抓取的 `chord_composer.cc` / `key_binder.cc` 正文混入疑似第三方 fork 片段（`ProcessSyntheticKey`、`StreamingChordProcessor`、`ReinterpretPagingKey`、繁体中文注释），与干净的 `speller.cc`、`translator_commons.cc` 风格不符。**只采信其与本地源码副本一致的配置键集**；fork 片段不作为结论依据。
- `rime.im/docs/` 实际返回反馈页，未取得配置键参考文档；`rime/home` 的 `Configuration.md` 返回 404。故配置键语义一律以 **GitHub 源码**为准。

### ⑤.3 未确认项清单

| # | 未确认项 | 影响 |
| :-- | :--- | :--- |
| 1 | `grammar.cc` 实现是否存在/在哪（核心树未见） | 决定 `contextual_suggestions` 是否开箱即用 |
| 2 | `_auto_commit` 内部 option 能否经 `key_binder/set_option` 稳定触发 | 决定「真正 commit 的顶功」可行性，需实测 |
| 3 | 是否有插件打出 `prediction` segment tag（key_binder `when:predicting` 的触发方） | 决定预测候选与 key_binder 的联动 |
| 4 | 第三方 predictor 插件（rime-predict 等）一手实现与 Linux(fcitx5-rime) 可用性 | 决定排名 4 之外的预测路径 |
| 5 | `enable_sentence: true` 与 `auto_select` + 并击合成键流的实际交互（重码/上屏时机） | 决定排名 3 是否需回退 |
| 6 | 顶功对空明码**并击口径**码长的净贡献 | 决定排名 2 是否值得做；需用 `km_chord_model.py` 实测 |
| 7 | 抓取内容中 fork 片段是否为官方 master 的真实代码 | 来源可靠性；已在 ⑤.2 规避 |

（报告完）
