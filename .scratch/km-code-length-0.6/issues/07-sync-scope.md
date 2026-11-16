# 票 07 — 繁体镜像与全量版的同步策略

Type: task
Status: open
Blocked by: 05

## Question

仓库有多个平行词库：`kongmingmas`（主战场）、`kongmingmas_t`（繁体镜像）、`kongmingma`（300 万全量，简码仍是旧的）。历史每一轮优化都要处理同步问题。

1. 本轮降码长改动，是否强制简繁同步（`--with-trad`）？全量版 `kongmingma` 是否纳入，还是本轮只动 `kongmingmas*`？
2. 若同步，用什么顺序与验证手段（备份、md5、部署复核）？
3. 若不同步，如何标注「全量版滞后」，避免下次误判。

依赖票 05 定了主策略后才能定同步范围。
