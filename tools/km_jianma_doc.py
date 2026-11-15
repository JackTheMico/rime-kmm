#!/usr/bin/env python3
"""生成空明码-宏版S 的简码参考文档（Markdown + 可搜索 HTML + TSV）。

判定口径
--------
- **码长** = 码元数。词库里所有 ≤3 码元的条目都算「简码」。
- **零延伸** = 词库中不存在以该码为前缀的更长的码。
- **自动上屏** = 零延伸 且 该码只有唯一候选。
  依据: kongmingmas.schema.yaml 里 `auto_select: true`（无 auto_select_pattern），
  librime 仅在「候选唯一且输入无法继续延伸」时才自动顶屏。
- `=` 表示与空格同击，故含 `=` 的码虽然码元数 ≥2，击数更少；本表只报码元数，不做击数换算。

用法
----
    python3 tools/km_jianma_doc.py
产出（均在 docs/reference/）:
    jianma_reference.md     分节全量清单（可 git / 可纯文本查阅）
    jianma_reference.html   单文件可搜索表格（全量, 支持筛选/排序）
    jianma_reference.tsv    机器可读全量数据
"""
import collections
import datetime
import hashlib
import html
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
REPORTS = os.path.join(DOCS, 'reports')
REFERENCE = os.path.join(DOCS, 'reference')
for _d in (REPORTS, REFERENCE):
    os.makedirs(_d, exist_ok=True)
DICT_S = os.path.join(ROOT, 'kongmingmas.dict.yaml')
OUT_MD = os.path.join(REFERENCE, 'jianma_reference.md')
OUT_HTML = os.path.join(REFERENCE, 'jianma_reference.html')
OUT_TSV = os.path.join(REFERENCE, 'jianma_reference.tsv')

spec = importlib.util.spec_from_file_location(
    'kmopt', os.path.join(ROOT, 'tools/km_jianma_opt.py'))
kmopt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kmopt)

MAX_LEN = 3                      # 只收录 ≤3 码元的条目
DIGITS = set('0123456789')


# ---------------------------------------------------------------- 数据
def load_entries(path):
    out = []
    started = False
    with open(path, encoding='utf-8') as f:
        for line in f:
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
            out.append((p[0], p[1].replace('\ufeff', '')))
    return out


def family_of(code):
    """返回 (结构形态, 标记字符)。

    形态：纯字母（AB/ab）／前缀（!X、7D）／后缀（A0、X'）／空格并击（X=）。
    分开「前缀」和「后缀」很重要——`0Y` 与 `A0` 用的是同一个数字键，
    但一个是数字打头、一个是数字收尾，混在一起没法记忆。
    """
    if '=' in code:
        return '空格并击', '='
    if code.isalpha():
        return '纯字母', ''
    if not code[0].isalpha():
        return '前缀', code[0]
    if len(code) > 1 and not code[1].isalpha():
        return '后缀', code[1]
    return '其他', ''


PATTERN_ORDER = ['纯字母', '前缀', '后缀', '空格并击', '其他']

# 族的可读名（避免反引号等符号破坏 Markdown）
MARK_LABEL = {
    '=': '空格并击', "'": '撇号', '`': '反引号', '~': '波浪号', '!': '叹号',
    '@': 'at', '?': '问号', '*': '星号', '.': '句点', ',': '逗号', ':': '冒号',
    ';': '分号', '/': '斜杠', '<': '小于号', '_': '下划线',
}


def fam_title(pattern, marker):
    """族标题，如「前缀 !X（叹号）」、『后缀 X\'（撇号）』。"""
    if pattern == '纯字母':
        return '纯字母（AB / ab / Ab）'
    if pattern == '空格并击':
        return '空格并击（X= / =X）'
    if pattern == '其他':
        return '其他'
    pat = '{}X'.format(marker) if pattern == '前缀' else 'X{}'.format(marker)
    lab = MARK_LABEL.get(marker)
    return '%s「%s」%s' % (pattern, pat, '（%s）' % lab if lab else '')


# 码内字符排序：大写 < 小写 < 数字 < 符号
_CHAR_RANK = {}
for _i, _ch in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    _CHAR_RANK[_ch] = (_i, 0)
for _i, _ch in enumerate('abcdefghijklmnopqrstuvwxyz'):
    _CHAR_RANK[_ch] = (_i, 1)
for _i, _ch in enumerate('0123456789'):
    _CHAR_RANK[_ch] = (_i, 2)


def code_key(code):
    return [_CHAR_RANK.get(ch, (ord(ch), 3)) for ch in code]


