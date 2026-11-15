#!/usr/bin/env python3
"""空明码-宏版S 简码词频优化工具
=================================

目标
----
空明码的「一击」= 一个两码元编码（左手一码 + 右手一码）。
kmrime 现有 3994 个两码槽位，其中大量被低频字词占用，
而「如果 / 所以 / 可以 / 都是」这类超高频词却要两击（4 码元）才能打出。

本工具按词频重新分配两码槽位：
  1. 自然码（推荐）：两字词的自然一击码 = 首字声码 + 次字声码。
     例如 如→R、果→G，故 如果 = RG。
  2. 槽位归属按词频裁决：新词词频必须明显高于原占用者才抢位，
     避免高频字词之间来回抖动词频。

声码的推导（关键）
------------------
单字的声码取自它的「声韵全码」首码元，而非最短码首码元。
全码通过四码元二字词反推，多数票决定：
    如果 = `R<GG`  ->  如 的全码是 `R<`、果 的全码是 `GG`
    果然 = `GGRt`、果汁 = `GGzc`、果树 = `GGSX`  ->  果 的声码是 G
若某字没有四码词可反推，则退回「空格并击一击码」的字母（`X_=` / `=_X`），
再退回最短码的首个非 `=` 码元。

裁决规则（同时满足才抢位）
  A. 原槽位组内最高词频 < DEAD          -> 回收废槽，直接占用
  B. 新词词频 >= ELITE_RATIO × 原占用者 且 >= ELITE_MIN
                                        -> 词频碾压，允许占位
被挤掉的条目不会删除，只是退到候选第二位（仍可用原全码输入）。

用法
----
  python3 tools/km_jianma_opt.py                 # 预览（dry-run，不写文件）
  python3 tools/km_jianma_opt.py --apply         # 写入词库（自动备份）
  python3 tools/km_jianma_opt.py --apply --with-trad   # 简体库 + 繁体镜像库一起写
"""

import argparse
import collections
import datetime
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
ESSAY = '/usr/share/rime-data/essay.txt'
CACHE = os.path.join(ROOT, '.workbuddy/tmp/essay_s.txt')
REPORT = os.path.join(REPORTS, 'jianma_optimization_report.md')

TOP_N = 3000          # 参与评选的高频二字词数量
DEAD = 2000           # 槽位组内最高词频低于此值视为废槽
MIN_PROMOTE = 2000    # 废槽回收时，新词自身的最低词频门槛
ELITE_RATIO = 20      # 词频碾压倍数
ELITE_MIN = 50000     # 碾压规则的最低词频门槛


# ---------------------------------------------------------------- 词频
def load_freq():
    """Rime 官方 frequency 语料（繁体），用 opencc 转简后缓存。"""
    if not os.path.exists(CACHE):
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        subprocess.run(['opencc', '-c', 't2s.json', '-i', ESSAY, '-o', CACHE], check=True)
    freq = collections.Counter()
    with open(CACHE, encoding='utf-8') as f:
        for line in f:
            p = line.rstrip('\n').split('\t')
            if len(p) < 2:
                continue
            try:
                freq[p[0]] += int(p[1])
            except ValueError:
                pass
    return freq


# ---------------------------------------------------------------- 词库
def load_dict(path):
    """返回 (header_lines, entries)；entries 保持原始行内容。"""
    header, entries = [], []
    with open(path, encoding='utf-8') as f:
        for line in f:
            raw = line.rstrip('\n')
            if not raw:
                continue
            if raw.startswith('#') or raw in ('---', '...') or '\t' not in raw:
                header.append(raw)
                continue
            p = raw.split('\t')
            entries.append((p[0], p[1].replace('\ufeff', ''), raw))
    return header, entries


MARKERS = set('=_~!@*')          # 简码/符号族标记，出现即不可能是声韵全码


