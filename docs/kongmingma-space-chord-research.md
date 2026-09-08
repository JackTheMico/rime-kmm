# 空明码在 RIME 中实现“空格并击让一个键打出两个不同单字”可行性研究与实施报告

> **调研结论**：**完全可以实现！**
> 且可以通过 librime **原生内置的 `chord_composer` + 正则代数（`algebra`）+ 码表配置 100% 原生实现**，无需借助任何外部改键软件或 Lua 脚本。
> 本结论已通过本机的真实 librime 引擎编写 C 语言测试并完成验证。

---

## 1. 用户提问与原文档背景

### 1.1 说明文档中的原述
在《空明码说明文档20230726.doc》的 **第 1.1 节「一简上屏字」** 中，作者明确定义了 104 个一简字和 104 个带空格并击字：
> “一简上屏字是指打一个码元就上屏的字，即一击上屏字；将系统切换到中文录入状态后只用左手录入码元 a 即可打出‘啊’字，只用右手录入码元 n 即可打出‘你’。
> 请熟练掌握下面的一简字列表（**括号里面的字表示与空格并击输出的字，比如只打 a，输出‘啊’，a+空格 输出‘唉’**）：
> ...
> **注\* 非；中州韵/小狼豪/管须鼠 只支持左右单击一简，如为统一，可以不去用并击空格的一击字**”

### 1.2 为什么当年文档会写“不支持”？
1. **历史工具依赖**：空明码作者早期主要是在“速录宝”、“快录”等专用并击软件上开发，速录宝有专门的图形化勾选项“开启拇指并击”（文档第 2.3 节），并将空格作为独立的修饰键处理。
2. **早期 RIME Schema 移植不完整**：在为 RIME 编写 `kongmingma.schema.yaml` 时，作者/协作者（zhanghaozhecn）虽然在并击按键集合（`alphabet`）末尾加入了空格，但**并未在 `chord_composer/algebra` 中编写针对空格组合的重写规则**，同时词库 `kongmingma.dict.yaml` 也未收录这 104 个空格并击的专用编码，导致作者误认为 RIME 不具备此能力。

---

## 2. librime 源码级原理解析

