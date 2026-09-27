# -*- coding: utf-8 -*-
"""把 .github/workflows/ci.yml 的 `cli` 作业在本机逐条复放一遍，逐条记退出码。

为什么不直接 `bash` 整块跑：CI 里那一步用的是 GitHub 的 ubuntu shell，本机
没有同一套环境（`moon` 不在原生 PATH 里、`/tmp` 在两边也不是同一个地方）；
而"整批跑完 rc=0"只代表最后一条语句，不能当成九步都过了。所以这里把 ci.yml
里的命令**逐条**取出来，在本机用等价的解释器执行（`python` 换成本次运行的
解释器，`moon` 换成 `--moon` 给的路径），每一条单独记退出码，最后打一张表。

它只读 `cli` 那个作业；安装类步骤（curl 装工具链、pip 装 Pillow、
`moon version`）本机没法等价复放，会被点名跳过而不是悄悄少几条——
"复放了多少条"由这张表自己说，不由这里的字数说。

跑法（仓库根目录）：

    python ci/replay_cli.py --moon D:/moonbit/bin/moon.exe
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

JOB = "cli"
SKIP_PREFIX = ("curl ", "echo ", "pip install", "moon version", "moon fmt",
               "moon info", "git diff")


def cli_job_lines(workflow):
    """取 `cli` 作业里的 (步骤名, 命令行列表)，按 ci.yml 原顺序。"""
    steps = []
    name = None
    in_job = False
    run_mode = None  # None / "block" / "inline"
    for raw in workflow.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            in_job = stripped[:-1] == JOB
            name, run_mode = None, None
            continue
        if not in_job:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("- name:"):
            name = stripped[len("- name:"):].strip()
            steps.append([name, []])
            run_mode = None
            continue
        if stripped.startswith("run:"):
            rest = stripped[len("run:"):].strip()
            if rest in ("|", ">"):
                run_mode = "block"
                continue
            run_mode = "inline"
            if steps:
                steps[-1][1].append(rest)
            continue
        if stripped.startswith("- ") or stripped.startswith("uses:"):
            run_mode = None
            continue
        if run_mode == "block" and indent >= 10 and steps and not stripped.startswith("#"):
            steps[-1][1].append(stripped)
    return [(n, c) for n, c in steps]


def substitute(argv, moon, python):
    """把 CI 里的解释器名换成本机的等价物；`mkdir -p` 换成 makedirs。"""
    if argv and argv[0] == "mkdir":
        rest = [a for a in argv[1:] if not a.startswith("-")]
        for one in rest:
            os.makedirs(one, exist_ok=True)
        print("      (mkdir -p {})".format(" ".join(rest)))
        return None
    argv = list(argv)
    if argv[0] == "python":
        argv[0] = python
    elif argv[0] == "moon":
        argv[0] = moon
    return argv


def job_step_count(workflow):
    """第二个口径：只按行首缩进数 `- name:`，不解析内容。

    复放器最坏的坏法是**悄悄少跑一步**（删掉一步、或者某个步骤的形状解析器认不
    出来），所以清单要由两套互不相干的算法各数一遍再对账。
    """
    n = 0
    in_job = False
    for raw in workflow.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if raw.startswith("  ") and not raw.startswith("    ") and stripped.endswith(":"):
            in_job = stripped[:-1] == JOB
            continue
        if in_job and raw.startswith("      - name:"):
            n += 1
    return n


COMMAND_TOKENS = ("python ", "moon ", "curl ", "echo ", "pip ", "mkdir ", "git ")


def job_command_lines(workflow):
    """第二个口径：只认"这行以某个命令名开头"，完全不看 YAML 结构。

    步骤数对上了不代表步骤里的命令都在：解析器切块时少拿一行，表上看不出来。
    这里故意不按缩进数——`with:` 底下那种键也是缩进十格，按缩进数会把不相干
    的行算进来，两个口径就永远对不上（那等于没有闸）。
    """
    n = 0
    in_job = False
    for raw in workflow.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if raw.startswith("  ") and not raw.startswith("    ") and stripped.endswith(":"):
            in_job = stripped[:-1] == JOB
            continue
        if not in_job:
            continue
        if stripped.startswith("run:"):
            stripped = stripped[4:].strip()  # 内联写法：命令就在这一行
        if stripped.startswith(COMMAND_TOKENS):
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--moon", default=os.environ.get("MOON", "moon"))
    ap.add_argument("--workflow", default=".github/workflows/ci.yml")
    ap.add_argument("--check-only", action="store_true",
                    help="只解析并对账清单，不起任何子进程")
    args = ap.parse_args()

    path = Path(args.workflow)
    steps = cli_job_lines(path)
    counted = job_step_count(path)
    if len(steps) != counted:
        print("清单对不上：解析器取出 {} 个步骤，按行首 `- name:` 数出来 {} 个。"
              "复放器可能正在悄悄漏步骤，先别信这张表。".format(len(steps), counted))
        return 1
    parsed_cmds = sum(len(lines) for _name, lines in steps)
    raw_cmds = job_command_lines(path)
    if parsed_cmds != raw_cmds:
        print("命令行对不上：解析器取出 {} 条，按命令名开头数出来 {} 条。"
              "少掉的那些条不会被这张表报出来，所以整表作废。".format(parsed_cmds, raw_cmds))
        return 1
    print("清单对账：{} 个步骤、{} 条命令，两个口径一致".format(counted, raw_cmds))
    if not steps:
        print("ci.yml 的 `{}` 作业里一个 run 步骤都没取到——复放器坏了。".format(JOB))
        return 1
    if args.check_only:
        for name, lines in steps:
            print("  {:<34} {} 行".format(name[:34], len(lines)))
        return 0
    commands = 0
    skipped = []
    bad = []
    for name, lines in steps:
        print("== {}".format(name))
        step_rc = 0
        for line in lines:
            try:
                argv = shlex.split(line)
            except ValueError as err:
                print("      解析不了这一行：{}（{}）".format(line, err))
                bad.append((name, line, -1))
                step_rc = step_rc or 1
                continue
            if not argv:
                continue
            if argv[0] in ("curl", "echo", "pip", "git") or (
                argv[0] == "moon" and argv[1:2] in (["version"], ["fmt"], ["info"])
            ):
                skipped.append((name, line))
                print("      [SKIP-ENV] {}".format(line[:120]))
                continue
            real = substitute(argv, args.moon, sys.executable)
            if real is None:
                commands += 1
                continue
            commands += 1
            proc = subprocess.run(real, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            out = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
            mark = "OK  " if proc.returncode == 0 else "FAIL"
            print("      [{}] rc={} {}".format(mark, proc.returncode, line[:120]))
            for tail in out[-2:]:
                print("        | " + tail[:200])
            if proc.returncode != 0:
                step_rc = step_rc or proc.returncode
                bad.append((name, line, proc.returncode))
        print("   -> 步骤退出码 {}".format(step_rc))
    print()
    print("复放清单：{} 个步骤、{} 条命令；本机环境复放不了的 {} 条（{}）".format(
        len(steps), commands, len(skipped),
        "、".join(sorted({a[1].split()[0] for a in skipped})) or "无"))
    print("非 0 的 {} 条".format(len(bad)))
    for name, line, rc in bad:
        print("  rc={}  [{}] {}".format(rc, name, line[:140]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