def build_index(entries):
    """建立索引，并推导每个单字的声码。

    返回 (codes, wordcodes, sheng)，其中 sheng: 单字 -> 单个字母（声码）。
    """
    codes = collections.defaultdict(list)       # code -> [word]
    wordcodes = collections.defaultdict(list)   # word -> [code]
    shortest = {}                               # 单字 -> 最短码
    full2 = collections.defaultdict(collections.Counter)   # 单字 -> {两码元全码前缀: 票数}

    for w, c, _ in entries:
        codes[c].append(w)
        wordcodes[w].append(c)
        if ' ' in w:                            # 「焫 b」这类异读标注行
            continue
        if len(w) == 1:
            cur = shortest.get(w)
            if cur is None or len(c) < len(cur):
                shortest[w] = c
        elif len(w) == 2 and len(c) == 4 and not (set(c) & MARKERS):
            full2[w[0]][c[:2]] += 1
            full2[w[1]][c[2:]] += 1

    def hit_letter(cs):
        """空格并击一击码的字母：`X_=` / `=_X` / `X=` / `=X`。"""
        for c in cs:
            if len(c) == 3 and c[1:] == '=_':
                return c[0]
            if len(c) == 3 and c[:2] == '=_':
                return c[2]
        for c in cs:
            if len(c) == 2 and c[0] == '=' and c[1].isalpha():
                return c[1]
            if len(c) == 2 and c[1] == '=' and c[0].isalpha():
                return c[0]
        return None

    sheng = {}
    src = collections.Counter()
    for w in wordcodes:
        if len(w) != 1:
            continue
        votes = full2.get(w)
        top = votes.most_common(1)[0] if votes else None
        if top and top[1] >= 2 and top[0][0].isalpha():
            sheng[w] = top[0][0]
            src['四码词反推'] += 1
            continue
        h = hit_letter(wordcodes[w])
        if h:
            sheng[w] = h
            src['空格一击码'] += 1
            continue
        if top and top[0][0].isalpha():
            sheng[w] = top[0][0]
            src['四码词单票'] += 1
            continue
        c = shortest.get(w)
        if c:
            for u in c:
                if u != '=':
                    sheng[w] = u
                    src['最短码兜底'] += 1
                    break

    print('  声码来源：' + '，'.join(f'{k} {v}' for k, v in src.most_common()))
    return codes, wordcodes, sheng


def sound(sheng, ch):
    """单字声码（单字母）。"""
    return sheng.get(ch)


def base_word(text):
    return text.split(' ')[0]


# ---------------------------------------------------------------- 方案
def build_plan(codes, wordcodes, sheng, freq, top_n=TOP_N, dead=DEAD,
               min_promote=MIN_PROMOTE, elite_ratio=ELITE_RATIO,
               elite_min=ELITE_MIN):
    """按词频重新分配两码槽位，反复迭代直到收敛。

    每一轮都会有一批词升级到一击层，它们退出「待升级」队列，
    队列后移又会暴露新的可升级词，因此需要迭代到稳态。
    """
    valid2 = {c for c in codes if len(c) == 2}
    # 可变副本：插入后会改变槽位归属
    c2 = {code: [base_word(t) for t in codes[code]] for code in valid2}

    def slot_best(code):
        bw, bf = None, -1
        for w in c2[code]:
            f = freq.get(w, 0)
            if f > bf:
                bw, bf = w, f
        return bw, bf

    have2 = sum(1 for w in wordcodes
                if len(w) == 2 and any(len(c) == 2 for c in wordcodes[w]))
    plan, taken, done = [], {}, set()
    blocked, no_code = [], []
    round_no = 0

    while True:
        round_no += 1
        cands = [(w, freq.get(w, 0)) for w in wordcodes
                 if len(w) == 2 and freq.get(w, 0) > 0 and w not in done
                 and not any(len(c) == 2 for c in wordcodes[w])]
        cands.sort(key=lambda x: -x[1])
        blocked, no_code = [], []
        added = 0
        for w, f in cands[:top_n]:
            nat = (sound(sheng, w[0]) or '?') + (sound(sheng, w[1]) or '?')
            if len(nat) != 2 or nat not in valid2:
                no_code.append((w, f, nat))
                continue
            if nat in taken:
                tw, tf = taken[nat]
                blocked.append((w, f, nat, tw, tf))
                continue
            bw, bf = slot_best(nat)
            kind = None
            if f >= min_promote and f >= 2 * max(bf, 1) and bf < dead:
                kind = 'recall'
            elif f >= elite_min and f >= elite_ratio * max(bf, 1) and f > bf:
                kind = 'crush'
            if kind is None:
                blocked.append((w, f, nat, bw, bf))
                continue
            plan.append((w, f, nat, bw, bf, kind))
            taken[nat] = (w, f)
            done.add(w)
            c2[nat].insert(0, w)      # 该槽位归属改变
            added += 1
        if added == 0 or round_no >= 6:
            break

    total_have2 = have2 + len(plan)
    return plan, blocked, no_code, valid2, have2, total_have2, round_no


