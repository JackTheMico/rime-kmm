#!/usr/bin/env python3
"""空明码-宏版S：清理「打不出来」的简码 —— 能修的修，修不了的删。

背景
----
一次并击 = 左右手各一个码元，且 algebra 里 `(sdf)`→`7`、`(wer)`→`8`、`(xcv)`→`9` 都是
**左手三键**。所以数字码元必须排在字母码元**前面**，否则两个码元都落在左手，同手冲突、
引擎收到的是反过来的串。词库历史遗留把这批写成了「字母+数字」：

    i8（的时候）  实际能打的写法是 8i
    F9（方式）    → 9F
    X7（学习）    → 7X

处理
----
对每条「≤2 码元且一击不可达」的码：

1. 反转顺序后可达、且码位空着 → **改写**（这是纯增益：词多一条一击路）
2. 反转后撞车（已被更常用的词占着）/ 反转也不可达 → **删除**（本来打不出来，占着也是死位）
3. 反转也不可达的**标点/符号直出码**（`;6`=^、`1~`=壹、`` ` `` …）→ **不动**，
   它们走 key_binder 或 punctuator，不在并击模型里
4. 含 1~6 的码 → **不动**（1-6 不在 chord 字母表里，靠 Ctrl 送键，属另一条路径）
5. 词条没有其它可用码 → **不删**（否则整个词会从词库消失）

用法
----
    python3 tools/km_fix_dead.py                # 预览
    python3 tools/km_fix_dead.py --apply --with-trad
"""
import argparse
import collections
import datetime
import importlib.util
import os
import shutil
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
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORT = os.path.join(REPORTS, 'dead_code_report.md')
KEYBINDER_DIGITS = set('123456')     # 1-6 不在 chord 字母表，靠 Ctrl 送键
MAX_LEN = 2                          # 只动 ≤2 码元的简码档


def load_kmopt():
    spec = importlib.util.spec_from_file_location('kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


kmopt = load_kmopt()
ONE = chord.one_press_codes()


def is_han(w):
    return all('\u4e00' <= ch <= '\u9fff' for ch in w)


def analyze():
    header, entries = kmopt.load_dict(DICT_S)
    freq = kmopt.load_freq()

    codes = collections.defaultdict(list)
    word_codes = collections.defaultdict(list)
    for w, c, raw in entries:
        codes[c].append(w)
        if ' ' not in w:
            word_codes[w].append(c)

    cnt = {c: len(v) for c, v in codes.items()}
    pref = set()
    for c in cnt:
        for i in range(1, len(c)):
            pref.add(c[:i])

    def cost(c):
        st = chord.strokes(c, ONE)
        if st >= 99:
            return 99
        return st if (c not in pref and cnt[c] == 1) else st + 1

    fixes, dels, skip = [], [], []
    for w, c, raw in entries:
        if len(c) > MAX_LEN or chord.strokes(c, ONE) < 99:
            continue
        if not is_han(w):
            skip.append((w, c, '标点/符号直出码'))
            continue
        if set(c) & KEYBINDER_DIGITS:
            skip.append((w, c, '含 1~6，走 Ctrl 送键'))
            continue

        others = [x for x in word_codes[w] if x != c]
        good = [x for x in others if chord.strokes(x, ONE) < 99]
        if not good:
            skip.append((w, c, '删了该词就没码了'))
            continue

        flip = c[::-1]
        if chord.strokes(flip, ONE) < 99 and flip not in codes:
            now = min((cost(x) for x in others), default=99)
            fixes.append({
                'word': w, 'old': c, 'new': flip, 'freq': freq.get(w, 0),
                'now': now, 'gain': freq.get(w, 0) * max(0, now - 1),
            })
        else:
            why = ('反转成 %s 已被 %s 占用' % (flip, '/'.join(codes[flip][:2]))
                   if flip in codes else '反转后仍不可达')
            dels.append({'word': w, 'code': c, 'freq': freq.get(w, 0), 'why': why})

    return header, entries, fixes, dels, skip, codes


def rewrite(path, fixes, dels, trad_map=None, apply=False, stamp=''):
    """删掉 fixes 的旧码与 dels 的码，把 fixes 的新码插到同首字符的末尾。"""
    header, entries = kmopt.load_dict(path)
    drop = {(f['word'], f['old']) for f in fixes} | {(d['word'], d['code']) for d in dels}

    last_of_head = {}
    for i, (w, c, raw) in enumerate(entries):
        if (w, c) in drop:
            continue
        last_of_head[c[0]] = i

    by_anchor = collections.defaultdict(list)
    for f in fixes:
        text = trad_map.get(f['word'], f['word']) if trad_map else f['word']
        pos = last_of_head.get(f['new'][0], len(entries) - 1)
        by_anchor[pos].append('%s\t%s' % (text, f['new']))

    out, n_rm, n_add = [], 0, 0
    for i, (w, c, raw) in enumerate(entries):
        if (w, c) in drop:
            n_rm += 1
        else:
            out.append(raw)
        if i in by_anchor:
            out.extend(by_anchor[i])
            n_add += len(by_anchor[i])

    if n_add != len(fixes):
        raise RuntimeError('新增条目数不符：计划 %d，实际 %d（锚点落空？）' % (len(fixes), n_add))

    if apply:
        bak = '%s.bak-%s' % (path, stamp)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header + out) + '\n')
    return n_rm, n_add


