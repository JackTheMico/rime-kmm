#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核实：符号族干净空槽的计数有没有重复元素（输出的列表里看到 < ! 连出两次）。"""
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
one = chord.one_press_codes()

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

pref_all = set()
for c in allcode_count:
    for i in range(1, len(c)):
        pref_all.add(c[:i])

print('one_press_codes 是 set?', isinstance(one, set), '总数', len(one))
for sym in ['<', ';', '!', '@', '?']:
    fam = [c for c in one if c.startswith(sym)]
    clean = [c for c in fam
             if c not in pref_all and c not in allcode_count]
    print('\n前缀 %s: fam=%d 去重后=%d clean(list)=%d 去重后=%d'
          % (sym, len(fam), len(set(fam)), len(clean), len(set(clean))))
    dup = [c for c, n in collections.Counter(clean).items() if n > 1]
    print('  重复的干净码:', dup[:20])
    if dup:
        print('  例: %r 出现 %d 次' % (dup[0], collections.Counter(clean)[dup[0]]))
