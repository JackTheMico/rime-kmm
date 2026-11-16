#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 01 验收尺子的测试。只测公开接口，期望值手算、独立于被测实现。

seam（spec 已约定）：
  - analyze(text, entries, one)：one 为可达码集合，测试时注入受控集合，
    使期望值可手算；生产时由 analyze_text 注入真实 km_chord_model。
  - analyze_text(text, dict_path)：用真实词库 + 真实击数模型跑端到端。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from km_verify_metrics import analyze, analyze_text, chord, load_entries  # noqa: E402

REAL_ONE = chord.one_press_codes()


def test_load_entries_strips_bom_from_code_field():
    # 词库里 泻 的码带 BOM (\ufeff!')，不清洗会被当死码兜底，污染尺子口径
    import tempfile
    tmpdir = "/home/jackwy/Nextcloud/kmrime/.workbuddy/tmp"
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=tmpdir, suffix=".yaml",
                                     delete=False, encoding="utf-8") as f:
        f.write("---\nname: t\n...\n泻\t\ufeff!'\n")
        path = f.name
    try:
        assert ("泻", "!'") in load_entries(path), load_entries(path)
    finally:
        os.unlink(path)


def _run(text, entries, one=None):
    return analyze(text, entries, REAL_ONE if one is None else one)


def test_one_strike_words_need_no_extra_key():
    # 两个词都是一击、零延伸、唯一候选 → 每词 1 击
    entries = [("我", "a="), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["theoretical"] == round(2 / 3, 4), m
    assert m["measured"] == round(2 / 3, 4), m


def test_extended_code_counts_space_confirmation():
    # "我" 的码 a= 是 "我啊"=a=Z 的前缀 → 打 "我" 需额外空格确认
    # 理论只算最短击数(1+1)/3，实测把空格算进去 (2+1)/3
    entries = [("我", "a="), ("我啊", "a=Z"), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["theoretical"] == round(2 / 3, 4), m
    assert m["measured"] == 1.0, m


def test_multi_candidate_counts_selection():
    # 选重 = 同一个码挂多个词（打 a= 要在「我/窝」间选），不是一词多码。
    # a= 挂「我」「窝」两词 → 打「我」需选词，extra 一击。
    entries = [("我", "a="), ("窝", "a="), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["measured"] == 1.0, m
    assert m["selection_rate"] == round(1 / 2, 4), m


def test_one_word_two_codes_is_not_selection():
    # 反向保护：一个词有多个可用码（同义码）不算选重——打的时候任选其一即可。
    entries = [("我", "a="), ("我", "x="), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["selection_rate"] == 0.0, m
    assert m["measured"] == round(2 / 3, 4), m


def test_space_and_selection_count_separately():
    # 严格计击：一个码既是长码前缀（要空格）又挂多词（要选词）时，两击都要算。
    # a= 挂「我」「窝」，且是 a=Z 的前缀 → 打「我」= 1击 + 空格1 + 选词1 = 3
    entries = [("我", "a="), ("窝", "a="), ("我啊", "a=Z"), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["measured"] == round(4 / 3, 4), m  # (3 + 1) / 3


def test_word_rate_counts_characters_not_units():
    # "我们"(2字) + "研究"(2字) + "生"(1字)：词打出 4 字 / 共 5 字
    entries = [("我们", "AA"), ("研究", "BB"), ("生", "G=")]
    m = _run("我们研究生", entries)
    assert m["word_rate"] == round(4 / 5, 4), m


def test_theoretical_and_measured_are_independent_lines():
    # 理论达标(<=0.7)不代表实测达标(<=0.8)：延伸码把实测顶到 1.0
    entries = [("我", "a="), ("我啊", "a=Z"), ("研究", "BB")]
    m = _run("我研究", entries)
    assert m["theoretical_pass"] is True, m
    assert m["measured_pass"] is False, m


def test_strict_counting_includes_predicted_symbol():
    # 严格计击：文本里出现词库覆盖外的字符（预测/全码），仍计入击数，
    # 不能让它凭空消失造成账面码长虚假下降。
    entries = [("我", "a="), ("研究", "BB")]
    m = _run("我研究@", entries)
    assert m["unmatched_chars"] == 1, m
    assert m["total_chars"] == 4, m
    # 未匹配字按每字 1 击兜底：(1+1+1)/4
    assert m["measured"] == round(3 / 4, 4), m


def test_multi_stroke_code_counts_real_strokes_not_fallback():
    # 词的码若不在「一击可达集合」里但确是多击码，应按真实击数(2)计，
    # 不能当未匹配兜底成 1 击/字。one 只含一击码，strokes 仍要算多击码。
    # "研究"=Ykjo(2击)，"我"=a=(1击)：文本"我研究"理论=(1+2)/3
    entries = [("我", "a="), ("研究", "Ykjo")]
    m = _run("我研究", entries)
    assert m["unmatched_chars"] == 0, m
    assert m["theoretical"] == 1.0, m  # (1+2)/3


def test_analyze_text_uses_real_chord_model_and_is_reproducible():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dict_path = os.path.join(root, "kongmingmas_exp.dict.yaml")
    a = analyze_text("我们的研究是中国的关键", dict_path)
    b = analyze_text("我们的研究是中国的关键", dict_path)
    assert a == b, (a, b)
    for key in ("theoretical", "measured", "word_rate", "selection_rate"):
        assert key in a and isinstance(a[key], (int, float)), (key, a)
    assert 0 <= a["word_rate"] <= 1, a


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("all %d tests passed" % len(fns))
