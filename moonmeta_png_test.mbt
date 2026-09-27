// 容器层 · PNG 的行为测试。
//
// PNG 的每个块自带 CRC，所以夹具不能只拼字节：长度域和校验和都得算对，
// 否则测试就是在测自己的夹具。校验和用本库的 crc32 现算，
// 而 crc32 本身由一条公开已知答案（"123456789" → 0xCBF43926）钉住。

///|
/// 带 eXIf 的夹具布局：
///   签名 0..8 | IHDR 8..33 | eXIf 33..271（载荷 41..267）
///   | tEXt(XMP) 271..313 | IDAT 313..329 | IEND 329..341
let png_total : Int = 341

///|
fn png_push(out : Array[Byte], src : Array[Byte]) -> Unit {
  for b in src {
    out.push(b)
  }
}

///|
fn png_ascii(s : String) -> Array[Byte] {
  let out : Array[Byte] = []
  for c in s {
    out.push(c.to_int().to_byte())
  }
  out
}

///|
fn be32(n : Int) -> Array[Byte] {
  [
    (n >> 24).to_byte(),
    (n >> 16).to_byte(),
    (n >> 8).to_byte(),
    (n & 0xff).to_byte(),
  ]
}

///|
fn be32_64(v : Int64) -> Array[Byte] {
  [
    ((v >> 24) & 255L).to_byte(),
    ((v >> 16) & 255L).to_byte(),
    ((v >> 8) & 255L).to_byte(),
    (v & 255L).to_byte(),
  ]
}

///|
fn kind_ihdr() -> Array[Byte] {
  png_ascii("IHDR")
}

///|
fn kind_idat() -> Array[Byte] {
  png_ascii("IDAT")
}

///|
fn kind_iend() -> Array[Byte] {
  png_ascii("IEND")
}

///|
fn kind_text() -> Array[Byte] {
  png_ascii("tEXt")
}

///|
fn kind_exif() -> Array[Byte] {
  png_ascii("eXIf")
}

///|
/// 造一个完整块：长度 + 类型 + 载荷 + 校验和（校验和覆盖类型与载荷）。
fn png_chunk(kind : Array[Byte], payload : Array[Byte]) -> Array[Byte] {
  let body : Array[Byte] = []
  png_push(body, kind)
  png_push(body, payload)
  let out : Array[Byte] = be32(payload.length())
  png_push(out, body)
  png_push(out, be32_64(@moonmeta.crc32(Bytes::from_array(body))))
  out
}

///|
fn ihdr_payload() -> Array[Byte] {
  [
    b'\x00', b'\x00', b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x01', b'\x08',
    b'\x02', b'\x00', b'\x00', b'\x00',
  ]
}

///|
fn idat_payload() -> Array[Byte] {
  [b'\x01', b'\x02', b'\x03', b'\x04']
}

///|
/// XMP 住在 tEXt 里：关键字 + NUL + 数据包。
fn xmp_payload() -> Array[Byte] {
  let out = png_ascii("XML:com.adobe.xmp")
  png_push(out, [b'\x00'])
  png_push(out, png_ascii("<x:xmpmeta/>"))
  out
}

///|
/// 签名 + IHDR + [eXIf] + tEXt(XMP) + [附加块] + IDAT + IEND。
fn png_with_extras(tiff : Bytes?, extras : Array[Array[Byte]]) -> Bytes {
  let out : Array[Byte] = [
    b'\x89', b'P', b'N', b'G', b'\x0d', b'\x0a', b'\x1a', b'\x0a',
  ]
  png_push(out, png_chunk(kind_ihdr(), ihdr_payload()))
  match tiff {
    Some(t) => png_push(out, png_chunk(kind_exif(), t.to_array()))
    None => ()
  }
  png_push(out, png_chunk(kind_text(), xmp_payload()))
  for e in extras {
    png_push(out, e)
  }
  png_push(out, png_chunk(kind_idat(), idat_payload()))
  png_push(out, png_chunk(kind_iend(), []))
  Bytes::from_array(out)
}

