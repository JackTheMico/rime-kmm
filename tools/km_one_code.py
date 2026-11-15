#!/usr/bin/env python3
"""空明码-宏版S：一个词条只留一条简码，多余的槽转给缺槽的高频词。

口径
----
简码 = ≤2 码元、不含空格、纯汉字的独立词条。

1. **去重**：一个词/字名下挂 ≥2 条简码时只留一条，其余摘掉。
   留哪条不是「一律留最便宜的」——那样会把 `如果` 的读音码 `RG` 丢掉。按价值模型逐条判：

       keep 便宜的码  ⇔  该词损失（频次 × 多出的动作）≤ 让出这条码能换回的收益
       keep 读音码    ⇔  让出便宜码更划算（读音码是用户可推导的主路径，也是老码）

2. **再分配**：摘掉后真正空出来的槽（该码不再有任何词条占用）才发得出去，
   只发给一条简码都没有、最佳路径 ≥2 击的高频词。
3. **护栏**：符号族语义守恒（`?X` 叠字 / `@X` 三字 / `*X` 四字）；一槽不发两次；
   目标拿到后只此一条；标点/数字直出槽不动。

用法
----
    python3 tools/km_one_code.py                      # 预览
    python3 tools/km_one_code.py --apply --with-trad  # 写入简繁双库
    python3 tools/km_one_code.py --keep-rule cheap    # 一律留最便宜的（速度优先）
    python3 tools/km_one_code.py --keep-rule mn       # 一律留读音码（可推导优先）
"""
import argparse
import collections
import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
sys.path.insert(0, HERE)

import km_chord_model as chord  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


kmopt = _load('km_jianma_opt')
rec = _load('km_jianma_reclaim')

ONE = chord.one_press_codes()
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORT = os.path.join(REPORTS, 'one_code_report.md')
MIN_WORD_FREQ = 20000
CHAR_MIN_WORD = 1000


def is_hanzi(w):
    return all('\u4e00' <= ch <= '\u9fff' for ch in w)


def is_digit_slot(c):
    """`1~`~`9~` 是数字大写族的语义位（壹贰叁…），不能当冗余摘掉。"""
    return len(c) == 2 and c[1] == '~' and c[0].isdigit()


def build(entries):
    """(code -> [word], word -> [简码])；简码 = ≤2 码元、不含空格。"""
    codes = collections.defaultdict(list)
    short = collections.defaultdict(list)
    for w, c, raw in entries:
        codes[c].append(w)
        if len(c) <= 2 and ' ' not in c and is_hanzi(w):
            short[w].append(c)
    return codes, short


def code_ages(words):
    """(词, 码) 最早出现在哪份备份 —— 判「谁是老码」。序号越小越老，今天新加的不在表里。"""
    import pickle
    cache = os.path.join(ROOT, '.workbuddy/tmp/code_ages.pkl')
    baks = sorted(p for p in os.listdir(ROOT)
                  if p.startswith('kongmingmas.dict.yaml.bak-2026'))
    key = tuple((p, os.path.getsize(os.path.join(ROOT, p))) for p in baks)
    if os.path.exists(cache):
        with open(cache, 'rb') as f:
            got = pickle.load(f)
        if got.get('key') == key and got.get('ages'):   # 空表视为坏缓存
            print('  年龄表：命中缓存（%d 条）' % len(got['ages']))
            return got['ages']
    ages = {}
    want = set(words)
    for idx, name in enumerate(baks):
        with open(os.path.join(ROOT, name), encoding='utf-8') as f:
            for line in f:
                a, _, b = line.rstrip('\n').partition('\t')
                if a in want and (a, b) not in ages:
                    ages[(a, b)] = idx
    with open(cache, 'wb') as f:
        pickle.dump({'key': key, 'ages': ages}, f)
    print('  年龄表：扫 %d 份备份，命中 %d 条' % (len(baks), len(ages)))
    return ages


def free_slots(units, codes, freq):
    """摘掉 units 后真正没人占的槽，以及它能不能一击即出。"""
    rm = set(units)
    cnt_after = collections.Counter()
    for c, lst in codes.items():
        n = sum(1 for w in lst if (w, c) not in rm)
        if n:
            cnt_after[c] = n
    pref_after = rec.prefixes(set(cnt_after))
    out = []
    for w, c in units:
        if cnt_after.get(c, 0):
            continue
        out.append({'code': c, 'from': w, 'freq': freq.get(w, 0),
                    'clean': c not in pref_after})
    out.sort(key=lambda f: (not f['clean'], -f['freq']))
    return out


