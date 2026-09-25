// 容器分派层的行为测试。
//
// 这一层的承诺只有一句："同一个策略，装在哪个容器里都得到同一个结果"。
// 所以大部分测试都是把同一份 TIFF 分别装进 JPEG、PNG，再三条一起比。
//
// 裸 TIFF 这一条用的是编码器自己产出的布局：写回要先过 `check_tiff_rewrite`
// 那道判据，而手算的 `fixture()` 是相机式的外来布局（值区夹在目录之间），
// 重建出来的字节数对不上。它仍然直接出现在解码与编码那两组测试里——
// 判据拒绝的是"改写一个我们没能完整建模的文件"，不是"读不懂它"。

///|
/// 同一份元数据的三种载体。
fn all_three() -> Array[(String, Bytes)] raise {
  [
    ("jpeg", jpeg_with(Some(fixture()))),
    ("png", png_with(Some(fixture()))),
    ("tiff", canonical_tiff()),
  ]
}

///|
/// 把 `fixture()` 读进来再原样编码：得到一份"除了元数据没有别的字节"、
/// 且能被编码器逐字节复现的裸 TIFF。
fn canonical_tiff() -> Bytes raise {
  @moonmeta.encode_tiff(decode_ok(fixture()))
}

///|
fn kind_of(data : Bytes) -> String {
  match @moonmeta.sniff(data) {
    None => "none"
    Some(k) => k.to_string()
  }
}

///|
fn decode_any_ok(data : Bytes) -> (@moonmeta.Kind, @moonmeta.TiffBlock?) raise {
  @moonmeta.decode_any(data) catch {
    e => fail("decode_any failed: \{e}")
  }
}

///|
fn redact_any_ok(
  data : Bytes,
  p : @moonmeta.Policy,
) -> (Bytes, @moonmeta.Redaction) raise {
  @moonmeta.redact_any(data, p) catch {
    e => fail("redact_any failed: \{e}")
  }
}

///|
fn strip_any_ok(data : Bytes) -> (Bytes, @moonmeta.Strip) raise {
  @moonmeta.strip_any(data) catch {
    e => fail("strip_any failed: \{e}")
  }
}

///|
test "认魔数：三种容器各自归位" {
  for e in all_three() {
    let (name, data) = e
    @test.assert_eq(kind_of(data), name)
  }
}

///|
test "认不出来就说不知道，不猜一个格式" {
  let junk : Array[Byte] = [b'%', b'P', b'D', b'F', b'-', b'1', b'.', b'4']
  @test.assert_eq(@moonmeta.sniff(Bytes::from_array(junk)), None)
  @test.assert_eq(@moonmeta.sniff(Bytes::from_array([])), None)
  // 只有一个字节也够看出不是 JPEG，但不足以判成任何容器
  @test.assert_eq(@moonmeta.sniff(Bytes::from_array([b'\xff'])), None)
  // PNG 的前 7 个字节还不构成签名
  let short = png_with(Some(fixture()))
  @test.assert_eq(@moonmeta.sniff(Bytes::from_array(span(short, 0, 7))), None)
}

///|
test "截断到只剩魔数也照样归位：判定不依赖读完整份文件" {
  let jpeg_head = span(jpeg_with(Some(fixture())), 0, 2)
  @test.assert_eq(
    @moonmeta.sniff(Bytes::from_array(jpeg_head)),
    Some(@moonmeta.Jpeg),
  )
  let tiff_head = span(fixture(), 0, 4)
  @test.assert_eq(
    @moonmeta.sniff(Bytes::from_array(tiff_head)),
    Some(@moonmeta.Tiff),
  )
}

///|
test "decode_any 顺带报告容器，元数据内容与裸块一致" {
  for e in all_three() {
    let (name, data) = e
    let (kind, block) = decode_any_ok(data)
    @test.assert_eq(kind.to_string(), name)
    match block {
      None => fail("\{name}: expected an EXIF block")
      Some(t) => {
        @test.assert_eq(t, decode_ok(fixture()))
        @test.assert_eq(t.gps.length(), 4)
      }
    }
  }
}

