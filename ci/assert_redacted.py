"""验收 moonmeta 的写操作：Pillow 说了算，不是 moonmeta 说了算。

CLI 会打印"删除 12 条"，但那只是它自己的说法。这里检查三件它没法
自证清白的事：

1. 敏感条目确实从文件里消失了（另一个实现读不到）；
2. 没被策略点名的东西确实还在（脱敏不等于砸字段）；
3. 输入文件一个字节都没动（默认不就地改，是这条命令行的硬规矩）。

外加图像像素必须逐字节相同——元数据处理弄坏了图，删得再干净也没用。
"""

import sys
from pathlib import Path

from PIL import Image

DEFAULT_FIX = Path(__file__).resolve().parent.parent / ".scratch" / "fix"

FIX = DEFAULT_FIX
if len(sys.argv) > 1:
    FIX = Path(sys.argv[1])

# 严格策略之后这些必须消失
MUST_GO_IFD0 = {"Artist": 315}
MUST_GO_EXIF = {
    "DateTimeOriginal": 36867,
    "DateTimeDigitized": 36868,
    "OffsetTimeOriginal": 36881,
    "MakerNote": 37500,
    "BodySerialNumber": 42033,
    "LensSerialNumber": 42037,
}
# 这些不在任何敏感类别里，删掉它们就是砸字段
MUST_STAY_IFD0 = {"Make": 271, "Model": 272, "Software": 305, "Copyright": 33432}


def ifds(path):
    ex = Image.open(path).getexif()
    sub = ex.get_ifd(0x8769)
    return ex, sub, sub.get(34853)


def pixels(path):
    im = Image.open(path)
    im.load()
    return im.tobytes()


def check_gone_and_kept(name, expect_redacted=True):
    ex, sub, gps_off = ifds(FIX / name)
    if not expect_redacted:
        return
    for label, tag in MUST_GO_IFD0.items():
        assert tag not in dict(ex), f"{name}: {label} 居然还在 IFD0 里"
    for label, tag in MUST_GO_EXIF.items():
        assert tag not in dict(sub), f"{name}: {label} 居然还在 Exif 里"
    assert gps_off is None, f"{name}: GPS 子目录指针还在，等于没删坐标"
    for label, tag in MUST_STAY_IFD0.items():
        assert tag in dict(ex), f"{name}: {label} 被误删了，策略没点名它"


def main():
    src_jpg = FIX / "cross.jpg"
    src_png = FIX / "cross.png"
    orig_jpg_bytes = src_jpg.read_bytes()
    orig_png_bytes = src_png.read_bytes()

    check_gone_and_kept("cross.redacted.jpg")
    check_gone_and_kept("cross.redacted.png")
    print("redact：严格策略点名的条目 Pillow 已读不到，未点名的仍在")

    for name in ("cross.stripped.jpg", "cross.stripped.png"):
        ex, sub, gps_off = ifds(FIX / name)
        assert len(dict(ex)) <= 1, f"{name}: strip 之后还剩 {dict(ex)}"
        assert not dict(sub), f"{name}: strip 之后 Exif 子目录还在"
        assert gps_off is None, f"{name}: strip 之后 GPS 指针还在"
    print("strip：两个文件的 EXIF 被 Pillow 读成空")

    assert src_jpg.read_bytes() == orig_jpg_bytes, "输入 JPEG 被动过了"
    assert src_png.read_bytes() == orig_png_bytes, "输入 PNG 被动过了"
    print("输入文件逐字节未改")

    assert pixels(src_jpg) == pixels(FIX / "cross.redacted.jpg")
    assert pixels(src_jpg) == pixels(FIX / "cross.stripped.jpg")
    assert pixels(src_png) == pixels(FIX / "cross.redacted.png")
    assert pixels(src_png) == pixels(FIX / "cross.stripped.png")
    print("像素：四种写操作之后与原图完全一致")

    ex, sub, _ = ifds(FIX / "cross.tiff")
    assert 34665 not in dict(ex), "对照组本身就带 EXIF，那前面全白测了"
    assert not dict(sub), dict(sub)


if __name__ == "__main__":
    main()
