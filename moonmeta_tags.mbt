// tag 名字表与敏感分类表。
//
// 表里每一个编号都逐条对着 exiftool 公布的 EXIF/GPS tag 名表
// （exiftool.org/TagNames/EXIF.html 与 GPS.html）核过，核对日期 2026-09-24。
// 没核过的一律不进表——宁可打印"0x927c"，也不要打印一个错名字，
// 因为这个名字会被人拿去决定删什么。

///|
/// 条目所在的目录。同名 tag 在不同目录里是不同含义，所以查名字必须带目录。
pub(all) enum Dir {
  Ifd0
  Exif
  Gps
  Interop
} derive(Debug, Eq)

///|
pub extend Dir with Eq::{not_equal, equal}

///|
pub extend Dir with @debug.Debug::{to_repr}

///|
pub fn Dir::label(self : Dir) -> String {
  match self {
    Ifd0 => "IFD0"
    Exif => "Exif"
    Gps => "GPS"
    Interop => "Interop"
  }
}

///|
pub impl Show for Dir with fn output(self : Dir, logger) {
  logger.write(self.label())
}

///|
pub extend Dir with Show::{to_string, output}

///|
/// tag 的规范名；表里没有就返回 `0xNNNN`。
pub fn tag_name(dir : Dir, tag : Int) -> String {
  let named = match dir {
    Ifd0 => ifd0_name(tag)
    Exif => exif_name(tag)
    Gps => gps_name(tag)
    Interop => interop_name(tag)
  }
  match named {
    Some(s) => s
    None => tag_hex(tag)
  }
}

///|
fn ifd0_name(tag : Int) -> String? {
  match tag {
    0x010f => Some("Make")
    0x0110 => Some("Model")
    0x0112 => Some("Orientation")
    0x0131 => Some("Software")
    0x0132 => Some("DateTime")
    0x013b => Some("Artist")
    0x0201 => Some("JPEGInterchangeFormat")
    0x0202 => Some("JPEGInterchangeFormatLength")
    0x02bc => Some("XMP")
    0x02bd => Some("PhotoshopSettings")
    0x8298 => Some("Copyright")
    0x83bb => Some("IptcNaa")
    0x8769 => Some("ExifOffset")
    0x8773 => Some("InterColorProfile")
    0x8825 => Some("GPSInfo")
    _ => None
  }
}

///|
fn exif_name(tag : Int) -> String? {
  match tag {
    0x8825 => Some("GPSInfo")
    0x9003 => Some("DateTimeOriginal")
    0x9004 => Some("DateTimeDigitized")
    0x9010 => Some("OffsetTime")
    0x9011 => Some("OffsetTimeOriginal")
    0x9012 => Some("OffsetTimeDigitized")
    0x927c => Some("MakerNote")
    0x9286 => Some("UserComment")
    0x9290 => Some("SubsecTime")
    0x9291 => Some("SubsecTimeOriginal")
    0xa005 => Some("InteropOffset")
    0xa420 => Some("ImageUniqueID")
    0xa431 => Some("BodySerialNumber")
    0xa435 => Some("LensSerialNumber")
    _ => None
  }
}

///|
/// Interoperability IFD 的名字表。
///
/// 只收真实语料里出现过的四个编号（对拍语料里带 Interop IFD 的 44 个文件，
/// 键集合恰好是 `0x1/0x2` 或 `0x1/0x2/0x1001/0x1002` 两种）。规范里还有别的编号，
/// 但没在这儿被任何相机写出过——把没验证过的名字写进表里，
/// 就等于把猜测冒充成这库的认识。
fn interop_name(tag : Int) -> String? {
  match tag {
    0x0001 => Some("InteropIndex")
    0x0002 => Some("InteropVersion")
    0x1001 => Some("RelatedImageWidth")
    0x1002 => Some("RelatedImageHeight")
    _ => None
  }
}

///|
fn gps_name(tag : Int) -> String? {
  match tag {
    0x0000 => Some("GPSVersionID")
    0x0001 => Some("GPSLatitudeRef")
    0x0002 => Some("GPSLatitude")
    0x0003 => Some("GPSLongitudeRef")
    0x0004 => Some("GPSLongitude")
    0x0005 => Some("GPSAltitudeRef")
    0x0006 => Some("GPSAltitude")
    0x0007 => Some("GPSTimeStamp")
    0x0008 => Some("GPSSatellites")
    0x0009 => Some("GPSStatus")
    0x000a => Some("GPSMeasureMode")
    0x000b => Some("GPSDOP")
    0x000c => Some("GPSSpeedRef")
    0x000d => Some("GPSSpeed")
    0x000e => Some("GPSTrackRef")
    0x000f => Some("GPSTrack")
    0x0010 => Some("GPSImgDirectionRef")
    0x0011 => Some("GPSImgDirection")
    0x0012 => Some("GPSMapDatum")
    0x0013 => Some("GPSDestLatitudeRef")
    0x0014 => Some("GPSDestLatitude")
    0x0015 => Some("GPSDestLongitudeRef")
    0x0016 => Some("GPSDestLongitude")
    0x0017 => Some("GPSDestBearingRef")
    0x0018 => Some("GPSDestBearing")
    0x0019 => Some("GPSDestDistanceRef")
    0x001a => Some("GPSDestDistance")
    0x001b => Some("GPSProcessingMethod")
    0x001c => Some("GPSAreaInformation")
    0x001d => Some("GPSDateStamp")
    0x001e => Some("GPSDifferential")
    0x001f => Some("GPSHPositioningError")
    _ => None
  }
}

