import os
import subprocess
import sys
import re

RIME_TEST_BIN = "/tmp/rime_test"

def ensure_bin():
    if not os.path.exists(RIME_TEST_BIN):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = os.path.join(root, "tools", "rime_test_console.c")
        subprocess.run(["gcc", "-o", RIME_TEST_BIN, src, "-lrime"], check=True)

def query_reverse(schema, key_seq):
    ensure_bin()
    res = subprocess.run([RIME_TEST_BIN, schema, key_seq], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error running /tmp/rime_test: {res.stderr}")
        return {}
    candidates = {}
    for line in res.stdout.splitlines():
        m = re.match(r"^\s*\[\d+\]\s+(\S+)\s+\(([^)]*)\)", line)
        if m:
            word, comment = m.group(1), m.group(2)
            candidates[word] = comment.split()
    return candidates

def test_reverse_yijian():
    print("Testing `yi in kongmingmas...")
    cands_yi = query_reverse("kongmingmas", "`yi")
    yi_codes = cands_yi.get("以", [])
    print(f"以: {yi_codes}")
    assert "i=" in yi_codes, f"以 should have current yijian i=, but got {yi_codes}"
    assert "y." in yi_codes, f"以 should have full code y., but got {yi_codes}"
    assert "y" not in yi_codes, f"以 MUST NOT have obsolete y, but got {yi_codes}"
    assert "y.f=" not in yi_codes, f"以 MUST NOT have wrong y.f=, but got {yi_codes}"
    assert "f=" not in yi_codes, f"以 MUST NOT have f=, but got {yi_codes}"

    one_codes = cands_yi.get("一", [])
    print(f"一: {one_codes}")
    assert "=y" in one_codes, f"一 should have =y, but got {one_codes}"
    assert "y" not in one_codes, f"一 MUST NOT have raw y, but got {one_codes}"

    cands_di = query_reverse("kongmingmas", "`di")
    di_codes = cands_di.get("地", [])
    print(f"地: {di_codes}")
    assert "a=" in di_codes and "d" not in di_codes and "U" not in di_codes

    cands_zhu = query_reverse("kongmingmas", "`zhu")
    zhu_codes = cands_zhu.get("主", [])
    print(f"主: {zhu_codes}")
    assert "=I" in zhu_codes and "Z" not in zhu_codes

    cands_hua = query_reverse("kongmingmas", "`hua")
    hua_codes = cands_hua.get("化", [])
    print(f"化: {hua_codes}")
    assert "=_F" in hua_codes and "h" not in hua_codes

    cands_you = query_reverse("kongmingmas", "`you")
    you_codes = cands_you.get("由", [])
    print(f"由: {you_codes}")
    assert "=_a" in you_codes and "u" not in you_codes

    print("\nALL REVERSE LOOKUP REGRESSION CHECKS PASSED!")

if __name__ == "__main__":
    test_reverse_yijian()
