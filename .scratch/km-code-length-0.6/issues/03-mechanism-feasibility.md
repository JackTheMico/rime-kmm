# 票 03 — 降码长新机制在 librime 上的可行性

Type: research
Status: resolved
Assignee: 研究代理「机制」
Blocked by:
Context pointer: `research/mechanism-feasibility.md`

## Question

用户已开放「引入新机制」。在一手来源（librime 源码/文档、Rime 方案配置、并击类方案实践）上回答：

1. **顶功（免空格自动上屏）**：librime 能否原生实现？`chord_composer` + `auto_select` 现有链路上有没有更激进的自动上屏配置？有无现成方案？
2. **短语/整句一键上屏**：现有词库已有 3–7 字长词简码（如 `*Q`=这是一个）。能否靠「扩充长词简码」低成本实现，而不改引擎？上限在哪？
3. **联想 / 智能预测**：librime 有无 predictor/联想组件？接入代价（Lua？改引擎？）与对「码长」口径的影响（预测出的字算不算击）？
4. 各机制的**代价分级**：零配置 / 改 schema / 写 Lua / 改引擎源码，以及是否破坏项目「纯原生零 Lua」现状。

给出可行性排序，供后续 grilling 票取舍。

## Answer

可行性排序：①扩充长词简码（纯词库，天花板是码位不是词库）②顶功参数微调（原生键存在，但对并击口径贡献存疑）③`enable_sentence` 整句（需实测与 auto_select 冲突）④`contextual_suggestions` 联想（核心无 grammar 实现，需插件）⑤Lua 预测（破零 Lua）⑥改引擎 predictor（最重）。最高风险：**预测/联想上屏的字若不选「击」计入口径，会账面虚低码长**——必须在验收协议（票 04）先定口径。详见 `research/mechanism-feasibility.md`。
