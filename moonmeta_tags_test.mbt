// 名字表的行为。
//
// `audit` 和 `read` 打印的每一行都从这里取词。名字打错或漏掉，
// 用户看到的就是"某个不认识的编号被删了"——这份报告也就没人敢照着签字。
// 所以这里把 README 承诺的 65 个规范名逐个钉死。

///|
fn check(dir : @moonmeta.Dir, id : Int, want : String) -> Unit raise {
  @test.assert_eq(@moonmeta.tag_name(dir, id), want)
}

///|
/// 本包有规范名的全部编号：IFD0 15 个、Exif 14 个、GPS 32 个、Interop 4 个。
test "规范名表：README 报出的编号与名字逐条对得上" {
  let ifd0 : Array[(Int, String)] = [
    (0x010f, "Make"),
    (0x0110, "Model"),
    (0x0112, "Orientation"),
    (0x0131, "Software"),
    (0x0132, "DateTime"),
    (0x013b, "Artist"),
    (0x0201, "JPEGInterchangeFormat"),
    (0x0202, "JPEGInterchangeFormatLength"),
    (0x02bc, "XMP"),
    (0x02bd, "PhotoshopSettings"),
    (0x83bb, "IptcNaa"),
    (0x8773, "InterColorProfile"),
    (0x8298, "Copyright"),
    (0x8769, "ExifOffset"),
    (0x8825, "GPSInfo"),
  ]
  let exif : Array[(Int, String)] = [
    (0x8825, "GPSInfo"),
    (0x9003, "DateTimeOriginal"),
    (0x9004, "DateTimeDigitized"),
    (0x9010, "OffsetTime"),
    (0x9011, "OffsetTimeOriginal"),
    (0x9012, "OffsetTimeDigitized"),
    (0x927c, "MakerNote"),
    (0x9286, "UserComment"),
    (0x9290, "SubsecTime"),
    (0x9291, "SubsecTimeOriginal"),
    (0xa005, "InteropOffset"),
    (0xa420, "ImageUniqueID"),
    (0xa431, "BodySerialNumber"),
    (0xa435, "LensSerialNumber"),
  ]
  let gps : Array[(Int, String)] = [
    (0x0000, "GPSVersionID"),
    (0x0001, "GPSLatitudeRef"),
    (0x0002, "GPSLatitude"),
    (0x0003, "GPSLongitudeRef"),
    (0x0004, "GPSLongitude"),
    (0x0005, "GPSAltitudeRef"),
    (0x0006, "GPSAltitude"),
    (0x0007, "GPSTimeStamp"),
    (0x0008, "GPSSatellites"),
    (0x0009, "GPSStatus"),
    (0x000a, "GPSMeasureMode"),
    (0x000b, "GPSDOP"),
    (0x000c, "GPSSpeedRef"),
    (0x000d, "GPSSpeed"),
    (0x000e, "GPSTrackRef"),
    (0x000f, "GPSTrack"),
    (0x0010, "GPSImgDirectionRef"),
    (0x0011, "GPSImgDirection"),
    (0x0012, "GPSMapDatum"),
    (0x0013, "GPSDestLatitudeRef"),
    (0x0014, "GPSDestLatitude"),
    (0x0015, "GPSDestLongitudeRef"),
    (0x0016, "GPSDestLongitude"),
    (0x0017, "GPSDestBearingRef"),
    (0x0018, "GPSDestBearing"),
    (0x0019, "GPSDestDistanceRef"),
    (0x001a, "GPSDestDistance"),
    (0x001b, "GPSProcessingMethod"),
    (0x001c, "GPSAreaInformation"),
    (0x001d, "GPSDateStamp"),
    (0x001e, "GPSDifferential"),
    (0x001f, "GPSHPositioningError"),
  ]
  for e in ifd0 {
    let (id, name) = e
    check(@moonmeta.Ifd0, id, name)
  }
  for e in exif {
    let (id, name) = e
    check(@moonmeta.Exif, id, name)
  }
  for e in gps {
    let (id, name) = e
    check(@moonmeta.Gps, id, name)
  }
  let interop : Array[(Int, String)] = [
    (0x0001, "InteropIndex"),
    (0x0002, "InteropVersion"),
    (0x1001, "RelatedImageWidth"),
    (0x1002, "RelatedImageHeight"),
  ]
  for e in interop {
    let (id, name) = e
    check(@moonmeta.Interop, id, name)
  }
  @test.assert_eq(
    ifd0.length() + exif.length() + gps.length() + interop.length(),
    // 上面四张期望清单的条目总数；新增要点名的 tag 时同步加。
    65,
  )
}

///|
/// 表外的编号必须打回十六进制。
///
/// 四个目录共用一套编号空间：同一个数字在 IFD0 和 Exif 下是两个不同的 tag。
/// 拿别的目录的名字来填，等于在报告里指一个不存在的位置。
test "查不到名字就回吐编号，不拿别的目录凑" {
  check(@moonmeta.Exif, 0xea1c, "0xea1c")
  check(@moonmeta.Ifd0, 0x9003, "0x9003")
  check(@moonmeta.Gps, 0x00ff, "0x00ff")
  check(@moonmeta.Interop, 0x2000, "0x2000")
}

///|
test "六个类别各有一句短名，供报告排版" {
  @test.assert_eq(@moonmeta.Location.label(), "location")
  @test.assert_eq(@moonmeta.Identity.label(), "identity")
  @test.assert_eq(@moonmeta.DeviceId.label(), "device_id")
  @test.assert_eq(@moonmeta.MakerNote.label(), "maker_note")
  @test.assert_eq(@moonmeta.Comments.label(), "comments")
  @test.assert_eq(@moonmeta.Timestamps.label(), "timestamps")
}

///|
/// `Copyright` 刻意不在任何类别里：它是权利声明，抹掉本身就是一种伤害。
test "策略够不着的条目要说清是哪一类，或明确不属于" {
  @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Ifd0, 0x8298), None)
  @test.assert_eq(
    @moonmeta.sensitive_category(@moonmeta.Ifd0, 0x013b),
    Some(@moonmeta.Identity),
  )
  // GPS 目录整体算坐标：连版本号都在说"这张图带过位置"。
  @test.assert_eq(
    @moonmeta.sensitive_category(@moonmeta.Gps, 0x0000),
    Some(@moonmeta.Location),
  )
  // TIFF 里的整包 IPTC-NAA 是 0x83bb。它一度被记成 0x8773，于是真 IPTC
  // 一条都不报、而别人的 ICC 配置文件被当成元数据摘掉——两头都错。
  @test.assert_eq(
    @moonmeta.sensitive_category(@moonmeta.Ifd0, 0x83bb),
    Some(@moonmeta.Carrier),
  )
  // 0x8773 是 ICC 色彩变换表：不是谁的行踪，摘了只会让产物偏色。
  // 这一条断言是那一格的反向闸——它要是变成 Some(_)，脱敏就在改颜色了。
  @test.assert_eq(@moonmeta.sensitive_category(@moonmeta.Ifd0, 0x8773), None)
}
