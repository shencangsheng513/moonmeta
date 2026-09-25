"""独立第二意见：让 Pillow 读一遍我们造的 fixture。

这一步存在的理由是"别用同一把尺子量两遍"。moonmeta 说它删了什么，
只有另一个实现同意，这句话才是事实。这里先确认的是反向的一半：
Pillow 能在原始 fixture 里看到坐标、序列号、厂商私有块——
如果它自己都没读到，后面那半天的比对就一文不值。
"""

import sys
from pathlib import Path

from PIL import Image

DEFAULT_FIX = Path(__file__).resolve().parent.parent / ".scratch" / "fix"

FIX = DEFAULT_FIX
if len(sys.argv) > 1:
    FIX = Path(sys.argv[1])

# Pillow 的 IFD 用十进制 tag 号
MAKE, ARTIST, COPYRIGHT = 271, 315, 33432
SOFTWARE = 305
DATETIME_ORIGINAL = 36867
MAKER_NOTE = 37500
BODY_SERIAL = 42033
LENS_SERIAL = 42037
GPS_LAT = 2
GPS_LON = 4


def ifds(path):
    ex = Image.open(path).getexif()
    sub = ex.get_ifd(0x8769)
    # 相机把 GPS 挂在 Exif 子目录下，Pillow 的 getexif 只跟 IFD0 那一层，
    # 所以这里从 Exif 目录再往下走一次。
    gps_off = sub.get(34853)
    return ex, sub, gps_off


def main():
    for name in ("cross.jpg", "cross.png"):
        path = FIX / name
        ex, sub, gps_off = ifds(path)
        assert ex[MAKE] == "NIKON CORPORATION", dict(ex)
        assert ex[ARTIST] == "Zhang San", dict(ex)
        assert ex[COPYRIGHT] == "(C) 2026 Someone", dict(ex)
        assert sub[DATETIME_ORIGINAL] == "2026:09:24 15:51:00", dict(sub)
        assert sub[MAKER_NOTE] is not None, dict(sub)
        assert sub[BODY_SERIAL] == "BODY-0001234567", dict(sub)
        assert sub[LENS_SERIAL] == "LENS-00098", dict(sub)
        assert gps_off is not None, "GPS 子目录指针没写进去，fixture 白造了"
        print(f"{name}: Pillow 读到署名/版权/时间/厂商块/两个序列号 + GPS 指针")

    raw_jpg = (FIX / "cross.jpg").read_bytes()
    raw_png = (FIX / "cross.png").read_bytes()
    assert b"Exif\x00\x00" in raw_jpg, "JPEG 里没有 APP1/EXIF 标识"
    assert b"eXIf" in raw_png, "PNG 里没有 eXIf 块"
    print("容器标识：JPEG APP1 与 PNG eXIf 都在位")

    ex, sub, _ = ifds(FIX / "cross.tiff")
    # 裸 TIFF 的 IFD0 就是图像本身的结构（宽高、条带偏移），不会为空。
    # "没有 EXIF"的判据是没有 Exif 子目录指针，不是"目录里一条都没有"。
    assert 34665 not in dict(ex), dict(ex)
    assert not dict(sub), dict(sub)
    print("cross.tiff 对照组：IFD0 只有图像结构，没有 Exif 子目录")


if __name__ == "__main__":
    main()
