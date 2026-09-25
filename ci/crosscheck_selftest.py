"""归因判据自己的行为测试：解释器太宽容时，语料是查不出来的。

对拍脚本里那三条判据（`xmp_injected` / `zero_length_entries` /
`xmp_flag_problems`）都只在真实语料上各命中几次。把判据改宽成
`return True`，这一轮跑批照样全绿——所以光靠语料不能证明它保守。这里用合成输入正面钉住它：
每种"证据不齐"的情形都必须拒绝归因，让那格红回到 triage 里去。

跑法（不需要语料，也不需要 moon）：

    python ci/crosscheck_selftest.py -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crosscheck_real import (  # noqa: E402
    XMP_MARKS,
    gps_via_exif_pointer,
    nested_gps_entries,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
