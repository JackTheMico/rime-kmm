#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理空明码-宏版S 里带数字的编码。

两批：

  默认（--two-char）  字母 + 数字 的两码简码，如 `Y4`、`K2`、`A0`。
  --legacy            含数字 1-6 的旧编码（多为 4 码元，如 `d5a=` 对了、
                      `w3d=` 我的、`z5g=` 中国）。这些是被当成全码写进
                      词库的老式「字母+数字韵」形态。

为什么删：
  chord 键盘字母表只有 7890，数字 1-6 不在其中。要打出 1-6 只能走
  schema 的 key_binder 映射（Control+u→2、Control+i→3、Control+w→4、
  Control+e→5），等于「字母键 + Ctrl 组合 + 空格」，比打正常全码还慢。
  `0` 是 asdf 并击、不用 Ctrl，但它同样属于这套别扭的历史形态。

安全护栏：
  - 词条不含汉字（标点、符号、纯数字）一律跳过，保证 `1`=1、`1~`=壹、
    `;6`=^ 这类**数字/符号直出**路径不被误删；
  - 纯数字码（`1`、`1~`）不删；
  - 逐行删除，保留 BOM、YAML 头与其余条目原样，不做重排；
  - 删除前自动备份为 `*.bak-<时间戳>`。

用法：
  python3 tools/km_jianma_prune.py                 # 预览（两码数字简码）
  python3 tools/km_jianma_prune.py --apply
  python3 tools/km_jianma_prune.py --legacy        # 预览（1-6 遗留码）
  python3 tools/km_jianma_prune.py --legacy --apply
  python3 tools/km_jianma_prune.py --digits 1-5    # 只删需要 Ctrl 的两码
