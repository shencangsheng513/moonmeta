///|
/// 一个 226 字节的大端 TIFF 块，按 EXIF 规范逐字节手算。
///
/// 故意让 GPS 子目录挂在 Exif 子目录下（真实相机就这么干），
/// 这样指针剥离与两处查找的代码路径都被覆盖。
fn fixture() -> Bytes {
  let v : Array[Byte] = [
    // 0: TIFF 头 "MM" + 42 + IFD0 偏移 8
    0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x08,
    // 8: IFD0 有 4 条
     0x00, 0x04,
    // 10: 0x010F Make, ASCII x4, 内联 "NIK\0"
     0x01, 0x0f, 0x00, 0x02, 0x00, 0x00, 0x00, 0x04, 0x4e, 0x49, 0x4b, 0x00,
    // 22: 0x0110 Model, ASCII x12, 外部偏移 0x3e
     0x01, 0x10, 0x00, 0x02, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x3e,
    // 34: 0x0112 Orientation, SHORT x1, 内联 6
     0x01, 0x12, 0x00, 0x03, 0x00, 0x00, 0x00, 0x01, 0x00, 0x06, 0x00, 0x00,
    // 46: 0x8769 Exif 子目录指针 -> 0x4a
     0x87, 0x69, 0x00, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x4a,
    // 58: IFD0 的下一目录 = 无
     0x00, 0x00, 0x00, 0x00,
    // 62: Model 的值 "D850" + NUL 填充
     0x44, 0x38, 0x35, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    // 74: Exif 子目录有 2 条
     0x00, 0x02,
    // 76: 0x9003 DateTimeOriginal, ASCII x20, 外部偏移 0x68
     0x90, 0x03, 0x00, 0x02, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x68,
    // 88: 0x8825 GPS 子目录指针 -> 0x7c
     0x88, 0x25, 0x00, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x7c,
    // 100: Exif 子目录的下一目录 = 无
     0x00, 0x00, 0x00, 0x00,
    // 104: "2026:09:24 15:51:00\0"
     0x32, 0x30, 0x32, 0x36, 0x3a, 0x30, 0x39, 0x3a, 0x32, 0x34, 0x20, 0x31, 0x35,
    0x3a, 0x35, 0x31, 0x3a, 0x30, 0x30, 0x00,
    // 124: GPS 子目录有 4 条
     0x00, 0x04,
    // 126: 0x0001 GPSLatRef, ASCII x2, 内联 "N\0"
     0x00, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x4e, 0x00, 0x00, 0x00,
    // 138: 0x0002 GPSLatitude, RATIONAL x3 -> 0xb2
     0x00, 0x02, 0x00, 0x05, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0xb2,
    // 150: 0x0003 GPSLonRef, ASCII x2, 内联 "E\0"
     0x00, 0x03, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02, 0x45, 0x00, 0x00, 0x00,
    // 162: 0x0004 GPSLongitude, RATIONAL x3 -> 0xca
     0x00, 0x04, 0x00, 0x05, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0xca,
    // 174: GPS 子目录的下一目录 = 无
     0x00, 0x00, 0x00, 0x00,
    // 178: 纬度 31°13'30"
     0x00, 0x00, 0x00, 0x1f, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0d, 0x00,
    0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x1e, 0x00, 0x00, 0x00, 0x01,
    // 202: 经度 121°8'42"
     0x00, 0x00, 0x00, 0x79, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x08, 0x00,
    0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x01,
  ]
  Bytes::from_array(v)
}

///|
fn near(a : Double, b : Double) -> Bool {
  let d = a - b
  let mag = if d < 0.0 { 0.0 - d } else { d }
  mag < 0.000000001
}

///|
fn decode_ok(data : Bytes) -> @moonmeta.TiffBlock raise {
  @moonmeta.decode_tiff(data) catch {
    e => fail("unexpected error: \{e}")
  }
}

///|
test "手算的大端块能逐字段读出来" {
  let t = decode_ok(fixture())
  @test.assert_eq(t.little, false)
  @test.assert_eq(t.make(), Some("NIK"))
  @test.assert_eq(t.model(), Some("D850"))
  @test.assert_eq(t.orientation(), Some(6))
  @test.assert_eq(t.date_time_original(), Some("2026:09:24 15:51:00"))
  @test.assert_eq(t.has_gps(), true)
  @test.assert_eq(t.has_ifd1, false)
}

///|
test "子目录指针被当作结构消费掉，不留进 IR" {
  let t = decode_ok(fixture())
  // IFD0 原本 4 条，其中 0x8769 是指针；Exif 2 条，其中 0x8825 是指针。
  @test.assert_eq(t.ifd0.length(), 3)
  @test.assert_eq(t.exif.length(), 1)
  @test.assert_eq(t.gps.length(), 4)
  // 指针 tag 在任何目录里都查不到
  @test.assert_eq(t.get(@moonmeta.tag_exif_ifd), None)
  @test.assert_eq(t.get(@moonmeta.tag_gps_ifd), None)
}

