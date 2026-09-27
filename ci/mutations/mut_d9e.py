# -*- coding: utf-8 -*-
"""D9-E 变异驱动：真实语料闸新加的三判据（iptc / unread / strip 第三载体）要各自能红。

这台闸最坏的坏法和它守的东西一样：`iptc_flag_problems` 写成 `return []`、
`unread` 那条偏移比对少一步、`strip_claims` 只数两个载体——**跑批照样全绿**，
只是那一路观察整个不再生效。语料查不出它：语料只会告诉"命中时对不对"，
不会告诉"这一位恒真/恒假时能不能红"。所以这里每种坏法注入一次，跑
`python -B ci/crosscheck_selftest.py`（不起 moon、不碰语料），要求退码非 0
**且** stderr 里出现指名这一格的用例名；跑完按字节还原并核对 sha。

M6 与 M9 各钉一条"正例也得红"：偏移比对挪错域、段码不再比名字时，
连"这一句本来就是对的"那格都会一起塌——那说明正例断言真在数值上站着，
不是只查了个非空。

M10 打的是 D9-E 的原始病灶本身：APP13 里的第二份元数据曾经既不点名也不摘除。

跑法（不需要语料，也不需要 moon）：

    PYTHONUTF8=1 python -u -B ci/mutations/mut_d9e.py
"""

import hashlib
import subprocess
import sys

TARGET = "ci/crosscheck_real.py"
DRIVER = ["ci/crosscheck_selftest.py"]

# (格名, 锚点, 替换, 必须变红的用例名子串)
MUTATIONS = [
    (
        "N1 非 JPEG 容器上的 iptc=true 不再算无中生有",
        '        if flag:\n'
        '            return ["说在有：{} 容器没有成包的 IPTC，iptc 却是 true".format(kind)]\n',
        "",
        ("test_PNG与裸TIFF不许报成包",),
    ),
    (
        "N2 iptc 只查假警报，不查漏报",
        '    if seen and not flag:\n'
        '        return ["说在无：原始字节里搜得到 Photoshop 资源包头，iptc 却是 false"]',
        '    if False:\n'
        '        return ["说在无：原始字节里搜得到 Photoshop 资源包头，iptc 却是 false"]',
        ("test_字节里有却说无必须红",),
    ),
    (
        "N3 包头匹配放宽成前缀（近邻头会被当成包）",
        'IPTC_PACKET_MARKS = {\n    "jpeg": (IPTC_HEAD,),\n}',
        'IPTC_PACKET_MARKS = {\n    "jpeg": (b"Photoshop 3.",)\n}',
        ("test_差一个字节就不算包",),
    ),
    (
        "N4 缺 iptc 键不再出声",
        '    if flag is None:\n        return ["read --json 少了 iptc 键"]\n',
        "",
        ("test_键整个不见了也要出声",),
    ),
    (
        "N5 裸 TIFF 的未解析段一律放行",
        '        return (\n'
        '            [] if not unread else ["tiff 容器不该报出未解析段：{}".format(unread)]\n'
        "        )",
        "        return []",
        ("test_裸TIFF有内容就是错",),
    ),
    (
        "N6 PNG 块类型偏移从类型域挪到长度域（正例一起塌）",
        "        head = blob[offset + 4 : offset + 8]",
        "        head = blob[offset : offset + 4]",
        ("test_一句话说清三种坏法",),
    ),
    (
        "N7 不再拦同一份字节报两遍",
        "    for head in NAMED_HEADS:\n        if payload.startswith(head):",
        "    for head in ():\n        if payload.startswith(head):",
        ("test_同一份字节不许报两遍",),
    ),
    (
        "N8 unread 键整个不见了被当成空列表",
        '    if unread is None:\n        return ["read --json 少了 unread 键"]\n',
        "    if unread is None:\n        return []\n",
        ("test_键整个不见了",),
    ),
    (
        "N9 段码与名字不再比对（指错偏移看不见）",
        "    if marker != bytes([want]):",
        "    if False:",
        ("test_名字与段码对不上", "test_一段坏不掩盖另一段坏"),
    ),
    (
        "N10 strip 那句不再数第三个载体（D9-E 的原始病灶）",
        '    if had_iptc and IPTC_LISTED not in listed:\n'
        '        out.append("源文件带着 IPTC/Photoshop 包，strip 却没有交代摘除它")\n',
        "",
        ("test_有IPTC包却没点名", "test_有IPTC却说三样都没有"),
    ),
    (
        "N11 「本来就没有」的触发条件少算 IPTC",
        "    if (had_exif or had_xmp or had_iptc) and said_absent:",
        "    if (had_exif or had_xmp) and said_absent:",
        ("test_有IPTC却说三样都没有",),
    ),
    (
        "N12 三样都没有却说摘了东西这一格失守",
        "    if not (had_exif or had_xmp or had_iptc) and not said_absent:",
        "    if False:",
        ("test_三样都没有却说摘了东西",),
    ),
    (
        "N13 产物里残留的 IPTC 包不再算红",
        "    if IPTC_HEAD in blob:\n        out.append(",
        "    if False:\n        out.append(",
        ("test_产物里还有包就红_说什么都不算",),
    ),
    (
        "N14 摘了不说也不再算红",
        '        if "IPTC" not in red_out:',
        "        if False:",
        ("test_摘净却没披露必须红",),
    ),
    (
        "N15 IPTC 那一趟去碰共用的 redacted 分母",
        '            out.append("{}：整包 IPTC 已被摘除，但 CLI 没有披露".format(policy))\n'
        "        else:\n"
        "            stats[dropped_key] = stats.get(dropped_key, 0) + 1",
        '            out.append("{}：整包 IPTC 已被摘除，但 CLI 没有披露".format(policy))\n'
        "        else:\n"
        "            stats[dropped_key] = stats.get(dropped_key, 0) + 1\n"
        '            stats["redacted"] = stats.get("redacted", 0) + 1',
        ("test_两趟各记各的键且都不碰redacted",),
    ),
    (
        "N16 源本来没有包也被记成摘除一个",
        "    elif IPTC_HEAD in src_blob:",
        "    elif True:",
        ("test_源本来没有包_既不红也不记账",),
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


def sha():
    return hashlib.sha256(open(TARGET, "rb").read()).hexdigest()


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
    base_sha = sha()
    absent = [n for n, o, _, _ in MUTATIONS if base_text.count(o) != 1]
    print("开跑前锚点清点：{}/{} 恰好在位一次".format(
        len(MUTATIONS) - len(absent), len(MUTATIONS)))
    for n in absent:
        print("        不在位/不唯一：{}".format(n))
    rc0, out0 = run_driver()
    print("基线自检（crosscheck_selftest）：rc={}，{}".format(
        rc0, out0.strip().splitlines()[-1] if out0.strip() else "无输出"))
    if rc0 != 0:
        print("基线不绿，先修闸再谈变异。")
        return 1
    caught = []
    missed = []
    for name, old, new, expects in MUTATIONS:
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
            back = sha()
            if back != base_sha:
                print("!!!   {} 还原失败：sha {} != {}".format(
                    name, back[:12], base_sha[:12]))
        missing = [e for e in expects if e not in out]
        red = rc != 0 and not missing
        line = [l for l in out.strip().splitlines() if l.strip()]
        print("{} {}：rc={}，测得「{}」，要求红在「{}」上".format(
            "CAUGHT" if red else "MISSED", name, rc,
            (line[-1] if line else "无输出")[:48], ",".join(expects)))
        for m in missing:
            print("        没有这一格的红：{}".format(m))
        (caught if red else missed).append(name)
    still = sha()
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
