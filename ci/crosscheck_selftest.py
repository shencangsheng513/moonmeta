"""归因判据自己的行为测试：解释器太宽容时，语料是查不出来的。

对拍脚本里那三条归因判据（`xmp_injected` / `zero_length_entries` /
`xmp_flag_problems`）都只在真实语料上各命中几次。把判据改宽成
`return True`，这一轮跑批照样全绿——所以光靠语料不能证明它保守。这里用合成输入正面钉住它：
每种"证据不齐"的情形都必须拒绝归因，让那格红回到 triage 里去。
`gps_via_exif_pointer`（GPS 指针挂在 Exif 里）和 `privacy_expectations`
（默认策略该删什么、该留什么）同理：后者一整批格子在语料上一次都不命中
也仍然全绿，所以它的双向门槛只能在这里钉。`strip_claims`（`strip` 那句话与
文件事实的差集）也一样——语料里只会出现其中两种说法，写成"查个子串就放行"
照样全绿，三个载体各自的点名与"本来就没有"那一格得在这里摆全。

这一轮再加四组：`TiffRefusalNumbers` / `TiffRefusalRecheck` / `TiffWalk` /
`ReadRefusal`，钉的是**设计内拒绝的分类判据**。为什么语料抓不到它：那句拒绝里
的数是库自己报的（IFD0 在哪、文件多少字节、模型重建多少字节、哪个 tag 用了哪个
类型码、指针越出到哪个偏移）。库把数报错时，语料只会把同一句谎话原样收下，
再按"按设计拒绝"记进分母——绿得理直气壮。只有拿这个文件的字节反着算一遍，
才分得出"这条拒绝真是设计内的"和"这句话是编的"。

最后一组 `FallbackNote` 钉的是**兜底文案本身**：那句"没有任何一句形状能被
字节复核"在四批语料上一格都不命中（命中过一次的话，上一轮第二趟里那个未定义
的名字早就炸了），所以它是那种"语料永远查不出来"的话——只能在这里钉：引擎那
一句必须原样带出来，拿不到错误句时也不许崩。

这一轮再加三组：`IptcFlag` / `UnreadItems` / `IptcResidue`，钉的是读侧新增的
`iptc`、`unread` 两位与写侧的 IPTC 残留复核。语料在这里更帮不上忙：它只会告诉
"命中时对不对"，永远不告诉"这一位被焊成恒 true（假警报）或恒 false（漏报）时
能不能红"。特别是 PNG 与裸 TIFF 上 `iptc` **必须**是 false（那两种容器没有成包
的 IPTC，报 true 就是无中生有）——语料里从来不会有这一格，因为它一次都不该命中。
`unread` 同理：那一条清单的坏法是**编**（偏移指错、名字与段码对不上、同一份字节
既算认出来又算没读懂），不是漏，编出来的东西在语料上只会以"全绿"的样子通过。
"这些格子真能红"不由这一段话自证：它长在 `ci/mutations/mut_d9e.py` 里，每处坏法
注入一次、要求红在指定用例上，跑完按字节还原并核对 sha。

跑法（不需要语料，也不需要 moon）：

    python ci/crosscheck_selftest.py -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crosscheck_real import (  # noqa: E402
    DIRS,
    IPTC_HEAD,
    IPTC_LISTED,
    TIFF_TYPE_SIZES,
    XMP_MARKS,
    gps_via_exif_pointer,
    forgive_disclosed_thumbnail,
    iptc_flag_problems,
    iptc_residue,
    jpeg_segments,
    metadata_block,
    metadata_signatures,
    nested_gps_entries,
    no_shape_note,
    out_dir_inside_corpus,
    pillow_dirs,
    png_chunks,
    privacy_expectations,
    read_refusal,
    strip_claims,
    tiff_entry_claims,
    tiff_entry_types,
    tiff_ifd0,
    tiff_refusal_numbers,
    tiff_refusal_problems,
    unread_problems,
    xmp_flag_problems,
    xmp_injected,
    zero_length_entries,
)

URI = b"http://ns.adobe.com/xap/1.0/"  # JPEG APP1/XMP 的包标记
# 这两份常量刻意写死字面量，不写 XMP_MARKS[i]：那是一份会长的名单，
# 别人往里插一项，下标就静默改指另一个头，而这里每一格的断言都在指某个具体的头。
PNG_KEYWORD = b"XML:com.adobe.xmp"  # PNG 靠这个 tEXt/iTXt 关键字认包
for _mark in (URI, PNG_KEYWORD):
    if _mark not in XMP_MARKS:
        # 用 -O 跑也不许哑掉：这行是"这里的字面量与闸扫的表同源"的唯一凭据
        raise SystemExit("selftest 的包标记 {!r} 已不在 XMP_MARKS 里".format(_mark))
del _mark


def doc_with(dir_name, entries):
    return {"directories": [{"dir": dir_name, "entries": entries}]}


def entry(tag, name, value):
    return {"tag": tag, "name": name, "type": 2, "value": value}


def blob(with_packet=True, with_orientation=True):
    out = bytearray(b"\xff\xd8\xff\xe0JFIF\x00")
    if with_packet:
        out += URI + b"<x:xmpmeta>"
        if with_orientation:
            out += b'<tiff:Orientation>1</tiff:Orientation>'
        out += b"</x:xmpmeta>"
    return bytes(out)


class XmpInjected(unittest.TestCase):
    def test_证据齐了才认(self):
        self.assertTrue(
            xmp_injected(blob(), "IFD0", {0x0112}, doc_with("IFD0", []))
        )

    def test_没有XMP包就不许拿注入当解释(self):
        self.assertFalse(
            xmp_injected(blob(with_packet=False), "IFD0", {0x0112}, doc_with("IFD0", []))
        )

    def test_包里没写这个属性就不算(self):
        self.assertFalse(
            xmp_injected(
                blob(with_orientation=False), "IFD0", {0x0112}, doc_with("IFD0", [])
            )
        )

    def test_段里已有一条同名的就不是注入(self):
        # 那种情况是真的对不上，得红。
        self.assertFalse(
            xmp_injected(
                blob(),
                "IFD0",
                {0x0112},
                doc_with("IFD0", [entry(0x0112, "Orientation", "Shorts(1 value(s))")]),
            )
        )

    def test_表外的编号一律不许归因(self):
        # 判据只认它说得出属性名的那几条；说不出就交给分诊。
        self.assertFalse(
            xmp_injected(blob(), "IFD0", {0x0132}, doc_with("IFD0", []))
        )

    def test_只适用于IFD0(self):
        self.assertFalse(
            xmp_injected(blob(), "Exif", {0x0112}, doc_with("Exif", []))
        )

    def test_一次缺两条时两条都要有证据(self):
        # 0x927c 是 MakerNote，XMP 里没有对应属性 -> 整体拒绝
        self.assertFalse(
            xmp_injected(blob(), "IFD0", {0x0112, 0x927C}, doc_with("IFD0", []))
        )


class ZeroLength(unittest.TestCase):
    def test_空串值算空声明(self):
        self.assertTrue(
            zero_length_entries(
                doc_with("IFD0", [entry(270, "0x010e", '""')]), "IFD0", {270}
            )
        )

    def test_Zero长度Raw也算(self):
        self.assertTrue(
            zero_length_entries(
                doc_with("IFD0", [entry(270, "0x010e", "Raw(0 byte(s))")]),
                "IFD0",
                {270},
            )
        )

    def test_有值的多报不许归因(self):
        self.assertFalse(
            zero_length_entries(
                doc_with("IFD0", [entry(270, "0x010e", '"A description"')]),
                "IFD0",
                {270},
            )
        )

    def test_多条里有一条有值就不许整批放行(self):
        doc = doc_with(
            "IFD0",
            [entry(270, "0x010e", '""'), entry(33432, "Copyright", '"(C) 2026"')],
        )
        self.assertFalse(zero_length_entries(doc, "IFD0", {270, 33432}))

    def test_查不到的目录返回False(self):
        self.assertFalse(
            zero_length_entries(doc_with("IFD0", []), "GPS", {270})
        )

    def test_条目不存在于该目录时不许放行(self):
        # seen.get(t) 是 None：不在白名单里，必须 False
        self.assertFalse(
            zero_length_entries(doc_with("IFD0", []), "IFD0", {270})
        )


class XmpFlag(unittest.TestCase):
    """`read --json` 的 `xmp` 键与原始字节的双向复核。

    这一位是"这个文件还有没有整包元数据"的唯一机读说法，两种不一致都得红：
    假警报会让人以为工具看见了不存在的东西，漏报就是当初那 13 个产物。
    """

    def test_说有且字节里真有_一致(self):
        self.assertEqual(
            xmp_flag_problems("jpeg", URI + b"<x:xmpmeta>", True), []
        )

    def test_说无且字节里真没有_一致(self):
        self.assertEqual(xmp_flag_problems("jpeg", b"\xff\xd8\xff\xd9", False), [])

    def test_字节里有却说无必须红(self):
        problems = xmp_flag_problems("jpeg", URI + b"<x:xmpmeta>", False)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在无", problems[0])

    def test_字节里没有却说有必须红(self):
        problems = xmp_flag_problems("jpeg", b"\xff\xd8\xff\xd9", True)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在有", problems[0])

    def test_PNG认的是关键字不是URI(self):
        self.assertEqual(xmp_flag_problems("png", PNG_KEYWORD + b"\x00<x/>", True), [])
        # 只有 URI、没有关键字：png_inspect 本来就认不到，说无是对的
        self.assertEqual(xmp_flag_problems("png", URI + b"<x/>", False), [])
        problems = xmp_flag_problems("png", PNG_KEYWORD + b"\x00<x/>", False)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在无", problems[0])

    def test_键整个不见了也要出声(self):
        self.assertEqual(
            xmp_flag_problems("jpeg", b"\xff\xd8", None),
            ["read --json 少了 xmp 键"],
        )

    def test_裸TIFF一律不判(self):
        # TIFF 的载体是 IFD0 的一条 0x02bc，逐条清单看得见它；
        # carrier_present 对 TIFF 恒返回 false 是设计，不是漏。
        self.assertEqual(
            xmp_flag_problems("tiff", URI + b"<x:xmpmeta>", False), []
        )

    def test_只有分块扩展包也算有包(self):
        # 语料里有这种文件：JPEG 里没有标准 URI，只有 extension 那一份。
        # 走查认它，`xmp` 就是 true；闸若只扫标准 URI 会在这里产假红。
        ext = b"http://ns.adobe.com/xmp/extension/"
        self.assertEqual(xmp_flag_problems("jpeg", ext + b"\x00\x00\x00\x10", True), [])
        problems = xmp_flag_problems("jpeg", ext + b"\x00\x00\x00\x10", False)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在无", problems[0])


class IptcFlag(unittest.TestCase):
    """`read --json` 的 `iptc` 键与原始字节的双向复核（I17）。

    为什么不能只靠语料：语料里 30 个 APP13 只会告诉"命中时对不对"，
    不会告诉"这一位被写成恒 true / 恒 false 时能不能红"。特别是另一半：
    PNG 与裸 TIFF 上这一位**必须**是 false——库里 PNG 的 IPTC 落在没解析的
    文本块里（走 `unread`），裸 TIFF 落在 IFD 的一条上（走逐条清单），
    在这两种容器上报 true 就是无中生有。
    """

    def test_说有且字节里真有_一致(self):
        self.assertEqual(iptc_flag_problems("jpeg", IPTC_HEAD + b"\x1c\x02", True), [])

    def test_说无且字节里真没有_一致(self):
        self.assertEqual(iptc_flag_problems("jpeg", b"\xff\xd8\xff\xd9", False), [])

    def test_字节里有却说无必须红(self):
        problems = iptc_flag_problems("jpeg", IPTC_HEAD + b"\x1c\x02", False)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在无", problems[0])

    def test_字节里没有却说有必须红(self):
        problems = iptc_flag_problems("jpeg", b"\xff\xd8\xff\xd9", True)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在有", problems[0])

    def test_差一个字节就不算包(self):
        # "Photoshop 3.1" 这种近邻头在库里是"点名但不摘"，
        # 判据若按前缀宽松匹配会把它算成包，闸就跟着库一起说瞎话。
        near = b"Photoshop 3.1\x00" + b"\x1c\x02"
        self.assertEqual(iptc_flag_problems("jpeg", near, False), [])
        problems = iptc_flag_problems("jpeg", near, True)
        self.assertEqual(len(problems), 1)
        self.assertIn("说在有", problems[0])

    def test_PNG与裸TIFF不许报成包(self):
        for kind in ("png", "tiff"):
            with self.subTest(kind=kind):
                self.assertEqual(iptc_flag_problems(kind, b"", False), [])
                problems = iptc_flag_problems(kind, IPTC_HEAD, True)
                self.assertEqual(len(problems), 1)
                self.assertIn("没有成包的 IPTC", problems[0])

    def test_连字节里有包也不改变png的结论(self):
        # 这一格钉的是"分支顺序"：容器没有成包 IPTC 时，
        # 判据不该先去搜字节再判，否则一个恰好含该字节的 PNG 会被说成"漏报"。
        self.assertEqual(iptc_flag_problems("png", IPTC_HEAD + b"tEXt", False), [])

    def test_键整个不见了也要出声(self):
        # 三种容器都要出声，且先于容器分支：漏键比"该容器不判"更严重。
        for kind in ("jpeg", "png", "tiff"):
            with self.subTest(kind=kind):
                self.assertEqual(
                    iptc_flag_problems(kind, b"", None),
                    ["read --json 少了 iptc 键"],
                )


class UnreadItems(unittest.TestCase):
    """`unread` 每一段的名字与偏移，都要在这个文件自己的字节上站得住（I18）。

    这一栏是"我看见了但没读懂"的诚实账，它的问题不是漏而是编：
    偏移指错、名字与段码对不上、同一份字节既算认出来又算没读懂——
    三种都会在语料上一次不命中，只能在这里摆全。
    """

    def setUp(self):
        # 偏移一律从段的实际长度算出来，不手打数字：手打错一位，
        # 断言就会指着另一个字节，红得像"判据坏了"。
        self.first = jpeg_app1(b"a comment", 0xFE)
        self.second = jpeg_app1(b"body", 0xE0)
        self.jpg = make_jpeg(self.first, self.second)
        self.off2 = 2 + len(self.first)

    def test_一句话说清三种坏法(self):
        # 段首偏移指着那个 0xff：COM 在偏移 2，第二条在第一条之后。
        self.assertEqual(unread_problems("jpeg", self.jpg, ["COM@2"]), [])
        self.assertEqual(
            unread_problems("jpeg", self.jpg, ["COM@2", "APP0@" + str(self.off2)]), []
        )
        png = make_png(png_chunk(b"acTL", b""))
        self.assertEqual(unread_problems("png", png, ["acTL@8"]), [])

    def test_偏移上不是段首(self):
        # 6 落在第一条的载荷里（SOI 自己那份 0xff 在 0，会被读成段码不符）
        problems = unread_problems("jpeg", self.jpg, ["COM@6"])
        self.assertEqual(len(problems), 1)
        self.assertIn("不是段首 0xff", problems[0])

    def test_名字与段码对不上(self):
        # 偏移指着那条 COM，名字却报 APP13：段码能算出来，一比对就露。
        problems = unread_problems("jpeg", self.jpg, ["APP13@2"])
        self.assertEqual(len(problems), 1)
        self.assertIn("段码却是", problems[0])

    def test_名字里没有偏移(self):
        for item in ("COM", "COM@x", "COM@"):
            with self.subTest(item=item):
                problems = unread_problems("jpeg", self.jpg, [item])
                self.assertEqual(len(problems), 1)
                self.assertIn("读不出偏移", problems[0])

    def test_不认识的段名(self):
        problems = unread_problems("jpeg", self.jpg, ["SOS@2"])
        self.assertEqual(len(problems), 1)
        self.assertIn("名字不认识", problems[0])

    def test_同一份字节不许报两遍(self):
        # 一条 APP13 段，载荷却是 `Exif\0\0`：那既是要认出来的头、
        # 又被挂进未解析段，说明两套分类在打架。
        jpg = make_jpeg(jpeg_app1(b"Exif\x00\x00" + b"II", 0xED))
        problems = unread_problems("jpeg", jpg, ["APP13@2"])
        self.assertEqual(len(problems), 1)
        self.assertIn("报了两遍", problems[0])

    def test_png偏移上没有那个块类型(self):
        png = make_png(png_chunk(b"acTL", b""))
        problems = unread_problems("png", png, ["tEXt@8"])
        self.assertEqual(len(problems), 1)
        self.assertIn("没有这个类型", problems[0])

    def test_裸TIFF有内容就是错(self):
        block = b"II" + (42).to_bytes(2, "little") + (8).to_bytes(4, "little")
        self.assertEqual(unread_problems("tiff", block, []), [])
        problems = unread_problems("tiff", block, ["COM@2"])
        self.assertEqual(len(problems), 1)
        self.assertIn("不该报出未解析段", problems[0])

    def test_键整个不见了(self):
        self.assertEqual(
            unread_problems("jpeg", b"\xff\xd8", None),
            ["read --json 少了 unread 键"],
        )

    def test_一段坏不掩盖另一段坏(self):
        # 计数口径：多条里每条各算一条，不许 return 掉第一条就完事。
        # 中间那条 COM@2 是对的，不能被邻居带跑。
        problems = unread_problems(
            "jpeg", self.jpg, ["COM@6", "COM@2", "APP13@" + str(self.off2)]
        )
        self.assertEqual(len(problems), 2)
        self.assertIn("不是段首 0xff", problems[0])
        self.assertIn("段码却是", problems[1])


class IptcResidue(unittest.TestCase):
    """写侧的 IPTC 残留复核（I19）：产物字节说了算，披露说了没说也要分得开。

    这五格在语料上只会以"摘净了"的形式出现（30 个 APP13 文件），
    剩下四种坏法——残留还红、摘净了不说、源本来没有、两趟抢同一个分母——
    一次都不命中，只能在这里造文件钉。
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.dir), ignore_errors=True)
        self.src = IPTC_HEAD + b"\x1c\x02\x00\x0e" + URI

    def write(self, name, blob):
        dst = self.dir / name
        dst.write_bytes(blob)
        return dst

    def test_产物里还有包就红_说什么都不算(self):
        dst = self.write("dirty.jpg", self.src)
        stats = {}
        res = iptc_residue(dst, self.src, "IPTC 包已摘除", stats, policy="strict")
        self.assertEqual(len(res), 1)
        self.assertIn("还有 IPTC/Photoshop 包", res[0])
        self.assertEqual(stats, {})

    def test_摘净且披露_只加摘除计数(self):
        dst = self.write("clean.jpg", b"\xff\xd8\xff\xd9")
        stats = {}
        res = iptc_residue(dst, self.src, "IPTC 包已摘除", stats)
        self.assertEqual(res, [])
        self.assertEqual(stats, {"iptc_dropped": 1})

    def test_摘净却没披露必须红(self):
        dst = self.write("silent.jpg", b"\xff\xd8\xff\xd9")
        res = iptc_residue(dst, self.src, "EXIF 已摘除", {})
        self.assertEqual(len(res), 1)
        self.assertIn("没有披露", res[0])

    def test_源本来没有包_既不红也不记账(self):
        # 没有的东西不必披露；把这一格算进"摘除 N 个"就是凭空涨分母。
        dst = self.write("plain.jpg", b"\xff\xd8\xff\xd9")
        stats = {}
        res = iptc_residue(dst, b"\xff\xd8\xff\xd9", "", stats)
        self.assertEqual(res, [])
        self.assertEqual(stats, {})

    def test_两趟各记各的键且都不碰redacted(self):
        # 与 xmp_residue 的刻意不同处：`redacted` 那个分母已由 XMP 那一趟加过，
        # 这里再加一次，"产物复查 N 个"就成了一个文件数两遍。
        dst = self.write("clean2.jpg", b"\xff\xd8\xff\xd9")
        stats = {"redacted": 1, "redacted_privacy": 1}
        self.assertEqual(
            iptc_residue(dst, self.src, "IPTC 包已摘除", stats, policy="privacy"), []
        )
        self.assertEqual(stats["redacted"], 1)
        self.assertEqual(stats["redacted_privacy"], 1)
        self.assertEqual(stats["iptc_dropped"], 1)
        self.assertNotIn("iptc_dropped_privacy", stats)
        self.assertEqual(
            iptc_residue(
                dst,
                self.src,
                "IPTC 包已摘除",
                stats,
                policy="privacy",
                dropped_key="iptc_dropped_privacy",
            ),
            [],
        )
        self.assertEqual(stats["iptc_dropped_privacy"], 1)