///|
test "认不出容器时 decode_any 报 UnknownFormat" {
  let junk = ascii("%PDF-1.4")
  try @moonmeta.decode_any(Bytes::from_array(junk)) catch {
    @moonmeta.UnknownFormat(0) => ()
    e => fail("expected UnknownFormat(0), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "同一个策略装在三个容器里：删掉的条目一字不差，留下的也一字不差" {
  let wants : Array[String] = [
    "GPS/GPSLatitudeRef(location)", "GPS/GPSLatitude(location)", "GPS/GPSLongitudeRef(location)",
    "GPS/GPSLongitude(location)",
  ]
  for e in all_three() {
    let (_, data) = e
    let (out, report) = redact_any_ok(data, @moonmeta.privacy_policy())
    @test.assert_eq(listing(report.removed), wants)
    let (_, block) = decode_any_ok(out)
    match block {
      None => fail("expected a slimmed EXIF, got nothing")
      Some(t) => {
        @test.assert_eq(t.gps.length(), 0)
        @test.assert_eq(t.make(), Some("NIK"))
        @test.assert_eq(t.date_time_original(), Some("2026:09:24 15:51:00"))
      }
    }
  }
}

///|
test "严格策略在三个容器里同样多删一条时间戳" {
  for e in all_three() {
    let (_, data) = e
    let (_, report) = redact_any_ok(data, @moonmeta.strict_policy())
    let got = listing(report.removed)
    @test.assert_eq(got.length(), 5)
    @test.assert_eq(got[0], "Exif/DateTimeOriginal(timestamps)")
  }
}

///|
test "strip 之后再也读不出坐标" {
  for e in all_three() {
    let (_, data) = e
    let (out, had) = strip_any_ok(data)
    @test.assert_eq(had.had_exif, true)
    let (_, block) = decode_any_ok(out)
    match block {
      None => () // JPEG/PNG：整段元数据已经不在了
      Some(t) => {
        // 裸 TIFF 只能留一个合法空壳，这里必须每一类都是空的
        @test.assert_eq(t.ifd0.length(), 0)
        @test.assert_eq(t.exif.length(), 0)
        @test.assert_eq(t.gps.length(), 0)
      }
    }
  }
}

///|
test "第二次 strip 必须承认无事可做，而不是再报一次成功" {
  for e in all_three() {
    let (_, data) = e
    let (once, had1) = strip_any_ok(data)
    @test.assert_eq(had1.had_exif, true)
    let (twice, had2) = strip_any_ok(once)
    @test.assert_eq(had2.had_exif, false)
    @test.assert_eq(twice, once)
  }
}

///|
/// 语料里 99 张真实照片有 34 张带 XMP 包，其中 20 张的包里有拍摄时间、机型、
/// 署名或序列号。下面这四条钉的就是那批文件暴露出来的问题。
test "redact 连容器里的 XMP 包一起带走，两个容器都一样" {
  let (jpeg, r1) = redact_any_ok(
    append_xmp_app1(jpeg_with(Some(fixture()))),
    @moonmeta.privacy_policy(),
  )
  @test.assert_eq(r1.dropped_xmp, true)
  @test.assert_eq(contains_ascii(jpeg, "http://ns.adobe.com/xap/1.0/"), false)
  let (png, r2) = redact_any_ok(
    png_with(Some(fixture())),
    @moonmeta.privacy_policy(),
  )
  @test.assert_eq(r2.dropped_xmp, true)
  @test.assert_eq(contains_ascii(png, "XML:com.adobe.xmp"), false)
}

///|
test "再脱一遍要承认 XMP 本来就没有：报告里那个 Bool 不能只写条数" {
  let (once, r1) = redact_any_ok(
    png_with(Some(fixture())),
    @moonmeta.strict_policy(),
  )
  @test.assert_eq(r1.dropped_xmp, true)
  let (twice, r2) = redact_any_ok(once, @moonmeta.strict_policy())
  @test.assert_eq(r2.dropped_xmp, false)
  @test.assert_eq(twice, once)
}

///|
test "策略不覆盖载体时，XMP 一个字节都不动" {
  let file = append_xmp_app1(jpeg_with(Some(fixture())))
  let (out, report) = redact_any_ok(file, @moonmeta.empty_policy())
  @test.assert_eq(report.dropped_xmp, false)
  @test.assert_eq(report.removed.length(), 0)
  @test.assert_eq(contains_ascii(out, "http://ns.adobe.com/xap/1.0/"), true)
  @test.assert_eq(out, file)
}

///|
/// 扩展协议的第二段与第一段共用同一个标识前缀，所以它天然也在识别名单里。
/// 一次脱敏必须把所有包都摘掉：只摘第一份，剩下那半包照样读得出拍摄时间，
/// 而报告上写的却是"已整包摘除"。
test "两包 XMP 一起摘，不许只摘第一包" {
  let base = append_xmp_app1(jpeg_with(Some(fixture())))
  let exif_end = match inspect_ok(base).exif {
    Some((_, e)) => e
    None => fail("fixture has no EXIF")
  }
  let second = xmp_identifier()
  push(second, ascii("<x:xmpmeta>the-second-packet</x:xmpmeta>"))
  let out : Array[Byte] = []
  push(out, span(base, 0, exif_end))
  push(out, var_seg(0xe1, second))
  push(out, span(base, exif_end, base.length()))
  let two = Bytes::from_array(out)
  @test.assert_eq(inspect_ok(two).xmp.length(), 2)
  let (cleaned, report) = redact_any_ok(two, @moonmeta.strict_policy())
  @test.assert_eq(report.dropped_xmp, true)
  @test.assert_eq(inspect_ok(cleaned).has_xmp, false)
  @test.assert_eq(inspect_ok(cleaned).xmp.length(), 0)
  @test.assert_eq(
    contains_ascii(cleaned, "http://ns.adobe.com/xap/1.0/"),
    false,
  )
  @test.assert_eq(contains_ascii(cleaned, "the-second-packet"), false)
}

///|
/// 这是最险的一种：文件的元数据只有 XMP，没有 EXIF。
/// 逐条清单天然是空的，工具若只照着清单说话，就会报"无可删"然后把整包留着。
test "没有 EXIF 只有 XMP 的文件照样要清，且不许谎称无事可做" {
  let out : Array[Byte] = [b'\xff', b'\xd8']
  push(out, var_seg(0xe1, xmp_identifier()))
  push(out, var_seg(0xda, sos_payload()))
  push(out, entropy_data())
  push(out, [b'\xff', b'\xd9'])
  let file = Bytes::from_array(out)
  let (_, block) = decode_any_ok(file)
  @test.assert_eq(block, None)
  let (cleaned, report) = redact_any_ok(file, @moonmeta.privacy_policy())
  @test.assert_eq(report.removed.length(), 0)
  @test.assert_eq(report.dropped_xmp, true)
  @test.assert_eq(
    contains_ascii(cleaned, "http://ns.adobe.com/xap/1.0/"),
    false,
  )
  // 剩下的仍然是一个能走查的合法 JPEG
  @test.assert_eq(inspect_ok(cleaned).has_xmp, false)
}

///|
/// 在字节里找一个 ASCII 串。报告说"整包摘除"，就得能在字节上验它真的没了。
fn contains_ascii(data : Bytes, text : String) -> Bool {
  let all = data.to_array()
  let needle = png_ascii(text)
  let n = all.length()
  let m = needle.length()
  if m == 0 || m > n {
    return false
  }
  let mut i = 0
  while i + m <= n {
    let mut j = 0
    while j < m && all[i + j] == needle[j] {
      j = j + 1
    }
    if j == m {
      return true
    }
    i = i + 1
  }
  false
}

///|
test "摘完元数据的文件仍是合法容器：段表块表都还能走查" {
  let (jpeg, jpeg_had) = strip_any_ok(jpeg_with(Some(fixture())))
  @test.assert_eq(inspect_ok(jpeg).exif, None)
  @test.assert_eq(inspect_ok(jpeg).segments.length(), 4)
  @test.assert_eq(jpeg_had.dropped_xmp, false)
  let (png, png_had) = strip_any_ok(png_with(Some(fixture())))
  @test.assert_eq(png_inspect_ok(png).exif, None)
  // 原来五块（IHDR/eXIf/tEXt/IDAT/IEND），现在连 XMP 文本块一起没了。
  @test.assert_eq(png_inspect_ok(png).chunks.length(), 3)
  @test.assert_eq(png_had.dropped_xmp, true)
  @test.assert_eq(contains_ascii(png, "XML:com.adobe.xmp"), false)
  // 压缩流和图像数据都还在原位
  @test.assert_eq(
    Bytes::from_array(last_bytes(png, 28)),
    Bytes::from_array(png_span(png_with(Some(fixture())), 313, 341)),
  )
}

///|
fn describe_of(data : Bytes) -> String raise {
  @moonmeta.describe_container(data) catch {
    e => fail("describe failed: \{e}")
  }
}

///|
test "describe_container 每个容器报自己的结构" {
  let jpeg = describe_of(jpeg_with(Some(fixture())))
  @test.assert_eq(jpeg.has_prefix("JPEG SOI@0"), true)
  let png = describe_of(png_with(Some(fixture())))
  @test.assert_eq(png.has_prefix("PNG IHDR@8"), true)
  // 读侧不受判据约束：外来布局照样报得出真实字节数。
  let line = describe_of(fixture())
  @test.assert_eq(line, "TIFF 裸块 226B, 3 条 IFD0 条目")
}

///|
/// 拒绝改写裸 TIFF 的那道判据，用真实语料（相机把 IFD0 放在图像数据之后）
/// 说话才有分量，这里用字节把它造出来：头 8 字节 + `pad` 字节假像素 + IFD 结构。
/// 块里的值全部内联，所以整体后移不会让任何偏移失效——这份文件是合法的，
/// 元数据也照样读得出来，它只是"除了元数据还有别的字节"。
fn tiff_with_image_data(pad : Int) -> Bytes raise {
  let t = @moonmeta.encode_tiff({
    little: false,
    ifd0: [{ tag: 256, type_code: 3, value: @moonmeta.Shorts([1200]), }],
    exif: [],
    gps: [],
    interop: [],
    has_ifd1: false,
  })
  let out : Array[Byte] = [b'M', b'M', b'\x00', b'*']
  for b in u32_be(8 + pad) {
    out.push(b)
  }
  for _ in 0..<pad {
    out.push(b'\x20')
  }
  for b in span(t, 8, t.length()) {
    out.push(b)
  }
  Bytes::from_array(out)
}

///|
fn u32_be(v : Int) -> Array[Byte] {
  [
    ((v >> 24) & 0xff).to_byte(),
    ((v >> 16) & 0xff).to_byte(),
    ((v >> 8) & 0xff).to_byte(),
    (v & 0xff).to_byte(),
  ]
}

///|
/// 空壳块（没有任何条目）加上假像素数据：`strip` 走到"本来就没有"那一支，
/// 应当在判据之前就原样返回。
fn empty_tiff_with_image_data(pad : Int) -> Bytes raise {
  let t = @moonmeta.encode_tiff({
    little: false,
    ifd0: [],
    exif: [],
    gps: [],
    interop: [],
    has_ifd1: false,
  })
  let out : Array[Byte] = [b'M', b'M', b'\x00', b'*']
  for b in u32_be(8 + pad) {
    out.push(b)
  }
  for _ in 0..<pad {
    out.push(b'\x20')
  }
  for b in span(t, 8, t.length()) {
    out.push(b)
  }
  Bytes::from_array(out)
}

///|
fn redact_err(data : Bytes) -> String {
  try @moonmeta.redact_any(data, @moonmeta.privacy_policy()) catch {
    e => e.to_string()
  } noraise {
    _ => "没有报错"
  }
}

///|
fn strip_err(data : Bytes) -> String {
  try @moonmeta.strip_any(data) catch {
    e => e.to_string()
  } noraise {
    _ => "没有报错"
  }
}

///|
/// 这条钉的是整个工具最贵的一次失败：真实语料里 8 个 TIFF 脱敏后 Pillow
/// 报 `decoder error -2`，而我们的 `read` 读自己的产物还一切正常。
test "像素数据在 IFD 之前的裸 TIFF：能读，能审，但拒绝改写" {
  let data = tiff_with_image_data(16)
  let (kind, block) = decode_any_ok(data)
  @test.assert_eq(kind.to_string(), "tiff")
  @test.assert_eq(block.unwrap().ifd0.length(), 1)
  // 8 + 16 = 24 是 IFD0 的偏移，42 是文件长度，26 是模型能重建出的长度。
  let msg = redact_err(data)
  @test.assert_eq(msg.contains("offset 24"), true)
  @test.assert_eq(msg.contains("42"), true)
  @test.assert_eq(msg.contains("26"), true)
  @test.assert_eq(msg, strip_err(data))
}

///|
/// 判据不看"像不像有像素"，只看字节能否复现，所以相机式布局即便纯元数据
/// 也一并拒绝：宁可少做，也不产出一个打不开的图像。
test "外来布局的裸 TIFF 同样拒绝改写，并把两个长度都说出来" {
  let msg = redact_err(fixture())
  @test.assert_eq(msg.contains("offset 8"), true)
  @test.assert_eq(msg.contains("226"), true)
  @test.assert_eq(msg.contains("没有报错"), false)
}

///|
/// 反向对照：判据不是"裸 TIFF 一律不写"。编码器自己的布局要放行，
/// 而且产物再过一遍判据还是过——删到底就是幂等。
test "可复现的裸 TIFF 照常改写，第二次改写字节不变" {
  let data = canonical_tiff()
  @test.assert_eq(redact_err(data), "没有报错")
  let (out, report) = redact_any_ok(data, @moonmeta.privacy_policy())
  @test.assert_eq(listing(report.removed).length(), 4)
  let (again, _) = redact_any_ok(out, @moonmeta.privacy_policy())
  @test.assert_eq(again, out)
}

///|
/// 没东西可删时不必惊动判据：这条分支的语义是"这个文件本来就没有 EXIF"，
/// 报"拒绝改写"是撒谎。
test "空元数据 + 像素数据的 TIFF：strip 原样返回并说无事可做" {
  let data = empty_tiff_with_image_data(20)
  @test.assert_eq(strip_err(data), "没有报错")
  let (out, had) = strip_any_ok(data)
  @test.assert_eq(had.had_exif, false)
  @test.assert_eq(had.dropped_xmp, false)
  @test.assert_eq(out, data)
}
