# 空明码·拼音反查 实施方案（已验证可用的最终版）

> 目标：空明码（并击方案）里输入 `` ` `` + 无声调全拼，列出汉字候选，注释列显示其空明码编码。
> **最终采用：librime 内置组件方案，零 Lua 依赖。已用真实 librime 引擎（rime_api 会话测试）验证通过。**

## 最终方案（已落地到 `kongmingma.schema.yaml`）

```yaml
schema:
  dependencies:
    - luna_pinyin          # 反查输入侧词典（部署时自动编译）

engine:
  filters:
    - simplifier
    - uniquifier
    - simplifier@reverse_t2s   # 反查候选繁→简
  processors:
    - ascii_composer
    - recognizer            # 捕获 ` 起始（内置，天然在 chord_composer 之前）
    - chord_composer
    ...                     # 与原来相同，无需任何 Lua bypass
  translators:
    - punct_translator
    - reverse_lookup_translator
    - table_translator
    ...

switches:
  - name: simplification    # 必须！simplifier 的选项默认是关的
    reset: 1
    states: [ 反查繁体, 反查简体 ]

reverse_lookup:
  dictionary: luna_pinyin
  prefix: "`"
  tips: "〔拼音反查〕"
  comment_format:
    - xform/~//

reverse_t2s:                # luna_pinyin 是繁体词典，选中后要上屏简体
  opencc_config: t2s.json
  tags: [ reverse_lookup ]
  tips: none

recognizer:
  patterns:
    reverse_lookup: "^`[a-z]*$"
```

另需两份配套文件：
- **`luna_pinyin.custom.yaml`**（本机必需）：本机 rime-data 缺 `key_binder/symbols` 预设，`luna_pinyin.schema.yaml` 的三个 `import_preset` 编译报错 → 依赖词典根本不构建、反查静默无候选。补丁把三个 `import_preset` 置空即可。
- **`opencc/t2s.json` + TS\*.ocd2**：从 `/usr/share/opencc/` 拷贝（librime 只在用户/共享数据的 opencc/ 目录找配置）。

## 工作原理（源码级，已验证）

1. `recognizer`（内置处理器，位于 chord_composer 之前）对模式首字符 `` ` `` `PushInput` 并 kAccepted——所以 `` ` `` 能进输入串，**不需要 Lua bypass**。
2. `chord_composer` 会把 a–z 当并击键吃掉（`ProcessChordingKey` 不看输入内容），**但松键时 `FinishChord` 把并击输出编码经 `engine_->ProcessKey` 重发**，此时 `sending_chord_=true` 使 chord_composer 放行 → `speller`（其 alphabet 含 a–z）把字母拼进输入串。
3. 输入串 `“`fa`”` 被 `matcher` 按 `recognizer/patterns` 打上 `reverse_lookup` 标签。
4. `reverse_lookup_translator` 用 luna_pinyin 查汉字（`prefix: "`"` 剥前缀），注释来自主码表 `build/kongmingma.reverse.bin`（部署自动构建）= 空明码。
5. `simplifier@reverse_t2s`（opencc t2s）把繁体候选转简体；注释列不受影响。

## 真实引擎验证结果（rime_api 会话模拟按键）

```
`fa        → 发(i.nt) 法(Fc) 伐(Ff;) …（简体 + 空明码注释）
`zhongguo  → 中国 …
`fa + 空格 → 上屏「发」 ✓
```

- 回归：正常并击输入路径未改动（仅删了本来就被跳过的死 Lua 引用）。
- 死引用报错清零（原来的 `helper`/`time_date` 每键报错，已从 kongmingma schema 移除；`date_translator` 保留，它在 rime.lua 有注册）。

## 已知限制

- **以 `` ` `` 开头的码位冲突**：` 是合法码元（jkl 并击 → `` ` ``）。凡「首码 `` ` `` + 后续纯字母」的编码会触发反查而非正常出字。这是 `` ` `` 前缀反查的固有权衡；若实际使用中冲突频繁，可把 `recognizer/patterns` 的前缀换掉或给反查加结尾符。
- 反查默认精确匹配音节（`enable_completion` 默认关），打全音节才出字，这是性能合理默认。
- 词组反查的注释列可能不完整（reverse.bin 只存了词组整体编码的一部分场景）。

## 繁体镜像修复（2026-09-07，重要）

**问题**：多字词反查注释大量为空（`我们(-)`、`中药(-)`、`敌方(-)`），尤其有简码的一击字词。

**根因（两层）**：

1. **luna_pinyin 是繁体词典**：反查候选文本是繁体（我們/中國/中藥/敵方），而 `reverse_lookup_translator` 的注释来自**主码表** `kongmingma(s).reverse.bin`（简体键）。繁体文本查简体键库 → 查不到 → 注释为空。简繁同形词（重要/地方/提防）恰好能查到，掩盖了问题。
2. **opencc 转换不改名**：用 `opencc -c s2t.json` 生成繁体镜像词典时，头部 `name:` 字段原样保留（仍是 `kongmingma`），导致 DictCompiler 把镜像词典与原词典编译产物混在一起（`kongmingma_t.reverse.bin` 与 `kongmingma.reverse.bin` md5 完全相同，实为简体库）。

**修复**（kongmingma 与 kongmingmas 都已打上）：

```yaml
schema:
  dependencies:
    - luna_pinyin
    - kongmingma_t            # 繁体镜像词典（新增）

