"""真实照片语料对拍：不再只给自己造的 fixture 打分。

仓库里的测试文件全是我用 Pillow 亲手造的，所以"Pillow 同意"有一半是
自己给自己打分。这个脚本换掉语料来源：喂给它的是相机与手机产出的
真实 JPEG / PNG / TIFF（外站语料，本仓库不收录），对拍两件事：

1. **读得到对不对**——我们枚举的条目编号集合，和 Pillow 看到的集合，
   两个方向都比（我们漏了 / 我们凭空报了）。
2. **删得干净不干净**——按策略脱敏之后，用 Pillow 复查：点名的条目读不到了、
   没点名的还在、像素没动、输入文件逐字节没动。
3. **整包 XMP 有没有被绕开**——脱敏产物里不许再搜到 XMP 包标记，也不许搜到
   包里的敏感键；摘除了就必须由 CLI 说出来。这一条是上一轮跑批抓出来的真漏
   （82 个产物里 13 个还带着完整的第二份元数据），所以它长在这里，
   不长在 .scratch 的一次性脚本里。
4. **两档策略都跑**——写侧不只验 strict，也验 CLI 的缺省档 privacy：
   用户不打 `--policy` 时拿到的就是它，而它先前一条真实语料证据都没有。
   privacy 的期望不另抄一份敏感表，从同一个文件的 strict findings 按
   category 推（两档只差 `timestamps`）；外加一条逐字节比对，
   钉住"缺省产物 == 显式 --policy privacy 的产物"。
5. **`strip` 也过一遍真实语料**——四步写侧里它一直是零证据（这个脚本从前从不跑它）。
   判据不靠猜它该说什么：产物要被我们自己的 `read` 判成干净、被 Pillow 读不出任何
   条目、字节里搜不到包标记与敏感键，而 CLI 那句话必须与这个文件的事实对齐。
   另有一条更硬的性质：**凡是 `redact` 写得出的文件，`strip` 也必须写得出来**，
   所以 strip 的非零退出码一律算分诊，不去匹配任何错误措辞。
6. **拒绝也要复核**——库里每一句"这一步我不做"都带着数字（IFD0 在哪、文件多少字节、
   模型重建出多少字节、哪个 tag 用了哪个类型码、指针越出到哪个偏移）。
   数字对不对，由这个文件自己的字节说了算；复核不上就落回 triage。
   量尺那一侧同理：`verify()` 过了不等于读得懂，分母只算连像素都解得开的那些。

"点名哪些条目"这件事刻意不在这个脚本里再抄一份策略：它取自 `audit --json`
的输出。策略只有一个来源（库），这个脚本只负责"另一个人怎么看"。

用法（第一个参数是必填的语料目录，脚本绝不硬编码任何个人路径）：

    python ci/crosscheck_real.py 语料目录 [-o 输出目录] [--moon moon可执行文件]

只读语料：写出的脱敏文件全部落在 -o 指定的目录（默认 .scratch/crosscheck/）。
退出码 0 = 没有 need-triage 失败；非 0 = 至少一条。

分桶口径（每个桶都要单独解读，混在一起看会骗人）：
- `ok`：读侧集合一致，且脱敏产物过了下面 2 的全部复查。
- `refused-rewrite`：读侧一致，但裸 TIFF 的重写判据主动拒绝（写侧因此**没有**被验证）。
  那句拒绝里的三个数（IFD0 偏移 / 文件字节数 / 模型重建的字节数）由这个文件自己的
  字节复核，复核不上就落回 `triage`——措辞不是判据。
- `designed-unsupported-type` / `designed-undefined-type`：读侧拒绝说某个 tag 用了
  类型 N，N 由脚本自己走一遍 IFD 复核（11/12/13 是边界条款里的"有定义但不解码"，
  其余编号 TIFF 6.0 根本没有，文件本身是坏的）。
- `designed-malformed-pointer`：拒绝说值指针越出块外——**值的那段字节**放不下才算
  （指针本身在文件内、但 pointer + 声明字节数越过文件尾，同样是越界；这一半先前漏了，
  104 个陌生 TIFF 的语料上有 4 个撞在它上面被误判），子目录指针则只要求头两字节落得进来。
  声明字节数由脚本自己按 TIFF 6.0 的宽度表从这个文件的条目算，不看引擎的表。
  已知限制：这一支只在文件的 TIFF 头就落在偏移 0 时才判——那时"块"就是整个文件，
  块长可以直接从字节量出来。JPEG 的 APP1 / PNG 的 `eXIf` 载荷里块长不等于文件长，
  那种句子一律退回 `triage` 而不是放行；目前三批语料里这样的格子是 0。
- `designed-truncated-value`：拒绝说某个偏移之后声明的字节放不下（`偏移 + 剩余 == 文件长`
  且声明 > 剩余）。这一支实际只有"整张目录表放不下"（tag 记 0）会命中：值那一支
  被前面两道长度闸挡在外面，脚本仍然按同一套数复核。
- `designed-wrong-magic`：拒绝说容器魔数不对，且那几个字节确实不是它说的那三种。
- `unreadable-by-pillow`：量尺自己打不开，不进任何比率。
- `triage`：以上都不是（包括**复核不通过**的设计内拒绝），需要人看。

分母也是两层：`verify()` 只查结构、`load()` 才真解像素，只有后者进分母。
一把解不开像素的尺子说"这个文件里没有条目"没有证明力。

量尺进不去的那批不是免检：第二趟只对它们跑 `read`，把每一句读侧拒绝的数字拿
这个文件自己的字节复核一遍（指针越没越出文件、类型码在不在目录表里、三种魔数
对不对）——这一类判据不需要一把能解像素的尺子。计数单记 `secondpass-*`，
不进任何比率的分母；复核不上照样落 `triage`。
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Pillow 的 EXIF 接口用十进制编号指子目录
EXIF_POINTER = 0x8769
GPS_POINTER = 0x8825
INTEROP_POINTER = 0xA005

# 三张表变四张的那一刻，对拍脚本里所有硬编码的目录列表都要跟着改。
POINTERS = (EXIF_POINTER, GPS_POINTER, INTEROP_POINTER)
DIRS = ("IFD0", "Exif", "GPS", "Interop")

# 容器里 XMP 包的字节标记。裸 TIFF 也用它：0x02bc 那条的载荷就是同一个 URI 开头。
XMP_MARKS = (
    b"http://ns.adobe.com/xap/1.0/",
    b"XML:com.adobe.xmp",
    b"<x:xmpmeta",
)

# XMP 里"能定位到人/时间/地点"的键，且必须是 strict 策略确实覆盖的那几类。
# 机型、厂商名（tiff:Make / tiff:Model）刻意不在这里——库里默认不把它们算敏感，
# 放进名单就等于让闸去报一个合法保留的键，红就成了噪声。
XMP_SENSITIVE = (
    b"exif:GPSLatitude",
    b"exif:GPSLongitude",
    b"exif:GPSAltitude",
    b"exif:GPSImgDirection",
    b"exif:GPSSpeed",
    b"exif:DateTimeOriginal",
    b"exif:DateTimeDigitized",
    b"tiff:DateTime",
    b"aux:OwnerName",
    b"aux:SerialNumber",
    b"xmpMM:DocumentID",
    b"xmpMM:InstanceID",
    b"dc:creator",
    b"Iptc4xmpCore:Creator",
    b"Iptc4xmpCore:Location",
    b"MP:RegionInfo",  # 微软 XMP 里的人脸区域
)

# 读侧的"这一步我不做"不能按变体名匹配。CLI 打出来的是 `Show` 的措辞，
# 那句话里从来没有 `UnsupportedType` 这样的名字——旧的那份名单（八个变体名）
# 是死闸：拿 104 个陌生 TIFF 跑，一格都没命中，全数落进 triage。
# 现在的分类一律带证据：**拒绝里报出的那个数字，必须能在这一号文件自己的字节上复核**；
# 复核不成就照旧分诊。宁可少放一个桶，不许拿措辞当判据。
TYPE_WITH_SIZE = (11, 12, 13)  # TIFF 6.0 里有定义、这一版按边界条款不解码
# 不在这三个里、却又被报成"用了类型 N"的编号，TIFF 6.0 根本没有：文件本身是坏的

# 类型码 → 单组件字节数，TIFF 6.0 的表。这里刻意**不**从库里 import：
# 拿被复核方自己的表去复核它的数，那道检查就是空的（import 只防得住抄错，
# 防不住错得一致）。它与库的 `type_size` 由 moonmeta_value_test.mbt 那条
# "type_size：13 个类型码全覆盖，越界返回 None" 各自钉住。
TIFF_TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
    13: 4,
}

RE_TAG = re.compile(r"tag (0x[0-9a-f]{4})")
RE_TYPE = re.compile(r"uses TIFF type (\d+), which this version does not decode")
RE_POINTER_OUT = re.compile(r"tag (0x[0-9a-f]{4}) points to offset (\d+), outside the block")
RE_SUBIFD_OUT = re.compile(
    r"sub-IFD pointer of tag (0x[0-9a-f]{4}) points to offset (\d+), outside the block"
)
RE_IFD_OUT = re.compile(r"IFD offset (\d+) points outside the block")
RE_ENTRY_LEN = re.compile(
    r"tag (0x[0-9a-f]{4}) at offset (\d+) declares (\d+) byte\(s\), only (\d+) left"
)
RE_NO_TIFF_HEADER = re.compile(r"no TIFF header \('II' or 'MM'\) at offset (\d+)")
RE_BAD_ORDER = re.compile(r"byte-order mark at offset (\d+) is neither 'II' nor 'MM'")
RE_NOT_PNG = re.compile(r"not a PNG: the 8-byte signature differs at offset (\d+)")
RE_NOT_JPEG = re.compile(r"no JPEG start-of-image marker \(0xffd8\) at offset (\d+)")
RE_NO_MAGIC = re.compile(r"none of the JPEG, PNG or TIFF magics is at offset (\d+)")
RE_TIFF_REFUSED = re.compile(
    r"refusing to rewrite this bare TIFF: its IFD0 sits at offset (\d+), "
    r"and the file's (\d+) byte\(s\) are not what the metadata model "
    r"rebuilds \((\d+) byte\(s\)"
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IFD_ENTRIES = 4096  # 一张 IFD 里条目数的地板；超过就当结构坏了，别去数


def tiff_reader(blob):
    """按 TIFF 头里的字节序返回 (u16, u32)；头不对返回 (None, None)。"""
    little = blob[:2] == b"II"
    if not little and blob[:2] != b"MM":
        return None, None

    def u16(off):
        if off is None or off < 0 or off + 2 > len(blob):
            return None
        return int.from_bytes(blob[off : off + 2], "little" if little else "big")

    def u32(off):
        if off is None or off < 0 or off + 4 > len(blob):
            return None
        return int.from_bytes(blob[off : off + 4], "little" if little else "big")

    return u16, u32


def tiff_ifd0(blob):
    """文件头自己写明的 IFD0 偏移；不是 TIFF 头（或不是 42）返回 None。"""
    u16, u32 = tiff_reader(blob)
    if u16 is None:
        return None
    if u16(2) != 42:
        return None
    return u32(4)


def tiff_entry_claims(blob):
    """走一遍 IFD 链与 Exif/GPS/Interop 子目录：
    {tag: [(类型码, 声明字节数或 None, 值偏移或 None, 值字段那个 32 位整数)]}。

    声明字节数与值偏移按 TIFF 的存法在这里自己算（count × 规范里的类型宽度；
    只有超过 4 字节才去看第 12 字节那个指针），宽度表是抄规范的、不看引擎的表
    ——这一趟要复核的正是引擎报出来的那些数，拿它的表复核等于问它自己。
    结构一异常就停在已经读到的那部分：宁可找不到，也绝不编证据。
    """
    u16, u32 = tiff_reader(blob)
    out = {}
    if u16 is None:
        return out
    seen = set()

    def walk(off, depth):
        if off is None or off in seen or depth > 2:
            return
        seen.add(off)
        n = u16(off)
        if n is None or n > MAX_IFD_ENTRIES or off + 2 + 12 * n > len(blob):
            return
        subs = []
        for i in range(n):
            e = off + 2 + 12 * i
            tag, typ = u16(e), u16(e + 2)
            count, field = u32(e + 4), u32(e + 8)
            if tag is None or typ is None or count is None or field is None:
                return
            size = TIFF_TYPE_SIZES.get(typ)
            total = None if size is None else count * size
            voff = None
            if total is not None:
                voff = e + 8 if total <= 4 else field
            out.setdefault(tag, []).append((typ, total, voff, field))
            if tag in POINTERS and typ == 4 and count == 1:
                subs.append(field)
        nxt = u32(off + 2 + 12 * n)  # 下一张 IFD（缩略图那类）；放不下就停在这里
        if nxt is not None:
            walk(nxt, depth + 1)
        for s in subs:  # 子目录
            walk(s, depth + 2)

    walk(tiff_ifd0(blob), 0)
    return out


def tiff_entry_types(blob):
    """{tag: set(声明的类型码)}——只取 tiff_entry_claims 的类型那一列。"""
    return {tag: {row[0] for row in rows} for tag, rows in tiff_entry_claims(blob).items()}


def tiff_refusal_numbers(text):
    """从那句拒绝里取出三个数：(IFD0 偏移, 文件字节数, 模型重建的字节数)。"""
    m = RE_TIFF_REFUSED.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def tiff_refusal_problems(text, blob):
    """那句拒绝的三个数对不对。返回问题列表，空表 = 复核通过。"""
    numbers = tiff_refusal_numbers(text)
    if numbers is None:
        return [
            "裸 TIFF 的拒绝那句话换了形状，三个数取不出来，复核无从做起: "
            + text.strip()[:160]
        ]
    ifd0, total, rebuilt = numbers
    out = []
    real = tiff_ifd0(blob)
    if real is None:
        out.append("句子里说这是裸 TIFF，文件头却不是 II/MM + 42")
    elif real != ifd0:
        out.append(
            "句子说 IFD0 在偏移 {}，文件头自己写的是 {}".format(ifd0, real)
        )
    if total != len(blob):
        out.append("句子说文件 {} 字节，实际 {} 字节".format(total, len(blob)))
    if rebuilt >= total:
        out.append(
            "句子说模型重建出 {} 字节，并不比文件的 {} 字节短——"
            "那句「写下去会丢字节」就不成立".format(rebuilt, total)
        )
    return out


def read_refusal(text, blob):
    """读侧的失败落在设计内吗。返回 (桶名或 None, 分诊说明列表)。

    每一支都拿这个文件的字节复核；复核不过就把说明交回去，让它留在 triage。
    """
    m = RE_TYPE.search(text)
    if m:
        code = int(m.group(1))
        tag_m = RE_TAG.search(text)
        tag = int(tag_m.group(1), 16) if tag_m else None
        declared = tiff_entry_types(blob).get(tag, set()) if tag is not None else set()
        if code not in declared:
            return None, [
                "拒绝说 tag {} 用类型 {}，可我们自己在这些字节里读到的类型是 {}："
                "那个数字复核不上".format(
                    tag_m.group(1) if tag_m else "?",
                    code,
                    sorted(declared) if declared else "（没有这条）",
                )
            ]
        if code in TYPE_WITH_SIZE:
            return "designed-unsupported-type", []
        return "designed-undefined-type", []

    m = RE_SUBIFD_OUT.search(text)
    if m:
        tag = int(m.group(1), 16)
        off = int(m.group(2))
        if tiff_ifd0(blob) is None:
            return None, [
                "说子目录指针越出块外，可这个文件连 TIFF 头都不是：块的分界无从复核"
            ]
        rows = tiff_entry_claims(blob).get(tag, [])
        if not any(row[3] == off for row in rows):
            return None, [
                "说 tag {} 的子目录指针越界，可字节里那条的值字段不是偏移 {}（读到的：{}）："
                "那个数字复核不上".format(
                    m.group(1),
                    off,
                    sorted({str(r[3]) for r in rows}) or "（没有这条）",
                )
            ]
        # 引擎对子目录指针只要求头两字节落进来（它随后才读条目数）。
        if off + 2 > len(blob):
            return "designed-malformed-pointer", []
        return None, [
            "说子目录指针 {} 越出块外，可整个文件 {} 字节，头两字节落得进去：复核不通过".format(
                off, len(blob)
            )
        ]

    m = RE_POINTER_OUT.search(text)
    if m:
        tag = int(m.group(1), 16)
        off = int(m.group(2))
        if tiff_ifd0(blob) is None:
            return None, [
                "说指针越出块外，可这个文件连 TIFF 头都不是：块的分界无从复核"
            ]
        # "越出块外"说的是**值的那段字节**放不下，不是指针本身落在文件外：
        # 只按后者判会把 4 个真越界的文件报成复核不通过（104 个陌生 TIFF 第一轮
        # 就撞在这上面）。声明字节数由这个文件的条目自己算出来。
        hits = [
            row
            for row in tiff_entry_claims(blob).get(tag, [])
            if row[1] is not None and row[1] > 4 and row[2] == off
        ]
        if not hits:
            return None, [
                "说 tag {} 的值指针落在偏移 {} 越界，可字节里没有一条这样的条目"
                "（该 tag 读到的值偏移：{}）：那个数字复核不上".format(
                    m.group(1),
                    off,
                    sorted({str(r[2]) for r in tiff_entry_claims(blob).get(tag, [])})
                    or "（没有这条）",
                )
            ]
        if any(off + row[1] > len(blob) for row in hits):
            return "designed-malformed-pointer", []
        return None, [
            "说指针 {} 越出块外，可它声明的 {} 字节从 {} 起放得进这个 {} 字节的文件："
            "复核不通过".format(off, min(row[1] for row in hits), off, len(blob))
        ]

    m = RE_ENTRY_LEN.search(text)
    if m:
        off = int(m.group(2))
        declared = int(m.group(3))
        avail = int(m.group(4))
        if tiff_ifd0(blob) is None:
            return None, [
                "说条目声明的字节放不下，可这个文件连 TIFF 头都不是：块的分界无从复核"
            ]
        out = []
        if off + avail != len(blob):
            out.append(
                "句子说偏移 {} 之后还剩 {} 字节，可这个文件长 {} 字节，两数对不上".format(
                    off, avail, len(blob)
                )
            )
        if declared <= avail:
            out.append(
                "句子说声明的 {} 字节放不下，可剩下的 {} 字节够用：那句不成立".format(
                    declared, avail
                )
            )
        if m.group(1) == "0x0000":
            # tag 记 0 是"整张目录表放不下"那一支：声明的该是 条目数 × 12，
            # 条目数就是表体前那两个字节（偏移 off-2 处的 u16）。
            u16, _u32 = tiff_reader(blob)
            n = u16(off - 2) if u16 is not None else None
            if n is None or n * 12 != declared:
                out.append(
                    "目录表那句说声明 {} 字节，可偏移 {} 前那两个字节里的条目数是 {}"
                    "（× 12 = {}）：那个数字复核不上".format(
                        declared, off, n, None if n is None else n * 12
                    )
                )
        else:
            tag = int(m.group(1), 16)
            rows = tiff_entry_claims(blob).get(tag, [])
            if not any(row[2] == off and row[1] == declared for row in rows):
                out.append(
                    "句子说 tag {} 在偏移 {} 声明 {} 字节，可字节里那条算出来的是 {}："
                    "那个数字复核不上".format(
                        m.group(1),
                        off,
                        declared,
                        sorted({str(r[1]) for r in rows if r[2] == off})
                        or "（没有这条）",
                    )
                )
        if out:
            return None, out
        return "designed-truncated-value", []

    m = RE_IFD_OUT.search(text)
    if m:
        off = int(m.group(1))
        real = tiff_ifd0(blob)
        if real is None:
            return None, [
                "说 IFD 偏移越出块外，可这个文件连 TIFF 头都不是：块的分界无从复核"
            ]
        if real != off:
            return None, [
                "句子里的 IFD 偏移是 {}，可文件头第 4 字节写的是 {}：那个数字复核不上".format(
                    off, real
                )
            ]
        if off + 2 > len(blob):
            return "designed-malformed-pointer", []
        return None, [
            "说 IFD 偏移 {} 越出块外，可整个文件 {} 字节，它的头两字节落得进去：复核不通过".format(
                off, len(blob)
            )
        ]

    for rx, want in (
        (RE_NO_TIFF_HEADER, (b"II", b"MM")),
        (RE_BAD_ORDER, (b"II", b"MM")),
    ):
        m = rx.search(text)
        if m:
            off = int(m.group(1))
            if blob[off : off + 2] in want:
                return None, [
                    "说偏移 {} 上没有 TIFF 头，可那两个字节就是 {}".format(
                        off, blob[off : off + 2]
                    )
                ]
            return "designed-wrong-magic", []

    m = RE_NOT_PNG.search(text)
    if m:
        off = int(m.group(1))
        if blob[off : off + 8] == PNG_SIGNATURE:
            return None, ["说 PNG 签名在偏移 {} 对不上，可那八个字节就是签名".format(off)]
        return "designed-wrong-magic", []

    m = RE_NOT_JPEG.search(text)
    if m:
        off = int(m.group(1))
        if blob[off : off + 2] == b"\xff\xd8":
            return None, ["说偏移 {} 上没有 JPEG 起始标记，可那里就是 0xffd8".format(off)]
        return "designed-wrong-magic", []

    m = RE_NO_MAGIC.search(text)
    if m:
        off = int(m.group(1))
        head = blob[off : off + 8]
        if (
            head[:2] in (b"II", b"MM")
            or head == PNG_SIGNATURE
            or head[:2] == b"\xff\xd8"
        ):
            return None, ["说三种魔数都不在偏移 {}，可这里就是有一种".format(off)]
        return "designed-wrong-magic", []

    return None, []


def run_moon(moon, args, cwd):
    """跑一次 CLI，拿它 stdout 的原始字节。

    构建进度走 stderr，这里只认 stdout；--json 的输出是纯 ASCII，
    所以 utf-8 解码不可能碰到控制台编码问题。
    """
    proc = subprocess.run(
        [moon, "run", "cmd/main", "--", *args],
        cwd=str(cwd),
        capture_output=True,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def read_json(moon, repo, path):
    code, out = run_moon(moon, ["read", str(path), "--json"], repo)
    line = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0:
        return None, line
    try:
        return json.loads(line), None
    except json.JSONDecodeError as e:
        return None, "JSON 解析失败: {} / 原文 {!r}".format(e, line[:200])


def pillow_probe(path):
    """量尺自己走到哪一步：`unopenable` / `verify-only` / `load`。

    `verify()` 只查结构（它甚至要求之后不能再用它），`load()` 才真的解像素。
    分母只认后者：一把打不开像素的尺子，说"这个文件里没有条目"没有证明力。
    """
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        return "unopenable"
    try:
        with Image.open(path) as im:
            im.load()
    except Exception:
        return "verify-only"
    return "load"


def pillow_dirs(path):
    """Pillow 看到的四张目录：{目录名: set(编号)}。读不出来返回 None。

    Pillow 12 会把它认识的条目用枚举成员（如 `Base.Orientation`）当键返回，
    那种键和整数 274 在集合运算里不相等——不归一化就会报出一片"我们漏了"，
    其实是量尺花了。
    """
    with Image.open(path) as im:
        ex = im.getexif()
        out = {name: set() for name in DIRS}
        out["IFD0"] = {int(k) for k in ex.keys()} - set(POINTERS)
        for name, pointer in (
            ("Exif", EXIF_POINTER),
            ("GPS", GPS_POINTER),
            ("Interop", INTEROP_POINTER),
        ):
            try:
                sub = ex.get_ifd(pointer)
                out[name] = {int(k) for k in sub.keys()} - set(POINTERS)
            except Exception:
                out[name] = set()
        return out


def ours_dirs(doc):
    out = {}
    for d in doc["directories"]:
        out[d["dir"]] = {e["tag"] for e in d["entries"]}
    return out


def pixel_hash(path):
    with Image.open(path) as im:
        return hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def xmp_residue(
    dst,
    src_blob,
    red_out,
    stats,
    policy="strict",
    redacted_key="redacted",
    dropped_key="xmp_dropped",
):
    """产物字节里的 XMP 残留，加上"摘了有没有说"。空列表 = 这一关过了。

    计数器键按策略分开：`redacted` / `xmp_dropped` 记的是 strict 那一趟，
    privacy 那一趟另用 `redacted_privacy` / `xmp_dropped_privacy`。
    共用一个键会把"产物复查 N 个"的分母翻倍，那行数字就没有意义了。
    """
    stats[redacted_key] = stats.get(redacted_key, 0) + 1
    out = []
    blob = dst.read_bytes()
    marks = [m.decode() for m in XMP_MARKS if m in blob]
    keys = [k.decode() for k in XMP_SENSITIVE if k in blob]
    if marks:
        out.append("{} 之后产物里还有 XMP 包: {}".format(policy, marks))
    if keys:
        out.append(
            "{} 之后产物字节里还搜得到 XMP 敏感键: {}".format(policy, keys)
        )
    # 摘了却不说，和没摘一样危险：下一次有人会以为这个文件本来就干净。
    if any(m in src_blob for m in XMP_MARKS) and not marks:
        if "XMP" not in red_out:
            out.append("{}：整包 XMP 已被摘除，但 CLI 没有披露".format(policy))
        else:
            stats[dropped_key] = stats.get(dropped_key, 0) + 1
    return out


# `read --json` 的 `xmp` 键是一个文件"有没有整包元数据"的唯一机读说法。
# 它必须能用这个文件自己的字节复核，两个方向都要红：说有而字节里没有是假警报，
# 字节里有却说没有，就是当初那 13 个产物泄漏的同一件事。
PACKET_MARKS = {
    "jpeg": (b"http://ns.adobe.com/xap/1.0/",),
    "png": (b"XML:com.adobe.xmp",),
}


def xmp_flag_problems(kind, blob, flag):
    """这个文件的 `xmp` 键与原始字节的不一致清单（空 = 一致）。"""
    marks = PACKET_MARKS.get(kind)
    if marks is None:
        # 裸 TIFF 的载体是 IFD 里的一条，逐条清单本来就看得见它
        return []
    if flag is None:
        return ["read --json 少了 xmp 键"]
    seen = any(m in blob for m in marks)
    if flag and not seen:
        return ["说在有：xmp=true，原始字节里却搜不到包标记"]
    if seen and not flag:
        return ["说在无：原始字节里搜得到包标记，xmp 却是 false（走查漏了一包）"]
    return []


# Pillow 的 get_ifd(0x8825) 只从 IFD0 取 GPSInfo 指针；而 Pillow 自己的写出器
# 常把这个指针挂在 Exif 子目录里（我们那五份 fixture 就是它写的）。
# 于是"我们多报了一整个 GPS 目录"其实是量尺不肯跳这一跳。
# 判据不许靠猜：拿 Pillow 自己的 IFD 解析器去读那个偏移，
# 它列出的编号必须把我们多报的每一个都包含在内。
GPS_TAG_MAX = 0x1E  # GPS IFD 用过的编号上界（0x0000–0x001E）


def nested_gps_entries(path):
    """Pillow 按 Exif 子目录里的 GPSInfo 指针能读到哪些编号；读不到返回 None。"""
    with Image.open(path) as im:
        ex = im.getexif()
        try:
            offset = ex.get_ifd(EXIF_POINTER).get(GPS_POINTER)
        except Exception:
            return None
        if offset is None:
            return None
        try:
            ifd = ex._get_ifd_dict(offset, GPS_POINTER)
        except Exception:
            return None
        return None if ifd is None else {int(k) for k in ifd.keys()}


def gps_via_exif_pointer(extra, nested):
    """纯判据：多报的 GPS 条目是否就是 Pillow 在那个偏移上读到的那一套。"""
    if not extra or nested is None:
        return False
    if not all(0 <= t <= GPS_TAG_MAX for t in extra):
        return False
    return extra <= nested


def zero_length_entries(doc, dir_name, tags):
    """多出来的条目是否都是 count=0 的空声明。

    Pillow 遍历 IFD 时对 count 为 0 的条目直接跳过（`TiffImagePlugin.py`
    里的 `if type_num != 0 and values_offset ... and count != 0`），
    所以"我们多报了"其实可以是"它不列空值条目"。
    判据用值本身：我们的解码器把 count=0 的 ASCII 解成空串。
    """
    for group in doc.get("directories", []):
        if group["dir"] != dir_name:
            continue
        seen = {e["tag"]: e["value"] for e in group["entries"]}
        return all(seen.get(t) in ('""', "Raw(0 byte(s))") for t in tags)
    return False


def xmp_injected(src_blob, dir_name, tags, doc):
    """缺的这几条是不是 Pillow 从 XMP 包里读进来、又混进 getexif 的。

    Pillow 12 会把 XMP 里的 tiff:Orientation / flash / ImageNumber 合并进
    `getexif()` 的结果（`Image.py` 里那段 `r'tiff:Orientation(=\"|>)([0-9])'`）。
    那是另一个载体里的值，不是 EXIF 段里的条目——我们只报段里有的。
    判据：包里真的写着这个条目名。
    """
    if dir_name != "IFD0":
        return False
    if not any(m in src_blob for m in XMP_MARKS):
        return False
    names = set()
    for group in doc.get("directories", []):
        if group["dir"] == "IFD0":
            names = {e["name"] for e in group["entries"]}
    for t in tags:
        name = KNOWN_IFD0_NAMES.get(t)
        if name is None or ("tiff:" + name).encode() not in src_blob:
            return False
        if name in names:  # 段里另有一条同名的，就不是注入问题
            return False
    return True


# 只用来把编号换回 XMP 里的属性名；策略一律不从这里读。
KNOWN_IFD0_NAMES = {0x0112: "Orientation"}


def audit_findings(moon, repo, path, policy):
    """跑一次 `audit --json`，只拿 findings 那一项。"""
    code, out = run_moon(
        moon, ["audit", str(path), "--policy", policy, "--json"], repo
    )
    assert code == 0, "audit 在 {} 上失败了: {}".format(path, out)
    return json.loads(out.strip().splitlines()[-1])["findings"]


def privacy_expectations(findings, their, after, explained):
    """默认策略该删什么、该留什么——全部从这个文件的 strict findings 推。

    `privacy` 与 `strict` 唯一的差别是 `timestamps` 那一格，所以这里不需要
    第二份敏感表（抄一份，就会有一份过时不候的期望）。返回 (残留, 误删)：

    - 残留：非时间戳的被点名条目，在 privacy 产物里 Pillow 还读得到。
    - 误删：时间戳条目，Pillow 在**原图**里读得到、在产物里读不到了——
      默认策略删时间戳，就是替用户把照片的拍摄时间弄没了。

    `explained` 是上一段拿字节证据归因过的格子，只用在误删这一方向：
    那种值住在 XMP 包里，两档策略都会连包一起摘，产物里读不到它是预期。
    残留这一方向刻意不减 `explained`、也不加 `t in their` 门槛：
    产物里读得到就是读得到（strict 那条 `still` 同理）。
    """
    residue = []
    ts_lost = []
    for f in findings:
        d, t = f["dir"], f["tag"]
        if f["category"] == "timestamps":
            if (d, t) in explained:
                continue
            if t in their[d] and t not in after.get(d, set()):
                ts_lost.append((d, t, f["name"]))
        elif t in after.get(d, set()):
            residue.append((d, t, f["name"]))
    return residue, ts_lost


# strip 报"摘了"的那句话的前缀。整句话由命令行自己的测试钉着，
# 改措辞会先红在 `moon test` 里，而不是红在这次的跑批里。
STRIP_AFFIRM = "元数据已整段摘除："


def strip_claims(output, had_exif, had_xmp):
    """CLI 那句话与这个文件的事实之间的差集（空 = 说得对）。

    先把"元数据已整段摘除：EXIF,XMP 包。"里点名的载体拆成一个集合再比。
    不能只做 `"EXIF" in output` 这种子串判断——否定那句"这个文件本来就没有
    EXIF，也没有 XMP 包"里同样写着 EXIF 和 XMP，子串会把一条谎说成实话。

    事实只取两处：`had_exif` 是这个文件自己 `read --json` 的 `exif` 位，
    `had_xmp` 是它的原始字节里有没有包标记。刻意不拿 Pillow 的读数当
    "有没有 EXIF"的依据——Pillow 会把 XMP 包里的值注进 `getexif()`，
    一个只有 XMP 的 PNG 会被判成"有 EXIF"，闸就会在一个合法的说法上报红。
    """
    out = []
    said_absent = "本来就没有" in output
    _, _, tail = output.partition(STRIP_AFFIRM)
    listed = {p for p in tail.split("。")[0].split(",") if p} if tail else set()
    if had_exif and "EXIF" not in listed:
        out.append("源文件有 EXIF 段，strip 却没有交代摘除它")
    if had_xmp and "XMP 包" not in listed:
        out.append("源文件带着 XMP 包，strip 却没有交代摘除它")
    if (had_exif or had_xmp) and said_absent:
        out.append("源文件有元数据，strip 却说这个文件本来就没有")
    if not (had_exif or had_xmp) and not said_absent:
        out.append("源文件 EXIF 与 XMP 两样都没有，strip 却说摘除了东西")
    return out


def strip_step(moon, repo, src, out_dir, stats, doc, src_blob, pixels_before):
    """在这个文件上跑一趟 `strip`，返回分诊说明（空 = 这一关过了）。

    六路观察，互相独立：产物我们自己读得回不读得回、Pillow 还读不读得到条目、
    产物字节里还剩不剩包标记与敏感键、CLI 那句话对不对得上事实、输入动没动、
    像素动没动。任何一路红都不需要另一路背书。
    """
    s_dst = out_dir / (src.stem + ".stripped" + src.suffix)
    had_xmp = any(m in src_blob for m in XMP_MARKS)
    before_input = sha256(src)
    code, out = run_moon(moon, ["strip", str(src), "-o", str(s_dst)], repo)
    if code != 0:
        # 调用方只在 redact 已经写出产物的分支里跑这里：同一个文件，
        # redact 改得动而 strip 改不动，只可能是 strip 自己的问题。
        # 所以这里不比对错误措辞——措辞会变，这条性质不会。
        return [
            "redact 写得出的文件，strip 退出码 {}: {}".format(
                code, out.strip()[:160]
            )
        ]

    stats["stripped"] = stats.get("stripped", 0) + 1
    if had_xmp:
        stats["strip_xmp"] = stats.get("strip_xmp", 0) + 1

    notes = strip_claims(out, bool(doc["exif"]), had_xmp)

    s_doc, s_err = read_json(moon, repo, s_dst)
    if s_doc is None:
        notes.append("strip 产物我们自己读不回来: " + (s_err or "")[:160])
    else:
        if s_doc["exif"]:
            notes.append("strip 之后 read 还报得出 EXIF")
        if s_doc.get("xmp") is True:
            notes.append("strip 之后 read 还报得出 XMP 包")

    try:
        left = pillow_dirs(s_dst)
    except OSError as e:
        notes.append("strip 产物 Pillow 解不开: {}".format(e))
        left = None
    if left is not None:
        seen = {name: sorted(left[name]) for name in DIRS if left[name]}
        if seen:
            notes.append("strip 之后 Pillow 还读得到条目: {}".format(seen))

    blob = s_dst.read_bytes()
    marks = [m.decode() for m in XMP_MARKS if m in blob]
    if marks:
        notes.append("strip 之后产物里还有 XMP 包: {}".format(marks))
    keys = [k.decode() for k in XMP_SENSITIVE if k in blob]
    if keys:
        notes.append("strip 之后产物字节里还搜得到敏感键: {}".format(keys))

    if sha256(src) != before_input:
        notes.append("strip 改动了输入文件本身")
    if pixels_before is not None:
        try:
            if pixel_hash(s_dst) != pixels_before:
                notes.append("strip 动了像素")
        except OSError as e:
            notes.append("strip 产物解不开，像素没比成: {}".format(e))
    return notes


def check_one(moon, repo, src, out_dir, stats):
    """一个文件的五条结论。返回 (状态桶, 需要分诊的说明列表)。"""
    notes = []
    src_blob = src.read_bytes()
    if any(m in src_blob for m in XMP_MARKS):
        stats["xmp_src"] = stats.get("xmp_src", 0) + 1
    doc, err = read_json(moon, repo, src)
    if doc is None:
        text = err or ""
        if "没有 EXIF" in text:
            return "unreadable-by-pillow", []
        bucket, problems = read_refusal(text, src_blob)
        if bucket:
            stats[bucket] = stats.get(bucket, 0) + 1
            return bucket, []
        if problems:
            return "triage", problems
        return "triage", ["读侧失败，且没有任何一句形状能被字节复核: " + text[:160]]

    their = pillow_dirs(src)
    if their is None:  # pragma: no cover - Pillow 打不开的文件在上面就滤掉了
        return "unreadable-by-pillow", []

    bucket = "ok"

    # 0) 机读那一位的 `xmp` 键，先跟这个文件的字节对一遍
    if doc.get("container") in PACKET_MARKS:
        stats["xmp_flag"] = stats.get("xmp_flag", 0) + 1
        flag_problems = xmp_flag_problems(
            doc["container"], src_blob, doc.get("xmp")
        )
        if flag_problems:
            notes.extend(flag_problems)
            bucket = "triage"

    # 1) 有没有 EXIF 这件事，两边得一致
    if bool(their["IFD0"]) != doc["exif"] and not any(their.values()):
        notes.append(
            "EXIF 有无不一致：我们 exif={}，Pillow IFD0 非空={}".format(
                doc["exif"], bool(their["IFD0"])
            )
        )
        bucket = "triage"

    if doc["exif"]:
        # 2) 条目编号集合，双向比
        mine = ours_dirs(doc)
        # 目录少一张，比较就会悄悄变窄：先钉住"两边都比了四张"。
        assert set(mine) == set(DIRS), "CLI 报的目录集合变了: {}".format(
            sorted(mine)
        )
        explained = set()
        for name in DIRS:
            missing = their[name] - mine[name]
            extra = mine[name] - their[name]
            # 先归因再定罪：三种已知的量尺行为都要拿这个文件的字节当证据，
            # 证据不成立就照样红。按下文件名来豁免等于没有闸。
            if missing and xmp_injected(src_blob, name, missing, doc):
                stats["scale-xmp-injected"] = (
                    stats.get("scale-xmp-injected", 0) + len(missing)
                )
                notes.append(
                    "{} 少的 {} 条已归因：Pillow 把 XMP 包里的值注进 getexif，"
                    "EXIF 段里本来就没有".format(name, sorted(missing))
                )
                explained |= {(name, t) for t in missing}
                missing = set()
            if extra and zero_length_entries(doc, name, extra):
                stats["scale-zero-length"] = (
                    stats.get("scale-zero-length", 0) + len(extra)
                )
                notes.append(
                    "{} 多的 {} 条已归因：count=0 的空声明，"
                    "Pillow 不列这种条目".format(name, sorted(extra))
                )
                explained |= {(name, t) for t in extra}
                extra = set()
            if name == "GPS" and extra and gps_via_exif_pointer(
                extra, nested_gps_entries(src)
            ):
                stats["scale-gps-nested"] = (
                    stats.get("scale-gps-nested", 0) + len(extra)
                )
                notes.append(
                    "GPS 多的 {} 条已归因：GPSInfo 指针挂在 Exif 子目录里，"
                    "Pillow 的 get_ifd 只从 IFD0 找；那一套编号它自己读得出".format(
                        sorted(extra)
                    )
                )
                explained |= {(name, t) for t in extra}
                extra = set()
            if missing or extra:
                bucket = "triage"
                notes.append(
                    "{} 目录不一致：我们缺 {}，我们多 {}".format(
                        name, sorted(missing), sorted(extra)
                    )
                )

        # 3) 脱敏效果：点名清单来自 audit，观察来自 Pillow
        findings = audit_findings(moon, repo, src, "strict")
        named = {(f["dir"], f["tag"]) for f in findings}
        # 按目录分桶比：0x0001 在 GPS 里是纬度引用，在 Interop 里是 InteropIndex。
        # 拿裸编号跨目录比，会把没点名的条目算成残留。
        named_in = {
            name: {tag for (d, tag) in named if d == name} for name in DIRS
        }

        dst = out_dir / (src.stem + ".redacted" + src.suffix)
        before_input = sha256(src)
        try:
            pixels_before = pixel_hash(src)
        except OSError:
            pixels_before = None

        code, red_out = run_moon(
            moon, ["redact", str(src), "--policy", "strict", "-o", str(dst)], repo
        )
        if code != 0:
            # CLI 打出来的是 Show 的措辞，不是变体名。这句话由
            # moonmeta_error_wbtest.mbt 钉住形状，但这里连措辞也不信任：
            # 句子里那三个数（IFD0 偏移 / 文件字节数 / 模型重建的字节数）
            # 必须能在这一号文件自己的字节上复核，复核不过就分诊。
            numbers = tiff_refusal_numbers(red_out)
            if numbers is not None:
                problems = tiff_refusal_problems(red_out, src_blob)
                if problems:
                    notes.extend(problems)
                    return "triage", notes
                ifd0, total, rebuilt = numbers
                stats["tiff-refused"] = stats.get("tiff-refused", 0) + 1
                if ifd0 != 8:
                    stats["tiff-refused-late-ifd"] = (
                        stats.get("tiff-refused-late-ifd", 0) + 1
                    )
                drop = total - rebuilt
                stats["tiff-drop-min"] = min(stats.get("tiff-drop-min", drop), drop)
                stats["tiff-drop-max"] = max(stats.get("tiff-drop-max", drop), drop)
                if bucket != "ok":
                    notes.append(
                        "redact 退出码 {}: {}".format(code, red_out.strip()[:160])
                    )
                    return "triage", notes
                # 裸 TIFF 的重写判据主动拒绝：读侧已经比过，写侧按设计不做。
                # 单独一个桶，不许混进 ok——那一格的写侧从没被验过。
                # 拒绝必须干净：不能留下一个"看着像产物"的坏文件。
                bucket = "refused-rewrite"
                if dst.exists():
                    notes.append("拒绝改写却仍然写出了 {}".format(dst.name))
                    bucket = "triage"
                return bucket, notes
            bucket = "triage"
            notes.append("redact 退出码 {}: {}".format(code, red_out.strip()[:160]))
            return bucket, notes

        if sha256(src) != before_input:
            bucket = "triage"
            notes.append("redact 改动了输入文件本身")

        after_doc, after_err = read_json(moon, repo, dst)
        if after_doc is None:
            bucket = "triage"
            notes.append("脱敏结果我们自己读不回来: " + (after_err or "")[:160])
        else:
            residue = audit_findings(moon, repo, dst, "strict")
            if residue:
                bucket = "triage"
                notes.append(
                    "脱敏之后还剩 {} 条敏感条目：{}".format(
                        len(residue), [r["name"] for r in residue][:8]
                    )
                )

        after = pillow_dirs(dst)
        still = sorted(
            (name, t) for name in DIRS for t in after[name] if t in named_in[name]
        )
        if still:
            bucket = "triage"
            notes.append("Pillow 仍读得到被点名的条目: {}".format(still))

        # 4) XMP 残留。这一关是语料逼出来的：逐条清单全绿的同时，
        #    产物里可以整整齐齐躺着第二份元数据——XMP 包不按条目编号露自己，
        #    所以这里不看编号，直接查产物字节。
        for note in xmp_residue(dst, src_blob, red_out, stats):
            notes.append(note)
            bucket = "triage"

        kept_before = {
            (name, t)
            for name in DIRS
            for t in their[name]
            if t not in named_in[name]
        }
        kept_after = {(name, t) for name in DIRS for t in after[name]}
        # 已经拿字节证据归因过的格子先扣掉：那种值本来住在 XMP 包里，
        # strict 摘完整包之后 Pillow 读不到它是预期结果，不是二次损失。
        lost = sorted(kept_before - kept_after - explained)
        if lost:
            bucket = "triage"
            notes.append("未点名的条目反而没了: {}".format(lost))

        if pixels_before is not None:
            try:
                if pixel_hash(dst) != pixels_before:
                    bucket = "triage"
                    notes.append("像素动了")
            except OSError as e:
                notes.append("像素无法比对（脱敏结果解不开）: {}".format(e))
                bucket = "triage"

        # 5) 默认策略那一档。上面四步全跑在 strict 上，而用户不打 `--policy`
        #    时拿到的是 privacy——它在此之前没有一条真实语料证据。两档只差
        #    `timestamps` 一格，所以期望不必另抄一份敏感表：从同一个文件的
        #    strict findings 按 category 分一下就是它的验收单。
        p_dst = out_dir / (src.stem + ".privacy" + src.suffix)
        d_dst = out_dir / (src.stem + ".default" + src.suffix)
        p_code, p_out = run_moon(
            moon,
            ["redact", str(src), "--policy", "privacy", "-o", str(p_dst)],
            repo,
        )
        if p_code != 0:
            # strict 刚在同一个文件上写过产物：写不出 privacy 只可能是
            # privacy 自己那档的问题。
            bucket = "triage"
            notes.append(
                "privacy 在 strict 能改写的文件上退出码 {}: {}".format(
                    p_code, p_out.strip()[:160]
                )
            )
        else:
            stats["privacy"] = stats.get("privacy", 0) + 1
            before_input_p = sha256(src)

            # "缺省就是 privacy"这句主张得用字节说：产物必须逐字节相同。
            d_code, d_out = run_moon(
                moon, ["redact", str(src), "-o", str(d_dst)], repo
            )
            if d_code != 0:
                bucket = "triage"
                notes.append(
                    "不带 --policy 的 redact 退出码 {}: {}".format(
                        d_code, d_out.strip()[:160]
                    )
                )
            elif sha256(d_dst) != sha256(p_dst):
                bucket = "triage"
                notes.append("缺省策略的产物与 --policy privacy 逐字节不一致")

            # 同策略闭合：拿 privacy 再审自己的产物，一条都不许剩
            p_left = audit_findings(moon, repo, p_dst, "privacy")
            if p_left:
                bucket = "triage"
                notes.append(
                    "privacy 之后还剩 {} 条敏感条目：{}".format(
                        len(p_left), [r["name"] for r in p_left][:8]
                    )
                )

            p_residue, ts_lost = privacy_expectations(
                findings, their, pillow_dirs(p_dst), explained
            )
            if p_residue:
                bucket = "triage"
                notes.append(
                    "privacy 没删掉被点名的条目：{}".format(p_residue)
                )
            if ts_lost:
                bucket = "triage"
                notes.append(
                    "privacy 把该保留的时间戳删了：{}".format(ts_lost)
                )

            for note in xmp_residue(
                p_dst,
                src_blob,
                p_out,
                stats,
                policy="privacy",
                redacted_key="redacted_privacy",
                dropped_key="xmp_dropped_privacy",
            ):
                notes.append(note)
                bucket = "triage"

            if sha256(src) != before_input_p:
                bucket = "triage"
                notes.append("privacy 改动了输入文件本身")
            if pixels_before is not None:
                try:
                    if pixel_hash(p_dst) != pixels_before:
                        bucket = "triage"
                        notes.append("privacy 动了像素")
                except OSError as e:
                    bucket = "triage"
                    notes.append("privacy 产物解不开: {}".format(e))

        # 6) 整段摘除。写侧四步里这一步先前一条真实语料证据都没有：
        #    redact 在这个文件上改得动，strip 就必须改得动、而且要摘得更干净。
        for note in strip_step(
            moon, repo, src, out_dir, stats, doc, src_blob, pixels_before
        ):
            notes.append(note)
            bucket = "triage"
    else:
        # 没有 EXIF 不等于没有元数据：整包 XMP 可以单独存在，
        # 而那种文件的逐条清单天然是空的。不单独跑这一趟，闸就永远绿。
        if any(m in src_blob for m in XMP_MARKS):
            dst = out_dir / (src.stem + ".redacted" + src.suffix)
            before_input = sha256(src)
            try:
                pixels_before = pixel_hash(src)
            except OSError:
                pixels_before = None
            code, red_out = run_moon(
                moon,
                ["redact", str(src), "--policy", "strict", "-o", str(dst)],
                repo,
            )
            if code != 0:
                if "refusing to rewrite this bare TIFF" not in red_out:
                    bucket = "triage"
                    notes.append(
                        "只有 XMP 的文件 redact 退出码 {}: {}".format(
                            code, red_out.strip()[:160]
                        )
                    )
            else:
                for note in xmp_residue(dst, src_blob, red_out, stats):
                    notes.append(note)
                    bucket = "triage"
                if sha256(src) != before_input:
                    bucket = "triage"
                    notes.append("redact 改动了输入文件本身")
                # 这一趟删掉的是整包（实测最大的一个 12 KB 级），
                # "没碰到画面"这句主张在这类文件上最该验。
                if pixels_before is not None:
                    try:
                        if pixel_hash(dst) != pixels_before:
                            bucket = "triage"
                            notes.append("像素动了")
                    except OSError as e:
                        bucket = "triage"
                        notes.append("产物解不开: {}".format(e))

                # 默认策略在这一形状上同样是 carrier: true，而"13 个产物带着
                # 第二份元数据"就出在这一形状上：privacy 必须在这里也摘干净。
                p_dst = out_dir / (src.stem + ".privacy" + src.suffix)
                p_code, p_out = run_moon(
                    moon,
                    ["redact", str(src), "--policy", "privacy", "-o", str(p_dst)],
                    repo,
                )
                if p_code != 0:
                    bucket = "triage"
                    notes.append(
                        "privacy 在只有 XMP 的文件上退出码 {}: {}".format(
                            p_code, p_out.strip()[:160]
                        )
                    )
                else:
                    stats["privacy"] = stats.get("privacy", 0) + 1
                    for note in xmp_residue(
                        p_dst,
                        src_blob,
                        p_out,
                        stats,
                        policy="privacy",
                        redacted_key="redacted_privacy",
                        dropped_key="xmp_dropped_privacy",
                    ):
                        notes.append(note)
                        bucket = "triage"
                    if sha256(src) != before_input:
                        bucket = "triage"
                        notes.append("privacy 改动了输入文件本身")

                # 这个形状上 strip 最该验：EXIF 段本来就是空的，
                # 唯一要摘的东西就是那一整包。
                for note in strip_step(
                    moon,
                    repo,
                    src,
                    out_dir,
                    stats,
                    doc,
                    src_blob,
                    pixels_before,
                ):
                    notes.append(note)
                    bucket = "triage"

    return bucket, notes


def out_dir_inside_corpus(corpus, out_dir):
    """产物目录落在语料目录里面吗？（含同一个目录这一种）

    落在里面，这一轮写的 `.redacted` / `.privacy` / `.default` 就成了下一轮
    的语料：本机实测一次把 fixture 的 13 份扫成 33 份，"语料 99 张"这种分母
    就是这么被自己的产物顶上去的。
    """
    try:
        c = Path(corpus).resolve()
        o = Path(out_dir).resolve()
    except OSError:
        return False
    return c == o or c in o.parents


def main():
    ap = argparse.ArgumentParser(description="真实照片语料对拍")
    ap.add_argument("corpus", help="语料目录（递归扫，只读）")
    ap.add_argument("-o", "--out", default=None, help="脱敏产物目录，默认 .scratch/crosscheck")
    ap.add_argument("--moon", default="moon", help="moon 可执行文件")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个文件，调试用")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print("语料目录不存在：{}".format(corpus))
        return 2
    out_dir = Path(args.out) if args.out else repo / ".scratch" / "crosscheck"
    if out_dir_inside_corpus(corpus, out_dir):
        print(
            "输出目录 {} 落在语料目录 {} 里面：这一轮写的产物会被当成下一轮的"
            "语料，扫到的份数就不再是语料的分母了。请把 -o 指到语料之外。".format(
                out_dir, corpus
            )
        )
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p
        for p in corpus.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    if args.limit:
        files = files[: args.limit]

    # 分母先自证清白，而且分两层：`verify()` 只查结构，`load()` 才真的解像素。
    # 104 个陌生 TIFF 里就有 2 个过得了前者、过不了后者（Pillow 自己报
    # "More samples per pixel than can be decoded"）——量尺解不开的文件不能进分母。
    usable, undecodable, unreadable = [], [], []
    for p in files:
        kind = pillow_probe(p)
        if kind == "load":
            usable.append(p)
        elif kind == "verify-only":
            undecodable.append(p)
        else:
            unreadable.append(p)

    buckets = {}
    triage = []
    stats = {}
    for p in usable:
        bucket, notes = check_one(args.moon, repo, p, out_dir, stats)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if bucket == "triage":
            triage.append((p, notes))
        print("{}: {}{}".format(bucket, p.name, "" if not notes else " ← " + notes[0]))
        sys.stdout.flush()

    # 第二趟：量尺解不开的那些文件不进分母，可它们的"按设计拒绝"照样能复核——
    # 那一类判据（指针有没有越出文件、类型码在不在目录表里、三种魔数对不对）
    # 只吃这个文件自己的字节，一把读不动像素的尺子拦不住它。104 个陌生 TIFF 里
    # 有 16 个走不到第一趟，其中 10 个正是上一轮落在 triage 里的那批。
    # 分母不变（比例还是第一趟的），计数单记 `secondpass-*`，红法一样。
    second = {}
    second_pass = [(p, "verify-only") for p in undecodable] + [
        (p, "unopenable") for p in unreadable
    ]
    for p, kind in second_pass:
        doc, err = read_json(args.moon, repo, p)
        if doc is not None:
            second["secondpass-read-ok"] = second.get("secondpass-read-ok", 0) + 1
            print("no-scale: {}（引擎读得通，量尺进不去，这一格不与任何尺子比）".format(p.name))
            sys.stdout.flush()
            continue
        bucket, problems = read_refusal(err or "", p.read_bytes())
        if bucket:
            key = "secondpass-" + bucket
            second[key] = second.get(key, 0) + 1
            second["secondpass-designed"] = second.get("secondpass-designed", 0) + 1
            print("{}: {}（第二趟，{}）".format(bucket, p.name, kind))
        elif problems:
            triage.append((p, ["（第二趟，量尺进不去）" + problems[0]]))
            second["secondpass-triage"] = second.get("secondpass-triage", 0) + 1
            print("triage: {}（第二趟） ← {}".format(p.name, problems[0]))
        else:
            triage.append(
                (p, ["（第二趟，量尺进不去）读侧失败，且没有任何一句形状能被字节复核: " + text[:160]])
            )
            second["secondpass-triage"] = second.get("secondpass-triage", 0) + 1
            print("triage: {}（第二趟）".format(p.name))
        sys.stdout.flush()
    stats.update(second)

    print()
    print(
        "语料：扫到 {} 个图片文件，Pillow verify 通得过 {} 个，"
        "其中连像素也解得开的 {} 个（verify 过了却解不开 {} 个，不进分母），"
        "完全打不开 {} 个".format(
            len(files),
            len(usable) + len(undecodable),
            len(usable),
            len(undecodable),
            len(unreadable),
        )
    )
    for name in sorted(buckets):
        print("  {:<20} {}".format(name, buckets[name]))
    refused = stats.get("tiff-refused", 0)
    print(
        "拒绝复核：写侧按设计拒绝裸 TIFF {} 个（IFD0 不在偏移 8 的 {} 个{}）；"
        "读侧复核通过的设计内拒绝：类型 11/12/13 共 {} 个、类型编号不存在 {} 个、"
        "值指针越出文件之外 {} 个、声明字节放不下 {} 个、容器魔数不对 {} 个".format(
            refused,
            stats.get("tiff-refused-late-ifd", 0),
            ""
            if not refused
            else "，写下去会丢的字节最少 {} 、最多 {}".format(
                stats.get("tiff-drop-min", 0), stats.get("tiff-drop-max", 0)
            ),
            stats.get("designed-unsupported-type", 0),
            stats.get("designed-undefined-type", 0),
            stats.get("designed-malformed-pointer", 0),
            stats.get("designed-truncated-value", 0),
            stats.get("designed-wrong-magic", 0),
        )
    )
    if second:
        print(
            "第二趟（量尺进不去的 {} 个，不进分母、不改比例）：读侧拒绝只按这个文件"
            "自己的字节复核——复核通过的设计内拒绝 {} 个（类型 11/12/13 {}、"
            "类型编号不存在 {}、值指针越界 {}、声明字节放不下 {}、容器魔数不对 {}），"
            "引擎读得通而无尺可核 {} 个，复核不上而落进分诊 {} 个".format(
                len(second_pass),
                stats.get("secondpass-designed", 0),
                stats.get("secondpass-designed-unsupported-type", 0),
                stats.get("secondpass-designed-undefined-type", 0),
                stats.get("secondpass-designed-malformed-pointer", 0),
                stats.get("secondpass-designed-truncated-value", 0),
                stats.get("secondpass-designed-wrong-magic", 0),
                stats.get("secondpass-read-ok", 0),
                stats.get("secondpass-triage", 0),
            )
        )
    print(
        "XMP 闸：语料里带包 {} 个，产物复查 {} 个，摘除并披露 {} 个".format(
            stats.get("xmp_src", 0),
            stats.get("redacted", 0),
            stats.get("xmp_dropped", 0),
        )
    )
    print(
        "默认策略（privacy）：产物复查 {} 个，摘除并披露 {} 个"
        "（分母与 strict 分开记，两档各验各的）".format(
            stats.get("redacted_privacy", 0),
            stats.get("xmp_dropped_privacy", 0),
        )
    )
    print(
        "整段摘除（strip）：写侧产物 {} 个，其中源文件带着 XMP 包 {} 个"
        "（分母就是 strict redact 写出产物的文件数：这类文件一个都不许漏跑）".format(
            stats.get("stripped", 0),
            stats.get("strip_xmp", 0),
        )
    )
    print(
        "xmp 键复核：jpeg/png 共 {} 个，两个方向都跟各自字节比过".format(
            stats.get("xmp_flag", 0)
        )
    )
    print(
        "量尺归因：XMP 注入 {} 格，count=0 空声明 {} 格，GPS 指针挂在 Exif 里 {} 格"
        "（每一格都是按这个文件的字节判的，数字变了要重看）".format(
            stats.get("scale-xmp-injected", 0),
            stats.get("scale-zero-length", 0),
            stats.get("scale-gps-nested", 0),
        )
    )
    if triage:
        print()
        print("需要分诊的 {} 个：".format(len(triage)))
        for p, notes in triage:
            print("  {}".format(p.name))
            for n in notes:
                print("      {}".format(n))
    if not stats.get("stripped"):
        # 全绿但一格都没跑，等于没有这一关：语料换了、过滤器改窄了，
        # 都会让 strip 的证据悄悄归零，而退出码还是 0。
        print()
        print(
            "strip 这一关一个文件都没跑到（语料里没有一个文件的 redact 写出过产物）。"
            "这一轮的绿不包括整段摘除的证据。"
        )
        return 1
    return 1 if triage else 0


if __name__ == "__main__":
    sys.exit(main())