///|
test "GPS 度分秒按参考系折算成十进制度" {
  let t = decode_ok(fixture())
  match t.gps_lat_lon() {
    Some((lat, lon)) => {
      if !near(lat, 31.225) {
        fail("lat = \{lat}, want 31.225")
      }
      if !near(lon, 121.145) {
        fail("lon = \{lon}, want 121.145")
      }
    }
    None => fail("expected a latitude/longitude pair")
  }
}

///|
test "小端块同样读得对" {
  // "II" + 42 + IFD0@8，一条 Orientation = 6
  let v : Array[Byte] = [
    0x49, 0x49, 0x2a, 0x00, 0x08, 0x00, 0x00, 0x00, 0x01, 0x00, 0x12, 0x01, 0x03,
    0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  ]
  let t = decode_ok(Bytes::from_array(v))
  @test.assert_eq(t.little, true)
  @test.assert_eq(t.orientation(), Some(6))
}

///|
test "encode 之后再 decode，IR 一模一样" {
  let t = decode_ok(fixture())
  let bytes = @moonmeta.encode_tiff(t) catch {
    e => fail("encode failed: \{e}")
  }
  let t2 = decode_ok(bytes)
  @test.assert_eq(t2, t)
}

///|
test "encode 重算偏移：GPS 指针从 Exif 目录上移到 IFD0" {
  let t = decode_ok(fixture())
  let t2 = decode_ok(
    @moonmeta.encode_tiff(t) catch {
      e => fail("encode failed: \{e}")
    },
  )
  // 数据一字不差，只是布局规范化了
  @test.assert_eq(t2.gps.length(), 4)
  @test.assert_eq(t2.exif.length(), 1)
  @test.assert_eq(t2.ifd0.length(), 3)
}

///|
test "编码是不动点：再读再写得到完全相同的字节" {
  let t = decode_ok(fixture())
  let b1 = @moonmeta.encode_tiff(t) catch {
    e => fail("first encode failed: \{e}")
  }
  let b2 = @moonmeta.encode_tiff(decode_ok(b1)) catch {
    e => fail("second encode failed: \{e}")
  }
  @test.assert_eq(b2, b1)
}

///|
test "既不是 II 也不是 MM：报出偏移" {
  let v : Array[Byte] = [0x00, 0x00, 0x00, 0x2a, 0x08, 0x00, 0x00, 0x00]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.BadByteOrder(0) => ()
    e => fail("expected BadByteOrder(0), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "魔数不是 42：报 BadTiffHeader" {
  let v : Array[Byte] = [0x4d, 0x4d, 0x00, 0x2b, 0x08, 0x00, 0x00, 0x00]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.BadTiffHeader(2) => ()
    e => fail("expected BadTiffHeader(2), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "短于 8 字节：报出需要多少、实有多少" {
  let v : Array[Byte] = [0x4d, 0x4d, 0x00, 0x2a]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.TooShort(8, 4) => ()
    e => fail("expected TooShort(8,4), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "IFD0 偏移指向块外：报 IfdOffsetOutOfRange" {
  let v : Array[Byte] = [0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0xff, 0xff]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.IfdOffsetOutOfRange(65535L) => ()
    e => fail("expected IfdOffsetOutOfRange(65535), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "条目数量撒谎：报 EntryTooLarge 而不是越界读" {
  // IFD0@8 声明 0xffff 条（要 786420 字节），计数域之后只剩 6 字节
  let v : Array[Byte] = [
    0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x08, 0xff, 0xff, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00,
  ]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.EntryTooLarge(0, 786420, 6) => ()
    e => fail("expected EntryTooLarge(0,786420,6), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "值偏移指向块外：报出是哪个 tag" {
  // 一条 Model 条目，count=20 但值偏移指着块外
  let v : Array[Byte] = [
    0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x08, 0x00, 0x01, 0x01, 0x10, 0x00,
    0x02, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
  ]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.ValueOffsetOutOfRange(0x0110, 256L) => ()
    e => fail("expected ValueOffsetOutOfRange(0x110,256), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}

///|
test "浮点类型码：本版本明确拒绝，而不是读出垃圾" {
  let v : Array[Byte] = [
    0x4d, 0x4d, 0x00, 0x2a, 0x00, 0x00, 0x00, 0x08, 0x00, 0x01, 0x88, 0x26, 0x00,
    0x0c, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  ]
  try @moonmeta.decode_tiff(Bytes::from_array(v)) catch {
    @moonmeta.UnsupportedType(0x8826, 12) => ()
    e => fail("expected UnsupportedType(0x8826,12), got \{e}")
  } noraise {
    _ => fail("expected a rejection")
  }
}
