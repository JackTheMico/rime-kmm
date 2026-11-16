#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读验证：用户点名的 < ; ! @ ? 五个符号前缀族到底是不是空码。

对这五个符号打头的每一个「一次并击可达码」，列出：
  1) 可达性（在不在 one_press_codes，即能否一击打出）
  2) 词库是否占用（该码当性格有没有词条）
  3) 是不是别的词库码的前缀（若是的，直接当一击上屏会截断长词）
  4) 词库里该码实际挂了什么词（含空格构造层）

口径与 one_strike_capacity_analysis.py 完全一致；不改任何现有文件。
"""
import collections
import importlib.util
import os

ROOT = '/home/jackwy/Nextcloud/kmrime'
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
TARGETS = ['<', ';', '!', '@', '?']


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chord = _load('km_chord_model', os.path.join(ROOT, 'tools/km_chord_model.py'))
one = chord.one_press_codes()

# 读词库：独立词条（不含空格）与全部数据行分开记
codes_indep = collections.defaultdict(list)
allcode_count = collections.Counter()
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
        w = w.replace('\ufeff', '')
        allcode_count[c] += 1
        if ' ' not in w:
            codes_indep[c].append(w)

# 严格前缀集：含空格词条的码也占位
pref_all = set()
for c in allcode_count:
    for i in range(1, len(c)):
        pref_all.add(c[:i])

print('一次并击可达码总数 = %d' % len(one))
print('=' * 78)

for sym in TARGETS:
    fam = sorted(c for c in one if c.startswith(sym))
    clean, dirty, zero, ext, auto = [], [], [], [], []
    for c in fam:
        is_pref = c in pref_all
        n = len(codes_indep.get(c, []))
        in_dict = c in allcode_count
        if is_pref:
            ext.append((c, n, codes_indep.get(c, [])[:5]))
        elif in_dict and n == 1:
            auto.append((c, codes_indep[c][0]))
        elif in_dict and n >= 2:
            zero.append((c, codes_indep[c][:5]))
        elif in_dict and n == 0:
            zero.append((c, ['<仅空格构造>']))
        else:
            clean.append(c)

    print('\n【前缀 %s】one 可达 %d 个：干净空槽 %d / 已上屏 %d / 多候选 %d / 会被当长码前缀 %d'
          % (sym, len(fam), len(clean), len(auto), len(zero), len(ext)))
    if auto:
        print('  -- 已经是一击上屏（占用中）%d 个，前 10：' % len(auto))
        for c, w in auto[:10]:
            print('     %-5s -> %s' % (c, w))
    if zero:
        print('  -- 零延伸但多候选/仅空格构造 %d 个，前 10：' % len(zero))
        for c, ws in zero[:10]:
            print('     %-5s -> %s' % (c, '/'.join(ws)))
    if ext:
        print('  -- 是更长码的前缀（用它会截断长词）%d 个，前 10：' % len(ext))
        for c, n, ws in ext[:10]:
            print('     %-5s 占位%d  例词 %s' % (c, n, '/'.join(str(x) for x in ws)))
    print('  -- 干净空槽（可达+词库无此码+非任何码前缀），全部：')
    for i in range(0, len(clean), 12):
        print('     ' + '  '.join('%-4s' % x for x in clean[i:i + 12]))

# 具体复核用户直觉：随便点几个码，看它们按什么键打出
print('\n' + '=' * 78)
print('附：这几个符号码是怎么按出来的（验证「可达」不是纸上谈兵）')
probe = []
for sym in TARGETS:
    for c in sorted(x for x in one if x.startswith(sym))[:3]:
        probe.append(c)
for c in probe:
    keys = None
    for lk in chord.realizations():
        pass
    # 反查：穷举左右手组合，找哪个按键组合产出该码
    real = chord.realizations()
    lefts, rights = [frozenset()], [frozenset()]
    for s, h in real.items():
        lefts.extend(h['L'])
        rights.extend(h['R'])
    lefts.extend(frozenset({k}) for k in chord.LEFT_KEYS)
    rights.extend(frozenset({k}) for k in chord.RIGHT_KEYS if k not in chord.UNXLIT)
    found = None
    for sp in (frozenset(), frozenset({' '})):
        for lk in lefts:
            for rk in rights:
                if chord.press(lk | rk | sp) == c:
                    found = ' '.join(sorted(lk | rk | sp))
                    break
            if found:
                break
        if found:
            break
    print('  码 %-5s  <- 同时按 %s' % (c, found or '未找到'))
