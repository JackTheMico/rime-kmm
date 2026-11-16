#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 01 — 一击码面物理容量盘点（只读，不改词库/现有文件）。

口径来源（全部只读，不写盘）：
- 一击可达码：tools/km_chord_model.py:one_press_codes()（权威，照抄 algebra）
- 词库：kongmingmas.dict.yaml 逐行流式读取
- 零延伸/唯一候选：对齐 tools/km_jianma_doc.py:build() 与
  tools/km_char_onehit.py:tier()，并额外给「含空格词条的码」口径做对照
- 族分类：对齐 tools/km_jianma_doc.py:family_of()

运行：
  /home/jackwy/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
      .scratch/km-code-length-0.6/research/one_strike_capacity_analysis.py
"""
import collections
import importlib.util
import os

ROOT = '/home/jackwy/Nextcloud/kmrime'
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chord = _load('km_chord_model', os.path.join(ROOT, 'tools/km_chord_model.py'))


def family_of(code):
    """对齐 km_jianma_doc.family_of，细分数字族。"""
    if '=' in code:
        return '空格并击'
    if code.isalpha():
        return '纯字母'
    if not code[0].isalpha():
        return '前缀:' + code[0]
    if len(code) > 1 and not code[1].isalpha():
        return '后缀:' + code[1]
    return '其他'


def fam_lump(fam):
    """粗分到票面要求的族。"""
    if fam == '纯字母':
        return '纯字母'
    if fam == '空格并击':
        return '空格并击'
    if fam.startswith('前缀:'):
        m = fam.split(':', 1)[1]
        if m in '0789':
            return '数字前缀' + m
        if m.isdigit():
            return '数字前缀其他'
        return '符号前缀' + m
    if fam.startswith('后缀:'):
        m = fam.split(':', 1)[1]
        if m in '0789':
            return '数字后缀' + m
        if m.isdigit():
            return '数字后缀其他'
        return '符号后缀' + m
    return fam


def main():
    one = chord.one_press_codes()
    print('=== A. 一击可达码基线 ===')
    print('one_press_codes 总数 = %d' % len(one))
    len_dist = collections.Counter(len(c) for c in one)
    print('码长(字符)分布 = %s' % dict(sorted(len_dist.items())))

    # ---------- 读词库 ----------
    entries = []
    with open(DICT_S, encoding='utf-8') as fh:
        started = False
        for line in fh:
            s = line.rstrip('\n')
            if not s:
                continue
            if not started:
                if s == '...':
                    started = True
                continue
            if s.startswith('#') or '\t' not in s:
                continue
            w, c = s.split('\t', 1)
            entries.append((w.replace('\ufeff', ''), c))

    codes_indep = collections.defaultdict(list)   # 独立词条（不含空格词）
    allcode_count = collections.Counter()          # 所有数据行
    code_first = {}
    for w, c in entries:
        allcode_count[c] += 1
        if c not in code_first:
            code_first[c] = w
        if ' ' in w:
            continue
        codes_indep[c].append(w)

    def prefixes(cset):
        p = set()
        for c in cset:
            for i in range(1, len(c)):
                p.add(c[:i])
        return p

    pref_indep = prefixes(codes_indep)     # 权威文档口径（跳过含空格词条）
    pref_all = prefixes(allcode_count)     # 严格口径（含空格词条也占位）

    print('\n=== B. 词库规模 ===')
    print('数据行 = %d, 不同码(独立) = %d, 不同码(全部行) = %d'
          % (len(entries), len(codes_indep), len(allcode_count)))
    print('跨行多候选码(独立, count>=2) = %d'
          % sum(1 for v in codes_indep.values() if len(v) >= 2))

    # ---------- 复现已知数 ----------
    auto_1396 = [c for c in codes_indep
                 if len(c) <= 3 and c not in pref_indep and len(codes_indep[c]) == 1]
    auto_1377 = [c for c in codes_indep
                 if c in one and c not in pref_indep and len(codes_indep[c]) == 1]
    print('\n=== C. 复现已知数（校验口径）===')
    print('≤3码元零延伸唯一(jianma_doc口径) = %d  (期望 1396)' % len(auto_1396))
    print('one可达零延伸唯一(char_onehit口径) = %d  (期望 1377)' % len(auto_1377))

    # ---------- 9111 全量分类矩阵 ----------
    # 用严格口径 pref_all 判零延伸；同时给权威口径 pref_indep 对照
    mat = collections.Counter()
    detail = collections.defaultdict(list)
    for c in one:
        in_dict = c in allcode_count
        n_indep = len(codes_indep.get(c, []))
        if c in pref_all:
            cat = 'ext-有延伸(严格)'
        elif in_dict and n_indep == 1:
            cat = 'auto-零延伸唯一'
        elif in_dict and n_indep >= 2:
            cat = 'zero-零延伸多候选'
        elif in_dict and n_indep == 0:
            cat = 'zero-仅空格构造层'
        else:
            cat = 'empty-词库无此码'
        # empty 再分干净/污染
        if cat == 'empty-词库无此码':
            cat += '-clean' if c not in pref_all else '-dirty'
        mat[cat] += 1
        detail[cat].append(c)

    print('\n=== D. 9111 一击码分类矩阵（严格 pref_all 口径）===')
    for k in sorted(mat):
        print('  %-28s %d' % (k, mat[k]))
    print('  合计 = %d' % sum(mat.values()))

    # auto 用两种 prefix 口径的差异
    auto_strict = [c for c in codes_indep
                   if c in one and c not in pref_all and len(codes_indep[c]) == 1]
    print('\n[口径差异] auto(严格pref_all) = %d vs auto(权威pref_indep) = %d, 差 %d'
          % (len(auto_strict), len(auto_1377), len(auto_1377) - len(auto_strict)))

    # ---------- 理论上限三档 ----------
    print('\n=== E. 一击上屏天花板（三档）===')
    print('[硬上限] 物理码面 = %d（algebra+左右手约束，不可突破）' % len(one))
    # 保留全部现有词条的零延伸唯一上限：one 中不属于任何词库码前缀的码
    keep = [c for c in one if c not in pref_all]
    print('[保留全部现有长码] one中非任何词库码前缀 = %d' % len(keep))
    # 完全重排词库、只留一击码：one 内部不构成前缀的码
    pref_one = set()
    for c in one:
        for i in range(1, len(c)):
            pref_one.add(c[:i])
    internal = [c for c in one if c not in pref_one]
    print('[只留一击码重排] one内部非前缀码 = %d' % len(internal))
    print('  one内部互为前缀而被迫二选一的码数 = %d' % (len(one) - len(internal)))

    # ---------- F. 各族盘点 ----------
    print('\n=== F. 各族盘点（one 可达码面 / 当前auto / 干净空槽 / 污染空槽）===')
    fam_one = collections.Counter()
    fam_auto = collections.Counter()
    fam_clean = collections.Counter()
    fam_dirty = collections.Counter()
    fam_zero = collections.Counter()
    fam_ext = collections.Counter()
    for c in one:
        g = fam_lump(family_of(c))
        fam_one[g] += 1
    for c in auto_strict:
        fam_auto[fam_lump(family_of(c))] += 1
    for cat, lst in detail.items():
        for c in lst:
            g = fam_lump(family_of(c))
            if cat.startswith('empty') and cat.endswith('-clean'):
                fam_clean[g] += 1
            elif cat.startswith('empty') and cat.endswith('-dirty'):
                fam_dirty[g] += 1
            elif cat.startswith('zero'):
                fam_zero[g] += 1
            elif cat.startswith('ext'):
                fam_ext[g] += 1
    hdr = '%-14s %8s %8s %8s %8s %8s %8s' % (
        '族', 'one码面', '当前auto', '干净空槽', '污染空槽', 'zero', 'ext')
    print(hdr)
    for g in sorted(fam_one, key=lambda x: -fam_one[x]):
        print('%-14s %8d %8d %8d %8d %8d %8d' % (
            g, fam_one[g], fam_auto[g], fam_clean[g], fam_dirty[g],
            fam_zero[g], fam_ext[g]))
    print('%-14s %8d %8d %8d %8d %8d %8d' % (
        '合计', sum(fam_one.values()), sum(fam_auto.values()),
        sum(fam_clean.values()), sum(fam_dirty.values()),
        sum(fam_zero.values()), sum(fam_ext.values())))

    # ---------- G. 符号/数字字符集 ----------
    print('\n=== G. one 里出现的全部字符 ===')
    chars = collections.Counter()
    for c in one:
        for ch in c:
            chars[ch] += 1
    print('字符集 = %s' % ''.join(sorted(chars)))
    nonalpha = sorted(ch for ch in chars if not ch.isalpha() and ch != ' ')
    print('非字母非空格字符 = %s' % ''.join(nonalpha))

    # ---------- H. 铁律复核 ----------
    print('\n=== H. 铁律复核 ===')
    # 1-6 是否出现在任何一击码
    d16 = [c for c in one if any(ch in '123456' for ch in c)]
    print('one中含 1-6 的码 = %d  %s' % (len(d16), d16[:30]))
    # X~ 后缀族 / 数字大写族
    tilde_suf = sorted(c for c in one if c.endswith('~'))
    tilde_digit = sorted(c for c in one
                         if len(c) == 2 and c[0].isdigit() and c[1] == '~')
    print('one中 X~ 后缀族 = %d' % len(tilde_suf))
    print('one中 数字~ 族(0-9~) = %d  %s' % (len(tilde_digit), tilde_digit))
    # 数字开头族
    for d in '0123456789':
        pre = [c for c in one if c.startswith(d)]
        print('  前缀 %s : %d' % (d, len(pre)))
    # 数字结尾族
    for d in '0123456789':
        suf = [c for c in one if c.endswith(d)]
        if suf:
            print('  后缀 %s : %d' % (d, len(suf)))

    # ---------- I. 新族探索 ----------
    print('\n=== I. 新族探索 ===')
    syms = set(nonalpha)
    # 双符号码：长度2且两位都是符号(非字母非数字)
    def is_sym(ch):
        return (not ch.isalpha()) and (not ch.isdigit())
    double_sym = sorted(c for c in one if len(c) == 2 and all(is_sym(x) for x in c))
    print('双符号码(两字符皆符号) = %d  %s' % (len(double_sym), double_sym))
    # 符号+符号长度2（含数字混合）宽口径
    n_alpha = lambda c: sum(1 for x in c if x.isalpha())
    nos_alpha2 = sorted(c for c in one if len(c) == 2 and n_alpha(c) == 0)
    print('长度2零字母码 = %d  %s' % (len(nos_alpha2), nos_alpha2))
    # 未用标点：schema speller.alphabet 里的符号
    speller_syms = set(",.?!<;:/='`~@*_")
    used_in_one = syms | set(ch for c in one for ch in c if ch in speller_syms)
    never = sorted(speller_syms - set(ch for c in one for ch in c))
    print('speller字母表中从未出现在one的符号 = %s' % never)
    # 双符号码的组合枚举（字母位固定大写/小写 A/a 时）
    print('\n[双符号候选举例] 在one里、符号在末位且前缀为大写字母的码：')
    big_sym = sorted(c for c in one if len(c) == 2
                     and c[0].isupper() and is_sym(c[1]))
    print('  大写字母+符号 = %d  %s' % (len(big_sym), big_sym))

    # ---------- J. 干净空槽样例（按族列前若干）----------
    print('\n=== J. 各族干净空槽样例（可直接新增一击上屏）===')
    by_fam_clean = collections.defaultdict(list)
    for c in detail['empty-词库无此码-clean']:
        by_fam_clean[fam_lump(family_of(c))].append(c)
    for g in sorted(by_fam_clean, key=lambda x: -len(by_fam_clean[x])):
        lst = sorted(by_fam_clean[g])
        print('  %-14s %4d  %s' % (g, len(lst), ' '.join(lst[:25])))


if __name__ == '__main__':
    main()