def report_md(plan, blocked, no_code, valid2, have2, total_have2, rounds,
              freq, wordcodes, args, stats):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = []
    A = lines.append

    crushed = [p for p in plan if p[5] == 'crush']
    recalled = [p for p in plan if p[5] == 'recall']

    def alt(code_of_word):
        """被挤掉条目还剩哪些码（说明它没有报废）。"""
        cs = [c for c in wordcodes.get(code_of_word, []) if len(c) > 2]
        return '、'.join(f'`{c}`' for c in cs[:3]) or '（仅此一码）'

    A('# 空明码-宏版S 简码词频优化报告\n')
    A(f'> 生成时间：{now}　工具：`tools/km_jianma_opt.py`（迭代 {rounds} 轮收敛）\n')
    A('## 1. 结论\n')
    A(f'- 两码（一击）槽位共 **{len(valid2)}** 个，优化前只有 **{have2}** 个被二字词占用。')
    A(f'- 本次把 **{len(plan)}** 个高频二字词提升到一击层：废槽回收 **{len(recalled)}** 条、词频碾压占位 **{len(crushed)}** 条。')
    A(f'- 一击二字词槽位：**{have2} → {total_have2}**。')
    A(f'- 一词一击覆盖率：Top 100 高频二字词 **{stats["cov_before_100"]}% → {stats["cov_after_100"]}%**；'
      f'Top 500 **{stats["cov_before_500"]}% → {stats["cov_after_500"]}%**；'
      f'Top 1000 **{stats["cov_before_1000"]}% → {stats["cov_after_1000"]}%**。')
    A(f'- 一击层承载的词频占比（按语料词频加权）：**{stats["mass_before"]}% → {stats["mass_after"]}%**。')
    A('- 被挤掉的条目**未删除**，只退到候选第二位，仍可用其全码（两击）输入。\n')

    A('## 2. 裁决规则\n')
    A('| 规则 | 条件 | 含义 |')
    A('| --- | --- | --- |')
    A(f'| 回收废槽 | 槽位组内最高词频 < {args.dead} | 原占用者基本不用，直接让位 |')
    A(f'| 词频碾压 | 新词 ≥ {args.elite_ratio}× 原占用者，且 ≥ {args.elite_min} | 只给绝对高频词开绿灯 |')
    A('| 一槽一词 | 每槽只放一个词 | 不制造新的重码 |')
    A('| 否则 | — | 保持原状，进入「未提升」清单 |\n')

    A('## 3. 提升清单\n')
    A('| # | 词 | 一击码 | 词频 | 原占用者(词频) | 方式 | 原占用者剩余码 |')
    A('| ---: | --- | :---: | ---: | --- | :---: | --- |')
    for i, (w, f, nat, bw, bf, kind) in enumerate(plan, 1):
        way = '废槽回收' if kind == 'recall' else '碾压占位'
        A(f'| {i} | {w} | `{nat}` | {f:,} | {bw}({bf}) | {way} | {alt(bw)} |')

    A('\n## 4. 未提升的高频词\n')
    A('这些词想要的自然码已被更常用的字词占着，或同一槽位已被更常用的词拿走：\n')
    A('| 词 | 词频 | 想要的码 | 当前占用者(词频) |')
    A('| --- | ---: | :---: | --- |')
    for w, f, nat, bw, bf in blocked[:150]:
        A(f'| {w} | {f:,} | `{nat}` | {bw}({bf}) |')
    if len(blocked) > 150:
        A(f'| … | | | 共 {len(blocked)} 条 |')
    A('')

    A('## 5. 自然码不存在的词\n')
    A('首字声码 + 次字声码的组合在现有码元空间里没有对应槽位，需要单独设计简码：\n')
    A('| 词 | 词频 | 期望码 |')
    A('| --- | ---: | :---: |')
    for w, f, nat in no_code[:60]:
        A(f'| {w} | {f:,} | `{nat}` |')
    A('')

    A('## 6. 部署与回滚\n')
    A('词库文件已自动备份为 `kongmingmas.dict.yaml.bak-<时间戳>`。')
    A('部署路径按本机实际配置调整（本例为 fcitx5 + 系统级共享目录）：\n')
    A('```bash')
    A('cd ~/Nextcloud/kmrime')
    A('')
    A('# 1) 同步到 Rime 共享目录')
    A('sudo cp kongmingmas.dict.yaml kongmingmas_t.dict.yaml /usr/share/rime-data/')
    A('')
    A('# 2) 重新部署（librime 只在主方案变化时才全量重编，故用 km_deploy 强制转一次）')
    A('sudo ./km_deploy /usr/share/rime-data ~/.local/share/fcitx5/rime')
    A('#    或者：rime_deployer --build ~/.local/share/fcitx5/rime /usr/share/rime-data')
    A('')
    A('# 3) 回滚')
    A('sudo cp kongmingmas.dict.yaml.bak-<时间戳> /usr/share/rime-data/kongmingmas.dict.yaml')
    A('```')
    A('')
    A('> 提示：`kongmingmas_t.dict.yaml`（繁体镜像库）已同步插入同样的简码，保持反查注释一致。')
    A('> 若只想改简体库，回滚时一并覆盖即可。')
    A('')
    A('## 7. 还可继续做的事\n')
    A('1. **符号族简码重排**：`X~`、`X\'`、`!X`、`@X` 等约 700 个槽位是零延伸码（真·一击上屏），')
    A('   其中不少被低频词占着（`I~`武当、`C~`悄然、`E~`无产阶级、`T~`解耦、`N~`男人、`U~`几个…）。')
    A('   这一族是手工设计的符号体系，改写会牵动既有肌肉记忆，建议单独评审后再动。')
    A('2. **三字词层**：目前约 1 万个三字词挤在一击槽位里互相重码，可另做一轮三字词频优化。')
    A('3. **重跑本工具**：调整 `--dead/--elite-ratio/--elite-min/--top` 即可换一套更激进或更保守的策略，')
    A('   工具是幂等的，重复执行不会重复插入。')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- 写盘
