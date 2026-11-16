# 冲 0.6 可达性裁决（票 05）

> Effort: `km-code-length-0.6`　日期: 2026-11-16　对象: 隔离实验方案 `kongmingmas_exp`
> 数据来源: `tools/km_verify_metrics.py`（验收尺子）、`tools/km_slot_validator.py`（空槽校验）、
> Rime 官方 `essay.txt`（经 opencc 转简，`tools/km_jianma_opt.py:load_freq()`）。
> 所有击数判定以 `tools/km_chord_model.py` 为准（一次并击 = 1 击，击数 = ⌈码元数/2⌉）。

## 结论先行

**在不改 algebra 底层、不引入 Lua 预测、守住现有单字一击率与 `X~` 保护族的前提下，
0.6 击/字在真实打字口径下结构性不可达；仅票面固定样本因"零未匹配"的人造条件而名义达标。**

- 全词频表加权理论码长 **K = 0.7495**；把**整个 9,111 一击码面**按词频最优分配，K 下限仍为 **0.6939**。
- 要压到 0.6 需追加约 **48,299 个一击码 = 全码面的 5.3 倍**——algebra 在当前按键模型下根本产生不出这么多一击码。
- 票 04 报告的"理论 0.5161（≤0.6）"是 **unmatched=0 的固定样本**：样本里的字全部在词库中有码，
  把真实语料里 **48% 的未覆盖字符**（每段都需按每字 1 击兜底）排除在外。这不是打字真实表现。

因此本票按 ticket 允许的交付方式结案：**确认不可达 + 给出改底层的另案建议**；不写入任何长词简码，
不动已稳定的 0.7 成果（前 1000 二字词词频覆盖 100%、尺子样本理论 0.5161）。

## 三个口径的数字（缺一不可，互不等价）

| 口径 | 理论码长 | 实测码长 | 未匹配字符 | 说明 |
| :--- | ---: | ---: | ---: | :--- |
| 票 04 固定样本（人工构造、全部有码） | 0.5161 | 0.5806 | 0% | 票面验收口径；≤0.6 在此口径下名义达标 |
| 真实语料 `essay_s.txt` 前 20 万字（日常随机） | 0.8909 | 0.9882 | 48% | 验收协议定义的"实测"口径；远离 0.6 |
| 全词频表加权 K（43.7 万词条） | 0.7495 | — | 每字 1 击兜底 | 非票面口径；衡量长尾整体 |

差异根因只有一个：**未覆盖字符的兜底**。固定样本 unmatched=0，长尾代价被完全隐去；
真实语料近半字符不在简码库内，每字 1 击兜底把理论码长顶到 0.89。这不是工具偏差，是覆盖率缺口。

## 为什么长词/短语简码也救不了（本票核心问题）

ticket 的假设是"给长词挂简码能降低码长"。实测否定该假设，三条独立原因：

1. **高频长词早已一击。** 词频 TOP30 的 3–7 字词（的时候/为什么/是一个/这个问题/也应该…）
   全部 `min_strokes=1`（如 `0b`、`@t`、`*S`），没有"待优化"空间。再挂就是重复占用。
2. **干净空槽已归零。** 票 04 把 603 个无空格干净槽全部挂满，`collect_all_clean_slots()` 现返回 **0**。
   剩余 4,520 个理论槽位全是前缀槽 / 尾空格槽 / `X~` 保护族 / 死码，动它们要么截断长词，要么破坏数字大写族。
3. **码面是硬上限。** 一击码面容量 9,111（枚举自 algebra），已用 4,591。即便把余下 4,520 个
   全部分给最高频的非一击词（贪心最优），K 也只到 **0.6939**。码面不够是结构性的，
   不是分配技巧问题。

### 0.6 门槛的双条件差距（model: K=(1-p)·c1 + p·cw/L）

门槛值出自 `research/word-coverage-gap.md` §③.3 的**自洽口径**（p≤q，前 N 高频二字词、
词频质量加权覆盖率），因此下表严格沿用该研究的口径对齐比较，不拿全表数字去比门槛：
覆盖率取 `coverage_stats(topn=N).mass_coverage`（一击词的词频质量占比），
词均码元数 m 取研究的原法（前 N 二字词最短码元数算术平均，无码记 0）。

