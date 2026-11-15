#!/usr/bin/env python3
"""空明码-宏版S 数字族（`0X`/`7X`/`8X`/`9X`）简码优化
=====================================================

为什么做
--------
`0Y` = 有没有 说明「数字码元 + 字母码元」这条路是通的，而 `0` 族只有 1 个延伸码，
剩下 51 个一击零延伸位全空着。与此同时 `7X`/`8X`/`9X` 已经被占了 100 多个槽，
但里面躺着一堆残渣（地黄 648、测速 851、惭愧 1586、幕后 2360），
而 自己 44 万、这样 14.7 万、通过 20.5 万、中国 17.4 万 还在打四码五码。

两类动作
--------
1. **开新槽**：`0` + 字母（26 小写 + 26 大写，扣掉 `0Y`）= 51 个全新一击零延伸位。
   新槽不会顶掉任何人，纯赚。
2. **换残渣**：`7X`/`8X`/`9X` 里原占用者词频低于 `--dead` 的槽位，
   按「词频 × 省下的击数」换成高频词。

排序依据
--------
收益 = 词频 ×（当前代价 − 2）。当前代价用码表算：码元数 ≈ 击数；
空格并击单字码（`X=`/`=X`/`X_=`/`=_X`）算 1 击；有延伸码要按空格，+1。
落到一击零延伸槽后代价固定为 1 击。

护栏
----
1. `0=`、`70`= `*`、`89`= `~`、`7=`= `7` 这类标点/数字直出槽一律不动（原占用者非汉字）。
2. 原占用者若只有这一条编码则跳过，避免换掉后无法输入。
3. 新词必须还没有任何零延伸码，避免一词占两槽。
4. 换残渣时新词词频须 ≥ `--ratio` × 原占用者，且 ≥ `--min-freq`。
5. 数字大写（柒/捌/玖）所在的 `X~` 槽跳过。

用法
----
  python3 tools/km_jianma_digit.py                       # 预览（不写盘）
  python3 tools/km_jianma_digit.py --apply               # 写入简体库（自动备份）
  python3 tools/km_jianma_digit.py --apply --with-trad   # 简繁双库
  python3 tools/km_jianma_digit.py --no-open-zero        # 只换残渣，不开 0 族
  python3 tools/km_jianma_digit.py --mnemonic            # 小写 0x 按拼音首字母排（好记但少省约 160 万击）
  python3 tools/km_jianma_digit.py --set 0o=知道 --apply # 单槽手动改派
"""

import argparse
import collections
import datetime
import importlib.util
import os
import pickle
import shutil
import string
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORT = os.path.join(REPORTS, 'jianma_digit_opt_report.md')

_spec = importlib.util.spec_from_file_location('kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
kmopt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kmopt)

OPEN_DIGIT = '0'                 # 要开新槽的首码元
REBAL_DIGITS = '789'             # 已有槽位、可置换残渣的首码元
LETTERS = string.ascii_lowercase + string.ascii_uppercase
NUMERALS = set('零〇一二三四五六七八九十壹贰叁肆伍陸柒捌玖拾佰仟万')
DENY = {'回复日期'}               # 语料模板残留，词频不可信
KEEP_CODES = {'K`'}              # 空明码（方案名）
ZERO_COST = 1                    # 一击零延伸槽的代价（一次并击＝左右手各一码元）
LUNA = '/usr/share/rime-data/luna_pinyin.dict.yaml'
INIT_CACHE = os.path.join(ROOT, '.workbuddy/tmp/luna_initial.pkl')


def is_cjk_word(w):
    return bool(w) and all('\u4e00' <= ch <= '\u9fff' for ch in w)


def steps(c):
    """击数 = ceil(码元数 / 2)：一次并击，左右手各出一个码元（见 tools/km_chord_model.py）。

    早期版本把 2 码元（如 `RG`、`0Y`）当成 2 击，是错的。
    空格并击单字码（`X=`/`X_=`/`=X`/`=_X`）仍算 1 击。
    """
    if len(c) == 2 and ((c[0] == '=' and c[1].isalpha()) or (c[1] == '=' and c[0].isalpha())):
        return 1
    if len(c) == 3 and (c[1:] == '_=' or c[:2] == '=_'):
        return 1
    return (len(c) + 1) // 2


