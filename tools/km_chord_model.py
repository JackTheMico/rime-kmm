#!/usr/bin/env python3
"""空明码并击模型：给定「同一次并击按下的键」，算出引擎真正收到的码。

为什么要这个文件
----------------
击数（1 击 / 2 击）不能靠数码元字符，也不能靠猜：
`schema.yaml` 的 `chord_composer.algebra` 会把一次并击的按键串变成码元串。
关键事实（2026-11-15 逐条核对 algebra）：

- **一次并击 = 双手同时按下**。左手贡献一个码元、右手贡献一个码元，
  所以一次并击最多产出 **2 个码元**（algebra 末尾 `xform/^\\S{3,}$//` 会清空 3 个以上）。
- 每个码元都有「左手式」和「右手式」两种按法，例如
  `R = e+t 或 y+i`、`G = d+g 或 h+k`、`Y = w+t 或 y+o`。
- 因此 `RG` = 左手 e+t ＋ 右手 h+k **同时**按下 = **1 击**，
  词库键就是 `RG`。反而「先 e+t 再 d+g」得到的是 `R=G=`，打不出 `RG`。
- 单手单键打出的码元带标记：左手 `d=`、右手 `=d`；键+空格同击 `d_=` / `=_d`。同样是 1 击。
- 4 码元码（如 `R<GG`）= 两次并击：`R<` ＋ `GG`。

用法
----
    from km_chord_model import press, one_press_codes, strokes
    press(['e', 't', 'h', 'k'])   # -> 'RG'
"""
import re

# schema 里 chord_composer.alphabet，顺序决定并击串的排列
ALPHABET = "qazwsxedcrfvtgbyhnujmik,ol.p;/'7890 "

# 左手键 / 右手键（xlit 之后的右手键里包含 F D J G，它们本来是 ; , . /）
# `'` 在键盘右侧（; 与 Enter 之间），必须算右手键 —— 漏了它会把整个 `X'` 符号族判成死码。
# 数字键 7 8 9 0 虽然也在右手侧，但方案里它们不是并击键元（`(sdf)`/`(wer)`/`(xcv)`/`(asdf)` 才是），
# 单独按 7890 由 `xform/^([7890]+)$/$1=/` 处理，故不放进 RIGHT_KEYS。
LEFT_KEYS = set("qwertasdfgzxcvb")
RIGHT_KEYS = set("yuiophjklFDJGnm,./;'")

XLIT = str.maketrans(';,./', 'FDJG')