| 二字词高频范围 | 一击覆盖率·词频质量 | 0.6 门槛 | 词均码元 m（研究原法） | ≤2 门槛 |
| :--- | ---: | ---: | ---: | ---: |
| 前 1000 | 100.00% | ≥91.9% ✅ | 1.999 | ≤2 ✅ |
| 前 5000 | 73.63% | ≥91.9% ❌ | 3.272 | ≤2 ❌ |
| 前 20000 | 57.86% | ≥91.9% ❌ | 3.793 | ≤2 ❌ |

**读法**：高频前 1000 词两项都达标（票 04 的成果）；但门槛要在**实际打词覆盖的前 5000/2 万**
也成立才撑得起 0.6，而这两档覆盖率和词均码元都显著不达标。m≥3 意味着 `cw=⌈m/2⌉=2`，
即使打词率 100% 也压不到 0.6——这是结构性瓶颈，与覆盖率无关。
对照研究基线（票 04 之前：前 5000 61.9% / m=3.341，前 2 万 48.9% / m=3.772）：
本轮增量把覆盖率推高（73.63% / 57.86%），但 m 几乎未动（3.272 / 3.793）——
**扩容给了更多词一击码，却没改变词本身的码元结构**，故 0.6 的硬前提仍然不满足。

全表口径另列（不与上表门槛直接比较）：二字词一击词频覆盖 42.08%（16.8 万词条），
未覆盖词按每字 1 击兜底 → 全表 K=0.7495。

### 码面容量硬约束（独立于覆盖率口径）

| 指标 | 可用上限 | 实测所需 | 差距 |
| :--- | ---: | ---: | :--- |
| 一击码净追加量（全表贪心到 K=0.6） | 4,520（理论剩余）/ **0（实际干净槽）** | 48,299 | 需 10.7 倍理论余量；实际槽为零 |

## 另案建议单：要冲 0.6 必须改底层（不在本轮）

本轮已停在 0.7 的稳定点，以下为独立评估，**本票不实施**。

| 方案 | 范围 | 风险 | 预期收益 |
| :--- | :--- | :--- | :--- |
| **A. 扩一击码面**（新增并击维度/解锁当前被 xform 清掉的 3 码元组合） | 改 `kongmingmas.schema.yaml` 的 `chord_composer` algebra + `km_chord_model.py` 同步 | 极高：动的是编码骨架，全部词库码面需重算，现有 1,397 一击上屏码与用户肌肉记忆作废 | 唯一能把码面从 9,111 往上抬的路径；理论上码面×5.3 才够 0.6，物理按键组合数不一定支撑 |
| **B. 存量零和重排**（拆高频单字的一击码给二字词） | 重排现有 1,377 个一击码 | 高：`c1=1.269` 会恶化，单字一击率 1097/1500 下降；净和收益接近相抵（issue 05 已论证） | 边际，无法补 49 个百分点覆盖缺口 |
| **C. 打词率训练 + 引导** | 用户侧习惯，不动词库 | 中：需真实用户数据验证 p 能否≥92%；无 predictor 时选重率上升 | 若 p 从当前 ~0.38 提到 0.92，K 模型可下探；但真实语料 48% 字符未覆盖仍是天花板 |
| **D. 引入 predictor/联想**（改引擎或插件） | librime 层，破"零 Lua" | 高：核心 librime 无 predictor；预测字是否计击的口径未定（issue 03） | 理论收益大，但验收协议已明确"预测字计一击"，净收益待证 |

**建议排序**：本轮停在 **0.7（可达且稳定）**；若确要冲 0.6，先立 A 的可行性研究票
（纯静态枚举新增并击维度能把码面抬到多少），再决定是否动编码骨架。C 作为低成本并行试验，
不依赖改码。B/D 暂不建议。

## 本票实际改动与不改动

- **改动**：新增验收函数 `km_verify_metrics.k_target_gap()`（TDD，12 项测试全绿，2 次变异测试均被杀死），
  作为"距目标码长还差多少个一击码"的唯一量化入口，供后续 A 方案复用。
- **不改动**：`kongmingmas_exp{,_t}.dict.yaml` 词库一字未动（无可用空槽，写长词只会制造重复码或截断前缀）；
  原方案 `kongmingmas` 全程未碰；未引入 Lua / predictor；未改 algebra。
