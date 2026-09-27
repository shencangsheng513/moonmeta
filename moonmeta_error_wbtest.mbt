// 白盒测试：错误信息的文案。
//
// 必须在包内跑——`suberror` 的变体在包外只能匹配、不能构造，
// 而这里要的正是"把每一条都造出来渲染一遍"。
//
// 为什么值得单独立一个文件：一个脱敏工具说"坏了"没有用，要说坏在第几个字节、
// 声明了多少、实际还剩多少，用户才知道该不该信这份输出。
// 新增变体时 Show 的 match 由编译器保证穷尽，但文案没人管；
// 漏了一条不会编译失败，会在这里的覆盖率上显形。

///|
fn cites(msg : String, needles : Array[String]) -> Unit raise {
  for s in needles {
    if !msg.contains(s) {
      fail("`\{msg}` 里没有点名 `\{s}`")
    }
  }
}

///|
test "每条错误都报出自己的编号、偏移与数额" {
  let cases : Array[(MetaError, Array[String])] = [
    (TooShort(3, 8, 4), ["at offset 3", "8", "4"]),
    (BadTiffHeader(12), ["12"]),
    (BadByteOrder(0), ["0"]),
    (IfdOffsetOutOfRange(65535L), ["65535"]),
    (
      EntryTooLarge(74, 0x0110, 786420, 6),
      ["0x0110", "offset 74", "786420", "6"],
    ),
    (ValueOffsetOutOfRange(0x0110, 256L), ["0x0110", "256"]),
    (UnsupportedType(0x8826, 12), ["0x8826", "12"]),
    (SubIfdOutOfRange(0x8769, 4096L), ["0x8769", "4096"]),
    (UnencodableText(0x013b, 24352), ["0x013b", "24352"]),
    (TypeMismatch(0x9201, 5), ["0x9201", "5"]),
    (ValueOutOfRange(0x927c, -1L), ["0x927c", "-1"]),
    (NotJpeg(0), ["0"]),
    (SegmentTooLarge(2, 65534, 288), ["2", "65534", "288"]),
    (TruncatedAt(281), ["281"]),
    (SegmentOverflow(20, 65535, 90008), ["20", "65535", "90008"]),
    (ExtraMetadata(260), ["260"]),
    (NotPng(1), ["1"]),
    (BadChecksum(33, 3421780262L, 16L), ["33", "0xcbf43926"]),
    (TiffNotByteExact(6400L, 6925, 533), ["6400", "6925", "533"]),
    (UnknownFormat(0), ["JPEG", "PNG", "TIFF"]),
  ]
  for c in cases {
    let (e, needles) = c
    cites(e.to_string(), needles)
  }
  @test.assert_eq(cases.length(), 20)
}

