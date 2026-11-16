#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 03 TDD：批量分配脚本的红测试。期望值均为手算字面量，独立于实现。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from km_family_alloc import (apply_plan, build_all_families, build_plan,  # noqa: E402
                             collect_all_clean_slots, preview, select_clean_slots)

TMP = "/home/jackwy/Nextcloud/kmrime/.workbuddy/tmp"
os.makedirs(TMP, exist_ok=True)

ONE = {"!A", "!B", "!AB", "nH"}


def stroke(code):
    """受控击数模型：ONE 里的码算 1 击，其余算 2 击。"""
    return 1 if code in ONE else 2


# ---------------------------------------------------------------- select_clean_slots
def test_select_clean_slots_only_takes_certified_clean():
    certify = lambda e, one, fam: {"clean": ["!A", "!B"], "pseudo": ["!C"]}
    got = select_clean_slots([], set(), "!", certify)
    assert got == ["!A", "!B"], got


def test_select_clean_slots_filters_to_family():
    certify = lambda e, one, fam: {"clean": ["!A", "?A", "!B"]}
    got = select_clean_slots([], set(), "!", certify)
    assert got == ["!A", "!B"], got


def test_select_clean_slots_excludes_trailing_space_codes():
    # 词库码里真空格是分隔符（现有库 0 个带空格码），空格并击正规写法是 =；
    # 枚举出的 '!! ' 等带尾空格码是副产物，不可写入词库
    certify = lambda e, one, fam: {"clean": ["!!", "!! ", "!A", "!A ", "!B"]}
    got = select_clean_slots([], set(), "!", certify)
    assert got == ["!!", "!A", "!B"], got


# ---------------------------------------------------------------- build_plan
def test_build_plan_picks_high_freq_two_stroke_words():
    # 你好词频最高，但已有 1 击码 nH → 必须跳过；上的/本身需 2 击 → 入选
    entries = [("上的", "SadW"), ("本身", "bJsW"), ("你好", "nH")]
    freq = {"上的": 80000, "本身": 70000, "你好": 999999}
    plan = build_plan(entries, ["!A", "!B"], freq, stroke, limit=2, min_freq=3000)
    assert [p["word"] for p in plan] == ["上的", "本身"], plan
    assert [p["code"] for p in plan] == ["!A", "!B"], plan
    assert all(p["old_strokes"] == 2 and p["new_strokes"] == 1 for p in plan), plan


def test_build_plan_skips_low_freq():
    entries = [("上的", "SadW"), ("冷词", "xxxx")]
    freq = {"上的": 80000, "冷词": 10}
    plan = build_plan(entries, ["!A", "!B"], freq, stroke, limit=2, min_freq=3000)
    assert [p["word"] for p in plan] == ["上的"], plan


def test_build_plan_respects_limit():
    entries = [("上的", "SadW"), ("本身", "bJsW"), ("体验", "tfYx")]
    freq = {"上的": 80000, "本身": 70000, "体验": 60000}
    plan = build_plan(entries, ["!A", "!B", "!C"], freq, stroke, limit=2, min_freq=3000)
    assert len(plan) == 2, plan
    assert [p["word"] for p in plan] == ["上的", "本身"], plan


def test_build_plan_drops_slot_that_is_prefix_of_another():
    # !A 是 !AB 的前缀：两个都挂会让 !A 退化成需选词 → 必须丢弃 !A
    entries = [("上的", "SadW"), ("本身", "bJsW")]
    freq = {"上的": 80000, "本身": 70000}
    plan = build_plan(entries, ["!A", "!AB"], freq, stroke, limit=2, min_freq=3000)
    codes = [p["code"] for p in plan]
    assert "!A" not in codes, plan
    assert "!AB" in codes, plan


def test_build_plan_skips_non_cjk_and_wrong_length():
    entries = [("上的", "SadW"), ("A", "xxxx"), ("三个字", "xxxx")]
    freq = {"上的": 80000, "A": 90000, "三个字": 70000}
    plan = build_plan(entries, ["!A", "!B", "!C"], freq, stroke, limit=3, min_freq=3000)
    assert [p["word"] for p in plan] == ["上的"], plan


def test_build_plan_no_duplicate_word_or_slot():
    entries = [("上的", "SadW"), ("上的", "zzzz")]  # 同一词两个 2 击码
    freq = {"上的": 80000}
    plan = build_plan(entries, ["!A", "!B"], freq, stroke, limit=2, min_freq=3000)
    assert len(plan) == 1, plan
    assert len({p["code"] for p in plan}) == len(plan), plan


# ---------------------------------------------------------------- preview
def test_preview_shows_code_word_freq_and_strokes():
    plan = [{"code": "!A", "word": "上的", "freq": 80000,
             "old_strokes": 2, "new_strokes": 1}]
    out = preview(plan, family="!")
    assert "!A" in out and "上的" in out and "80,000" in out and "2→1" in out, out
    assert "! 族" in out, out


