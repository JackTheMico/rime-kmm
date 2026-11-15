#!/usr/bin/env python3
"""空明码-宏版S：回收「已有读音简码」词条的多余一击槽，转给更需要它的词与字。

起因
----
「知道」有 `zD`、「可以」有 `ky`，「如果」有 `RG` —— 这类由声码拼出来的码本身就能
一击出码，词条名下再挂一个 `0o` / `0b` / `0f`，对主人只是省一次空格，对别人却是
稀缺的「一击槽」。所以把它们摘下来重新分配。

判定
----
读音码 = 单字声码逐字拼接（大小写照抄），且该码确实挂在本词名下：

    如果 → RG      可以 → ky      知道 → zD      我们 → Wm
    单字 → 声码单键形态：X= / =X / X_= / =_X（大 → d=）

「多余的一击码」= 该词名下除读音码之外的其它一次并击可达码。

价值模型
--------
一次并击 = 1 个动作；成本 = 击数 + (要不要额外按空格/选词 ? 1 : 0)

    零延伸且唯一候选 → 打完即出，成本 = 击数
    有延伸 / 多候选   → 还要一次空格（或数字选词），成本 = 击数 + 1

    收益 = 新主人频次 ×（原成本 − 落槽后成本）
    代价 = 原主人频次 ×（失去该槽后的成本 − 现有成本）
    净   = 收益 − 代价，只做净为正的配对。

注意：摘下来的码如果本身还是更长码的前缀（如 `dW` 之于 `dWxx`），新主人仍要按空格，
只能算「省一动作」而不是「一击即出」——工具会分别标 clean / prefixed。

用法
----
    python3 tools/km_jianma_reclaim.py                      # 预览（不写盘）
    python3 tools/km_jianma_reclaim.py --apply --with-trad  # 写入简繁双库
    python3 tools/km_jianma_reclaim.py --word-share 0.75    # 词语多分一些槽
    python3 tools/km_jianma_reclaim.py --no-chars           # 不动单字的全码槽
    python3 tools/km_jianma_reclaim.py --priority value     # 纯按收益排（不按词先字后）
"""
import argparse
import collections
import datetime
import importlib.util
import os
import pickle
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
sys.path.insert(0, HERE)
import km_chord_model as chord  # noqa: E402

DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
DICT_T = os.path.join(ROOT, 'kongmingmas_t.dict.yaml')
REPORT = os.path.join(REPORTS, 'jianma_reclaim_report.md')

MIN_WORD_FREQ = 3000        # 参与再分配的词，词频下限
CHAR_TOP = 2000             # 参与再分配的单字，取字频前 N
CHAR_MIN_WORD = 1000        # 统计字频时只算词频≥此值的词（滤长尾噪声）
WORD_SHARE = 0.5            # 槽位给词语的比例（其余给单字）
DENY = {'回复日期'}          # 语料模板残留，词频不可信
KEEP_CODES = {'K`'}         # 空明码（方案名）


