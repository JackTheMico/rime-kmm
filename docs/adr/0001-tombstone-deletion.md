# 使用墓碑标记（Tombstone）实现词库条目删除

## Context
RIME 词库文件可能达到数十兆字节（如 `kongmingma.dict.yaml` 包含逾 150 万行）。条目在内存中以 `EntryRef` 数组形式按顺序存储，`code_index` 与 `word_index` 等索引均直接记录数组下标。如果使用 `Vec::remove` 进行物理删除，会导致后续百万级下标全部前移，触发全量哈希表重新索引，造成 TUI 界面显著卡顿。

## Decision
我们决定采用墓碑标记（Tombstone）软删除机制：
1. 删除条目时，将其在 `EntryRef` 中标记为墓碑（或通过位图/集合记录），从 `code_index`、`word_index`、`pinyin_index` 及 `single_char_map` 中精确剔除对应下标（O(1) 复杂度）。
2. 在后台异步落盘（`write_to_disk`）时，统一遍历过滤掉已标记墓碑的条目，完成物理写出。

## Consequences
- 删除操作在百万级词库中保持 0 延迟、O(1) 实时响应，完全杜绝 TUI 掉帧。
- 保证了写盘时的文件整洁性与规范性，与原生 Rime 词库完全兼容。
