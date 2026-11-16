# 地图：空明码码长降到 0.6–0.7（击/字）

> Effort slug: `km-code-length-0.6`　Tracker: local-markdown（`.scratch/`）　Charted: 2026-11-16

## Destination

把空明码的**平均码长（并击击/字口径）从 0.8 降到 0.6–0.7**：既让**理论码长可达**该区间，又给出**实测码长逼近**它的可执行方案。终点是一份已拍板的决策集 + 可交接的实施规格，不是直接改好的词库。

## Notes

- **域**：`kmrime` 仓库，空明码并击方案，主战场 `kongmingmas`（160 万精简版）。
- **口径铁律**（项目记忆 + `tools/km_chord_model.py`）：一次并击 = 左右手各一码元 = **1 击**；击数 = ⌈码元数/2⌉。`0`=`asdf`（仅左手）、`7/8/9` 左手三键、`'` 右手单键、`/` 可打出、`X~` 数字大写族永不外借。**任何击数判断以 `km_chord_model.py` 为准，勿凭肉眼。**
- **目标已由用户拍板（2026-11-16）**：①并击击/字口径（非 52dazi 的物理键/字）；②理论可达 + 实测逼近双目标；③四类手段全开——仅优化词库/编码、引导改变打字习惯、引入新机制、结构性重构编码。
- **导航模型**：`K = (1-p)·c1 + p·cw/L`。`c1` 现状 1.269（前 1500 字一次并击出 73.1%），`cw=⌈m/2⌉`，跌破 1 击/字的**硬前提是词平均码元数 m≤2**，`p`=打词率、`L`=词长。详见 `docs/reports/52dazi_code_length_research.md` §4（外部数据一手、模型为估算）。
- **承重证据**：`docs/reports/52dazi_code_length_research.md`（52dazi 官方指标定义 + 榜单实测 + 空明码官方宣称，已由主会话复核原文）；`docs/reports/char_onehit_report.md`（c1 与槽位分配）；`docs/reference/jianma_reference.md`（一击码族清单）。
- **每 session 先读**：本 map → 上述承重证据 → `tools/README.md`。
- **交互风格**：用户指令极简；grilling 票严格一次一问，不一次性倒出多个问题。
- **研究票落点**：`.scratch/km-code-length-0.6/research/<name>.md`，票内留 context pointer。
- **实施阶段已启动（2026-11-16）**：spec 已 solidify（`.scratch/km-code-length-0.6/spec.md`，ready-for-agent）；用 `to-tickets` 拆成 **6 张实施票**，落在 `.scratch/km-code-length-0.6/tickets/01..06-*.md`，与 `issues/` 里的 7 张决策票分开存放。粒度与阻塞边经用户确认：01/02 并行起步 → 03 单族打通 → 04 全族扩容拿 0.7 → 05(冲0.6)/06(全量版) 标 stretch。本地图的票 06/07 是 grilling 决策，已被 spec 吸收，实施请直接取 `tickets/`。**实施进度（2026-11-16）：票 01/02/03/04 已 resolve**（均在隔离方案 `kongmingmas_exp` 上）；票 04 把 603 个无空格干净槽全部挂满，前 1000 二字词词频覆盖率 83.2%→100%、尺子理论码长 0.5806→0.5161（票面验收全过）。**唯一未达的是非票面的「全表加权 K」=0.7495>0.7**，长尾词覆盖是瓶颈 → 交票 05（改 algebra / 长词短语）。剩余 frontier：票 05（冲 0.6，stretch）、票 06（全量版同步决策，stretch）。
- **实施进度（全部 6 票已 resolve，2026-11-16）**：票 01（验尺尺子）、票 02（空槽校验器）、票 03（`!` 族端到端，写 29 词）完成；票 04（全族扩容）把 603 个无空格干净槽挂满，前 1000 二字词词频覆盖 100%、尺子样本理论 0.5161；票 05（冲 0.6）裁决**不可达**——全表 K=0.7495、全码面最优下限 0.6939、需追加 48,299 个一击码（全码面 5.3 倍），新增 `k_target_gap()` 量化函数，结论与另案见 `docs/reports/code_length_06_verdict.md`；票 06（全量版同步）决策**不同步**，理由与分叉事实见 `docs/reports/full_dict_sync_decision.md`。全部改动只在隔离方案 `kongmingmas_exp`，原方案 `kongmingmas` 与全量版 `kongmingma` 一字未动。部署真机复核因沙箱锁限制始终未执行。
- **隔离实验方案**：所有码长实验只在 `kongmingmas_exp{,_t}.{dict,schema}.yaml` 上做，`kongmingmas` 原方案一字不动。部署器写死 `MAIN_SCHEMA=kongmingmas`，实验方案不自动切换用户输入法。

