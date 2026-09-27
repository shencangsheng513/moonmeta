"""原位模式（`--keep-bytes`）的真实语料复核：给"一个字节都不搬"这句话找证据。

裸 TIFF 的重写路径会拒绝相机式布局（`crosscheck_real.py` 里的 `refused-rewrite`
桶），因为整份重建会丢掉目录之间与之后的像素字节。`--keep-bytes` 是那条拒绝的
出路：只把目录表里的条目往前搬、条目数改小、被删条目的外置值清零，
**输出长度永远等于输入长度**。

这个脚本要回答两件事，两件都得有独立证据：

1. **放行与拒绝的理由对不对**——脚本自己按 TIFF 6.0 从文件字节走一遍目录图，
   独立算出"哪些区间要写、哪些区间有人住"，据此预言这个文件该放行还是该拒绝，
   再和引擎的实际决定对账。两个方向的分歧都算 `triage`：引擎放行而脚本说会撞，
   是产物可能坏；引擎拒绝而脚本说这一下谁都不碰，是出路白挖了。
   预言用的遍历顺序（IFD0 → IFD0 的 next 链 → Exif → 它的 next → GPS → Interop）
   与 `seen` 集合的共享方式照着实现的目录发现顺序写；那条一致性由
   `moonmeta_tiff_patch_test.mbt` 的字节级夹具钉住，这里只负责把它推广到
   我们没写过的文件上。
2. **产物到底动了哪些字节**——这是原位模式的全部承诺所在，所以不看措辞、
   直接逐字节比：
   - 长度相等，头 8 字节一模一样；
   - 每一处改动都落在**由输入文件自己算出来的施工区间**里（被改写表的旧条目区
     + 被删条目的外置值区间）。这一条同时是反向闸：在区间外随便改一个字节，
     脚本必须红——`selftest` 里就有一格专门演这个。
   - 像素声明（273/278、324/325、513/514 三对）指着的字节一格都没变；
   - 被删条目的外置值区间逐字节为零；
   - 用我们自己的 `read` 把产物读回来：被点名的条目没了、没点名的还在、
     再 audit 一次应当无可删；
   - Pillow 打得开产物且像素哈希与输入一致。**输入自己就解不开**的那些
     记在脚注 `unreadable-by-pillow` 里（没有像素可对，字节级复核照做），
     不占每份文件一格的桶位——桶合计必须等于语料份数。

拒绝的那一类也不白拿：种类要能从那句拒绝里认出来（撞像素/撞别人的值/表被走两次/
像素声明读不懂），认不出来就落 `triage`。种类之外的数字由 `classify_refusal`
拿这个文件的字节复核。

用法（第一个参数必填，脚本绝不硬编码任何个人路径）：

    python ci/inplace_crosscheck.py 语料目录 [-o 输出目录] [--moon moon可执行文件]
        [--policy strict|privacy] [--strip] [--selftest]

只读语料：产物一律落在 -o 指定的目录（默认 .scratch/inplace-crosscheck/），
且必须在语料目录之外——否则这一轮的 `.inplace` 产物会成为下一轮的语料。
退出码 0 = 没有 triage；1 = 至少一条；2 = 这一轮没开跑（语料目录不存在、
产物目录嵌在语料里、一份都没扫到）。2 单独一档，是因为空跑的退出码绝不能
和"跑完且干净"共用一个数。
"""

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # 量尺不在场要明确出声，不许把该比的格子静默当成比过了
    Image = None

TIFF_SUFFIXES = (".tif", ".tiff")
# 条带那一对是 273/278。279 是 SamplesPerPixel：它和 273 一样是个数组，
# 抄错了不会报错，只会把"像素在哪"读成一小段莫名其妙的区间（本项目真错过一次，
# 所以这一行旁边要有这句话）。
PIXEL_PAIRS = ((273, 278), (324, 325), (513, 514))
POINTER_TAGS = (0x8769, 0x8825, 0xA005)
# 解一张裸 TIFF 的像素绕不开的字段（TIFF 6.0 的图像结构条目：尺寸、位深、
# 压缩、色彩解释、条带/瓦片偏移与长度、解码参数）。按规范独立列出，
# 与实现的 `image_shape` 同源不同笔——两边都写下来还一致，才算钉住。
# GeoTIFF 那几个带位置的字段（33550/33922/34735…）不在清单里：那是位置，不是解码。
# 274 Orientation 在里面：删掉它产物会被 Pillow 解成输入的镜像，"显示方向"
# 这个说法是错的。282/283/296（分辨率）不在：逐份比过像素哈希，删了不动像素。
# 346/347 也在：JPEG 压缩的 TIFF 把公共量化表放在 347（JPEGTables），删掉后
# Pillow 报 `decoder error -2`（语料里 4 份）。这是 274 那次的同一课——
# "看起来只管显示/编码细节"的字段，判据要拿产物解码结果说话，不能靠猜。
IMAGE_SHAPE = frozenset(
    (
        256, 257, 258, 259, 262, 266, 273, 274, 277, 278, 279, 284, 317, 320,
        322, 323, 324, 325, 326, 338, 339, 340, 341, 346, 347, 530, 531, 532,
    )
)
DIRS = ("IFD0", "Exif", "GPS", "Interop")
MAX_ENTRIES = 4096

# TIFF 6.0 的类型宽度，但只留这一版**解得码**的那些：11/12/13 规范里有定义、
# 本库按边界条款不解码，所以在这里也一并当作读不通——跟着解码能力走，
# 不跟着规范走。（语料里 `no_rows_per_strip.tif` 就是撞在这一格上：
# 脚本照规范算成"能改写"，引擎却在算值区间那一步拒绝了。）
TYPE_SIZES = {
    1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
}

# 引擎那几句拒绝的形状（moonmeta_error.mbt 的 Show 措辞）。只用来认种类，
# 不用来判放行与否：认不出种类 = 一句我们从没打算说的话，那才是要人看的。
RE_SHARED = re.compile(
    r"refusing to write this bare TIFF in place: tag (0x[0-9a-f]{4}) would write "
    r"offsets (\d+)\.\.(\d+), but those bytes are already (.+) \(of the table at "
    r"offset (\d+)\)"
)
RE_CYCLE = re.compile(
    r"refusing to write this bare TIFF in place: the table at offset (\d+) is "
    r"reached twice"
)
RE_OPAQUE = re.compile(
    r"refusing to write this bare TIFF in place: tag (0x[0-9a-f]{4}) declares "
    r"where the pixel data sits, but (.+?);"
)
RE_INPLACE_SAID = re.compile(r"原位模式：文件长度不变（(\d+) 字节）")

