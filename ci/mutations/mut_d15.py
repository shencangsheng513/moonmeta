# -*- coding: utf-8 -*-
"""D15 变异驱动：IPTC 与 ICC 这两个编号一旦混回去，测试必须指名道姓地红。

被验的主张只有一句：**裸 TIFF 里 `0x83bb`（IPTC-NAA）要整包摘掉，
`0x8773`（ICC 色彩配置文件）要原样留下**。这一对编号在本仓库里一度写成同一个，
后果是两头同时错——真 IPTC 一条都不报（假脱敏），而别人的色彩配置文件被当成
"这里还有一整套元数据"删掉（产物偏色）。

为什么要一个专门的驱动：这一格的判据住在数据表里，表写错时**读侧与写侧都照常
工作**，146 个不相关的用例一个都不会抖。所以"测试会红"这句话必须被反着验一次：
把三种历史写法逐个注回去，看红的到底是不是那几条用例。

三格各验一种方向，期望红的用例清单互不相同（这正是它们的区分度所在）：
  I1 载体表退回 `0x8773`     → 真 IPTC 失去覆盖 + ICC 被误删，三格红
  I2 载体表同时留两条        → IPTC 覆盖对了但 ICC 多挨一刀，两格红（"七个类别"
                               那一格此时仍然绿——它只查该删的，不查不该删的）
  I3 名字表退回              → 类别没变、报告里的名字变了，两格红

跑法（moon 路径用 --moon 或环境变量 MOON 指）：
    PYTHONUTF8=1 python -u ci/mutations/mut_d15.py
    python -u ci/mutations/mut_d15.py --moon D:/moonbit/bin/moon.exe I1 I3
只跟位置参数是"只跑这几格"。跑到一半崩了会在 `finally` 里按字节还原，
还原凭据只认 sha。
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    REPO = next(p for p in Path(__file__).resolve().parents if (p / "moon.mod").is_file())
except StopIteration:
    raise SystemExit("找不到模块根（{} 往上没有 moon.mod）".format(__file__))

TAGS = REPO / "moonmeta_tags.mbt"
MOON = None

# 历史写法的三个片段。锚点必须**恰好命中一次**，否则注入的是个不存在的位置。
CARRIER_ROW = "  (Ifd0, 0x83bb, Carrier),\n"
NAME_ROWS = (
    '    0x83bb => Some("IptcNaa")\n'
    '    0x8769 => Some("ExifOffset")\n'
    '    0x8773 => Some("InterColorProfile")\n'
)

CASES = [
    (
        "I1",
        "载体表退回 0x8773：真 IPTC 没人管，ICC 反被当成元数据",
        [(CARRIER_ROW, "  (Ifd0, 0x8773, Carrier),\n")],
        [
            "TIFF 里的 IPTC 要摘掉，ICC 要原样留下",
            "策略够不着的条目要说清是哪一类，或明确不属于",
            "七个类别各自点名，不互相串",
        ],
    ),
    (
        "I2",
        "载体表两条都留：IPTC 摘对了，ICC 多挨一刀",
        [(CARRIER_ROW, CARRIER_ROW + "  (Ifd0, 0x8773, Carrier),\n")],
        [
            "TIFF 里的 IPTC 要摘掉，ICC 要原样留下",
            "策略够不着的条目要说清是哪一类，或明确不属于",
        ],
    ),
    (
        "I3",
        "名字表退回：类别没变，报告里的名字指错了方向",
        [(NAME_ROWS, '    0x8769 => Some("ExifOffset")\n'
                     '    0x8773 => Some("IptcNaa")\n')],
        [
            "规范名表：README 报出的编号与名字逐条对得上",
            "TIFF 里的 IPTC 要摘掉，ICC 要原样留下",
        ],
    ),
]


def read_text():
    raw = TAGS.read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_text(text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    TAGS.write_bytes(text.encode("utf-8"))


def sha():
    return hashlib.sha256(TAGS.read_bytes()).hexdigest()


def resolve_moon():
    global MOON
    if "--moon" in sys.argv:
        i = sys.argv.index("--moon")
        if i + 1 >= len(sys.argv):
            print("ABORT --moon 后面没有路径")
            sys.exit(2)
        MOON = sys.argv[i + 1]
    else:
        MOON = os.environ.get("MOON") or "moon"
    if os.path.sep in MOON and not Path(MOON).is_file():
        print("ABORT 没找到 moon：{}（这一格既不算红也不算绿）".format(MOON))
        sys.exit(2)


def moon_test():
    """跑一遍 wasm 后端，返回 (退码, 跑到收尾行没, 红掉的用例名集合)。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(
            [MOON, "test", "--target", "wasm"],
            cwd=str(REPO), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
    except OSError as e:
        print("ABORT moon 跑不起来（{}）：{}".format(MOON, e))
        sys.exit(2)
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"Total tests: \d+, passed: \d+, failed: (\d+)", out)
    if m is None:
        print("  !! 没看到收尾计数，末 8 行：")
        for ln in out.splitlines()[-8:]:
            print("     | " + ln)
        return p.returncode, False, set()
    names = set(re.findall(r'test \S+ \("(.+?)"\) failed', out))
    return p.returncode, True, names