def assign(free, targets):
    """槽按价值降序发；每个槽挑「成本差 × 频次」最大的候选。"""
    used, plan = set(), []
    for f in free:
        new_cost = 1 if f['clean'] else 2
        best, best_gain = None, 0
        for t in targets:
            if t['word'] in used:
                continue
            if not rec.family_ok(f['code'], t['word']):
                continue
            if t['cost'] <= new_cost:
                continue
            g = t['freq'] * (t['cost'] - new_cost)
            if g > best_gain:
                best, best_gain = t, g
        if best is None:
            continue
        used.add(best['word'])
        plan.append({'slot': f, 'target': best, 'gain': best_gain, 'new_cost': new_cost})
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    ap.add_argument('--keep-rule', choices=['value', 'cheap', 'mn'], default='value',
                    help='value=按价值逐条判（默认）；cheap=一律留最便宜；mn=一律留读音码')
    ap.add_argument('--min-word-freq', type=int, default=MIN_WORD_FREQ)
    ap.add_argument('--no-chars', action='store_true', help='只处理多字词，不动单字')
    ap.add_argument('--char-min-word', type=int, default=CHAR_MIN_WORD)
    ap.add_argument('--top', type=int, default=30)
    ap.add_argument('--dict', choices=['S', 'T'], default='S',
                    help='处理哪本词库：S=简体（默认）、T=繁体（繁体独有的词要单独收敛）')
    ap.add_argument('--dedupe-only', action='store_true',
                    help='只收敛多简码，不新增任何条目（繁体库用）')
    args = ap.parse_args()
    path = DICT_T if args.dict == 'T' else DICT_S

    print('读取词库与备份史…')
    header, entries = kmopt.load_dict(path)
    codes, short = build(entries)
    sheng = kmopt.build_index(entries)[2]
    freq = kmopt.load_freq()
    init = rec.char_initials()
    cnt = {c: len(v) for c, v in codes.items()}
    pref = rec.prefixes(set(codes))
    multi = [w for w, cs in short.items() if len(cs) >= 2]
    ages = code_ages(multi)

    # ---- 每条目：候选 keeper 与读音码
    items = []
    for w in multi:
        cs = sorted(set(short[w]))          # 完全重复的行不算「多简码」
        if len(cs) < 2:
            continue
        if w in rec.DENY or any(c in rec.KEEP_CODES for c in cs):
            continue
        if args.no_chars and len(w) == 1:
            continue
        mn = [c for c in rec.readable_codes(w, cs, sheng, init)]
        def ordered(seq):
            # 成本 → 同码竞争者少（越接近一击即出）→ 老码 → 码面
            return sorted(seq, key=lambda c: (rec.cost_of(c, cnt[c], pref), cnt[c],
                                              ages.get((w, c), 999), c))
        fast = ordered(cs)[0]
        mnb = ordered(mn)[0] if mn else None
        if args.keep_rule == 'mn' and mnb:
            fast = mnb
        items.append({'word': w, 'codes': cs, 'fast': fast, 'mn': mnb,
                      'freq': freq.get(w, 0), 'keep': fast,
                      'prot': bool([c for c in cs if is_digit_slot(c)]),
                      'cost': {c: rec.cost_of(c, cnt[c], pref) for c in cs}})
        if items[-1]['prot']:
            items[-1]['keep'] = [c for c in cs if is_digit_slot(c)][0]

    # ---- 接手人池
    all_codes = collections.defaultdict(list)
    for w, c, raw in entries:
        if is_hanzi(w) and ' ' not in w:
            all_codes[w].append(c)
    targets = []
    for w, f in freq.items():
        if not is_hanzi(w) or not (2 <= len(w) <= 4) or w in rec.DENY:
            continue
        if f < args.min_word_freq or short.get(w):
            continue
        k = rec.cost_set(all_codes.get(w) or [], cnt, pref)
        if 2 <= k < 99:
            targets.append({'word': w, 'freq': f, 'cost': k})
    targets.sort(key=lambda t: -t['freq'] * (t['cost'] - 1))
    if args.dedupe_only:
        targets = []

    def evaluate():
        units = [(it['word'], c) for it in items for c in it['codes'] if c != it['keep']]
        free = free_slots(units, codes, freq)
        return units, free, assign(free, targets)

    def potential(code):
        """这条码如果空出来，最好能换回多少收益（不考虑竞争）。"""
        if cnt.get(code, 0) != 1:
            return 0
        new_cost = 1 if code not in pref else 2
        best = 0
        for t in targets:
            if t['cost'] <= new_cost or not rec.family_ok(code, t['word']):
                continue
            best = max(best, t['freq'] * (t['cost'] - new_cost))
        return best

    # ---- 价值迭代：便宜的码让出去更划算时，改留读音码
    prev = None
    for step in range(4):
        units, free, plan = evaluate()
        if args.keep_rule != 'value':
            break
        gain_of = {p['slot']['code']: p['gain'] for p in plan}
        changed = 0
        for it in items:
            if it['prot'] or not it['mn'] or it['keep'] != it['fast']:
                continue
            # 读音码比现在的码贵多少 → 改留读音码要付的代价
            d = it['cost'][it['mn']] - it['cost'][it['fast']]
            if d <= 0:
                continue
            g = potential(it['fast'])          # 让出便宜码能换回的收益
            if g > it['freq'] * d:
                it['keep'] = it['mn']
                changed += 1
        if not changed or changed == prev:
            break
        prev = changed

    units, free, plan = evaluate()
    clean = [f for f in free if f['clean']]
    net = sum(p['gain'] for p in plan)
    n_word = sum(1 for it in items if len(it['word']) > 1)
    print('去重：%d 个条目（词 %d / 字 %d），摘掉 %d 条简码'
          % (len(items), n_word, len(items) - n_word, len(units)))
    print('空槽：%d 个真正空出（其中一击即出 %d）' % (len(free), len(clean)))
    print('再分配：%d 槽，净省 %s 动作' % (len(plan), f'{net:,}'))
    print('\n一击即出的空槽 → 新主人：')
    for p in sorted(plan, key=lambda x: -x['gain'])[:args.top]:
        print('  %-4s 来自 %-6s → %-6s %s 动作 %d→%d  收益 %s'
              % (p['slot']['code'], p['slot']['from'], p['target']['word'],
                 f'{p["target"]["freq"]:,}', p['target']['cost'], p['new_cost'],
                 f'{p["gain"]:,}'))
    print('\n留读音码、让出快码的条目：')
    for it in items:
        if it['keep'] == it['mn'] and it['fast'] != it['mn']:
            print('  %-6s 留 %-3s（%d 动作）让 %-3s（%d 动作）'
                  % (it['word'], it['keep'], it['cost'][it['keep']],
                     it['fast'], it['cost'][it['fast']]))
    dropped_mn = [it for it in items if it['keep'] != it['mn'] and it['mn']
                  and it['mn'] in [c for c in it['codes'] if c != it['keep']]]
    print('\n丢掉了读音码的条目：%d' % len(dropped_mn))
    for it in dropped_mn:
        print('  %-6s 留 %-3s 丢 %-3s' % (it['word'], it['keep'], it['mn']))

    if len(items) <= 20:
        print('\n去重清单：')
        for it in items:
            print('  %-6s 留 %-4s 丢 %s'
                  % (it['word'], it['keep'],
                     '　'.join(c for c in it['codes'] if c != it['keep'])))
    if not args.apply:
        print('\n预览模式（未写盘）。')
        return

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    removals = set(units)
    additions = [(p['target']['word'], p['slot']['code']) for p in plan]
    seen = set()
    for w, c in additions:
        assert c not in seen, '码重复分配：%s' % c
        seen.add(c)
        assert c not in all_codes.get(w, []), '目标已有该码：%s %s' % (w, c)
        assert (w, c) not in removals, '同一行既删又加：%s %s' % (w, c)
    n_rm, n_add = rec.rewrite(path, removals, additions, apply=True, stamp=stamp)
    assert n_rm == len(removals), '删除数不符：计划 %d 实际 %d' % (len(removals), n_rm)
    print('\n%s：删 %d 增 %d' % (path.rsplit('/', 1)[-1], n_rm, n_add))
    if args.with_trad and args.dict == 'S':
        trad = kmopt.to_trad(sorted({w for w, _ in removals} | {w for w, _ in additions}))
        a, b = rec.rewrite(DICT_T,
                           {(trad.get(w, w), c) for w, c in removals},
                           [(trad.get(w, w), c) for w, c in additions],
                           apply=True, stamp=stamp)
        print('繁体：删 %d 增 %d' % (a, b))

    rpt = REPORT if args.dict == 'S' else REPORT.replace('.md', '_t.md')
    with open(rpt, 'w', encoding='utf-8') as f:
        f.write(build_report(items, units, free, plan, args, stamp, n_rm, n_add))
    print('报告：%s' % rpt)