reverse_lookup:
  ...
  target: kongmingma_t_rev    # 新增：注释查码指向繁体镜像

kongmingma_t_rev:             # librime 机制：target 作为 name_space，
  dictionary: kongmingma_t    # 读 <name_space>/dictionary 得到真实词典名
```

配套文件（每个方案一份，`name:` 字段必须是镜像名！）：
- `kongmingma_t.dict.yaml` / `kongmingmas_t.dict.yaml` —— `opencc -i <主>.dict.yaml -o <_t>.dict.yaml -c /usr/share/opencc/s2t.json` 生成后，**手工把头部 `name:` 改成 `<主>_t`**（第 1 行注释也顺手改，行尾是 CRLF，sed 时注意 `\r`）
- `kongmingma_t.schema.yaml` / `kongmingmas_t.schema.yaml` —— 最小 schema，仅 `translator/dictionary` 指向镜像词典，不用于输入

**librime 源码依据**（`reverse_lookup_translator.cc` + `reverse_lookup_dictionary.cc`）：
- `target` 的值不是词典名，而是 **Ticket 的 name_space**；组件用 `config->GetString(name_space + "/dictionary")` 解析真实词典名，解析失败返回 NULL。
- 注释在 `ReverseLookupTranslation::Peek()` 用候选**原文**（繁体）查目标库；simplifier 只改显示文本，不影响查码。

**验证结果（真实 librime 引擎）**：

```
kongmingma   `women    → 我们(Uw WqmF w3m=)          # 一击简码 Uw 正常显示
kongmingmas  `zhongguo → 中国(Uz ZgGG z5g=) 种过(ZqGJ) 种果(ZqGG)
```

## 排查记录（为什么前几版不生效）

1. 第一版（Lua 方案）：schema 引用 `*yoyo.*`，但 `lua/yoyo/*` 不存在 → RIME 对未知组件跳过 → 无 bypass → 字母被并击吃掉。
2. 第二版：组件本地化 + rime.lua 注册，但**未验证真实引擎**；LuaJIT 65536 常量上限等隐藏 bug 修复了，但始终缺真实反馈回路。
3. 第三版：搭建 rime_api C 测试程序，踩坑：`create_session` 前必须 `initialize()`（此前"会话创建失败"全是这个原因，与 Lua 无关）；`simplifier` 的 `simplification` 选项默认关，必须 `switches` 里 `reset: 1`。
4. 最终：改用纯内置组件方案（上述），根本不依赖 Lua 装载行为，最稳。

## 文件清单（最终）

- `kongmingma.schema.yaml` —— 反查补丁（见上）+ 繁体镜像 target（2026-09-07）
- `kongmingma_t.dict.yaml` / `kongmingma_t.schema.yaml` —— kongmingma 繁体镜像
- `kongmingmas.schema.yaml` —— 同一补丁已镜像（2026-09-07），真实引擎验证：`` `fa `` → 发(i.nt)/法(Fc)/伐(Ff;)、`` `zhongguo `` → 中国、空格上屏「发」；并顺手清掉了 helper/time_date 死引用。给其他并击 schema 套用时只需五处：`dependencies` 加 `luna_pinyin`、`switches` 加 `simplification`（reset: 1）、filters 加 `simplifier@reverse_t2s`、translators 加 `reverse_lookup_translator` 并删死 Lua 引用、顶层加 `reverse_lookup`/`reverse_t2s`/`recognizer.patterns.reverse_lookup` 三个块。**多字词注释为空时还需：镜像词典 + `target`（见上节）。**
- `kongmingmas_t.dict.yaml` / `kongmingmas_t.schema.yaml` —— kongmingmas 繁体镜像
- `luna_pinyin.custom.yaml` —— 修复预设缺失，让依赖词典可编译
- `opencc/t2s.json`、`opencc/TS*.ocd2`、`opencc/CJK_Compatibility_Ideographs.ocd2` —— 从 /usr/share/opencc 拷贝
- `tools/rime_test_console.c` —— 真实引擎测试器：`gcc -o rt tools/rime_test_console.c -lrime && ./rt <schema_id>`（不传参默认 kongmingma）
- 已删除：`lua/kongmingma/`（102MB Lua 分片数据，不再需要）

## 参考

- librime 源码：`gear/chord_composer.cc`（FinishChord 重发机制）、`gear/reverse_lookup_translator.cc`、`gear/simplifier.cc`（simplification 选项）、`service.cc`
- 数据：`/usr/share/rime-data/luna_pinyin.dict.yaml`、`build/kongmingma.reverse.bin`