def test_preview_title_uses_given_family():
    out = preview([], family=";")
    assert "; 族" in out and "! 族" not in out, out


def test_build_plan_respects_family_word_length():
    # ? 族是叠字族：普通二字词「上的」不得挂入；叠字词「看看」才可
    entries = [("上的", "SadW"), ("看看", "kSkS")]
    freq = {"上的": 80000, "看看": 70000}
    plan = build_plan(entries, ["?A", "?B"], freq, stroke, limit=2,
                      min_freq=3000, family="?")
    assert [p["word"] for p in plan] == ["看看"], plan


# ---------------------------------------------------------------- apply_plan
DICT = """# Rime dictionary: kongmingmas_exp
# encoding: utf-8
---
name: kongmingmas_exp
...
上的\tSadW
本身\tbJsW
"""


def _write(p, text=DICT):
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def test_apply_dry_run_does_not_write():
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d.yaml")
        _write(p)
        before = open(p, encoding="utf-8").read()
        n = apply_plan(p, [{"code": "!A", "word": "体验"}], apply=False,
                       stamp="dry", trad_map=None)
        assert open(p, encoding="utf-8").read() == before
        assert n == 1, n


def test_apply_writes_backup_and_keeps_header():
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d.yaml")
        _write(p)
        n = apply_plan(p, [{"code": "!A", "word": "体验"}], apply=True,
                       stamp="20260101-000000", trad_map=None)
        assert n == 1, n
        text = open(p, encoding="utf-8").read()
        assert "体验\t!A" in text, text
        assert text.startswith("# Rime dictionary:") and "name: kongmingmas_exp" in text, text
        assert os.path.exists(p + ".bak-20260101-000000")
        assert "体验\t!A" not in open(p + ".bak-20260101-000000", encoding="utf-8").read()


def test_apply_syncs_trad_map():
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d_t.yaml")
        _write(p)
        apply_plan(p, [{"code": "!A", "word": "后来"}], apply=True,
                   stamp="t", trad_map={"后来": "後來"})
        text = open(p, encoding="utf-8").read()
        assert "後來\t!A" in text and "后来\t!A" not in text, text


def test_apply_does_not_duplicate_existing_code():
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d.yaml")
        _write(p)
        n = apply_plan(p, [{"code": "SadW", "word": "体验"}], apply=True,
                       stamp="dup", trad_map=None)
        assert n == 0, n


def test_apply_rejects_code_with_bom_prefixed_existing_entry():
    # 词库里 泻 的码是 \ufeff!'（BOM 前缀）；挂 !' 会撞码 → auto_select 失效
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d.yaml")
        _write(p, "# h\n---\nname: t\n...\n泻\t\ufeff!'\n")
        n = apply_plan(p, [{"code": "!'", "word": "体验"}], apply=True,
                       stamp="bom", trad_map=None)
        assert n == 0, n


def test_apply_always_creates_backup_even_on_same_stamp():
    # 同一秒二次写库，第二份备份必须反映「第二次写库前」的状态（含第一次的 上的!A），
    # 否则 if-not-exists 跳过备份 → 第二次改动无法回滚。
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        p = os.path.join(d, "d.yaml")
        _write(p)
        apply_plan(p, [{"code": "!A", "word": "上的"}], apply=True,
                   stamp="same", trad_map=None)
        apply_plan(p, [{"code": "!B", "word": "体验"}], apply=True,
                   stamp="same", trad_map=None)
        bak = open(p + ".bak-same", encoding="utf-8").read()
        assert "上的\t!A" in bak and "体验\t!B" not in bak, bak


def test_e2e_one_stroke_word_lowers_metrics_with_all_four_numbers():
    # 端到端：把「上的」从 2 击码 SadW 改成 1 击码 !A 后，尺子四数齐全且理论码长下降。
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(n, p):
        sp = importlib.util.spec_from_file_location(n, p)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m

    vm = load("vm", os.path.join(root, "tools", "km_verify_metrics.py"))
    from km_verify_metrics import analyze
    one = vm.chord.one_press_codes()
    assert "SadW" in one or vm.chord.strokes("SadW", one) == 2  # 确认基线是 2 击
    before_e = [("上的", "SadW")]
    after_e = [("上的", "!A")]
    b = analyze("上的", before_e, one)
    a = analyze("上的", after_e, one)
    for key in ("theoretical", "measured", "word_rate", "selection_rate"):
        assert key in a and isinstance(a[key], (int, float)), (key, a)
    assert a["theoretical"] < b["theoretical"], (b, a)
    assert a["theoretical"] == 0.5, a  # 2字 / 1击 = 0.5 击/字