def build_report(items, units, free, plan, args, stamp, n_rm, n_add):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []

    def A(s):
        L.append(s)

    n_word = sum(1 for it in items if len(it['word']) > 1)
    clean = [f for f in free if f['clean']]
    net = sum(p['gain'] for p in plan)
    A('# 空明码-宏版S：一词一码（多简码收敛 + 空槽再分配）\n')
    A('> %s　工具：`tools/km_one_code.py`　词库：`kongmingmas.dict.yaml`\n' % now)
    A('## 1. 结论\n')
    A('- **去重 %d 个条目**（词 %d / 字 %d），摘掉 **%d 条**多余简码 —— 每个词/字此后只剩一条。'
      % (len(items), n_word, len(items) - n_word, len(units)))
    A('- 其中 **%d 个槽真正空了出来**；其余 %d 条码摘掉后仍被别人占着（只是删冗余，腾不出槽）。'
      % (len(free), len(units) - len(free)))
    A('- 空槽里 **%d 个一击即出**，连同 %d 个仍需空格的槽一起发给缺槽的高频词：'
      '再分配 %d 槽，净省 **%s 个动作**。'
      % (len(clean), len(free) - len(clean), len(plan), f'{net:,}'))
    A('')
    A('## 2. 留哪一条码\n')
    A('| 判据 | 说明 |')
    A('| --- | --- |')
    A('| 成本 | 1 = 一击即出；2 = 一击 + 空格；3 = 两次并击 |')
    A('| 默认 | 留成本最低的；同成本优先老码（备份史里最早的），再优先读音码 |')
    A('| 例外 | 若让出便宜码能换回更多收益（收益 > 该词频次 × 多出的动作），改留读音码 |')
    A('| 接收人 | 一条简码都没有、最佳路径 ≥2 击、词频 ≥ %s |' % f'{args.min_word_freq:,}')
    A('| 护栏 | 符号族语义；一槽不发两次；目标只此一条；直出槽不动 |')
    A('')
    A('## 3. 去重清单（%d 条）\n' % len(items))
    A('| 词条 | 词频 | 留下 | 摘掉 |')
    A('| --- | ---: | :---: | --- |')
    for it in sorted(items, key=lambda r: -r['freq']):
        drop = [c for c in it['codes'] if c != it['keep']]
        A('| %s | %s | `%s`（%d） | %s |'
          % (it['word'], f'{it["freq"]:,}', it['keep'], it['cost'][it['keep']],
             '　'.join('`%s`(%d)' % (c, it['cost'][c]) for c in drop)))
    A('')
    A('## 4. 再分配（%d 槽，净省 %s）\n' % (len(plan), f'{net:,}'))
    A('| 码 | 来源 | 新主人 | 频次 | 原成本 | 新成本 | 收益 |')
    A('| :---: | --- | --- | ---: | ---: | ---: | ---: |')
    for p in sorted(plan, key=lambda x: -x['gain']):
        A('| `%s` | %s | **%s** | %s | %d | %d | %s |'
          % (p['slot']['code'], p['slot']['from'], p['target']['word'],
             f'{p["target"]["freq"]:,}', p['target']['cost'], p['new_cost'],
             f'{p["gain"]:,}'))
    A('')
    A('## 5. 空出但没人接的槽（%d）\n' % (len(free) - len(plan)))
    used = {p['slot']['code'] for p in plan}
    left = [f for f in free if f['code'] not in used]
    if left:
        A('| 码 | 来源 | 能否一击即出 | 原因 |')
        A('| :---: | --- | :---: | --- |')
        for f in left:
            A('| `%s` | %s | %s | %s |'
              % (f['code'], f['from'], '是' if f['clean'] else '否（仍是前缀）',
                 '符号族语义不匹配' if not f['clean'] else '没有更高收益的候选人'))
    else:
        A('无。')
    A('')
    A('## 6. 部署与回滚\n')
    A('```bash')
    A('python3 tools/km_deploy_xsime.py')
    A('cp kongmingmas.dict.yaml.bak-%s kongmingmas.dict.yaml   # 回滚' % stamp)
    A('```')
    A('')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