def load_initial():
    """词 → 拼音首字母。借 luna_pinyin 词库建表（繁→简），本地缓存。"""
    if os.path.exists(INIT_CACHE):
        with open(INIT_CACHE, 'rb') as f:
            return pickle.load(f)
    raw = {}
    with open(LUNA, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or '\t' not in line:
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2:
                continue
            w, py = parts[0], parts[1]
            if ' ' in w or not py:
                continue
            ch = py.split()[0][:1]
            if ch.isalpha():
                raw.setdefault(w, ch.lower())
    words = list(raw)
    tmp_in = os.path.join(ROOT, '.workbuddy/tmp/_luna_in.txt')
    tmp_out = os.path.join(ROOT, '.workbuddy/tmp/_luna_out.txt')
    os.makedirs(os.path.dirname(tmp_in), exist_ok=True)
    with open(tmp_in, 'w', encoding='utf-8') as f:
        f.write('\n'.join(words) + '\n')
    subprocess.run(['opencc', '-c', 't2s.json', '-i', tmp_in, '-o', tmp_out], check=True)
    with open(tmp_out, encoding='utf-8') as f:
        simp = [l.rstrip('\n') for l in f]
    table = {}
    for t, s in zip(words, simp):
        if s and len(s) == len(t):
            table.setdefault(s, raw[t])
    with open(INIT_CACHE, 'wb') as f:
        pickle.dump(table, f)
    return table


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
    best = 99
    for c in code_set:
        n = steps(c) + (0 if c not in prefix else 1)
        if n < best:
            best = n
    return best


def is_zero_slot(codes, prefix, c):
    return c not in prefix and len(codes[c]) == 1


def pick_slots(codes, word_codes, prefix, freq, dead, open_zero):
    """返回 (new_slots, swap_slots)。

    new_slots: [(code, None, 0)] 全新空槽
    swap_slots: [(code, old_word, old_freq)] 可置换的残渣槽
    """
    new_slots, swap_slots = [], []
    if open_zero:
        for ch in LETTERS:
            c = OPEN_DIGIT + ch
            if c in codes:
                continue
            if c in KEEP_CODES:
                continue
            new_slots.append((c, None, 0))

    for d in REBAL_DIGITS:
        for c in sorted(codes):
            if c[0] != d or len(c) != 2:
                continue
            if not is_zero_slot(codes, prefix, c):
                continue
            old = codes[c][0][0]
            if not is_cjk_word(old) or old in NUMERALS:
                continue
            if len([x for x in word_codes.get(old, []) if x != c]) == 0:
                continue                      # 换掉就没法输入了
            f = freq.get(old, 0)
            if f >= dead:
                continue                      # 不是残渣，保留
            swap_slots.append((c, old, f))

    swap_slots.sort(key=lambda x: x[2])       # 最弱的槽先补
    return new_slots, swap_slots


def build_pool(codes, word_codes, prefix, freq, min_freq):
    """候选池：按「词频 × 可省击数」降序，长度不设限。"""
    taken = set()
    for c in codes:
        if len(c) == 2 and is_zero_slot(codes, prefix, c):
            taken.add(codes[c][0][0])

    pool = []
    for w, cs in word_codes.items():
        if w in taken or w in DENY:
            continue
        f = freq.get(w, 0)
        if f < min_freq or not is_cjk_word(w):
            continue
        cur = cost(cs, prefix)
        gain = f * (cur - ZERO_COST)
        if gain <= 0:                         # 已在 1 击以内，没必要占槽
            continue
        pool.append((gain, f, w, cur))
    pool.sort(reverse=True)
    return pool


def make_plan(new_slots, swap_slots, pool, ratio, min_freq, initial=None):
    """新槽先拿最值钱的候选（纯赚），残渣槽再拿次一档的。

    `initial` 不为空时，小写 `0x` 槽按拼音首字母对号入座
    （`0Y`=有没有 就是这个规矩），大写槽与首字母无词的槽按收益补。
    """
    used = set()
    plan_new = []
    filled = {}

    if initial:
        best = {}
        for item in pool:
            L = initial.get(item[2])
            if L and L not in best:
                best[L] = item
        for code, _, _ in new_slots:
            L = code[1]
            if L.isupper() or L not in best:
                continue
            item = best.pop(L)
            if item[2] in used:
                continue
            used.add(item[2])
            filled[code] = item

    ptr = 0

    def take(threshold):
        nonlocal ptr
        while ptr < len(pool):
            gain, f, w, cur = pool[ptr]
            ptr += 1
            if w in used or f < threshold:
                continue
            return (gain, f, w, cur)
        return None

    for code, _, _ in new_slots:
        if code in filled:
            gain, f, w, cur = filled[code]
            plan_new.append((code, w, f, cur, gain))
            continue
        got = take(min_freq)
        if not got:
            break
        gain, f, w, cur = got
        used.add(w)
        plan_new.append((code, w, f, cur, gain))

    plan_swap = []
    for code, old, old_f in swap_slots:
        thr = max(ratio * old_f, min_freq)
        got = take(thr)
        if not got:
            break
        gain, f, w, cur = got
        used.add(w)
        plan_swap.append((code, w, f, cur, old, old_f, gain))

    return plan_new, plan_swap


def build_overrides(codes, word_codes, prefix, freq, pairs):
    """`--set 码=词` 手动改派：不走价值模型，直接照办。"""
    out = []
    for pair in pairs:
        if '=' not in pair:
            raise SystemExit('--set 需要「码=词」格式，例如 --set 0o=知道')
        code, w = pair.split('=', 1)
        code, w = code.strip(), w.strip()
        if code not in codes:
            raise SystemExit('码 %s 不存在' % code)
        if len(codes[code]) != 1:
            raise SystemExit('码 %s 有多个候选，不敢直接改' % code)
        old = codes[code][0][0]
        if old == w:
            print('  --set %s：已经是 %s，跳过' % (code, w))
            continue
        if not is_cjk_word(w):
            raise SystemExit('--set 只接受汉字词：%s' % w)
        f = freq.get(w, 0)
        cur = cost(word_codes.get(w, []), prefix) if word_codes.get(w) else 4
        out.append((code, w, f, cur, old, freq.get(old, 0), f * max(1, cur - ZERO_COST)))
    return out


def rewrite(path, plan_new, plan_swap, trad_map=None, apply=False, stamp=''):
    header, entries = kmopt.load_dict(path)
    swap = {code: w for code, w, *_ in plan_swap}

    anchor = -1
    for i, (w, c, raw) in enumerate(entries):
        if c[0] == OPEN_DIGIT:
            anchor = i

    out, n_new, n_swap = [], 0, 0
    for i, (w, c, raw) in enumerate(entries):
        if c in swap and ' ' not in w:
            nw = swap[c]
            text = trad_map.get(nw, nw) if trad_map else nw
            if text != w:
                out.append('%s\t%s' % (text, c))
                n_swap += 1
                continue
        out.append(raw)
        if i == anchor and plan_new:
            for code, nw, *_ in plan_new:
                text = trad_map.get(nw, nw) if trad_map else nw
                out.append('%s\t%s' % (text, code))
                n_new += 1

    if apply:
        bak = '%s.bak-%s' % (path, stamp)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            # 保留 YAML 头，否则 Rime 无法识别词库
            f.write('\n'.join(header + out) + '\n')
    return n_new, n_swap


def zero_snapshot(codes, freq, plan_new, plan_swap):
    """`0` 族两码字母槽的当前全表（含本次计划改动），供报告与核对用。"""
    over = {c: w for c, w, *_ in plan_swap}
    rows = []
    for c in codes:
        if c[0] != OPEN_DIGIT or len(c) != 2 or not c[1].isalpha():
            continue
        w = over.get(c, codes[c][0][0])
        rows.append((c, w, freq.get(w, 0)))
    for c, w, f, *_ in plan_new:
        if c[0] == OPEN_DIGIT and len(c) == 2 and c[1].isalpha():
            rows.append((c, w, f))
    rows.sort(key=lambda r: (r[0][1].islower(), r[0][1]))
    return rows


def report(plan_new, plan_swap, freq, args, new_savings, swap_savings, loss,
           snapshot=None):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    snapshot = snapshot or []
    L = []
    A = L.append
    A('# 空明码-宏版S 数字族简码优化报告\n')
    A('> 生成时间：%s　工具：`tools/km_jianma_digit.py`\n' % now)
    A('## 1. 结论\n')
    A('- 起因：`0Y` = 有没有，说明「数字码元 + 字母码元」可用，而 `0` 族此前只有这 1 个延伸码。')
    A('- `0` 族当前共 **%d** 个一击零延伸槽（26 小写 + 26 大写），承载词频合计 **%s**。'
      % (len(snapshot), f'{sum(f for _, _, f in snapshot):,}'))
    A('- 本次运行：新开槽 **%d** 个，置换/改派 **%d** 个。' % (len(plan_new), len(plan_swap)))
    A('- 击键收支：新槽净省 **%s** 击，换槽净省 **%s** 击，合计 **%s** 击'
      '（按语料词频折算的单次输入量）。'
      % (f'{new_savings:,}', f'{swap_savings - loss:,}', f'{new_savings + swap_savings - loss:,}'))
    A('')
    A('## 2. 裁决规则\n')
    A('| 规则 | 条件 |')
    A('| --- | --- |')
    A('| 新槽优先 | `0` 族空位先拿最值钱的候选，纯赚不占地 |')
    A('| 收益排序 | 按「词频 ×（当前代价 − 2）」排，不按纯词频 |')
    A('| 残渣门槛 | `7/8/9` 族原占用者词频 < %s 才算残渣 |' % f'{args.dead:,}')
    A('| 置换门槛 | 新词 ≥ %d× 原占用者，且 ≥ %s |' % (args.ratio, f'{args.min_freq:,}'))
    A('| 手动改派 | `--set 码=词` 直接照办，不走价值模型（个人习惯优先） |')
    A('| 不动标点 | `70`= `*`、`89`= `~`、`0=`= `0`、`7=`= `7` 这类直出槽保留 |')
    A('| 可回退 | 原词若仅有这一条编码则跳过，避免失去输入途径 |')
    A('')
    A('## 3. `0` 族当前全表（%d 槽）\n' % len(snapshot))
    A('| 码 | 词 | 词频 |')
    A('| :---: | --- | ---: |')
    for code, w, f in snapshot:
        A('| `%s` | **%s** | %s |' % (code, w, f'{f:,}'))
    A('')
    A('## 4. 本次运行改动（%d 槽）\n' % (len(plan_new) + len(plan_swap)))
    if plan_new:
        A('### 4.1 新开槽\n')
        A('| 码 | 词 | 词频 | 原代价 | 省 |')
        A('| :---: | --- | ---: | ---: | ---: |')
        for code, w, f, cur, gain in plan_new:
            A('| `%s` | **%s** | %s | %d 击 | %d |' % (code, w, f'{f:,}', cur, cur - ZERO_COST))
        A('')
    if plan_swap:
        A('### 4.2 置换 / 改派\n')
        A('| 码 | 原词(词频) | 新词(词频) | 原代价 | 省 |')
        A('| :---: | --- | --- | ---: | ---: |')
        for code, w, f, cur, old, old_f, gain in plan_swap:
            A('| `%s` | %s(%s) | **%s**(%s) | %d 击 | %d |'
              % (code, old, f'{old_f:,}', w, f'{f:,}', cur, cur - ZERO_COST))
        A('')
    if not plan_new and not plan_swap:
        A('（本次无改动，词库已是目标状态。）\n')
    A('## 5. 部署与回滚\n')
    A('```bash')
    A('cd ~/Nextcloud/kmrime')
    A('python3 tools/km_deploy_xsime.py            # 增量部署到 XSIME')
    A('')
    A('# 回滚')
    A('cp kongmingmas.dict.yaml.bak-<时间戳> kongmingmas.dict.yaml')
    A('```')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    ap.add_argument('--ratio', type=int, default=3)
    ap.add_argument('--min-freq', type=int, default=3000)
    ap.add_argument('--dead', type=int, default=3000, help='7/8/9 族低于此词频视为残渣')
    ap.add_argument('--no-open-zero', action='store_true')
    ap.add_argument('--mnemonic', action='store_true',
                    help='小写 0x 槽按拼音首字母对号入座（好记但费槽，约少省 160 万击）')
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--set', action='append', default=[], metavar='码=词',
                    help='手动改派某个槽位，可重复，例如 --set 0o=知道')
    args = ap.parse_args()

    print('读取词频…')
    freq = kmopt.load_freq()
    print('读取词库…')
    header, entries = kmopt.load_dict(DICT_S)
    codes, word_codes, prefix = build(entries)

    initial = None
    if args.mnemonic:
        print('建立拼音首字母表…')
        initial = load_initial()

    new_slots, swap_slots = pick_slots(codes, word_codes, prefix, freq,
                                       args.dead, not args.no_open_zero)
    pool = build_pool(codes, word_codes, prefix, freq, args.min_freq)
    plan_new, plan_swap = make_plan(new_slots, swap_slots, pool, args.ratio,
                                    args.min_freq, initial)

    if args.set:
        print('\n手动改派：')
        overrides = build_overrides(codes, word_codes, prefix, freq, args.set)
        planned = {c for c, *_ in plan_swap} | {c for c, *_ in plan_new}
        for o in overrides:
            if o[0] in planned:
                print('  %s 已由价值模型安排，manual 覆盖' % o[0])
            print('  %s：%s -> %s' % (o[0], o[4], o[1]))
        plan_swap = [p for p in plan_swap if p[0] not in {o[0] for o in overrides}] + overrides

    new_savings = sum(g for *_, g in plan_new)
    swap_savings = sum(p[6] for p in plan_swap)
    loss = 0
    for code, w, f, cur, old, old_f, gain in plan_swap:
        remain = [c for c in word_codes[old] if c != code]
        new_cost = cost(remain, prefix) if remain else cur
        loss += old_f * max(0, new_cost - ZERO_COST)

    print('\n空槽 %d 个（%s 族）｜残渣槽 %d 个（%s 族）'
          % (len(new_slots), OPEN_DIGIT, len(swap_slots), REBAL_DIGITS))
    print('拟开新槽 %d 个，拟置换 %d 个' % (len(plan_new), len(plan_swap)))
    print('击键收支：新槽省 %s，换槽省 %s，损 %s，净省 %s'
          % (f'{new_savings:,}', f'{swap_savings:,}', f'{loss:,}',
             f'{new_savings + swap_savings - loss:,}'))

    print('\n新开 0 族 TOP %d：' % args.top)
    for code, w, f, cur, gain in plan_new[:args.top]:
        print('  %-3s %s(%s)  %d击→2击' % (code, w, f'{f:,}', cur))

    print('\n残渣置换 TOP %d：' % args.top)
    for code, w, f, cur, old, old_f, gain in plan_swap[:args.top]:
        print('  %-3s %s(%s) -> %s(%s)  %d击→2击' % (code, old, f'{old_f:,}', w, f'{f:,}', cur))

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    n_new, n_swap = rewrite(DICT_S, plan_new, plan_swap, apply=args.apply, stamp=stamp)
    print('\n简体库：新增 %d 条，置换 %d 条%s'
          % (n_new, n_swap, '' if args.apply else '（dry-run）'))

    if args.with_trad and args.apply:
        words = [w for _, w, *_ in plan_new] + [p[1] for p in plan_swap]
        trad = kmopt.to_trad(words)
        t_new, t_swap = rewrite(DICT_T, plan_new, plan_swap, trad_map=trad,
                                apply=True, stamp=stamp)
        print('繁体库：新增 %d 条，置换 %d 条' % (t_new, t_swap))

    if args.apply:
        snap = zero_snapshot(codes, freq, plan_new, plan_swap)
        with open(REPORT, 'w', encoding='utf-8') as f:
            f.write(report(plan_new, plan_swap, freq, args,
                           new_savings, swap_savings, loss, snap))
        print('报告已写入 %s' % REPORT)


if __name__ == '__main__':
    main()
