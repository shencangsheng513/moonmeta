# -*- coding: utf-8 -*-
"""把 ci/mutations/ 里的每个驱动一次跑一个，并且**替它们判定收尾**。

驱动名单只有一个来源：下面的 `SPECS`（打印里的期望数就是它的长度）。

为什么要有这个文件：申报书里那句"每一句'会红'都由变异驱动钉住"，如果复算方式
是"人眼看每个日志的最后一行"，那它就不是一个可复算的主张。更要紧的是判定本身会错——
按子串扫 "FAIL" 会把绿读成红（`mut_explain` 正常收尾时，unittest 照样会打 FAILED），
而 CAUGHT 行会把期望文案整句打出来，那句里就有"对不上"三个字。所以判定只认每个驱动
自己那几行顶格收尾语，外加两组"必须相等"的计数。

四种用法：
    python ci/mutations/run_all.py                 # 串行跑全部驱动，跑完判定
    python ci/mutations/run_all.py --report DIR    # 只判定 DIR 里已有的 <驱动名>.log，不起子进程
    python ci/mutations/run_all.py --ci            # 只实跑「不要外来语料」的那几个（CI 那一步）
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
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$", r"^\d+ 处坏各处红一次"],
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
    "mut_d9e.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$",
                  r"^开跑前锚点清点：(\d+)/(\d+) ",
                  r"^基线自检（crosscheck_selftest）：rc=0",
                  r"^还原对账：sha [0-9a-f]+ vs 基线 [0-9a-f]+ -> 一致$"],
        red_re=[r"^MISSED ", r"^SKIP  ", r"^!!!   ", r"^没抓到：", r"^基线不绿",
                r"^还原对账：.*-> 不一致$"],
        rc_is_verdict=True,
    ),
    "mut_d15.py": dict(
        green_re=[r"^期望表态 (\d+) 处，抓到 (\d+) 处$",
                  r"^开跑前锚点清点：(\d+)/(\d+) "],
        red_re=[r"^MISSED ", r"^!!!   ", r"^ABORT ", r"^  !! ",
                r"^还原\*\*失败\*\*"],
        rc_is_verdict=True,
    ),
}
DRIVERS = list(SPECS)

# 每个驱动要不要外来语料。这件事必须**声明**而不是推断：CI 上跑哪几个、
# 本机全量跑哪几个，都由这张表说了算。缺席不当"不要语料"——名单悄悄变短
# 会让 CI 少跑一个驱动还全绿，所以 --selftest 里有一条双向差集钉住它。
NEEDS_CORPUS = {
    "mut_explain.py": False,   # 改坏的是 python 侧判据，喂合成字节
    "mut_d7.py": True,         # 要 .scratch 下的外来照片
    "mut_d8.py": True,         # 要 .scratch/tif-subset
    "mut_d10.py": True,        # 要 .scratch/tif-samples
    "mut_d11b.py": False,      # 驱动是 inplace_crosscheck --selftest
    "mut_d12.py": False,       # 驱动是 crosscheck_selftest
    "mut_d13.py": False,       # 驱动是 replay_cli --check-only
    "mut_d9e.py": False,       # 驱动是 crosscheck_selftest
    "mut_d15.py": False,       # 驱动是 moon test，夹具（IPTC/ICC 那一对）在库内
}

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
    "mut_d9e.py": "MISSED Z9：rc=0，要求红在「x」上\n",
    "mut_d15.py": "MISSED 没红在「一条不存在的用例名」（实际红=[]）\n",
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
    log_path.parent.mkdir(parents=True, exist_ok=True)
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
    """只判定已有日志：名单里的都得在，缺一个就是红（计数闸，不是否定式文本闸）。"""
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
    print("\n{} 个驱动里绿 {} 个（期望 {}）".format(
        len(DRIVERS), greens, len(DRIVERS)))
    return 0 if greens == len(DRIVERS) and not missing else 1


def cmd_ci():
    """CI 实跑的那一步：只跑声明为"不要外来语料"的驱动，一个都不许少。

    这里不用否定式判断（"跑不了语料的跳过"）：那样一个新驱动只要忘了登记
    就会**悄悄不进 CI**。名单由 `NEEDS_CORPUS` 声明，两边差集必须为空。
    """
    untagged = [n for n in DRIVERS if n not in NEEDS_CORPUS]
    orphan = [n for n in NEEDS_CORPUS if n not in SPECS]
    for n in untagged:
        print("RED  {} 没声明要不要语料，CI 名单不敢猜".format(n))
    for n in orphan:
        print("RED  {} 声明了但 SPECS 里没有它（名单是死的）".format(n))
    if untagged or orphan:
        return 1
    free = [n for n in DRIVERS if NEEDS_CORPUS[n] is False]
    if not free:
        print("RED  语料无关的驱动一个都没有——空名单不等于全过")
        return 1
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("工作树不干净，先停下（变异驱动要按字节还原目标文件）：\n"
              + dirty[:800])
        return 2
    logs = REPO / ".scratch" / "mutations-ci"
    greens = 0
    for name in free:
        rc, txt = run_one(name, logs / (name.replace(".py", "") + ".log"))
        ok, problems, measured = judge(name, rc, txt)
        greens += ok
        emit(name, ok, problems, measured, extra="   （语料无关）")
    print("\n{} 个语料无关的驱动里绿 {} 个（期望 {}）".format(
        len(free), greens, len(free)))
    after = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if after:
        print("RED  跑完工作树不干净（有驱动的按字节还原没做到位）：\n"
              + after[:800])
        return 1
    return 0 if greens == len(free) else 1


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
    print("\n{} 个驱动里绿 {} 个（期望 {}）".format(
        len(DRIVERS), greens, len(DRIVERS)))
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
    ("mut_d7.py", "期望表态 7 处，抓到 7 处\n7 处坏各处红一次，句与事实的判据不靠字节也抓得到，地板出声；还原后复跑真绿。", 0, True),
    ("mut_d7.py", "期望表态 7 处，抓到 6 处\n6 处坏各处红一次，句与事实的判据不靠字节也抓得到，地板出声；还原后复跑真绿。", 0, False),  # 计数闸
    ("mut_d8.py", "六处谎报各处红一次，六个数字都由文件字节反着算过；还原后复跑真绿。", 0, True),
    ("mut_d10.py", "期望表态 9 处，抓到 9 处", 0, True),
    ("mut_d10.py", "期望表态 9 处，抓到 8 处", 0, False),        # 计数闸
    ("mut_d10.py", "期望表态 9 处，抓到 9 处", 1, False),        # 退码闸
    ("mut_d11b.py", "期望表态 6 处，抓到 6 处\n还原对账：sha c7ab086f9eea vs 基线 c7ab086f9eea -> 一致", 0, True),
    ("mut_d11b.py", "期望表态 6 处，抓到 6 处\n还原对账：sha c7ab086f9eea vs 基线 aaaaaaaaaaaa -> 不一致", 0, False),
    ("mut_d11b.py", "期望表态 6 处，抓到 5 处", 0, False),        # 计数闸：M6 漏抓时不许蒙混成绿
    ("mut_d12.py", "开跑前锚点清点：10/10 恰好在位一次\n期望表态 10 处，抓到 10 处", 0, True),
    ("mut_d12.py", "开跑前锚点清点：9/10 恰好在位一次\n期望表态 10 处，抓到 10 处", 0, False),
    ("mut_d13.py", "基线复放（--check-only）：rc=0，清单对账：11 个步骤、28 条命令，两个口径一致\n"
                   "开跑前锚点清点：5/5 恰好在位一次\n期望表态 5 处，抓到 5 处", 0, True),
    ("mut_d13.py", "基线复放（--check-only）：rc=1，清单对账：11 个步骤、28 条命令，两个口径一致\n"
                   "开跑前锚点清点：5/5 恰好在位一次\n期望表态 5 处，抓到 5 处", 0, False),
    ("mut_d9e.py", "开跑前锚点清点：16/16 恰好在位一次\n"
                   "基线自检（crosscheck_selftest）：rc=0，OK\n"
                   "期望表态 16 处，抓到 16 处\n"
                   "还原对账：sha 9adf15e4f410 vs 基线 9adf15e4f410 -> 一致", 0, True),
    ("mut_d9e.py", "开跑前锚点清点：16/16 恰好在位一次\n"
                   "基线自检（crosscheck_selftest）：rc=0，OK\n"
                   "期望表态 16 处，抓到 15 处\n没抓到：N7 不再拦同一份字节报两遍\n"
                   "还原对账：sha 9adf15e4f410 vs 基线 9adf15e4f410 -> 一致", 0, False),
    ("mut_d9e.py", "开跑前锚点清点：16/16 恰好在位一次\n基线不绿，先修闸再谈变异。", 1, False),
    ("mut_d15.py", "开跑前锚点清点：3/3 唯一在位\n期望表态 7 处，抓到 7 处", 0, True),
    ("mut_d15.py", "开跑前锚点清点：3/3 唯一在位\n期望表态 7 处，抓到 6 处", 0, False),
    ("mut_d15.py", "开跑前锚点清点：2/3 唯一在位\nMISSED 锚点漂了，先停下。", 1, False),
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
    # CI 跑哪几个驱动由 NEEDS_CORPUS 决定；这张表瞎了就是悄悄少跑，所以它也进真值表。
    untagged = [n for n in DRIVERS if n not in NEEDS_CORPUS]
    orphan = [n for n in NEEDS_CORPUS if n not in SPECS]
    census_ok = not untagged and not orphan
    fails += not census_ok
    print("{}  语料名单双向差集为空（SPECS {} 个 / 声明 {} 个）{}".format(
        "ok  " if census_ok else "FAIL", len(SPECS), len(NEEDS_CORPUS),
        "" if census_ok else "　缺声明：" + "、".join(untagged + orphan)))
    covered = {n for n, _b, _rc, g in TRUTH_TABLE if g}
    no_row = [n for n in DRIVERS if n not in covered]
    no_red = [n for n in DRIVERS if n not in RED_LINES]
    row_ok = not no_row and not no_red
    fails += not row_ok
    miss = "".join([
        "　缺正例：" + "、".join(no_row) if no_row else "",
        "　缺红句：" + "、".join(no_red) if no_red else "",
    ])
    print("{}  每个 SPECS 驱动都有一格真日志正例与一句红句（{} 个驱动）{}".format(
        "ok  " if row_ok else "FAIL", len(DRIVERS), miss))
    print("\n判定器真值表：{} 格，错 {} 格".format(
        len(TRUTH_TABLE) + len(RED_LINES) + 2, fails))
    return 0 if fails == 0 else 1


def main(argv):
    ap = argparse.ArgumentParser(description="串行跑全部变异驱动并替它们判定收尾")
    ap.add_argument("--report", type=Path, metavar="DIR",
                    help="只判定 DIR 里已有的 <驱动名>.log，不起子进程")
    ap.add_argument("--selftest", action="store_true",
                    help="判定器自己的真值表（不起子进程、不碰语料）")
    ap.add_argument("--ci", action="store_true",
                    help="只实跑声明为「不要外来语料」的那些驱动（CI 上那一步）")
    ap.add_argument("--logs", type=Path, default=REPO / ".scratch" / "mutations",
                    help="跑批日志目录（默认 .scratch/mutations）")
    ap.add_argument("--moon", default=None, help="moon 可执行文件路径")
    args = ap.parse_args(argv)
    if args.moon:
        os.environ["MOON"] = args.moon
    if args.selftest:
        return cmd_selftest()
    if args.ci:
        return cmd_ci()
    if args.report:
        return cmd_report(args.report if args.report.is_absolute() else REPO / args.report)
    logs = args.logs if args.logs.is_absolute() else REPO / args.logs
    return cmd_run(logs)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
