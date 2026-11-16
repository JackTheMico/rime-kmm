#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票04 TDD：覆盖率与加权理论码长工具的测试。

seam = km_verify_metrics 聚合入口（spec Testing Decisions 已约定）。
stroke_of_code 注入，期望值全部手算，独立于 chord 模型实现。
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from km_verify_metrics import coverage_stats, weighted_theory_k, k_target_gap  # noqa: E402

# 受控小词库：我们(1击) / 研究(2击) / 体验(2击) / 的(1击) / 了(2击)
ENTRIES = [("我们", "AA"), ("研究", "BB"), ("体验", "EEEE"),
           ("的", "C="), ("了", "D=")]
FREQ = {"我们": 100, "研究": 50, "体验": 20, "的": 200, "了": 30}
STROKE = lambda c: {"AA": 1, "BB": 2, "EEEE": 2, "C=": 1, "D=": 2}.get(c, 99)


def test_coverage_word_count():
    # 二字词：我们/研究/体验 共3个；仅我们一击 → 1/3
    m = coverage_stats(ENTRIES, FREQ, STROKE)
    assert m["two_total"] == 3, m
    assert m["two_onehit"] == 1, m
    assert m["word_coverage"] == round(1 / 3, 4), m


def test_coverage_mass_weighted():
    # 二字词词频和 = 100+50+20=170；一击(我们)=100 → 100/170
    m = coverage_stats(ENTRIES, FREQ, STROKE)
    assert m["mass_total"] == 170, m
    assert m["mass_onehit"] == 100, m
    assert m["mass_coverage"] == round(100 / 170, 4), m


def test_coverage_excludes_single_char():
    # 单字 的/了 不计入二字词覆盖率（它们只在加权K里出现）
    m = coverage_stats(ENTRIES, FREQ, STROKE)
    assert m["two_total"] == 3, m


def test_coverage_topn_limits_high_freq_words():
    # 取前2高频二字词：我们(100)/研究(50)；一击1个 → 1/2；词频 100/150
    m = coverage_stats(ENTRIES, FREQ, STROKE, topn=2)
    assert m["two_total"] == 2, m
    assert m["word_coverage"] == round(1 / 2, 4), m
    assert m["mass_coverage"] == round(100 / 150, 4), m


def test_weighted_k_hand_computed():
    # 分子 = 100*1+50*2+200*1+30*2+20*2 = 500
    # 分母 = 100*2+50*2+200*1+30*1+20*2 = 570
    # K = 500/570
    k = weighted_theory_k(ENTRIES, FREQ, STROKE)
    assert k == round(500 / 570, 4), k


def test_weighted_k_unknown_word_falls_back_per_char():
    # freq 里有 "未知词"(freq=10,3字) 但词库无码 → 按每字1击兜底 = 3击
    # 新分子 = 500 + 10*3 = 530；新分母 = 570 + 10*3 = 600
    f2 = dict(FREQ, 未知词=10)
    k = weighted_theory_k(ENTRIES, f2, STROKE)
    assert k == round(530 / 600, 4), k


def test_weighted_k_topn():
    # 前2高频词：的(200,1击,1字)/我们(100,1击,2字)
    # 分子 = 200*1+100*1 = 300；分母 = 200*1+100*2 = 400 → 0.75
    k = weighted_theory_k(ENTRIES, FREQ, STROKE, topn=2)
    assert k == round(300 / 400, 4), k


# ---- 票05：冲 0.6 门槛差距量化 --------------------------------------------
# 受控词库：我(1击,1字) / 你们(2击,2字) / 大家好(3击,3字)
#           谢谢(无码,2字) / 明天(无码,2字)
GAP_ENTRIES = [("我", "a"), ("你们", "bb"), ("大家好", "ccc")]
GAP_FREQ = {"我": 100, "你们": 50, "大家好": 10, "谢谢": 60, "明天": 5}
GAP_STROKE = lambda c: {"a": 1, "bb": 2, "ccc": 3}.get(c, 99)
# 分母(总字次) = 100*1 + 50*2 + 10*3 + 60*2 + 5*2 = 360
# 当前分子 = 100*1 + 50*2 + 10*3 + 60*2(未覆盖每字1击) + 5*2 = 360 → current_k = 1.0
# target=0.7 → 目标分子 = 0.7*360 = 252 → 需省 360-252 = 108 击
# 非一击词按词频降序贪心：谢谢(60,省60) → 你们(50,省50) 累计110>=108 → 需2个码
#   若漏掉未覆盖词：你们50+大家好20+明天5=75<108 → 需3个码且不可达（用于变异测试）
# 一击词频质量占比 = 100/225 = 0.4444


def test_k_target_gap_current_k():
    m = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=0.7)
    assert m["current_k"] == 1.0, m


def test_k_target_gap_extra_codes_greedy():
    # 未覆盖词「谢谢」必须算进候选（漏掉它只会得到 你们50+大家好20=70<87，需3个码）
    m = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=0.7)
    assert m["extra_codes_needed"] == 2, m
    assert m["strokes_saved"] == 110, m
    assert m["need_save"] == 108, m


def test_k_target_gap_onehit_mass_share():
    m = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=0.7)
    assert m["onehit_mass_share"] == round(100 / 225, 4), m


def test_k_target_gap_capacity_verdict():
    # 需2个码：容量2→可达，容量1→不可达
    ok = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=0.7, capacity=2)
    no = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=0.7, capacity=1)
    assert ok["reachable"] is True, ok
    assert no["reachable"] is False, no


def test_k_target_gap_already_at_target():
    # 目标 1.0：无需追加，可达（即使容量 0）
    m = k_target_gap(GAP_ENTRIES, GAP_FREQ, GAP_STROKE, target=1.0, capacity=0)
    assert m["need_save"] == 0, m
    assert m["extra_codes_needed"] == 0, m
    assert m["reachable"] is True, m


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", fn.__name__, repr(e))
    print("all %d tests passed" % len(fns) if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