def main():
    resolve_moon()
    argv = sys.argv[1:]
    wanted = []
    i = 0
    while i < len(argv):
        if argv[i] == "--moon":
            i += 2
            continue
        if argv[i].startswith("--"):
            i += 1
            continue
        wanted.append(argv[i])
        i += 1
    wanted = set(wanted)
    cases = [c for c in CASES if not wanted or c[0] in wanted]
    if wanted and len(cases) != len(wanted):
        print("ABORT 没有这些变异编号：{}".format(
            sorted(wanted - {c[0] for c in cases})))
        return 2

    base_text, crlf = read_text()
    base_sha = sha()
    anchors = [old for _, _, edits, _ in cases for old, _ in edits]
    uniq = sum(1 for a in anchors if base_text.count(a) == 1)
    print("开跑前锚点清点：{}/{} 唯一在位".format(uniq, len(anchors)))
    if uniq != len(anchors):
        for a in anchors:
            if base_text.count(a) != 1:
                print("!!!   锚点在位 {} 次：{!r}".format(base_text.count(a), a[:48]))
        print("MISSED 锚点漂了，先停下（在红树或错位上验红都是假的）")
        return 1

    code, ran, reds = moon_test()
    print("  基线 moon test: rc={} 跑到={} 红={} 个".format(code, ran, len(reds)))
    if not ran or reds or code != 0:
        print("MISSED 基线不干净，先停下")
        return 2

    expect = sum(len(c[3]) for c in cases)
    caught = 0
    try:
        for tag, label, edits, wants in cases:
            print("\n== {} {}".format(tag, label))
            text = base_text
            for old, new in edits:
                assert text.count(old) == 1, "锚点不在位：{}".format(old[:40])
                text = text.replace(old, new)
            write_text(text, crlf)
            try:
                code, ran, reds = moon_test()
                if not ran:
                    print("  !! {} 没跑到收尾计数，判红".format(tag))
                    continue
                for name in wants:
                    if name in reds:
                        caught += 1
                        print("CAUGHT 红在「{}」".format(name))
                    else:
                        print("MISSED 没红在「{}」（实际红={}）".format(
                            name, sorted(reds)[:3]))
            finally:
                write_text(base_text, crlf)
                back = sha() != base_sha
                print("  [sha 对账] {} vs {} -> {}".format(
                    base_sha[:12], sha()[:12], "一致" if not back else "不一致"))
                if back:
                    print("还原**失败**：{} 的 sha 对不上".format(TAGS.name))
                    return 1
    finally:
        write_text(base_text, crlf)

    code, ran, reds = moon_test()
    if not ran or reds or code != 0:
        print("MISSED 还原后没回到绿：红={} 个".format(sorted(reds)[:3]))
        return 1
    print("期望表态 {} 处，抓到 {} 处".format(expect, caught))
    return 0 if caught == expect else 1


if __name__ == "__main__":
    sys.exit(main())