def report(fixes, dels, skip, stamp):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []
    A = L.append
    gain = sum(f['gain'] for f in fixes)
    A('# 空明码-宏版S：清理打不出来的简码\n')
    A('> 生成时间：%s　工具：`tools/km_fix_dead.py`\n' % now)
    A('## 1. 为什么会有这种码\n')
    A('一次并击要求**左右手各出一个码元**。而 `(sdf)`→`7`、`(wer)`→`8`、`(xcv)`→`9` ')
    A('都是**左手三键**，所以数字码元必须排在字母**前面**。词库把一批写成了「字母+数字」：\n')
    A('| 词 | 词库里写的 | 实际引擎收到 | 能打的写法 |')
    A('| --- | :---: | :---: | :---: |')
    A('| 的时候 | `i8` | `8i` | `8i` |')
    A('| 方式 | `F9` | `9F` | `9F` |')
    A('| 学习 | `X7` | `7X` | `7X` |')
    A('')
    A('另外 `/` 之前被我误判成死码 —— `xform=(z-v-|m-G-)=/=` 这条规则的替换值是 `/`，')
    A('`z+v` 并击就能打出，`/S`、`/d`、`/Z` 全是活的。本轮已修正模型。\n')
    A('## 2. 处理结果\n')
    A('| 动作 | 条数 | 说明 |')
    A('| --- | ---: | --- |')
    A('| 改写（写反了，反转后可用） | **%d** | 净省 **%s** 个动作 |' % (len(fixes), f'{gain:,}'))
    A('| 删除（反转撞车 / 仍不可达） | **%d** | 本来打不出来，白占码位 |' % len(dels))
    A('| 保留不动 | %d | 标点直出码、含 1~6 的 Ctrl 送键码、删了就没码的词 |' % len(skip))
    A('')
    A('## 3. 改写清单（%d 条，净省 %s）\n' % (len(fixes), f'{gain:,}'))
    A('| 词 | 词频 | 旧码 | 新码 | 原成本 | 省 |')
    A('| --- | ---: | :---: | :---: | ---: | ---: |')
    for f in sorted(fixes, key=lambda x: -x['gain']):
        A('| %s | %s | `%s` | **`%s`** | %d | %s |'
          % (f['word'], f'{f["freq"]:,}', f['old'], f['new'], f['now'], f'{f["gain"]:,}'))
    A('')
    A('## 4. 删除清单（%d 条）\n' % len(dels))
    A('| 词 | 词频 | 死码 | 原因 |')
    A('| --- | ---: | :---: | --- |')
    for d in sorted(dels, key=lambda x: -x['freq']):
        A('| %s | %s | `%s` | %s |'
          % (d['word'], f'{d["freq"]:,}', d['code'], d['why']))
    A('')
    A('## 5. 保留不动的（%d 条）\n' % len(skip))
    grp = collections.Counter(s[2] for s in skip)
    for k, v in grp.most_common():
        A('- %s：%d 条' % (k, v))
    A('')
    A('## 6. 回滚\n')
    A('```bash')
    A('cp kongmingmas.dict.yaml.bak-%s kongmingmas.dict.yaml' % stamp)
    A('cp kongmingmas_t.dict.yaml.bak-%s kongmingmas_t.dict.yaml' % stamp)
    A('```')
    A('')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    args = ap.parse_args()

    print('读取词库与击数模型…')
    header, entries, fixes, dels, skip, codes = analyze()
    print('改写 %d 条，删除 %d 条，保留 %d 条' % (len(fixes), len(dels), len(skip)))
    print('改写净省 %s 个动作' % f'{sum(f["gain"] for f in fixes):,}')

    if not args.apply:
        print('\n预览（未写盘）：')
        for f in sorted(fixes, key=lambda x: -x['gain'])[:20]:
            print('  改写 %-10s %-4s → %-4s 省 %s'
                  % (f['word'], f['old'], f['new'], f'{f["gain"]:,}'))
        for d in sorted(dels, key=lambda x: -x['freq'])[:10]:
            print('  删除 %-10s %-4s（%s）' % (d['word'], d['code'], d['why']))
        return

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    trad_map = None
    if args.with_trad:
        trad_map = kmopt.to_trad(sorted({f['word'] for f in fixes}))

    assert len({f['new'] for f in fixes}) == len(fixes), '新码重复'
    for f in fixes:
        assert f['new'] not in codes, '新码已被占用：%s' % f['new']

    n_rm, n_add = rewrite(DICT_S, fixes, dels, apply=True, stamp=stamp)
    print('简体库：删 %d 行，增 %d 行' % (n_rm, n_add))
    if args.with_trad:
        f_t = [dict(f, word=trad_map.get(f['word'], f['word'])) for f in fixes]
        d_t = [dict(d, word=trad_map.get(d['word'], d['word'])) for d in dels]
        n2, n3 = rewrite(DICT_T, f_t, d_t, apply=True, stamp=stamp)
        print('繁体库：删 %d 行，增 %d 行' % (n2, n3))

    with open(REPORT, 'w', encoding='utf-8') as fh:
        fh.write(report(fixes, dels, skip, stamp))
    print('报告已写入 %s' % REPORT)


if __name__ == '__main__':
    main()