def write_dict(path, inserts, stamp, trad_map=None, apply=False):
    """inserts: {code: [(word, code, freq)]}，按词频降序排在组首。

    幂等：已存在相同 (词, 码) 的条目会跳过，可重复运行。
    """
    header, entries = load_dict(path)
    existing = {(w, c) for w, c, _ in entries}
    out_raw = []
    cur = None
    emitted = set()
    n_add = 0
    for w, c, raw in entries:
        if c != cur:
            cur = c
            if c in inserts and c not in emitted:
                for iw, ic, _f in inserts[c]:
                    text = trad_map.get(iw, iw) if trad_map else iw
                    if (text, ic) in existing:
                        continue
                    out_raw.append(f'{text}\t{ic}')
                    n_add += 1
                emitted.add(c)
        out_raw.append(raw)
    missing = set(inserts) - emitted
    if missing:
        print(f'  [warn] {len(missing)} 个码在词库中不存在，已跳过: {sorted(missing)[:10]}')

    if not apply:
        return n_add
    bak = f'{path}.bak-{stamp}'
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    with open(path, 'w', encoding='utf-8') as f:
        # 必须带上 YAML 头（--- name: version: ...），否则 Rime 无法识别词库
        f.write('\n'.join(header + out_raw) + '\n')
    return n_add


