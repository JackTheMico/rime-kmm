# kmrime / km-tui

RIME 词库管理与检索交互系统，支持空明码形码及通用 Rime 词库的编码检索、候选调序、新增与删除。

## Language

**条目 (Entry)**:
词库中的单行数据单元，由「字词」与「编码」二元组构成。
_Avoid_: 行, 记录, 数据

**字词 (Word)**:
词条中所承载的汉字单字或多字词语本体。
_Avoid_: 词, 汉字, 文本

**编码 (Code)**:
输入法方案中用于键入该字词的击键字母/符号序列。
_Avoid_: 码, 键码

**删除确认 (Delete Confirmation)**:
触发条目删除时弹出的轻量模态卡片，展示当前字词、编码以及同码词影响评估。
_Avoid_: 确认框, 弹框

**墓碑标记 (Tombstone)**:
内存中用于标记已删除条目的状态，保障在超大词库（百万级条目）下的 O(1) 瞬时删除性能并在写盘时自动过滤。
_Avoid_: 假删除, 逻辑删除

**方案包 (Scheme Package)**:
XSIME 中导入方案后生成的共享资源目录 `~/.local/share/rimes/schemes/packages/<id>/`，是运行时实际读取词库与方案配置的位置；`schemes/active.yaml` 指向当前生效的包。
_Avoid_: 方案目录, 数据目录

**学习目录 (Learning Directory)**:
方案包对应的用户数据目录 `~/.local/share/rimes/schemes/learning/<id>/`，存放编译产物、用户词库与运行期锁文件。
_Avoid_: 用户目录, 缓存目录
