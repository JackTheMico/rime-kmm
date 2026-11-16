#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 01 补充分析：族分类修正（拆解带空格码）+ 1396/1377 差异 + 新族空槽。只读。"""
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


def fam2(code):
    """修正族分类：先剥离尾随空格（空格同击标记），再判形态。"""
    has_sp = code.endswith(' ')
    base = code.rstrip(' ')
    if '=' in code:
        return '空格并击'
    if not base:                      # 单个空格码 rstrip 后为空串
        return '纯空格'
    if base.isalpha():
        return '纯字母' + ('·带空格' if has_sp else '')
    # 判定前缀/后缀符号（用 base）
    if not base[0].isalpha():
        m = base[0]
        tag = '数字前缀' + m if m.isdigit() else '符号前缀' + m
        return tag + ('·带空格' if has_sp else '')
    if len(base) > 1 and not base[1].isalpha():
        m = base[1]
        tag = '数字后缀' + m if m.isdigit() else '符号后缀' + m
        return tag + ('·带空格' if has_sp else '')
    return '其他' + ('·带空格' if has_sp else '')


def lump(f):
    return f.replace('·带空格', '')


def main():
    one = chord.one_press_codes()

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

    codes_indep = collections.defaultdict(list)
    allcode_count = collections.Counter()
    code_first = {}
    for w, c in entries:
        allcode_count[c] += 1
        code_first.setdefault(c, w)
        if ' ' in w:
            continue
        codes_indep[c].append(w)

    pref_all = set()
    for c in allcode_count:
        for i in range(1, len(c)):
            pref_all.add(c[:i])

    # ---- 1) 1396 vs 1377 差异码 ----
    auto1396 = {c for c in codes_indep
                if len(c) <= 3 and c not in pref_all and len(codes_indep[c]) == 1}
    auto1377 = {c for c in auto1396 if c in one}
    diff = sorted(auto1396 - auto1377)
    print('=== 1) ≤3码元零延伸唯一(%d) 与 one可达(%d) 差异 = %d ==='
          % (len(auto1396), len(auto1377), len(diff)))
    for c in diff:
        print('   %-6r -> %s' % (c, codes_indep[c][0]))

    # ---- 2) 修正族表 ----
    print('\n=== 2) 修正族表（带空格码已归位）===')
    fam_one = collections.Counter()
    fam_auto = collections.Counter()
    fam_empty = collections.Counter()
    fam_zero = collections.Counter()
    fam_ext = collections.Counter()
    for c in one:
        fam_one[fam2(c)] += 1
        if c in pref_all:
            fam_ext[fam2(c)] += 1
        elif c in allcode_count and len(codes_indep.get(c, [])) == 1:
            fam_auto[fam2(c)] += 1
        elif c in allcode_count:
            fam_zero[fam2(c)] += 1
        else:
            fam_empty[fam2(c)] += 1

    print('%-18s %7s %7s %7s %7s %7s' % ('族', 'one', 'auto', '空槽', 'zero', 'ext'))
    for f in sorted(fam_one, key=lambda x: -fam_one[x]):
        print('%-18s %7d %7d %7d %7d %7d'
              % (f, fam_one[f], fam_auto[f], fam_empty[f],
                 fam_zero[f], fam_ext[f]))
    print('%-18s %7d %7d %7d %7d %7d' % (
        '合计', sum(fam_one.values()), sum(fam_auto.values()),
        sum(fam_empty.values()), sum(fam_zero.values()), sum(fam_ext.values())))

    # ---- 3) 粗族汇总（票面口径）----
    print('\n=== 3) 粗族汇总（票面口径）===')
    g_one, g_auto, g_empty, g_zero, g_ext = (collections.Counter() for _ in range(5))
    for c in one:
        g = lump(fam2(c))
        g_one[g] += 1
        if c in pref_all:
            g_ext[g] += 1
        elif c in allcode_count and len(codes_indep.get(c, [])) == 1:
            g_auto[g] += 1
        elif c in allcode_count:
            g_zero[g] += 1
        else:
            g_empty[g] += 1
    print('%-12s %7s %7s %7s %7s %7s' % ('族', 'one', 'auto', '空槽', 'zero', 'ext'))
    for g in sorted(g_one, key=lambda x: -g_one[x]):
        print('%-12s %7d %7d %7d %7d %7d'
              % (g, g_one[g], g_auto[g], g_empty[g], g_zero[g], g_ext[g]))

    # ---- 4) 新族：双符号/符号形态的干净空槽 ----
    print('\n=== 4) 新族候选：one里符号形态码的「干净空槽」统计 ===')
    def is_sym(ch):
        return not ch.isalpha() and not ch.isdigit()

    groups = {
        '双符号码(2字符皆符号)': [c for c in one if len(c) == 2 and all(is_sym(x) for x in c)],
        '符号前缀+大写字母': [c for c in one if len(c) == 2 and is_sym(c[0]) and c[1].isupper()],
        '符号前缀+小写字母': [c for c in one if len(c) == 2 and is_sym(c[0]) and c[1].islower()],
        '大写字母+符号(后缀)': [c for c in one if len(c) == 2 and c[0].isupper() and is_sym(c[1])],
        '小写字母+符号(后缀)': [c for c in one if len(c) == 2 and c[0].islower() and is_sym(c[1])],
        '数字0/7/8/9+符号': [c for c in one if len(c) == 2 and c[0] in '0789' and is_sym(c[1])],
    }
    for name, sel in groups.items():
        sel = set(sel)
        occ = sum(1 for c in sel if c in allcode_count)
        auto = sum(1 for c in sel if c in allcode_count
                   and len(codes_indep.get(c, [])) == 1 and c not in pref_all)
        clean = sum(1 for c in sel if c not in allcode_count and c not in pref_all)
        print('%-22s one=%4d 已占=%4d auto=%3d 干净空槽=%4d'
              % (name, len(sel), occ, auto, clean))

    # ---- 5) 数字大写族 1~-9~ 状态 ----
    print('\n=== 5) 数字大写族 N~ 在one/词库的状态 ===')
    for d in '0123456789':
        c = d + '~'
        in_one = c in one
        in_dict = c in allcode_count
        words = codes_indep.get(c, [])
        print('  %-3r one=%-5s 词库=%-5s 候选=%s'
              % (c, in_one, in_dict, words[:3]))

    # ---- 6) 纯字母族饱和分析 ----
    print('\n=== 6) 纯字母族饱和 ===')
    pure = [c for c in one if fam2(c) == '纯字母']
    print('纯字母one码面 = %d，其中 auto=%d, 空槽=%d, zero=%d, ext=%d'
          % (len(pure),
             sum(1 for c in pure if c in allcode_count
                 and len(codes_indep.get(c, [])) == 1 and c not in pref_all),
             sum(1 for c in pure if c not in allcode_count),
             sum(1 for c in pure if c in allcode_count
                 and len(codes_indep.get(c, [])) != 1 and c not in pref_all),
             sum(1 for c in pure if c in pref_all)))
    # ext 里纯字母有多少是「被更长的纯字母码延伸」vs「被其它族延伸」
    pure_ext = [c for c in pure if c in pref_all]
    ext_by_pure = 0
    for c in pure_ext:
        if any(c != d and d.startswith(c) and fam2(d) == '纯字母'
               for d in allcode_count):
            ext_by_pure += 1
    print('纯字母ext=%d，其中被更长的纯字母码延伸=%d（其余被带符号/空格码延伸）'
          % (len(pure_ext), ext_by_pure))


if __name__ == '__main__':
    main()
