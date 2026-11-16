#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 02 — 高频词一击覆盖率缺口分析（只读，不改词库/现有文件）。

来源与口径
----------
- 词频：/usr/share/rime-data/essay.txt（经 opencc t2s.json 转简，缓存于
  .workbuddy/tmp/essay_s.txt），经 tools/km_jianma_opt.py:load_freq() 加载。
- 词库：kongmingmas.dict.yaml，逐行流式读取（不整库载入）。
- 击数：tools/km_chord_model.py 的 strokes(code, one_press_codes())；
  strokes==1 即「一词一击」（权威口径，禁止肉眼数码元）。

用法：
  /home/jackwy/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
      .scratch/km-code-length-0.6/research/word_coverage_analysis.py
"""
import collections
import functools
import importlib.util
import os

ROOT = '/home/jackwy/Nextcloud/kmrime'
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kmopt = _load('kmopt', os.path.join(ROOT, 'tools/km_jianma_opt.py'))
chord = _load('km_chord_model', os.path.join(ROOT, 'tools/km_chord_model.py'))


def is_cjk(ch):
    return '\u4e00' <= ch <= '\u9fff'


def is_cjk_all(s):
    return bool(s) and all(is_cjk(c) for c in s)


def pct(a, b):
    return 100.0 * a / max(b, 1)


def main():
    one = chord.one_press_codes()
    print('[chord] 一次并击可达码 = %d' % len(one))

    @functools.lru_cache(maxsize=None)
    def nstroke(code):
        return chord.strokes(code, one)

    # ---------- 词频 ----------
    freq = kmopt.load_freq()
    print('[freq] essay 词频表词条数 = %d' % len(freq))
    cjk_items = [(w, f) for w, f in freq.items() if is_cjk_all(w)]
    cjk_items.sort(key=lambda x: (-x[1], x[0]))
    n1 = sum(1 for w, _ in cjk_items if len(w) == 1)
    n2 = sum(1 for w, _ in cjk_items if len(w) == 2)
    n3 = sum(1 for w, _ in cjk_items if len(w) > 2)
    print('[freq] 纯CJK词条 = %d （单字 %d / 二字 %d / 多字 %d）'
          % (len(cjk_items), n1, n2, n3))
    # 被过滤掉的非纯CJK（标点/英文/含"〇"等）候选，看词频占比
    all_sum = sum(f for _, f in freq.items())
    cjk_sum = sum(f for _, f in cjk_items)
    print('[freq] 纯CJK词频占全表 = %.2f%% （排除的非CJK含标点/数字/〇等）'
          % pct(cjk_sum, all_sum))

    max_rank = 20000
    need = {w for w, _ in cjk_items[:max_rank]}

    # ---------- 流式读词库 ----------
    word_codes = collections.defaultdict(list)
    code_count = collections.Counter()
    code_first = {}
    total = 0
    with open(DICT_S, encoding='utf-8') as fh:
        for line in fh:
            raw = line.rstrip('\n')
            if '\t' not in raw:
                continue
            w, c = raw.split('\t', 1)
            w = w.replace('\ufeff', '')
            total += 1
            if w in need:
                word_codes[w].append(c)
            code_count[c] += 1
            if c not in code_first:
                code_first[c] = w
    print('[dict] 数据行 = %d, 不同码 = %d' % (total, len(code_count)))

    prefix = set()
    for c in code_count:
        for i in range(1, len(c)):
            prefix.add(c[:i])

    def best_strokes(w):
        cs = word_codes.get(w, [])
        return min((nstroke(c) for c in cs), default=99)

    def onehit(w):
        return best_strokes(w) == 1

    def le2(w):
        return any(len(c) <= 2 for c in word_codes.get(w, []))

    # ---------- 覆盖率表 ----------
    print('\n[coverage] rank | 总词 | 一击 | %% | 二字词 | 二字一击 | %% | '
          '二字<=2码元 | %% | 单字 | 单字一击 | %% | 多字 | 多字一击 | %%')
    cov = {}
    for k in (1000, 5000, 20000):
        top = cjk_items[:k]
        hit = sum(1 for w, _ in top if onehit(w))
        two = [(w, f) for w, f in top if len(w) == 2]
        two_hit = sum(1 for w, _ in two if onehit(w))
        two_le2 = sum(1 for w, _ in two if le2(w))
        one_c = [(w, f) for w, f in top if len(w) == 1]
        one_hit = sum(1 for w, _ in one_c if onehit(w))
        multi = [(w, f) for w, f in top if len(w) > 2]
        multi_hit = sum(1 for w, _ in multi if onehit(w))
        print('[coverage] %d | %d | %d | %.1f | %d | %d | %.1f | %d | %.1f | '
              '%d | %d | %.1f | %d | %d | %.1f'
              % (k, len(top), hit, pct(hit, len(top)),
                 len(two), two_hit, pct(two_hit, len(two)),
                 two_le2, pct(two_le2, len(two)),
                 len(one_c), one_hit, pct(one_hit, len(one_c)),
                 len(multi), multi_hit, pct(multi_hit, len(multi))))
        cov[k] = (pct(hit, len(top)), pct(two_hit, len(two)),
                  pct(two_le2, len(two)))

    # 二字词平均码元数 + 词频质量（一击覆盖的词频占比）
    print('\n[mass] rank | 二字词一击覆盖词频质量%% | 二字词平均最短码元数')
    for k in (1000, 5000, 20000):
        two = [(w, f) for w, f in cjk_items[:k] if len(w) == 2]
        tot_f = sum(f for _, f in two)
        hit_f = sum(f for w, f in two if onehit(w))
        avg_m = sum(min((len(c) for c in word_codes.get(w, [])), default=0)
                    for w, _ in two) / max(len(two), 1)
        print('[mass] %d | %.1f | %.3f' % (k, pct(hit_f, tot_f), avg_m))

    # ---------- 槽位盘点（chord 口径，零延伸且唯一候选） ----------
    one_auto = [c for c in code_count
                if c in one and c not in prefix and code_count[c] == 1]
    char_slots = [c for c in one_auto
                  if len(code_first[c]) == 1 and is_cjk(code_first[c])]
    word_slots = [c for c in one_auto if len(code_first[c]) > 1]
    other_slots = [c for c in one_auto
                   if len(code_first[c]) == 1 and not is_cjk(code_first[c])]
    print('\n[slots] 一击上屏码(chord口径) = %d; 单字 %d / 词 %d / 其他 %d'
          % (len(one_auto), len(char_slots), len(word_slots), len(other_slots)))

    # 前1500常用字一击上屏（对齐 char_onehit_report）
    char_rank = [(w, f) for w, f in freq.items()
                 if len(w) == 1 and is_cjk(w)]
    char_rank.sort(key=lambda x: -x[1])
    top1500 = [w for w, _ in char_rank[:1500]]
    onehit_chars = {code_first[c] for c in char_slots}
    hit1500 = sum(1 for w in top1500 if w in onehit_chars)
    print('[slots] 前1500字中一击上屏 = %d (%.1f%%)，榜单外单字槽 = %d'
          % (hit1500, pct(hit1500, 1500), len(char_slots) - hit1500))

    # 零和冲突面：每100槽转给词
    S_char = len(char_slots)
    print('\n[zero-sum] 单字一击槽 S_char=%d' % S_char)
    # 策略A 均匀损失
    h_uniform = hit1500 * (1.0 - 100.0 / S_char)
    print('[zero-sum] A均匀: 前1500一击 %d -> %.0f，覆盖率 %.1f%% -> %.1f%%，掉 %.1f pp'
          % (hit1500, h_uniform, pct(hit1500, 1500), pct(h_uniform, 1500),
             pct(hit1500 - h_uniform, 1500)))
    # 策略B 优先转榜单外低频槽
    outside = S_char - hit1500
    hurt = max(0, 100 - outside)
    h_lowfirst = hit1500 - hurt
    print('[zero-sum] B优先低频: 榜单外槽%d个先转，伤及榜单内%d字，'
          '覆盖率 %.1f%% -> %.1f%%，掉 %.1f pp'
          % (outside, hurt, pct(hit1500, 1500), pct(h_lowfirst, 1500),
             pct(hurt, 1500)))
    # 策略C 最坏：全从榜单内转
    h_worst = max(0, hit1500 - 100)
    print('[zero-sum] C最坏(全榜单内): 覆盖率 %.1f%% -> %.1f%%，掉 %.1f pp'
          % (pct(hit1500, 1500), pct(h_worst, 1500), pct(hit1500 - h_worst, 1500)))
    print('[zero-sum] 每100槽占单字一击地盘 = %.1f%%'
          % pct(100, S_char))

    # ---------- 缺口推导 ----------
    c1 = 1.269
    print('\n[gap] 模型 K=(1-p)*c1 + p*cw/L, c1=%.3f, L=2, cw=2-q' % c1)
    for K, pg in ((0.7, 0.74), (0.6, 0.87)):
        # K = (1-pg)*c1 + pg*(2-q)/2  =>  q = 2 - 2*(K-(1-pg)*c1)/pg
        q = 2.0 - 2.0 * (K - (1 - pg) * c1) / pg
        print('[gap] 锁定p=%.2f 要K=%.1f -> 需覆盖率 q=%.4f (%.2f%%)'
              % (pg, K, q, 100 * q))
    print('[gap] 覆盖率 q | 要K=0.7所需p | 要K=0.6所需p （p>1 即无解）')
    for q in (1.0, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5):
        denom = c1 - (2 - q) / 2.0
        p7 = (c1 - 0.7) / denom
        p6 = (c1 - 0.6) / denom
        print('[gap] %.2f | %s | %s'
              % (q, ('%.3f' % p7) if p7 <= 1 else '无解(%.3f)' % p7,
                 ('%.3f' % p6) if p6 <= 1 else '无解(%.3f)' % p6))
    # 当前二字词覆盖率代入（top1000 用 chord 口径）
    cur = cov[1000][1] / 100.0
    denom = c1 - (2 - cur) / 2.0
    print('[gap] 当前二字词覆盖率(top1000)=%.1f%% -> K=0.7需p=%.3f, K=0.6需p=%.3f'
          % (100 * cur, (c1 - 0.7) / denom, (c1 - 0.6) / denom))

    # 框架B：打词率受覆盖率约束 p=q，解析解 0.5q^2+(c1-1)q+(K-c1)=0
    import math
    print('\n[gap-B] 若打词率受覆盖率约束 p=q: K=(1-q)*c1+q*(2-q)/2')
    for K in (0.7, 0.6):
        a, b, cc = 0.5, c1 - 1.0, K - c1
        q = (-b + math.sqrt(b * b - 4 * a * cc)) / (2 * a)
        print('[gap-B] K=%.1f 临界覆盖率 q=%.4f (%.1f%%)' % (K, q, 100 * q))
    for q in (0.5, 0.7, 0.8, 0.8312, 0.9, 0.9186, 1.0):
        K = (1 - q) * c1 + q * (2 - q) / 2.0
        print('[gap-B] q=%.4f -> K=%.3f' % (q, K))

    # 覆盖率代入框架A（词数口径 q_word 与 词频加权 q_token 并列）
    def p_needed(q):
        d = c1 - (2 - q) / 2.0
        return (c1 - 0.7) / d, (c1 - 0.6) / d

    print('\n[gap-A] 二字词覆盖率 -> 框架A所需打词率（词数 / 词频加权）')
    for k in (1000, 5000, 20000):
        two = [(w, f) for w, f in cjk_items[:k] if len(w) == 2]
        tot_f = sum(f for _, f in two)
        q_word = sum(1 for w, _ in two if onehit(w)) / max(len(two), 1)
        q_tok = sum(f for w, f in two if onehit(w)) / max(tot_f, 1)
        for label, q in (('词数', q_word), ('词频', q_tok)):
            p7, p6 = p_needed(q)
            print('[gap-A] top%d %s覆盖=%.1f%% -> K=0.7需p=%.3f, K=0.6需p=%.3f'
                  % (k, label, 100 * q, p7, p6))


if __name__ == '__main__':
    main()