class GpsNested(unittest.TestCase):
    """GPSInfo 挂在 Exif 子目录里时，"我们多报了一整个目录"怎么归因。

    这条判据放行的是一整张目录，所以它只认 Pillow 自己在那个偏移上读到的
    编号：证据不齐（读不到、越界、对不上）就还得回 triage。
    """

    def test_Pillow在那个偏移读到了同一套才算(self):
        self.assertTrue(gps_via_exif_pointer({0, 1, 2}, {0, 1, 2, 3, 4}))

    def test_读不到那个IFD就不许放行(self):
        self.assertFalse(gps_via_exif_pointer({0, 1, 2}, None))

    def test_没有多报时不涉及归因(self):
        self.assertFalse(gps_via_exif_pointer(set(), {0, 1}))

    def test_越出GPS命名空间的一条不许混进来(self):
        # 0x9003 是 Exif 子目录里的时间戳：它出现在 GPS 目录里就是走查走歪了
        self.assertFalse(gps_via_exif_pointer({0, 1, 0x9003}, {0, 1, 0x9003}))

    def test_Pillow没读到的那条仍要红(self):
        self.assertFalse(gps_via_exif_pointer({0, 1, 5}, {0, 1}))


def finding(dir_name, tag, name, category):
    return {"dir": dir_name, "tag": tag, "name": name, "category": category}


