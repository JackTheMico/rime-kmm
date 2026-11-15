#!/usr/bin/env python3
"""统计常用单字的上屏成本（几次并击、要不要空格、要不要选词），生成 char_onehit_report.md。

击数口径（2026-11-15 校正，模型见 tools/km_chord_model.py）
----------------------------------------------------------
**一次并击 = 双手同时按下**：左手出一个码元、右手出一个码元，一次最多 2 个码元。

- `RG`：左手 `e+t`（=R）＋ 右手 `h+k`（=G）同时按下 → 引擎收到 `RG` → **1 击**。
  词库键正是 `RG`；「先 e+t 再 d+g」得到 `R=G=`，反而打不出 `RG`。
- `0f`：左手 `asdf`（=0）＋ 右手 `j`（=f）→ `0f` → **1 击**。
- `0Y`：左手 `asdf` ＋ 右手 `y+o`（=Y）→ `0Y` → **1 击**。
- `R<GG`：4 码元，两次并击（`R<` ＋ `GG`）→ 2 击。

自动上屏 = 零延伸（不是任何更长码的前缀）且唯一候选（schema `auto_select: true`）。
有延伸的码按一下空格就上屏，算「一击+空格」，不算选词。

用法
----
    python3 tools/km_char_onehit.py              # 前 1500，写报告
    python3 tools/km_char_onehit.py --top 3000   # 换范围
    python3 tools/km_char_onehit.py --no-write   # 只看终端输出
"""
import argparse
import collections
import datetime
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
REPORT = os.path.join(REPORTS, 'char_onehit_report.md')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kmopt = _load('kmopt', os.path.join(ROOT, 'tools/km_jianma_opt.py'))
chord = _load('km_chord_model', os.path.join(ROOT, 'tools/km_chord_model.py'))


def is_cjk(ch):
    return '\u4e00' <= ch <= '\u9fff'


def load_entries(path):
    out, started = [], False
    for line in open(path, encoding='utf-8'):
        s = line.rstrip('\n')
        if not s:
            continue
        if not started:
            if s == '...':
                started = True
            continue
        if s.startswith('#') or '\t' not in s:
            continue
        p = s.split('\t')
        out.append((p[0].replace('\ufeff', ''), p[1]))
    return out


def build(entries):
    codes = collections.defaultdict(list)
    word_codes = collections.defaultdict(list)
    for w, c in entries:
        if ' ' in w:                       # 「字 + 空格 + 后缀」不是独立词条
            continue
        codes[c].append(w)
        word_codes[w].append(c)
    prefix = set()
    for c in codes:
        for i in range(1, len(c)):
            prefix.add(c[:i])
    return codes, word_codes, prefix


def tier(c, codes, prefix):
    if c in prefix:
        return 'ext'
    return 'auto' if len(codes[c]) == 1 else 'zero'


def char_rank(freq):
    cf = collections.Counter()
    for w, f in freq.items():
        if len(w) == 1 and is_cjk(w):
            cf[w] += f
    return [w for w, _ in cf.most_common()], cf


