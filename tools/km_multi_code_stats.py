#!/usr/bin/env python3
"""空明码-宏版S：统计「一个词条挂了几条简码」，并拆开可达性。

起因
----
「学习」名下有 `X7` 和 `Id` 两条简码，但 `X7` 其实**打不出来**（下面第 6 节详述）。
所以「有几条简码」和「有几条能用」是两件事，必须分开数。

口径
----
简码 = ≤2 码元、不含空格、纯汉字的独立词条（一击可达的上限是 2 码元）。
「一击可达」以 `km_chord_model.one_press_codes()` 为准（8,719 个）。

    口径 A（库面）：这个词条挂了几条简码 —— 不管能不能打出来
    口径 B（可用）：其中几条真的能一次并击打出

用法
----
    python3 tools/km_multi_code_stats.py            # 打印摘要
    python3 tools/km_multi_code_stats.py --report   # 另写 multi_code_report.md
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

DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
REPORT = os.path.join(REPORTS, 'multi_code_report.md')


def load_kmopt():
    spec = importlib.util.spec_from_file_location('kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


kmopt = load_kmopt()
ONE = chord.one_press_codes()


def cost(c, cnt, pref):
    """词条码成本 = 击数 +（要空格/选词 ? 1 : 0）。"""
    st = chord.strokes(c, ONE)
    if st >= 99:
        return 99
    return st if (c not in pref and cnt[c] == 1) else st + 1


def collect():
    header, entries = kmopt.load_dict(DICT_S)
    freq = kmopt.load_freq()

    cnt = collections.Counter()
    pref = set()
    code_owner = collections.defaultdict(list)   # 码 -> 所有挂它的词条（含后缀构造）
    for w, c, raw in entries:
        code_owner[c].append(w)
        if ' ' in w:
            continue
        cnt[c] += 1
        for i in range(1, len(c)):
            pref.add(c[:i])

    wc = collections.defaultdict(set)
    for w, c, raw in entries:
        if ' ' in w or not c or len(c) > 2:
            continue
        if not all('\u4e00' <= ch <= '\u9fff' for ch in w):
            continue
        wc[w].add(c)

    rows = []
    for w, cs in wc.items():
        reach = {c for c in cs if c in ONE}
        costmap = {c: cost(c, cnt, pref) for c in reach}
        rows.append({
            'word': w, 'codes': sorted(cs), 'reach': reach,
            'freq': freq.get(w, 0),
            'costmap': costmap,
            'costs': sorted(costmap.values()),
            'dead': sorted(cs - reach),
        })
    return rows, code_owner


def summarize(rows):
    multi = [r for r in rows if len(r['codes']) >= 2]
    pure = [r for r in multi if len(r['reach']) == len(r['codes'])]
    dead = [r for r in multi if 0 < len(r['reach']) < len(r['codes'])]
    return {
        'total': len(rows),
        'multi': multi,
        'pure': pure,
        'dead': dead,
        'multi_word': [r for r in multi if len(r['word']) >= 2],
        'multi_char': [r for r in multi if len(r['word']) == 1],
        'pure_word': [r for r in pure if len(r['word']) >= 2],
        'pure_char': [r for r in pure if len(r['word']) == 1],
        'dead_word': [r for r in dead if len(r['word']) >= 2],
        'dead_char': [r for r in dead if len(r['word']) == 1],
    }


def build_report(rows, s, code_owner):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []
    A = L.append
    A('# 空明码-宏版S：一个词条挂了几条简码\n')
    A('> 生成时间：%s　工具：`tools/km_multi_code_stats.py`　词库：`kongmingmas.dict.yaml`\n' % now)
    A('## 1. 结论\n')
    A('| 口径 | 合计 | 词语 | 单字 |')
    A('| --- | ---: | ---: | ---: |')
    A('| 挂 ≥2 条简码（口径 A，不管能不能打） | %d | %d | %d |'
      % (len(s['multi']), len(s['multi_word']), len(s['multi_char'])))
    A('| ├ 几条全都打得出（真·多简码） | %d | %d | %d |'
      % (len(s['pure']), len(s['pure_word']), len(s['pure_char'])))
    A('| └ 其中有码打不出来（死码） | %d | %d | %d |'
      % (len(s['dead']), len(s['dead_word']), len(s['dead_char'])))
    A('')
    dist = collections.Counter(len(r['codes']) for r in rows)
    A('码数分布：' + '　'.join('%d 条简码 %d 个条目' % (k, dist[k]) for k in sorted(dist) if k >= 2))
    A('')
    A('> **`学习` 是「含死码」那一类**：它挂 `X7` 和 `Id`，但 `X7` 打不出来（见第 6 节），')
    A('> 真正能用的一击简码只有 `Id`。')
    A('')
    A('## 2. 词语：挂 ≥2 条简码的全表（%d 个）\n' % len(s['multi_word']))
    A('| 词 | 词频 | 简码（`[死]` = 打不出来） |')
    A('| --- | ---: | --- |')
    for r in sorted(s['multi_word'], key=lambda x: -x['freq']):
        cs = '　'.join('`%s`%s' % (c, ' [死]' if c in r['dead'] else '') for c in r['codes'])
        A('| %s | %s | %s |' % (r['word'], f'{r["freq"]:,}', cs))
    A('')
    A('## 3. 单字：挂 ≥2 条简码的构成（%d 个）\n' % len(s['multi_char']))
    A('| 类别 | 数量 |')
    A('| --- | ---: |')
    A('| 几条全部打得出来 | %d |' % len(s['pure_char']))
    A('| 含有打不出来的死码 | %d |' % len(s['dead_char']))
    A('')
    A('「真·多简码」单字里，两枚码的成本组合：\n')
    combos = collections.Counter(
        tuple(r['costs']) for r in s['pure_char'] if len(r['costs']) >= 2)
    A('| 成本组合 | 条目数 | 说明 |')
    A('| --- | ---: | --- |')
    desc = {(1, 1): '两枚都是一击即出，摘任一枚都不影响速度 → 可无损回收',
            (1, 2): '一枚一击即出、一枚要补空格 → 摘下「2」那枚无影响',
            (2, 2): '两枚都要补空格，摘任一枚都变慢 → 不能动'}
    for k in sorted(combos):
        A('| %s | %d | %s |' % (' + '.join(str(x) for x in k), combos[k],
                                desc.get(k, '含更高成本码，拆开看')))
    A('')
    A('## 4. 无损冗余码：摘掉不影响速度，但多数腾不出空槽\n')
    giveable = []
    for r in s['pure']:
        cm = r['costmap']
        for c in r['reach']:
            rest = [k for x, k in cm.items() if x != c]
            if rest and min(rest) == 1:      # 摘掉 c 后主人仍有一击即出的路
                giveable.append((r, c, cm[c]))

    free = [(r, c, k) for r, c, k in giveable if len(code_owner.get(c, [])) == 1]
    busy = [(r, c, k) for r, c, k in giveable if len(code_owner.get(c, [])) > 1]
    A('| 项 | 数量 |')
    A('| --- | ---: |')
    A('| 摘下后主人仍有一击即出码（loss = 0） | %d 枚 / %d 条目 |'
      % (len(giveable), len({id(r) for r, _, _ in giveable})))
    A('| ├ 摘掉后码位真的空出来（能给别人） | **%d 枚** |' % len(free))
    A('| └ 码位仍被生僻字或后缀构造占着 | %d 枚 |' % len(busy))
    A('')
    A('**能真正回收的 %d 枚：**\n' % len(free))
    A('| 条目 | 词频 | 冗余码（成本） | 留下的码 |')
    A('| --- | ---: | --- | --- |')
    for r, c, k in sorted(free, key=lambda x: -x[0]['freq']):
        keep = [x for x in r['reach'] if x != c]
        A('| %s | %s | `%s`(%d) | %s |'
          % (r['word'], f'{r["freq"]:,}', c, k, '　'.join('`%s`' % x for x in keep)))
    A('')
    A('**腾不出空槽的 %d 枚**：这些码位同时还挂着生僻字或「字+空格+字」后缀构造，'
      '摘掉词条主人只是让位次前移，槽位本身仍被别人占着，回收没有意义。例如：\n' % len(busy))
    A('| 条目 | 词频 | 想摘的码 | 码位的其他主人 |')
    A('| --- | ---: | --- | --- |')
    for r, c, k in sorted(busy, key=lambda x: -x[0]['freq'])[:15]:
        others = [w for w in code_owner.get(c, []) if w != r['word']]
        A('| %s | %s | `%s` | %s |'
          % (r['word'], f'{r["freq"]:,}', c,
             '　'.join(others[:3]) + ('　…' if len(others) > 3 else '')))
    A('')
    A('> 注意：其中一部分「冗余码」其实是**读音码**（`js` 之于「就是」、`zg` 之于「这个」、')
    A('> `Sy` 之于「所以」）。读音码是用户的主路径与肌肉记忆，`tools/km_jianma_reclaim.py --dedup`')
    A('> 已把它们排除在外，只收非读音的冗余槽。')
    A('')
    A('> 口径差异：`--dedup` 判定「码位是否还有别人」时只数不带空格的独立词条（它会报出 32 个槽），')
    A('> 本报告把「字+空格+字」后缀构造也算作占位，所以判定更严 —— 上表 %d 枚才是真正空得出来的。'
      % len(free))
    A('')
    A('## 5. 死码：为什么有些码永远打不出来\n')
    A('简码里含 `/` 的一律不可达 —— schema 的 `xlit|;,./|FDJG|` 先把 `/` 改写成 `G`，')
    A('而 algebra 里没有任何规则能输出 `/`。这类码在库里有约 2.8 万条，本次统计里落在简码档的：\n')
    A('| 条目 | 词频 | 死码 | 可用的码 |')
    A('| --- | ---: | --- | --- |')
    for r in sorted(s['dead'], key=lambda x: -x['freq'])[:40]:
        A('| %s | %s | %s | %s |'
          % (r['word'], f'{r["freq"]:,}',
             '　'.join('`%s`' % c for c in r['dead']),
             '　'.join('`%s`' % c for c in sorted(r['reach']))))
    A('')
    A('`X7`（学习）属于另一类：`7` 只有左手式 `(sdf)`，而 `X` 的右手式与 `(sdf)` 组合后')
    A('走不到 `X7` 这条输出，所以同样不可达。')
    A('')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true', help='写出 multi_code_report.md')
    args = ap.parse_args()

    print('读取词库与击数模型…')
    rows, code_owner = collect()
    s = summarize(rows)
    print('简码条目 %d（1 条 %d / 2 条 %d / 3 条 %d / 4 条 %d）'
          % (len(rows),
             sum(1 for r in rows if len(r['codes']) == 1),
             sum(1 for r in rows if len(r['codes']) == 2),
             sum(1 for r in rows if len(r['codes']) == 3),
             sum(1 for r in rows if len(r['codes']) >= 4)))
    print('挂 ≥2 条简码：%d（词语 %d / 单字 %d）'
          % (len(s['multi']), len(s['multi_word']), len(s['multi_char'])))
    print('  ├ 几条全都能打出来：%d（词语 %d / 单字 %d）'
          % (len(s['pure']), len(s['pure_word']), len(s['pure_char'])))
    print('  └ 含打不出来的死码：%d（词语 %d / 单字 %d）'
          % (len(s['dead']), len(s['dead_word']), len(s['dead_char'])))
    if args.report:
        with open(REPORT, 'w', encoding='utf-8') as f:
            f.write(build_report(rows, s, code_owner))
        print('报告已写入 %s' % REPORT)


if __name__ == '__main__':
    main()
