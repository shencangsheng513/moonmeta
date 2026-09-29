"""D8 变异驱动：新加的每一格"拒绝复核"，都要在对应的谎话下真的红。

这一轮钉的是**库自己报出的数字**：那句拒绝里的 IFD0 偏移、文件字节数、模型重建
字节数、类型码、越界指针偏移、目录表声明的字节数。语料本身抓不到它们——库报错数时，
跑批只会把同一句谎话原样收下并记成"按设计拒绝"。所以这里往库里注入六种谎报，
看对拍脚本那边的字节复核是不是每一处都拦得下来。

语料是 6 个文件的子集，两趟都有：M1–M4 落在 Pillow 解得开的文件上（第一趟），
M5、M6 只能落在 Pillow 解不开的那几个上（crash-*、oom-*）——这两格正是第二趟
存在的理由：读侧拒绝的数字复核不需要一把能解像素的尺子。

判"红"看的是分诊个数与红的到底是哪一句，不看退出码：纯 TIFF 语料里 strip 一格都
跑不到，地板按设计会出声（rc=1），那是正常状态，不能拿它当"注入生效"的证据。

跑法（需要 moon 在 PATH 里，语料在 .scratch/tif-subset 下）：
    python -u ci/mutations/mut_d8.py
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "moon.mod").is_file())
SUBSET = REPO / ".scratch" / "tif-subset"
CONTAINER = REPO / "moonmeta_container.mbt"
TIFF = REPO / "moonmeta_tiff.mbt"

REFUSE_CALL = """    raise TiffNotByteExact(
      u32_at(data, 4, block.little),
      data.length(),
      rebuilt.length(),
    )
"""

MUTS = [
    {
        "name": "M1 拒绝里报一个假的 IFD0 偏移",
        "file": CONTAINER,
        "old": REFUSE_CALL,
        "new": """    raise TiffNotByteExact(
      u32_at(data, 4, block.little) + 1000L,
      data.length(),
      rebuilt.length(),
    )
""",
        "expect": ["文件头自己写的是"],
    },
    {
        "name": "M2 拒绝里把重建长度报成文件长度（那句「会丢字节」就成了谎）",
        "file": CONTAINER,
        "old": REFUSE_CALL,
        "new": """    raise TiffNotByteExact(
      u32_at(data, 4, block.little),
      data.length(),
      data.length(),
    )
""",
        "expect": ["就不成立"],
    },
    {
        "name": "M3 拒绝里把文件长度多报一个字节",
        "file": CONTAINER,
        "old": REFUSE_CALL,
        "new": """    raise TiffNotByteExact(
      u32_at(data, 4, block.little),
      data.length() + 1,
      rebuilt.length(),
    )
""",
        "expect": ["实际"],
    },
    {
        "name": "M4 类型码谎报一位（设计内的类型桶要能被这句谎话打回 triage）",
        "file": TIFF,
        "old": "    None => raise UnsupportedType(tag, type_code)\n",
        "new": "    None => raise UnsupportedType(tag, type_code + 1)\n",
        "expect": ["复核不上"],
    },
    {
        "name": "M5 把越界指针报成块内的偏移",
        "file": TIFF,
        "old": "      raise ValueOffsetOutOfRange(tag, off)\n",
        "new": "      raise ValueOffsetOutOfRange(tag, 0L)\n",
        # 报出来的偏移在字节里没有对应的条目 → 复核不上
        "expect": ["复核不上"],
    },
    {
        "name": "M6 目录表那句谎报声明字节数（第二趟才抓得到：这文件 Pillow 解不开）",
        "file": TIFF,
        "old": "    raise EntryTooLarge(dir_off + 2, 0, count * 12, avail)\n",
        "new": "    raise EntryTooLarge(dir_off + 2, 0, count * 12 + 12, avail)\n",
        "expect": ["那个数字复核不上"],
    },
]


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def as_bytes(s, nl):
    """按文件自己的行尾编码。变异与还原全程走字节：`write_text` 在 Windows
    会把 \\n 翻成 \\r\\n，那样还原检查会留下内容相同、sha 不同的文件。"""
    return s.replace("\n", nl).encode("utf-8")


def run(corpus, out_dir):
    env = dict(os.environ)
    env["PATH"] = env["PATH"] + ";D:\\moonbit\\bin"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [
            sys.executable,
            "-u",
            "ci/crosscheck_real.py",
            str(corpus),
            "-o",
            str(out_dir),
        ],
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


def compiled(text, err):
    """注入没把构建弄坏：坏法必须只改变数字，不能改变能不能跑起来。"""
    return "read 失败" not in text and "Error: [" not in err


problems = []
DUMP = REPO / ".scratch" / "d8mut_out"
DUMP.mkdir(parents=True, exist_ok=True)
for i, m in enumerate(MUTS):
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
    if sha_bytes(path.read_bytes()) == sha_bytes(raw):
        problems.append(m["name"] + "：变异没落盘")
        continue
    try:
        rc, text, err = run(SUBSET, REPO / ".scratch" / "d8mut")
    finally:
        path.write_bytes(raw)
        restored = sha_bytes(path.read_bytes()) == sha_bytes(raw)
    (DUMP / "{}.txt".format(i)).write_text(
        text + "\n--- stderr ---\n" + err, encoding="utf-8"
    )
    n = triage_count(text)
    print("== {}".format(m["name"]))
    print(
        "   rc={}，分诊 {} 个，还原{}".format(
            rc, n, "成功" if restored else "**失败**"
        )
    )
    if not restored:
        problems.append(m["name"] + "：还原失败")
    if not text.strip():
        problems.append(m["name"] + "：跑批零输出（看 dump 的 stderr）")
    if not compiled(text, err):
        problems.append(m["name"] + "：注入破坏了构建或读这一步就红了，这一格不算")
    if n == 0:
        problems.append(m["name"] + "：一处数字撒谎，分诊却一个都没有")
    for e in m["expect"]:
        got = e in text
        print("   {} {}".format("抓到" if got else "漏了", e))
        if not got:
            problems.append("{}：没抓到「{}」".format(m["name"], e))
    print()

rc, text, _err = run(SUBSET, REPO / ".scratch" / "d8green")
print(
    "== 全部还原后的复跑：rc={}，分诊 {} 个".format(rc, triage_count(text))
)
print(
    "   （纯 TIFF 语料里 strip 一格都跑不到，地板按设计出声，"
    "所以这里看的是分诊 0 个）"
)
if triage_count(text) != 0:
    problems.append("还原后复跑仍有分诊")

print()
if problems:
    print("变异驱动没过关：")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(
    "六处谎报各处红一次，六个数字都由文件字节反着算过"
    "（其中指针与目录表那两处只有第二趟抓得到）；还原后复跑真绿。"
)
