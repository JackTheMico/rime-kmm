#!/usr/bin/env python3
"""空明码-宏版S 零延伸槽位（符号族简码）词频优化
================================================

为什么单独做
------------
符号族（`X'`、`X`` `、`7X`、`8X`、`!X` …）约 570 个槽位是**零延伸码**：
没有任何更长的编码以它开头，所以打完最后一个键立即上屏，不必按空格、不弹候选。
这是整个方案里价值最高的档位，但当前占用与词频严重脱节
（`X'` 里躺着 搬弄 539、物质文明 749、绝顶 827，而 都是 38.4 万还在打四码）。

排序依据：收益 = 词频 × 省下的击数
--------------------------------
不是简单按词频排序，而是按「这个词一年被敲多少次 × 每个词能省几击」。
当前代价用码表算：码元数 ≈ 击数；空格并击单字码（`X=`/`=X`/`X_=`/`=_X`）算 1 击；
有延伸码的槽位要多按一次空格，故 +1。落到零延伸槽位后代价固定为 1 击
（一次并击＝左右手各一个码元，见 tools/km_chord_model.py）。

关键约束：自动上屏依赖「该码只有一个候选」
----------------------------------------
若往零延伸槽位里追加第二个条目，候选数变成 2，auto_select 不再触发，
槽位会退化成「必须按空格」——那就白做了。
因此本工具采用**置换**而非追加：把槽位首条换成高频词，
被顶掉的原词只失去这条捷径码，其余全码不受影响。

安全护栏（不满足即跳过该槽）
----------------------------
1. 原占用者必须是汉字：`a'`= `'`、`a,`= `,` 这类标点快捷槽一律不动。
2. 原占用者必须有其它编码：否则换掉后该词就没法输入了。
3. 长度必须相同：单字槽换单字、二字词槽换二字词，保持「打出来多长」的直觉。
4. 语义族守恒：`?X` 只收叠字，`@X` 只收三字词，`*X` 只收四字语。
5. 数字族（`1~`=壹 …）整族跳过。
6. 新词必须还没有任何零延伸码（避免一词占两槽）。
7. 收益必须为正，且词频 ≥ 3× 原占用者、≥ 3000，避免来回抖动。

用法
----
  python3 tools/km_jianma_zero.py                    # 预览（不写盘）
  python3 tools/km_jianma_zero.py --apply            # 写入简体库（自动备份）
  python3 tools/km_jianma_zero.py --apply --with-trad # 简繁双库
"""

import argparse
import collections
import datetime
import importlib.util
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORT = os.path.join(REPORTS, 'jianma_zero_opt_report.md')

_spec = importlib.util.spec_from_file_location('kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
kmopt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kmopt)

RATIO = 3          # 新词词频必须达到原占用者的倍数
MIN_FREQ = 3000    # 新词自身的最低词频
SYMS = set(",.?!<;:/='`~@*_")
NUMERALS = set('零〇一二三四五六七八九十壹贰叁肆伍陸柒捌玖拾佰仟万')
SKIP_FAMILY = {'X=', '=X'}          # 单字空格一击层，已是最高频字，不动
DENY = {'回复日期'}                  # 语料模板残留，词频不可信
KEEP_CODES = {'K`'}                 # 空明码（方案名，作者自用，保留）

ZERO_COST = 1       # 零延伸两码元槽位的代价：一次并击（左右手各一码元）= 1 击


def is_cjk_word(w):
    return bool(w) and all('\u4e00' <= ch <= '\u9fff' for ch in w)


def family(code):
    return f'X{code[1]}' if code[1] in SYMS else f'{code[0]}X'


def steps(c):
    """击数 = ceil(码元数 / 2)：一次并击，左右手各出一个码元。

    早期版本把 2 码元当 2 击，是错的——`RG` 就是左手 e+t 配右手 h+k 同时按下，
    见 tools/km_chord_model.py。空格并击单字码（`X=`/`X_=`/`=X`/`=_X`）仍算 1 击。
    """
    if len(c) == 2 and ((c[0] == '=' and c[1].isalpha()) or (c[1] == '=' and c[0].isalpha())):
        return 1
    if len(c) == 3 and (c[1:] == '_=' or c[:2] == '=_'):
        return 1
    return (len(c) + 1) // 2