# 目录图连读都不读得通的种类：那一步还没走到"要不要落笔"，
# 所以不去套原位拒绝的那几句措辞，另记一桶、按种类分开数。
READ_KINDS = (
    "read-past-eof",
    "table-does-not-fit",
    "unsupported-type",
    "value-ptr-out-of-range",
)
# 原位 strip 成功那句断言的原文（cmd/main/main.mbt 的 `inplace_strip_said`）。
# 抄在这里是有意的：措辞一改这一格就红，人要红着去看一眼，不许静默放过。
# 它不是 `crosscheck_real.py` 里那句"元数据已整段摘除"：裸 TIFF 的图像说明和
# 元数据同表，原位这条路做不到"整段"，那句谎话宁可不省。
STRIP_AFFIRM = "原位摘除非解码条目："
# 同一句话里那个从产物里数回来的条数：话里的数字必须等于产物 IFD0 的真条目数。
RE_KEPT = re.compile(r"IFD0 里留着 (\d+) 条图像解码必需的字段")


def read_key(kind):
    return "refused-read-" + kind


class CannotPredict(Exception):
    """目录图独立走不通：这一份没有预言。不许当放行，也不许当设计内拒绝。"""


class Refuse(Exception):
    """预言出的拒绝。kind 与实现里的三种拒绝同名，落笔之前就判得出。"""

    def __init__(self, kind, tag=None, off=None, owner=None, desc=None, at=None):
        super().__init__(kind)
        self.kind = kind
        self.tag = tag
        self.off = off
        self.owner = owner
        self.desc = desc
        self.at = at