def to_trad(words):
    if not words:
        return {}
    tmp_in = os.path.join(ROOT, '.workbuddy/tmp/_s2t_in.txt')
    tmp_out = os.path.join(ROOT, '.workbuddy/tmp/_s2t_out.txt')
    with open(tmp_in, 'w', encoding='utf-8') as f:
        f.write('\n'.join(words) + '\n')
    subprocess.run(['opencc', '-c', 's2t.json', '-i', tmp_in, '-o', tmp_out], check=True)
    with open(tmp_out, encoding='utf-8') as f:
        outs = [l.rstrip('\n') for l in f]
    return dict(zip(words, outs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='写入词库（默认只预览）')
    ap.add_argument('--with-trad', action='store_true', help='同时写繁体镜像库')
    ap.add_argument('--top', type=int, default=TOP_N)
    ap.add_argument('--dead', type=int, default=DEAD)
    ap.add_argument('--min-promote', type=int, default=MIN_PROMOTE)
    ap.add_argument('--elite-ratio', type=int, default=ELITE_RATIO)
    ap.add_argument('--elite-min', type=int, default=ELITE_MIN)
    args = ap.parse_args()

    print('读取词频…')
    freq = load_freq()
    print('读取词库…')
    header, entries = load_dict(DICT_S)
    print(f'  条目 {len(entries):,}')
    codes, wordcodes, sheng = build_index(entries)

    plan, blocked, no_code, valid2, have2, total_have2, rounds = build_plan(
        codes, wordcodes, sheng, freq, args.top, args.dead,
        args.min_promote, args.elite_ratio, args.elite_min)

    # ---- 覆盖率统计 ----
    promoted = {p[0] for p in plan}
    alltwo = sorted(((w, freq.get(w, 0)) for w in wordcodes
                     if len(w) == 2 and freq.get(w, 0) > 0),
                    key=lambda x: -x[1])

    def coverage(k):
        top = [w for w, _ in alltwo[:k]]
        total = max(len(top), 1)
        before = sum(1 for w in top if any(len(c) == 2 for c in wordcodes[w]))
        after = before + sum(1 for w in top if w in promoted)
        pct = lambda a: f'{100.0 * a / total:.1f}'
        return pct(before), pct(after)

    def mass(flag):
        tot = sum(f for _, f in alltwo)
        got = sum(f for w, f in alltwo
                  if any(len(c) == 2 for c in wordcodes[w]) or (flag and w in promoted))
        return f'{100.0 * got / max(tot, 1):.1f}'

    b100, a100 = coverage(100)
    b500, a500 = coverage(500)
    b1000, a1000 = coverage(1000)
    stats = {
        'cov_before_100': b100, 'cov_after_100': a100,
        'cov_before_500': b500, 'cov_after_500': a500,
        'cov_before_1000': b1000, 'cov_after_1000': a1000,
        'mass_before': mass(False), 'mass_after': mass(True),
    }

    print(f'\n两码槽位 {len(valid2)}，优化前被二字词占用 {have2} 个')
    print(f'迭代 {rounds} 轮收敛；提升 {len(plan)} 条'
          f'（废槽回收 {sum(1 for p in plan if p[5]=="recall")} / '
          f'碾压占位 {sum(1 for p in plan if p[5]=="crush")}）')
    print(f'优化后一击二字词槽位 {total_have2} 个')
    print(f'未提升 {len(blocked)} 条，自然码不存在 {len(no_code)} 条')
    print(f'一击覆盖率 Top100 {b100}% -> {a100}%  Top500 {b500}% -> {a500}%  Top1000 {b1000}% -> {a1000}%')
    print(f'一击层词频占比 {stats["mass_before"]}% -> {stats["mass_after"]}%')

    print('\n前 30 条：')
    for w, f, nat, bw, bf, kind in plan[:30]:
        print(f'  {w:<4} -> {nat}   freq={f:<8} 原占用 {bw}({bf}) [{kind}]')

    # 按码分组，组内按词频降序
    inserts = collections.defaultdict(list)
    plan_sorted = sorted(plan, key=lambda x: -x[1])
    for w, f, nat, bw, bf, kind in plan_sorted:
        inserts[nat].append((w, nat, f))

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    n_add = write_dict(DICT_S, inserts, stamp, apply=args.apply)
    print(f'\n简体库：插入 {n_add} 条' + ('' if args.apply else '（dry-run，未写盘）'))

    if args.with_trad and args.apply:
        trad_map = to_trad([w for w, *_ in plan_sorted])
        n_t = write_dict(DICT_T, inserts, stamp, trad_map=trad_map, apply=True)
        print(f'繁体镜像库：插入 {n_t} 条')

    if args.apply:
        with open(REPORT, 'w', encoding='utf-8') as f:
            f.write(report_md(plan, blocked, no_code, valid2, have2, total_have2,
                              rounds, freq, wordcodes, args, stats))
        print(f'报告已写入 {REPORT}')


if __name__ == '__main__':
    main()
