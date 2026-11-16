#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 02：空槽校验器——认证「可达 + 未占用 + 非前缀 + 唯一候选」的干净一击空槽。

杜绝的坑（来自 spec / research）：
- 伪空槽：`@k` 看着空，其实是「可以说」= @kXYZ 的前缀，挂一击会截断长词。
- `X~` 数字大写族永不外借（大写字母 + `~`）。
- 含 1–6 的码只能 Ctrl 送键，比全码还慢，不可用（7/8/9 可用）。
- 干净空槽要求「零延伸 + 唯一候选」：挂词后必须自动上屏，不能退化成按空格选词。

对外接口（seam，spec Testing Decisions 已约定）：
  classify_slot(code, code_words, prefix, one) -> {"state": ..., "reason": ...}
  certify(entries, one) -> {"clean": [...], "rejected": {...}, "summary": {...}}

用法
----
    python3 tools/km_slot_validator.py                      # 全库认证，终端摘要
    python3 tools/km_slot_validator.py --prefix '?' --list   # 看某族干净空槽
    python3 tools/km_slot_validator.py --dict kongmingmas_exp.dict.yaml
"""
import argparse
import collections
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DICT = os.path.join(ROOT, "kongmingmas_exp.dict.yaml")
# 数字大写族永不外借：大写字母 + 波浪号
PROTECTED = {"%s~" % c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
SLOW_DIGITS = set("123456")   # 只能 Ctrl 送键


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chord = _load("km_chord_model", os.path.join(ROOT, "tools", "km_chord_model.py"))


def load_entries(path):
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


def build_index(entries):
    """code_words: 码 → 词列表; prefix: 所有码的真前缀集合。"""
    code_words = collections.defaultdict(list)
    for w, c in entries:
        code_words[c].append(w)
    prefix = set()
    for c in code_words:
        for i in range(1, len(c)):
            prefix.add(c[:i])
    return dict(code_words), prefix


def classify_slot(code, code_words, prefix, one):
    """判定单个码可否作为干净一击空槽。

    判定顺序（先硬伤后占用）：
      excluded   含 1-6 的码（Ctrl 送键，不可用）
      protected  X~ 数字大写族（永不外借）
      unreachable 一击打不出（不在 one 集合）
      pseudo     是某个更长码的前缀（挂上去会截断长词）
      occupied   词库已有此码
      clean      可达 + 未占 + 非前缀，可安全挂词
    """
    if any(ch in SLOW_DIGITS for ch in code):
        return {"state": "excluded", "reason": "含 1-6，只能 Ctrl 送键"}
    if code in PROTECTED:
        return {"state": "protected", "reason": "X~ 数字大写族，永不外借"}
    if code not in one:
        return {"state": "unreachable", "reason": "一次并击打不出"}
    # prefix 由 code_words 的所有真前缀构造，故 in prefix 必存在更长码
    if code in prefix:
        return {"state": "pseudo", "reason": "是更长码的前缀，会截断长词"}
    if code in code_words:
        return {"state": "occupied", "reason": "词库已占用"}
    return {"state": "clean", "reason": "可达+未占+非前缀，零延伸唯一候选"}


def certify(entries, one, prefixes=None):
    """对整份词库认证：遍历 all one-press codes，产出分类清单。

    prefixes 可传多个前缀族过滤（如 ['?','*']），None 表示全部。
    """
    code_words, prefix = build_index(entries)
    candidates = sorted(one)
    if prefixes:
        candidates = [c for c in candidates if any(c.startswith(p) for p in prefixes)]
    groups = collections.defaultdict(list)
    for c in candidates:
        r = classify_slot(c, code_words, prefix, one)
        groups[r["state"]].append(c)
    return {
        "clean": groups.get("clean", []),
        "rejected": {k: v for k, v in groups.items() if k != "clean"},
        "summary": {k: len(v) for k, v in groups.items()},
    }


def certify_by_family(entries, one, families):
    """按前缀族给出分项盘点（票 02 验收标准）：每族 reachable/occupied/clean/pseudo 等。

    与 certify 的区别：certify 给全局汇总，本函数按族分组，便于对照
    `< ; ! @ ?` 各族的可达数/已占数/干净空槽数。
    """
    code_words, prefix = build_index(entries)
    out = {}
    for fam in families:
        codes = sorted(c for c in one if c.startswith(fam))
        groups = collections.defaultdict(list)
        for c in codes:
            groups[classify_slot(c, code_words, prefix, one)["state"]].append(c)
        out[fam] = {
            "reachable": len(codes),
            "clean": groups.get("clean", []),
            "occupied": len(groups.get("occupied", [])),
            "pseudo": len(groups.get("pseudo", [])),
            "protected": len(groups.get("protected", [])),
            "excluded": len(groups.get("excluded", [])),
            "unreachable": len(groups.get("unreachable", [])),
        }
    return out


def main():
    ap = argparse.ArgumentParser(description="空槽校验器：认证干净一击空槽")
    ap.add_argument("--dict", default=DEFAULT_DICT)
    ap.add_argument("--prefix", action="append", help="只看某前缀族，可重复")
    ap.add_argument("--by-family", action="store_true",
                    help="按族盘点（默认五符号族 < ; ! @ ?），各给可达/已占/干净数")
    ap.add_argument("--list", action="store_true", help="列出干净空槽（默认只给摘要）")
    args = ap.parse_args()
    entries = load_entries(args.dict)
    one = chord.one_press_codes()
    if args.by_family:
        families = args.prefix or ["<", ";", "!", "@", "?"]
        result = certify_by_family(entries, one, families)
        for fam, r in result.items():
            print("%s 族：可达 %d / 已占 %d / 伪空槽 %d / 干净 %d"
                  % (fam, r["reachable"], r["occupied"], r["pseudo"], len(r["clean"])))
        if args.list:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = certify(entries, one, args.prefix)
    if args.list:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("认证结果：", json.dumps(result["summary"], ensure_ascii=False))
        print("干净空槽前 40：", "  ".join(result["clean"][:40]))


if __name__ == "__main__":
    main()