# 与 kongmingmas.schema.yaml 的 chord_composer.algebra 逐条对应，顺序不可动
OPS = [
    ('xform', r'(asdf)', '0'),
    ('xform', r'(jkl;)', '@'),
    ('xform', r'(sdf)', '7'),
    ('xform', r'(jkl)', '`'),
    ('xform', r'(wer)', '8'),
    ('xform', r'(uio)', '~'),
    ('xform', r'(xcv)', '9'),
    ('xform', r'(nm)', 'm'),
    ('xlit', None, None),
    ('xform', r'^([qwertasdfgzxcvb]+)( ?)$', r'\1=\2'),
    ('xform', r'^([yuiophjklFnmDJG])', r'=\1'),
    ('xform', r'([A-Za-z])', r'\1-'),
    ('xform', r'^([7890]+)$', r'\1='),
    ('xform', r'(78)', '`'),
    ('xform', r'(89)', '~'),
    ('xform', r'(79)', '@'),
    ('xform', r'(70)', '*'),
    ('xform', r'(90)', '_'),
    ('xform', r'(w-g-|h-o-)', 'U'),
    ('xform', r'(r-g-|h-u-)', '*'),
    ('xform', r'(q-g-|h-p-)', '@'),
    ('xform', r'(e-g-|h-i-)', 'I'),
    ('xform', r'(s-e-f-|j-i-l-)', 'Q'),
    ('xform', r'(w-d-f-|j-k-o-)', '_'),
    ('xform', r'(j-o-|w-f-)', 'h'),
    ('xform', r'(d-f-|j-k-)', 'j'),
    ('xform', r'(s-d-|k-l-)', 'k'),
    ('xform', r'(s-f-|j-l-)', 'l'),
    ('xform', r'(s-g-|h-l-)', 'F'),
    ('xform', r'(a-f-|j-F-)', ';'),
    ('xform', r'(a-s-|l-F-)', ':'),
    ('xform', r'(s-c-|D-l-)', 'n'),
    ('xform', r'(D-l-)', 'n'),
    ('xform', r'(c-v-|m-D-)', 'm'),
    ('xform', r'(x-c-|D-J-)', ','),
    ('xform', r'(a-t-|y-F-)', '<'),
    ('xform', r'(x-v-|m-J-)', '.'),
    ('xform', r'(a-g-|h-F-)', '!'),
    ('xform', r'(z-v-|m-G-)', '/'),
    ('xform', r'(z-x-|J-G-)', '?'),
    ('xform', r'(e-f-|j-i-)', 'y'),
    ('xform', r'(e-r-|u-i-)', 'u'),
    ('xform', r'(w-e-|i-o-)', 'i'),
    ('xform', r'(w-r-|u-o-)', 'o'),
    ('xform', r'(q-r-|u-p-)', 'p'),
    ('xform', r'(q-v-|m-p-)', 'Q'),
    ('xform', r'(w-v-|m-o-)', 'W'),
    ('xform', r'(e-v-|m-i-)', 'E'),
    ('xform', r'(e-t-|y-i-)', 'R'),
    ('xform', r'(q-t-|y-p-)', 'T'),
    ('xform', r'(a-v-|m-F-)', 'A'),
    ('xform', r'(s-v-|m-l-)', 'S'),
    ('xform', r'(d-v-|m-k-)', 'D'),
    ('xform', r'(s-g-|h-l-)', 'F'),
    ('xform', r'(d-g-|h-k-)', 'G'),
    ('xform', r'(q-w-|o-p-)', 'B'),
    ('xform', r'(z-f-|j-G-)', 'Z'),
    ('xform', r'(x-d-|k-J-)', 'X'),
    ('xform', r'(c-f-|j-D-)', 'C'),
    ('xform', r'(z-s-|l-G-)', 'V'),
    ('xform', r'(w-t-|y-o-)', 'Y'),
    ('xform', r'(q-f-|j-p-)', 'P'),
    ('xform', r'(a-w-|o-F-)', 'O'),
    ('xform', r'(a-r-|u-F-)', 'H'),
    ('xform', r'(s-r-|u-l-)', 'L'),
    ('xform', r'(d-r-|u-k-)', 'K'),
    ('xform', r'(x-f-|j-J-)', 'J'),
    ('xform', r'(s-e-|i-l-)', 'N'),
    ('xform', r'(w-d-|k-o-)', 'M'),
    ('xform', r'[aF]-', 'a'),
    ('xform', r'[sl]-', 's'),
    ('xform', r'[dk]-', 'd'),
    ('xform', r'[fj]-', 'f'),
    ('xform', r'[gh]-', 'g'),
    ('xform', r'[zG]-', 'z'),
    ('xform', r'[xJ]-', 'x'),
    ('xform', r'[cD]-', 'c'),
    ('xform', r'[vm]-', 'v'),
    ('xform', r'[bn]-', 'b'),
    ('xform', r'[qp]-', 'q'),
    ('xform', r'[wo]-', 'w'),
    ('xform', r'[ei]-', 'e'),
    ('xform', r'[ru]-', 'r'),
    ('xform', r'[ty]-', 't'),
    ('xform', r'^\S{3,}$', ''),
    ('xform', r'^([A-Za-z])= $', r'\1_='),
    ('xform', r'^=([A-Za-z]) $', r'=_\1'),
]


def press(keys):
    """同一次并击：keys = 同时按下的键（可含空格）。返回引擎收到的输入码。"""
    s = ''.join(sorted(set(keys), key=ALPHABET.index))
    for kind, pat, rep in OPS:
        if kind == 'xlit':
            s = s.translate(XLIT)
        else:
            s = re.sub(pat, rep, s)
    return s


UNXLIT = {'F': ';', 'D': ',', 'J': '.', 'G': '/'}   # algebra 里 F D J G 就是 ; , . /


def _hand(keys):
    if keys and all(k in LEFT_KEYS for k in keys):
        return 'L'
    if keys and all(k in RIGHT_KEYS for k in keys):
        return 'R'
    return None