- **可复现**：见附录命令。所有数值由工具实跑得出，无手填。

## 附录：复现命令

所有数值来自以下工具实跑。口径分三类，对应上文三张表：
① 全表加权 K 与 k_target_gap（第一/二表）；② 高频二字词覆盖率与词均码元 m（门槛表）；
③ 码面容量上限（容量表）。为避免口径混用，逐条给出命令。

```bash
# ① 全表 K=0.7495、0.6 需追加 48299 个一击码
python3 -c "
import importlib.util
def load(n,r):
    s=importlib.util.spec_from_file_location(n,r); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
chord=load('c','tools/km_chord_model.py'); val=load('v','tools/km_slot_validator.py')
met=load('m','tools/km_verify_metrics.py'); kmopt=load('k','tools/km_jianma_opt.py')
e=val.load_entries('kongmingmas_exp.dict.yaml'); one=chord.one_press_codes()
f=lambda c: chord.strokes(c,one); freq=kmopt.load_freq()
print('weighted_K=', met.weighted_theory_k(e,freq,f))
print('k_target_gap(0.6)=', met.k_target_gap(e,freq,f,target=0.6,capacity=9111))
"

# ① 全码面最优分配下限 K=0.6939（把 top-(9111-4591) 个非一击词改成一击）
python3 -c "
import importlib.util,collections
def load(n,r):
    s=importlib.util.spec_from_file_location(n,r); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
chord=load('c','tools/km_chord_model.py'); val=load('v','tools/km_slot_validator.py'); kmopt=load('k','tools/km_jianma_opt.py')
e=val.load_entries('kongmingmas_exp.dict.yaml'); one=chord.one_press_codes(); f=lambda c: chord.strokes(c,one); freq=kmopt.load_freq()
wc=collections.defaultdict(list)
for w,c in e:
    if ' ' not in w: wc[w].append(c)
def st(w):
    ss=[f(c) for c in wc.get(w,[])]; ss=[s for s in ss if s is not None and s<99]; return min(ss) if ss else len(w)
items=sorted(freq.items(),key=lambda x:-x[1]); den=sum(z*len(w) for w,z in items); num=sum(z*st(w) for w,z in items)
used=len(set(c for _,c in e if f(c)==1)); room=len(one)-used
nonone=[(w,z,st(w)) for w,z in items if st(w)>1]; gain=sum(z*(s-1) for w,z,s in nonone[:room])
print('used=',used,'code_space=',len(one),'ceiling_K=',round((num-gain)/den,4))
"

# ② 高频二字词覆盖率(词频质量) + m(研究原法)：门槛表三行
python3 -c "
import importlib.util,collections
def load(n,r):
    s=importlib.util.spec_from_file_location(n,r); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
chord=load('c','tools/km_chord_model.py'); val=load('v','tools/km_slot_validator.py')
met=load('m','tools/km_verify_metrics.py'); kmopt=load('k','tools/km_jianma_opt.py')
e=val.load_entries('kongmingmas_exp.dict.yaml'); one=chord.one_press_codes(); f=lambda c: chord.strokes(c,one); freq=kmopt.load_freq()
wc=collections.defaultdict(list)
for w,c in e:
    if ' ' not in w: wc[w].append(c)
for N in (1000,5000,20000):
    two=sorted(((w,z) for w,z in freq.items() if len(w)==2),key=lambda x:-x[1])[:N]
    m=sum(min((len(c) for c in wc.get(w,[])),default=0) for w,z in two)/len(two)
    cs=met.coverage_stats(e,freq,f,topn=N)
    print('top%d: mass_cov=%.4f m=%.3f'%(N,cs['mass_coverage'],m))
"

# ③ 干净空槽数（容量表现状）
python3 -c "
import importlib.util
def load(n,r):
    s=importlib.util.spec_from_file_location(n,r); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
chord=load('c','tools/km_chord_model.py'); val=load('v','tools/km_slot_validator.py'); alloc=load('a','tools/km_family_alloc.py')
e=val.load_entries('kongmingmas_exp.dict.yaml'); one=chord.one_press_codes()
print('clean_slots=',len(alloc.collect_all_clean_slots(e,one,val.certify)))
"

# 全套测试（58 项 + 反查回归）
for t in tools/test_*.py; do python3 "$t" || exit 1; done
```
