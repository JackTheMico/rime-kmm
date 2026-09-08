#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成空明码「拼音反查」分片数据。

原理
----
1. 从 luna_pinyin.dict.yaml 建立 单字 -> 无声调全拼 的映射
   （只取文本正好为 1 个汉字的条目，避免把整词拼音误当作单字拼音）。
2. 流式读取 kongmingma.dict.yaml（word -> code），对每个词条：
     拼音键 = 各字拼音顺序拼接（任意一字无拼音则跳过该词）；
     按拼音首字母分桶，写入 lua/kongmingma/data/reverse_<initial>.lua。
3. 反查翻译器（lua/kongmingma/reverse_lookup.lua）按 ` + 拼音 查这些分片，
   候选注释显示该字/词在空明码主码表中的编码。

依赖：本机需有 luna_pinyin.dict.yaml（Arch: /usr/share/rime-data/luna_pinyin.dict.yaml）。

用法
----
  python3 tools/gen_kongmingma_reverse.py
  python3 tools/gen_kongmingma_reverse.py --limit 200000   # 调试用，只处理前 N 条

输出
----
  lua/kongmingma/data/reverse_<initial>.lua       （加载器，合并下方各片）
  lua/kongmingma/data/reverse_<initial>_N.lua     （数据分片，单片常量数 < 65536）
  每个首字母按条目数自动切片，避免 LuaJIT 单文件 65536 常量上限导致加载失败。
"""

import os
import sys
import argparse
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KM_DICT = os.path.join(ROOT, "kongmingma.dict.yaml")
LUNA_DICT = "/usr/share/rime-data/luna_pinyin.dict.yaml"
OUT_DIR = os.path.join(ROOT, "lua", "kongmingma", "data")

# 每个拼音键下多字词条的最大保留数（单字不受限，天然有限）。
# 调小可显著减小生成文件体积；调大可保留更多长词。
CAP_MULTI = 600


def char_len(s: str) -> int:
    """Unicode 码点个数（汉字=1）。"""
    return len(s)


def build_char_pinyin(path: str) -> dict:
    """单字 -> 无声调全拼（首个出现者优先）。"""
    char_py = {}
    with open(path, "r", encoding="utf-8") as f:
        in_body = False
        for line in f:
            line = line.rstrip("\n")
            if not in_body:
                if line.strip() == "...":
                    in_body = True
                continue
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            # RIME 词典格式：text ⇥ code（此处 code 为拼音音节）
            text, py = parts[0].strip(), parts[1].strip()
            if text == "" or py == "":
                continue
            # 仅取「单字 + 纯字母拼音」条目建立映射，排除多字词与注音符号
            if char_len(text) != 1:
                continue
            if not (py.isascii() and py.isalpha()):
                continue
            if text not in char_py:
                char_py[text] = py.lower()
    return char_py


def pinyin_key(word: str, char_py: dict):
    keys = []
    for ch in word:
        py = char_py.get(ch)
        if py is None:
            return None
        keys.append(py)
    return "".join(keys).lower()


def lua_quote(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + s + '"'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（调试）")
    args = ap.parse_args()

    if not os.path.exists(LUNA_DICT):
        print("找不到 luna_pinyin.dict.yaml：%s" % LUNA_DICT, file=sys.stderr)
        print("请安装 rime-pinyin（Arch: pacman -S rime-pinyin）后重试。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(KM_DICT):
        print("找不到 kongmingma.dict.yaml：%s" % KM_DICT, file=sys.stderr)
        sys.exit(1)

    print("建立 单字->拼音 映射 …")
    char_py = build_char_pinyin(LUNA_DICT)
    print("  单字数：%d" % len(char_py))

    # shards[initial][pinyin_key] = list of [word, code]
    shards = {chr(ord("a") + i): {} for i in range(26)}

    print("扫描 kongmingma.dict.yaml …")
    total = 0
    indexed = 0
    with open(KM_DICT, "r", encoding="utf-8") as f:
        in_body = False
        for line in f:
            if args.limit and total >= args.limit:
                break
            line = line.rstrip("\n")
            if not in_body:
                if line.strip() == "...":
                    in_body = True
                continue
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word = parts[0].strip()
            code = parts[1].strip()
            if word == "" or code == "":
                continue
            total += 1
            pk = pinyin_key(word, char_py)
            if not pk or not (pk.isascii() and pk.isalpha()):
                continue
            initial = pk[0]
            bucket = shards[initial]
            lst = bucket.get(pk)
            is_single = char_len(word) == 1
            if lst is None:
                bucket[pk] = [[word, code]]
                indexed += 1
            else:
                # 去重（同一拼音键下同一词条只留一次）
                dup = False
                for e in lst:
                    if e[0] == word:
                        dup = True
                        break
                if dup:
                    continue
                if is_single or len(lst) < CAP_MULTI:
                    lst.append([word, code])
                    indexed += 1
            if total % 500000 == 0:
                print("  已扫描 %d 万条，索引 %d 万" % (total // 10000, indexed // 10000))

    print("扫描完成：共 %d 条，可反查索引 %d 条" % (total, indexed))

    os.makedirs(OUT_DIR, exist_ok=True)

    # 清理旧分片（含旧版单片文件与多片文件），避免残留。
    # 注意：部分环境将 os.remove 重定向为“安全删除”并可能失败，故忽略删除错误，
    # 后续写入会直接覆盖同名文件；多出的旧 part 文件无害（加载器只 require 实际引用的分片）。
    for old in glob.glob(os.path.join(OUT_DIR, "reverse_*.lua")):
        try:
            os.remove(old)
        except OSError:
            pass

    # 每片条目上限：确保单片 Lua 的字符串常量数 < 65536（LuaJIT 单函数上限）。
    # 每条目约贡献 3 个字符串常量（拼音键 + 词 + 码），12000 条目 ≈ 3.6 万，留足余量。
    MAX_ENTRIES = 12000

    print("写出分片到 %s …" % OUT_DIR)
    for initial in sorted(shards.keys()):
        bucket = shards[initial]
        keys = sorted(bucket.keys())

        # 按条目数分片，避免单片超出常量上限
        parts = []
        cur = {}
        cur_entries = 0
        for pk in keys:
            lst = bucket[pk]
            if cur and len(cur) > 0 and cur_entries + len(lst) > MAX_ENTRIES:
                parts.append(cur)
                cur = {}
                cur_entries = 0
            cur[pk] = lst
            cur_entries += len(lst)
        if cur:
            parts.append(cur)

        if not parts:
            # 该首字母无数据（如 i/u/v），写入空加载器
            loader_path = os.path.join(OUT_DIR, "reverse_%s.lua" % initial)
            with open(loader_path, "w", encoding="utf-8") as out:
                out.write("-- 自动生成，请勿手改。由 tools/gen_kongmingma_reverse.py 生成。\n")
                out.write("return {}\n")
            print("  reverse_%s.lua: 0 个拼音键（空）" % initial)
            continue

        # 写出各 part 文件（数据本体）
        for idx, part in enumerate(parts, start=1):
            part_path = os.path.join(OUT_DIR, "reverse_%s_%d.lua" % (initial, idx))
            with open(part_path, "w", encoding="utf-8") as out:
                out.write("-- 自动生成，请勿手改。reverse_%s 第 %d 片。\n" % (initial, idx))
                out.write("return {\n")
                for pk in sorted(part.keys()):
                    arr = ",".join(
                        "{%s,%s}" % (lua_quote(w), lua_quote(c)) for w, c in part[pk]
                    )
                    out.write('  [%s] = {%s},\n' % (lua_quote(pk), arr))
                out.write("}\n")

        # 写出加载器：合并所有 part（绕过 LuaJIT 单文件常量上限）
        loader_path = os.path.join(OUT_DIR, "reverse_%s.lua" % initial)
        with open(loader_path, "w", encoding="utf-8") as out:
            out.write("-- 自动生成，请勿手改。由 tools/gen_kongmingma_reverse.py 生成。\n")
            out.write("-- reverse_%s 的分片合并加载器。\n" % initial)
            out.write("local _t = {}\n")
            out.write("local function _m(t) for k, v in pairs(t) do _t[k] = v end end\n")
            for idx in range(1, len(parts) + 1):
                out.write('_m(require("kongmingma.data.reverse_%s_%d"))\n' % (initial, idx))
            out.write("return _t\n")

        print("  reverse_%s.lua: %d 个拼音键，分 %d 片" % (initial, len(bucket), len(parts)))

    print("完成。")


if __name__ == "__main__":
    main()