# ---------------------------------------------------------------- build_all_families（票04）
# 全族槽：二字通用族 ! _ / 叠字族 ? / 三字族 @ / 四字族 *
ALL_ONE = {"!A", "_A", ".A", "?A", "?B", "@A", "*A", "nH"}
# 原码 SadW/KbW/XxY/ZzQ 均为 2 击（待替换），nH 是「我们」已有的一击码。


def stroke_all(code):
    return 1 if code in ALL_ONE else 2


# 体验(二字,2击) / 后来(二字,2击) / 看看(叠字,2击) / 说不定(三字,2击) / 我们(已有1击nH)
FULL_ENTRIES = [("体验", "SadW"), ("后来", "KbW"), ("看看", "XxY"),
                ("说不定", "ZzQ"), ("我们", "nH")]
FULL_FREQ = {"体验": 100, "后来": 90, "看看": 80, "说不定": 70, "我们": 200}


def test_build_all_families_respects_shape_and_dedup():
    # 槽按族：二字 !A _A .A / 叠字 ?A / 三字 @A / 四字 *A
    slots = ["!A", "_A", ".A", "?A", "@A", "*A"]
    plan = build_all_families(FULL_ENTRIES, slots, FULL_FREQ, stroke_all,
                              limit=20, min_freq=0)
    by_word = {p["word"]: p["code"] for p in plan}
    # 我们已有 nH 1击 → 不挂；其余各挂一个，且形状匹配
    assert "我们" not in by_word, by_word
    assert by_word.get("体验") in ("!A", "_A", ".A"), by_word
    assert by_word.get("后来") in ("!A", "_A", ".A"), by_word
    assert by_word.get("看看") == "?A", by_word       # 叠字只进 ? 族
    assert by_word.get("说不定") == "@A", by_word      # 三字只进 @ 族
    # 跨族去重：一个词只出现一次
    assert len(by_word) == len(plan), plan


def test_build_all_families_one_word_one_slot():
    # 我们(200,1击已有) + 体验(100,二字)：即使多个二字槽，体验也只挂一次
    slots = ["!A", "_A", ".A"]
    plan = build_all_families(FULL_ENTRIES, slots, FULL_FREQ, stroke_all,
                              limit=20, min_freq=0)
    codes = [p["code"] for p in plan]
    words = [p["word"] for p in plan]
    assert len(codes) == len(set(codes)), codes      # 槽不重复
    assert len(words) == len(set(words)), words      # 词不重复


def test_build_all_families_limits_count():
    slots = ["!A", "_A", ".A", "?A", "@A", "*A"]
    plan = build_all_families(FULL_ENTRIES, slots, FULL_FREQ, stroke_all,
                              limit=2, min_freq=0)
    assert len(plan) == 2, plan
    # 词频降序：先 体验(100) 后 后来(90)，我们(200)因已有1击被跳过
    assert [p["word"] for p in plan] == ["体验", "后来"], plan


def test_build_all_families_reduplication_skips_general_two_char_slot():
    # 区分「通用二字族排除叠字」与「不排除」的关键夹具：
    # 只有叠字词，通用槽 !A 排在叠字槽 ?A 前面。
    #   正确实现：跳过 !A → 看看挂 ?A
    #   错误实现：通用族收叠字 → 看看挂 !A（被本断言杀死）
    entries = [("看看", "XxY")]
    freq = {"看看": 100}
    plan = build_all_families(entries, ["!A", "?A"], freq, stroke_all, 20, 0)
    assert len(plan) == 1 and plan[0]["word"] == "看看" and plan[0]["code"] == "?A", plan


def test_build_all_families_drops_prefix_slots():
    # 两个干净槽互为前缀（!A 是 !AB 前缀）→ 丢弃短槽 !A，否则挂词后会截断长词。
    # certify 的 prefix 只来自「已占用码」，不覆盖「两个都是干净槽」的情形。
    slots = ["!AB", "!A", "_B"]
    plan = build_all_families(FULL_ENTRIES, slots, FULL_FREQ, stroke_all,
                              limit=20, min_freq=0)
    codes = [p["code"] for p in plan]
    assert "!A" not in codes, codes       # 前缀短槽被剔除
    assert "!AB" in codes, codes          # 长槽保留


def test_collect_all_clean_slots_filters_space_and_protected():
    # certify 返回全族干净槽；编排入口要过滤尾空格码、排除 X~ 保护族、按族稳定排序
    certify = lambda e, one: {
        "clean": ["!A", "_B", "A~", ".C ", "  ", "?D"],
    }
    got = collect_all_clean_slots([], set(), certify)
    assert "A~" not in got, got          # X~ 保护族排除
    assert ".C " not in got and "  " not in got, got   # 尾空格/纯空格过滤
    assert set(got) == {"!A", "_B", "?D"}, got
    assert got == sorted(got), got       # 稳定排序，保证可复现


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("all %d tests passed" % len(fns))
