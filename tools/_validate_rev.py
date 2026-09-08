import re
base = "/home/jackwy/.local/share/fcitx5/rime/lua/kongmingma/data"
for ini in ["a", "f", "z", "y"]:
    p = base + "/reverse_%s.lua" % ini
    src = open(p, encoding="utf-8").read()
    ok = src.startswith("-- 自动生成")
    balanced = src.count("{") == src.count("}")
    has = ('"啊","a="' in src) if ini == "a" else True
    print("reverse_%s.lua header=%s braces=%s sample_ok=%s" % (ini, ok, balanced, has))
