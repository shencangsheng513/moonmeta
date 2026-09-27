"""D7 变异驱动：strip 那一关的每一条断言，都要在对应坏法下真的红。

做法：往库里/闸里注入一处坏 → 跑一小段真实语料 → 记下红的到底是哪几句 →
**立刻还原并核对字节** → 全部跑完再复跑一次真绿。
还原失败会把脚本停在半路，那比红更糟，所以每次还原都比对 sha256。

跑法（需要 moon 在 PATH 里，语料在 .scratch 下）：
    python -u ci/mutations/mut_d7.py
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "moon.mod").is_file())
JPG = REPO / ".scratch" / "exif-samples" / "jpg"
PNG = REPO / ".scratch" / "png-samples"
CONTAINER = REPO / "moonmeta_container.mbt"
GATE = REPO / "ci" / "crosscheck_real.py"

JPEG_ARM = """    Some(Jpeg) => {
      let (no_exif, had) = jpeg_remove_exif(data)
      let (no_xmp, dropped) = jpeg_drop_xmp(no_exif)
      let (out, dropped_iptc) = jpeg_drop_iptc(no_xmp)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc, })
    }
"""
PNG_ARM = """    Some(Png) => {
      let (no_exif, had) = png_remove_exif(data)
      let (out, dropped) = png_drop_xmp(no_exif)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc: false, })
    }
"""

MUTS = [
    {
        "name": "M1 jpeg strip 跳过 XMP 包（产物里留一整包元数据）",
        "file": CONTAINER,
        "old": JPEG_ARM,
        "new": """    Some(Jpeg) => {
      let (no_exif, had) = jpeg_remove_exif(data)
      let (no_xmp, dropped) = (no_exif, false)
      let (out, dropped_iptc) = jpeg_drop_iptc(no_xmp)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc, })
    }
""",
        "corpus": JPG,
        "limit": 4,
        "expect": [
            "strip 之后产物里还有 XMP 包",
            "strip 之后 read 还报得出 XMP 包",
            "源文件带着 XMP 包，strip 却没有交代摘除它",
        ],
    },
    {
        "name": "M2 png strip 跳过 XMP 包",
        "file": CONTAINER,
        "old": PNG_ARM,
        "new": """    Some(Png) => {
      let (no_exif, had) = png_remove_exif(data)
      let (out, dropped) = (no_exif, false)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc: false, })
    }
""",
        "corpus": PNG,
        "limit": 5,
        "expect": ["strip 之后产物里还有 XMP 包"],
    },
    {
        "name": "M3 摘干净了却报告「本来就没有」（只有句与事实的判据抓得到）",
        "file": CONTAINER,
        "old": JPEG_ARM,
        "new": """    Some(Jpeg) => {
      let (no_exif, _had) = jpeg_remove_exif(data)
      let (no_xmp, _dropped) = jpeg_drop_xmp(no_exif)
      let (out, _iptc) = jpeg_drop_iptc(no_xmp)
      (out, { had_exif: false, dropped_xmp: false, dropped_iptc: false, })
    }
""",
        "corpus": JPG,
        "limit": 4,
        "expect": ["源文件有元数据，strip 却说这个文件本来就没有"],
        # 这一格刻意要求"只红在句上"：产物本身是干净的
        "absent": ["strip 之后产物里还有 XMP 包", "strip 之后 Pillow 还读得到条目"],
    },
    {
        "name": "M4 redact 写得出的文件 strip 拒绝改写（钉住那条不变性质）",
        "file": CONTAINER,
        "old": JPEG_ARM,
        "new": "    Some(Jpeg) => raise UnknownFormat(0)\n",
        "corpus": JPG,
        "limit": 3,
        "expect": ["redact 写得出的文件，strip 退出码"],
    },
    {
        "name": "M5 把 strip 这一关短路掉（一格没跑，地板要出声）",
        "file": GATE,
        "old": '    s_dst = out_dir / (src.stem + ".stripped" + src.suffix)\n',
        "new": (
            '    return []\n'
            '    s_dst = out_dir / (src.stem + ".stripped" + src.suffix)\n'
        ),
        "corpus": JPG,
        "limit": 3,
        "expect": ["strip 这一关一个文件都没跑到"],
    },
    {
        # 这两格打的是 D9-E 新加的那一位。带 APP13 的文件在 `jpg/` 里按字典序
        # 排在第 11~89 位，前四个文件根本走不到这一支——所以它们不靠加大 limit，
        # 而是用 --only 点到一处既有 EXIF 又带 IPTC 包的真照片上。
        "name": "M6 jpeg strip 跳过 IPTC 包（产物里留第二份隐私副本）",
        "file": CONTAINER,
        "old": JPEG_ARM,
        "new": """    Some(Jpeg) => {
      let (no_exif, had) = jpeg_remove_exif(data)
      let (out, dropped) = jpeg_drop_xmp(no_exif)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc: false, })
    }