def realizations():
    """从 algebra 反推：每个码元的左手式/右手式按键集合。"""
    out = {}

    def add(sym, keys):
        keys = [UNXLIT.get(k, k) for k in keys]
        h = _hand(keys)
        if h:
            out.setdefault(sym, {'L': set(), 'R': set()})[h].add(frozenset(keys))

    for kind, pat, rep in OPS:
        if kind != 'xform' or not rep or len(rep) != 1:
            continue
        m = re.fullmatch(r'\((.*)\)', pat)
        if m:                                   # (a-b-|c-d-) 或 (asdf) 两种写法
            for alt in m.group(1).split('|'):
                if re.fullmatch(r'[a-z]+', alt):            # (asdf) → 逐键
                    add(rep, list(alt))
                elif re.fullmatch(r'[a-zA-Z](?:-[a-zA-Z])*-?', alt):
                    add(rep, [k for k in alt if k != '-'])
        m = re.fullmatch(r'\[(..)\]-', pat)      # [aF]- 这类：两个键同义
        if m:
            for k in m.group(1):
                add(rep, [k])
    return out


def one_press_codes():
    """所有「一次并击」能打出的码。

    一次并击 = 左右手各一个码元（可与空格同击，空格也算这一击的一部分）。

    候选按键集合有两个来源：
    1. 从 algebra 反推的每个码元的左手式/右手式（`R = e+t` 或 `y+i`）；
    2. **单个可打印键**——有些词条码是「码元 + 裸键」（`C'` 公司 = 左手 `c+f` ＋ 右手 `'`），
       `'` 不出现在任何 algebra 规则里，只能按位置算作右手单键。
    """
    real = realizations()
    lefts, rights = [frozenset()], [frozenset()]
    for sym, h in real.items():
        lefts.extend(h['L'])
        rights.extend(h['R'])
    lefts.extend(frozenset({k}) for k in LEFT_KEYS)
    # F D J G 是 xlit 之后的产物（原键是 ; , . /），不能当按键直接枚举
    rights.extend(frozenset({k}) for k in RIGHT_KEYS if k not in UNXLIT)
    seen = set()
    for space in (frozenset(), frozenset({' '})):
        for lk in lefts:
            for rk in rights:
                code = press(lk | rk | space)
                if code:
                    seen.add(code)
    return seen


def strokes(code, onepress=None):
    """一个词条码要几次并击：每段 ≤2 码元且可达，段数相加。"""
    if onepress is None:
        onepress = one_press_codes()
    n = len(code)
    if n == 0:
        return 0
    INF = 99
    dp = [INF] * (n + 1)
    dp[0] = 0
    for j in range(1, n + 1):
        for i in range(max(0, j - 4), j):
            if dp[i] + 1 < dp[j] and code[i:j] in onepress:
                dp[j] = dp[i] + 1
    return dp[n]


if __name__ == '__main__':
    cases = [
        (['e', 't', 'h', 'k'], 'RG'),
        (['a', 's', 'd', 'f', 'j'], '0f'),
        (['a', 's', 'd', 'f', 'y', 'o'], '0Y'),
        (['r', 'g', ','], '*c'),
        (['e', 't', 'y', ';'], 'R<'),
        (['d', 'g', 'h', 'k'], 'GG'),
        (['d'], 'd='),
        (['k'], '=d'),
        (['d', ' '], 'd_='),
    ]
    ok = True
    for keys, want in cases:
        got = press(keys)
        flag = 'ok' if got == want else 'X'
        if got != want:
            ok = False
        print('%-22s -> %-8r want %-8r %s' % ('+'.join(keys), got, want, flag))
    one = one_press_codes()
    print('\n一次并击可达码：%d 个' % len(one))
    for c in ['RG', '0f', '0Y', '*c', 'R<', 'GG', 'd=', '=d', 'Wm', 'Ky']:
        print('  %-4s %s' % (c, '可一击' if c in one else '不可一击'))
    print('\n击数：RG=%d  0f=%d  0Y=%d  R<GG=%d' %
          (strokes('RG'), strokes('0f'), strokes('0Y'), strokes('R<GG')))
