// 脱敏层的行为：报告说什么、删了什么、留下什么。
//
// 这一层的价值全在"没删错也没漏删"，所以每个断言都指向一个具体的 tag，
// 而不是"看起来少了几个"。

///|
fn dir_tag(r : @moonmeta.Removed) -> String {
  "\{r.dir.label()}/\{r.name}(\{r.category})"
}

///|
fn listing(rs : Array[@moonmeta.Removed]) -> Array[String] {
  let out : Array[String] = []
  for r in rs {
    out.push(dir_tag(r))
  }
  out
}

///|
fn ascii_entry(tag : Int, s : String) -> @moonmeta.IfdEntry {
  let e : @moonmeta.IfdEntry = { tag, type_code: 2, value: @moonmeta.Text(s), }
  e
}

///|
fn rat(num : Int64, den : Int64) -> @moonmeta.Rational {
  { num, den, }
}

///|
/// 一个大杂烩块：七个类别各点名一次，外加一个本库不认识的厂商 tag。
fn busy(thumb : Bool) -> @moonmeta.TiffBlock {
  let unknown : @moonmeta.IfdEntry = {
    tag: 0x9999,
    type_code: 4,
    value: @moonmeta.Longs([42L]),
  }
  // 整包载体：一整套 XMP 数据包就藏在这一条里
  let xmp_packet : @moonmeta.IfdEntry = {
    tag: 0x02bc,
    type_code: 7,
    value: @moonmeta.Raw(ascii("<x:xmpmeta xmlns:x=\"adobe:xmp/\">")),
  }
  let note : @moonmeta.IfdEntry = {
    tag: 0x927c,
    type_code: 7,
    value: @moonmeta.Raw([b'N', b'i', b'k', b'o', b'\x00']),
  }
  let ver : @moonmeta.IfdEntry = {
    tag: 0x0000,
    type_code: 1,
    value: @moonmeta.Raw([b'\x02', b'\x03', b'\x00', b'\x00']),
  }
  let lat : @moonmeta.IfdEntry = {
    tag: 0x0002,
    type_code: 5,
    value: @moonmeta.Rationals([rat(31L, 1L), rat(13L, 1L), rat(30L, 1L)]),
  }
  {
    little: true,
    ifd0: [
      ascii_entry(0x010f, "NIK"),
      ascii_entry(0x0110, "D850"),
      ascii_entry(0x0131, "CameraApp 1.2"),
      ascii_entry(0x013b, "Zhang San"),
      ascii_entry(0x8298, "(C) 2026 Someone"),
      xmp_packet,
    ],
    exif: [
      ascii_entry(0x9003, "2026:09:24 15:51:00"),
      ascii_entry(0x9011, "+08:00"),
      ascii_entry(0x9286, "in a car, home at 5pm"),
      ascii_entry(0xa431, "BODY-0001"),
      ascii_entry(0xa435, "LENS-0002"),
      note,
      unknown,
    ],
    gps: [ver, lat],
    // 语料里 44 个文件的 Interop 表就是这个样子：一个索引串加版本号，
    // 相机还常带相关图像尺寸。留非空是为了让"第四张表能被重发"这件事
    // 真的被比到，而不是只在空表上成立。
    interop: [
      ascii_entry(0x0001, "R98"),
      { tag: 0x1001, type_code: 3, value: @moonmeta.Shorts([160]), },
    ],
    has_ifd1: thumb,
  }
}

///|
fn busy_bytes() -> Bytes raise {
  @moonmeta.encode_tiff(busy(false)) catch {
    e => fail("busy fixture must encode: \{e}")
  }
}

///|
test "审计只报告，不修改：坐标那一类被整条点名" {
  let t = decode_ok(fixture())
  @test.assert_eq(listing(t.findings(@moonmeta.privacy_policy())), [
    "GPS/GPSLatitudeRef(location)", "GPS/GPSLatitude(location)", "GPS/GPSLongitudeRef(location)",
    "GPS/GPSLongitude(location)",
  ])
  // 报告完，原块一个条目都没少
  @test.assert_eq(t.gps.length(), 4)
}

///|
test "常规策略留时间戳，严格策略连时间一起清" {
  let t = decode_ok(fixture())
  @test.assert_eq(t.findings(@moonmeta.privacy_policy()).length(), 4)
  @test.assert_eq(listing(t.findings(@moonmeta.strict_policy())), [
    "Exif/DateTimeOriginal(timestamps)", "GPS/GPSLatitudeRef(location)", "GPS/GPSLatitude(location)",
    "GPS/GPSLongitudeRef(location)", "GPS/GPSLongitude(location)",
  ])
}