## Decisions so far

<!-- 每关闭一张票追加一行：gist + 链接 -->

- [外部数据与口径基线](../../docs/reports/52dazi_code_length_research.md) — 52dazi「码长」是物理键/字，与并击击/字不可换算；`K=(1-p)c1+p·cw/L`，词码元≤2 是跌破 1 的硬前提。
- [一击码面的物理容量与扩容上限](issues/01-one-strike-capacity.md) — 硬上限 9111，当前 auto 1377，干净空槽 5086；码面不是瓶颈（可扩至 6652 不破长词），零和分配才是。
- [高频词的一击覆盖率缺口](issues/02-word-coverage-gap.md) — 二字词一击覆盖 71%/33%/11%（词数），自洽支撑目标需 83%/92%，结构性缺口大；让槽给词与保单字一击率净和接近相抵。
- [降码长新机制在 librime 上的可行性](issues/03-mechanism-feasibility.md) — 长词简码性价比最高；联想/预测有「预测字是否计击」的口径失真风险，须验收协议先定口径。
- [验收协议：理论与实测如何定义与测量](issues/04-acceptance-protocol.md) — 理论≤0.7 / 实测≤0.8 两条独立线；严格计击（预测字、空格确认均计一击）；理论=跟打器理想码长，实测=日常随机文本；打词率+选重率双约束。
- [一击槽位在「单字」与「词」之间如何取舍](issues/05-slot-tradeoff.md) — 守住前 1500 单字一击（c1=1.269 不恶化）；5086 增量空槽优先挂高频二字词走增量扩容而非存量重排；X~ 永不外借。增量能破 K=0.7，K=0.6 仍需票 06 配合。

## Not yet specified

- **结构性重构的具体形态**：改 algebra、增加并击维度（如三键并击）的理论下限究竟多少，雾太重——票 01 已给出「不改 algebra 可扩至 6652」的天花板，但改 algebra 的极限仍未探，等主策略（票 05/06）定了再决定要不要 ticket。
- **智能预测的语料/模型选型**：票 03 判定核心 librime 无 predictor，需插件/改引擎；除非验收协议放行且用户愿破「零 Lua」，否则暂不 ticket。
- **码长 vs 选重率的具体阈值**：票 04 已定「双约束」方向，但选重率上限、打词率 `p` 下限的具体数值未定——待票 05/06 给出可达范围后再量化。
- **全量版 `kongmingma`（300 万）同步**：票 05 已定「只动 `kongmingmas`、增量挂词」，票 07 将据此定范围；全量版是否纳入由票 07 拍板。

## Frontier（下次 session 从这里取票）

- **实施票 01–06 全部 resolve**。本 effort 的 plan 阶段（决策票 01–07）与 implement 阶段（实施票 01–06）均已完成。
- 若用户决定继续冲 0.6：先立**另案 A 的可行性研究票**（静态枚举"改 algebra / 新增并击维度能把码面抬到多少"），
  见 `docs/reports/code_length_06_verdict.md` §另案建议单。在此之前不建议动编码骨架。
- 遗留运维项（非本 effort）：实验方案 `kongmingmas_exp` 是否转正、全量版 `kongmingma` 历史简码追平、
  真机部署复核（沙箱锁限制），均为独立任务。

## Out of scope

<!--  consciously ruled beyond the destination -->

- 52dazi 榜单成绩冲榜 / 账号运营：该站只作外部校准数据，不是本 effort 目标。
- 拼音 / 五笔等非并击方案的码长优化：与本目标无关。
