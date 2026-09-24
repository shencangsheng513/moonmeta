// 容器分派层的行为测试。
//
// 这一层的承诺只有一句："同一个策略，装在哪个容器里都得到同一个结果"。
// 所以大部分测试都是把同一份 TIFF 分别装进 JPEG、PNG，再三条一起比。

///|
/// 同一份元数据的三种载体。
fn all_three() -> Array[(String, Bytes)] {
  [
    ("jpeg", jpeg_with(Some(fixture()))),
    ("png", png_with(Some(fixture()))),
    ("tiff", fixture()),
  ]
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
fn strip_any_ok(data : Bytes) -> (Bytes, Bool) raise {
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
    @test.assert_eq(had, true)
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
    @test.assert_eq(had1, true)
    let (twice, had2) = strip_any_ok(once)
    @test.assert_eq(had2, false)
    @test.assert_eq(twice, once)
  }
}

///|
test "摘完元数据的文件仍是合法容器：段表块表都还能走查" {
  let (jpeg, _) = strip_any_ok(jpeg_with(Some(fixture())))
  @test.assert_eq(inspect_ok(jpeg).exif, None)
  @test.assert_eq(inspect_ok(jpeg).segments.length(), 4)
  let (png, _) = strip_any_ok(png_with(Some(fixture())))
  @test.assert_eq(png_inspect_ok(png).exif, None)
  @test.assert_eq(png_inspect_ok(png).chunks.length(), 4)
  // 压缩流和图像数据都还在原位
  @test.assert_eq(
    Bytes::from_array(last_bytes(png, 28)),
    Bytes::from_array(png_span(png_with(Some(fixture())), 313, 341)),
  )
}

///|
test "describe_container 每个容器报自己的结构" {
  for e in all_three() {
    let (name, data) = e
    let line = @moonmeta.describe_container(data) catch {
      err => fail("describe failed: \{err}")
    }
    let prefix = if name == "jpeg" {
      "JPEG SOI@0"
    } else if name == "png" {
      "PNG IHDR@8"
    } else {
      "TIFF 裸块 226B, 3 条 IFD0 条目"
    }
    @test.assert_eq(line.has_prefix(prefix), true)
  }
}