///|
fn png_with(tiff : Bytes?) -> Bytes {
  png_with_extras(tiff, [])
}

///|
/// 一个文本块：关键字 + NUL + 值。真实语料里 `date:create`、`Copyright`
/// 就是这个形状。
fn text_block(keyword : String, value : String) -> Array[Byte] {
  let body = png_ascii(keyword)
  png_push(body, [b'\x00'])
  png_push(body, png_ascii(value))
  png_chunk(kind_text(), body)
}

///|
/// 白名单外的参数类块：APNG 的动画控制块，本库既不读也不删。
fn actl_block() -> Array[Byte] {
  png_chunk(png_ascii("acTL"), [b'\x00', b'\x00', b'\x00', b'\x03'])
}

///|
fn png_span(data : Bytes, from : Int, to : Int) -> Array[Byte] {
  let all = data.to_array()
  let out : Array[Byte] = []
  let mut i = from
  while i < to {
    if i >= 0 && i < all.length() {
      out.push(all[i])
    }
    i = i + 1
  }
  out
}

///|
fn png_inspect_ok(data : Bytes) -> @moonmeta.PngMap raise {
  @moonmeta.png_inspect(data) catch {
    e => fail("inspect failed: \{e}")
  }
}

///|
fn png_decoded(data : Bytes) -> @moonmeta.TiffBlock raise {
  let opt = @moonmeta.png_decode(data) catch {
    e => fail("decode failed: \{e}")
  }
  match opt {
    None => fail("expected an eXIf chunk")
    Some(t) => t
  }
}

///|
test "CRC-32 对得上公开已知答案" {
  @test.assert_eq(
    @moonmeta.crc32(Bytes::from_array(png_ascii("123456789"))),
    3421780262L,
  )
  @test.assert_eq(@moonmeta.crc32(Bytes::from_array([])), 0L)
}

///|
test "块表逐块可查，eXIf 载荷正好是那段 TIFF" {
  let file = png_with(Some(fixture()))
  @test.assert_eq(file.length(), png_total)
  let map = png_inspect_ok(file)
  @test.assert_eq(
    map.describe(),
    "PNG IHDR@8(13B) eXIf@33(226B) tEXt@271(30B) IDAT@313(4B) IEND@329(0B) ; 另含 XMP 文本块",
  )
  @test.assert_eq(map.has_xmp, true)
  match map.exif {
    None => fail("expected an eXIf span")
    Some((s, e)) => {
      @test.assert_eq(s, 41)
      @test.assert_eq(e, 267)
      @test.assert_eq(Bytes::from_array(png_span(file, s, e)), fixture())
    }
  }
}

///|
/// 与 JPEG 的 `unread` 同一条判据：白名单只收结构与图像参数，
/// 白名单外一律逐块点名。`acTL` 是动画控制块、`tEXt(Copyright)` 是人写的文字，
/// 两者都不在逐条清单里，也就都不许被"已摘除"那句话盖过去。
test "白名单外的块逐块点名，脱敏不碰它们" {
  let file = png_with_extras(Some(fixture()), [
    text_block("Copyright", "2026 shenshi"),
    actl_block(),
  ])
  let map = png_inspect_ok(file)
  @test.assert_eq(map.unread.map(c => "\{c.kind}@\{c.offset}"), [
    "tEXt@313", "acTL@347",
  ])
  @test.assert_eq(
    map.describe(),
    "PNG IHDR@8(13B) eXIf@33(226B) tEXt@271(30B) tEXt@313(22B) acTL@347(4B) IDAT@363(4B) IEND@379(0B) ; 另含 XMP 文本块 ; 未解析块 2 块：tEXt@313 acTL@347",
  )
  // 干净夹具（没有附加块）必须是空名单——否则这一栏永远是噪音
  @test.assert_eq(png_inspect_ok(png_with(Some(fixture()))).unread.length(), 0)
  // 不解析的东西不许声称删掉了：脱敏之后这两个块要逐字节还在
  let strict = @moonmeta.strict_policy()
  let (out, report) = @moonmeta.png_redact(file, strict) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(report.dropped_iptc, false)
  @test.assert_eq(inspect_contains(out, "Copyright"), true)
  @test.assert_eq(inspect_contains(out, "acTL"), true)
  @test.assert_eq(png_inspect_ok(out).unread.map(c => c.kind), ["tEXt", "acTL"])
  // XMP 那一块是解析过的载体：它该走
  @test.assert_eq(png_inspect_ok(out).has_xmp, false)
}