def build(entries):
    codes = collections.defaultdict(list)
    word_codes = collections.defaultdict(list)
    for w, c, raw in entries:
        codes[c].append((w, raw))
        if ' ' not in w:
            word_codes[w].append(c)
    prefix = set()
    for c in codes:
        for i in range(1, len(c)):
            prefix.add(c[:i])
    return codes, word_codes, prefix


def cost(code_set, prefix):
    """该词当前最省力的输入代价（含上屏所需空格）。"""
    best = 99
    for c in code_set:
        n = steps(c) + (0 if c not in prefix else 1)
        best = min(best, n)
    return best


def pick_candidates(codes, word_codes, prefix, freq, ratio, min_freq):
    zero_codes = [c for c in codes
                  if len(c) == 2 and (set(c) & SYMS)
                  and c not in prefix                       # 零延伸
                  and family(c) not in SKIP_FAMILY
                  and not any(ch.isdigit() for ch in c)     # 数字族跳过
                  and c not in KEEP_CODES
                  and len(codes[c]) == 1]                   # 多候选的槽本来就不自动上屏

    taken = {w for c in codes
             if len(c) == 2 and (set(c) & SYMS) and c not in prefix
             for w, _ in codes[c]}

    pool = collections.defaultdict(list)
    for w, cs in word_codes.items():
        if w in taken or w in DENY or ' ' in w:
            continue
        f = freq.get(w, 0)
        if f < min_freq or not is_cjk_word(w):
            continue
        cur = cost(cs, prefix)
        gain = f * (cur - ZERO_COST)
        if gain <= 0:                     # 已经在 1 击以内，没有升级空间
            continue
        pool[len(w)].append((w, f, gain, cur))
    for L in pool:
        pool[L].sort(key=lambda x: -x[2])

    slots = []
    for c in zero_codes:
        old, _ = codes[c][0]
        if not is_cjk_word(old) or old in NUMERALS:
            continue
        if len([x for x in word_codes.get(old, []) if x != c]) == 0:
            continue                      # 换掉就没法输入了
        slots.append((c, old, freq.get(old, 0)))

    slots.sort(key=lambda x: x[2])        # 最弱的槽先补
    used = set()
    plan = {}
    ptr = collections.defaultdict(int)
    for code, old, old_f in slots:
        L = len(old)
        cands = pool.get(L, [])
        thr = max(ratio * old_f, min_freq)
        i = ptr[L]
        chosen = None
        while i < len(cands):
            w, f, gain, cur = cands[i]
            i += 1
            if w in used or f < thr:
                continue
            if family(code) == '?X' and not (len(w) == 2 and w[0] == w[1]):
                continue
            chosen = (w, f, gain, cur)
            break
        ptr[L] = i
        if chosen:
            used.add(chosen[0])
            plan[code] = (chosen[0], chosen[1], old, old_f, chosen[3])
    return plan, zero_codes


def rewrite(path, plan, trad_map=None, apply=False, stamp=''):
    header, entries = kmopt.load_dict(path)
    out, n = [], 0
    for w, c, raw in entries:
        if c in plan and ' ' not in w:
            new_w = plan[c][0]
            text = trad_map.get(new_w, new_w) if trad_map else new_w
            if text != w:
                out.append(f'{text}\t{c}')
                n += 1
                continue
        out.append(raw)
    if apply:
        bak = f'{path}.bak-{stamp}'
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            # 保留 YAML 头，否则 Rime 无法识别词库
            f.write('\n'.join(header + out) + '\n')
    return n


