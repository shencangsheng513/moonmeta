# -*- coding: utf-8 -*-
"""D13 变异驱动：复放器（ci/replay_cli.py）的两条清单闸要各自能红。

这台工具最坏的坏法不是"某一步红了"，而是**悄悄少复放一条命令**——它的输出
仍然全绿，只是那张表上没有了这一步。所以它自己带了两条对账闸（步骤数、
命令行数，都由第二个口径独立数一遍），这里逐条确认它们真的能红：
每处坏法注入一次，跑 `python -B ci/replay_cli.py --check-only`（不起任何
子进程），要求退出码非 0 **且** stdout 里出现指名这一格的那句问题。
跑完按字节还原并核对 sha。

R4 打的是今天真踩过的那一格：第二个口径当初没处理内联写法 `run: python ...`，
两个口径永远差 9 条——这条闸第一次上机就是靠这个不一致发现的，别把它改回
"看起来一致"。
"""

import hashlib
import subprocess
import sys

TARGET = "ci/replay_cli.py"
DRIVER = ["ci/replay_cli.py", "--check-only"]

MUTATIONS = [
    (
        "R1 块内容按更深的缩进取（少拿一批命令行）",
        "        if run_mode == \"block\" and indent >= 10 and steps and not stripped.startswith(\"#\"):",
        "        if run_mode == \"block\" and indent >= 12 and steps and not stripped.startswith(\"#\"):",
        "命令行对不上",
    ),
    (
        "R2 步骤名那一支认不出来（清单整个塌成空）",
        "        if stripped.startswith(\"- name:\"):",
        "        if stripped.startswith(\"-name:\"):",
        "清单对不上",
    ),
    (
        "R3 作业名写错（两个口径一起数到 0，也算一种假绿）",
        "JOB = \"cli\"",
        "JOB = \"clix\"",
        "一个 run 步骤都没取到",
    ),
    (
        "R4 第二个口径不看内联 run:（今天真错过的形状）",
        "            stripped = stripped[4:].strip()  # 内联写法：命令就在这一行",
        "            continue",
        "命令行对不上",
    ),
    (
        "R5 第二个口径的缩进前缀少一格（数不到任何步骤名）",
        "        if in_job and raw.startswith(\"      - name:\"):",
        "        if in_job and raw.startswith(\"     - name:\"):",
        "清单对不上",
    ),
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


def run_driver():
    p = subprocess.run(
        [sys.executable, "-B", "-u"] + DRIVER,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    base_text, crlf = read_text()
    base_sha = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
    absent = [n for n, o, _, _ in MUTATIONS if base_text.count(o) != 1]
    print("开跑前锚点清点：{}/{} 恰好在位一次".format(
        len(MUTATIONS) - len(absent), len(MUTATIONS)))
    for n in absent:
        print("        不在位/不唯一：{}".format(n))
    rc0, out0 = run_driver()
    print("基线复放（--check-only）：rc={}，{}".format(
        rc0, out0.strip().splitlines()[0] if out0.strip() else "无输出"))
    if rc0 != 0:
        print("基线不绿，先修工具再谈变异。")
        return 1
    caught = []
    missed = []
    for name, old, new, expect in MUTATIONS:
        hits = base_text.count(old)
        if hits != 1:
            print("SKIP  {}: 锚点命中 {} 次，不敢改".format(name, hits))
            missed.append(name + "（锚点不唯一）")
            continue
        write_text(base_text.replace(old, new, 1), crlf)
        try:
            rc, out = run_driver()
        finally:
            write_text(base_text, crlf)
            back = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
            if back != base_sha:
                print("!!!   {} 还原失败：sha {} != {}".format(
                    name, back[:12], base_sha[:12]))
        red = rc != 0 and expect in out
        line = [l for l in out.strip().splitlines() if l.strip()]
        print("{} {}：rc={}，测得「{}」，要求 stdout 里有「{}」".format(
            "CAUGHT" if red else "MISSED", name, rc,
            (line[-1] if line else "无输出")[:60], expect))
        (caught if red else missed).append(name)
    still = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
    print("还原对账：sha {} vs 基线 {} -> {}".format(
        still[:12], base_sha[:12], "一致" if still == base_sha else "不一致"))
    print("期望表态 {} 处，抓到 {} 处".format(len(MUTATIONS), len(caught)))
    rc, out = run_driver()
    print("还原后复跑：rc={}，最后一行 {}".format(
        rc, out.strip().splitlines()[-1] if out.strip() else "无输出"))
    for m in missed:
        print("没抓到：{}".format(m))
    return 0 if (len(caught) == len(MUTATIONS) and still == base_sha and rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