ALL_DIRS = ("IFD0", "Exif", "GPS", "Interop")


def dirs(**kw):
    # 每次都给全新的 set：共享一个可变默认值，一个用例的改动会渗进下一个
    return {name: set(kw.get(name, ())) for name in ALL_DIRS}


class PrivacyExpectations(unittest.TestCase):
    """默认策略（privacy）的双向期望：该删的删了没有、该留的还在不在。

    这一批格子在真实语料上大多一次都不命中（比如"时间戳被误删"，正常情况下
    永远为空），所以全绿不说明它在工作——门槛必须在合成输入上钉。
    """

    def test_非时间戳的还读得到就是残留(self):
        f = [finding("IFD0", 271, "Make", "device_id")]
        res, lost = privacy_expectations(
            f, dirs(IFD0={271}), dirs(IFD0={271}), set()
        )
        self.assertEqual(res, [("IFD0", 271, "Make")])
        self.assertEqual(lost, [])

    def test_该删的删干净了两边都空(self):
        f = [finding("IFD0", 271, "Make", "device_id")]
        res, lost = privacy_expectations(f, dirs(IFD0={271}), dirs(), set())
        self.assertEqual((res, lost), ([], []))

    def test_时间戳在原图读得到又被删了就是误删(self):
        f = [finding("Exif", 36867, "DateTimeOriginal", "timestamps")]
        res, lost = privacy_expectations(
            f, dirs(Exif={36867}), dirs(Exif=set()), set()
        )
        self.assertEqual(lost, [("Exif", 36867, "DateTimeOriginal")])
        self.assertEqual(res, [])

    def test_时间戳留着不误报(self):
        f = [finding("Exif", 36867, "DateTimeOriginal", "timestamps")]
        res, lost = privacy_expectations(
            f, dirs(Exif={36867}), dirs(Exif={36867}), set()
        )
        self.assertEqual((res, lost), ([], []))

    def test_量尺在原图上看不到的时间戳不许报误删(self):
        # Pillow 读不到的条目，"产物里也没有"不构成证据：门槛得在原图那一侧。
        f = [finding("Exif", 36867, "DateTimeOriginal", "timestamps")]
        res, lost = privacy_expectations(f, dirs(), dirs(Exif=set()), set())
        self.assertEqual((res, lost), ([], []))

    def test_已归因的时间戳格子不算误删(self):
        # 那个值住在 XMP 包里，摘完整包之后读不到它是预期（GPS 指针那格同理）
        f = [finding("Exif", 36867, "DateTimeOriginal", "timestamps")]
        res, lost = privacy_expectations(
            f, dirs(Exif={36867}), dirs(Exif=set()), {("Exif", 36867)}
        )
        self.assertEqual((res, lost), ([], []))

    def test_归因豁免不许渗到残留那一方向(self):
        # 归因说的是"原图上量尺看漏了"，与"产物里还读得到"是两回事
        f = [finding("IFD0", 271, "Make", "device_id")]
        res, lost = privacy_expectations(
            f, dirs(), dirs(IFD0={271}), {("IFD0", 271)}
        )
        self.assertEqual(res, [("IFD0", 271, "Make")])

    def test_按目录比不许跨目录串台(self):
        # 编号 1 在 GPS 里是纬度引用、在 Interop 里是 InteropIndex
        f = [
            finding("GPS", 1, "GPSLatitudeRef", "location"),
            finding("Interop", 1, "InteropIndex", "identity"),
        ]
        res, lost = privacy_expectations(
            f, dirs(GPS={1}, Interop={1}), dirs(Interop={1}), set()
        )
        self.assertEqual(res, [("Interop", 1, "InteropIndex")])
        self.assertEqual(lost, [])