///|
/// `ci/crosscheck_real.py` 认设计内拒绝靠的是句子形状＋句里那几个数
/// （CLI 打的是 `Show` 文案，不是变体名）。这里逐字钉整句：改文案会先红在
/// 这里，而不是让对拍脚本悄悄把整批文件重算成失败——反过来说，脚本那边
/// 只认这些句子，多出来的形状一律落进 triage。
test "语料脚本接头暗号：每一句设计内拒绝都钉成整句" {
  let exact : Array[(MetaError, String)] = [
    (
      TiffNotByteExact(6400L, 6925, 533),
      "refusing to rewrite this bare TIFF: its IFD0 sits at offset 6400, and the file's 6925 byte(s) are not what the metadata model rebuilds (533 byte(s)); the difference is bytes the model does not hold, and writing would drop them",
    ),
    (
      UnsupportedType(0x014a, 13),
      "tag 0x014a uses TIFF type 13, which this version does not decode",
    ),
    (
      ValueOffsetOutOfRange(0x015b, 294),
      "tag 0x015b points to offset 294, outside the block",
    ),
    (
      SubIfdOutOfRange(0x8769, 4048),
      "sub-IFD pointer of tag 0x8769 points to offset 4048, outside the block",
    ),
    (IfdOffsetOutOfRange(65536L), "IFD offset 65536 points outside the block"),
    (
      EntryTooLarge(10, 0, 132, 78),
      "tag 0x0000 at offset 10 declares 132 byte(s), only 78 left",
    ),
    (NotPng(1), "not a PNG: the 8-byte signature differs at offset 1"),
    (BadTiffHeader(12), "no TIFF header ('II' or 'MM') at offset 12"),
    (BadByteOrder(0), "byte-order mark at offset 0 is neither 'II' nor 'MM'"),
    (NotJpeg(7), "no JPEG start-of-image marker (0xffd8) at offset 7"),
    (
      UnknownFormat(0),
      "none of the JPEG, PNG or TIFF magics is at offset 0; the container cannot be identified",
    ),
    // 原位模式这三族。`ci/inplace_crosscheck.py` 拿它们的句子形状当接头暗号：
    // Shared / Cycle 用正则抠数，Opaque 那一族还要拿四个短语对账"说的是哪一种看不懂"。
    (
      TiffInplaceShared(
        273, 40, 16, 146, "the image data itself, declared at offset 8",
      ),
      "refusing to write this bare TIFF in place: tag 0x0111 would write offsets 40..56, but those bytes are already the image data itself, declared at offset 8 (of the table at offset 146); in-place mode never moves bytes, and it will not guess which of the two uses is the real one",
    ),
    (
      TiffInplaceCycle(146),
      "refusing to write this bare TIFF in place: the table at offset 146 is reached twice, so the file holds two readings of the same bytes and there is no way to say which one a viewer would use",
    ),
    (
      TiffInplaceOpaque(273, 0),
      "refusing to write this bare TIFF in place: tag 0x0111 declares where the pixel data sits, but its partner entry is missing; guessing wrong would delete the image, so the file is left untouched",
    ),
    (
      TiffInplaceOpaque(273, -1),
      "refusing to write this bare TIFF in place: tag 0x0111 declares where the pixel data sits, but its partner entry lists a different number of values; guessing wrong would delete the image, so the file is left untouched",
    ),
    (
      TiffInplaceOpaque(273, -2),
      "refusing to write this bare TIFF in place: tag 0x0111 declares where the pixel data sits, but the pixel range it declares runs past the end of the file; guessing wrong would delete the image, so the file is left untouched",
    ),
    (
      TiffInplaceOpaque(278, 13),
      "refusing to write this bare TIFF in place: tag 0x0116 declares where the pixel data sits, but its value is TIFF type 13, not a list of byte offsets; guessing wrong would delete the image, so the file is left untouched",
    ),
  ]
  for c in exact {
    let (e, s) = c
    @test.assert_eq(e.to_string(), s)
  }
  @test.assert_eq(exact.length(), 17)
}

///|
test "CRC 用十六进制报，而且补齐到 8 位" {
  @test.assert_eq(
    BadChecksum(33, 3421780262L, 16L).to_string(),
    "chunk at offset 33 declares CRC 0xcbf43926 but its bytes hash to 0x00000010",
  )
}

///|
test "拒绝写入的错误明说了为什么不能只删一半" {
  cites(ExtraMetadata(260).to_string(), ["fake redaction"])
  cites(SegmentOverflow(20, 65535, 90008).to_string(), [
    "can hold 65535", "needs 90008",
  ])
}

///|
test "tag 编号永远用十六进制呈现，且补齐到 4 位" {
  // 这个格式会出现在每一条解析错误里：0x110 会让人以为是十进制编号
  @test.assert_eq(tag_hex(0x0110), "0x0110")
  @test.assert_eq(tag_hex(0x8769), "0x8769")
  @test.assert_eq(tag_hex(0x0002), "0x0002")
  @test.assert_eq(tag_hex(0), "0x0000")
  @test.assert_eq(tag_hex(0xffff), "0xffff")
}
