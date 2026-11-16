#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""票 03：批量分配脚本——把当前需两击的高频二字词挂进某符号族的干净空槽。

只作用于隔离实验方案 kongmingmas_exp，原方案 kongmingmas 不受影响。

流水线（tracer bullet，票 03）
------------------------------
  1. select_clean_slots  复用票 02 certify，取该族认证干净的空槽（可达/未占/非前缀）
  2. build_plan          按词频挑「当前需 ≥2 击、尚无 1 击码」的二字词，一一映射到空槽
  3. preview             打印预览表（默认行为，不写库）
  4. apply_plan          --apply 才写库：先备份，保留 YAML 头，可同步繁体库

关键护栏（来自 spec / 票 02 / 票 05 决策）
-------------------------------------------
- 空槽必须经票 02 校验器认证，伪空槽（如 @k 是「可以说」的前缀）零漏网。
- 同源码前缀关系：若槽 A 是槽 B 的前缀，两个都挂会让 A 退化成需选词 → 丢弃 A。
- 目标词必须「当前 ≥2 击且无 1 击码」——已有 1 击码的词再挂是重复占用。
- 二字纯汉字词，词频达门槛，避免异读标注行（含空格）。
- 一个码只挂一个词：零延伸 + 唯一候选，auto_select 才能生效。
- 写库前自动备份；转义体用 trad_map 同步；YAML 头原样保留。

对外接口（seam，spec Testing Decisions 已约定）
  select_clean_slots(entries, one, family, certify) -> [code]
  build_plan(entries, clean_slots, freq, stroke_of_code, limit, min_freq) -> [dict]
  preview(plan) -> str
  apply_plan(dict_path, plan, apply, stamp, trad_map) -> int

用法
----
    python3 tools/km_family_alloc.py --family '!'                # 预览
    python3 tools/km_family_alloc.py --family '!' --limit 40     # 限量预览
    python3 tools/km_family_alloc.py --family '!' --apply        # 写库（自动备份）
    python3 tools/km_family_alloc.py --family '!' --apply --with-trad  # 简繁同步
