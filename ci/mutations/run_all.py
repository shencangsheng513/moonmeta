# -*- coding: utf-8 -*-
"""把 ci/mutations/ 里的七个驱动一次跑一个，并且**替它们判定收尾**。

为什么要有这个文件：申报书里那句"每一句'会红'都由变异驱动钉住"，如果复算方式
是"人眼看七个日志的最后一行"，那它就不是一个可复算的主张。更要紧的是判定本身会错——
按子串扫 "FAIL" 会把绿读成红（`mut_explain` 正常收尾时，unittest 照样会打 FAILED），
而 CAUGHT 行会把期望文案整句打出来，那句里就有"对不上"三个字。所以判定只认每个驱动
自己那几行顶格收尾语，外加两组"必须相等"的计数。

三种用法：
    python ci/mutations/run_all.py                 # 串行跑全部七个，跑完判定
    python ci/mutations/run_all.py --report DIR    # 只判定 DIR 里已有的 <驱动名>.log，不起子进程
    python ci/mutations/run_all.py --selftest      # 判定器自己：真日志收尾行 + 两向变异

退码：全绿 0；有红 1；用法错 2。注意 `mut_explain` 自己恒返回 0（源码里没有 sys.exit），
它的判定只认 "ALL WIDENINGS CAUGHT" 那一行——所以本脚本从不把子进程退码当唯一凭据。
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / "moon.mod").is_file())
DRIVERS_DIR = REPO / "ci" / "mutations"

# 每个驱动怎么算绿，是它自己定的；这里照抄它的收尾语汇（顶格锚定，不扫全文）。
SPECS = {
    "mut_explain.py": dict(
        green_re=[r"^ALL WIDENINGS CAUGHT$"],
        red_re=[r"^SOMETHING UNPROVEN$", r"^ABORT ", r"^  !! "],
        rc_is_verdict=False,
    ),
    "mut_d7.py": dict(
        green_re=[r"^五处坏各处红一次"],
        red_re=[r"^变异驱动没过关", r"^   漏了 ", r"^   多抓 ", r"还原\*\*失败\*\*"],
        rc_is_verdict=True,
    ),
    "mut_d8.py": dict(
        green_re=[r"^六处谎报各处红一次"],
        red_re=[r"^变异驱动没过关", r"^   漏了 ", r"^   多抓 "],
        rc_is_verdict=True,
    ),
    "mut_d10.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$"],
        red_re=[r"^  !! ", r"^没找到 moon"],
        rc_is_verdict=True,
    ),
    "mut_d11b.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$",
                  r"^还原对账：sha [0-9a-f]+ vs 基线 [0-9a-f]+ -> 一致$"],
        red_re=[r"^MISSED ", r"^SKIP  ", r"^!!!   ", r"^没抓到：",
                r"^还原对账：.*-> 不一致$"],
        rc_is_verdict=True,
    ),
    "mut_d12.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$",
                  r"^开跑前锚点清点：(\d+)/(\d+) "],
        red_re=[r"^MISSED ", r"^SKIP  ", r"^!!!   ", r"^没抓到："],
        rc_is_verdict=True,
    ),
    "mut_d13.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$",
                  r"^开跑前锚点清点：(\d+)/(\d+) ",
                  r"^基线复放（--check-only）：rc=0"],
        red_re=[r"^MISSED ", r"^SKIP  ", r"^!!!   ", r"^没抓到：", r"^基线不绿"],
        rc_is_verdict=True,
    ),
}
DRIVERS = list(SPECS)

# 两组"必须自己相等"的计数：注入的格数 vs 抓到红的格数；锚点在位数 vs 锚点总数。
PAIRS = [
    (r"期望表态 (\d+) 处，抓到 (\d+) 处", "期望表态/抓到"),
    (r"开跑前锚点清点：(\d+)/(\d+)", "锚点在位/总数"),
]

# 注入用的红句：每个驱动真会打的那一句，不是本脚本编的词。
RED_LINES = {
    "mut_explain.py": "SOMETHING UNPROVEN\n",
    "mut_d7.py": "变异驱动没过关：\n",
    "mut_d8.py": "变异驱动没过关：\n",
    "mut_d10.py": "  !! N9：期望红，测得绿（红数 0）——区分度丢了\n",
    "mut_d11b.py": "MISSED Z9：rc=0，要求 stdout 里有「x」\n",
    "mut_d12.py": "MISSED Z9：rc=0，要求 stdout 里有「x」\n",
    "mut_d13.py": "MISSED Z9：rc=0，要求 stdout 里有「x」\n",
}


def judge(name, rc, txt):
    """返回 (绿?, [问题], [测得])。测得的数字一律打出来，不只在坏消息时打。"""
    spec = SPECS[name]
    lines = txt.splitlines()
    problems, measured = [], []
    for rex in spec["green_re"]:
        hits = [l for l in lines if re.match(rex, l)]
        if not hits:
            problems.append("缺判据行 " + rex)
        else:
            measured.append(hits[-1].strip())
    for rex, label in PAIRS:
        m = re.search(rex, txt)
        if m:
            if m.group(1) != m.group(2):
                problems.append("{}：{} != {}".format(
                    label, m.group(1), m.group(2)))
            else:
                measured.append("{}：{} == {}".format(
                    label, m.group(1), m.group(2)))
    for rex in spec["red_re"]:
        hits = [l for l in lines if re.match(rex, l)]
        if hits:
            problems.append("红判据 {} 命中 {} 行：{}".format(
                rex, len(hits), hits[0].strip()[:120]))
    if not txt.strip():
        problems.append("零输出（驱动根本没跑起来）")
    if spec["rc_is_verdict"] and rc != 0:
        problems.append("退码 {}".format(rc))
    measured.append("退码 {}{}".format(
        rc, "" if spec["rc_is_verdict"] else "（该驱动按设计恒 0，判定只认上面那行）"))
    return (not problems), problems, measured


def emit(name, ok, problems, measured, extra=""):
    print("{}  {}{}".format("GREEN" if ok else "RED  ", name, extra), flush=True)
    for m in measured:
        print("      测得：" + m[:170], flush=True)
    for q in problems:
        print("      问题：" + q[:200], flush=True)


def run_one(name, log_path):
    moon = os.environ.get("MOON") or r"D:\moonbit\bin\moon.exe"
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "wb") as f:
        p = subprocess.run(
            [sys.executable, "-B", "-u", str(DRIVERS_DIR / name)],
            stdout=f, stderr=subprocess.STDOUT, cwd=str(REPO),
            env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                     PYTHONDONTWRITEBYTECODE="1", MOON=moon,
                     PATH=os.environ["PATH"] + os.pathsep
                     + str(Path(moon).parent)),
        )
    return p.returncode, log_path.read_text(encoding="utf-8", errors="replace")


def cmd_report(log_dir):
    """只判定已有日志：七个都得在，缺一个就是红（计数闸，不是否定式文本闸）。"""
    missing, greens = [], 0
    for name in DRIVERS:
        log = log_dir / (name.replace(".py", "") + ".log")
        if not log.is_file():
            missing.append(log.name)
            continue
        txt = log.read_text(encoding="utf-8", errors="replace")
        when = datetime.datetime.fromtimestamp(log.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        ok, problems, measured = judge(name, 0, txt)
        greens += ok
        emit(name, ok, problems, measured, extra="   （日志时间 {}，未起子进程）".format(when))
    if missing:
        print("RED    日志缺 {} 个：{}".format(len(missing), "、".join(missing)))
    print("\n七个驱动绿 {} 个（期望 {}）".format(greens, len(DRIVERS)))
    return 0 if greens == len(DRIVERS) and not missing else 1


def cmd_run(log_dir):
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("工作树不干净，先停下：变异驱动会把目标文件按字节还原，"
              "半路有别人的改动就会被盖掉。\n" + dirty[:800])
        return 2
    greens = 0
    for name in DRIVERS:
        rc, txt = run_one(name, log_dir / (name.replace(".py", "") + ".log"))
        ok, problems, measured = judge(name, rc, txt)
        greens += ok
        emit(name, ok, problems, measured)
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    print("\n七个驱动绿 {} 个（期望 {}）".format(greens, len(DRIVERS)))
    if dirty:
        print("RED  跑完工作树仍不干净（还原没做到位）：\n" + dirty[:800])
        return 1
    print("跑完工作树干净：注入的文件都按字节回去了。")
    return 0 if greens == len(DRIVERS) else 1


# 判定器自己的真值表。标的行是从盘上真日志里逐字抄来的收尾句（不是本脚本编的形状）。
# 每行自带退码：变异行一律给 rc=0，否则"红"是退码给的，不是被测那道闸给的——
# 而 --report 模式下根本没有退码（rc 恒 0），那时唯一的区分度就是这些行闸。
TRUTH_TABLE = [
    ("mut_explain.py", "ALL WIDENINGS CAUGHT", 0, True),
    ("mut_d7.py", "五处坏各处红一次，句与事实的判据不靠字节也抓得到，还原后复跑真绿。", 0, True),
    ("mut_d8.py", "六处谎报各处红一次，六个数字都由文件字节反着算过；还原后复跑真绿。", 0, True),
    ("mut_d10.py", "期望表态 9 处，抓到 9 处", 0, True),
    ("mut_d10.py", "期望表态 9 处，抓到 8 处", 0, False),        # 计数闸
    ("mut_d10.py", "期望表态 9 处，抓到 9 处", 1, False),        # 退码闸
    ("mut_d11b.py", "期望表态 5 处，抓到 5 处\n还原对账：sha 13d0f7e76d27 vs 基线 13d0f7e76d27 -> 一致", 0, True),
    ("mut_d11b.py", "期望表态 5 处，抓到 5 处\n还原对账：sha 13d0f7e76d27 vs 基线 aaaaaaaaaaaa -> 不一致", 0, False),
    ("mut_d12.py", "开跑前锚点清点：10/10 恰好在位一次\n期望表态 10 处，抓到 10 处", 0, True),
    ("mut_d12.py", "开跑前锚点清点：9/10 恰好在位一次\n期望表态 10 处，抓到 10 处", 0, False),
    ("mut_d13.py", "基线复放（--check-only）：rc=0，清单对账：11 个步骤、28 条命令，两个口径一致\n"
                   "开跑前锚点清点：5/5 恰好在位一次\n期望表态 5 处，抓到 5 处", 0, True),
    ("mut_d13.py", "基线复放（--check-only）：rc=1，清单对账：11 个步骤、28 条命令，两个口径一致\n"
                   "开跑前锚点清点：5/5 恰好在位一次\n期望表态 5 处，抓到 5 处", 0, False),
]


def cmd_selftest():
    fails = 0
    for name, body, rc, want_green in TRUTH_TABLE:
        ok, problems, _ = judge(name, rc, body + "\n")
        tag = "正例" if want_green else "变异"
        good = (ok == want_green)
        fails += not good
        print("{}  {} {} rc={} -> 判成{}{}".format(
            "ok  " if good else "FAIL", name, tag, rc,
            "绿" if ok else "红",
            "" if good else "　期望{}｜{}".format(
                "绿" if want_green else "红", "；".join(problems)[:120])))
    # 每一句红都必须被自己的驱动抓到：注入本驱动真会打的那一句红，判定要翻红。
    for name, red in RED_LINES.items():
        green_body = next((b for n, b, _rc, g in TRUTH_TABLE if n == name and g), "")
        ok, problems, _ = judge(name, 0, green_body + "\n" + red)
        good = not ok
        fails += not good
        print("{}  {} 注入红句翻红{}".format(
            "ok  " if good else "FAIL", name,
            "" if good else "——判定器瞎：{}".format("；".join(problems)[:120])))
    print("\n判定器真值表：{} 格，错 {} 格".format(len(TRUTH_TABLE) + len(RED_LINES), fails))
    return 0 if fails == 0 else 1


def main(argv):
    ap = argparse.ArgumentParser(description="串行跑七个变异驱动并替它们判定收尾")
    ap.add_argument("--report", type=Path, metavar="DIR",
                    help="只判定 DIR 里已有的 <驱动名>.log，不起子进程")
    ap.add_argument("--selftest", action="store_true",
                    help="判定器自己的真值表（不起子进程、不碰语料）")
    ap.add_argument("--logs", type=Path, default=REPO / ".scratch" / "mutations",
                    help="跑批日志目录（默认 .scratch/mutations）")
    ap.add_argument("--moon", default=None, help="moon 可执行文件路径")
    args = ap.parse_args(argv)
    if args.moon:
        os.environ["MOON"] = args.moon
    if args.selftest:
        return cmd_selftest()
    if args.report:
        return cmd_report(args.report if args.report.is_absolute() else REPO / args.report)
    logs = args.logs if args.logs.is_absolute() else REPO / args.logs
    return cmd_run(logs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