def load_kmopt():
    spec = importlib.util.spec_from_file_location('kmopt', os.path.join(HERE, 'km_jianma_opt.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


kmopt = load_kmopt()
ONE = chord.one_press_codes()


# ---------------------------------------------------------------- 索引
def build(entries):
    codes = collections.defaultdict(list)        # code -> [(word, raw)]
    word_codes = collections.defaultdict(list)   # word -> [code]
    for w, c, raw in entries:
        codes[c].append((w, raw))
        if ' ' not in w:
            word_codes[w].append(c)
    return codes, word_codes


def prefixes(code_set):
    p = set()
    for c in code_set:
        for i in range(1, len(c)):
            p.add(c[:i])
    return p


def tier(c, cnt, pref):
    """auto=零延伸唯一（打完即出）／zero=多候选／ext=有延伸。"""
    if c in pref:
        return 'ext'
    return 'auto' if cnt == 1 else 'zero'


def cost_of(c, cnt, pref):
    st = chord.strokes(c, ONE)
    if st >= 99:
        return 99
    return st if tier(c, cnt, pref) == 'auto' else st + 1


def cost_set(cs, cnt, pref):
    """cnt 是 {code: 候选数}；取该词名下最便宜的那个码。"""
    return min((cost_of(c, cnt.get(c, 0), pref) for c in cs), default=99)


# ---------------------------------------------------------------- 读音码
INIT_CACHE = os.path.join(ROOT, '.workbuddy/tmp/char_initials.pkl')
LUNA = '/usr/share/rime-data/luna_pinyin.dict.yaml'


def char_initials():
    """单字 → 拼音首字母。借 luna_pinyin 词库（繁），opencc 转简后按字建表。"""
    if os.path.exists(INIT_CACHE):
        with open(INIT_CACHE, 'rb') as f:
            return pickle.load(f)
    raw = {}
    with open(LUNA, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#') or '\t' not in line:
                continue
            p = line.rstrip('\n').split('\t')
            if len(p) < 2 or len(p[0]) != 1 or ' ' in p[1]:
                continue
            raw.setdefault(p[0], p[1][0].lower())
    chars = list(raw)
    tmp_in = os.path.join(ROOT, '.workbuddy/tmp/_luna_c_in.txt')
    tmp_out = os.path.join(ROOT, '.workbuddy/tmp/_luna_c_out.txt')
    os.makedirs(os.path.dirname(tmp_in), exist_ok=True)
    with open(tmp_in, 'w', encoding='utf-8') as f:
        f.write('\n'.join(chars) + '\n')
    subprocess.run(['opencc', '-c', 't2s.json', '-i', tmp_in, '-o', tmp_out], check=True)
    with open(tmp_out, encoding='utf-8') as f:
        simp = [l.rstrip('\n') for l in f]
    table = {}
    for t, s in zip(chars, simp):
        if len(s) == 1:
            table.setdefault(s, raw[t])
    with open(INIT_CACHE, 'wb') as f:
        pickle.dump(table, f)
    return table


def _case_variants(s, limit=16):
    """声码/首字母表里的大小写不可靠（`不` 记作 `B` 却打成 `=b`），逐位枚举大小写再比对。"""
    outs = ['']
    for ch in s:
        if ch.isalpha():
            outs = [o + c for o in outs for c in {ch.lower(), ch.upper()}]
        else:
            outs = [o + ch for o in outs]
    return outs[:limit]


def readable_codes(w, cs, sheng, init):
    """该词名下的「读音码」。

    两条路都算：拼音首字母串（`如果`→RG、`知道`→zD、`可以`→ky）
    与方案声码串（`都是`→Ds 这种以声码为准的）。单字取单键形态 X= / =X / X_= / =_X。
    """
    letters = [init.get(ch) for ch in w]
    shengs = [sheng.get(ch) for ch in w]
    out = set()
    for seq in (letters, shengs):
        if len(w) == 1:
            if not seq[0]:
                continue
            for v in _case_variants(seq[0]):
                for f in (v + '=', '=' + v, v + '_=', '=_' + v):
                    if f in cs:
                        out.add(f)
        else:
            if not all(seq):
                continue
            for v in _case_variants(''.join(seq)):
                if v in cs:
                    out.add(v)
    return sorted(out)


# ---------------------------------------------------------------- 语义族
SYMS = set(",.?!<;:/='`~@*_")


def family(c):
    """与 km_jianma_zero.family 一致：`X'` 记为 `'X`，`7a` 记为 `7X`。"""
    return f'X{c[1]}' if c[1] in SYMS else f'{c[0]}X'


def family_ok(code, w):
    """语义族守恒：`?X` 只收叠字，`@X` 三字，`*X` 四字。"""
    if len(code) != 2 or not (set(code) & SYMS):
        return True
    fam = family(code)
    if fam == '?X':
        return len(w) == 2 and w[0] == w[1]
    if fam == '@X':
        return len(w) == 3
    if fam == '*X':
        return len(w) == 4
    return True


# ---------------------------------------------------------------- 回收
def plan_reclaim(codes, word_codes, sheng, init, freq, with_chars=True, dedup=False):
    """返回可摘槽位：[{code, word, freq, mn, cost_now, cost_after, loss}]

    两个来源：

    1. **读音码冗余**（默认）：词已有读音简码（`ky`/`RG`/`zD`），名下再挂的一击码
       对主人只是省一次空格；
    2. **一词多槽**（`dedup=True`）：词已经有一击即出码（成本 1），其余一击码全是
       冗余，摘掉不增加任何成本（`loss = 0`）——纯赚。读音码不在此列（那是主人的
       主路径，也是当初 `--set` 留下的习惯）。
    """
    cnt = {c: len(v) for c, v in codes.items()}
    pref = prefixes(codes)
    out = []

    for w, cs in word_codes.items():
        if not all('\u4e00' <= ch <= '\u9fff' for ch in w):
            continue
        if ' ' in w or len(w) > 4 or w in DENY:
            continue
        if len(w) == 1 and not with_chars:
            continue
        mns = readable_codes(w, cs, sheng, init)
        now = cost_set(cs, cnt, pref)

        def emit(c, base):
            rest = [x for x in cs if x != c]
            after = cost_set(rest, cnt, pref)        # 只摘这一枚时的成本上界
            out.append({
                'code': c, 'word': w, 'freq': freq.get(w, 0),
                'mn': mns[0] if mns else '',
                'cost_now': now, 'cost_after': after,
                'loss': max(0, (after - base)) * freq.get(w, 0),
                'single': len(w) == 1,
            })

        # 1) 有读音码 → 额外的一击码是冗余
        if mns:
            for c in cs:
                if c in ONE and c not in mns and c not in KEEP_CODES:
                    emit(c, now)

        # 2) 已有一击即出码 → 其余一击码也是冗余（loss 恒为 0）
        #    注意必须留住那个成本 1 的码，它是主人现在的主路径
        if dedup and now == 1:
            best = [c for c in cs if c in ONE
                    and cost_of(c, cnt.get(c, 0), pref) == 1]
            for c in cs:
                if (c in ONE and c not in mns and c not in KEEP_CODES
                        and c not in best):
                    emit(c, 1)
    return out


# ---------------------------------------------------------------- 候选
def plan_targets(codes, word_codes, sheng, init, freq, char_freq, rank):
    cnt = {c: len(v) for c, v in codes.items()}
    pref = prefixes(codes)
    words, chars = [], []

    for w, cs in word_codes.items():
        if not all('\u4e00' <= ch <= '\u9fff' for ch in w):
            continue
        if ' ' in w or not (2 <= len(w) <= 4) or w in DENY:
            continue
        f = freq.get(w, 0)
        if f < MIN_WORD_FREQ:
            continue
        k = cost_set(cs, cnt, pref)
        if k <= 1 or k >= 99:
            continue
        # 二字词：已经有读音简码的视为「够用」，不再补槽（用户口径）
        if len(w) == 2 and readable_codes(w, cs, sheng, init):
            continue
        words.append({'word': w, 'freq': f, 'cost': k, 'codes': cs})
    words.sort(key=lambda r: -r['freq'] * (r['cost'] - 1))

    for i, ch in enumerate(rank[:CHAR_TOP], 1):
        cs = word_codes.get(ch, [])
        if not cs:
            continue
        k = cost_set(cs, cnt, pref)
        if k <= 1 or k >= 99:
            continue
        if readable_codes(ch, cs, sheng, init):   # 已有 X= 这类一击读音码
            continue
        chars.append({'word': ch, 'freq': char_freq[ch], 'cost': k,
                      'codes': cs, 'rank': i})
    chars.sort(key=lambda r: -r['freq'] * (r['cost'] - 1))
    return words, chars


# ---------------------------------------------------------------- 配对
def match(slots, words, chars, word_share=None, priority='words', force=False,
          force_codes=()):
    """按「代价最低的槽先出手」配对，每个槽挑当前最划算的候选。

    槽按原主人代价升序 → 便宜的先分配；每个槽先看词语（受配额约束），
    词语配额用完再给单字。同一槽内取「收益 − 代价」最大者，收益 ≤ 代价就不配。

    `force=True`   —— 全库硬换（严格执行「有读音码就不再占额外槽」）；
    `force_codes`  —— 只对列出的码硬换，其余照常按净收益判断（用户点名的槽）。
    """
    force_codes = set(force_codes)
    for s in slots:
        s['cost_new'] = 1 if s['clean'] else 2
        s['forced'] = force or s['code'] in force_codes

    order = sorted(range(len(slots)), key=lambda i: slots[i]['loss'])
    if priority == 'value':
        wq = len(slots)
    else:
        wq = int(round(len(slots) * (word_share if word_share is not None else WORD_SHARE)))
    wq = max(0, min(wq, len(slots)))

    used_w, used_c = set(), set()
    n_w = n_c = 0
    plan = []
    for idx in order:
        s = slots[idx]

        def best_of(arr, used):
            best, best_gain = None, 0
            for t in arr:
                if t['word'] in used:
                    continue
                if not family_ok(s['code'], t['word']):
                    continue
                gain = t['freq'] * (t['cost'] - s['cost_new'])
                if gain > best_gain:
                    best, best_gain = t, gain
            return best, best_gain

        pick, gain, kind = None, 0, ''
        if n_w < wq:
            pick, gain = best_of(words, used_w)
            kind = '词'
            if pick is not None and gain <= s['loss'] and not s['forced']:
                pick, gain = None, 0       # 词不划算就让给字
        if pick is None:
            pick, gain = best_of(chars, used_c)
            kind = '字'
            if pick is not None and gain <= s['loss'] and not s['forced']:
                pick, gain = None, 0
        if pick is None:
            continue
        if kind == '词':
            used_w.add(pick['word'])
            n_w += 1
        else:
            used_c.add(pick['word'])
            n_c += 1
        plan.append({'slot': s, 'target': pick, 'kind': kind,
                     'gain': gain, 'net': gain - s['loss']})
    plan.sort(key=lambda r: -r['net'])
    return plan


# ---------------------------------------------------------------- 写库
def rewrite(path, removals, additions, trad_map=None, apply=False, stamp=''):
    """removals: {(word, code)}；additions: [(word, code)]。保留 YAML 头。"""
    header, entries = kmopt.load_dict(path)

    # 插入锚点：同首码元的最后一条（跳过将被删的行，否则锚点落空会丢掉新条目）
    last_of_head = {}
    for i, (w, c, raw) in enumerate(entries):
        if (w, c) in removals:
            continue
        last_of_head[c[0]] = i
    anchor = last_of_head.get('0', len(entries) - 1)

    by_anchor = collections.defaultdict(list)
    for w, c in additions:
        text = trad_map.get(w, w) if trad_map else w
        pos = last_of_head.get(c[0], anchor)
        by_anchor[pos].append('%s\t%s' % (text, c))

    out, n_rm, n_add = [], 0, 0
    for i, (w, c, raw) in enumerate(entries):
        if (w, c) in removals:
            n_rm += 1
        else:
            out.append(raw)
        if i in by_anchor:
            out.extend(by_anchor[i])
            n_add += len(by_anchor[i])

    if n_add != len(additions):
        raise RuntimeError('新增条目数不符：计划 %d，实际 %d（锚点落空？）'
                           % (len(additions), n_add))

    if apply:
        bak = '%s.bak-%s' % (path, stamp)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(header + out) + '\n')
    return n_rm, n_add


# ---------------------------------------------------------------- 报告
def report(plan, slots, unassigned, args, stats, share_tbl):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    L = []
    A = L.append
    total_net = sum(p['net'] for p in plan)
    n_word = sum(1 for p in plan if p['kind'] == '词')
    n_char = len(plan) - n_word

    A('# 空明码-宏版S：冗余一击槽回收与再分配\n')
    A('> 生成时间：%s　工具：`tools/km_jianma_reclaim.py`　词库：`kongmingmas.dict.yaml`\n' % now)
    A('## 1. 结论\n')
    A('- **起因**：`知道` 有 `zD`、`可以` 有 `ky` 这类读音简码，词条名下再挂 `0o`/`0b` 只是省一次空格；'
      '而另有一批高频词连个一击码都没有。')
    A('- **回收 %d 个槽**：多字词 %d 个、单字 %d 个（单字的声韵全码本来就慢，读音码 `X=` 才是主路径）。'
      % (len(plan), sum(1 for p in plan if len(p['slot']['word']) > 1),
         sum(1 for p in plan if len(p['slot']['word']) == 1)))
    A('- **再分配 %d 个槽**：词语 %d 个、单字 %d 个；净省 **%s 个动作**（按语料频次折算）。'
      % (len(plan), n_word, n_char, f'{total_net:,}'))
    A('- 另有 %d 个槽没找到划算的接手人（详见第 5 节）。' % len(unassigned))
    A('')
    A('## 2. 判定与价值模型\n')
    A('**读音码** = 拼音首字母逐字拼接（大小写照抄）或方案声码串，且该码确实挂在本词名下：'
      '`如果`→`RG`、`可以`→`ky`、`知道`→`zD`、`都是`→`Ds`；单字取单键形态 `d=`（大）、'
      '`=b`（不）、`=R`（如）。')
    A('')
    A('**多余一击码** = 该词名下除读音码外，其它一次并击可达的码（`0o`、`8Z`、`9e`、`dW` …）。')
    A('')
    A('**成本** = 击数 +（要不要额外按空格/选词 ? 1 : 0）：零延伸唯一候选 = 打完即出，'
      '有延伸或多候选要多按一次空格。')
    A('')
    A('> 摘下来的码若本身仍是更长码的前缀（如 `dW` 之于 `dWxx`），新主人照样要按空格，'
      '只算「省一个动作」；工具对此标 `prefixed`，不按「一击即出」算收益。')
    A('')
    A('| 判据 | 条件 |')
    A('| --- | --- |')
    A('| 回收 | 词条有读音一击码，且名下另有一击码 |')
    A('| 不动标点/直出槽 | `K\\`` 等保留码跳过 |')
    A('| 候选-词 | 无读音简码、成本 ≥ 2 动作、词频 ≥ %s' % f'{args.min_word_freq:,}')
    A('| 候选-字 | 无 `X=` 类读音码、成本 ≥ 2 动作、字频前 %d' % args.char_top)
    A('| 配对 | 净收益 = 新主人收益 − 原主人代价 > 0，贪心取最大 |')
    A('| 分槽 | %s |' % ('纯按净收益' if args.priority == 'value'
                         else '词语 %.0f%%、单字 %.0f%%' % (100 * args.word_share,
                                                            100 * (1 - args.word_share))))
    A('')
    A('## 3. 回收清单（%d 槽）\n' % len(slots))
    A('| # | 码 | 原主人 | 频次 | 读音码 | 现在成本 | 摘掉后 | 代价 | 槽况 |')
    A('| ---: | :---: | --- | ---: | :---: | ---: | ---: | ---: | :--- |')
    for i, s in enumerate(sorted(slots, key=lambda x: -x['freq']), 1):
        A('| %d | `%s` | %s | %s | `%s` | %d | %d | %s | %s |'
          % (i, s['code'], s['word'], f'{s["freq"]:,}', s['mn'],
             s['cost_now'], s['cost_after'], f'{s["loss"]:,}',
             'clean（可一击即出）' if s['clean'] else 'prefixed（仍要空格）'))
    A('')
    A('## 4. 再分配清单（%d 槽，净省 %s）\n' % (len(plan), f'{total_net:,}'))
    A('| # | 码 | 新主人 | 类型 | 频次 | 原成本 | 落槽后 | 收益 | 原主人代价 | 净 |')
    A('| ---: | :---: | --- | :---: | ---: | ---: | ---: | ---: | ---: | ---: |')
    for i, p in enumerate(plan, 1):
        s, t = p['slot'], p['target']
        net_str = f'{p["net"]:,}'
        if p['net'] <= 0:
            net_str += ' ⚠强制'
        A('| %d | `%s` | **%s** | %s | %s | %d | %d | %s | %s | %s |'
          % (i, s['code'], t['word'], p['kind'], f'{t["freq"]:,}', t['cost'],
             s['cost_new'], f'{p["gain"]:,}', f'{s["loss"]:,}', net_str))
    A('')
    A('## 5. 未收回的槽（%d）\n' % len(unassigned))
    if unassigned:
        A('这些槽的主人同样有读音码，但**没人接得住**：原主人词频太高，换给谁都是净亏'
          '（例如 `0a`=所以 53 万，而剩下候选的收益都低于这个数）。所以保留原样。')
        A('')
        A('要严格执行「有读音码就不再占额外槽」，加 `--force` 重跑。')
        A('')
        A('| 码 | 原主人 | 频次 | 读音码 | 收回代价 | 原因 |')
        A('| :---: | --- | ---: | :---: | ---: | --- |')
        for s in sorted(unassigned, key=lambda x: -x['loss'])[:60]:
            A('| `%s` | %s | %s | `%s` | %s | %s |'
              % (s['code'], s['word'], f'{s["freq"]:,}', s['mn'], f'{s["loss"]:,}',
                 '仍是更长码的前缀，接手人只能省一次空格' if not s['clean']
                 else '候选池里没有收益更高的接手人'))
    else:
        A('无。')
    A('')
    A('## 6. 分槽比例敏感性\n')
    A('| 词语占比 | 槽位（词/字） | 净省动作 |')
    A('| :---: | :---: | ---: |')
    for label, nw, nc, net in share_tbl:
        A('| %s | %d / %d | %s |' % (label, nw, nc, f'{net:,}'))
    A('')
    A('## 7. 部署与回滚\n')
    A('```bash')
    A('python3 tools/km_deploy_xsime.py          # 部署')
    A('cp kongmingmas.dict.yaml.bak-%s kongmingmas.dict.yaml   # 回滚' % stats['stamp'])
    A('```')
    A('')
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--with-trad', action='store_true')
    ap.add_argument('--no-chars', action='store_true', help='不回收单字的全码槽')
    ap.add_argument('--priority', choices=['words', 'value'], default='words',
                    help='words=词语优先分槽；value=纯按净收益')
    ap.add_argument('--word-share', type=float, default=WORD_SHARE)
    ap.add_argument('--min-word-freq', type=int, default=MIN_WORD_FREQ)
    ap.add_argument('--char-top', type=int, default=CHAR_TOP)
    ap.add_argument('--force', action='store_true',
                    help='收益 ≤ 代价时也硬换（严格执行「有读音码就不再占额外槽」）')
    ap.add_argument('--force-codes', default='',
                    help='点名强制回收的码，逗号分隔（只影响这些槽，其余仍按净收益判断）')
    ap.add_argument('--dedup', action='store_true',
                    help='额外回收「一词多槽」：词已有一击即出码时，其余一击码无损交出（loss=0）')
    ap.add_argument('--report-suffix', default='',
                    help='报告文件名后缀（如 dedup → jianma_reclaim_report_dedup.md）')
    ap.add_argument('--char-min-word', type=int, default=CHAR_MIN_WORD,
                    help='统计字频时只算词频≥此值的词，滤掉词表长尾（如地名）噪声')
    args = ap.parse_args()
    force_codes = {c.strip() for c in args.force_codes.split(',') if c.strip()}

    print('读取词库…')
    header, entries = kmopt.load_dict(DICT_S)
    codes, word_codes = build(entries)
    sheng = kmopt.build_index(entries)[2]
    print('读取词频与拼音首字母…')
    freq = kmopt.load_freq()
    init = char_initials()

    char_freq = collections.Counter()
    for w, f in freq.items():
        if f < args.char_min_word:
            continue
        for ch in w:
            char_freq[ch] += f
    rank = [c for c, _ in char_freq.most_common(6000)]

    print('挑选可回收槽…')
    raw_slots = plan_reclaim(codes, word_codes, sheng, init, freq,
                             not args.no_chars, args.dedup)

    # 模拟摘除，判断哪些槽真的空出来、哪些仍是别人的前缀
    rm = {(s['word'], s['code']) for s in raw_slots}
    cnt_after = collections.Counter()
    remain = set()
    for c, lst in codes.items():
        n = sum(1 for w, _ in lst if (w, c) not in rm)
        if n:
            cnt_after[c] = n
            remain.add(c)
    pref_after = prefixes(remain)

    slots = []
    for s in raw_slots:
        if cnt_after.get(s['code'], 0) != 0:
            continue                       # 槽里还有别人，不摘
        s['clean'] = s['code'] not in pref_after
        # 精确重算代价：摘掉这一个码后，主人用剩下最好的码
        rest = [c for c in word_codes[s['word']] if c != s['code']]
        s['cost_after'] = cost_set(rest, cnt_after, pref_after)
        s['loss'] = max(0, s['cost_after'] - s['cost_now']) * s['freq']
        slots.append(s)

    print('挑选候选…')
    words, chars = plan_targets(codes, word_codes, sheng, init, freq, char_freq, rank)
    print('  可回收 %d 槽；候选 词 %d / 字 %d' % (len(slots), len(words), len(chars)))

    plan = match(slots, words, chars, args.word_share, args.priority, args.force,
                 force_codes)
    used = {id(p['slot']) for p in plan}
    unassigned = [s for s in slots if id(s) not in used]

    # 敏感性：同一个候选池，不同分槽比例
    share_tbl = []
    for sh in (0.0, 0.25, 0.5, 0.75, 1.0):
        p = match(slots, words, chars, sh, 'words', False, force_codes)
        share_tbl.append(('%d%%' % (100 * sh),
                          sum(1 for x in p if x['kind'] == '词'),
                          sum(1 for x in p if x['kind'] == '字'),
                          sum(x['net'] for x in p)))
    pv = match(slots, words, chars, None, 'value', False, force_codes)
    share_tbl.append(('纯按收益',
                      sum(1 for x in pv if x['kind'] == '词'),
                      sum(1 for x in pv if x['kind'] == '字'),
                      sum(x['net'] for x in pv)))

    n_word = sum(1 for p in plan if p['kind'] == '词')
    n_char = len(plan) - n_word
    net = sum(p['net'] for p in plan)
    print('计划：收回 %d 槽（未分配的 %d 个保持原样），再分配 词 %d / 字 %d，净省 %s'
          % (len(plan), len(unassigned), n_word, n_char, f'{net:,}'))

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    trad_map = None
    if args.with_trad:
        allw = [p['slot']['word'] for p in plan] + [p['target']['word'] for p in plan]
        trad_map = kmopt.to_trad(sorted(set(allw)))

    n_rm = n_add = 0
    n_rm_t = n_add_t = 0
    if args.apply:
        removals = {(p['slot']['word'], p['slot']['code']) for p in plan}
        additions = [(p['target']['word'], p['slot']['code']) for p in plan]
        # 护栏：目标不得已经拥有该码；一个码不得发两次
        seen = set()
        for w, c in additions:
            assert c not in seen, '码重复分配：%s' % c
            assert c not in word_codes.get(w, []), '目标已有该码：%s %s' % (w, c)
            seen.add(c)
        n_rm, n_add = rewrite(DICT_S, removals, additions, apply=True, stamp=stamp)
        print('简体库：删 %d 行，增 %d 行' % (n_rm, n_add))
        if args.with_trad:
            rm_t = {(trad_map.get(w, w), c) for w, c in removals}
            add_t = [(trad_map.get(w, w), c) for w, c in additions]
            n_rm_t, n_add_t = rewrite(DICT_T, rm_t, add_t, apply=True, stamp=stamp)
            print('繁体库：删 %d 行，增 %d 行' % (n_rm_t, n_add_t))
        rpt = REPORT if not args.report_suffix else \
            REPORT.replace('.md', '_%s.md' % args.report_suffix)
        with open(rpt, 'w', encoding='utf-8') as f:
            f.write(report(plan, slots, unassigned, args,
                           {'stamp': stamp, 'n_rm': n_rm, 'n_add': n_add}, share_tbl))
        print('报告已写入 %s' % rpt)
    else:
        print('\n预览（未写盘）：')
        for p in plan[:25]:
            s, t = p['slot'], p['target']
            print('  %-5s %s(%s) → %s 净 %s'
                  % (s['code'], s['word'], f'{s["freq"]:,}', t['word'], f'{p["net"]:,}'))
        if len(plan) > 25:
            print('  …共 %d 条' % len(plan))
        print('\n分槽比例敏感性：')
        for label, nw, nc, net in share_tbl:
            print('  词语 %-6s 槽 %2d/%2d  净省 %s' % (label, nw, nc, f'{net:,}'))


if __name__ == '__main__':
    main()
