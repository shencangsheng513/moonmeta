"""给归因判据做变异：解释器被改宽时，selftest 必须立刻变红。

跑法（在仓库根目录）：python -u ci/mutations/mut_explain.py
判"抓到"必须同时满足：退出码非 0、真的跑过用例（Ran N tests）、且结论行是 FAILED。
只看出退码会把"崩在半路"当成"抓到了"。
"""

import re
import subprocess
import sys

MUTATIONS = [
    (
        "E1 注入判据改成无条件放行",
        '    if dir_name != "IFD0":\n        return False',
        "    if False:\n        return False",
    ),
    (
        "E2 段里已有同名条目这一票取消",
        '        if name in names:  # 段里另有一条同名的，就不是注入问题\n            return False',
        "        pass",
    ),
    (
        "E3 表外编号也算能解释",
        '        if name is None or ("tiff:" + name).encode() not in src_blob:\n            return False',
        '        if name is None:\n            name = "Orientation"\n        if ("tiff:" + name).encode() not in src_blob:\n            return False',
    ),
    (
        "E4 空声明判据把缺失条目也放行",
        "in ('\"\"', \"Raw(0 byte(s))\")",
        "in ('\"\"', \"Raw(0 byte(s))\", None)",
    ),
    (
        "E5 空声明判据无条件放行",
        "        return all(seen.get(t) in",
        "        return True or all(seen.get(t) in",
    ),
]

TARGET = "ci/crosscheck_real.py"
SELFTEST = ["ci/crosscheck_selftest.py"]


def run_selftest():
    r = subprocess.run(
        [sys.executable, "-u"] + SELFTEST,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    blob = r.stdout + r.stderr
    ran = re.findall(r"Ran \d+ tests", blob)
    last = [ln for ln in blob.splitlines() if ln.startswith("FAILED") or ln.strip() == "OK"]
    caught = r.returncode != 0 and bool(ran) and any(ln.startswith("FAILED") for ln in last)
    return r, ran, last, caught


ok = True
for name, old, new in MUTATIONS:
    src = open(TARGET, encoding="utf-8").read()
    if src.count(old) != 1:
        print("ABORT {}: 目标串出现 {} 次，不是 1 次".format(name, src.count(old)))
        ok = False
        break
    open(TARGET, "w", encoding="utf-8", newline="").write(src.replace(old, new, 1))
    r, ran, last, caught = run_selftest()
    print("{}\n  -> rc={} | {} | {}".format(name, r.returncode, ran[:1], last[:1]))
    open(TARGET, "w", encoding="utf-8", newline="").write(src)
    if open(TARGET, encoding="utf-8").read() != src:
        print("ABORT {}: 还原失败".format(name))
        ok = False
        break
    if not caught:
        print("  !! selftest 没抓到这处放宽（或根本没跑起来）")
        ok = False

r, ran, last, _ = run_selftest()
print("restored baseline rc={} | {} | {}".format(r.returncode, ran[:1], last[:1]))
print("ALL WIDENINGS CAUGHT" if ok and r.returncode == 0 else "SOMETHING UNPROVEN")