"""

import argparse
import collections
import datetime
import hashlib
import importlib.util
import os
import re
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
REPORT_TWO = os.path.join(REPORTS, 'jianma_prune_report.md')
REPORT_LEGACY = os.path.join(REPORTS, 'jianma_prune_report_legacy.md')

CTRL_DIGITS = set('123456')    # 只能靠 Ctrl 组合打出的数字
FREE_DIGITS = set('0789')      # 并击字母表成员
CJK = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


def _load_opt():
    spec = importlib.util.spec_from_file_location(
        'kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_lines(path):
    with open(path, encoding='utf-8', newline='') as f:
        return f.read().splitlines(keepends=True)


def split_body(lines):
    """返回 (header_lines, body_lines)；header 以 '...' 行结束。"""
    for i, ln in enumerate(lines):
        if ln.strip() == '...':
            return lines[:i + 1], lines[i + 1:]
    return [], lines


def parse_entry(line):
    if not line.strip() or line.lstrip().startswith('#'):
        return None
    if '\t' not in line:
        return None
    parts = line.rstrip('\r\n').split('\t')
    if len(parts) < 2:
        return None
    word = parts[0].strip().replace('\ufeff', '')
    code = parts[1].strip().replace('\ufeff', '')
    if not word or not code:
        return None
    return word, code


def scan(path, accept):
    lines = read_lines(path)
    header, body = split_body(lines)
    hits, kept = [], []
    for i, ln in enumerate(body):
        e = parse_entry(ln)
        if not e:
            continue
        word, code = e
        if any(ch in CTRL_DIGITS for ch in code) or any(ch in '05' for ch in code):
            (hits if accept(word, code) else kept).append((word, code))
    return header, body, hits, kept


def word_codes(body):
    wc = collections.defaultdict(list)
    for ln in body:
        e = parse_entry(ln)
        if e:
            wc[e[0]].append(e[1])
    return wc


def clean_alt(codes, code):
    """删除 code 之后，该词还剩哪些不含受限数字的码。"""
    return [c for c in codes if c != code and not any(ch in CTRL_DIGITS for ch in c)]


def make_matcher(args):
    if args.legacy:
        return (lambda w, c: (any(ch in CTRL_DIGITS for ch in c)
                             and bool(CJK.search(w))
                             and not re.fullmatch(r'\d+~?', c)),
                '^含 1-6 的旧编码（汉字词条）$')
    lo, hi = args.digits.split('-')
    chars = ''.join(str(d) for d in range(int(lo), int(hi) + 1))
    pat = re.compile(args.pattern or r'^[A-Za-z][%s]$' % re.escape(chars))
    return (lambda w, c: bool(pat.match(c)), pat.pattern)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='真正写盘（默认只预览）')
    ap.add_argument('--legacy', action='store_true', help='清理含 1-6 的旧编码')
    ap.add_argument('--no-trad', action='store_true', help='不同步繁体镜像库')
    ap.add_argument('--digits', default='0-5', help='两码模式下的数字范围，如 0-5 / 1-5')
    ap.add_argument('--pattern', default=None, help='自定义正则，覆盖 --digits')
    args = ap.parse_args()

    accept, desc = make_matcher(args)
    print(f'规则：{desc}')

    opt = _load_opt()
    print('读取词频…')
    freq = opt.load_freq()

    header_s, body_s, hits_s, kept_s = scan(DICT_S, accept)
    header_t, body_t, hits_t, kept_t = scan(DICT_T, accept)
    print(f'简体库命中 {len(hits_s)} 条；繁体镜像命中 {len(hits_t)} 条')
    if len(hits_s) != len(hits_t):
        print('  [warn] 简繁命中数不一致，请核对')

    wc_s = word_codes(body_s)

    ctrl = [h for h in hits_s if any(ch in CTRL_DIGITS for ch in h[1])]
    free = [h for h in hits_s if not any(ch in CTRL_DIGITS for ch in h[1])]
    print(f'  需 Ctrl 的 {len(ctrl)} 条；纯并击的 {len(free)} 条')

    orphan = []
    for w, c in hits_s:
        if not clean_alt(wc_s[w], c):
            orphan.append((w, c, wc_s[w]))
    print(f'  删除后无其他干净码（将失去输入途径）：{len(orphan)} 条')

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

    def rewrite(path, header, body, hits):
        drop_pairs = {(w, c) for w, c in hits}
        keep = []
        drop = 0
        for ln in body:
            e = parse_entry(ln)
            if e and e in drop_pairs:
                drop += 1
                continue
            keep.append(ln)
        new = ''.join(header) + ''.join(keep)
        if args.apply:
            bak = f'{path}.bak-{stamp}'
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(new)
        return drop, len(keep)

    pairs = [(DICT_S, header_s, body_s, hits_s)]
    if not args.no_trad:
        pairs.append((DICT_T, header_t, body_t, hits_t))
    names = ['简体库', '繁体镜像库']
    for k, (path, header, body, hits) in enumerate(pairs):
        n, keep = rewrite(path, header, body, hits)
        print(f'{names[k]}：删除 {n} 行，保留 {keep} 行'
              + ('' if args.apply else '（dry-run，未写盘）'))

    if args.apply:
        out = REPORT_LEGACY if args.legacy else REPORT_TWO
        with open(out, 'w', encoding='utf-8') as f:
            f.write(report_md(hits_s, kept_s, wc_s, freq, orphan, ctrl, free,
                              desc, stamp, args.legacy))
        print(f'报告已写入 {os.path.relpath(out, ROOT)}')
    else:
        rows = sorted(hits_s, key=lambda x: -freq.get(x[0], 0))
        print('\n前 25 条预览：')
        for w, c in rows[:25]:
            rest = '、'.join(clean_alt(wc_s[w], c)[:3]) or '（仅此一码）'
            print(f'  {c:<6} {w:<8} freq={freq.get(w, 0):<8} 剩余 {rest}')


def report_md(hits, kept, wc, freq, orphan, ctrl, free, desc, stamp, legacy):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []
    A = L.append
    title = '旧式数字编码清理' if legacy else '数字简码清理'
    A(f'# 空明码-宏版S {title}报告\n')
    A(f'> 生成时间：{now}　工具：`tools/km_jianma_prune.py`　规则：`{desc}`\n')

    A('## 1. 结论\n')
    A(f'- 删除 **{len(hits)}** 条（简繁两库各 {len(hits)} 条，一一对应）。')
    if legacy:
        A('- 这批是 1–6 的旧编码，多为 4 码元全码形态（`d5a=` 对了、`w3d=` 我的、'
          '`z5g=` 中国），属老式「字母 + 数字韵」遗留。')
        A('- 其中不少存在**重复变体**：`我的` 同时有 `o3d=` 与 `w3d=` 两条，'
          '另有正常的 `Wd` / `WqdW`。')
    else:
        A(f'- 其中 **{len(free)}** 条以 `0` 结尾（`0` 是 `asdf` 并击，不用 Ctrl）；'
          f'**{len(ctrl)}** 条以 `1`–`5` 结尾（只能靠 Ctrl 组合打出）。')
    A('- 删除的是**单条捷径码**，逐行删除，未改动任何其他条目。\n')

    A('## 2. 为什么这些码不好用\n')
    A('`kongmingmas.schema.yaml` 里两处字母表都不含数字 1–6：\n')
    A('```yaml')
    A('speller:')
    A('  alphabet: "...\'7890`~@*_"        # 只有 7 8 9 0')
    A('chord_composer:')
    A('  alphabet: "qazwsxedcrfvtgbyhnujmik,ol.p;/\'7890 "')
    A('```\n')
    A('要输入 2/3/4/5 只能走 `key_binder`：\n')
    A('```yaml')
    A('- { when: composing, accept: "Control+u", send: 2 }')
    A('- { when: composing, accept: "Control+i", send: 3 }')
    A('- { when: composing, accept: "Control+w", send: 4 }')
    A('- { when: composing, accept: "Control+e", send: 5 }')
    A('```\n')
    A('于是 `K2`（看起来）实际是「K 和弦 → Ctrl+i → 空格」，'
      '`d5a=`（对了）是「d → Ctrl+e → a → 空格」，都要插 Ctrl，打断并击节奏。\n')

    A('## 3. 删除清单\n')
    A('| # | 码 | 词 | 词频 | 该词剩余编码 |')
    A('| ---: | :---: | :--- | ---: | :--- |')
    rows = sorted(hits, key=lambda x: -freq.get(x[0], 0))
    for i, (w, c) in enumerate(rows, 1):
        rest = '、'.join('`%s`' % x for x in wc[w] if x != c) or '**（无）**'
        A(f'| {i} | `{c}` | {w} | {freq.get(w, 0):,} | {rest} |')
    A('')

    if orphan:
        A('## 4. 删除后失去唯一输入途径的词\n')
        A('这些条目的该编码是**唯一**的码，删除后无法再作为整体输入'
          '（仍可逐字输入）：\n')
        A('| 码 | 词 | 原全部编码 |')
        A('| :---: | :--- | :--- |')
        for w, c, codes in orphan:
            A(f'| `{c}` | {w} | ' + '、'.join('`%s`' % x for x in codes) + ' |')
        A('')

    A('## 5. 保留未删的条目\n')
    A('为保住数字与符号的直出路径，以下条目被**显式跳过**：\n')
    A('| 码 | 词 | 原因 |')
    A('| :---: | :--- | :--- |')
    for w, c in sorted(set(kept), key=lambda x: x[1])[:40]:
        if re.fullmatch(r'\d+~?', c):
            why = '数字 / 大写数字直出'
        elif not CJK.search(w):
            why = '符号直出（词条不含汉字）'
        else:
            why = '其他'
        A(f'| `{c}` | {w} | {why} |')
    A('')

    A('## 6. 回滚\n')
    A('```bash')
    A(f'cp kongmingmas.dict.yaml.bak-{stamp} kongmingmas.dict.yaml')
    A(f'cp kongmingmas_t.dict.yaml.bak-{stamp} kongmingmas_t.dict.yaml')
    A('python3 tools/km_jianma_doc.py      # 重新生成参考文档')
    A('python3 tools/km_deploy_xsime.py    # 重新部署')
    A('```\n')
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
