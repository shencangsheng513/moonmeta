// 容器层 · JPEG 的行为测试。
//
// 夹具是手工拼的最小 JPEG，段长字段按规范自己算——
// "我们的解析器认为对"只能当测试的输出，不能当测试的输入。
//
// 夹具的字节布局（TIFF 块 226 字节）：
//   SOI 0..2 | APP0 2..20 | APP1 20..256（标识 24..30，TIFF 30..256）
//   | COM 256..272 | SOS 272..281 | 压缩流 281..291 | EOI 291..293

///|
/// ASCII 串转字节。夹具里的字符串全是 ASCII，逐字符截断成字节即可。
fn ascii(s : String) -> Array[Byte] {
  let out : Array[Byte] = []
  for c in s {
    out.push(c.to_int().to_byte())
  }
  out
}

///|
fn push(out : Array[Byte], src : Array[Byte]) -> Unit {
  for b in src {
    out.push(b)
  }
}

///|
fn be16(n : Int) -> Array[Byte] {
  [(n >> 8).to_byte(), (n & 0xff).to_byte()]
}

///|
/// 一个带长度域的段：`FF <marker>` + 长度（把自己算在内）+ 载荷。
fn var_seg(marker : Int, payload : Array[Byte]) -> Array[Byte] {
  let out : Array[Byte] = [b'\xff', marker.to_byte()]
  push(out, be16(payload.length() + 2))
  push(out, payload)
  out
}

///|
fn exif_identifier() -> Array[Byte] {
  let out = ascii("Exif")
  push(out, [b'\x00', b'\x00'])
  out
}

///|
fn xmp_identifier() -> Array[Byte] {
  let out = ascii("http://ns.adobe.com/xap/1.0/")
  push(out, [b'\x00'])
  out
}

///|
fn jfif_payload() -> Array[Byte] {
  [
    b'J', b'F', b'I', b'F', b'\x00', b'\x01', b'\x02', b'\x00', b'\x00', b'\x01',
    b'\x00', b'\x01', b'\x00', b'\x00',
  ]
}

///|
fn sos_payload() -> Array[Byte] {
  [b'\x01', b'\x00', b'\x00', b'\x3f', b'\x00']
}

///|
/// 压缩流的替身：刻意不含任何元数据标识，免得被自己的尾部扫描误报。
fn entropy_data() -> Array[Byte] {
  [
    b'\x00', b'\x11', b'\x22', b'\x33', b'\x44', b'\x55', b'\x66', b'\x77', b'\x88',
    b'\x99',
  ]
}

///|
/// 装进 APP1 的完整载荷：标识 + TIFF 块，共 6 + 226 = 232 字节。
fn app1_payload(tiff : Bytes) -> Array[Byte] {
  let out = exif_identifier()
  push(out, tiff.to_array())
  out
}