def sort_codes(rows):
    return sorted(rows, key=lambda r: code_key(r['code']))


def group_families(rs):
    """把一组行按（形态, 标记）聚合，按 PATTERN_ORDER 输出。"""
    d = collections.defaultdict(list)
    for r in rs:
        d[(r['pattern'], r['marker'])].append(r)
    out = []
    for pat in PATTERN_ORDER:
        keys = [k for k in d if k[0] == pat]
        keys.sort(key=lambda k: code_key(k[1]) if k[1] else [])
        for k in keys:
            out.append((k, sort_codes(d[k])))
    return out


def build():
    freq = kmopt.load_freq()
    entries = load_entries(DICT_S)
    codes = collections.defaultdict(list)
    space_entries = 0
    for w, c in entries:
        if ' ' in w:                    # 「字 + 空格 + 后缀」类条目不是独立词条
            if len(c) <= MAX_LEN:
                space_entries += 1
            continue
        if len(c) <= MAX_LEN:
            codes[c].append(w)
    for c in codes:
        codes[c].sort(key=lambda w: -freq.get(w, 0))

    all_codes = collections.defaultdict(list)
    for w, c in entries:
        if ' ' not in w:
            all_codes[c].append(w)
    prefix = set()
    for c in all_codes:
        for i in range(1, len(c)):
            prefix.add(c[:i])

    rows = []
    for c in sorted(codes):
        ws = codes[c]
        zero = c not in prefix
        tier = 'auto' if (zero and len(ws) == 1) else ('zero' if zero else 'ext')
        pat, mark = family_of(c)
        rows.append({
            'code': c,
            'tier': tier,
            'pattern': pat,
            'marker': mark,
            'words': [(w, freq.get(w, 0)) for w in ws],
        })
    return rows, prefix, freq, len(entries), space_entries


# ---------------------------------------------------------------- Markdown
TIER_NAME = {'auto': '一击上屏（零延伸 + 唯一候选）',
             'zero': '零延伸 · 多候选（需选择）',
             'ext': '有延伸（需按空格/继续输入）'}
TIER_SHORT = {'auto': '上屏', 'zero': '多选', 'ext': '延伸'}
tier_mark = TIER_SHORT


def md_table(rows, show_cand=False):
    out = ['| 码 | 词 | 词频 |' + (' 同码候选 |' if show_cand else '')]
    out.append('| :---: | :--- | ---: |' + (' :---: |' if show_cand else ''))
    for r in rows:
        w, f = r['words'][0]
        extra = ''
        if show_cand:
            n = len(r['words'])
            more = '、'.join(x for x, _ in r['words'][1:4])
            extra = (' %d%s |' % (n, '（' + more + '…）' if more else '')) if n > 1 else ' 1 |'
        out.append('| `%s` | %s | %s |%s' % (r['code'], w, format(f, ','), extra))
    return out