深入查阅 librime 的源码（[`src/rime/gear/chord_composer.cc`](file:///home/jackwy/Nextcloud/kmrime/tools/rime_test_console.c) 及 [`src/rime/key_event.cc`](file:///tmp/key_event.cc)），librime 对空格作为并击键的支持是完全内置且经过特别考量的：

### 2.1 按键收集与排序
在 `chord_composer.cc` 中：
```cpp
// 1. 初始化时解析并击键集合
config->GetString("chord_composer/alphabet", &alphabet);
chording_keys_.Parse(alphabet);
```
在 `kongmingma.schema.yaml` 当前第 122 行中：
```yaml
chord_composer:
  alphabet: "qazwsxedcrfvtgbyhnujmik,ol.p;/'7890 "
```
`' '`（空格）位于 `alphabet` 序列的最后一位。

当用户同时按下某个键（如 `a`）与 `Space`（空格）时：
- `state_.PressKey('a')` 和 `state_.PressKey(' ')` 将两键加入当前并击缓冲；
- `SerializeChord()` 按照 `chording_keys_` 中的顺序重排并击键。由于 `a` 在前、空格在后，生成的按键序列为 `['a', ' ']`；
- `key_sequence.repr()` 输出序列化字符串 `"a "`。

### 2.2 独击空格与并击空格的区分
在 `chord_composer.cc` 的 `UpdateChord` 和 `FinishChord` 中：
```cpp
// UpdateChord 中专门判断单按空格：不显示并击提示框
if (chord.empty() || (chord.size() == 1 && chord.count(' ') > 0)) {
  ClearChord();
  return;
}
```
当按键全部释放（`key release`）触发 `FinishChord` 时：
1. **单按空格（未与其他键并击）**：
   - 序列化得到单个空格 `" "`。
   - `algebra` 不对其做任何替换，保留 `" "`。
   - 经 `engine_->ProcessKey` 发送：
     - 若当前**处于候选状态**（如反查拼音 `` `fa `` 正在选词），空格被后续的 `selector` 捕获，正常**选词上屏**；
     - 若当前**输入缓冲区为空**，所有处理器返回 `kNoop`，最终由 `engine_->CommitText(" ")` **直接上屏空格**。
2. **字母 + 空格并击（如 `a` + `Space`）**：
   - 序列化得到 `"a "`；
   - 经过 `chord_composer/algebra` 的规则处理（例如被替换为包含空格特征的编码，如 `a_=`）；
   - `FinishChord` 发送重写后的按键序列，触发 `speller` 和 `table_translator`；
   - 结合 `speller/auto_select: true`，直接精准自动上屏括号里的第二个单字（`唉`）！

---

## 3. 真实 librime 环境验证

我们在系统环境（Arch/CachyOS，librime 1.17.0）中构建了隔离的测试方案，进行了严格的按键流实测（测试代码位于 `/tmp/verify_test_space.c`）。

### 3.1 测试配置
在 Schema 中增加规则：
```yaml
speller:
  auto_select: true
  alphabet: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_="

chord_composer:
  alphabet: "qazwsxedcrfvtgbyhnujmik,ol.p;/'7890 "
  algebra:
    - xform/^([qwertasdfgzxcvb]+) $/$1_=/   # 字母+空格并击：转为 $1_=
    - xform/^([qwertasdfgzxcvb]+)$/$1=/     # 单击字母：转为 $1=

translator:
  dictionary: test_space
```
在测试词库中加入条目：
```text
啊	a=
唉	a_=
```

### 3.2 实际运行输出
```text
=== Case 1: Press 'a' alone (单打 a) ===
a down               | preedit='[a=]' candidates=0
a up                 | preedit='' candidates=0 | COMMIT: '啊'

=== Case 2: Press 'a' + ' ' (a与空格并击) ===
a+space down         | preedit='[a_=]' candidates=0
a+space up           | preedit='' candidates=0 | COMMIT: '唉'

=== Case 3: Press ' ' (单打空格) ===
space down           | preedit='' candidates=0
space up             | preedit='' candidates=0 | COMMIT: ' '
```
**实测结果表明：**
- **单按 `a` 立即出 `啊`**；
- **`a` 与空格并击立即出 `唉`**；
- **单独击打空格立即上屏标准空格**，完全互不干扰，逻辑无缝闭环！

---

## 4. 空明码在 RIME 中的落地改造指南

若要在当前的 [`kongmingma.schema.yaml`](file:///home/jackwy/Nextcloud/kmrime/kongmingma.schema.yaml) 中完整实现文档所述的 104 对单字双出功能，只需执行以下两步改造：

### 第一步：在 `kongmingma.schema.yaml` 中配置 `algebra`
在 `chord_composer/algebra` 的单手单字定码规则前加入针对空格的规则：

```yaml
chord_composer:
  alphabet: "qazwsxedcrfvtgbyhnujmik,ol.p;/'7890 "
  algebra:
    # --- 1. 特殊三键扩展指法（原配置已有） ---
    ...
    # --- 2. 空格并击单字重写规则（新增部分） ---
    # 左手单键 + 空格（如 a+空格 -> a_=）
    - xform/^([qwertasdfgzxcvb]+) $/$1_=/
    # 右手单键 + 空格（如 n+空格 -> =_n）
    - xform/^([yuiophjklFnmDJG]+) $/=_$1/

    # --- 3. 普通单字定码（原配置已有） ---
    - xform/^([qwertasdfgzxcvb]+)$/$1=/
    - xform/^([yuiophjklFnmDJG])/=$1/
```

> **注**：在空明码中，除了 26 个单字母外，双手同侧相邻两键并击会生成大写字母（如左手 `q-w-` 映射为 `B`，右手 `o-p-` 映射为 `B`）。若也需支持这部分大写码元的空格并击，只需将空格规则移至单手相邻键合成大写字母的规则**之后**，统一匹配 `$1_=` 和 `=_$1` 即可。

### 第二步：在 `kongmingma.dict.yaml` 补充 104 个空格并击字
在词库中为带括号的 104 个单字补充对应的码位。例如：

| 按键/并击 | 原始单打编码 | 默认出字 | 空格并击编码 | 并击出字 |
| :--- | :--- | :--- | :--- | :--- |
| `a` | `a=` | 啊 | `a_=` | **唉** |
| `b` | `b=` | 把 | `b_=` | **病** |
| `n` (右手) | `=n` | 你 | `=_n` | **牛** |
| `c` | `c=` | 成 | `c_=` | **常** |
| `d` | `d=` | 地 | `d_=` | **带** |
| `j` (右手) | `=j` | 就 | `=_j` | **建** |
| `B` (左手qw) | `B=` | 变 | `B_=` | **币** |
| `B` (右手op) | `=B` | 保 | `=_B` | **必** |
| ... | ... | ... | ... | *(依说明文档补齐全部104字)* |

---

## 5. 使用体验与注意事项

1. **按键手感与松键时机（Key Release）**：
   RIME 的 `chord_composer` 默认在“所有按键松开时”或“首个按键松开时”（受 `finish_chord_on_first_key_release` 控制）结算并击。输入字母+空格时，双手同步按下并松开，字符即可瞬间上屏，手感极为轻快流畅。
2. **全键盘无冲（NKRO）**：
   大部分现代键盘对于 `字母键 + Space` 都具有极佳的防冲突特性，甚至优于同侧三字母并击。
3. **选重冲突解决**：
   由于一简字配置了 `speller/auto_select: true`，单字输入无需候选框等待，上屏后输入法立即回归空闲态。因此日常空格选词与空格并击在时序上完全隔离，不会造成按键冲突。