""",
        "corpus": JPG,
        "limit": 4,
        "only": "landscape_1",
        "expect": [
            "strip 之后 read 还报得出 IPTC 包",
            "strip 之后产物里还有 IPTC/Photoshop 包",
        ],
    },
    {
        "name": "M7 IPTC 摘干净了却不交代（只有句与事实的判据抓得到）",
        "file": CONTAINER,
        "old": JPEG_ARM,
        "new": """    Some(Jpeg) => {
      let (no_exif, had) = jpeg_remove_exif(data)
      let (no_xmp, dropped) = jpeg_drop_xmp(no_exif)
      let (out, _iptc) = jpeg_drop_iptc(no_xmp)
      (out, { had_exif: had, dropped_xmp: dropped, dropped_iptc: false, })
    }
""",
        "corpus": JPG,
        "limit": 4,
        "only": "landscape_1",
        "expect": ["源文件带着 IPTC/Photoshop 包，strip 却没有交代摘除它"],
        # 和 M3 同一条道理：产物是干净的，红只能红在那句话上
        "absent": [
            "strip 之后产物里还有 IPTC/Photoshop 包",
            "strip 之后 read 还报得出 IPTC 包",
        ],
    },
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def as_bytes(s, nl):
    """把模式串换成这个文件自己的换行风格再编码。

    变异与还原全程按字节做：`write_text` 在 Windows 上会把 \n 变成 \r\n，
    那样"还原"会留下一个内容相同、sha 不同的文件，还原检查就成了假警报
    （上一轮真在这里翻过一次车）。
    """
    return s.replace("\n", nl).encode("utf-8")


def run(corpus, limit, out_dir, only=None):
    env = dict(os.environ)
    env["PATH"] = env["PATH"] + ";D:\\moonbit\\bin"
    env["PYTHONIOENCODING"] = "utf-8"
    argv = [
        sys.executable,
        "-u",
        "ci/crosscheck_real.py",
        str(corpus),
        "-o",
        str(out_dir),
        "--limit",
        str(limit),
    ]
    if only:
        argv += ["--only", only]
    proc = subprocess.run(
        argv,
        cwd=str(REPO),
        capture_output=True,
        env=env,
    )
    text = proc.stdout.decode("utf-8", errors="replace")
    return proc.returncode, text, proc.stderr.decode("utf-8", errors="replace")


def triage_count(text):
    for line in text.splitlines():
        if line.startswith("需要分诊的 "):
            return int(line.split()[1])
    return 0


problems = []
caught = 0
DUMP = REPO / ".scratch" / "d7mut_out"
DUMP.mkdir(exist_ok=True)
for i, m in enumerate(MUTS):
    before = len(problems)
    path = m["file"]
    raw = path.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    old = as_bytes(m["old"], nl)
    new = as_bytes(m["new"], nl)
    if raw.count(old) != 1:
        problems.append(
            "{}：注入点命中 {} 次，跳过".format(m["name"], raw.count(old))
        )
        continue
    path.write_bytes(raw.replace(old, new, 1))
    if sha(path) == sha_bytes(raw):
        problems.append(m["name"] + "：变异没落盘")
        continue
    try:
        rc, text, err = run(
            m["corpus"], m["limit"], REPO / ".scratch" / "d7mut", m.get("only")
        )
    finally:
        path.write_bytes(raw)
        restored = sha(path) == sha_bytes(raw)
    (DUMP / "{}.txt".format(i)).write_text(
        text + "\n--- stderr ---\n" + err, encoding="utf-8"
    )
    print("== {}".format(m["name"]))
    print(
        "   rc={}，分诊 {} 个，还原{}".format(
            rc, triage_count(text), "成功" if restored else "**失败**"
        )
    )
    if not restored:
        problems.append(m["name"] + "：还原失败")
    if not text.strip():
        problems.append(m["name"] + "：跑批零输出（先看 dump 的 stderr）")
    if "read 失败" in text:
        # 注入把构建弄坏了：CLI 整个跑不起来，红是红的，但和这条断言无关
        problems.append(m["name"] + "：read 这一步就红了（多半是注入破坏了构建），这一格不算")
    if rc == 0:
        problems.append(m["name"] + "：注入之后仍然全绿")
    for e in m["expect"]:
        got = e in text
        print("   {} {}".format("抓到" if got else "漏了", e))
        if not got:
            problems.append("{}：没抓到「{}」".format(m["name"], e))
    for e in m.get("absent", []):
        if e in text:
            problems.append("{}：不该红的也红了（{}）".format(m["name"], e))
            print("   多抓 {}".format(e))
    print()
    if len(problems) == before:
        caught += 1

rc, text, _err = run(JPG, 4, REPO / ".scratch" / "d7green")
print("== 全部还原后的复跑：rc={}，分诊 {} 个".format(rc, triage_count(text)))
if rc != 0:
    problems.append("还原后复跑不绿")

print()
print("期望表态 {} 处，抓到 {} 处".format(len(MUTS), caught))
if problems:
    print("变异驱动没过关：")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(
    "{} 处坏各处红一次，句与事实的判据不靠字节也抓得到，地板出声；还原后复跑真绿。".format(
        caught
    )
)