def analyze(top, codes, word_codes, prefix, cf, one):
    """成本模型：击数（一次双手并击 = 1 击）＋ 要不要按空格。"""
    rows = []
    tally = collections.Counter()
    for i, ch in enumerate(top, 1):
        best = None
        for c in word_codes.get(ch, []):
            st = chord.strokes(c, one)
            if st >= 99:                       # 码里含 `/` 等 algebra 产不出的字符
                continue
            space = 0 if tier(c, codes, prefix) == 'auto' else 1
            key = (st + space, st, len(c))
            if best is None or key < best[0]:
                best = (key, c, st, space)
        if best is None:
            tally['死码'] += 1
            rows.append((i, ch, '死码', '-', 0, cf[ch]))
            continue
        key, c, st, space = best
        if st <= 1:
            tag = '一击' if not space else '一击+空格'
        else:
            tag = '多击' if not space else '多击+空格'
        tally[tag] += 1
        rows.append((i, ch, tag, c, st, cf[ch]))
    return rows, tally


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=1500)
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args()

    entries = load_entries(DICT_S)
    codes, word_codes, prefix = build(entries)
    freq = kmopt.load_freq()
    rank, cf = char_rank(freq)
    top = rank[:args.top]

    one = chord.one_press_codes()
    rows, tally = analyze(top, codes, word_codes, prefix, cf, one)
    total = len(top)
    n1, n1s = tally['一击'], tally['一击+空格']
    nm, nms = tally['多击'], tally['多击+空格']
    nsel, dead = tally['选词'], tally['死码']
    free_sel = n1 + n1s + nm + nms
    press_sum = sum(r[4] for r in rows if r[4])
    reach = sum(1 for r in rows if r[4])
    print('前 %d 常用单字：一击上屏 %d（%.1f%%）／一击+空格 %d／两次并击 %d／'
          '两次并击+空格 %d／需选词 %d／死码 %d'
          % (total, n1, 100 * n1 / total, n1s, nm, nms, nsel, dead))
    print('一次并击即出 %.1f%%；免选词 %.1f%%；平均 %.2f 击'
          % (100 * (n1 + n1s) / total, 100 * free_sel / total,
             press_sum / max(reach, 1)))

    # 一击槽位盘点（只看被「单字」占着的槽；被词语占的另算）
    one_auto = [c for c in codes if c in one and tier(c, codes, prefix) == 'auto']
    one_cjk = [c for c in one_auto
               if len(codes[c][0]) == 1 and is_cjk(codes[c][0])]
    word_slots = [c for c in one_auto if len(codes[c][0]) > 1]
    used = {r[3] for r in rows if r[2] == '一击'}
    outside = [(c, codes[c][0]) for c in one_cjk if c not in used]

    if args.no_write:
        return

    L = []
    A = L.append
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    A('# 空明码-宏版S：常用单字上屏成本\n')
    A('> 生成时间：%s　脚本：`tools/km_char_onehit.py`　词库：`kongmingmas.dict.yaml`\n' % now)
    A('## 1. 结论\n')
    A('**前 %d 常用单字中，%d 个字一击上屏（%.1f%%）；连同「一击+空格」的 %d 个，'
      '共 %d 个字一次并击就能出（%.1f%%）。**\n'
      % (total, n1, 100 * n1 / total, n1s, n1 + n1s, 100 * (n1 + n1s) / total))
    A('| 输入方式 | 字数 | 占比 |')
    A('| :--- | ---: | ---: |')
    A('| 一击上屏（双手同时并击一次，打完即出） | **%d** | **%.1f%%** |'
      % (n1, 100 * n1 / total))
    A('| 一击 + 空格（同码有更长候选，按空格上屏） | %d | %.1f%% |'
      % (n1s, 100 * n1s / total))
    A('| 两次并击上屏 | %d | %.1f%% |' % (nm, 100 * nm / total))
    A('| 两次并击 + 空格 | %d | %.1f%% |' % (nms, 100 * nms / total))
    A('| 合计：免选词 | **%d** | **%.1f%%** |' % (free_sel, 100 * free_sel / total))
    A('| 打完还要翻候选 | %d | %.1f%% |' % (nsel, 100 * nsel / total))
    if dead:
        A('| 最短码含 `/`，S 版打不出（只能补全后选词） | %d | %.1f%% |'
          % (dead, 100 * dead / total))
    A('')
    A('| 范围 | 一击上屏 | 覆盖率 | 一击（含+空格） | 免选词 | 覆盖率 |')
    A('| :--- | ---: | ---: | ---: | ---: | ---: |')
    for n in (100, 300, 500, 800, 1000, 1500):
        if n > total:
            break
        a = sum(1 for r in rows[:n] if r[2] == '一击')
        b = sum(1 for r in rows[:n] if r[2] in ('一击', '一击+空格'))
        c = sum(1 for r in rows[:n] if r[2] not in ('选词', '死码'))
        A('| 前 %d 字 | %d | %.1f%% | %d | %d | %.1f%% |'
          % (n, a, 100 * a / n, b, c, 100 * c / n))
    A('')
    A('## 2. 口径\n')
    A('- **一次并击 = 双手同时按下**：左手出一个码元、右手出一个码元，一次最多 2 个码元'
      '（algebra 末尾 `xform/^\\S{3,}$//` 会清掉 3 个以上的组合）。')
    A('- 每个码元都有左手式与右手式两种按法，例如 `R = e+t 或 y+i`、`G = d+g 或 h+k`、'
      '`Y = w+t 或 y+o`、`0 = asdf`（仅左手式）。')
    A('- 所以 `RG` = 左手 `e+t` ＋ 右手 `h+k` **同时**按下 = **1 击**，词库键正是 `RG`；'
      '「先 e+t 再 d+g」得到 `R=G=`，反而打不出 `RG`。同理 `0f`（`asdf` ＋ `j`）、'
      '`0Y`（`asdf` ＋ `y+o`）、`*c`（`r+g` ＋ `,`）都是一击。')
    A('- 单手单键 / 键+空格 同击带标记：`d=`、`=d`、`d_=`、`=_d`，都是 1 击。')
    A('- 4 码元码（`R<GG`）需要两次并击 = 2 击。')
    A('- 自动上屏 = **零延伸**（不是任何更长码的前缀）且 **唯一候选**；'
      '有延伸的码按一下空格即可上屏，不算选词。')
    A('- 「常用」按 Rime 官方语料 `essay.txt` 的单字词频排序。')
    A('- 击数由 `tools/km_chord_model.py` 模拟 `chord_composer.algebra` 算出：'
      '先用 algebra 反推每个码元的左右手按键集合，枚举「左右手各挑一种 ＋ 是否带空格」的全部组合'
      '（得到 %d 个可达码），再对词条码做分段最少击数。\n' % len(one))

    A('## 3. 一击上屏的 %d 个字\n' % n1)
    A('| # | 字 | 码 | 词频 | # | 字 | 码 | 词频 | # | 字 | 码 | 词频 |')
    A('| ---: | :---: | :---: | ---: | ---: | :---: | :---: | ---: |'
      ' ---: | :---: | :---: | ---: |')
    hit = [r for r in rows if r[2] == '一击']
    per = (len(hit) + 2) // 3
    for i in range(per):
        cells = []
        for k in range(3):
            idx = i + k * per
            if idx < len(hit):
                j, ch, tag, code, st, f = hit[idx]
                cells.append('%d | %s | `%s` | %s' % (j, ch, code, format(f, ',')))
            else:
                cells.append(' |  |  ')
        A('| ' + ' | '.join(cells) + ' |')
    A('')

    A('## 4. 一击 + 空格的 %d 个字\n' % n1s)
    A('一次并击就出码，但同码还有更长的候选，按一下空格上屏。\n')
    A('| # | 字 | 码 | 词频 | # | 字 | 码 | 词频 |')
    A('| ---: | :---: | :---: | ---: | ---: | :---: | :---: | ---: |')
    hit2 = [r for r in rows if r[2] == '一击+空格']
    per = (len(hit2) + 1) // 2
    for i in range(per):
        cells = []
        for k in range(2):
            idx = i + k * per
            if idx < len(hit2):
                j, ch, tag, code, st, f = hit2[idx]
                cells.append('%d | %s | `%s` | %s' % (j, ch, code, format(f, ',')))
            else:
                cells.append(' |  |  ')
        A('| ' + ' | '.join(cells) + ' |')
    A('')

    A('## 5. 仍需两次并击的字（前 60）\n')
    A('| # | 字 | 码 | 击数 | 空格 | 词频 |')
    A('| ---: | :---: | :---: | ---: | :---: | ---: |')
    for j, ch, tag, code, st, f in [r for r in rows if r[2] in ('多击', '多击+空格')][:60]:
        A('| %d | %s | `%s` | %d | %s | %s |'
          % (j, ch, code, st, '需要' if tag.endswith('空格') else '不要', format(f, ',')))
    A('')

    A('## 6. 槽位盘点\n')
    A('- 全库一击码（可达且零延伸唯一）%d 个：被单字占 %d 个，被词语占 %d 个。'
      % (len(one_auto), len(one_cjk), len(word_slots)))
    A('- 前 %d 字占了其中 %d 个单字槽（%.0f%%），还剩 %d 个单字槽在榜单之外。'
      % (total, len(used), 100 * len(used) / max(len(one_cjk), 1),
         len(one_cjk) - len(used)))
    if outside:
        A('- 榜单外的单字槽：%s。'
          % '、'.join('`%s`=%s' % (c, w) for c, w in outside[:40]))
    if dead:
        names = [r[1] for r in rows if r[2] == '死码']
        A('- **最短码含 `/` 的 %d 个字**：S 版 algebra 有 `xlit|;,./|FDJG|`，'
          '`/` 永远被改写成 `G`，而没有任何规则会输出 `/`，所以这些码打不出来，'
          '只能靠 `enable_completion` 打前缀再选词。原版同样有这条 xlit，属历史遗留键。'
          '字表：%s。' % (dead, '、'.join(names[:40])))
    A('')

    open(REPORT, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('报告已写入 %s' % REPORT)


if __name__ == '__main__':
    main()
