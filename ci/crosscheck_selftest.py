"""归因判据自己的行为测试：解释器太宽容时，语料是查不出来的。

对拍脚本里那三条归因判据（`xmp_injected` / `zero_length_entries` /
`xmp_flag_problems`）都只在真实语料上各命中几次。把判据改宽成
`return True`，这一轮跑批照样全绿——所以光靠语料不能证明它保守。这里用合成输入正面钉住它：
每种"证据不齐"的情形都必须拒绝归因，让那格红回到 triage 里去。
`gps_via_exif_pointer`（GPS 指针挂在 Exif 里）和 `privacy_expectations`
（默认策略该删什么、该留什么）同理：后者一整批格子在语料上一次都不命中
也仍然全绿，所以它的双向门槛只能在这里钉。`strip_claims`（`strip` 那句话与
文件事实的差集）也一样——语料里只会出现其中两种说法，写成"查个子串就放行"
照样全绿，四态真值表得在这里摆全。

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
    XMP_MARKS,
    gps_via_exif_pointer,
    nested_gps_entries,
    out_dir_inside_corpus,
    privacy_expectations,
    strip_claims,
    xmp_flag_problems,
    xmp_injected,
    zero_length_entries,
)

URI = XMP_MARKS[0]  # JPEG APP1/XMP 的包标记


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


PNG_KEYWORD = XMP_MARKS[1]  # PNG 靠这个 tEXt/iTXt 关键字认包


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

    今天真踩了一次：fixture 那一轮把 `-o` 指到语料目录下，扫到 33 份，
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


# CLI 的三句原话，逐字抄在这里当量尺：改了措辞要先红在这组用例里
# （cmd/main 的 strip_said 那边也有一条同名断言）。
SAID_BOTH = "元数据已整段摘除：EXIF,XMP 包。\n已写出 out.jpg"
SAID_EXIF = "元数据已整段摘除：EXIF。\n已写出 out.jpg"
SAID_XMP = "元数据已整段摘除：XMP 包。\n已写出 out.png"
SAID_NONE = "这个文件本来就没有 EXIF，也没有 XMP 包。\n已写出 out.jpg"


class StripClaims(unittest.TestCase):
    """strip 那句话与文件事实之间的判据：四态真值表。

    这一关在语料上只命中两种（两个载体都有、只有 XMP），其余靠这里钉：
    判据一旦写松（比如退化成 `"EXIF" in output` 的子串查找），
    全绿的跑批查不出来，这组用例能。
    """

    def test_两样都摘了两样都说了_不报(self):
        self.assertEqual(strip_claims(SAID_BOTH, True, True), [])

    def test_只有XMP的文件不提EXIF_不报(self):
        # had_exif=false 时那句只点名 XMP 包，这是实话
        self.assertEqual(strip_claims(SAID_XMP, False, True), [])

    def test_两样都没有_承认没有就不报(self):
        self.assertEqual(strip_claims(SAID_NONE, False, False), [])

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

    def test_明明有却说本来就没有(self):
        # 这一格就是子串判据的陷阱：SAID_NONE 里 EXIF 和 XMP 两个词都在，
        # 查子串会以为"说了"，查点名的载体才看得出它什么都没说。
        res = strip_claims(SAID_NONE, True, True)
        self.assertEqual(
            [n for n in res if "本来就没有" in n],
            ["源文件有元数据，strip 却说这个文件本来就没有"],
        )
        self.assertEqual(len(res), 3)  # 两个载体各一条 + 谎说没有一条

    def test_两样都没有却说摘了东西(self):
        res = strip_claims(SAID_EXIF, False, False)
        self.assertEqual(
            res, ["源文件 EXIF 与 XMP 两样都没有，strip 却说摘除了东西"]
        )

    def test_两种说法都不是_也算没交代(self):
        # 前缀换掉、否定句也没有：两个载体各算一条"没点名"
        res = strip_claims("清完了。\n已写出 out.jpg", True, True)
        self.assertEqual(len(res), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