///|
/// 敏感条目总表：(所在目录, tag 编号, 类别)。
///
/// 目录必须写进表里：同一个编号在 IFD0 和 Exif 下是两个不同的 tag，
/// 只按编号匹配会给出一条指错方向、名字打不出来的删除记录，
/// 而这份报告是拿来决定"删了什么"的。
///
/// 每一个编号都对着 exiftool 的 tag 名表核过（见文件头）。
let sensitive_tags : Array[(Dir, Int, Sensitive)] = [
  // 署名与内容指纹：直接指向人
  (Ifd0, 0x013b, Identity),
  (Exif, 0xa420, Identity),
  // 机身/镜头序列号：能把两张"匿名"照片关联到同一台机器
  (Exif, 0xa431, DeviceId),
  (Exif, 0xa435, DeviceId),
  // 厂商私有块：内容不受规范约束，坐标常藏在里面
  (Exif, 0x927c, MakerNote),
  // 整包载体：条目本身只有一句"这里另有一整套元数据"，
  // 里面的字段归 XMP / Photoshop / IPTC 各自的规范管，我们逐条判断不了。
  (Ifd0, 0x02bc, Carrier),
  (Ifd0, 0x02bd, Carrier),
  (Ifd0, 0x83bb, Carrier),
  // `0x8773` (InterColorProfile) 刻意不在任何类别里：ICC 是一份色彩变换表，
  // 不是元数据的第二副本，里面既指不出人也指不出地点。把它当载体摘掉，
  // 换来的不是隐私而是产物偏色——摘别人的颜色不是脱敏工具的权利。
  // 用户写的话
  (Exif, 0x9286, Comments),
  // 能把照片排进时间线的一切
  (Ifd0, 0x0132, Timestamps),
  (Exif, 0x9003, Timestamps),
  (Exif, 0x9004, Timestamps),
  (Exif, 0x9010, Timestamps),
  (Exif, 0x9011, Timestamps),
  (Exif, 0x9012, Timestamps),
  (Exif, 0x9290, Timestamps),
  (Exif, 0x9291, Timestamps),
]

///|
/// 敏感信息的类别。
///
/// 刻意不做成 String：类别是策略的开关，"加了新类别却忘了在策略里处理"
/// 必须变成编译错误，不能变成"静默不删、数据照原样发出去"。
pub(all) enum Sensitive {
  /// GPS 目录里的全部条目，以及坐标本身
  Location
  /// 署名、内容指纹：直接指向人
  Identity
  /// 机身/镜头序列号：能把两台"匿名"照片关联到同一台机器
  DeviceId
  /// 厂商私有块：内容不受规范约束，坐标常藏在里面
  MakerNote
  /// 用户写的话
  Comments
  /// 能把照片排进时间线的一切
  Timestamps
  /// 整包的外部元数据载体：XMP / Photoshop IRB / IPTC-NAA。
  ///
  /// 前六类说的是"这一条是什么"，这一类说的是"这里还有一整套元数据"：
  /// 载体里的字段编号、命名、编码都归另一份规范管，按条判断力所不及，
  /// 只能整包丢。所以这一类不是理论负担——那批外来裸 TIFF（104 份）按 TIFF 6.0
  /// 走一遍 IFD0，带 XMP（`0x02bc`）的 10 份、带 IPTC-NAA（`0x83bb`）的 1 份、
  /// 带 Photoshop（`0x02bd`）的 0 份。这 10 份里有 1 份（`ifd_tag_type.tiff`）
  /// 在 Exif 指针上用了类型 13，读取侧按设计先拒绝、走不到那条条目，所以这个数
  /// 只回答"条目在不在"，不回答"库读不读得通"（对拍闸按字节里的包标记数是 9 份，
  /// 差的正是这一份）。JPEG 那一侧的 IPTC 不住在 IFD0 里，走 APP13 段，
  /// 由容器层整段摘（见 `moonmeta_jpeg.mbt`）：99 张真实照片那批里带包 10 份，
  /// 摘除并披露 10 份。
  Carrier
} derive(Debug, Eq)

///|
pub extend Sensitive with Eq::{not_equal, equal}

///|
pub extend Sensitive with @debug.Debug::{to_repr}

///|
/// 用于展示的短名。
pub fn Sensitive::label(self : Sensitive) -> String {
  match self {
    Location => "location"
    Identity => "identity"
    DeviceId => "device_id"
    MakerNote => "maker_note"
    Comments => "comments"
    Timestamps => "timestamps"
    Carrier => "carrier"
  }
}

///|
pub impl Show for Sensitive with fn output(self : Sensitive, logger) {
  logger.write(self.label())
}

///|
pub extend Sensitive with Show::{to_string, output}

///|
/// 这个条目属于哪一类敏感信息；`None` 表示不属于任何被策略覆盖的类别。
///
/// GPS 目录整体算 `Location`：目录里的 tag 没有一个是无辜的，
/// 连 `GPSVersionID` 都在告诉别人"这张图带过坐标"。
///
/// `Copyright` 不在任何类别里——它是权利声明，抹掉它本身就是一种伤害。
pub fn sensitive_category(dir : Dir, tag : Int) -> Sensitive? {
  if dir == Gps {
    Some(Location)
  } else {
    for e in sensitive_tags {
      let (d, t, cat) = e
      if d == dir && t == tag {
        return Some(cat)
      }
    }
    None
  }
}