///|
fn inspect_contains(data : Bytes, needle : String) -> Bool {
  let all = data.to_array()
  let pat = png_ascii(needle)
  let m = pat.length()
  let mut p = 0
  let mut found = false
  while p + m <= all.length() && !found {
    let mut i = 0
    while i < m && all[p + i] == pat[i] {
      i = i + 1
    }
    if i == m {
      found = true
    }
    p = p + 1
  }
  found
}

///|
test "eXIf 里的 EXIF 读出来和裸 TIFF 块一模一样" {
  @test.assert_eq(png_decoded(png_with(Some(fixture()))), decode_ok(fixture()))
}

///|
test "没有 eXIf 的 PNG 是合法状态，不是错误" {
  let file = png_with(None)
  @test.assert_eq(png_inspect_ok(file).exif, None)
  let opt = @moonmeta.png_decode(file) catch {
    e => fail("decode failed: \{e}")
  }
  @test.assert_eq(opt, None)
  @test.assert_eq(png_inspect_ok(file).has_xmp, true)
}

///|
test "eXIf 校验和被改动：拒绝，不在坏块上报告成功" {
  let broken = png_with(Some(fixture())).to_array()
  // 保证真的改动了：加一而非赋值，否则可能撞上原本就相同的字节
  broken[267] = (broken[267].to_int() + 1).to_byte()
  try @moonmeta.png_inspect(Bytes::from_array(broken)) catch {
    @moonmeta.BadChecksum(33, _, _) => ()
    e => fail("expected BadChecksum(33,..), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "与元数据无关的坏块不挡脱敏：只验 eXIf 自己的校验和" {
  let file = png_with(Some(fixture()))
  let corrupt = file.to_array()
  corrupt[325] = (corrupt[325].to_int() + 1).to_byte()
  let (out, report) = @moonmeta.png_redact(
    Bytes::from_array(corrupt),
    @moonmeta.privacy_policy(),
  ) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(report.removed.length(), 4)
  @test.assert_eq(png_decoded(out).gps.length(), 0)
}

///|
test "两份 eXIf：拒绝，而不是只删第一份" {
  let file = png_with(Some(fixture()))
  let out : Array[Byte] = []
  png_push(out, png_span(file, 0, 271))
  png_push(out, png_chunk(kind_exif(), fixture().to_array()))
  png_push(out, png_span(file, 271, file.length()))
  try @moonmeta.png_inspect(Bytes::from_array(out)) catch {
    @moonmeta.ExtraMetadata(271) => ()
    e => fail("expected ExtraMetadata(271), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "摘掉 eXIf 之后，其余每个字节都还在原位" {
  let file = png_with(Some(fixture()))
  let (stripped, had) = @moonmeta.png_remove_exif(file) catch {
    e => fail("remove failed: \{e}")
  }
  @test.assert_eq(had, true)
  @test.assert_eq(stripped.length(), png_total - 238)
  @test.assert_eq(
    Bytes::from_array(png_span(stripped, 0, 33)),
    Bytes::from_array(png_span(file, 0, 33)),
  )
  @test.assert_eq(
    Bytes::from_array(png_span(stripped, 33, stripped.length())),
    Bytes::from_array(png_span(file, 271, png_total)),
  )
  @test.assert_eq(png_inspect_ok(stripped).exif, None)
}

///|
test "本来没有 eXIf 时，remove 报告 false 且一个字节都不动" {
  let file = png_with(None)
  let (out, had) = @moonmeta.png_remove_exif(file) catch {
    e => fail("remove failed: \{e}")
  }
  @test.assert_eq(had, false)
  @test.assert_eq(out, file)
}

///|
test "新写的 eXIf 块自带正确校验和，别人的解码器打得开" {
  let out = @moonmeta.png_replace_exif(png_with(None), fixture()) catch {
    e => fail("replace failed: \{e}")
  }
  // 重新走查会验校验和；能走查通过就说明 CRC 算对了
  let map = png_inspect_ok(out)
  match map.exif {
    Some((s, e)) => {
      @test.assert_eq(s, 41)
      @test.assert_eq(e, 267)
    }
    None => fail("expected an eXIf span")
  }
  @test.assert_eq(png_decoded(out), decode_ok(fixture()))
  @test.assert_eq(out, png_with(Some(fixture())))
}

///|
test "替换元数据时不碰 tEXt 里的 XMP" {
  let file = png_with(Some(fixture()))
  let kept = @moonmeta.png_replace_exif(file, busy_bytes()) catch {
    e => fail("replace failed: \{e}")
  }
  let map = png_inspect_ok(kept)
  @test.assert_eq(map.has_xmp, true)
  let after = match map.exif {
    Some((_, e)) => e + 4
    None => fail("expected an eXIf span")
  }
  @test.assert_eq(
    Bytes::from_array(png_span(kept, after, kept.length())),
    Bytes::from_array(png_span(file, 271, 341)),
  )
  @test.assert_eq(png_decoded(kept).gps.length(), 2)
}

///|
test "脱敏只改 eXIf 的载荷，图像数据一个字节都不动" {
  let file = png_with(Some(fixture()))
  let (out, report) = @moonmeta.png_redact(file, @moonmeta.strict_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(listing(report.removed), [
    "Exif/DateTimeOriginal(timestamps)", "GPS/GPSLatitudeRef(location)", "GPS/GPSLatitude(location)",
    "GPS/GPSLongitudeRef(location)", "GPS/GPSLongitude(location)",
  ])
  @test.assert_eq(png_decoded(out).gps.length(), 0)
  @test.assert_eq(
    Bytes::from_array(png_span(out, out.length() - 28, out.length())),
    Bytes::from_array(png_span(file, 313, 341)),
  )
}

///|
test "回写幂等：再读再写得到完全相同的字节" {
  let file = png_with(Some(fixture()))
  let out = @moonmeta.png_replace_exif(file, fixture()) catch {
    e => fail("replace failed: \{e}")
  }
  @test.assert_eq(out, file)
  @test.assert_eq(png_inspect_ok(out), png_inspect_ok(file))
}

///|
test "开头不是 PNG 签名：报出差异在第几个字节" {
  let junk = png_with(Some(fixture())).to_array()
  junk[1] = b'X'
  try @moonmeta.png_inspect(Bytes::from_array(junk)) catch {
    @moonmeta.NotPng(1) => ()
    e => fail("expected NotPng(1), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "块长字段撒谎：报出声明与实有" {
  let broken = png_with(Some(fixture())).to_array()
  broken[8] = b'\x7f'
  broken[9] = b'\xff'
  broken[10] = b'\xff'
  broken[11] = b'\xff'
  try @moonmeta.png_inspect(Bytes::from_array(broken)) catch {
    @moonmeta.SegmentTooLarge(8, 2147483647, 321) => ()
    e => fail("expected SegmentTooLarge(8,2147483647,321), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "文件在块表中间结束：报 TruncatedAt" {
  // 只留到 eXIf 块的开头：剩下的字节凑不齐 12 字节的块开销
  let out = png_span(png_with(Some(fixture())), 0, 39)
  try @moonmeta.png_inspect(Bytes::from_array(out)) catch {
    @moonmeta.TruncatedAt(33) => ()
    e => fail("expected TruncatedAt(33), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}
