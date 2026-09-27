# -*- coding: utf-8 -*-
"""D11-B 变异驱动：给 inplace_crosscheck.py 的分母闸装眼睛，逐格打红。

四格新闸（嵌套 / 同名 / 语料不存在 / 空扫描）各自对应一句实现里承重的话。
每处坏法注入一次，跑 `--selftest`，要求：退出码 1 **且** stdout 里出现
指名这一格的那句问题——只看退出码会把"红在别处"当成抓到。
跑完按字节还原并核对 sha。
"""
import subprocess
import sys
import hashlib

TARGET = "ci/inplace_crosscheck.py"
ANCHOR_LAYOUT = "    if not Path(corpus).is_dir():\n"
ANCHOR_INSIDE = "    return c == o or c in o.parents\n"
ANCHOR_SCAN = "    if files:\n        return None\n"

MUTATIONS = [
    ("M1 先建目录再判（拒绝成了事后道歉）",
     ANCHOR_LAYOUT,
     "    Path(out_dir).mkdir(parents=True, exist_ok=True)\n" + ANCHOR_LAYOUT,
     "口头拒了，语料目录里却多了东西"),
    ("M2 嵌套判据恒放行",
     ANCHOR_INSIDE, "    return False\n",
     "产物目录嵌在语料目录里：期望拒绝，测得放行"),
    ("M3 嵌套判据恒拒绝",
     ANCHOR_INSIDE, "    return True\n",
     "产物目录与语料目录同级：期望放行，测得拒绝"),
    ("M4 空扫描恒放行",
     ANCHOR_SCAN, "    if True:\n        return None\n",
     "扫到 0 份：期望拒绝，测得放行"),
    ("M5 空扫描恒拒绝",
     ANCHOR_SCAN, "    if False:\n        return None\n",
     "扫到 1 份：期望放行，测得拒绝"),
]


def read_text():
    raw = open(TARGET, "rb").read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return text, crlf


def write_text(text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(TARGET, "wb") as f:
        f.write(text.encode("utf-8"))


def run_selftest():
    p = subprocess.run(
        [sys.executable, TARGET, "--selftest"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    base_text, crlf = read_text()
    base_sha = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
    caught = []
    for name, old, new, expect in MUTATIONS:
        if base_text.count(old) != 1:
            print("SKIP  {}: 锚点命中 {} 次，不敢改库".format(name, base_text.count(old)))
            continue
        write_text(base_text.replace(old, new, 1), crlf)
        try:
            rc, out = run_selftest()
        finally:
            write_text(base_text, crlf)
            back = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
            if back != base_sha:
                print("!!!   {} 还原失败：sha {} != {}".format(name, back[:12], base_sha[:12]))
        red = rc == 1 and expect in out
        print("{} {}：rc={}，要求 stdout 里有「{}」".format(
            "CAUGHT" if red else "MISSED", name, rc, expect))
        if red:
            caught.append(name)
    still = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
    print("还原对账：sha {} vs 基线 {} -> {}".format(
        still[:12], base_sha[:12], "一致" if still == base_sha else "不一致"))
    print("期望表态 {} 处，抓到 {} 处".format(len(MUTATIONS), len(caught)))
    rc, out = run_selftest()
    print("还原后复跑自测：rc={}".format(rc))
    print(out.strip().splitlines()[-1])
    return 0 if (len(caught) == len(MUTATIONS) and still == base_sha and rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
