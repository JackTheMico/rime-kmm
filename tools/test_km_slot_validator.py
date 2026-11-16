#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 02 空槽校验器的测试。期望值手算，只测公开接口。

seam（spec 已约定）：
  - classify_slot(code, code_words, prefix, one)：判定单个码的状态
  - certify(entries, one)：对整份词库产出认证空槽清单
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from km_slot_validator import classify_slot, certify, certify_by_family, load_entries  # noqa: E402


def test_load_entries_strips_bom_from_code_field():
    # 词库里 泻/嚎/锭 的码字段是 \ufeff!'（BOM 前缀），词字段也有 BOM。
    # 若不清洗码字段，!' 会被误判为空槽，挂词后与原字撞码 → auto_select 失效。
    tmpdir = "/home/jackwy/Nextcloud/kmrime/.workbuddy/tmp"
    os.makedirs(tmpdir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=tmpdir, suffix=".yaml",
                                     delete=False, encoding="utf-8") as f:
        f.write("---\nname: t\n...\n")
        f.write("\ufeff泻\t\ufeff!'\n")   # 词与码都带 BOM（真实词库就是这个形态）
        f.write("体验\tdry\n")
        path = f.name
    try:
        entries = load_entries(path)
        assert ("泻", "!'") in entries, entries
        codes = {c for w, c in entries}
        assert "!'" in codes, codes
    finally:
        os.unlink(path)


def test_clean_slot_is_certified():
    # a= 可达、词库未占、非任何码前缀 → clean
    code_words = {"oY": ["研究"]}
    prefix = {"o"}          # oY 的真前缀
    one = {"a=", "oY"}
    assert classify_slot("a=", code_words, prefix, one)["state"] == "clean"


def test_unreachable_code_is_rejected():
    code_words = {}
    prefix = set()
    one = {"a=", "b="}
    r = classify_slot("ZZ", code_words, prefix, one)
    assert r["state"] == "unreachable", r


def test_occupied_code_is_rejected():
    code_words = {"a=": ["我"]}
    prefix = set()
    one = {"a="}
    r = classify_slot("a=", code_words, prefix, one)
    assert r["state"] == "occupied", r


def test_false_slot_prefix_of_longer_code_is_rejected():
    # @k 看着空，其实是「可以说」= @kXYZ 的前缀 → 挂一击会截断长词
    code_words = {"@kXYZ": ["可以说"]}
    prefix = {"@", "@k", "@kX", "@kXY"}
    one = {"@", "@k"}
    r = classify_slot("@k", code_words, prefix, one)
    assert r["state"] == "pseudo", r
    assert "前缀" in r["reason"], r


def test_x_tilde_family_is_protected():
    # X~ 数字大写族永不外借：即便干净也不进可挂词清单
    code_words = {}
    prefix = set()
    one = {"A~", "B~", "a="}
    r = classify_slot("A~", code_words, prefix, one)
    assert r["state"] == "protected", r


def test_codes_with_1_to_6_are_excluded():
    # 含 1-6 的码只能靠 Ctrl 送键，比全码还慢 → 不可用
    code_words = {}
    prefix = set()
    one = {"a1", "a=", "a7"}
    assert classify_slot("a1", code_words, prefix, one)["state"] == "excluded"
    assert classify_slot("a7", code_words, prefix, one)["state"] not in ("excluded", "unreachable")


def test_certify_excludes_all_but_clean():
    entries = [("研究", "oY"), ("我", "a=")]
    one = {"a=", "oY", "b=", "A~"}
    result = certify(entries, one)
    # a= 被占、oY 被占、A~ 受保护 → 清单只有 b=
    assert result["clean"] == ["b="], result
    assert "A~" not in result["clean"], result


def test_certify_by_family_reports_reachable_occupied_clean():
    # 票02 验收：五符号族各输出「可达码数/已占/干净空槽数」分项。
    # 构造 ? 族：?a 可达且干净、?b 被占、?c 是 ?cd 前缀（伪空槽）
    entries = [("X", "?b"), ("Y", "?cd")]
    one = {"?a", "?b", "?c", "?cd"}
    r = certify_by_family(entries, one, ["?"])
    fam = r["?"]
    assert fam["reachable"] == 4, fam
    assert fam["clean"] == ["?a"], fam
    assert fam["occupied"] == 2, fam  # ?b 挂 X、?cd 挂 Y
    assert fam["pseudo"] == 1, fam  # ?c 是 ?cd 的前缀


def test_certify_counts_match_validator():
    entries = [("研究", "oY")]
    one = {"a=", "b=", "oY"}
    result = certify(entries, one)
    assert result["summary"]["clean"] == len(result["clean"]), result
    assert result["summary"]["occupied"] >= 1, result


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("all %d tests passed" % len(fns))