def gen_md(rows, freq, total_entries, space_entries=0):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(DICT_S, 'rb') as f:
        digest = hashlib.md5(f.read()).hexdigest()
    lines = []
    A = lines.append

    by_tier = collections.defaultdict(list)
    for r in rows:
        by_tier[r['tier']].append(r)
    auto = by_tier['auto']
    zero = by_tier['zero']
    ext = by_tier['ext']
    multi = [r for r in rows if len(r['words'][0][0]) >= 3]

    def split_len(rs):
        d = collections.defaultdict(list)
        for r in rs:
            d[len(r['code'])].append(r)
        return d

    auto_len, zero_len, ext_len = split_len(auto), split_len(zero), split_len(ext)

    A('# 空明码-宏版S 简码参考\n')
    A('> 生成时间：%s　词库：`kongmingmas.dict.yaml`（%s 条，md5 `%s`）\n'
      % (now, format(total_entries, ','), digest[:12]))
    A('> 本表由 `tools/km_jianma_doc.py` 从词库直接导出，与部署到 XSIME 的词库同源。'
      '完整可搜索版见 `jianma_reference.html`。\n')

    A('## 1. 速览\n')
    total = sum(len(r['words']) for r in rows)
    A('| 档位 | 码数 | 词条数 | 说明 |')
    A('| :--- | ---: | ---: | :--- |')
    A('| 一击上屏 | %s | %s | 零延伸 + 唯一候选，打完即上屏，不弹候选 |'
      % (format(len(auto), ','), format(sum(len(r['words']) for r in auto), ',')))
    A('| 零延伸·多候选 | %s | %s | 打不出更长的码，但要选词 |'
      % (format(len(zero), ','), format(sum(len(r['words']) for r in zero), ',')))
    A('| 有延伸 | %s | %s | 存在更长的码，需按空格或继续打 |'
      % (format(len(ext), ','), format(sum(len(r['words']) for r in ext), ',')))
    A('| **合计** | **%s** | **%s** | 词库中所有 ≤%d 码元的独立词条 |\n'
      % (format(len(rows), ','), format(total, ','), MAX_LEN))

    A('按码长分布：\n')
    A('| 码长 | 一击上屏 | 多候选 | 有延伸 |')
    A('| :---: | ---: | ---: | ---: |')
    for L in range(1, MAX_LEN + 1):
        A('| %d 码元 | %d | %d | %d |'
          % (L, len(auto_len[L]), len(zero_len[L]), len(ext_len[L])))
    A('')

    A('## 2. 怎么读这张表\n')
    A('- **自动上屏**的判定是「零延伸 + 唯一候选」两条同时满足。'
      '`kongmingmas.schema.yaml` 用的是 `auto_select: true` 且没有 `auto_select_pattern`，'
      'librime 只在候选唯一、且输入无法再延伸时才顶屏。')
    A('- **`=` 代表与空格同击**。所以 `地` 的 `a=` 虽然写出来是 2 个码元，实际是一次并击。'
      '本表只报码元数，不做击数换算，免得出错。')
    A('- 每个码下的**第一行候选**就是实际首选词；多候选码在 HTML 版里能看到全部同码词。')
    A('- 词频来自 `essay.txt`（经 opencc 转简）。词频为 0 表示语料未收录，不代表罕见。\n')

    A('---\n')
    A('## 3. 一击上屏（%s 个码）\n' % format(len(auto), ','))
    A('这一档是性价比最高的：打完最后一键立刻上屏，不弹候选框。\n')
    seq = 0
    for L in range(1, MAX_LEN + 1):
        part = auto_len[L]
        if not part:
            continue
        seq += 1
        title = {1: '单键码', 2: '两码码', 3: '三码码'}[L]
        A('### 3.%d %s（%s）\n' % (seq, title, format(len(part), ',')))
        # 按「纯字母 / 前缀式 / 后缀式」分族，便于按范式记忆
        fams = group_families(part)
        if len(fams) > 1:
            A('族一览：' + '　'.join('%s %d' % (fam_title(*k), len(v))
                                   for k, v in fams) + '\n')
        for (pat, mark), rs in fams:
            if len(fams) > 1:
                A('#### %s（%d）\n' % (fam_title(pat, mark), len(rs)))
            lines.extend(md_table(rs))
            A('')

    A('## 4. 零延伸 · 多候选（%s 个码）\n' % format(len(zero), ','))
    A('打完不会自动上屏，因为同码有多个词。列出首选与同码词数，便于判断值不值得记。\n')
    seq = 0
    for L in range(1, MAX_LEN + 1):
        part = zero_len[L]
        if not part:
            continue
        seq += 1
        A('### 4.%d %d 码元（%d）\n' % (seq, L, len(part)))
        lines.extend(md_table(sort_codes(part), show_cand=True))
        A('')

    A('## 5. 有延伸的两码 / 三码（%s 个码）\n' % format(len(ext), ','))
    A('这些码之后还有更长的码，因此必须按空格（或继续打）才上屏。'
      '按首码分组，每组内按码序。\n')
    groups = collections.OrderedDict()
    for r in sort_codes(ext):
        key = r['code'][0]
        groups.setdefault(key, []).append(r)
    for key, rs in groups.items():
        A('### 5.%s 首码「%s」（%d）\n' % (key.upper() if key.isalpha() else key, key, len(rs)))
        lines.extend(md_table(rs, show_cand=True))
        A('')

    multi_words = [(r['code'], w, f, r['tier'])
                   for r in rows for w, f in r['words'] if len(w) >= 3]
    multi_words.sort(key=lambda x: (-x[2], code_key(x[0])))
    A('## 6. 多字词简码（三字及以上，%d 个词）\n' % len(multi_words))
    A('三字词及以上在简码层里很少，但多是高频口号式短语，按词频降序，值得优先记。\n')
    A('| 码 | 词 | 词频 | 档位 |')
    A('| :---: | :--- | ---: | :---: |')
    for code, w, f, tier in multi_words:
        A('| `%s` | %s | %s | %s |' % (code, w, format(f, ','), TIER_SHORT[tier]))
    A('')

    A('## 7. 单字速查\n')
    A('把所有有简码路径的单字按字列出，按该字最高词频降序。用于「这个字怎么打最快」。\n')
    per_char = collections.defaultdict(list)
    for r in rows:
        for w, f in r['words']:
            if len(w) == 1:
                per_char[w].append((r['code'], r['tier'], f))
    A('共 %d 个单字带有 ≤%d 码元的路径。\n' % (len(per_char), MAX_LEN))
    A('| 字 | 简码路径（码 / 档位） |')
    A('| :---: | :--- |')
    for ch in sorted(per_char, key=lambda c: (-max(f for _, _, f in per_char[c]), c)):
        paths = '　'.join('`%s`(%s)' % (c, tier_mark[t]) for c, t, _ in
                          sorted(per_char[ch], key=lambda x: (len(x[0]), -x[2])))
        A('| %s | %s |' % (ch, paths))
    A('')

    A('## 8. 附录\n')
    A('- 重新生成：`python3 tools/km_jianma_doc.py`')
    A('- 部署到 XSIME：`python3 tools/km_deploy_xsime.py`')
    A('- 全量可搜索版：`jianma_reference.html`（含全部同码候选，支持按码/词/词频筛选排序）')
    A('- 机器可读：`jianma_reference.tsv`')
    A('- 另有一层不在本表内：词库中 %s 条「字 + 空格 + 键」形式的后缀构造条目'
      '（如 `蔼 p`），那是单字的精确化/后缀输入层，不属于词语简码。\n'
      % format(space_entries, ','))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- HTML
