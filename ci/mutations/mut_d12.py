# -*- coding: utf-8 -*-
"""D9-D 变异驱动：容器级那三把尺子，每把都要被单点坏法打红。

M9/M10 打的是**兜底文案**那一格：四批语料上没有一格走到它（走到过的话，上一轮
那里那个作用域不存在的名早炸了），所以它只能靠这里证明自己有区分度。

跑法（在仓库根目录）：python ci/mutations/mut_d12.py
驱动是 ci/crosscheck_selftest.py（不需要语料、不需要 moon）。每处坏法注入一次，
要求退出码非 0 **且** stdout 里出现指名这一格的那句 FAIL——只看退出码会把
"红在别处"当成抓到。跑完按字节还原并核对 sha。
"""

import hashlib
import subprocess
import sys

TARGET = "ci/crosscheck_real.py"
DRIVER = ["ci/crosscheck_selftest.py"]

MUTATIONS = [
    (
        "M1 清单丢掉 XMP URI（只数 Exif 签名）",
        "        return sorted(set(find_all(blob, EXIF_HEAD)) | set(find_all(blob, XMP_URI)))",
        "        return sorted(set(find_all(blob, EXIF_HEAD)))",
        "test_第二份是XMP包也数得到",
    ),
    (
        "M2 「第二份」不再要求前面有一份",
        "    if marks.index(off) == 0:",
        "    if False:",
        "test_说第二份其实是第一份_要红",
    ),
    (
        "M3 断表判据不看停下的原因",
        "    if why not in ok_whys:",
        "    if False:",
        "test_段长越界不是断在段表中间",
    ),
    (
        "M4 断表判据不比偏移",
        "    if stop != off:",
        "    if False:",
        "test_谎报断点_要红",
    ),
    (
        "M5 块长那个数不复核",
        "    if len(blk) != have:",
        "    if False:",
        "test_谎报块长_要红",
    ),
    (
        "M6 块从签名算起（把 6 字节签名算进块里）",
        "                return blob[payload + 6 : off + length]",
        "                return blob[payload : off + length]",
        "test_块长对得上_算设计内",
    ),
    (
        "M7 容器里的块内偏移拿整个文件核（旧 bug）",
        "    view = blk if blk is not None else blob",
        "    view = blob",
        "test_容器里的块内偏移核的是块长",
    ),
    (
        "M8 块边界算不出来时把整个文件当块",
        "        return None\n    if blob[:8] == PNG_SIGNATURE:\n        for kind, off, length in png_chunks(blob)[0]:",
        "        return blob\n    if blob[:8] == PNG_SIGNATURE:\n        for kind, off, length in png_chunks(blob)[0]:",
        "test_块边界算不出来不许当通过",
    ),
    (
        "M9 兜底文案不带引擎那一句",
        '    return "读侧失败，且没有任何一句形状能被字节复核: " + (err or "")[:160]',
        '    return "读侧失败，且没有任何一句形状能被字节复核"',
        "test_引擎那一句必须出现在兜底里",
    ),
    (
        "M10 兜底不做 None 保护（错误句缺失时直接崩）",
        '复核: " + (err or "")[:160]',
        '复核: " + err[:160]',
        "test_err为空也要出一句完整话不崩",
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
        print("{} {}：rc={}，要求 stdout 里有「{}」".format(
            "CAUGHT" if red else "MISSED", name, rc, expect))
        (caught if red else missed).append(name)
    still = hashlib.sha256(open(TARGET, "rb").read()).hexdigest()
    print("还原对账：sha {} vs 基线 {} -> {}".format(
        still[:12], base_sha[:12], "一致" if still == base_sha else "不一致"))
    print("期望表态 {} 处，抓到 {} 处".format(len(MUTATIONS), len(caught)))
    rc, out = run_driver()
    print("还原后复跑自测：rc={}，最后一行 {}".format(
        rc, out.strip().splitlines()[-1]))
    for m in missed:
        print("没抓到：{}".format(m))
    return 0 if (len(caught) == len(MUTATIONS) and still == base_sha and rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