"""
import argparse
import datetime
import importlib.util
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT_S = os.path.join(ROOT, "kongmingmas_exp.dict.yaml")
DICT_T = os.path.join(ROOT, "kongmingmas_exp_t.dict.yaml")
DEFAULT_FAMILY = "!"
DEFAULT_LIMIT = 40
DEFAULT_MIN_FREQ = 3000


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chord = _load("km_chord_model", os.path.join(ROOT, "tools", "km_chord_model.py"))
val = _load("km_slot_validator", os.path.join(ROOT, "tools", "km_slot_validator.py"))
kmopt = _load("kmopt", os.path.join(ROOT, "tools", "km_jianma_opt.py"))

# 语义族守恒（km_jianma_zero 的护栏）：族决定能挂什么词形。
# 不遵守会把二字词塞进叠字族，打乱既有分工（票 05 决策 / 票03 验收第7条）。
FAMILY_SHAPE = {
    "?": lambda w: len(w) == 2 and w[0] == w[1],   # 叠字族
    "@": lambda w: len(w) == 3,                     # 三字族
    "*": lambda w: len(w) == 4,                     # 四字语族
}


def _shape_ok(family, word):
    pred = FAMILY_SHAPE.get(family)
    return pred(word) if pred else _is_two_cjk(word)


def select_clean_slots(entries, one, family, certify):
    """取该族经校验器认证的干净空槽；certify 注入以便测试。

    排除带尾随空格的码：词库两列结构里真空格是分隔符（现有库 0 个带空格码），
    空格并击的正规写法是 `=`。`!! ` 这类是 one_press_codes 枚举副产物，不可写库。
    """
    result = certify(entries, one, [family])
    return [c for c in result["clean"]
            if c.startswith(family) and " " not in c]


def _is_two_cjk(w):
    return len(w) == 2 and all("\u4e00" <= ch <= "\u9fff" for ch in w)


def build_plan(entries, clean_slots, freq, stroke_of_code, limit, min_freq, family="!"):
    """把当前需两击的高频词映射到干净空槽。

    family 决定词形（? 叠字 / @ 三字 / * 四字 / 其余二字），守住语义分工。
    stroke_of_code 注入（生产传 chord.strokes 的偏函数），期望值可在测试里手算。
    返回 [{"word","code","freq","old_strokes","new_strokes"}].
    """
    # 词 → 该词所有码的击数；词若已有任一 1 击码则跳过（不重复占用）
    word_codes = {}
    for w, c in entries:
        if " " in w:            # 跳过异读标注构造行
            continue
        word_codes.setdefault(w, []).append(c)

    candidates = []
    for w, codes in word_codes.items():
        if " " in w or not _shape_ok(family, w):
            continue
        f = freq.get(w, 0)
        if f < min_freq:
            continue
        strokes = [stroke_of_code(c) for c in codes]
        strokes = [s for s in strokes if s is not None and s < 99]
        if not strokes:
            continue
        best = min(strokes)
        if best < 2:            # 已有 1 击码 → 不挂
            continue
        candidates.append((f, w, best))
    # 词频降序；同频按词面排序保证可复现
    candidates.sort(key=lambda x: (-x[0], x[1]))

    # 剔除「是另一空槽前缀」的槽：两个都挂会让短码退化成需选词
    slots = sorted(set(clean_slots))
    usable = [c for c in slots if not any(c != d and d.startswith(c) for d in slots)]
    if not usable or not candidates:
        return []

    plan = []
    seen_words = set()
    for (f, w, old), code in zip(candidates, usable[:limit]):
        if w in seen_words:
            continue
        seen_words.add(w)
        plan.append({
            "code": code,
            "word": w,
            "freq": f,
            "old_strokes": old,
            "new_strokes": stroke_of_code(code),
        })
    return plan


def collect_all_clean_slots(entries, one, certify):
    """全族干净槽汇总（票04）：校验器认证 → 过滤尾空格/纯空格/X~ 保护族 → 稳定排序。

    certify 注入（生产传 val.certify 的偏函数），期望值可手算。
    排序按码面字典序：族内前缀相邻，编排时短线优先，且结果可复现。
    """
    clean = certify(entries, one)["clean"]
    kept = [c for c in clean if c.strip() and " " not in c and c not in val.PROTECTED]
    return sorted(kept)


def _shape_ok_all(code, word):
    """全族语义约束：槽的首字符决定它能挂什么词形（票05语义分工）。

    ? 叠字 / @ 三字 / * 四字 / 其余二字（通用二字族不收叠字）。
    """
    # 注意：与单族脚本的 FAMILY_SHAPE 不同——那里 ? 族之外的二字族也收叠字；
    # 全族编排必须把叠字单独归到 ? 族，故通用二字族显式排除叠字，避免分工漂移。
    fam = code[0]
    if fam == "?":
        return len(word) == 2 and word[0] == word[1]
    if fam == "@":
        return len(word) == 3
    if fam == "*":
        return len(word) == 4
    return _is_two_cjk(word) and not (len(word) == 2 and word[0] == word[1])


def build_all_families(entries, clean_slots, freq, stroke_of_code, limit, min_freq):
    """全族编排（票04）：跨族去重，按词频降序把词挂进形状匹配的干净槽。

    - 一个词只挂一个槽、一个槽只挂一个词（全局去重）。
    - 语义分工由 _shape_ok_all 保证（叠字/?三字@/四字*/二字其余）。
    - 已有 1 击码的词跳过；槽前缀关系由票02校验器保证，此处不重复判。
    - 槽按给定顺序（调用方已排序）分配，保证可复现。
    """
    word_codes = {}
    for w, c in entries:
        if " " in w:
            continue
        word_codes.setdefault(w, []).append(c)

    candidates = []
    for w, codes in word_codes.items():
        f = freq.get(w, 0)
        if f < min_freq:
            continue
        strokes = [stroke_of_code(c) for c in codes]
        strokes = [s for s in strokes if s is not None and s < 99]
        if not strokes:
            continue
        if min(strokes) < 2:      # 已有 1 击码 → 不重复占用
            continue
        candidates.append((f, w, min(strokes)))
    candidates.sort(key=lambda x: (-x[0], x[1]))

    # 剔除「是别的空槽前缀」的短槽：两个干净槽互为前缀时 certify 不拦
    # （它的 prefix 只来自已占用码），短槽若挂词会截断长槽 → 丢弃短槽。
    slots = sorted(set(clean_slots))
    usable = [c for c in slots if not any(c != d and d.startswith(c) for d in slots)]

    # 一词一槽由内层 break 保证；一槽一词由 used_slots 保证。
    # （候选词来自 dict，天然唯一，无需额外的词去重集合。）
    used_slots = set()
    plan = []
    for f, w, old in candidates:
        if len(plan) >= limit:
            break
        for code in usable:
            if code in used_slots or not _shape_ok_all(code, w):
                continue
            used_slots.add(code)
            plan.append({"code": code, "word": w, "freq": f,
                         "old_strokes": old, "new_strokes": stroke_of_code(code)})
            break
    return plan


def preview(plan, family="!"):
    """人类可读预览表。"""
    lines = ["# 码长实验 · 批量分配预览（%s 族）" % family,
             "", "| 码 | 词 | 词频 | 击数 |", "| :--- | :--- | ---: | :---: |"]
    for p in plan:
        lines.append("| `{code}` | {word} | {freq:,} | {old}→{new} |".format(
            code=p["code"], word=p["word"], freq=p["freq"],
            old=p["old_strokes"], new=p["new_strokes"]))
    lines.append("")
    lines.append("共 %d 条；默认预览不写库，加 --apply 才落盘。" % len(plan))
    return "\n".join(lines)


def apply_plan(dict_path, plan, apply, stamp, trad_map=None):
    """写库（或 dry-run）；返回实际新增行数。备份保留 YAML 头。"""
    with open(dict_path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    # 已有码集合（避免重复挂同一码）
    existing = set()
    for line in lines:
        if "\t" in line:
            existing.add(line.split("\t", 1)[1].replace("\ufeff", ""))

    additions = []
    for p in plan:
        code = p["code"]
        if code in existing:
            continue
        word = (trad_map or {}).get(p["word"], p["word"])
        additions.append("%s\t%s" % (word, code))
        existing.add(code)
    if not additions:
        return 0

    if apply:
        bak = "%s.bak-%s" % (dict_path, stamp)
        shutil.copy2(dict_path, bak)   # 总是备份：多次写库各自留一个可回滚点
        body = "\n".join(lines).rstrip("\n") + "\n" + "\n".join(additions) + "\n"
        with open(dict_path, "w", encoding="utf-8") as f:
            f.write(body)
    return len(additions)


def main():
    ap = argparse.ArgumentParser(description="码长实验：高频二字词 → 符号族空槽")
    ap.add_argument("--family", default=DEFAULT_FAMILY, help="前缀族，如 ! 或 ;")
    ap.add_argument("--all", action="store_true",
                    help="全族编排（票04）：遍历全部干净槽，跨族去重挂高频词")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--min-freq", type=int, default=DEFAULT_MIN_FREQ)
    ap.add_argument("--dict", default=DICT_S, help="简体词库（默认实验方案）")
    ap.add_argument("--apply", action="store_true", help="写库（默认只预览）")
    ap.add_argument("--with-trad", action="store_true", help="同步繁体实验库")
    args = ap.parse_args()

    print("读取词库与可达码…")
    entries = val.load_entries(args.dict)
    one = chord.one_press_codes()
    print("读取词频…")
    freq = kmopt.load_freq()
    stroke = lambda c: chord.strokes(c, one)

    if args.all:
        clean = collect_all_clean_slots(entries, one, val.certify)
        print("全族干净空槽 %d 个" % len(clean))
        plan = build_all_families(entries, clean, freq, stroke,
                                  args.limit, args.min_freq)
        print(preview(plan, family="全族"))
    else:
        clean = select_clean_slots(entries, one, args.family, val.certify)
        print("%s 族干净空槽 %d 个" % (args.family, len(clean)))
        plan = build_plan(entries, clean, freq, stroke, args.limit, args.min_freq,
                          family=args.family)
        print(preview(plan, family=args.family))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    n_s = apply_plan(args.dict, plan, apply=args.apply, stamp=stamp)
    print("简体库：%s %d 条" % ("写入" if args.apply else "待写", n_s))
    if args.with_trad and args.apply:
        trad = kmopt.to_trad([p["word"] for p in plan])
        trad_map = {p["word"]: trad.get(p["word"], p["word"]) for p in plan}
        n_t = apply_plan(DICT_T, plan, apply=True, stamp=stamp, trad_map=trad_map)
        print("繁体库：写入 %d 条" % n_t)


if __name__ == "__main__":
    main()