HTML_TMPL = '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>空明码-宏版S 简码参考</title>
<style>
:root{--bg:#0f1216;--panel:#171c22;--line:#262d36;--fg:#e6edf3;--dim:#8b98a5;
--auto:#5ec26a;--zero:#d8a13a;--ext:#6a8caf;--hot:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 "Noto Sans CJK SC","Source Han Sans SC",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:rgba(15,18,22,.96);
border-bottom:1px solid var(--line);padding:14px 18px;backdrop-filter:blur(8px)}
h1{margin:0 0 6px;font-size:17px;font-weight:600;letter-spacing:.3px}
.meta{color:var(--dim);font-size:12px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;align-items:center}
input[type=search]{flex:1 1 260px;min-width:200px;padding:8px 11px;border-radius:8px;
border:1px solid var(--line);background:var(--panel);color:var(--fg);font-size:14px;outline:none}
input[type=search]:focus{border-color:#3d7dd6}
button{padding:6px 12px;border-radius:8px;border:1px solid var(--line);
background:var(--panel);color:var(--fg);cursor:pointer;font-size:13px}
button.on{border-color:#3d7dd6;background:#1c2a3d;color:#9fc6ff}
.count{color:var(--dim);font-size:12px;margin-left:auto}
main{padding:0 18px 60px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}
th{position:sticky;top:106px;background:var(--panel);text-align:left;
padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer;
font-weight:600;color:var(--dim);white-space:nowrap;user-select:none}
th:hover{color:var(--fg)}
td{padding:6px 10px;border-bottom:1px solid rgba(38,45,54,.6);vertical-align:top}
tr:hover td{background:rgba(61,125,214,.07)}
code{font-family:"JetBrains Mono",ui-monospace,monospace;background:#1d242c;
padding:1px 6px;border-radius:5px;color:#9fc6ff;font-size:13px}
.w{font-size:14px}
.f{color:var(--dim);font-variant-numeric:tabular-nums}
.t-auto{color:var(--auto)}.t-zero{color:var(--zero)}.t-ext{color:var(--ext)}
.cands{color:var(--dim);font-size:12px}
.hot{color:var(--hot)}
footer{color:var(--dim);font-size:12px;padding:0 18px 30px}
</style></head><body>
<header>
  <h1>空明码-宏版S 简码参考</h1>
  <div class="meta" id="meta"></div>
  <div class="bar">
    <input type="search" id="q" placeholder="搜索：码 / 词（支持正则，如 ^R 或 如果）">
    <button data-tier="all" class="on">全部</button>
    <button data-tier="auto">一击上屏</button>
    <button data-tier="zero">多候选</button>
    <button data-tier="ext">有延伸</button>
    <span class="count" id="count"></span>
  </div>
</header>
<main>
<table><thead><tr>
  <th data-sort="code">码</th><th data-sort="word">词</th>
  <th data-sort="freq">词频</th><th data-sort="tier">档位</th>
  <th data-sort="n">同码候选</th>
</tr></thead><tbody id="tb"></tbody></table>
</main>
<footer>词频来自 essay.txt（opencc 转简）；词频 0 表示语料未收录。`=` 表示与空格同击。</footer>
<script>
const DATA = __DATA__;
const TIER = {auto:'一击上屏', zero:'多候选', ext:'有延伸'};
const q = document.getElementById('q'), tb = document.getElementById('tb'),
      cnt = document.getElementById('count'), metaEl = document.getElementById('meta');
metaEl.textContent = DATA.meta;

let rows = DATA.rows, tier = 'all', sortKey = 'code', sortDir = 1;
const fmt = n => n ? n.toLocaleString('en-US') : '0';

function cands(w){
  if (w.length <= 1) return '';
  return w.slice(1, 5).map(x => x[0]).join('、') + (w.length > 5 ? ' 等' : '');
}
function render(){
  const re = q.value.trim() ? new RegExp(q.value.trim()) : null;
  const out = rows.filter(r => (tier === 'all' || r.tier === tier) &&
    (!re || re.test(r.code) || r.words.some(w => re.test(w[0]))));
  out.sort((a,b) => {
    let x, y;
    if (sortKey === 'code') { x = a.code; y = b.code; }
    else if (sortKey === 'word') { x = a.words[0][0]; y = b.words[0][0]; }
    else if (sortKey === 'freq') { x = a.words[0][1]; y = b.words[0][1]; }
    else if (sortKey === 'n') { x = a.words.length; y = b.words.length; }
    else { x = a.tier; y = b.tier; }
    if (x === y) return a.code < b.code ? -1 : 1;
    return (x < y ? -1 : 1) * sortDir;
  });
  tb.innerHTML = out.map(r => {
    const w = r.words[0];
    return `<tr><td><code>${r.code}</code></td>
<td class="w">${w[0]}</td>
<td class="f">${fmt(w[1])}</td>
<td class="t-${r.tier}">${TIER[r.tier]}</td>
<td class="cands">${r.words.length > 1 ? r.words.length + '：' + cands(r.words) : '1'}</td></tr>`;
  }).join('');
  cnt.textContent = out.length.toLocaleString('en-US') + ' / ' +
                    rows.length.toLocaleString('en-US') + ' 条';
}
document.querySelectorAll('button[data-tier]').forEach(b => b.onclick = () => {
  document.querySelectorAll('button[data-tier]').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); tier = b.dataset.tier; render();
});
document.querySelectorAll('th[data-sort]').forEach(th => th.onclick = () => {
  const k = th.dataset.sort;
  if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
  render();
});
q.oninput = render;
render();
</script></body></html>
'''


def gen_html(rows, total_entries):
    payload = []
    for r in rows:
        payload.append({'code': r['code'], 'tier': r['tier'],
                        'words': [[w, f] for w, f in r['words']]})
    with open(DICT_S, 'rb') as f:
        digest = hashlib.md5(f.read()).hexdigest()
    meta = ('词库 %s 条 · md5 %s · 收录 ≤%d 码元条目 %s 个码 / %s 条词'
            % (format(total_entries, ','), digest[:12], MAX_LEN,
               format(len(rows), ','), format(sum(len(r['words']) for r in rows), ',')))
    data = json.dumps({'meta': meta, 'rows': payload}, ensure_ascii=False,
                      separators=(',', ':'))
    return HTML_TMPL.replace('__DATA__', data)


def gen_tsv(rows):
    out = ['code\ttier\tword\tfreq\tcandidates\tpattern\tmarker']
    for r in rows:
        for w, f in r['words']:
            out.append('%s\t%s\t%s\t%d\t%d\t%s\t%s'
                       % (r['code'], r['tier'], w, f, len(r['words']),
                          r['pattern'], r['marker']))
    return '\n'.join(out) + '\n'


def main():
    print('读取词库与词频…')
    rows, prefix, freq, total_entries, space_entries = build()
    print('  简码码位 %s 个，词条 %s 条（另有 %s 条后缀构造已排除）'
          % (format(len(rows), ','), format(sum(len(r['words']) for r in rows), ','),
             format(space_entries, ',')))
    t = collections.Counter(r['tier'] for r in rows)
    print('  一击上屏 %d / 多候选 %d / 有延伸 %d' % (t['auto'], t['zero'], t['ext']))

    for path, content in ((OUT_MD, gen_md(rows, freq, total_entries, space_entries)),
                          (OUT_HTML, gen_html(rows, total_entries)),
                          (OUT_TSV, gen_tsv(rows))):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print('  写入 %-28s %s' % (os.path.basename(path),
                                   format(os.path.getsize(path), ',')))


if __name__ == '__main__':
    main()