def report(plan, zero_codes, freq, args, before, after, savings, loss):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []
    A = L.append
    A('# 空明码-宏版S 零延伸槽位优化报告\n')
    A(f'> 生成时间：{now}　工具：`tools/km_jianma_zero.py`\n')
    A('## 1. 结论\n')
    A(f'- 零延伸槽位（打完即上屏、不弹候选、免按空格）共 **{len(zero_codes)}** 个。')
    A(f'- 本次置换 **{len(plan)}** 个槽位。')
    A(f'- 零延伸层承载的词频总量：**{before:,} → {after:,}**（×{after / max(before, 1):.1f}）。')
    A(f'- 击键收支：新词省下 **{savings:,}** 击，被顶掉的原词损失 **{loss:,}** 击，'
      f'**净省 {savings - loss:,} 击**（按语料词频折算的单次输入量）。')
    A('- 采用**置换**而非追加：零延伸槽必须保持「单一候选」才能自动上屏，')
    A('  追加第二个条目会让它退化成「必须按空格」。被顶掉的原词只失去这条捷径码，全码不受影响。\n')
    A('## 2. 裁决规则\n')
    A('| 规则 | 条件 |')
    A('| --- | --- |')
    A('| 收益排序 | 按「词频 × 省下的击数」排，不按纯词频 |')
    A(f'| 词频门槛 | 新词 ≥ {args.ratio}× 原占用者，且 ≥ {args.min_freq} |')
    A('| 长度一致 | 单字槽换单字、二字槽换二字词、三字槽换三字词 |')
    A('| 语义守恒 | `?X` 只收叠字，`@X` 三字，`*X` 四字 |')
    A('| 不动标点 | `a\'`= `\'`、`a,`= `,` 这类快捷槽保留 |')
    A('| 不动数字 | `1~`=壹 整族跳过 |')
    A('| 可回退 | 原词若仅有这一条编码则跳过，避免失去输入途径 |\n')
    A('## 3. 置换清单（按收益降序）\n')
    A('| # | 码 | 族 | 原词(词频) | 新词(词频) | 原代价 | 省 |')
    A('| ---: | :---: | :---: | --- | --- | ---: | ---: |')
    for i, (code, (nw, nf, ow, of, cur)) in enumerate(
            sorted(plan.items(), key=lambda kv: -kv[1][1] * (kv[1][4] - ZERO_COST)), 1):
        A(f'| {i} | `{code}` | `{family(code)}` | {ow}({of:,}) | **{nw}**({nf:,}) | {cur} 击 | {cur - ZERO_COST} |')
    A('')
    A('## 4. 部署与回滚\n')
    A('```bash')
    A('cd ~/Nextcloud/kmrime')
    A('sudo cp kongmingmas.dict.yaml kongmingmas_t.dict.yaml /usr/share/rime-data/')
    A('sudo ./km_deploy /usr/share/rime-data ~/.local/share/fcitx5/rime')
    A('')
    A('# 回滚')
    A('sudo cp kongmingmas.dict.yaml.bak-<时间戳> /usr/share/rime-data/kongmingmas.dict.yaml')
    A('```')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    ap.add_argument('--ratio', type=int, default=RATIO)
    ap.add_argument('--min-freq', type=int, default=MIN_FREQ)
    args = ap.parse_args()

    print('读取词频…')
    freq = kmopt.load_freq()
    print('读取词库…')
    header, entries = kmopt.load_dict(DICT_S)
    codes, word_codes, prefix = build(entries)

    plan, zero_codes = pick_candidates(codes, word_codes, prefix, freq,
                                       args.ratio, args.min_freq)

    before = sum(freq.get(codes[c][0][0], 0) for c in zero_codes)
    after = sum(freq.get(plan.get(c, (codes[c][0][0],))[0], 0) for c in zero_codes)

    # 击键收支：新词省下的 - 被顶掉原词损失的
    savings = loss = 0
    for code, (nw, nf, ow, of, cur) in plan.items():
        savings += nf * (cur - ZERO_COST)
        remain = [c for c in word_codes[ow] if c != code]
        new_cost = cost(remain, prefix) if remain else cur
        loss += of * max(0, new_cost - cur)

    print(f'\n零延伸槽位 {len(zero_codes)} 个，拟置换 {len(plan)} 个')
    print(f'零延伸层词频承载 {before:,} → {after:,}（×{after / max(before, 1):.1f}）')
    print(f'击键收支：省 {savings:,}，损 {loss:,}，净省 {savings - loss:,}')
    print('\n按收益前 30 条：')
    for code, (nw, nf, ow, of, cur) in sorted(
            plan.items(), key=lambda kv: -kv[1][1] * (kv[1][4] - ZERO_COST))[:30]:
        print(f'  {code:<3} {family(code):<4} {ow}({of}) -> {nw}({nf})  {cur}击→2击')

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    n_s = rewrite(DICT_S, plan, apply=args.apply, stamp=stamp)
    print(f'\n简体库：置换 {n_s} 条' + ('' if args.apply else '（dry-run）'))

    if args.with_trad and args.apply:
        trad = kmopt.to_trad([v[0] for v in plan.values()])
        n_t = rewrite(DICT_T, plan, trad_map=trad, apply=True, stamp=stamp)
        print(f'繁体库：置换 {n_t} 条')

    if args.apply:
        with open(REPORT, 'w', encoding='utf-8') as f:
            f.write(report(plan, zero_codes, freq, args, before, after, savings, loss))
        print(f'报告已写入 {REPORT}')


if __name__ == '__main__':
    main()
