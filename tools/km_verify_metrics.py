#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 01：码长指标工具——聚合输出四数，作为所有验收断言的唯一入口。

口径（spec §验收脚本 / 票 04 验收协议）
------------------------------------------------
- 输入：一段文本 + 词库；输出：理论码长 / 实测码长 / 打词率 / 选重率。
- 严格计击：选重、空格确认、预测上屏均计入击数，账面码长不会虚低。
- 理论线与实测线独立判定：理论 ≤0.7、实测 ≤0.8 各自 pass/fail。
- 击数 = ⌈码元数/2⌉，以 km_chord_model 为唯一权威；可达性同源于它。

对外接口（seam，spec Testing Decisions 已约定）：
  analyze(text, entries, one) —— one 为可达码集合，注入以便测试；
  analyze_text(text, dict_path) —— 用真实词库 + 真实击数模型跑端到端。

用法
----
    python3 tools/km_verify_metrics.py --text "我们的研究" [--dict kongmingmas_exp.dict.yaml]
    python3 tools/km_verify_metrics.py --text-file path/to/sample.txt
"""
import argparse
import collections
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DICT = os.path.join(ROOT, "kongmingmas_exp.dict.yaml")
THEORY_TARGET = 0.7
MEASURED_TARGET = 0.8


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chord = _load("km_chord_model", os.path.join(ROOT, "tools", "km_chord_model.py"))


def load_entries(path):
    """读词库两列结构，返回 (word, code) 列表（跳过 YAML 头与空格构造词条）。"""
    out, started = [], False
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.rstrip("\n")
            if not started:
                if s == "...":
                    started = True
                continue
            if not s or s.startswith("#") or "\t" not in s:
                continue
            w, c = s.split("\t", 1)
            w = w.replace("\ufeff", "")
            c = c.replace("\ufeff", "")   # 码字段也可能带 BOM（如 泻/嚎/锭 的 !'）
            if " " in w:
                continue
            out.append((w, c))
    return out


def _build_index(entries):
    """词 → 该词所有可达码；码 → 候选词数；前缀集合。"""
    word_codes = collections.defaultdict(list)
    code_words = collections.defaultdict(list)
    for w, c in entries:
        word_codes[w].append(c)
        code_words[c].append(w)
    prefix = set()
    for c in code_words:
        for i in range(1, len(c)):
            prefix.add(c[:i])
    return word_codes, code_words, prefix


def _strokes_codes(word_codes, one):
    """预计算每个 (词, 码) 的击数；真死码（strokes>=99）记为 None。

    注意：多击码（如 Ykjo=2 击）不在 one_press_codes 集合里，但 chord.strokes
    能直接算它——不可因「不在一击集合」就当不可达，否则多击词被兜底成 1 击/字。
    """
    cost = {}
    for w, codes in word_codes.items():
        for c in codes:
            st = chord.strokes(c, one)
            if st >= 99:
                st = None
            cost[(w, c)] = st
    return cost


def _segment(text, word_codes):
    """最长匹配分词：返回 [(unit, is_word), ...]，未覆盖字符单列出来。"""
    max_len = max((len(w) for w in word_codes), default=1)
    units, i = [], 0
    n = len(text)
    while i < n:
        hit = None
        for L in range(min(max_len, n - i), 0, -1):
            w = text[i:i + L]
            if w in word_codes:
                hit = w
                break
        if hit:
            units.append((hit, len(hit) >= 2))
            i += len(hit)
        else:
            units.append((text[i], False))
            i += 1
    return units


def _unit_cost(unit, word_codes, code_words, cost, prefix):
    """返回 (最短击数, 是否需要空格确认, 是否需要选词)；无可打码返回 (None, False, False)。

    选重的判据是「同一个码挂了多个词」(len(code_words[best_code])>1)，
    不是「同一个词有多个码」——后者是同义码，打字时任选其一即可，不构成选词。
    """
    best_st = None
    best_code = None
    for c in word_codes.get(unit, []):
        st = cost.get((unit, c))
        if st is None:
            continue
        if best_st is None or st < best_st or (st == best_st and len(c) < len(best_code)):
            best_st, best_code = st, c
    if best_st is None:
        return None, False, False
    need_space = best_code in prefix
    need_select = len(code_words[best_code]) > 1
    return best_st, need_space, need_select


def analyze(text, entries, one):
    """核心聚合：输入文本/词条/可达码集合，输出四数 + 明细。"""
    word_codes, code_words, prefix = _build_index(entries)
    cost = _strokes_codes(word_codes, one)
    units = _segment(text, word_codes)

    theory_keys = 0
    measured_keys = 0
    word_chars = 0
    total_chars = len(text)
    confirm_units = 0
    sel_units = 0
    unmatched = 0

    for unit, is_word in units:
        st, need_space, need_select = _unit_cost(unit, word_codes, code_words, cost, prefix)
        if st is None:
            # 未覆盖/不可达字符：按每字 1 击兜底，绝不让它凭空消失
            unmatched += len(unit)
            theory_keys += len(unit)
            measured_keys += len(unit)
            continue
        theory_keys += st
        # 严格计击：空格确认与选词各自计一击，两个都命中就加两击
        extra = 0
        if need_space:
            extra += 1
            confirm_units += 1
        if need_select:
            extra += 1
            sel_units += 1
        measured_keys += st + extra
        if is_word:
            word_chars += len(unit)

    return {
        "theoretical": round(theory_keys / max(total_chars, 1), 4),
        "measured": round(measured_keys / max(total_chars, 1), 4),
        "word_rate": round(word_chars / max(total_chars, 1), 4),
        "selection_rate": round(sel_units / max(len(units), 1), 4),
        "theoretical_pass": theory_keys / max(total_chars, 1) <= THEORY_TARGET,
        "measured_pass": measured_keys / max(total_chars, 1) <= MEASURED_TARGET,
        "total_chars": total_chars,
        "unmatched_chars": unmatched,
        "theory_keys": theory_keys,
        "measured_keys": measured_keys,
        "units": len(units),
        "confirm_units": confirm_units,
    }


def analyze_text(text, dict_path=DEFAULT_DICT):
    """端到端：真实词库 + 真实击数模型。"""
    entries = load_entries(dict_path)
    one = chord.one_press_codes()
    return analyze(text, entries, one)


def _is_two_cjk(w):
    return len(w) == 2 and all("\u4e00" <= ch <= "\u9fff" for ch in w)


def _min_strokes(w, word_codes, stroke_of_code):
    """词的最短击数；无码返回 None。"""
    ss = [stroke_of_code(c) for c in word_codes.get(w, [])]
    ss = [s for s in ss if s is not None and s < 99]
    return min(ss) if ss else None


def coverage_stats(entries, freq, stroke_of_code, topn=None):
    """二字词一击覆盖率：词数口径 + 词频加权口径（票04验收）。

    topn 限制在词频降序的前 N 个二字高频词；None 表示全部二字词。
    stroke_of_code 注入（生产传 chord.strokes 偏函数），期望值可手算。
    """
    word_codes = collections.defaultdict(list)
    for w, c in entries:
        if " " not in w:
            word_codes[w].append(c)
    two = [(w, f) for w, f in freq.items() if _is_two_cjk(w)]
    two.sort(key=lambda x: (-x[1], x[0]))
    if topn is not None:
        two = two[:topn]
    total = len(two)
    mass_total = sum(f for w, f in two)
    onehit = 0
    mass_onehit = 0
    for w, f in two:
        st = _min_strokes(w, word_codes, stroke_of_code)
        if st == 1:
            onehit += 1
            mass_onehit += f
    return {
        "two_total": total,
        "two_onehit": onehit,
        "word_coverage": round(onehit / max(total, 1), 4),
        "mass_total": mass_total,
        "mass_onehit": mass_onehit,
        "mass_coverage": round(mass_onehit / max(mass_total, 1), 4),
    }


def weighted_theory_k(entries, freq, stroke_of_code, topn=None):
    """词频加权理论码长 K = Σ f·击数(w) / Σ f·字长(w)。

    覆盖整个词频表（或 topn 高频词）；词无码时按每字 1 击兜底，
    与 analyze 的未匹配兜底口径一致。
    """
    word_codes = collections.defaultdict(list)
    for w, c in entries:
        if " " not in w:
            word_codes[w].append(c)
    items = list(freq.items())
    if topn is not None:
        items.sort(key=lambda x: (-x[1], x[0]))
        items = items[:topn]
    num = den = 0
    for w, f in items:
        st = _min_strokes(w, word_codes, stroke_of_code)
        if st is None:
            st = len(w)   # 未覆盖：每字 1 击兜底
        num += f * st
        den += f * len(w)
    return round(num / max(den, 1), 4)


def k_target_gap(entries, freq, stroke_of_code, target=0.6, capacity=None):
    """冲 N 门槛差距量化（票05）：把非一击词贪心升级为一击，要追加多少个码。

    反事实模型（独立数据源，不依赖 chord 实现；stroke_of_code 注入以便手算）：
      每词当前击数 st = 该词各码最短击数；无码/死码按每字 1 击兜底（与 analyze 同口径）。
      分子 num = Σ f·st；分母 den = Σ f·len(w)；current_k = num/den。
      目标分子 = target·den → need_save = max(0, num - target·den)。
      把所有 st>1 的词按词频降序贪心升级到 1 击，每个省 f·(st-1) 击；
      累计省够 need_save 时所花的词数即 extra_codes_needed（一词一码）。

    capacity 给定则裁决 reachable = (need_save==0) 或 (extra_codes_needed<=capacity
    且贪心确实省够)。未覆盖词（freq 有、词库无码）必须计入候选——它们是最大的
    可提升空间，漏掉会系统性高估达标难度。

    返回 dict：current_k / target / need_save / strokes_saved / extra_codes_needed /
    onehit_mass_share / reachable / capacity。
    """
    word_codes = collections.defaultdict(list)
    for w, c in entries:
        if " " not in w:
            word_codes[w].append(c)

    # 每词只算一次最短击数；None（未覆盖/死码）按每字 1 击兜底，与 analyze 同口径。
    # 三处用途（分子 / 一击质量 / 非一击候选）共用这份结果，避免重复计算与口径漂移。
    items = []
    num = den = 0
    onehit_mass = 0
    for w, f in freq.items():
        raw = _min_strokes(w, word_codes, stroke_of_code)
        st = raw if raw is not None else len(w)
        items.append((w, f, st))
        num += f * st
        den += f * len(w)
        if raw == 1:
            onehit_mass += f
    current_k = round(num / max(den, 1), 4)
    mass_total = sum(f for _, f, _ in items)
    need_save = max(0.0, num - target * den)

    # 非一击词（含未覆盖）按词频降序：升级到 1 击可省 f*(st-1)
    nonone = [(f, w, st) for w, f, st in items if st > 1]
    nonone.sort(key=lambda x: (-x[0], x[1]))

    saved = 0.0
    extra = 0
    for f, _w, st in nonone:
        if saved >= need_save:
            break
        saved += f * (st - 1)
        extra += 1

    reached = saved >= need_save
    if capacity is None:
        reachable = None
    else:
        reachable = bool(need_save == 0 or (reached and extra <= capacity))

    return {
        "current_k": current_k,
        "target": target,
        "num": num,
        "den": den,
        "need_save": round(need_save, 4),
        "strokes_saved": round(saved, 4),
        "extra_codes_needed": extra,
        "onehit_mass_share": round(onehit_mass / max(mass_total, 1), 4),
        "greedy_reached": bool(reached),
        "reachable": reachable,
        "capacity": capacity,
    }


def main():
    ap = argparse.ArgumentParser(description="码长四数验收工具（严格计击）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="直接给出待统计文本")
    src.add_argument("--text-file", help="待统计文本文件（UTF-8）")
    ap.add_argument("--dict", default=DEFAULT_DICT, help="词库路径（默认新实验方案）")
    args = ap.parse_args()
    text = args.text if args.text is not None else open(args.text_file, encoding="utf-8").read()
    text = text.strip()
    m = analyze_text(text, args.dict)
    print(json.dumps(m, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