///|
/// 取 `[from, to)`；越界时静默少给，让长度断言去发现问题。
fn span(data : Bytes, from : Int, to : Int) -> Array[Byte] {
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
/// 尾部 n 个字节。
fn last_bytes(data : Bytes, n : Int) -> Array[Byte] {
  span(data, data.length() - n, data.length())
}

///|
/// SOI + APP0 + [APP1/EXIF] + COM + SOS + 压缩流 + EOI。
fn jpeg_with(tiff : Bytes?) -> Bytes {
  let out : Array[Byte] = [b'\xff', b'\xd8']
  push(out, var_seg(0xe0, jfif_payload()))
  match tiff {
    Some(t) => push(out, var_seg(0xe1, app1_payload(t)))
    None => ()
  }
  push(out, var_seg(0xfe, ascii("moonbit test")))
  push(out, var_seg(0xda, sos_payload()))
  push(out, entropy_data())
  push(out, [b'\xff', b'\xd9'])
  Bytes::from_array(out)
}

///|
fn inspect_ok(data : Bytes) -> @moonmeta.JpegMap raise {
  @moonmeta.jpeg_inspect(data) catch {
    e => fail("inspect failed: \{e}")
  }
}

///|
/// 夹具里必须读得出 EXIF，读不出来就是夹具坏了或者解析器坏了——
/// 两种情况都不该让测试安静地通过。
fn decoded(data : Bytes) -> @moonmeta.TiffBlock raise {
  let opt = @moonmeta.jpeg_decode(data) catch {
    e => fail("decode failed: \{e}")
  }
  match opt {
    None => fail("expected an EXIF block")
    Some(t) => t
  }
}

///|
fn contains_bytes(haystack : Bytes, needle : Array[Byte]) -> Bool {
  let n = haystack.length()
  let m = needle.length()
  let mut p = 0
  let mut found = false
  while p + m <= n && !found {
    let mut i = 0
    while i < m && haystack.get(p + i) == needle.get(i) {
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
test "APP1 里的 EXIF 读出来和裸 TIFF 块一模一样" {
  let file = jpeg_with(Some(fixture()))
  @test.assert_eq(file.length(), 293)
  @test.assert_eq(decoded(file), decode_ok(fixture()))
}

///|
/// 夹具里那条 COM 注释（`moonbit test`）是"我们读不了、也不假装删掉了"的那一类：
/// 它必须在 describe 里点名下落，不许被静默略过。
test "段表的命名与偏移逐段可查，EXIF 载荷正好是那段 TIFF" {
  let file = jpeg_with(Some(fixture()))
  let map = inspect_ok(file)
  @test.assert_eq(
    map.describe(),
    "JPEG SOI@0 APP0@2 APP1@20 COM@256 SOS@272 ; 未解析段 1 段：COM@256",
  )
  @test.assert_eq(map.has_xmp, false)
  @test.assert_eq(map.has_iptc, false)
  @test.assert_eq(map.unread.map(s => "\{s.name()}@\{s.offset}"), ["COM@256"])
  match map.exif {
    None => fail("expected an EXIF span")
    Some((s, e)) => {
      @test.assert_eq(s, 30)
      @test.assert_eq(e, 256)
      @test.assert_eq(Bytes::from_array(span(file, s, e)), fixture())
    }
  }
}

///|
test "走查在 SOS 处停下，压缩流之后的东西不进段表" {
  let names : Array[String] = []
  for s in inspect_ok(jpeg_with(Some(fixture()))).segments {
    names.push("\{s.name()}@\{s.offset}")
  }
  @test.assert_eq(names, ["SOI@0", "APP0@2", "APP1@20", "COM@256", "SOS@272"])
}

///|
test "没有 EXIF 的 JPEG 是合法状态，不是错误" {
  let file = jpeg_with(None)
  @test.assert_eq(inspect_ok(file).exif, None)
  let opt = @moonmeta.jpeg_decode(file) catch {
    e => fail("decode failed: \{e}")
  }
  @test.assert_eq(opt, None)
}

///|
test "摘掉 APP1 之后，其余每个字节都还在原位" {
  let file = jpeg_with(Some(fixture()))
  let (stripped, had) = @moonmeta.jpeg_remove_exif(file) catch {
    e => fail("remove failed: \{e}")
  }
  @test.assert_eq(had, true)
  @test.assert_eq(stripped.length(), 293 - 236)
  // 头部（SOI + APP0）原样
  @test.assert_eq(
    Bytes::from_array(span(stripped, 0, 20)),
    Bytes::from_array(span(file, 0, 20)),
  )
  // 尾部（COM + SOS + 压缩流 + EOI）原样，只是整体前移了一整段
  @test.assert_eq(
    Bytes::from_array(span(stripped, 20, 57)),
    Bytes::from_array(span(file, 256, 293)),
  )
  @test.assert_eq(contains_bytes(stripped, exif_identifier()), false)
}

///|
test "本来就没有 EXIF 时，strip 报告 false 且一个字节都不动" {
  let file = jpeg_with(None)
  let (out, had) = @moonmeta.jpeg_remove_exif(file) catch {
    e => fail("remove failed: \{e}")
  }
  @test.assert_eq(had, false)
  @test.assert_eq(out, file)
}

///|
/// 在 APP1/EXIF 之后追加一段 APP1/XMP，插在压缩流之前——真实相机就这么放。
fn append_xmp_app1(data : Bytes) -> Bytes raise {
  let span_after = match inspect_ok(data).exif {
    Some((_, e)) => e
    None => fail("fixture has no EXIF")
  }
  let out : Array[Byte] = []
  push(out, span(data, 0, span_after))
  push(out, var_seg(0xe1, xmp_identifier()))
  push(out, span(data, span_after, data.length()))
  Bytes::from_array(out)
}

///|
test "替换 EXIF 时不碰隔壁的 XMP 段" {
  let base = jpeg_with(Some(fixture()))
  let with_xmp = append_xmp_app1(base)
  @test.assert_eq(inspect_ok(with_xmp).has_xmp, true)
  let kept = @moonmeta.jpeg_replace_exif(with_xmp, fixture()) catch {
    e => fail("replace failed: \{e}")
  }
  @test.assert_eq(contains_bytes(kept, xmp_identifier()), true)
  @test.assert_eq(inspect_ok(kept).has_xmp, true)
  @test.assert_eq(decoded(kept).gps.length(), 4)
}

///|
test "XMP 冒充的 APP1 不会被当成 EXIF，也不会被 strip 误伤" {
  let out : Array[Byte] = [b'\xff', b'\xd8']
  push(out, var_seg(0xe1, xmp_identifier()))
  push(out, var_seg(0xda, sos_payload()))
  push(out, entropy_data())
  push(out, [b'\xff', b'\xd9'])
  let file = Bytes::from_array(out)
  let map = inspect_ok(file)
  @test.assert_eq(map.has_xmp, true)
  @test.assert_eq(map.exif, None)
  let (stripped, had) = @moonmeta.jpeg_remove_exif(file) catch {
    e => fail("remove failed: \{e}")
  }
  @test.assert_eq(had, false)
  @test.assert_eq(stripped, file)
}

///|
test "摘 XMP 只摘那一段：EXIF 还读得出来，尾巴一个字节没动" {
  let with_xmp = append_xmp_app1(jpeg_with(Some(fixture())))
  let before = inspect_ok(with_xmp).segments.length()
  let (out, dropped) = @moonmeta.jpeg_drop_xmp(with_xmp) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(dropped, true)
  @test.assert_eq(inspect_ok(out).has_xmp, false)
  @test.assert_eq(inspect_ok(out).segments.length(), before - 1)
  // EXIF 与隔壁的注释段是"其余字节"，必须原样留下
  @test.assert_eq(decoded(out).gps.length(), 4)
  @test.assert_eq(contains_bytes(out, ascii("moonbit test")), true)
  @test.assert_eq(
    Bytes::from_array(span(out, out.length() - 8, out.length())),
    Bytes::from_array(span(with_xmp, with_xmp.length() - 8, with_xmp.length())),
  )
  let (again, second) = @moonmeta.jpeg_drop_xmp(out) catch {
    e => fail("second drop failed: \{e}")
  }
  @test.assert_eq(second, false)
  @test.assert_eq(again, out)
}

///|
/// APP13 里的 Photoshop 资源包：头是 `Photoshop 3.0\0`，后面跟 8BIM 记录。
/// 这一层不看记录内容——判据只有那个头。
fn iptc_payload() -> Array[Byte] {
  let out = ascii("Photoshop 3.0")
  push(out, [b'\x00'])
  push(out, ascii("8BIM"))
  push(out, [
    b'\x1c', b'\x02', b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', b'\x00',
  ])
  push(out, ascii("Byline=camera owner"))
  out
}

///|
/// 分块扩展 XMP（`http://ns.adobe.com/xmp/extension/`）：Photoshop 写超大 XMP
/// 时用这一段，头后面跟 GUID 与四段长度，最后才是 RDF。
fn xmp_ext_payload() -> Array[Byte] {
  let out = ascii("http://ns.adobe.com/xmp/extension/")
  push(out, [b'\x00'])
  push(out, ascii("0123456789abcdef0123456789abcdef"))
  push(out, [b'\x00', b'\x00', b'\x01', b'\x00'])
  push(out, [b'\x00', b'\x00', b'\x00', b'\x00'])
  push(out, [b'\x00', b'\x00', b'\x00', b'\x04'])
  push(out, ascii("xmp="))
  out
}

///|
/// 在压缩流之前插一段自定义载荷——真实文件里的 IPTC、扩展 XMP 就住在这种位置。
fn with_extra_seg(
  tiff : Bytes?,
  marker : Int,
  payload : Array[Byte],
) -> Bytes raise {
  let base = jpeg_with(tiff)
  let mut cut = base.length()
  for s in inspect_ok(base).segments {
    if s.name() == "SOS" {
      cut = s.offset
    }
  }
  @test.assert_eq(cut < base.length(), true)
  let out : Array[Byte] = []
  push(out, span(base, 0, cut))
  push(out, var_seg(marker, payload))
  push(out, span(base, cut, base.length()))
  Bytes::from_array(out)
}

///|
/// 标识串 + 结尾 NUL + 后续几个字节：`ascii` 打不出 NUL，夹具要自己拼。
fn tag_payload(s : String, rest : Array[Byte]) -> Array[Byte] {
  let out = ascii(s)
  push(out, [b'\x00'])
  push(out, rest)
  out
}

///|
/// 尾巴补一个 NUL：真实标识串都以 NUL 结束，`ascii` 造不出这个字节。
fn with_nul(s : String) -> Array[Byte] {
  tag_payload(s, [])
}

///|
/// APP13 是"整包载体"：认得出、点得名，但不进逐条清单，也不算未解析段——
/// 一个已经说了名字的东西不许同时挂在"我们没看见"那一栏里。
test "APP13 的 Photoshop 包会被点名，但不冒充 EXIF" {
  let file = with_extra_seg(Some(fixture()), 0xed, iptc_payload()) catch {
    e => fail("build failed: \{e}")
  }
  let map = inspect_ok(file)
  @test.assert_eq(map.has_iptc, true)
  @test.assert_eq(map.iptc.length(), 1)
  @test.assert_eq(map.has_xmp, false)
  @test.assert_eq(map.unread.map(s => s.name()), ["COM"])
  @test.assert_eq(decoded(file).gps.length(), 4)
  assert_true(map.describe().contains("另含 IPTC/Photoshop 包 1 段"))
}

///|
test "摘 IPTC 只摘那一段：EXIF、注释、尾巴都原样留着" {
  let file = with_extra_seg(Some(fixture()), 0xed, iptc_payload()) catch {
    e => fail("build failed: \{e}")
  }
  let before = inspect_ok(file).segments.length()
  let (out, dropped) = @moonmeta.jpeg_drop_iptc(file) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(dropped, true)
  @test.assert_eq(inspect_ok(out).has_iptc, false)
  @test.assert_eq(inspect_ok(out).segments.length(), before - 1)
  @test.assert_eq(decoded(out).gps.length(), 4)
  @test.assert_eq(contains_bytes(out, ascii("moonbit test")), true)
  @test.assert_eq(contains_bytes(out, iptc_payload()), false)
  @test.assert_eq(
    Bytes::from_array(span(out, out.length() - 8, out.length())),
    Bytes::from_array(span(file, file.length() - 8, file.length())),
  )
  let (again, second) = @moonmeta.jpeg_drop_iptc(out) catch {
    e => fail("second drop failed: \{e}")
  }
  @test.assert_eq(second, false)
  @test.assert_eq(again, out)
}

///|
/// 头差一个字节就是另一回事：不许按段号整段放行，也不许顺手摘掉。
/// 这条钉的是"按前缀匹配"这个判据本身——改成"按段号放行"它就红。
test "APP13 的头差一个字节：不许摘，但必须点名" {
  let near_miss = with_nul("Photoshop 3.1")
  let file = with_extra_seg(Some(fixture()), 0xed, near_miss) catch {
    e => fail("build failed: \{e}")
  }
  let map = inspect_ok(file)
  @test.assert_eq(map.has_iptc, false)
  @test.assert_eq(map.unread.map(s => s.name()), ["COM", "APP13"])
  let (out, dropped) = @moonmeta.jpeg_drop_iptc(file) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(dropped, false)
  @test.assert_eq(out, file)
}

///|
/// Adobe 的色彩管理包住在 APP14，头在名单上：不出声，但也不在摘除的射程里。
/// 删它会把颜色改掉，而它一条隐私都不装。
test "APP14 的 Adobe 包：安静，而且摘不掉" {
  let adobe_cm = tag_payload("Adobe", [b'\x00', b'\x32', b'\x00'])
  let file = with_extra_seg(Some(fixture()), 0xee, adobe_cm) catch {
    e => fail("build failed: \{e}")
  }
  let map = inspect_ok(file)
  @test.assert_eq(map.has_iptc, false)
  @test.assert_eq(map.unread.map(s => s.name()), ["COM"])
  let (a, d1) = @moonmeta.jpeg_drop_iptc(file) catch {
    e => fail("drop failed: \{e}")
  }
  let (b, d2) = @moonmeta.jpeg_drop_xmp(file) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(d1, false)
  @test.assert_eq(d2, false)
  @test.assert_eq(a, file)
  @test.assert_eq(b, file)
}

///|
/// ICC 描述子是 APP2 的常见住户，公认不装元数据：不出声。
/// 同一段号的 MPF（缩略图链，常自带坐标）必须点名。
test "同一段号两种前缀：ICC 安静，MPF 出声" {
  let icc = tag_payload("ICC_PROFILE", [b'\x01', b'\x01'])
  let quiet = with_extra_seg(None, 0xe2, icc) catch {
    e => fail("build failed: \{e}")
  }
  @test.assert_eq(inspect_ok(quiet).unread.map(s => s.name()), ["COM"])
  let mpf = tag_payload("MPF", [b'\x00', b'\x00'])
  let loud = with_extra_seg(None, 0xe2, mpf) catch {
    e => fail("build failed: \{e}")
  }
  @test.assert_eq(inspect_ok(loud).unread.map(s => s.name()), ["COM", "APP2"])
}

///|
/// APP0 是 JFIF 的家，但规范不禁止它装别的：一段以 `Exif\0\0` 开头的 APP0
/// 不解析、不搬动，可它必须出现在未解析名单里——"段号看起来无害"不是理由。
test "APP0 里藏一份 EXIF 头：不解析，但必须点名" {
  let file = with_extra_seg(None, 0xe0, app1_payload(fixture())) catch {
    e => fail("build failed: \{e}")
  }
  let map = inspect_ok(file)
  @test.assert_eq(map.exif, None)
  @test.assert_eq(map.unread.map(s => s.name()), ["COM", "APP0"])
  let none = @moonmeta.jpeg_decode(file) catch {
    e => fail("decode failed: \{e}")
  }
  @test.assert_eq(none, None)
  // 不解析就不许声称删掉了：drop_iptc / drop_xmp 都不动它
  let (kept, dropped) = @moonmeta.jpeg_drop_xmp(file) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(dropped, false)
  @test.assert_eq(kept, file)
}

///|
/// 分块扩展 XMP 与标准 XMP 是同一种东西的第二种拼法：只认前一种的话，
/// Photoshop 写出来的那一批会静默漏网。
test "分块扩展 XMP 也算 XMP：点名与摘除走同一条路" {
  let file = with_extra_seg(Some(fixture()), 0xe1, xmp_ext_payload()) catch {
    e => fail("build failed: \{e}")
  }
  let map = inspect_ok(file)
  @test.assert_eq(map.has_xmp, true)
  @test.assert_eq(map.xmp.length(), 1)
  @test.assert_eq(map.exif != None, true)
  @test.assert_eq(map.unread.map(s => s.name()), ["COM"])
  let (out, dropped) = @moonmeta.jpeg_drop_xmp(file) catch {
    e => fail("drop failed: \{e}")
  }
  @test.assert_eq(dropped, true)
  @test.assert_eq(inspect_ok(out).has_xmp, false)
  @test.assert_eq(decoded(out).gps.length(), 4)
}

///|
/// 载体覆盖时 IPTC 与 XMP 一起走；不覆盖时必须留着并且报 false。
/// 少一条腿都是假脱敏：CLI 缺省策略就是 privacy，它覆盖载体。
test "carrier 覆盖与否决定 IPTC 走不走" {
  let file = with_extra_seg(Some(fixture()), 0xed, iptc_payload()) catch {
    e => fail("build failed: \{e}")
  }
  let (gone, r) = @moonmeta.jpeg_redact(file, @moonmeta.strict_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(r.dropped_iptc, true)
  @test.assert_eq(inspect_ok(gone).has_iptc, false)
  let (gone2, r2) = @moonmeta.jpeg_redact(file, @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(r2.dropped_iptc, true)
  @test.assert_eq(inspect_ok(gone2).has_iptc, false)
  let (kept, r3) = @moonmeta.jpeg_redact(file, @moonmeta.empty_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(r3.dropped_iptc, false)
  @test.assert_eq(inspect_ok(kept).has_iptc, true)
  @test.assert_eq(kept, file)
}

///|
test "没有 EXIF 的文件也能写进去：新段插在 APP0 之后" {
  let out = @moonmeta.jpeg_replace_exif(jpeg_with(None), fixture()) catch {
    e => fail("replace failed: \{e}")
  }
  match inspect_ok(out).exif {
    Some((s, _)) => @test.assert_eq(s, 30)
    None => fail("expected an EXIF span")
  }
  // 插进去之后，与"一开始就带着 EXIF"的版本完全一致
  @test.assert_eq(out, jpeg_with(Some(fixture())))
  @test.assert_eq(decoded(out), decode_ok(fixture()))
}

///|
test "脱敏只改 APP1 的载荷，压缩流一个字节都不动" {
  let file = jpeg_with(Some(fixture()))
  let (out, report) = @moonmeta.jpeg_redact(file, @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(listing(report.removed), [
    "GPS/GPSLatitudeRef(location)", "GPS/GPSLatitude(location)", "GPS/GPSLongitudeRef(location)",
    "GPS/GPSLongitude(location)",
  ])
  let t = decoded(out)
  @test.assert_eq(t.gps.length(), 0)
  @test.assert_eq(t.make(), Some("NIK"))
  // 压缩流与其后的字节必须与原文逐字节一致
  @test.assert_eq(
    Bytes::from_array(last_bytes(out, 21)),
    Bytes::from_array(span(file, 272, 293)),
  )
}

///|
test "两份 EXIF 段：拒绝，而不是只删第一份" {
  let base = jpeg_with(Some(fixture()))
  let out : Array[Byte] = []
  push(out, span(base, 0, 256))
  push(out, var_seg(0xe1, app1_payload(fixture())))
  push(out, span(base, 256, base.length()))
  try @moonmeta.jpeg_inspect(Bytes::from_array(out)) catch {
    @moonmeta.ExtraMetadata(260) => ()
    e => fail("expected ExtraMetadata(260), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "压缩流之后还藏着 EXIF：同样拒绝" {
  let out : Array[Byte] = []
  push(out, jpeg_with(Some(fixture())).to_array())
  push(out, exif_identifier())
  push(out, fixture().to_array())
  try @moonmeta.jpeg_inspect(Bytes::from_array(out)) catch {
    @moonmeta.ExtraMetadata(293) => ()
    e => fail("expected ExtraMetadata(293), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "段长字段撒谎：报出声明与实有，不做越界读" {
  let broken = jpeg_with(Some(fixture())).to_array()
  broken[4] = b'\xff'
  broken[5] = b'\xfe'
  try @moonmeta.jpeg_inspect(Bytes::from_array(broken)) catch {
    @moonmeta.SegmentTooLarge(2, 65534, 288) => ()
    e => fail("expected SegmentTooLarge(2,65534,288), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "开头不是 SOI：报 NotJpeg" {
  let junk : Array[Byte] = [b'P', b'K', b'\x03', b'\x04']
  try @moonmeta.jpeg_inspect(Bytes::from_array(junk)) catch {
    @moonmeta.NotJpeg(0) => ()
    e => fail("expected NotJpeg(0), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "载荷超过 16 位段长上限：拒绝写入而不是截断" {
  let fat : Array[Byte] = []
  for i = 0; i < 9000; i = i + 1 {
    push(fat, entropy_data())
  }
  let big = Bytes::from_array(fat)
  try @moonmeta.jpeg_replace_exif(jpeg_with(None), big) catch {
    @moonmeta.SegmentOverflow(20, 65535, 90008) => ()
    e => fail("expected SegmentOverflow(20,65535,90008), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
/// 同一条错标成 ASCII 的 10 字节条目，装进真的 APP1 载荷。
fn mislabelled_ascii_block() -> Bytes {
  let v : Array[Byte] = [
    0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00, 0x01, 0x00,
    // 0x011a, ASCII x10 -> 26
     0x1a, 0x01, 0x02, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x1a, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00,
    // 值：第一个字节就是 NUL
     0x00, 0x04, 0x95, 0x0c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  ]
  Bytes::from_array(v)
}

///|
/// 这一条是外来语料抓到的真 bug：`privacy` 谁都没点名，产物却被打坏——
/// 读侧在 NUL 处截断、写侧只补一个 NUL，条目从 10 字节缩成 1 字节，
/// Pillow 随后 `x_resolution[1]` 越界，整个文件"不能被识别为图像"。
test "没点名的 10 字节 ASCII 条目，脱敏后在产物里逐字节还在" {
  let file = jpeg_with(Some(mislabelled_ascii_block()))
  let (out, report) = @moonmeta.jpeg_redact(file, @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(report.removed.length(), 0)
  let payload : Array[Byte] = [
    0x00, 0x04, 0x95, 0x0c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  ]
  @test.assert_eq(contains_bytes(out, payload), true)
  let t = decoded(out)
  @test.assert_eq(t.ifd0.length(), 1)
  match t.ifd0[0].value {
    @moonmeta.Text(s) => @test.assert_eq(s.length(), 10)
    v => fail("expected Text, got \{v}")
  }
}

///|
test "回写幂等：同样的载荷写回去，得到同样的字节" {
  let file = jpeg_with(Some(fixture()))
  let out = @moonmeta.jpeg_replace_exif(file, fixture()) catch {
    e => fail("replace failed: \{e}")
  }
  @test.assert_eq(inspect_ok(out), inspect_ok(file))
  @test.assert_eq(out, file)
}