class OutDirNesting(unittest.TestCase):
    """产物目录不许落在语料目录里面，否则分母是自己喂出来的。

    这一格是 2026-09-25 真踩出来的（提交 `833dad5`）：fixture 那一轮把 `-o` 指到语料目录下，扫到 33 份，
    而按计划文件复跑时同一批 fixture 只有 13 份。
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.corpus = self.root / "fix"
        self.corpus.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_产物目录是语料的子目录_算嵌套(self):
        self.assertTrue(
            out_dir_inside_corpus(self.corpus, self.corpus / "cross-out")
        )

    def test_产物目录就是语料目录_也算(self):
        self.assertTrue(out_dir_inside_corpus(self.corpus, self.corpus))

    def test_兄弟目录不算(self):
        self.assertFalse(
            out_dir_inside_corpus(self.corpus, self.root / "cross")
        )

    def test_产物目录是语料的上一级也不算(self):
        # 语料在 fix/ 里、产物写到根：根下面确实还有别的图片，但那不是这一轮写的
        self.assertFalse(out_dir_inside_corpus(self.corpus, self.root))


# CLI 的原话，逐字抄在这里当量尺：点是哪几样由 main.mbt 的 `strip_parts` 决定
# （分隔符是 ","，句号收尾）。改了措辞要先红在这组用例里
# （cmd/main 的 strip_said / inplace_strip_said 那边也各有同名断言）。
SAID_BOTH = "元数据已整段摘除：EXIF,XMP 包。\n已写出 out.jpg"
SAID_EXIF = "元数据已整段摘除：EXIF。\n已写出 out.jpg"
SAID_XMP = "元数据已整段摘除：XMP 包。\n已写出 out.png"
SAID_ALL = "元数据已整段摘除：EXIF,XMP 包,IPTC/Photoshop 包。\n已写出 out.jpg"
SAID_IPTC = "元数据已整段摘除：IPTC/Photoshop 包。\n已写出 out.jpg"
SAID_NONE = (
    "这个文件本来就没有 EXIF，也没有 XMP 包与 IPTC 包。\n已写出 out.jpg"
)


class StripClaims(unittest.TestCase):
    """strip 那句话与文件事实之间的判据：三个载体的真值表。

    这一关在语料上只命中几种（两个载体都有、只有 XMP……），"只有 IPTC"与
    "三样都有"要靠这里钉：判据一旦写松（比如退化成 `"EXIF" in output`
    的子串查找），全绿的跑批查不出来，这组用例能。
    """

    def test_两样都摘了两样都说了_不报(self):
        self.assertEqual(strip_claims(SAID_BOTH, True, True), [])

    def test_三样都摘了三样都说了_不报(self):
        # IPTC 那一格在语料上是活的：30 个带 APP13 的文件走 strip
        self.assertEqual(strip_claims(SAID_ALL, True, True, True), [])

    def test_只有IPTC的文件只点名IPTC_不报(self):
        self.assertEqual(strip_claims(SAID_IPTC, False, False, True), [])

    def test_只有XMP的文件不提EXIF_不报(self):
        # had_exif=false 时那句只点名 XMP 包，这是实话
        self.assertEqual(strip_claims(SAID_XMP, False, True), [])

    def test_两样都没有_承认没有就不报(self):
        self.assertEqual(strip_claims(SAID_NONE, False, False), [])

    def test_三样都没有_承认没有就不报(self):
        # 与上一格同句：那句否定话同时覆盖三个载体，多一个参数不改变结论
        self.assertEqual(strip_claims(SAID_NONE, False, False, False), [])

    def test_有EXIF却没点名(self):
        res = strip_claims(SAID_XMP, True, False)
        self.assertEqual(
            [n for n in res if "EXIF 段" in n],
            ["源文件有 EXIF 段，strip 却没有交代摘除它"],
        )

    def test_有XMP包却没点名(self):
        res = strip_claims(SAID_EXIF, True, True)
        self.assertEqual(
            [n for n in res if "XMP 包" in n],
            ["源文件带着 XMP 包，strip 却没有交代摘除它"],
        )

    def test_有IPTC包却没点名(self):
        # 这一格就是 D9-E 的原始病灶：SAID_BOTH 点名了两样、独独漏 IPTC，
        # 只要判据不数第三个载体，它就一路绿。
        res = strip_claims(SAID_BOTH, True, True, True)
        self.assertEqual(
            res, ["源文件带着 IPTC/Photoshop 包，strip 却没有交代摘除它"]
        )

    def test_明明有却说本来就没有(self):
        # 这一格就是子串判据的陷阱：SAID_NONE 里 EXIF、XMP、IPTC 三个词都在，
        # 查子串会以为"说了"，查点名的载体才看得出它什么都没说。
        res = strip_claims(SAID_NONE, True, True, True)
        self.assertEqual(
            [n for n in res if "本来就没有" in n],
            ["源文件有元数据，strip 却说这个文件本来就没有"],
        )
        self.assertEqual(len(res), 4)  # 三个载体各一条 + 谎说没有一条

    def test_三样都没有却说摘了东西(self):
        res = strip_claims(SAID_EXIF, False, False, False)
        self.assertEqual(
            res,
            ["源文件 EXIF、XMP 包、IPTC 包三样都没有，strip 却说摘除了东西"],
        )

    def test_有IPTC却说三样都没有(self):
        # 与"谎说没有"同一分支，但只由 IPTC 触发：另两位都是 False。
        # 少了这一格，`had_exif or had_xmp or had_iptc` 少写一项照样全绿。
        res = strip_claims(SAID_NONE, False, False, True)
        self.assertEqual(
            sorted(res),
            sorted(
                [
                    "源文件带着 IPTC/Photoshop 包，strip 却没有交代摘除它",
                    "源文件有元数据，strip 却说这个文件本来就没有",
                ]
            ),
        )

    def test_两种说法都不是_也算没交代(self):
        # 前缀换掉、否定句也没有：三个载体各算一条"没点名"
        res = strip_claims("清完了。\n已写出 out.jpg", True, True, True)
        self.assertEqual(len(res), 3)


# 设计内拒绝的复核。句子措辞不是这里编的：那十一句由
# moonmeta_error_wbtest.mbt 逐字钉成整句，这里按同一句拼出带数的版本。
def say_tiff_refuse(ifd0, total, rebuilt):
    return (
        "x.tif: refusing to rewrite this bare TIFF: its IFD0 sits at offset {}, "
        "and the file's {} byte(s) are not what the metadata model rebuilds "
        "({} byte(s)); the difference is bytes the model does not hold, "
        "and writing would drop them"
    ).format(ifd0, total, rebuilt)


def say_type(tag, code):
    return "x.tif: tag {} uses TIFF type {}, which this version does not decode".format(
        tag, code
    )


def say_pointer(tag, off):
    return "x.tif: tag {} points to offset {}, outside the block".format(tag, off)


def say_subifd(tag, off):
    return "x.tif: sub-IFD pointer of tag {} points to offset {}, outside the block".format(
        tag, off
    )


def say_ifd_offset(off):
    return "x.tif: IFD offset {} points outside the block".format(off)


def say_declares(tag, off, declared, avail):
    return "x.tif: tag {} at offset {} declares {} byte(s), only {} left".format(
        tag, off, declared, avail
    )


def say_not_png(off):
    return "x.png: not a PNG: the 8-byte signature differs at offset {}".format(off)


# 容器级那三句。整句话由 moonmeta_error_wbtest.mbt 钉着，这里是同一句的带数版本：
# 换措辞会先红在 `moon test` 里，红不到这里来——所以这里的正则与那边必须同形。
def say_second_block(off):
    return (
        "x.jpg: a second metadata block sits at offset {}; removing only the "
        "first one would be a fake redaction"
    ).format(off)


def say_runs_out(off):
    return "x.jpg: the file runs out at offset {}, in the middle of a segment table".format(
        off
    )


def say_short_block(need, off, have):
    return "x.jpg: need {} byte(s) at offset {} but the block holds only {}".format(
        need, off, have
    )


def make_tiff(rows, extra=(), ifd0=8, little=True):
    """合成一张最小裸 TIFF：头 +（空洞补零）+ 主 IFD + 排在它后面的子 IFD。

    rows = [(tag, type, count, 值字段)]，值字段给 int 按 4 字节存，给 bytes 左对齐补零，
    给 None 就填 `extra` 里同 tag 那条子 IFD 的偏移。
    extra = [(指针 tag, 子条目表)]，指针一律按 LONG(4) 存——脚本只跟 LONG 指针。
    """
    o = "little" if little else "big"

    def pack(entries, nxt):
        out = bytearray(len(entries).to_bytes(2, o))
        for tag, typ, count, val in entries:
            v = (
                val.to_bytes(4, o)
                if isinstance(val, int)
                else (v_bytes(val)[:4].ljust(4, b"\x00"))
            )
            out += (
                tag.to_bytes(2, o)
                + typ.to_bytes(2, o)
                + count.to_bytes(4, o)
                + v
            )
        out += nxt.to_bytes(4, o)
        return bytes(out)

    body_len = 2 + 12 * len(rows) + 4
    off = ifd0 + body_len
    patch = {}
    tail = b""
    for ptr_tag, sub_rows in extra:
        patch[ptr_tag] = off
        blob = pack(sub_rows, 0)
        tail += blob
        off += len(blob)
    filled = []
    for tag, typ, count, val in rows:
        filled.append((tag, typ, count, patch.get(tag) if val is None else val))
    head = (b"II" if little else b"MM") + (42).to_bytes(2, o) + ifd0.to_bytes(4, o)
    return head + b"\x00" * (ifd0 - len(head)) + pack(filled, 0) + tail


def v_bytes(val):
    return val if isinstance(val, bytes) else str(val).encode()


class TiffRefusalNumbers(unittest.TestCase):
    def test_三个数取得出(self):
        self.assertEqual(
            tiff_refusal_numbers(say_tiff_refuse(7696, 7926, 240)),
            (7696, 7926, 240),
        )

    def test_句子换了形状_就取不出(self):
        # 取不出 → tiff_refusal_problems 给一条说明 → 那格落回 triage。
        # 不许有第三种"静悄悄放行"的路径。
        self.assertIsNone(tiff_refusal_numbers("refusing to rewrite this bare TIFF"))
        problems = tiff_refusal_problems("refusing", b"II*\x00" + b"\x00" * 40)
        self.assertEqual(len(problems), 1)
        self.assertIn("换了形状", problems[0])


class TiffRefusalRecheck(unittest.TestCase):
    def setUp(self):
        self.blob = make_tiff([(0x0112, 3, 1, 1), (0x0131, 2, 7, b"hello\x00")])

    def test_数字与文件一致时放行(self):
        text = say_tiff_refuse(8, len(self.blob), 20)
        self.assertEqual(tiff_refusal_problems(text, self.blob), [])

    def test_IFD0偏移报错了要红(self):
        text = say_tiff_refuse(8 + 1000, len(self.blob), 20)
        notes = tiff_refusal_problems(text, self.blob)
        self.assertEqual(len(notes), 1)
        self.assertIn("文件头自己写的是 8", notes[0])

    def test_文件长度报错了要红(self):
        notes = tiff_refusal_problems(
            say_tiff_refuse(8, len(self.blob) + 1, 20), self.blob
        )
        self.assertIn("实际 {} 字节".format(len(self.blob)), notes[0])

    def test_重建不比文件短_那句会丢字节就不成立(self):
        # 这一格钉的是拒绝的**理由**：模型重建出来的东西如果比文件还长，
        # 那"写下去会丢字节"根本不是事实，这个拒绝就不该被算成设计内。
        notes = tiff_refusal_problems(
            say_tiff_refuse(8, len(self.blob), len(self.blob)), self.blob
        )
        self.assertEqual(len(notes), 1)
        self.assertIn("写下去会丢字节", notes[0])

    def test_头不是TIFF时不许自称裸TIFF(self):
        blob = b"MM\x00\x2b" + b"\x00" * 34  # 魔数对，但版本号不是 42
        notes = tiff_refusal_problems(say_tiff_refuse(8, len(blob), 20), blob)
        self.assertEqual(len(notes), 1)
        self.assertIn("不是 II/MM + 42", notes[0])

    def test_大端文件也要复核得过(self):
        # 只认小端的复核会把大端文件一律判成"数字对不上"——那是假红，
        # 会让整批合法拒绝涌进 triage，然后有人把它改回不复核。
        blob = make_tiff([(0x0112, 3, 1, 1)], little=False)
        self.assertEqual(tiff_ifd0(blob), 8)
        self.assertEqual(tiff_refusal_problems(say_tiff_refuse(8, len(blob), 20), blob), [])


class TiffWalk(unittest.TestCase):
    def test_子目录里的条目也走得到(self):
        blob = make_tiff(
            [(0x0112, 3, 1, 1), (0x8769, 4, 1, None)],
            extra=[(0x8769, [(0x9003, 13, 1, 0)])],
        )
        types = tiff_entry_types(blob)
        self.assertEqual(types.get(0x9003), {13})

    def test_SHORT指针不跟_宁可找不到(self):
        # 子 IFD 指针写成 SHORT 的文件不是没有；猜错存法就是编证据，
        # 所以只跟 LONG(4)。这里要看到的是"没走到"，不是"走到了但报错"。
        blob = make_tiff([(0x8769, 3, 1, 26)])
        self.assertNotIn(0x9003, tiff_entry_types(blob))

    def test_条目数越界时停在读到的部分(self):
        head = b"II" + (42).to_bytes(2, "little") + (8).to_bytes(4, "little")
        blob = head + (60000).to_bytes(2, "little") + b"\x00" * 40
        self.assertEqual(tiff_entry_types(blob), {})

    def test_指针值的条目_算出声明字节与值偏移(self):
        # RATIONAL(5) 每个 8 字节，count=2 → 16 字节 > 4，值偏移就是第 12 字节那个指针
        blob = make_tiff([(0x015b, 5, 2, 65536)])
        self.assertEqual(tiff_entry_claims(blob)[0x015B], [(5, 16, 65536, 65536)])

    def test_放得进四字的值_偏移在条目自己身上(self):
        blob = make_tiff([(0x0112, 3, 1, 1)])
        # 表在 8，第一条从 10 开始，内联值在第 10+8 字节
        self.assertEqual(tiff_entry_claims(blob)[0x0112], [(3, 2, 18, 1)])

    def test_类型码不存在_就没有声明字节可算(self):
        # 编不出宽度的类型码不许硬凑一个数：那一格只能退回分诊
        blob = make_tiff([(0x0212, 4099, 7, 65536)])
        self.assertEqual(tiff_entry_claims(blob)[0x0212], [(4099, None, None, 65536)])


def jpeg_app1(payload, marker=0xE1):
    """一个变长段：0xff + 段码 + 2 字节大端长度（长度把自己算在内）+ 载荷。"""
    seg_len = len(payload) + 2
    return bytes([0xFF, marker]) + seg_len.to_bytes(2, "big") + payload


def make_jpeg(*segments):
    return b"\xff\xd8" + b"".join(segments)


def exif_app1(block):
    """装着一块 TIFF 的 APP1：签名那 6 字节在前，块从偏移 0 起就是它的字节。"""
    return jpeg_app1(b"Exif\x00\x00" + block)


def png_chunk(kind, payload):
    """一个 PNG 块：长度(4) + 类型(4) + 载荷 + 校验和(4)。"""
    return len(payload).to_bytes(4, "big") + kind + payload + b"\x00" * 4


def make_png(*chunks):
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


class ContainerRefusal(unittest.TestCase):
    # 三把容器级尺子（第二份元数据块 / 断在段表中间 / 块装不下）。
    # 为什么必须在这里钉：偏移是库报的，语料只会把同一句谎话原样收下再记进
    # "按设计拒绝"的分母——绿得理直气壮。这里每个桶都正反各一格。
    def setUp(self):
        self.block = b"II" + (42).to_bytes(2, "little") + (8).to_bytes(4, "little")
        # 载荷起于偏移 6（SOI 2 + 0xff/段码/长度 4），块从 12 起。
        self.jpg = make_jpeg(exif_app1(self.block))

    def test_签名单按容器各自数(self):
        # 裸 TIFF 没有段表 / 块表，一份也算不出来——"第二份"那句本来就不该
        # 在它身上判；拿整个文件当清单会让任何偏移都"复核得上"。
        self.assertEqual(metadata_signatures(self.jpg), [6])
        self.assertEqual(
            metadata_signatures(make_png(png_chunk(b"eXIf", self.block))), [8]
        )
        self.assertEqual(metadata_signatures(self.block), [])

    # ---- 第二份元数据块 ----

    def test_第二份的偏移对得上_算设计内(self):
        first = self.jpg
        second = exif_app1(self.block)
        blob = first + second
        off = len(first) + 4  # 第二个 APP1 的签名起始
        self.assertEqual(blob[off : off + 6], b"Exif\x00\x00")
        bucket, notes = read_refusal(say_second_block(off), blob)
        self.assertEqual(bucket, "designed-second-metadata-block", notes)

    def test_偏移上根本没有签名_数字复核不上(self):
        first = self.jpg
        blob = first + exif_app1(self.block)
        bucket, notes = read_refusal(say_second_block(len(blob) - 2), blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_说第二份其实是第一份_要红(self):
        # "只删第一份就是假脱敏"这句要靠"它前面还有一份"撑着：报第一份的偏移
        # 时那句不成立，不许混进设计内。
        blob = make_jpeg(exif_app1(self.block))
        bucket, notes = read_refusal(say_second_block(6), blob)
        self.assertIsNone(bucket)
        self.assertIn("前面一份都没有", notes[0])

    def test_PNG认的是块起点不是签名(self):
        one = png_chunk(b"eXIf", self.block)
        blob = make_png(one, one)
        off = 8 + len(one)
        bucket, notes = read_refusal(say_second_block(off), blob)
        self.assertEqual(bucket, "designed-second-metadata-block", notes)

    def test_第二份是XMP包也数得到(self):
        # 清单只数 Exif 签名的话，"EXIF + XMP"这种文件会说"偏移上没有签名"，
        # 而引擎那两处 raise 都认 XMP——两个方向都得放行。
        blob = self.jpg + jpeg_app1(URI + b"\x00<p/>")
        off = len(self.jpg) + 4  # 第二个 APP1 的签名起始
        self.assertEqual(blob[off : off + len(URI)], URI)
        self.assertIn(off, metadata_signatures(blob))
        bucket, notes = read_refusal(say_second_block(off), blob)
        self.assertEqual(bucket, "designed-second-metadata-block", notes)

    def test_PNG那句偏移上是IDAT时要红(self):
        # eXIf 只有一个，句子里那个偏移落在一个普通块上：既不是"第二份"，
        # 也不在清单里——不许混进设计内。
        blob = make_png(
            png_chunk(b"eXIf", self.block), png_chunk(b"IDAT", b"more")
        )
        off = 8 + 12 + len(self.block)
        bucket, notes = read_refusal(say_second_block(off), blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    # ---- 断在段表 / 块表中间 ----

    def test_段表停处一致_算设计内(self):
        # 一个长度声明 10 的段，载荷只有 2 字节：走查读到段尾之后撞在非 0xff 上。
        blob = make_jpeg(jpeg_app1(b"ab"), b"\x00\x00\x00\x00")
        _segs, stop, why = jpeg_segments(blob)
        self.assertEqual(why, "no-0xff")
        bucket, notes = read_refusal(say_runs_out(stop), blob)
        self.assertEqual(bucket, "designed-truncated-segments", notes)

    def test_谎报断点_要红(self):
        blob = make_jpeg(jpeg_app1(b"ab"), b"\x00\x00\x00\x00")
        _segs, stop, _why = jpeg_segments(blob)
        bucket, notes = read_refusal(say_runs_out(stop + 1), blob)
        self.assertIsNone(bucket)
        self.assertIn("我这遍走段表停在", notes[0])

    def test_段长越界不是断在段表中间(self):
        # 引擎在那种情况下说的是另一句（segment ... only N left）；
        # 拿"断掉"那句来套同一个文件必须打红。
        blob = b"\xff\xd8\xff\xe1" + (100).to_bytes(2, "big") + b"ab"
        _segs, stop, why = jpeg_segments(blob)
        self.assertEqual(why, "segment-runs-off-end")
        self.assertGreater(stop, len(blob))
        bucket, notes = read_refusal(say_runs_out(stop), blob)
        self.assertIsNone(bucket)
        self.assertIn("而那句说的是「断在段表中间」", notes[0])

    def test_PNG块头都放不下_算设计内(self):
        blob = make_png(png_chunk(b"IDAT", b"xyz")) + b"\x00" * 5
        _c, stop, why = png_chunks(blob)
        self.assertEqual(why, "no-chunk-header")
        bucket, notes = read_refusal(say_runs_out(stop), blob)
        self.assertEqual(bucket, "designed-truncated-segments", notes)

    # ---- 块装不下固定字节数 ----

    def test_块长对得上_算设计内(self):
        # 块只有 6 字节，TIFF 头要 8 字节——正是那句"块只有 N 字节"。
        blob = make_jpeg(exif_app1(b"II*\x00\x08\x00"))
        self.assertEqual(len(metadata_block(blob)), 6)
        bucket, notes = read_refusal(say_short_block(8, 0, 6), blob)
        self.assertEqual(bucket, "designed-short-block", notes)

    def test_谎报块长_要红(self):
        blob = make_jpeg(exif_app1(b"II*\x00\x08\x00"))
        self.assertEqual(len(metadata_block(blob)), 6)
        bucket, notes = read_refusal(say_short_block(8, 0, 99), blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_装得下却说不行_要红(self):
        blob = make_jpeg(exif_app1(b"II*\x00\x08\x00\x00\x00\x00\x00"))
        self.assertEqual(len(metadata_block(blob)), 10)
        bucket, notes = read_refusal(say_short_block(8, 0, 10), blob)
        self.assertIsNone(bucket)
        self.assertIn("那句不成立", notes[0])

    def test_容器里的块内偏移核的是块长(self):
        # 这就是 55 张首测里 hopper_bad_exif 那个形状：容器是好的，块是坏的。
        # 那句"偏移 10 之后只剩 20 字节"只有拿段表算出的块长（30）才对得上；
        # read_refusal 里把 view 换回整个文件，这一格立刻红。
        block = (
            b"II"
            + (42).to_bytes(2, "little")
            + (8).to_bytes(4, "little")
            + (11).to_bytes(2, "little")
            + b"\x00" * 20
        )
        blob = make_jpeg(exif_app1(block))
        self.assertEqual(len(metadata_block(blob)), 30)
        bucket, notes = read_refusal(say_declares("0x0000", 10, 132, 20), blob)
        self.assertEqual(bucket, "designed-truncated-value", notes)

    def test_拿整个文件长凑的剩余字节数要红(self):
        block = (
            b"II"
            + (42).to_bytes(2, "little")
            + (8).to_bytes(4, "little")
            + (11).to_bytes(2, "little")
            + b"\x00" * 20
        )
        blob = make_jpeg(exif_app1(block))
        self.assertGreater(len(blob), 30)
        bucket, notes = read_refusal(
            say_declares("0x0000", 10, 132, len(blob) - 10), blob
        )
        self.assertIsNone(bucket)
        self.assertIn("两数对不上", notes[0])

    def test_块边界算不出来不许当通过(self):
        # 一个没有 APP1 的 JPEG：块无从谈起，那句"块只有 7 字节"既不能放行
        # 也不能被"没这句话的形状"混过去——要出声，落进分诊。
        blob = make_jpeg(jpeg_app1(b"JFIF\x00\x01"), b"\xff\xd9")
        self.assertIsNone(metadata_block(blob))
        bucket, notes = read_refusal(say_short_block(8, 0, 7), blob)
        self.assertIsNone(bucket)
        self.assertIn("无从复核", notes[0])


class ReadRefusal(unittest.TestCase):
    def setUp(self):
        self.blob = make_tiff(
            [
                (0x014a, 13, 1, 0),
                (0x0112, 3, 1, 1),
                (0x015b, 5, 2, 65536),  # 16 字节从 65536 起：整个文件外
                (0x0160, 5, 1, 4),  # 8 字节从 4 起：落得进这个文件
            ],
        )

    def test_类型11到13是边界条款(self):
        bucket, notes = read_refusal(say_type("0x014a", 13), self.blob)
        self.assertEqual(bucket, "designed-unsupported-type")
        self.assertEqual(notes, [])

    def test_编号不存在算坏文件_桶要分开(self):
        blob = make_tiff([(0x0212, 4099, 1, 0)])
        bucket, _ = read_refusal(say_type("0x0212", 4099), blob)
        self.assertEqual(bucket, "designed-undefined-type")

    def test_字节里那条不是这个类型就红(self):
        # 库里把类型码读错一位，语料上是绿的——只有这一格能抓。
        bucket, notes = read_refusal(say_type("0x0112", 13), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("复核不上", notes[0])

    def test_这条tag不在文件里也红(self):
        bucket, notes = read_refusal(say_type("0x0100", 13), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("（没有这条）", notes[0])

    def test_指针本身越出文件_算设计内(self):
        bucket, _ = read_refusal(say_pointer("0x015b", 65536), self.blob)
        self.assertEqual(bucket, "designed-malformed-pointer")

    def test_指针在文件内但值越过文件尾_也算设计内(self):
        # 旧判据只认"指针本身越出去"，于是 104 个陌生 TIFF 里 4 个真越界的
        # 被报成复核不通过。那句"越出块外"说的是值的那段字节放不下。
        blob = make_tiff([(0x015b, 5, 2, 20)])  # 16 字节，指针 20 在 26 字节的文件内
        self.assertLess(20, len(blob))
        bucket, notes = read_refusal(say_pointer("0x015b", 20), blob)
        self.assertEqual(bucket, "designed-malformed-pointer", notes)

    def test_指针和值都放得进_不许拿设计内当解释(self):
        bucket, notes = read_refusal(say_pointer("0x0160", 4), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("复核不通过", notes[0])

    def test_字节里没有这条指针_数字复核不上(self):
        # 内联值那条根本不可能报出"值指针越界"；拿它凑数就是编证据
        bucket, notes = read_refusal(say_pointer("0x0112", 30), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_不是TIFF头时无从复核块边界(self):
        bucket, notes = read_refusal(say_pointer("0x014a", 9999), b"\x00" * 30)
        self.assertIsNone(bucket)
        self.assertIn("无从复核", notes[0])

    def test_魔数说对了算设计内(self):
        bucket, _ = read_refusal(say_not_png(0), b"not a png at all")
        self.assertEqual(bucket, "designed-wrong-magic")

    def test_魔数其实就在那里却说没有要红(self):
        blob = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        bucket, notes = read_refusal(say_not_png(0), blob)
        self.assertIsNone(bucket)
        self.assertIn("就是签名", notes[0])

    def test_句子形状不认识时既不放行也不编说明(self):
        bucket, notes = read_refusal("some other wording entirely", self.blob)
        self.assertIsNone(bucket)
        self.assertEqual(notes, [])


class SubIfdRefusal(unittest.TestCase):
    def setUp(self):
        # Exif 指针（LONG、count=1）指向 4048，文件只有 26 字节
        self.blob = make_tiff([(0x8769, 4, 1, 4048)])

    def test_指针越出文件且字节里那条就是它_算设计内(self):
        bucket, notes = read_refusal(say_subifd("0x8769", 4048), self.blob)
        self.assertEqual(bucket, "designed-malformed-pointer", notes)

    def test_值字段不是那个数_数字复核不上(self):
        bucket, notes = read_refusal(say_subifd("0x8769", 1234), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_指针落得进去_不许拿设计内当解释(self):
        blob = make_tiff([(0x8769, 4, 1, 20)])
        bucket, notes = read_refusal(say_subifd("0x8769", 20), blob)
        self.assertIsNone(bucket)
        self.assertIn("复核不通过", notes[0])


class IfdOffsetRefusal(unittest.TestCase):
    def test_文件头写的就是它且越出文件_算设计内(self):
        blob = b"II" + (42).to_bytes(2, "little") + (9000).to_bytes(4, "little") + b"\x00" * 20
        bucket, notes = read_refusal(say_ifd_offset(9000), blob)
        self.assertEqual(bucket, "designed-malformed-pointer", notes)

    def test_文件头写的是别的数_数字复核不上(self):
        blob = b"II" + (42).to_bytes(2, "little") + (8).to_bytes(4, "little") + b"\x00" * 20
        bucket, notes = read_refusal(say_ifd_offset(9000), blob)
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_偏移落得进文件_不许拿设计内当解释(self):
        blob = b"II" + (42).to_bytes(2, "little") + (8).to_bytes(4, "little") + b"\x00" * 20
        bucket, notes = read_refusal(say_ifd_offset(8), blob)
        self.assertIsNone(bucket)
        self.assertIn("复核不通过", notes[0])


class DeclaredBytesRefusal(unittest.TestCase):
    def setUp(self):
        # 头 + 空洞 + 表长 11 条（132 字节）却只给了 20 字节的表体
        self.blob = (
            b"II"
            + (42).to_bytes(2, "little")
            + (8).to_bytes(4, "little")
            + (11).to_bytes(2, "little")
            + b"\x00" * 20
        )

    def test_目录表放不下_三个数都对得上_算设计内(self):
        off = 10
        blob = self.blob
        bucket, notes = read_refusal(
            say_declares("0x0000", off, 132, len(blob) - off), blob
        )
        self.assertEqual(bucket, "designed-truncated-value", notes)

    def test_声明字节数与条目数对不上_数字复核不上(self):
        blob = self.blob
        bucket, notes = read_refusal(
            say_declares("0x0000", 10, 144, len(blob) - 10), blob
        )
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])

    def test_剩余字节数与文件长对不上_要红(self):
        bucket, notes = read_refusal(say_declares("0x0000", 10, 132, 9999), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("两数对不上", notes[0])

    def test_声明的字节其实够用_那句不成立(self):
        bucket, notes = read_refusal(say_declares("0x0000", 10, 4, 20), self.blob)
        self.assertIsNone(bucket)
        self.assertIn("那句不成立", notes[0])

    def test_单个条目那一支也算得过(self):
        # tag 不记 0 的那一支实际到不了（前面两道长度闸挡着），复算照样做
        blob = make_tiff([(0x015b, 5, 1, 20)])  # RATIONAL ×1 = 8 字节，从 20 起
        bucket, notes = read_refusal(
            say_declares("0x015b", 20, 8, len(blob) - 20), blob
        )
        self.assertEqual(bucket, "designed-truncated-value", notes)

    def test_单个条目报错了字节数_数字复核不上(self):
        blob = make_tiff([(0x015b, 5, 1, 20)])
        bucket, notes = read_refusal(
            say_declares("0x015b", 20, 99, len(blob) - 20), blob
        )
        self.assertIsNone(bucket)
        self.assertIn("那个数字复核不上", notes[0])


class TiffTypeSizes(unittest.TestCase):
    # 这张表是脚本自己抄规范的，与库的 type_size 是两份。两份都得有人钉：
    # 库那份在 moonmeta_value_test.mbt，这一份在这里。
    SPEC = [
        (1, 1),
        (2, 1),
        (3, 2),
        (4, 4),
        (5, 8),
        (6, 1),
        (7, 1),
        (8, 2),
        (9, 4),
        (10, 8),
        (11, 4),
        (12, 8),
        (13, 4),
    ]

    def test_规范里13个类型码逐个对(self):
        for code, size in self.SPEC:
            self.assertEqual(TIFF_TYPE_SIZES.get(code), size, "类型码 {}".format(code))

    def test_规范没给的编号不许有宽度(self):
        for code in (0, 14, 99, -1):
            self.assertNotIn(code, TIFF_TYPE_SIZES)


class ThumbnailForgiveness(unittest.TestCase):
    # "缩略图指针没了"这一格只在命令行当场说过的时候才豁免。
    # 抄一份编号名单放行会让"条目消失但工具一个字没提"变成全绿——
    # 那正是这一格存在的理由，所以四个方向都要钉。
    SAID = "删除 4 条，并丢掉可能自带坐标的缩略图。"
    UNSAID = "删除 4 条。"

    def test_披露过的缩略图指针算设计内(self):
        lost = [("IFD0", 0x0201), ("IFD0", 0x0202)]
        self.assertEqual(forgive_disclosed_thumbnail(lost, self.SAID), [])

    def test_没说过的同样两格仍然要红(self):
        lost = [("IFD0", 0x0201), ("IFD0", 0x0202)]
        self.assertEqual(
            forgive_disclosed_thumbnail(lost, self.UNSAID), lost
        )

    def test_别的编号不许被这句话放行(self):
        lost = [("IFD0", 0x013B), ("IFD0", 0x0202)]
        self.assertEqual(
            forgive_disclosed_thumbnail(lost, self.SAID), [("IFD0", 0x013B)]
        )

    def test_同一个编号挂在别的目录也不放行(self):
        # 0x0201 在 GPS 目录里是 GPSLatitude：它没了绝不是缩略图的事
        lost = [("GPS", 0x0201)]
        self.assertEqual(
            forgive_disclosed_thumbnail(lost, self.SAID), [("GPS", 0x0201)]
        )

    def test_输出为空时一律不豁免(self):
        self.assertEqual(
            forgive_disclosed_thumbnail([("IFD0", 0x0202)], ""),
            [("IFD0", 0x0202)],
        )


class RulerRefusesProduct(unittest.TestCase):
    # 量尺读不出来时必须返回 None，而且**不许**把异常抛出去：
    # 上一批外来语料里我们的产物不是合法 JPEG，`pillow_dirs` 直接把整批
    # 跑批在 12/55 处崩掉——一个红都没数到，看起来像"脚本坏了"而不是
    # "我们写坏了文件"。反向对照同样钉在这里：只写 `return None` 的
    # 实现会让每一格都变成"跳过"，全绿。
    def test_不是图的文件返回None不抛(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "not-an-image.jpg"
            p.write_bytes(b"\xff\xd8\xff\xe1 this is not a jpeg at all")
            self.assertIsNone(pillow_dirs(p))

    def test_根本不存在的路径也只返回None(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(pillow_dirs(Path(td) / "missing.png"))

    def test_真图照常返回四张目录(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "real.png"
            Image.new("RGB", (4, 3), (10, 20, 30)).save(p)
            out = pillow_dirs(p)
            self.assertIsNotNone(out)
            self.assertEqual(sorted(out.keys()), sorted(DIRS))
            self.assertEqual(out["IFD0"], set())


class FallbackNote(unittest.TestCase):
    # 兜底那句是"复核不上"时唯一给人看的东西：把它写成固定文案，红就变成
    # 一句没有出处的话；把参数写成 None 就干脆崩在这条路上。
    # 上一轮第二趟就地抄了一遍这句话、抄来了一个作用域里没有的名字，
    # 命中就是 NameError——所以两趟现在共用 no_shape_note，这一格钉住它。
    def test_引擎那一句必须出现在兜底里(self):
        sentence = "tag 0x0112 uses TIFF type 99, which TIFF 6.0 does not define"
        note = no_shape_note(sentence)
        self.assertIn("读侧失败", note)
        self.assertIn(sentence, note)

    def test_err为空也要出一句完整话不崩(self):
        for err in (None, ""):
            note = no_shape_note(err)
            self.assertTrue(note.startswith("读侧失败"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
