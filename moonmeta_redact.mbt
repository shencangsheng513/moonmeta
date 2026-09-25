// 脱敏策略与执行。
//
// 读—改—写走同一套 IR：`redact` 只删条目，不碰没被策略点名的任何东西，
// 所以"删掉 GPS 之后照片还能不能看、颜色对不对"这件事由构造保证，
// 不由运气保证。

///|
/// 哪些类别要清除。每一类对应 `sensitive_category` 的一个返回值。
///
/// 默认策略 `privacy` 保留时间戳：拍摄日期对相册、排序、法律证据都太常用，
/// 而它单独存在时定位不到人。要连时间一起清掉用 `strict`。
pub(all) struct Policy {
  location : Bool
  identity : Bool
  device_id : Bool
  maker_note : Bool
  comments : Bool
  timestamps : Bool
  /// 整包载体：JPEG 的 APP1/XMP 段、PNG 的 XMP 文本块，以及 IFD0 里的
  /// XMP / Photoshop / IPTC-NAA 条目。
  ///
  /// 单独一个开关，是因为它管的不是"某一条敏不敏感"，而是"这张图还有第二份元数据"。
  /// EXIF 里的 DateTimeOriginal 删掉、XMP 里那份原样留着，等于没删——
  /// 而报告上看不出任何异常。99 张真实照片里有 34 张带 XMP 包。
  carrier : Bool
} derive(Debug, Eq)

///|
pub extend Policy with Eq::{not_equal, equal}

///|
pub extend Policy with @debug.Debug::{to_repr}

///|
/// 常规发布用：坐标、署名、序列号、厂商私有块、备注，以及整包 XMP。
///
/// XMP 默认也删：它是同一批事实的第二份副本，留着就等于没删。
pub fn privacy_policy() -> Policy {
  {
    location: true,
    identity: true,
    device_id: true,
    maker_note: true,
    comments: true,
    timestamps: false,
    carrier: true,
  }
}

///|
/// 对外交付证据前的最强档：连时间戳一起清。
pub fn strict_policy() -> Policy {
  {
    location: true,
    identity: true,
    device_id: true,
    maker_note: true,
    comments: true,
    timestamps: true,
    carrier: true,
  }
}

///|
/// 什么都不清，只用来做只读审计的对照。
pub fn empty_policy() -> Policy {
  {
    location: false,
    identity: false,
    device_id: false,
    maker_note: false,
    comments: false,
    timestamps: false,
    carrier: false,
  }
}

///|
/// 策略是否覆盖某一类。
///
/// 这里刻意不写 `_ => false`：新增一类敏感信息时，编译要在这里停下来，
/// 否则默认行为是"不删"，而"不删"在脱敏库里等于泄露。
pub fn Policy::covers(self : Policy, category : Sensitive) -> Bool {
  match category {
    Location => self.location
    Identity => self.identity
    DeviceId => self.device_id
    MakerNote => self.maker_note
    Comments => self.comments
    Timestamps => self.timestamps
    Carrier => self.carrier
  }
}

///|
/// 一条被点名（或将被删除）的条目。
pub(all) struct Removed {
  dir : Dir
  tag : Int
  name : String
  category : Sensitive
} derive(Debug, Eq)

///|
pub extend Removed with Eq::{not_equal, equal}

///|
pub extend Removed with @debug.Debug::{to_repr}

///|
/// 一次脱敏的交代：删了什么、有没有连带丢掉缩略图。
///
/// `dropped_thumbnail` 为真表示原文件的 APP1 里挂着缩略图链，
/// 回写时它被整条丢掉——缩略图常常自带一份 GPS，
/// "删了主 GPS 却留着缩略图"是最常见的假脱敏。
pub(all) struct Redaction {
  removed : Array[Removed]
  dropped_thumbnail : Bool
  /// 容器里的 XMP 包有没有被整段摘掉。
  ///
  /// 和 `dropped_thumbnail` 一样，这一项没法用 `removed` 里的一条记录表达：
  /// XMP 不归 IFD 管，条目清单里根本没有它。
  /// 那个 Bool 同样要区分"丢了"和"本来就没有"。
  dropped_xmp : Bool
} derive(Debug, Eq)

///|
pub extend Redaction with Eq::{not_equal, equal}

///|
pub extend Redaction with @debug.Debug::{to_repr}

///|
/// 只报告，不修改：把会被删的东西先给用户看一遍。
pub fn TiffBlock::findings(self : TiffBlock, p : Policy) -> Array[Removed] {
  let out : Array[Removed] = []
  collect(self.ifd0, Ifd0, p, out)
  collect(self.exif, Exif, p, out)
  collect(self.gps, Gps, p, out)
  collect(self.interop, Interop, p, out)
  out
}

///|
fn collect(
  entries : Array[IfdEntry],
  dir : Dir,
  p : Policy,
  out : Array[Removed],
) -> Unit {
  for e in entries {
    match sensitive_category(dir, e.tag) {
      Some(cat) =>
        if p.covers(cat) {
          out.push({
            dir,
            tag: e.tag,
            name: tag_name(dir, e.tag),
            category: cat,
          })
        }
      None => ()
    }
  }
}

///|
/// 执行脱敏，同时交出报告。
pub fn TiffBlock::redact(
  self : TiffBlock,
  p : Policy,
) -> (TiffBlock, Redaction) {
  let report = self.findings(p)
  let block = {
    little: self.little,
    ifd0: keep_entries(self.ifd0, Ifd0, p),
    exif: keep_entries(self.exif, Exif, p),
    gps: keep_entries(self.gps, Gps, p),
    interop: keep_entries(self.interop, Interop, p),
    has_ifd1: false,
  }
  // 裸 TIFF 里 XMP 是 IFD0 的一条（0x02bc），已经被上面的按条过滤处理了；
  // 这里的 dropped_xmp 只说容器里那种成包的 XMP。
  (
    block,
    { removed: report, dropped_thumbnail: self.has_ifd1, dropped_xmp: false, },
  )
}

///|
fn keep_entries(
  entries : Array[IfdEntry],
  dir : Dir,
  p : Policy,
) -> Array[IfdEntry] {
  let out : Array[IfdEntry] = []
  for e in entries {
    let drop = match sensitive_category(dir, e.tag) {
      Some(cat) => p.covers(cat)
      None => false
    }
    if !drop {
      out.push(e)
    }
  }
  out
}

///|
/// 一步到位：解析 → 脱敏 → 回写。返回新的 TIFF 块字节与报告。
pub fn redact_tiff(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  let block = decode_tiff(data)
  let (kept, report) = block.redact(p)
  (encode_tiff(kept), report)
}
