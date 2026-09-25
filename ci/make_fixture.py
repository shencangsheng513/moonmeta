"""造两份真实图片给 moonmeta 做外部对照。

不自己手写 TIFF 布局：让 PIL 生成 JPEG/PNG 容器，我们只提供一份按 EXIF
规范拼出来的 APP1 载荷。反过来读回来打表，就是独立第二意见。
"""

import struct
import sys
from pathlib import Path

from PIL import Image, TiffImagePlugin

# 不带参数时落在仓库的 .scratch/fix：本地连跑三条命令不用重复敲路径，
# 也不会把测试图片写到仓库根上去。
DEFAULT_FIX = Path(__file__).resolve().parent.parent / ".scratch" / "fix"

OUT = DEFAULT_FIX
if len(sys.argv) > 1:
    OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


def ascii_entry(tag, text):
    raw = text.encode("latin-1") + b"\x00"
    return (tag, 2, len(raw), raw)


def rational_entry(tag, values):
    payload = b"".join(
        struct.pack(">II", num & 0xFFFFFFFF, den & 0xFFFFFFFF) for num, den in values
    )
    return (tag, 5, len(values), payload)


def long_entry(tag, values):
    payload = b"".join(struct.pack(">I", v & 0xFFFFFFFF) for v in values)
    return (tag, 4, len(values), payload)


IFD0 = [
    ascii_entry(0x010F, "NIKON CORPORATION"),
    ascii_entry(0x0110, "NIKON D850"),
    ascii_entry(0x0131, "MoonMeta CrossCheck 1.0"),
    ascii_entry(0x013B, "Zhang San"),
    ascii_entry(0x8298, "(C) 2026 Someone"),
]

EXIF = [
    ascii_entry(0x9003, "2026:09:24 15:51:00"),
    ascii_entry(0x9004, "2026:09:24 15:51:00"),
    ascii_entry(0x9011, "+08:00"),
    ascii_entry(0x927C, "Nikon made this"),
    ascii_entry(0xA431, "BODY-0001234567"),
    ascii_entry(0xA435, "LENS-00098"),
    rational_entry(0x9201, [(105, 10)]),
]

GPS = [
    long_entry(0x0000, [2, 3, 0, 0]),
    ascii_entry(0x0001, "N"),
    rational_entry(0x0002, [(31, 1), (13, 60), (30, 60)]),
    ascii_entry(0x0003, "E"),
    rational_entry(0x0004, [(121, 1), (8, 60), (42, 60)]),
]


def build_ifd(entries, start, next_off):
    """把 entries 拼成一个 IFD：计数 + 12 字节条目 + 下一目录指针。

    超过 4 字节的值一律放到 `start` 之后堆出来的外部区，偏移当场算。
    """
    count = len(entries)
    area_at = start + 2 + count * 12 + 4
    body = bytearray()
    tail = bytearray()
    for tag, typ, n, payload in entries:
        size = len(payload)
        if size <= 4:
            value_field = payload + b"\x00" * (4 - size)
        else:
            value_field = struct.pack(">I", area_at + len(tail))
            tail += payload
            pad = len(payload) % 2
            if pad:
                tail += b"\x00" * (2 - pad)
        body += struct.pack(">HHI", tag, typ, n) + value_field
    return struct.pack(">H", count) + bytes(body) + struct.pack(">I", next_off) + bytes(
        tail
    )


def build_exif_block():
    """TIFF 头 + IFD0（挂 Exif 指针）+ Exif（挂 GPS 指针）+ 尾部 4 字节。"""
    # 先放 Exif/GPS 两段，再让 IFD0 指过去，省掉回填
    gps_at = 8
    gps_bytes = build_ifd(GPS, gps_at, 0)
    exif_at = gps_at + len(gps_bytes)
    exif_bytes = build_ifd(
        EXIF + [(0x8825, 4, 1, struct.pack(">I", gps_at))], exif_at, 0
    )
    ifd0_at = exif_at + len(exif_bytes)
    ifd0_bytes = build_ifd(
        IFD0 + [(0x8769, 4, 1, struct.pack(">I", exif_at))], ifd0_at, 0
    )
    header = b"MM\x00\x2a" + struct.pack(">I", ifd0_at)
    return header + gps_bytes + exif_bytes + ifd0_bytes


def main():
    """写三份 fixture：带 EXIF 的 JPEG、带 EXIF 的 PNG、不带 EXIF 的 TIFF。

    第三份是"本来就没有"那条分支的对照：脱敏工具把"已清除"和"无需清除"
    混为一谈，用户就再没有信任它的理由了。
    """
    block = build_exif_block()
    img = Image.new("RGB", (24, 16), (200, 40, 40))
    img.save(OUT / "cross.jpg", "JPEG", exif=b"Exif\x00\x00" + block)
    img.save(OUT / "cross.png", "PNG", exif=block)
    img.save(OUT / "cross.tiff", "TIFF")
    (OUT / "exif_block.bin").write_bytes(block)
    print("wrote", OUT / "cross.jpg", OUT / "cross.png", OUT / "cross.tiff")


if __name__ == "__main__":
    main()