///|
test "七个类别各自点名，不互相串" {
  let d = @moonmeta.Ifd0
  let x = @moonmeta.Exif
  let g = @moonmeta.Gps
  @test.assert_eq(
    @moonmeta.sensitive_category(d, 0x013b),
    Some(@moonmeta.Identity),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0xa420),
    Some(@moonmeta.Identity),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0xa431),
    Some(@moonmeta.DeviceId),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0xa435),
    Some(@moonmeta.DeviceId),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0x927c),
    Some(@moonmeta.MakerNote),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0x9286),
    Some(@moonmeta.Comments),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(x, 0x9011),
    Some(@moonmeta.Timestamps),
  )
  @test.assert_eq(
    @moonmeta.sensitive_category(d, 0x0132),
    Some(@moonmeta.Timestamps),
  )
  // GPS 目录里连版本号都算坐标痕迹
  @test.assert_eq(
    @moonmeta.sensitive_category(g, 0x0000),
    Some(@moonmeta.Location),
  )
  // 整包载体：XMP / Photoshop / IPTC-NAA 三个编号都在 IFD0 下
  for tag in [0x02bc, 0x02bd, 0x8773] {
    @test.assert_eq(
      @moonmeta.sensitive_category(d, tag),
      Some(@moonmeta.Carrier),
    )
  }
  // 换个目录就不是载体：编号不能跨目录顶名
  @test.assert_eq(@moonmeta.sensitive_category(x, 0x02bc), None)
  @test.assert_eq(@moonmeta.Carrier.label(), "carrier")
  @test.assert_eq(@moonmeta.Location.label(), "location")
}

///|
test "版权、机型、厂商名默认不算敏感：删掉权利声明是另一种伤害" {
  for tag in [0x010f, 0x0110, 0x0112, 0x0131, 0x8298] {
    @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Ifd0, tag), None)
  }
  // 表里没有的编号也不许被顺手删掉
  @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Exif, 0x9999), None)
  // 目录参与匹配：0xa420 只在 Exif 下是 ImageUniqueID，0x0132 只在 IFD0 下是 DateTime
  @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Ifd0, 0xa420), None)
  @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Exif, 0x0132), None)
}

///|
test "脱敏后坐标查不到，被点名的字段原样保留" {
  let (out, report) = @moonmeta.redact_tiff(
    fixture(),
    @moonmeta.privacy_policy(),
  ) catch {
    e => fail("redact failed: \{e}")
  }
  let t = decode_ok(out)
  @test.assert_eq(t.has_gps(), false)
  @test.assert_eq(t.gps_lat_lon(), None)
  @test.assert_eq(t.gps.length(), 0)
  @test.assert_eq(report.removed.length(), 4)
  @test.assert_eq(report.dropped_thumbnail, false)
  // 没被点名的照旧
  @test.assert_eq(t.make(), Some("NIK"))
  @test.assert_eq(t.model(), Some("D850"))
  @test.assert_eq(t.orientation(), Some(6))
  @test.assert_eq(t.date_time_original(), Some("2026:09:24 15:51:00"))
}

///|
test "七类各删一次：报告逐条对得上，且严格按 tag 升序" {
  let (out, report) = @moonmeta.redact_tiff(
    busy_bytes(),
    @moonmeta.strict_policy(),
  ) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(listing(report.removed), [
    "IFD0/Artist(identity)", "IFD0/XMP(carrier)", "Exif/DateTimeOriginal(timestamps)",
    "Exif/OffsetTimeOriginal(timestamps)", "Exif/MakerNote(maker_note)", "Exif/UserComment(comments)",
    "Exif/BodySerialNumber(device_id)", "Exif/LensSerialNumber(device_id)", "GPS/GPSVersionID(location)",
    "GPS/GPSLatitude(location)",
  ])
  let t = decode_ok(out)
  @test.assert_eq(t.artist(), None)
  @test.assert_eq(t.copyright(), Some("(C) 2026 Someone"))
  @test.assert_eq(t.software(), Some("CameraApp 1.2"))
  @test.assert_eq(t.ifd0_find(0x013b), None)
  @test.assert_eq(t.exif_find(0xa431), None)
  @test.assert_eq(t.gps.length(), 0)
}