def run_moon(moon, args, cwd):
    proc = subprocess.run(
        [moon, "run", "cmd/main", "--", *args], cwd=str(cwd), capture_output=True
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def last_json(out):
    text = out.strip()
    if not text:
        return None, "没有输出"
    line = text.splitlines()[-1]
    try:
        return json.loads(line), None
    except json.JSONDecodeError as e:
        return None, "JSON 解析失败: {} / {!r}".format(e, line[:160])


def read_json(moon, repo, path):
    code, out = run_moon(moon, ["read", str(path), "--json"], repo)
    if code != 0:
        return None, out.strip()[:200]
    return last_json(out)


def audit_findings(moon, repo, path, policy):
    code, out = run_moon(
        moon, ["audit", str(path), "--policy", policy, "--json"], repo
    )
    if code != 0:
        return None
    doc, _ = last_json(out)
    return None if doc is None else doc["findings"]


def dirs_of(doc):
    return {d["dir"]: {e["tag"] for e in d["entries"]} for d in doc["directories"]}


def pixel_hash(path):
    with Image.open(path) as im:
        return hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()


def runs(a, b):
    """两串等长字节里所有不相等的极大连续段。"""
    out = []
    i, n = 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    if len(a) != len(b):
        out.append((n, max(len(a), len(b))))
    return out


def merge(regions):
    out = []
    for f, t in sorted(regions):
        if out and f <= out[-1][1]:
            out[-1][1] = max(out[-1][1], t)
        else:
            out.append([f, t])
    return [(f, t) for f, t in out]


def inside(region, covered):
    return any(c <= region[0] and region[1] <= c1 for c, c1 in covered)


class TIFF:
    """按这一个文件自己的头解释它的字节。"""

    def __init__(self, blob):
        if len(blob) < 8:
            raise CannotPredict("文件不到 8 字节，连 TIFF 头都没有")
        if blob[:2] == b"II":
            self.le = True
        elif blob[:2] == b"MM":
            self.le = False
        else:
            raise CannotPredict("头两字节既不是 II 也不是 MM")
        self.blob = blob
        if self.u16(2) != 42:
            raise CannotPredict("偏移 2 的版本号不是 42")

    def u16(self, off):
        if off < 0 or off + 2 > len(self.blob):
            raise Refuse("read-past-eof", off=off)
        return struct.unpack_from("<H" if self.le else ">H", self.blob, off)[0]

    def u32(self, off):
        if off < 0 or off + 4 > len(self.blob):
            raise Refuse("read-past-eof", off=off)
        return struct.unpack_from("<I" if self.le else ">I", self.blob, off)[0]

    def table(self, off):
        n = self.u16(off)
        body = off + 2 + 12 * n
        if n > MAX_ENTRIES or body + 4 > len(self.blob):
            raise Refuse("table-does-not-fit", off=off)
        entries = []
        for i in range(n):
            slot = off + 2 + 12 * i
            tag, typ, count = self.u16(slot), self.u16(slot + 2), self.u32(slot + 4)
            size = TYPE_SIZES.get(typ)
            if size is None:
                raise Refuse("unsupported-type", tag=tag)
            total = count * size
            inline = total <= 4
            voff = slot + 8 if inline else self.u32(slot + 8)
            if not inline and (voff < 0 or voff + total > len(self.blob)):
                raise Refuse("value-ptr-out-of-range", tag=tag, off=voff)
            entries.append(
                dict(
                    tag=tag, typ=typ, count=count, total=total,
                    slot=(slot, slot + 12), voff=voff, inline=inline,
                )
            )
        return dict(off=off, entries=entries, body=body, next=self.u32(body))

    def pointer(self, entries, tag):
        """子目录指针。形状不对（不是单个 LONG）按"没有"处理，与实现一致。"""
        for e in entries:
            if e["tag"] == tag and e["typ"] == 4 and e["total"] == 4:
                return self.u32(e["slot"][0] + 8)
        return None

    def numbers(self, e):
        """SHORT/LONG 数组读成一串数字；形状不对就承认看不懂。"""
        if e["typ"] not in (3, 4):
            raise Refuse("opaque", tag=e["tag"], desc="类型码 %d" % e["typ"])
        raw = self.blob[e["voff"] : e["voff"] + e["total"]]
        code = "H" if e["typ"] == 3 else "I"
        fmt = ("<" if self.le else ">") + "%d" % e["count"] + code
        return list(struct.unpack_from(fmt, raw, 0))

    def graph(self):
        """照实现的发现顺序走一遍，返回 (要改写的表, 只登记的表)。"""
        seen = set()
        mine, foreign = [], []

        def visit(off, name, bucket):
            if off in seen:
                raise Refuse("cycle", off=off)
            seen.add(off)
            t = self.table(off)
            t["name"] = name
            bucket.append(t)
            return t

        def chain(start, label):
            nxt, k = start, 0
            while nxt:
                t = visit(nxt, "%s#%d" % (label, k), foreign)
                nxt = t["next"]
                k += 1

        ifd0 = visit(self.u32(4), "IFD0", mine)
        chain(ifd0["next"], "IFD0next")
        exif = None
        eo = self.pointer(ifd0["entries"], 0x8769)
        if eo is not None:
            exif = visit(eo, "Exif", mine)
            chain(exif["next"], "Exifnext")
        go = self.pointer(ifd0["entries"], 0x8825)
        if go is None and exif is not None:
            go = self.pointer(exif["entries"], 0x8825)
        if go is not None:
            t = visit(go, "GPS", mine)
            chain(t["next"], "GPSnext")
        if exif is not None:
            io = self.pointer(exif["entries"], 0xA005)
            if io is not None:
                t = visit(io, "Interop", mine)
                chain(t["next"], "Interopnext")
        return mine, foreign

    def pixel_guards(self, tables):
        """像素数据声明在哪儿，哪儿就不许碰。三对标签，配对缺半边算读不懂。"""
        out = []
        for t in tables:
            for o_tag, c_tag in PIXEL_PAIRS:
                offs = [e for e in t["entries"] if e["tag"] == o_tag]
                cnts = [e for e in t["entries"] if e["tag"] == c_tag]
                if not offs or not cnts:
                    if offs or cnts:
                        raise Refuse("opaque", tag=(offs or cnts)[0]["tag"],
                                     desc="配对缺半边")
                    continue
                ovals, cvals = self.numbers(offs[0]), self.numbers(cnts[0])
                if len(ovals) != len(cvals):
                    raise Refuse("opaque", tag=offs[0]["tag"], desc="条数不配对")
                for o, c in zip(ovals, cvals):
                    if c == 0:
                        continue
                    if o < 0 or o + c > len(self.blob):
                        raise Refuse("opaque", tag=offs[0]["tag"], desc="声明越出文件")
                    out.append((o, o + c, t["off"], "像素数据本身"))
        return out


def plan(tif, named, strip_mode):
    """独立算一遍施工单。返回 (dropped 数, 施工区间, 要清零的区间)。

    `named` 是 (目录名, 编号) 的集合：这个策略点名要删的那些。子目录指针
    是结构不是数据，两种删法都不动它——这一条与实现同源。
    """
    mine, foreign = tif.graph()
    jobs, doomed = [], []
    dropped = 0
    for t in mine:
        keep = []
        for e in t["entries"]:
            if e["tag"] in POINTER_TAGS:
                hit = False  # 子目录指针是结构，两种删法都不动
            elif strip_mode:
                # 图像解码字段只可能住在 IFD0：子目录表里同样的编号是别的含义。
                hit = t["name"] != "IFD0" or e["tag"] not in IMAGE_SHAPE
            else:
                hit = (t["name"], e["tag"]) in named
            if hit:
                dropped += 1
                if not e["inline"]:
                    doomed.append((e["voff"], e["voff"] + e["total"], e["tag"], t["off"]))
            else:
                keep.append(e)
        jobs.append((t["off"], len(t["entries"]), keep, t["body"]))
    if dropped == 0:
        # 无事可做时实现直接原样交回，一个字节都不写；那种情况下
        # "像素声明读不懂"根本不构成危险。这条提前返回必须与实现同步。
        return dict(
            dropped=0, disclosed=[], scrub=[], jobs=[], mine_bytes=tif.blob
        )
    guards = [(0, 8, 0, "文件自己的 TIFF 头", "header")]
    for t in foreign:
        guards.append((t["off"], t["body"] + 4, t["off"], "本模式只读的目录表", "table"))
        for e in t["entries"]:
            if not e["inline"]:
                guards.append((e["voff"], e["voff"] + e["total"], t["off"],
                               "只登记那张表里的一个值", "table-value"))
    for off, old, keep, body in jobs:
        guards.append((body, body + 4, off, "表末尾那条 next 指针", "table"))
        for e in keep:
            guards.append((e["slot"][0], e["slot"][1], off, "本次保留的一个槽位", "kept-slot"))
            if not e["inline"]:
                guards.append((e["voff"], e["voff"] + e["total"], off,
                               "本次保留的一个值", "kept-value"))
    guards += [(f, t, o, d, "pixel") for f, t, o, d in tif.pixel_guards(mine + foreign)]

    def check_free(frm, to, tag, self_off):
        if frm >= to:
            return
        for g0, g1, owner, _desc, kind in guards:
            if frm < g1 and g0 < to and not (kind == "kept-slot" and owner == self_off):
                raise Refuse(
                    "shared", tag=tag, off=frm, owner=owner, desc=kind, at=(frm, to)
                )

    scrub = []
    for f, t, tag, owner in doomed:
        if t > f + 4:
            check_free(f, t, tag, None)
            scrub.append((f, t))
    disclosed = []
    for off, old, keep, body in jobs:
        dest = off + 2 + 12 * len(keep)
        check_free(off, dest, 0, off)
        check_free(dest, body, 0, off)
        disclosed.append((off, body))
    return dict(
        dropped=dropped,
        disclosed=disclosed + scrub,
        scrub=scrub,
        jobs=jobs,
        mine_bytes=apply_plan(tif, jobs, scrub),
    )


def apply_plan(tif, jobs, scrub):
    """按同一份施工单独立算一遍"本该写出的字节"。

    这不是多余的一步：产物与它逐字节对上，等于两条互不知情的实现（MoonBit 的
    `apply_plan` 与这里）在同一份陌生文件上写出同一份答案。对不上就是要人看，
    而且第一处差异的偏移会直接报出来。
    """
    blob = tif.blob
    out = bytearray(blob)
    # 与 MoonBit 那一侧同一个承重顺序：先清被删条目的外置值，再搬槽位。
    # 一个值指针可以指到本表自己的槽位区（畸形输入就是这么造的），反过来的话
    # 这一刀清零会落在刚搬好的保留条目上，产物当场读不回来。
    for f, t in scrub:
        out[f:t] = b"\x00" * (t - f)
    for off, old, keep, body in jobs:
        w = off + 2
        for e in keep:
            src = e["slot"][0]
            out[w : w + 12] = blob[src : src + 12]
            w += 12
        struct.pack_into("<H" if tif.le else ">H", out, off, len(keep))
        # next 指针跟着计数走：读侧按 off + 2 + 12n 找它，光把 n 改小，
        # 那里就落在清零的表尾上，链读出来是 0。源从 blob 读，不从 out 读。
        out[w : w + 4] = blob[body : body + 4]
        for i in range(w + 4, body):
            out[i] = 0
    return bytes(out)


def classify_refusal(text, blob):
    """那句拒绝说的是哪一种、报的是哪些数。返回 (种类, 数字字典或 None, 问题列表)。

    种类认不出来 = 一句我们从没打算说的话，那才是要人看的东西；
    数字本身不在这里判对错，交给调用方与独立预言的那份对账。
    """
    out = []
    m = RE_SHARED.search(text)
    if m:
        nums = {
            "tag": int(m.group(1), 16),
            "frm": int(m.group(2)),
            "to": int(m.group(3)),
            "desc": m.group(4),
            "owner": int(m.group(5)),
        }
        if nums["to"] <= nums["frm"]:
            out.append("说要在 {}..{} 落笔，区间是倒的".format(nums["frm"], nums["to"]))
        if nums["to"] > len(blob):
            out.append(
                "说的区间 {}..{} 越出文件（{} 字节）".format(
                    nums["frm"], nums["to"], len(blob)
                )
            )
        return "shared", nums, out
    m = RE_CYCLE.search(text)
    if m:
        off = int(m.group(1))
        if not (8 <= off < len(blob)):
            out.append(
                "说偏移 {} 的表被走了两次，那个数不在文件（{} 字节）里".format(off, len(blob))
            )
        return "cycle", {"off": off}, out
    m = RE_OPAQUE.search(text)
    if m:
        return "opaque", {"tag": int(m.group(1), 16), "reason": m.group(2)}, out
    return None, None, ["认不出这是哪一种原位拒绝: " + text.strip()[:200]]


def chain_digest(tif):
    """读侧眼里的目录形状：每张表的偏移 + 它那条 next 指针的值。

    原位模式承诺"只删条目、一个字节都不搬"，那这条形状在产物里必须与输入
    逐项相同。它躲得过本函数隔壁那条"改动落在施工区间之外"的检查——
    next 就落在点名的表尾里，改动合法，可链值读出来是 0。
    """
    mine, foreign = tif.graph()
    return sorted((t["off"], t["next"]) for t in mine + foreign)


def verify_product(tif, src_blob, dst_blob, disclosed, scrub):
    """产物复查。返回问题列表，空表 = 这一格过了。"""
    out = []
    if len(dst_blob) != len(src_blob):
        out.append("长度变了：{} -> {}".format(len(src_blob), len(dst_blob)))
        return out
    if dst_blob[:8] != src_blob[:8]:
        out.append("TIFF 头被改了")
    covered = merge(disclosed)
    for f, t in runs(src_blob, dst_blob):
        if not inside((f, t), covered):
            out.append(
                "改动落在施工区间之外：[{},{}) 只被 {} 覆盖".format(
                    f, t, ["[{},{})".format(a, b) for a, b in covered][:4]
                )
            )
            break
    try:
        pixels = tif.pixel_guards(tif.graph()[0] + tif.graph()[1])
    except Refuse as e:
        pixels = []
        out.append("产物复查读不懂像素声明（{}）".format(e.kind))
    for f, t, _owner, _d in pixels:
        if src_blob[f:t] != dst_blob[f:t]:
            out.append("像素声明的字节变了：[{},{}]".format(f, t))
            break
    for f, t in scrub:
        if any(dst_blob[f:t]):
            out.append("被删条目的外置值没有清零：[{},{}]".format(f, t))
            break
    try:
        want = chain_digest(tif)
    except (Refuse, CannotPredict):
        want = None  # 输入本身就画不出这张图，那这一格没资格下结论
    if want is not None:
        try:
            got = chain_digest(TIFF(dst_blob))
        except (Refuse, CannotPredict) as e:
            got = "读不通（{}）".format(getattr(e, "kind", e))
        if got != want:
            out.append("目录链的形状变了：输入 {} -> 产物 {}".format(want, got))
    return out


def check_one(moon, repo, src, out_dir, stats, feet, strip_mode, policy):
    """一个文件的一整趟。返回 (桶名, 说明列表)。

    不变式：每份文件在 `stats` 里恰好进一个桶（`feet` 是旁证，不算桶位）。
    合计那行拿这条对账，多算一次就会红。
    """
    notes = []
    blob = src.read_bytes()
    try:
        tif = TIFF(blob)
    except CannotPredict as e:
        stats["not-tiff"] = stats.get("not-tiff", 0) + 1
        return "not-tiff", [str(e)]
    doc, err = read_json(moon, repo, src)
    if doc is None:
        stats["unreadable-by-us"] = stats.get("unreadable-by-us", 0) + 1
        return "unreadable-by-us", [(err or "")[:200]]
    if strip_mode:
        named = set()
    else:
        findings = audit_findings(moon, repo, src, policy)
        if findings is None:
            stats["audit-failed"] = stats.get("audit-failed", 0) + 1
            return "triage", ["audit --json 非零退出"]
        named = {(f["dir"], f["tag"]) for f in findings}

    predicted = None
    pl = None
    dropped = disclosed = scrub = None
    try:
        pl = plan(tif, named, strip_mode)
        dropped, disclosed, scrub = pl["dropped"], pl["disclosed"], pl["scrub"]
    except Refuse as e:
        predicted = e
    except CannotPredict as e:
        stats["cannot-predict"] = stats.get("cannot-predict", 0) + 1
        return "cannot-predict", [str(e)]

    cmd = ["strip" if strip_mode else "redact"]
    if not strip_mode:
        cmd += ["--policy", policy]
    dst = out_dir / (src.stem + ".inplace" + src.suffix)
    # 上一轮的同名产物必须先清掉：不然"拒绝改写却写出了文件"这一格
    # 测的是脚本自己的历史，不是这一次的运行。
    if dst.exists():
        dst.unlink()
    code, out = run_moon(moon, cmd + ["--keep-bytes", str(src), "-o", str(dst)], repo)

    if code != 0:
        # 那句"文件长度不变"是做完的凭证，不是打算做的口号：一次没写出任何
        # 文件的运行里出现它，就是在替一个没发生的改动背书。
        if RE_INPLACE_SAID.search(out):
            stats["triage"] = stats.get("triage", 0) + 1
            return "triage", [
                "拒绝改写却已经把「文件长度不变」说了出去：" + out.strip()[:200]
            ]
        if dst.exists():
            stats["triage"] = stats.get("triage", 0) + 1
            return "triage", ["拒绝改写却仍然写出了 {}".format(dst.name)]
        if predicted is not None and predicted.kind in READ_KINDS:
            # 目录图连读都不读得通，那就轮不到"原位改写要不要落笔"这一步。
            # 这一桶不去套原位拒绝的措辞：那种句子在这里本来就不该出现。
            # 只点二级桶名：一份文件占一格，`refused` 的合计靠前缀归拢。
            bucket = read_key(predicted.kind)
            stats[bucket] = stats.get(bucket, 0) + 1
            return bucket, []
        kind, nums, problems = classify_refusal(out, blob)
        if predicted is None:
            problems.append(
                "脚本预言这个文件能原位改写（要动 {} 条），引擎却拒绝了".format(dropped)
            )
        elif kind is None:
            pass  # 脚本说该拒绝、引擎也确实拒绝了，但句子认不出种类：problems 里已有那句
        elif kind != predicted.kind:
            problems.append(
                "两边拒绝的理由不是同一种：引擎={} 脚本={}".format(kind, predicted.kind)
            )
        else:
            problems += compare_numbers(kind, nums, predicted)
        if problems:
            stats["triage"] = stats.get("triage", 0) + 1
            return "triage", problems + [out.strip()[:200]]
        bucket = "refused-" + kind
        stats[bucket] = stats.get(bucket, 0) + 1
        return bucket, []

    # 引擎落笔了。预言说该拒绝的每一格都要人看。
    if predicted is not None:
        stats["triage"] = stats.get("triage", 0) + 1
        return "triage", [
            "引擎改写了，脚本却预言会因「{}」拒绝".format(predicted.kind),
            out.strip()[:200],
        ]
    if not dst.exists():
        stats["triage"] = stats.get("triage", 0) + 1
        return "triage", ["退出码 0 却没有产物"]
    if dropped == 0:
        # 无事可做：这一条路的承诺退化成"原样交回"，那就逐字节比。
        if dst.read_bytes() != blob:
            stats["triage"] = stats.get("triage", 0) + 1
            return "triage", ["无事可做却写出了不同的字节"]
        stats["identity"] = stats.get("identity", 0) + 1
        return "identity", []

    said = RE_INPLACE_SAID.search(out)
    if said is None:
        notes.append("原位改写成功了却没说那句话（承诺必须当场声明）")
    elif int(said.group(1)) != len(blob):
        notes.append("话里说长度 {}，实际文件 {} 字节".format(said.group(1), len(blob)))
    if strip_mode and STRIP_AFFIRM not in out:
        notes.append("摘除非解码条目却没有说「{}」".format(STRIP_AFFIRM))
    if strip_mode:
        # 那句里的条数是 CLI 从产物读回来的。这里用脚本自己的目录读者再数一遍：
        # 两个来源不一致才放行，比"话里有个数"严。
        kept_said = RE_KEPT.search(out)
        real = product_ifd0_kept(dst)
        if kept_said is None and real not in (None, 0):
            notes.append(
                "产物 IFD0 里留着 {} 条解码字段，那句话却没数出来".format(real)
            )
        elif kept_said is not None and real is None:
            notes.append("话里数了解码字段，产物自己却读不回一张 IFD0")
        elif kept_said is not None and int(kept_said.group(1)) != real:
            notes.append(
                "话里说留着 {} 条，产物 IFD0 实际 {} 条".format(
                    kept_said.group(1), real
                )
            )
    got_bytes = dst.read_bytes()
    mine = pl["mine_bytes"]
    if got_bytes != mine:
        at = next(
            (i for i in range(min(len(got_bytes), len(mine))) if got_bytes[i] != mine[i]),
            None,
        )
        notes.append(
            "两条独立实现写出的字节不一致：第一处差异在偏移 {}（脚本 {}，引擎 {}），"
            "长度 {} vs {}".format(
                at,
                None if at is None else mine[at],
                None if at is None else got_bytes[at],
                len(mine),
                len(got_bytes),
            )
        )
    notes += verify_product(tif, blob, got_bytes, disclosed, scrub)

    after_doc, after_err = read_json(moon, repo, dst)
    if after_doc is None:
        notes.append("产物我们自己读不回来: " + (after_err or "")[:200])
    else:
        before, after = dirs_of(doc), dirs_of(after_doc)
        # 期望全部从这个文件读回来的条目推：redact 的是 `audit --json` 点名的那些
        # （策略只有库一个来源）；strip 的是"除 IFD0 图像解码字段以外"的全部。
        gone_expected = {
            (d, t)
            for d in DIRS
            for t in before.get(d, set())
            if t not in POINTER_TAGS
            and not (strip_mode and d == "IFD0" and t in IMAGE_SHAPE)
            and (strip_mode or (d, t) in named)
        }
        still = sorted((d, t) for d, t in gone_expected if t in after.get(d, set()))
        if still:
            notes.append("该删的条目还在产物里: {}".format(still[:6]))
        lost = sorted(
            (d, t)
            for d in DIRS
            for t in before.get(d, set())
            if (d, t) not in gone_expected and t not in after.get(d, set())
        )
        if lost:
            notes.append("没点名的条目反而没了: {}".format(lost[:6]))
        residue = audit_findings(moon, repo, dst, policy)
        if residue is None:
            notes.append("产物 audit 非零退出")
        elif residue:
            notes.append(
                "产物里还剩 {} 条敏感条目: {}".format(
                    len(residue), [r["name"] for r in residue][:6]
                )
            )
    if Image is None:
        feet["no-pillow"] = feet.get("no-pillow", 0) + 1
    else:
        try:
            if pixel_hash(src) != pixel_hash(dst):
                notes.append("像素哈希变了")
        except Exception as e:
            if pixel_ok(src):
                notes.append("输入能解像素、产物不能: {}".format(e))
            else:
                feet["unreadable-by-pillow"] = (
                    feet.get("unreadable-by-pillow", 0) + 1
                )
    if notes:
        stats["triage"] = stats.get("triage", 0) + 1
        return "triage", notes
    stats["ok"] = stats.get("ok", 0) + 1
    return "ok", notes


# 引擎那句 Shared 里对保护区的叫法（moonmeta_error.mbt 的 region_desc）。
# 这张表是"引擎的措辞 → 脚本自己的守卫种类"，只用来对账：措辞一改这里就认不出，
# 那一格会红到人面前——这正是要的效果，不许让它静默变绿。
GUARD_PHRASE = {
    "header": "the file's own TIFF header",
    "table": "a directory this mode only reads",
    "table-value": "a value of a directory this mode only reads, at offset",
    "kept-slot": "an entry slot this run keeps, at offset",
    "kept-value": "a value this run keeps, at offset",
    "pixel": "the image data itself, declared at offset",
}

# 引擎那句 opaque 里"读不懂哪一种"的说法（moonmeta_error.mbt 的 opaque_form），
# 与脚本自己的四种读不懂一一对应。句子换词、这张表没跟上就会红——
# 四种读不懂要是塌回一句，"引擎说的是不是同一件事"就没法判了。
OPAQUE_PHRASE = {
    "配对缺半边": "its partner entry is missing",
    "条数不配对": "its partner entry lists a different number of values",
    "声明越出文件": "the pixel range it declares runs past the end of the file",
}
RE_OPAQUE_CODE = re.compile(
    r"its value is TIFF type (\d+), not a list of byte offsets"
)


def compare_opaque(nums, predicted):
    """"读不懂像素声明"有两种以上，说的是不是同一种也得对账。"""
    reason = nums.get("reason", "")
    desc = predicted.desc
    if desc is not None and desc.startswith("类型码 "):
        code = desc[len("类型码 ") :]
        m = RE_OPAQUE_CODE.search(reason)
        if m is None:
            return [
                "脚本说的是值不是偏移表（类型码 {}），引擎那句却没提类型码：「{}」".format(
                    code, reason
                )
            ]
        if m.group(1) != code:
            return ["说的类型码对不上：引擎 {} 脚本 {}".format(m.group(1), code)]
        return []
    want = OPAQUE_PHRASE.get(desc)
    if want is None:
        return ["脚本这边冒出一个没映射的读不懂种类：{}".format(desc)]
    if reason != want:
        return [
            "读不懂的是哪一种，两边说法不同：引擎「{}」脚本以为是「{}」".format(
                reason, want
            )
        ]
    return []


def compare_numbers(kind, nums, predicted):
    """种类对上了以后，那几个数字也得是同一批数。返回问题列表。"""
    out = []
    if kind != "shared":
        want = predicted.off if kind == "cycle" else predicted.tag
        got = nums["off"] if kind == "cycle" else nums["tag"]
        if want != got:
            out.append(
                "说的位置不是同一处：引擎 {} 脚本 {}".format(got, want)
            )
        if kind == "opaque":
            out += compare_opaque(nums, predicted)
        return out
    if nums["tag"] != predicted.tag:
        out.append(
            "撞的条目不是同一条：引擎 0x{:04x} 脚本 0x{:04x}".format(nums["tag"], predicted.tag)
        )
    if (nums["frm"], nums["to"]) != tuple(predicted.at):
        out.append(
            "要写的区间对不上：引擎 {}..{} 脚本 {}..{}".format(
                nums["frm"], nums["to"], predicted.at[0], predicted.at[1]
            )
        )
    if nums["owner"] != predicted.owner:
        out.append(
            "归属的目录表对不上：引擎 {} 脚本 {}".format(nums["owner"], predicted.owner)
        )
    phrase = GUARD_PHRASE.get(predicted.desc)
    if phrase is None:
        out.append("脚本这边冒出一个没映射的守卫种类：{}".format(predicted.desc))
    elif not nums["desc"].startswith(phrase):
        out.append(
            "撞上的那段字节两边叫法不同：引擎「{}」脚本以为是「{}」".format(nums["desc"], phrase)
        )
    return out


def product_ifd0_kept(path):
    """产物 IFD0 里还剩几条条目（子目录指针不算：CLI 数的是解出来的条目）。

    读不回来返回 None——那是"没数成"，不是"数到 0"。
    """
    try:
        tif = TIFF(path.read_bytes())
        return sum(
            1 for e in tif.table(tif.u32(4))["entries"] if e["tag"] not in POINTER_TAGS
        )
    except (Refuse, CannotPredict, IndexError, ValueError, struct.error):
        return None


def pixel_ok(path):
    try:
        with Image.open(path) as im:
            im.load()
        return True
    except Exception:
        return False


def out_dir_inside_corpus(corpus, out_dir):
    """产物目录落在语料目录里面吗？（含同一个目录这一种）

    与 `ci/crosscheck_real.py` 里同名那道拒绝同口径：本脚本的产物后缀是
    `.inplace.tif`，落在语料里面就会被下一轮的 `rglob` 当成语料读——
    "语料 104 份"这种分母正是这么被自己的产物顶上去的。
    """
    try:
        c = Path(corpus).resolve()
        o = Path(out_dir).resolve()
    except OSError:
        return False
    return c == o or c in o.parents


def check_layout(corpus, out_dir):
    """落笔之前的两道闸：语料在不在、产物目录嵌没嵌在语料里。通过才建目录。

    返回 (可用产物目录, None)，或 (None, 理由)。语料不存在那一格必须在这里
    拦住：`rglob` 对不存在的目录不抛异常，它安静地扫出 0 份，然后
    "分母自证 0 vs 0 -> OK"、退出码 0 —— 一次空跑就这样变成了放行。

    `main()` 与自测走的是**同一个**函数。分开放就白放：判据单独测绿了，
    `main()` 里却仍是"先 mkdir 再判"，那个空目录照样凭空多出来。
    """
    if not Path(corpus).is_dir():
        return None, "语料目录不存在：{}。空跑的退出码是 0，不能当成放行。".format(corpus)
    if out_dir_inside_corpus(corpus, out_dir):
        return None, (
            "输出目录 {} 落在语料目录 {} 里面：这一轮写的 `.inplace` 产物会被"
            "下一轮当语料扫到，扫到的份数就不再是语料的分母了。请把 -o 指到"
            "语料之外。".format(out_dir, corpus)
        )
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    return Path(out_dir), None


def refuse_empty_scan(files, corpus, only=None):
    """扫到 0 份＝这一轮什么都没测，要出声而不是退 0。"""
    if files:
        return None
    return "在 {} 里{}一个 TIFF 都没扫到：这一轮什么都没测。".format(
        corpus, "（--only {}）".format(only) if only else ""
    )


def selftest():
    """反向闸：脚本自己有没有眼睛。这一格不跑 CLI，也不需要语料。

    两条来路闸（合法产物本身、区间内再动一格必须绿）+ 五条反向闸（区间外、
    TIFF 头、像素、该清零却没清零、目录链形状）。只验红的闸会把"逢产物必红"
    这种坏法一起放行，所以先来路后反向。后两条还有一层共同点：改动全落在
    施工区间内，覆盖闸看不见它们，只有各自那一闸看得见——这正是它们存在的理由。

    最后一簇是分母闸（语料目录不存在、产物目录嵌在语料里/就是语料、扫到 0 份）：
    它和 `main()` 用的是同一个函数，所以钉的是真会走的那条路，而不是一个
    只有测试在调的副本；每一格都有配对的放行格，恒拒绝的实现同样要红。
    """
    problems = []
    blob = bytes(mini_tiff())
    tif = TIFF(blob)
    pl = plan(tif, {("IFD0", 315)}, False)
    dropped, disclosed, scrub = pl["dropped"], pl["disclosed"], pl["scrub"]
    good = pl["mine_bytes"]
    print("夹具：{} 字节，预言删 {} 条，施工区间 {}".format(len(blob), dropped, merge(disclosed)))
    if dropped != 1:
        problems.append("预期删 1 条（Artist），实际 {}".format(dropped))
    if not scrub:
        problems.append("Artist 是外置值，却没算出要清零的区间")
    if good == blob:
        problems.append("独立实现算出的产物与输入一模一样——那下面全是空跑")
    digest = chain_digest(tif)
    if len(digest) < 2 or digest[0][1] == 0:
        problems.append(
            "夹具没带缩略图链（读出来 {}），下面那条链闸全是空跑".format(digest)
        )

    def check(what, mutated, expect_red, because=None):
        got = verify_product(tif, blob, mutated, disclosed, scrub)
        red = bool(got)
        ok = red == expect_red
        if ok and because is not None and not any(because in g for g in got):
            ok = False
            got = got + ["红是红了，但不是因为「{}」".format(because)]
        print("  {} {}：期望{}，测得{}".format(
            "OK  " if ok else "FAIL", what, "红" if expect_red else "绿",
            "红" if red else "绿"))
        if not ok:
            problems.append("{}：{}".format(what, "; ".join(got[:2]) or "着色与期望相反"))
        return got

    def poke(base, pos, value):
        b = bytearray(base)
        b[pos] = value
        return bytes(b)

    # 来路闸：合法产物本身必须绿，区间内的改动也必须绿——只验红的闸会把
    # "逢产物必红"这种坏法一起放行。
    check("独立实现的合法产物本身", good, False)
    check("在合法产物上再动一格区间内的字节", poke(good, disclosed[0][0] + 2, 0x00), False)
    check("施工区间外改一格", poke(good, len(blob) - 1, 0xFF), True, "施工区间之外")
    check("改 TIFF 头", poke(good, 7, blob[7] ^ 0x01), True, "TIFF 头")
    check("改像素声明覆盖的字节", poke(good, 40, 0x22), True, "像素声明的字节")
    # 把该清零的那段原样填回去：改动仍然全部落在施工区间内，覆盖闸看不见它，
    # 只有"没清零"那一闸能看见——所以这一格要连红的原因一起验。
    f, t = scrub[0]
    b = bytearray(good)
    b[f:t] = blob[f:t]
    got = check("被删条目的外置值没清零", bytes(b), True, "没有清零")
    if got and not any("没有清零" in g for g in got):
        problems.append("红了，但不是因为「没清零」：{}".format(got[:2]))
    # 把搬到新表尾的 next 清零 = 交出"忘了搬"那份实现会写的字节。
    # 它落在施工区间内，覆盖闸看不见；只有链这一闸看得见。
    off0, _old0, keep0, _body0 = pl["jobs"][0]
    new_tail = off0 + 2 + 12 * len(keep0)
    b = bytearray(good)
    b[new_tail : new_tail + 4] = b"\x00\x00\x00\x00"
    check("next 指针没跟着条目数搬到新表尾", bytes(b), True, "目录链的形状")
    # 长度这一维单独验：截掉一格必须红（上面几条全是等长改动）
    if not verify_product(tif, blob, good[:-1], disclosed, scrub):
        problems.append("产物短了一格，脚本没红")
    else:
        print("  OK   长度变了：期望红，测得红")
    # 分母不许自己喂自己，也不许空跑：这几格走真目录、真判据，而且各格之间
    # 是双向的——恒拒绝的实现输在"同级放行"那一格，恒放行（或"先 mkdir 再判"）
    # 的实现输在拒绝那几格。拒绝的那几格除了看返回值，还要回头看语料目录本身
    # 有没有被建出/多出东西：`-o` 指成语料目录时，"目录存在"这个观测本身没有
    # 区分度（语料自己就在盘上），所以要比清单。
    tmp = Path(tempfile.mkdtemp(prefix="ipcc-nest-"))
    try:
        corpus_dir = tmp / "corpus"
        corpus_dir.mkdir()
        listing_before = sorted(p.name for p in corpus_dir.iterdir())

        def gate(what, call, want_refusal):
            reason = call()
            if bool(reason) != want_refusal:
                problems.append("{}：期望{}，测得{}".format(
                    what, "拒绝" if want_refusal else "放行",
                    "拒绝" if reason else "放行"))
                return
            if want_refusal and sorted(p.name for p in corpus_dir.iterdir()) != listing_before:
                problems.append("{}：口头拒了，语料目录里却多了东西：{}".format(
                    what, sorted(p.name for p in corpus_dir.iterdir())))
                return
            print("  OK   {}：期望{}，测得{}".format(
                what, "拒绝" if want_refusal else "放行",
                "拒绝且未落笔" if want_refusal else "放行"))

        gate("产物目录嵌在语料目录里",
             lambda: check_layout(corpus_dir, corpus_dir / "out")[1], True)
        gate("产物目录就是语料目录",
             lambda: check_layout(corpus_dir, corpus_dir)[1], True)
        gate("语料目录不存在",
             lambda: check_layout(tmp / "nope", tmp / "side2")[1], True)
        gate("产物目录与语料目录同级",
             lambda: check_layout(corpus_dir, tmp / "side")[1], False)
        if not (tmp / "side").is_dir():
            problems.append("同级那一格是空跑：说放行了，目录却没真建出来")
        gate("扫到 0 份", lambda: refuse_empty_scan([], corpus_dir), True)
        gate("扫到 1 份", lambda: refuse_empty_scan([corpus_dir / "a.tif"], corpus_dir), False)
    finally:
        shutil.rmtree(tmp, ignore_errors=False)
    if tmp.exists():
        problems.append("自测的临时目录没清干净：{}".format(tmp))
    print("inplace_crosscheck 自测：{}".format("通过" if not problems else "失败"))
    for p in problems:
        print("  - " + p)
    return 1 if problems else 0


def ifd_bytes(rows, next_off, heap_start):
    """一张目录表的字节：条目数 + 槽位 + next 指针，外置值另算起点。"""
    width = {2: 1, 3: 2, 4: 4}
    body = bytearray(struct.pack("<H", len(rows)))
    heap = bytearray()
    for tag, typ, raw in rows:
        body += struct.pack("<HHI", tag, typ, len(raw) // width[typ])
        if len(raw) <= 4:
            body += raw + bytes(4 - len(raw))
        else:
            body += struct.pack("<I", heap_start + len(heap))
            heap += raw
    body += struct.pack("<I", next_off)
    return body, heap


def mini_tiff():
    """造一个 IFD0 落在像素之后、并且挂着缩略图链的裸 TIFF，字节全在这里摆明。

    自测要的是一份**真能按规则改写**的文件（抄一段字符串当产物等于没测），
    所以布局照相机式来：头 8 字节 → 64 字节假像素 → IFD0（6 条，Artist 外置）
    → next 指针 → Artist 的值 → IFD1（1 条）→ 两字节尾垫。
    尾垫不落在任何声明区间里，拿它验"区间外动一个字节必须红"；
    IFD1 是必须有的：条目数改小时后 next 指针要跟着搬到新表尾，
    没有链的文件上这一刀搬与不搬读出来都是 0，测不出区别。
    """
    image = b"\x11" * 64
    base = 8 + len(image)
    rows = [
        (256, 3, struct.pack("<H", 4)),
        (259, 3, struct.pack("<H", 1)),
        (273, 4, struct.pack("<I", 8)),
        (277, 3, struct.pack("<H", 1)),
        # StripByteCounts 是 278。这里曾经写过 279（SamplesPerPixel）：
        # 那一格配错时守卫会去护一个 1 字节的假区间，真像素反而没人管。
        (278, 4, struct.pack("<I", len(image))),
        (315, 2, b"Jean Cornillon\x00"),
    ]
    ifd0_end = base + 2 + 12 * len(rows) + 4
    heap_len = sum(len(raw) for _t, _ty, raw in rows if len(raw) > 4)
    ifd1_off = ifd0_end + heap_len
    body0, heap0 = ifd_bytes(rows, ifd1_off, ifd0_end)
    body1, _ = ifd_bytes([(274, 3, struct.pack("<H", 2))], 0, 0)
    return (
        b"II"
        + struct.pack("<H", 42)
        + struct.pack("<I", base)
        + image
        + bytes(body0)
        + bytes(heap0)
        + bytes(body1)
        + b"\x2a\x2a"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus", nargs="?", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path(".scratch/inplace-crosscheck"))
    ap.add_argument("--moon", default="moon")
    ap.add_argument("--policy", default="strict", choices=["strict", "privacy"])
    ap.add_argument("--strip", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.corpus is None:
        print("缺语料目录")
        return 2
    repo = Path(__file__).resolve().parent.parent
    corpus = args.corpus
    out_dir = args.out if args.out.is_absolute() else repo / args.out
    out_dir, refusal = check_layout(corpus, out_dir)
    if refusal:
        print(refusal)
        return 2
    files = [
        p for p in sorted(corpus.rglob("*"))
        if p.is_file() and p.suffix.lower() in TIFF_SUFFIXES and p.read_bytes()[:2] in (b"II", b"MM")
    ]
    if args.only:
        files = [p for p in files if args.only in str(p)]
    if args.limit:
        files = files[: args.limit]
    refusal = refuse_empty_scan(files, corpus, args.only)
    if refusal:
        print(refusal)
        return 2
    stats = {}
    feet = {}
    triage = []
    for p in files:
        try:
            bucket, notes = check_one(
                args.moon, repo, p, out_dir, stats, feet, args.strip, args.policy
            )
        except Exception as e:  # 脚本自己崩了要出声，绝不能把崩溃当"这个文件没问题"
            bucket = "triage"
            notes = ["脚本在 {} 上崩了: {}: {}".format(p.name, type(e).__name__, e)]
            stats["triage"] = stats.get("triage", 0) + 1
        if bucket == "triage":
            triage.append((p, notes))
            print("  TRIAGE {}".format(p.name))
    refused = sum(v for k, v in stats.items() if k.startswith("refused-"))
    counted = stats.get("ok", 0) + stats.get("identity", 0) + refused
    # 分母自证：一份文件恰好进一个桶，桶合计必须等于语料份数。
    # 多算一次（同一份既进 ok 又进脚注、既进父桶又进子桶）在这里当场红，
    # 不等读者自己拿计算器加。
    bucket_sum = sum(stats.values())
    denominator_ok = bucket_sum == len(files)
    mode = "strip" if args.strip else "redact " + args.policy
    print("原位模式（{}）：语料 {} 份，计数 {}".format(
        mode, len(files), json.dumps(stats, ensure_ascii=False, sort_keys=True)))
    print(
        "  产物复查通过 {} 份、无事可做原样交回 {} 份，设计内拒绝 {} 份，"
        "三者合计进分母 {} 份；没落笔的：不是 TIFF {} 份、我们读不通 {} 份、"
        "脚本预言不出 {} 份；triage {} 份（内含 audit 非零退出 {} 份）".format(
            stats.get("ok", 0), stats.get("identity", 0), refused, counted,
            stats.get("not-tiff", 0),
            stats.get("unreadable-by-us", 0),
            stats.get("cannot-predict", 0),
            len(triage), stats.get("audit-failed", 0),
        )
    )
    print(
        "  分母自证：桶合计 {} 份 vs 语料 {} 份 -> {}"
        "（脚注：像素这格输入自己就解不开 {} 份、本机无 Pillow {} 份）".format(
            bucket_sum, len(files), "OK" if denominator_ok else "FAIL 有文件被计了两次",
            feet.get("unreadable-by-pillow", 0), feet.get("no-pillow", 0),
        )
    )
    for p, notes in triage[:12]:
        print("  - {}: {}".format(p.name, "; ".join(notes)[:220]))
    return 1 if (triage or not denominator_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
