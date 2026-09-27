# -*- coding: utf-8 -*-
"""D10 变异驱动：next 指针跟着条目数搬家，这一刀的每一层都要有牙齿。

被验的东西分三层，缺一条都不算证过：
  N1 引擎忘了搬        → `moon test` 必须红（那两格链断言）+ 真语料必须进 triage（N6）
  N2 引擎搬完又清零    → `moon test` 必须红（顺序坏了等于没搬）
  N3 门禁 python 退回不搬 → 门禁自测必须红（链这一闸）
  N4 把链这一闸摘掉     → 门禁自测必须红（"next 没搬"那格失去区分度）
  N5 夹具退回不带链     → 门禁自测必须红（前提闸：没链的文件测不出这一刀）

N6 是 N1 的现网票：N3–N5 全走手打夹具，只验字符串不验真产物。少了这一格，
"N4 把链这一闸摘掉"仍然会红——红在夹具上，可夹具是我手打的。

跑法（moon 路径可用 --moon 或环境变量 MOON 指；语料用 --corpus 指）：
    PYTHONUTF8=1 python -u ci/mutations/mut_d10.py
    python -u ci/mutations/mut_d10.py --moon D:/moonbit/bin/moon.exe --corpus .scratch/tif-samples N1 N6
只跟位置参数是"只跑这几格"；跑到一半崩了会在 `finally` 里按字节还原。
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    # 按模块根标记往上找，别按层数猜：从 .scratch 搬进 ci/mutations 那次，
    # 靠层数反推的两个驱动把 .scratch 找成了 ci/.scratch。
    REPO = next(p for p in Path(__file__).resolve().parents if (p / "moon.mod").is_file())
except StopIteration:
    raise SystemExit("找不到模块根（{} 往上没有 moon.mod）".format(__file__))
PATCH = REPO / "moonmeta_tiff_patch.mbt"
GATE = REPO / "ci/inplace_crosscheck.py"
# moon 路径由 --moon / 环境变量 MOON / PATH 三处之一给出（解析见 parse_args）。
MOON = None
# 语料与产物目录默认落在 .scratch 下（仓库自带的那批外来裸 TIFF）。
CORPUS = REPO / ".scratch/tif-samples"
OUT = REPO / ".scratch/mut_d10_out"
# 这一格只跑一个文件：它是当初"三条链全断"里唯一在 redact 腿上也断的那一个。
TRIGGER = "total-pages-zero"

COPY4 = (
    b"    for k = 0; k < 4; k = k + 1 {\n"
    b"      buf[w + k] = byte_at(data, old_body + k)\n"
    b"    }\n"
    b"    for p = w + 4; p < old_body; p = p + 1 {\n"
)
PY_COPY = b"        out[w : w + 4] = blob[body : body + 4]\n        for i in range(w + 4, body):\n"

CASES = [
    ("N1", "引擎忘了把 next 搬到新表尾（连清零一起退回旧写法）",
     [(PATCH, COPY4, b"    for p = w; p < old_body; p = p + 1 {\n")],
     ("moon", "corpus")),
    ("N2", "引擎搬完又从新表尾开始清零（顺序反了，等于没搬）",
     [(PATCH, b"    for p = w + 4; p < old_body; p = p + 1 {",
       b"    for p = w; p < old_body; p = p + 1 {")],
     ("moon",)),
    ("N3", "门禁的独立实现退回不搬 next",
     [(GATE, PY_COPY, b"        for i in range(w, body):\n")],
     ("gate",)),
    ("N4", "把链这一闸摘掉（产物照旧，闸瞎了）",
     [(GATE, b"        want = chain_digest(tif)", b"        want = None")],
     ("gate",)),
    ("N5", "自测夹具退回不带缩略图链",
     [(GATE, b"ifd_bytes(rows, ifd1_off, ifd0_end)", b"ifd_bytes(rows, 0, ifd0_end)")],
     ("gate",)),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def patch(path, old, new, label):
    raw = path.read_bytes()
    if old not in raw:
        raise SystemExit("变异 {} 的目标片段没找到，拒绝改动 {}".format(label, path))
    if raw.count(old) != 1:
        raise SystemExit("变异 {} 的目标片段在 {} 里出现 {} 次，不止一处".format(
            label, path.name, raw.count(old)))
    path.write_bytes(raw.replace(old, new))
    print("  [注入] {} -> {} sha={}".format(label, path.name, sha(path)))


def run(cmd):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def moon_test():
    if not MOON:
        raise SystemExit(
            "找不到 moon：这一格既不算红也不算绿。用 --moon 指路（本机 "
            "D:/moonbit/bin/moon.exe），或把 moon 放进 PATH")
    code, out = run([MOON, "test", "--target", "wasm"])
    m = re.search(r"Total tests: \d+, passed: \d+, failed: (\d+)", out)
    ran = m is not None
    if not ran:
        print("     末 8 行：\n" + "\n".join("     " + ln for ln in out.splitlines()[-8:]))
    return code, (int(m.group(1)) if ran else 0), ran


def gate_selftest():
    """门禁自测。红了不够，还要看红的是哪一格：拿 FAIL 行对账。"""
    code, out = run([sys.executable, str(GATE), "--selftest"])
    ran = "自测：" in out
    verdict = bool(re.search(r"自测：失败", out))
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    print("  门禁自测: rc={} 跑到={} 判定={} FAIL 格数={}".format(
        code, ran, "红" if verdict else ("绿" if ran else "没跑到"), len(fails)))
    for ln in fails[:3]:
        print("     | " + ln)
    # 前提闸与对账类问题不打 FAIL 行，是"  - "清单里的条目：看不见它们就等于
    # 只知道红了，不知道为什么红。
    for ln in [
        ln.strip() for ln in out.splitlines() if ln.strip().startswith("- ")
    ][:3]:
        print("     ! " + ln)
    return code, (1 if verdict else 0), ran


def corpus_leg():
    """真语料一票：只跑那一个带链的文件，看它进不进 triage。"""
    if not MOON:
        raise SystemExit(
            "找不到 moon：语料这一格（N6，现网票）跑不了。门禁默认 `--moon moon`，"
            "解析不到时这条腿会静默零 TRIAGE，读起来像变异逃掉了")
    if not CORPUS.is_dir():
        raise SystemExit(
            "语料目录不存在：{}。这一格（N6，现网票）不能跳——跳了 N1 就只剩"
            "手打夹具那一半证据。用 --corpus 指一份外来裸 TIFF 语料".format(CORPUS))
    code, out = run([
        sys.executable, str(GATE), str(CORPUS), "-o", str(OUT / TRIGGER),
        "--moon", MOON, "--strip", "--only", TRIGGER,
    ])
    triage = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("TRIAGE")]
    print("  语料腿(--only {}): rc={} TRIAGE={} 份".format(TRIGGER, code, len(triage)))
    for ln in out.splitlines():
        if "不一致" in ln or "目录链" in ln:
            print("     | " + ln.strip()[:220])
            break
    return code, len(triage)


def need(what, ran, reds, want_red):
    if not ran:
        print("  !! {}：没跑到汇总行，这一格不算红也不算绿".format(what))
        return False
    if (reds > 0) != want_red:
        print("  !! {}：期望{}，测得{}（红数 {}）——区分度丢了".format(
            what, "红" if want_red else "绿", "红" if reds else "绿", reds))
        return False
    print("  OK  {}：期望{}，测得{}".format(what, "红" if want_red else "绿",
                                        "红" if reds else "绿"))
    return True


def parse_args(argv):
    """--moon / --corpus 之外，位置参数是"只跑这几格"。"""
    global MOON, CORPUS
    want, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--moon", "--corpus"):
            if i + 1 >= len(argv):
                print("{} 后面要跟一个值".format(a))
                return None
            i += 1
            if a == "--moon":
                MOON = argv[i]
            else:
                CORPUS = Path(argv[i])
                if not CORPUS.is_absolute():
                    CORPUS = REPO / CORPUS
        elif a.startswith("--moon="):
            MOON = a.split("=", 1)[1]
        elif a.startswith("--corpus="):
            CORPUS = Path(a.split("=", 1)[1])
            if not CORPUS.is_absolute():
                CORPUS = REPO / CORPUS
        else:
            want.append(a)
        i += 1
    if MOON is None:
        found = os.environ.get("MOON") or shutil.which("moon") or shutil.which("moon.exe")
        MOON = found
    if not MOON:
        print("没找到 moon（--moon / 环境变量 MOON / PATH 三处都没指到）："
              "N1、N2 与语料腿都跑不了，只有门禁自测那三格能跑。")
    print("本次配置：moon={} 语料={}".format(MOON or "（无）", CORPUS))
    return want


def main():
    wanted = parse_args(sys.argv[1:])
    if wanted is None:
        return 2
    cases = [c for c in CASES if not wanted or c[0] in wanted]
    if wanted and len(cases) != len(wanted):
        print("没有这些变异编号：{}".format(sorted(set(wanted) - {c[0] for c in cases})))
        return 2
    files = sorted({p for _, _, edits, _ in cases for p, _, _ in edits})
    originals = {p: p.read_bytes() for p in files}
    base_sha = {p: sha(p) for p in files}
    print("== 跑前回读：基线必须干净，且每个变异目标都唯一在位")
    code, reds, ran = moon_test()
    print("  基线 moon test: rc={} ran={} failed={}".format(code, ran, reds))
    if not ran or reds or code != 0:
        print("  基线不干净，先停下（别在红树上验红）")
        return 2
    gcode, gre, grun = gate_selftest()
    if not grun or gre or gcode != 0:
        print("  基线门禁自测不干净，先停下")
        return 2
    ccode, ctriage = corpus_leg()
    if ctriage:
        print("  基线语料腿就有 {} 份 triage，先停下：拿红树当来路是假的".format(ctriage))
        return 2

    caught = 0
    expected = sum(len(t) for _, _, _, t in cases)
    try:
        for tag, label, edits, targets in cases:
            print("\n== {} {}".format(tag, label))
            for path, old, new in edits:
                patch(path, old, new, tag)
            try:
                if "moon" in targets:
                    code, reds, ran = moon_test()
                    caught += need("moon test", ran, reds, True)
                if "gate" in targets:
                    code, reds, ran = gate_selftest()
                    caught += need("门禁自测", ran, reds, True)
                if "corpus" in targets:
                    code, n = corpus_leg()
                    ok = need("真语料 strip 腿", True, n, True)
                    caught += ok
            finally:
                for path in files:
                    path.write_bytes(originals[path])
                # 还原凭据只认 sha。曾经这里是"变异片段还在不在"：N4 的替换串
                # `want = None` 在原文里本来就出现一次（下面那个 except 分支），
                # 于是成功的还原被读成失败，整批停在半路。
                back = [p for p in files if sha(p) != base_sha[p]]
                if back:
                    raise SystemExit("还原失败：{} 的 sha 对不上".format(
                        " ".join(p.name for p in back)))
                print("  [还原] " + " ".join("{}={}".format(p.name, sha(p)) for p in files))
    finally:
        for p in files:
            p.write_bytes(originals[p])

    print("\n== 还原后复跑，确认真绿（N1 的来路票在这里）")
    code, reds, ran = moon_test()
    caught += need("moon test", ran, reds, False)
    gcode, gre, grun = gate_selftest()
    caught += need("门禁自测", grun, gre, False)
    ccode, ctriage = corpus_leg()
    caught += need("真语料 strip 腿", True, ctriage, False)
    print("  [sha 对账] " + " ".join("{}={}".format(p.name, sha(p)) for p in files))
    print("\n期望表态 {} 处，抓到 {} 处".format(expected + 3, caught))
    return 0 if caught == expected + 3 else 1


if __name__ == "__main__":
    sys.exit(main())
