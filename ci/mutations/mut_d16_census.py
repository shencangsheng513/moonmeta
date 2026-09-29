# -*- coding: utf-8 -*-
"""D16 变异驱动：查重计数器"扣掉申报人自己"那一层要能红。

为什么这一层值得单独有一簇注入：申报书里"功能重叠"那一格是本项两次被驳回的正中，
而 2026-09-29 把包发到 mooncakes 之后，那 13 个词里有 11 个词的命中列表里出现了
`shencangsheng513/moonmeta` 自己。这个数如果是手算的，它就只是一句形容词；
现在是脚本算的，那脚本就得证明它算得动——扣不掉就会把"重叠面"算大，
凭空扣就会把它算小，两个方向都要有牙齿。

四处坏法各注入一次，跑 `python -B ci/registry_census.py --selftest`（不打网、
不起 moon、不要语料），要求退码非 0 **且** stdout 里出现指名这一格的那句
`问题 <格名>`——只匹配格名不行：同一句格名也出现在它通过时打的那行 `OK` 里。
跑完按字节还原并核对 sha。
"""

import hashlib
import subprocess
import sys

TARGET = "ci/registry_census.py"
DRIVER = ["ci/registry_census.py", "--selftest"]

MUTATIONS = [
    (
        "C1 命中里的自己不当成自己（重叠面被算大——发布之后这一处最可能坏）",
        "    others = [(w, [n for n in names if n != self_name])",
        "    others = [(w, list(names))",
        "问题 命中里有自己时",
    ),
    (
        "C2 words_with_self 恒为 0（扣没扣都不出声）",
        '        "words_with_self": sum(1 for _, _, _, _, names in rows if self_name in names),',
        '        "words_with_self": 0,',
        "问题 一个别人的命中都没有",
    ),
    (
        "C3 模块名不去重不排序（同一个邻居命中三个词就被数成三个邻居）",
        '        "other_names": sorted({n for _, v in others for n in v}),',
        '        "other_names": [n for _, v in others for n in v],',
        "问题 模块名去重后排序",
    ),
    (
        "C4 把自测名单地板从 15 改成 14（名单被删短一格时它就不该再报通过）",
        "    if cells[0] != 15:",
        "    if cells[0] != 14:",
        "问题 自测名单只剩",
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
    print("基线自检（--selftest）：rc={}，最后一行 {}".format(
        rc0, out0.strip().splitlines()[-1] if out0.strip() else "无输出"))
    if rc0 != 0:
        print("基线不绿，先修计数器再谈变异。")
        return 1
    caught, missed = [], []
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
                print("!!!   {} 还原**失败**：sha {} != {}".format(
                    name, back[:12], base_sha[:12]))
        red = rc != 0 and expect in out
        named = [l.strip() for l in out.splitlines() if l.strip().startswith("问题")]
        print("{} {}：rc={}，点名的格数={}，要求 stdout 里有「{}」".format(
            "CAUGHT" if red else "MISSED", name, rc, len(named), expect))
        for l in named:
            print("        " + l[:110])
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
    return 0 if (len(caught) == len(MUTATIONS) and still == base_sha and rc == 0) \
        else 1


if __name__ == "__main__":
    sys.exit(main())