///|
test "本库不认识的厂商 tag 在脱敏后仍然留在文件里" {
  let (out, _) = @moonmeta.redact_tiff(busy_bytes(), @moonmeta.strict_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  let t = decode_ok(out)
  match t.exif_find(0x9999) {
    None => fail("unknown vendor tag 0x9999 was dropped")
    Some(e) => {
      @test.assert_eq(e.type_code, 4)
      match e.value {
        @moonmeta.Longs(vs) => @test.assert_eq(vs, [42L])
        v => fail("expected Longs, got \{v}")
      }
    }
  }
}

///|
/// 与上面那条的差别就是这一类的意义：0x9999 是"我们不认识的编号"，
/// 0x02bc 是"我们认识、但里面装的是另一整套元数据"。后者必须被点名并被删。
test "整包载体在清单里点名，删完字节里查不到" {
  let src = busy_bytes()
  let found = listing(decode_ok(src).findings(@moonmeta.privacy_policy()))
  @test.assert_eq(found.contains("IFD0/XMP(carrier)"), true)
  let (out, report) = @moonmeta.redact_tiff(src, @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(listing(report.removed).contains("IFD0/XMP(carrier)"), true)
  let t = decode_ok(out)
  @test.assert_eq(t.ifd0_find(0x02bc), None)
  @test.assert_eq(contains_bytes(out, ascii("<x:xmpmeta")), false)
  // 权利声明与机型不受牵连
  @test.assert_eq(t.copyright(), Some("(C) 2026 Someone"))
  @test.assert_eq(t.make(), Some("NIK"))
}

///|
test "脱敏是幂等的：第二遍既无可删、字节也不变" {
  let (b1, r1) = @moonmeta.redact_tiff(busy_bytes(), @moonmeta.strict_policy()) catch {
    e => fail("first pass failed: \{e}")
  }
  @test.assert_eq(r1.removed.length() > 0, true)
  let (b2, r2) = @moonmeta.redact_tiff(b1, @moonmeta.strict_policy()) catch {
    e => fail("second pass failed: \{e}")
  }
  @test.assert_eq(listing(r2.removed), [])
  @test.assert_eq(b2, b1)
}

///|
test "空策略是恒等：什么都不删、报告为空" {
  let src = busy_bytes()
  let before = decode_ok(src)
  let (after_bytes, report) = @moonmeta.redact_tiff(
    src,
    @moonmeta.empty_policy(),
  ) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(listing(report.removed), [])
  let after = decode_ok(after_bytes)
  // 每一本目录都逐条目相等
  @test.assert_eq(after.ifd0, before.ifd0)
  @test.assert_eq(after.exif, before.exif)
  @test.assert_eq(after.gps, before.gps)
  @test.assert_eq(after.little, before.little)
}

///|
test "小端块脱敏后仍是小端：字节序不是被顺手改掉的" {
  @test.assert_eq(decode_ok(busy_bytes()).little, true)
  let (out, _) = @moonmeta.redact_tiff(busy_bytes(), @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(out[0], b'I')
  @test.assert_eq(out[1], b'I')
  let (big, _) = @moonmeta.redact_tiff(fixture(), @moonmeta.privacy_policy()) catch {
    e => fail("redact failed: \{e}")
  }
  @test.assert_eq(big[0], b'M')
  @test.assert_eq(big[1], b'M')
}

///|
test "缩略图链一定会被丢掉，所以一定要报告" {
  let (kept, report) = busy(true).redact(@moonmeta.privacy_policy())
  @test.assert_eq(report.dropped_thumbnail, true)
  @test.assert_eq(kept.has_ifd1, false)
  // 报告里说丢了，就得真没有：不能只删主目录坐标、留着带坐标的缩略图
  let again = busy(true)
  let (_, r2) = again.redact(@moonmeta.empty_policy())
  @test.assert_eq(r2.dropped_thumbnail, true)
}

///|
test "非 ASCII 文本在回写时明确报错，不会被换成问号" {
  let dirty : @moonmeta.TiffBlock = {
    little: true,
    ifd0: [ascii_entry(0x013b, "张三")],
    exif: [],
    gps: [],
    interop: [],
    has_ifd1: false,
  }
  try @moonmeta.encode_tiff(dirty) catch {
    @moonmeta.UnencodableText(0x013b, 24352) => ()
    e => fail("expected UnencodableText(0x13b,24352), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "tag 名表：核过的打名字，没核过的打编号" {
  @test.assert_eq(@moonmeta.tag_name(@moonmeta.Ifd0, 0x010f), "Make")
  @test.assert_eq(@moonmeta.tag_name(@moonmeta.Exif, 0x9286), "UserComment")
  @test.assert_eq(@moonmeta.tag_name(@moonmeta.Gps, 0x0002), "GPSLatitude")
  // 表里没有的编号绝不猜名字
  @test.assert_eq(@moonmeta.tag_name(@moonmeta.Exif, 0xea1c), "0xea1c")
  // 同一编号在不同目录里是两回事
  @test.assert_eq(@moonmeta.tag_name(@moonmeta.Exif, 0x0132), "0x0132")
}
