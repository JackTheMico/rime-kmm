# tools —— 空明码-宏版S 简码优化工具链

所有脚本都以**仓库根目录**为基准（`ROOT = 词库所在目录`），可在任意 cwd 下执行：

```bash
python3 tools/km_one_code.py            # 预览
python3 tools/km_one_code.py --apply --with-trad   # 写入简繁双库
```

**通用约定**

- 默认只预览，`--apply` 才写库；`--with-trad` 同时写繁体镜像库 `kongmingmas_t.dict.yaml`。
- 每次写库前自动生成 `kongmingmas.dict.yaml.bak-<时间戳>`（已在 `.gitignore` 中排除）。
- 报告一律写到 `docs/reports/`，参考文档写到 `docs/reference/`。
- 写库后必须跑 `python3 tools/km_deploy_xsime.py` 才会生效。

---

## 1. 口径与度量

| 脚本 | 作用 | 产出 |
| :--- | :--- | :--- |
| `km_chord_model.py` | **击数权威模型**：解析 `kongmingmas.schema.yaml` 的 `chord_composer.alphabet` 与 `algebra`，模拟按键→码串变换，枚举全部「一次并击」可达码。`python3 tools/km_chord_model.py` 自带自检用例。 | 无（库） |
| `km_char_onehit.py` | 统计常用单字的上屏成本（一击上屏 / 一击+空格 / 两次并击 / 需选词）。 | `char_onehit_report.md` |
| `km_multi_code_stats.py` | 统计「一个词条挂几条简码」，含死码与无损冗余判定。 | `multi_code_report.md` |

> 击数口径：**一次并击 = 双手同时按下 = 左右手各一个码元**，故 `击数 = ceil(码元数 / 2)`。
> `RG`（左 `e+t` ＋ 右 `h+k`）与 `0f`（`asdf` ＋ `j`）都是 1 击。判定一律以 `km_chord_model` 为准，不要凭肉眼猜。

## 2. 简码优化（写库类）

| 脚本 | 作用 | 产出 |
| :--- | :--- | :--- |
| `km_jianma_opt.py` | 按词频把高频词提到更短的简码槽位（废槽阈值 `--dead`、碾压规则 `--elite-ratio/--elite-min`）。 | `jianma_optimization_report.md` |
| `km_jianma_zero.py` | **零延伸槽位**（`X~` `X'` `@X` `*X` 等符号族）优化。零延伸槽一旦两个候选就会退化成「必须空格」，所以只能置换不能追加。 | `jianma_zero_opt_report.md` |
| `km_jianma_digit.py` | 数字族（`0X` / `7X` / `8X` / `9X`）优化：开新槽 + 清残渣。`--set 0o=知道` 可单槽改派。 | `jianma_digit_opt_report.md` |
| `km_jianma_reclaim.py` | 回收「已有读音简码」的词额外占的一击槽，再分配给缺槽的高频词/字。`--force-codes 0b` 点名强制回收，`--dedup` 回收一词多槽。 | `jianma_reclaim_report.md` |
| `km_one_code.py` | **一词一码**：收敛「一词多简码」，把腾出的空槽再分配给缺槽高频词。留哪条按价值模型（成本、码位竞争者、备份史老码、读音码收益）。内置护栏：摘掉某码位唯一真候选时跳过（`--allow-empty-head` 可关），否则首候选会变成 `载 ;` 这类后缀构造。 | `one_code_report.md` / `one_code_report_t.md` |
| `km_fix_dead.py` | 清理打不出来的简码：数字码元（`7/8/9` 是左手三键）写到字母后面会变成死码，能反转的改写（`A8`→`8A`）、撞车的删除。 | `dead_code_report.md` |
| `km_code_head_fix.py` | **回补码位首候选**。词库头是 `sort: original`、没有权重列，同码候选全按文件行序。删掉某码位唯一的真候选后，同码的「字+空格+后缀」构造（`载 ;`）就会顶到首位。本工具按改动前备份把这些条目原样补回。 | `code_head_fix_report.md` |
| `km_jianma_prune.py` | 清理含数字的编码（`Y4` 这类两码简码、`--legacy` 清含 1–6 的旧式码）。 | `jianma_prune_report*.md` |

## 3. 文档与部署

| 脚本 | 作用 | 产出 |
| :--- | :--- | :--- |
| `km_jianma_doc.py` | 导出简码参考：分节 Markdown + 单文件可搜索 HTML + TSV。判定「自动上屏 = 零延伸且唯一候选」。 | `docs/reference/jianma_reference.{md,html,tsv}` |
| `km_deploy_xsime.py` | 部署到 XSIME：同步词库/方案/`lua/` 到当前方案包，调 `rimes-deploy` 重编，再重启 fcitx5。`--full` 全量重建、`--dry-run` 只看待同步文件。 | 无 |

## 4. 探针与测试

| 文件 | 作用 |
| :--- | :--- |
| `km_probe_chord.c` | 用 librime 实测「一次并击输出什么码」，验证击数口径的唯一可靠判据。 |
| `km_deploy.c` | `km_deploy_xsime.py` 的 C 后端：调用 librime 把方案编译到 learning 目录（强制走一次完整部署以重编依赖词库）。 |
| `rime_test_console.c` | 真实 librime 会话：模拟按键观察反查行为。 |
| `mini_probe.c` | 最小 librime 环境探测（反查调试期留存）。 |
| `gen_kongmingma_reverse.py` | 生成拼音反查分片数据（`lua/kongmingma/data/reverse_*.lua`）。 |
| `test_reverse_regression.py` | 反查回归测试（依赖 `/tmp/rime_test` 二进制）。 |
| `_validate_rev.py` | 反查分片自检，**已过时**：路径写死在旧 fcitx5-rime 布局下。 |

---

## 典型工作流

```bash
# 1) 看现状
python3 tools/km_multi_code_stats.py --report
python3 tools/km_char_onehit.py

# 2) 预览改动（不写盘）
python3 tools/km_one_code.py

# 3) 写库 + 部署 + 刷新文档
python3 tools/km_one_code.py --apply --with-trad
python3 tools/km_deploy_xsime.py
python3 tools/km_jianma_doc.py

# 繁体独有词要单独收敛一轮
python3 tools/km_one_code.py --dict T --dedupe-only --apply
```

**回滚**：词库备份就在根目录（`kongmingmas.dict.yaml.bak-<时间戳>`），

```bash
cp kongmingmas.dict.yaml.bak-20261115-201820 kongmingmas.dict.yaml
cp kongmingmas_t.dict.yaml.bak-20261115-201820 kongmingmas_t.dict.yaml
```
