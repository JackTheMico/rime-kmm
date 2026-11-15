--[[
librime-lua 样例

调用方法：
在配方文件中作如下修改：
```
  engine:
    ...
    translators:
      ...
      - lua_translator@lua_function3
      - lua_translator@lua_function4
      ...
    filters:
      ...
      - lua_filter@lua_function1
      - lua_filter@lua_function2
      ...
```

其中各 `lua_function` 为在本文件所定义变量名。
--]]

--[[
本文件的后面是若干个例子，按照由简单到复杂的顺序示例了 librime-lua 的用法。
每个例子都被组织在 `lua` 目录下的单独文件中，打开对应文件可看到实现和注解。

各例可使用 `require` 引入。
如：
```
  foo = require("bar")
```
可认为是载入 `lua/bar.lua` 中的例子，并起名为 `foo`。
配方文件中的引用方法为：`...@foo`。

--]]


-- I. translators:

-- date_translator: 将 `date` 翻译为当前日期
-- 详见 `lua/date.lua`:
date_translator = require("date")

-- time_translator: 将 `time` 翻译为当前时间
-- 详见 `lua/time.lua`
time_translator = require("time")

-- number_translator: 将 `/` + 阿拉伯数字 翻译为大小写汉字
-- 详见 `lua/number.lua`
number_translator = require("number")


-- II. filters:

-- charset_filter: 滤除含 CJK 扩展汉字的候选项
-- charset_comment_filter: 为候选项加上其所属字符集的注释
-- 详见 `lua/charset.lua`
local charset = require("charset")
charset_filter = charset.filter
charset_comment_filter = charset.comment_filter

-- single_char_filter: 候选项重排序，使单字优先
-- 详见 `lua/single_char.lua`
single_char_filter = require("single_char")

-- reverse_lookup_filter: 依地球拼音为候选项加上带调拼音的注释
-- 详见 `lua/reverse.lua`
reverse_lookup_filter = require("reverse")

-- ext_gate: 扩展库开关（Ctrl+Alt+E 切换 ext_dict）。
-- 核心库由匿名 table_translator 提供（initial_quality 默认 0）；
-- 扩展库由 table_translator@ext 提供，其 initial_quality 设为 -1000，
-- 用这条分界线区分两者来源，只保留其中一侧：
--   ext_dict 关 -> 只留核心库候选；开 -> 只留扩展库（整库）候选。
-- 非码表来源的候选（标点、拼音反查、日期等）不受影响。
local EXT_QUALITY = -100
local TABLE_TYPES = { table = true, completion = true, user_table = true }
local function ext_gate_filter(input, env)
  local on = env.engine.context:get_option("ext_dict")
  for cand in input:iter() do
    local genuine = cand:get_genuine()
    if not TABLE_TYPES[genuine.type] or
        on == (genuine.quality <= EXT_QUALITY) then
      yield(cand)
    end
  end
end
ext_gate = ext_gate_filter
