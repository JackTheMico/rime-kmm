#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回补「码位只剩空格后缀构造」的条目。

背景
----
词库头是 `sort: original`，Rime 完全按文件行序排列同码候选，词库本身
没有任何权重列（严格两列 `词条<TAB>码`）。所以「字频」并不会被改动，
改变的只是某个词条在文件里的去留 —— 拿掉一条，同码的下一条就顶上首位。

`tools/km_one_code.py` 收敛「一词一码」时，会把某条简码整行删掉。如果该码位
剩下的全是「字+空格+后缀」构造（如 `载 ;` / `枣 o`），那么这一删就把首候选
变成了这种构造，用户敲 `Zj` 看到的第一个就变成 `载 ;`，而真正的头名（`再`）
消失。这类码位等于被废掉。

本工具按「改动前的备份」把这类条目原样补回，并插到该码位第一条之前，
使其重新成为首候选。

用法
----
    python3 tools/km_code_head_fix.py                      # 预览
    python3 tools/km_code_head_fix.py --apply              # 写简体
    python3 tools/km_code_head_fix.py --apply --with-trad  # 简繁都写
    python3 tools/km_code_head_fix.py --base <备份路径>

产出
----
    docs/reports/code_head_fix_report.md
"""
import argparse
import collections
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import km_jianma_opt as kmopt          # noqa: E402

DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORTS = os.path.join(ROOT, 'docs', 'reports')
REPORT = os.path.join(REPORTS, 'code_head_fix_report.md')

BASE_S = DICT_S + '.bak-20261115-201820'
BASE_T = DICT_T + '.bak-20261115-201820'


def is_suffix(text):
    """「字+空格+后缀」构造：文本里带空格。"""
    return ' ' in text


def scan(path, base):
    """返回 (header, entries, restore, stats)。restore: [(word, code, 原首候选说明)]"""
    header, entries = kmopt.load_dict(path)
    cur = {(w, c) for w, c, _ in entries}
    by_code = collections.defaultdict(list)
    for i, (w, c, _) in enumerate(entries):
        by_code[c].append(i)

    base_header, base_entries = kmopt.load_dict(base)

    restore, skipped_occupied, gone = [], [], []
    seen = set()
    for w, c, _ in base_entries:
        if (w, c) in cur or (w, c) in seen:
            continue
        seen.add((w, c))
        if is_suffix(w):
            continue                      # 后缀构造本身不补
        idxs = by_code.get(c)
        if not idxs:
            gone.append((w, c))           # 整个码位没了，不属本工具范围
            continue
        texts = [entries[i][0] for i in idxs]
        if not all(is_suffix(t) for t in texts):
            skipped_occupied.append((w, c, texts[0]))
            continue
        restore.append({'word': w, 'code': c, 'head_now': texts[0],
                        'n_suffix': len(texts)})
    return header, entries, restore, {'gone': gone, 'skipped': skipped_occupied}


def rewrite(path, header, entries, restore, apply=False, stamp=''):
    """把 restore 的条目插到各自码位的第一条之前。"""
    by_code = collections.defaultdict(list)
    for i, (_, c, _) in enumerate(entries):
        by_code[c].append(i)

    at = collections.defaultdict(list)
    for r in restore:
        at[by_code[r['code']][0]].append('%s\t%s' % (r['word'], r['code']))

    out, n_add = [], 0
    for i, (_, _, raw) in enumerate(entries):
        out.extend(at.get(i, []))
        n_add += len(at.get(i, []))
        out.append(raw)

    if n_add != len(restore):
        raise RuntimeError('回补数不符：计划 %d，实际 %d' % (len(restore), n_add))

    if apply:
        bak = '%s.bak-%s' % (path, stamp)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header + out) + '\n')

        # 自检：补完后只剩后缀构造的码位，应当正好少掉这次补的那些
        before = collections.defaultdict(list)
        for w, c, _ in entries:
            before[c].append(w)
        expect = {c for c, ts in before.items() if all(is_suffix(t) for t in ts)}
        expect -= {r['code'] for r in restore}

        _, after = kmopt.load_dict(path)
        ctx = collections.defaultdict(list)
        for w, c, _ in after:
            ctx[c].append(w)
        got = {c for c, ts in ctx.items() if ts and all(is_suffix(t) for t in ts)}
        if got != expect:
            raise RuntimeError('自检失败：多出 %s，少了 %s'
                               % (sorted(got - expect)[:5], sorted(expect - got)[:5]))
    return n_add


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    ap.add_argument('--base', default='', help='改动前的备份路径（默认简体那份 20:18 备份）')
    ap.add_argument('--top', type=int, default=30)
    args = ap.parse_args()

    stamp = time.strftime('%Y%m%d-%H%M%S')
    jobs = [('S', DICT_S, args.base or BASE_S)]
    if args.with_trad:
        jobs.append(('T', DICT_T, args.base or BASE_T))

    freq = kmopt.load_freq()
    summary, detail = [], {}
    for tag, path, base in jobs:
        if not os.path.exists(base):
            print('!! 备份不存在：%s' % base)
            continue
        header, entries, restore, st = scan(path, base)
        restore.sort(key=lambda r: -freq.get(r['word'], 0))
        n = rewrite(path, header, entries, restore, apply=args.apply, stamp=stamp)
        summary.append((tag, len(restore), len(st['gone']), len(st['skipped']), n))
        detail[tag] = restore
        print('%s：需回补 %d 条（腾空码位 %d、仍有真候选 %d）%s'
              % (tag, len(restore), len(st['gone']), len(st['skipped']),
                 '，已写入 %d' % n if args.apply else ''))

    if args.apply and summary:
        with open(REPORT, 'w', encoding='utf-8') as f:
            L = []
            A = L.append
            A('# 码位首候选回补报告\n')
            A('生成时间：%s\n' % stamp)
            A('## 结论\n')
            A('| 库 | 回补条目 | 真腾空码位 | 仍有真候选（不回补） |')
            A('| :--- | ---: | ---: | ---: |')
            for tag, nr, ng, ns, _ in summary:
                A('| %s | **%d** | %d | %d |'
                  % ('简体' if tag == 'S' else '繁体', nr, ng, ns))
            A('')
            A('- 词库无权重列、头是 `sort: original`，同码候选按**文件行序**排列；')
            A('  删掉一条真候选后，同码的「字+空格+后缀」构造就会顶到首位（`Zj` 的 `载 ;`）。')
            A('- 本工具只补「补完之前该码位只剩后缀构造」的条目，不动还有其他真候选的码位。')
            A('')
            for tag, rows in detail.items():
                A('## %s：回补清单（前 %d）\n' % ('简体' if tag == 'S' else '繁体', args.top))
                A('| 词条 | 码 | 词频 | 原首候选 | 后缀构造数 |')
                A('| :--- | :---: | ---: | :--- | ---: |')
                for r in rows[:args.top]:
                    A('| %s | `%s` | %s | `%s` | %d |'
                      % (r['word'], r['code'], f'{freq.get(r["word"], 0):,}',
                         r['head_now'], r['n_suffix']))
                A('')
            f.write('\n'.join(L))
        print('报告：%s' % REPORT)


if __name__ == '__main__':
    sys.exit(main())
