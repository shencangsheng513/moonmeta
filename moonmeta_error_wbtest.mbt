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
    (TooShort(8, 4), ["8", "4"]),
    (BadTiffHeader(12), ["12"]),
    (BadByteOrder(0), ["0"]),
    (IfdOffsetOutOfRange(65535L), ["65535"]),
    (EntryTooLarge(0x0110, 786420, 6), ["0x0110", "786420", "6"]),
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
    (UnknownFormat(0), ["JPEG", "PNG", "TIFF"]),
  ]
  for c in cases {
    let (e, needles) = c
    cites(e.to_string(), needles)
  }
  @test.assert_eq(cases.length(), 19)
}

///|
test "CRC 用十六进制报，而且补齐到 8 位" {
  @test.assert_eq(
    (BadChecksum(33, 3421780262L, 16L)).to_string(),
    "chunk at offset 33 declares CRC 0xcbf43926 but its bytes hash to 0x00000010",
  )
}

///|
test "拒绝写入的错误明说了为什么不能只删一半" {
  cites(
    (ExtraMetadata(260)).to_string(),
    ["fake redaction"],
  )
  cites(
    (SegmentOverflow(20, 65535, 90008)).to_string(),
    ["can hold 65535", "needs 90008"],
  )
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
