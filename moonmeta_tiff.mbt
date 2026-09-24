// TIFF/IFD 读取器。
//
// 一个 EXIF APP1 段去掉 `Exif\0\0` 前缀之后就是一个完整的 TIFF 文件，
// 所以这里读的字节流从 TIFF 头开始：`II`/`MM` + 42 + IFD0 偏移。
//
// 与"读出 4 个认识的字段就走"的写法不同，这里把每一个能解的条目都留在
// IR 里——包括本库完全不懂的厂商私有 tag。脱敏工具只有在知道自己
// 略过了什么的时候才有意义。

///|
/// 一个 IFD 条目。
///
/// `type_code` 是原始 TIFF 类型码，回写时要照它重新编码；
/// `value` 的形状由 `type_code` 决定（见 `moonmeta_value.mbt` 的对应表）。
pub(all) struct IfdEntry {
  tag : Int
  type_code : Int
  value : TagValue
} derive(Debug, Eq)

///|
pub extend IfdEntry with Eq::{not_equal, equal}

///|
pub extend IfdEntry with @debug.Debug::{to_repr}

///|
/// 解析结果：TIFF 头的字节序 + 三个目录。
///
/// `ifd0` 里**不含** `0x8769`/`0x8825` 这两个子目录指针——它们是结构而不是
/// 数据，解析时被消费掉，回写时按新布局重算，所以
/// `decode(encode(x)) == x` 才可能成立。
///
/// `has_ifd1` 记录原文件是否有缩略图目录。它只是"这里曾经有过一张缩略图"
/// 的记号：回写时缩略图链连同它的字节一起丢弃，这是**有意**的行为——
/// 留着缩略图的"脱敏"结果仍然可能泄露原始 GPS 与机身信息。
pub(all) struct TiffBlock {
  little : Bool
  ifd0 : Array[IfdEntry]
  exif : Array[IfdEntry]
  gps : Array[IfdEntry]
  has_ifd1 : Bool
} derive(Debug, Eq)

///|
pub extend TiffBlock with Eq::{not_equal, equal}

///|
pub extend TiffBlock with @debug.Debug::{to_repr}

///|
/// Exif 子目录指针。
pub let tag_exif_ifd : Int = 0x8769

///|
/// GPS 子目录指针。
pub let tag_gps_ifd : Int = 0x8825

///|
/// 缩略图数据偏移（与 IFD1 配对出现）。
pub let tag_thumb_offset : Int = 0x0201

///|
/// 缩略图数据长度。
pub let tag_thumb_length : Int = 0x0202

///|
/// 从一个 TIFF 字节块解析。`data` 的第一字节必须是 `I`/`M`。
pub fn decode_tiff(data : Bytes) -> TiffBlock raise MetaError {
  if data.length() < 8 {
    raise TooShort(8, data.length())
  }
  let b0 = byte_at(data, 0)
  let b1 = byte_at(data, 1)
  let little = if b0 == b'I' && b1 == b'I' {
    true
  } else if b0 == b'M' && b1 == b'M' {
    false
  } else {
    raise BadByteOrder(0)
  }
  if u16_at(data, 2, little) != 42 {
    raise BadTiffHeader(2)
  }
  let ifd0_off = check_ifd_offset(data, u32_at(data, 4, little))
  let dir0 = parse_dir(data, ifd0_off, little)
  let exif_dir = match sub_dir_offset(data, dir0.entries, tag_exif_ifd) {
    Some(off) => parse_dir(data, off, little)
    None => { entries: [], next: 0L, }
  }
  let gps_off = match sub_dir_offset(data, dir0.entries, tag_gps_ifd) {
    Some(off) => Some(off)
    None => sub_dir_offset(data, exif_dir.entries, tag_gps_ifd)
  }
  let gps_dir = match gps_off {
    Some(off) => parse_dir(data, off, little)
    None => { entries: [], next: 0L, }
  }
  // 指针 tag 是结构不是数据，不进 IR；各目录的后继（缩略图链）只留一个记号。
  {
    little,
    ifd0: without(dir0.entries, [tag_exif_ifd, tag_gps_ifd]),
    exif: without(exif_dir.entries, [tag_gps_ifd, tag_exif_ifd]),
    gps: gps_dir.entries,
    has_ifd1: dir0.next > 0L || exif_dir.next > 0L || gps_dir.next > 0L,
  }
}

///|
/// 一个目录末尾"下一目录指针"所在的偏移。
/// `n` 来自 u16，且 parse_dir 已保证表体落在块内，这里不会溢出。
fn dir_end(dir_off : Int, n : Int) -> Int {
  dir_off + 2 + 12 * n
}

///|
fn parse_dir(
  data : Bytes,
  dir_off : Int,
  little : Bool,
) -> RawDir raise MetaError {
  let count = u16_at(data, dir_off, little)
  let avail = data.length() - dir_off - 2
  if count > avail / 12 {
    // 声明的条目表比剩余字节还长：直接拒绝，不进入逐条读取。
    raise EntryTooLarge(0, count * 12, avail)
  }
  let entries : Array[IfdEntry] = []
  for i = 0; i < count; i = i + 1 {
    entries.push(parse_entry(data, dir_off + 2 + 12 * i, little))
  }
  let next = u32_at(data, dir_end(dir_off, count), little)
  { entries, next, }
}

///|
priv struct RawDir {
  entries : Array[IfdEntry]
  next : Int64
}

///|
fn parse_entry(
  data : Bytes,
  entry_off : Int,
  little : Bool,
) -> IfdEntry raise MetaError {
  let tag = u16_at(data, entry_off, little)
  let type_code = u16_at(data, entry_off + 2, little)
  let count = u32_at(data, entry_off + 4, little)
  let size = match type_size(type_code) {
    Some(s) => s
    None => raise UnsupportedType(tag, type_code)
  }
  let total = count * size.to_int64()
  // 先卡上限再看它放不放得进 4 字节：`total <= 4` 在 Int64 上判断，
  // 避免 count 大到让 count*size 绕回 32 位。
  let voff = if total <= 4L {
    entry_off + 8
  } else {
    let off = u32_at(data, entry_off + 8, little)
    let len = data.length().to_int64()
    if off < 0L || off + total > len {
      raise ValueOffsetOutOfRange(tag, off)
    }
    off.to_int()
  }
  let have = data.length() - voff
  if total > have.to_int64() {
    raise EntryTooLarge(tag, total.to_int(), have)
  }
  {
    tag,
    type_code,
    value: decode_value(data, voff, tag, type_code, count.to_int(), little),
  }
}

///|
fn decode_value(
  data : Bytes,
  voff : Int,
  tag : Int,
  type_code : Int,
  count : Int,
  little : Bool,
) -> TagValue raise MetaError {
  match type_code {
    2 => Text(read_latin1(data, voff, count))
    1 | 6 | 7 => Raw(read_bytes(data, voff, count))
    3 => Shorts(read_shorts(data, voff, count, little, false))
    8 => Shorts(read_shorts(data, voff, count, little, true))
    4 => Longs(read_longs(data, voff, count, little, false))
    9 => Longs(read_longs(data, voff, count, little, true))
    5 | 10 => Rationals(read_rationals(data, voff, type_code, count, little))
    _ => raise UnsupportedType(tag, type_code)
  }
}

///|
/// 子目录指针：只认 count=1 的 LONG。形状不对当作没有子目录，
/// 但指针落在块外是文件坏了，要报错而不是静默忽略。
fn sub_dir_offset(
  data : Bytes,
  entries : Array[IfdEntry],
  tag : Int,
) -> Int? raise MetaError {
  match find_entry(entries, tag) {
    Some(e) =>
      match e.value {
        Longs(v) if v.length() == 1 => {
          let off = v[0]
          if off < 0L || off + 2L > data.length().to_int64() {
            raise SubIfdOutOfRange(tag, off)
          }
          Some(off.to_int())
        }
        _ => None
      }
    None => None
  }
}

///|
fn find_entry(entries : Array[IfdEntry], tag : Int) -> IfdEntry? {
  for e in entries {
    if e.tag == tag {
      return Some(e)
    }
  }
  None
}

///|
fn without(entries : Array[IfdEntry], tags : Array[Int]) -> Array[IfdEntry] {
  let out : Array[IfdEntry] = []
  for e in entries {
    if !has_tag(tags, e.tag) {
      out.push(e)
    }
  }
  out
}

///|
fn has_tag(tags : Array[Int], tag : Int) -> Bool {
  for t in tags {
    if t == tag {
      return true
    }
  }
  false
}

// ---- 便捷访问 ----

///|
/// 按 tag 查值：IFD0 → Exif → GPS 依次找。
/// 同名 tag 在不同目录里含义不同，所以这是"够用就好"的捷径，
/// 需要精确时用 `ifd0_find`/`exif_find`/`gps_find`。
pub fn TiffBlock::get(self : TiffBlock, tag : Int) -> TagValue? {
  match self.ifd0_find(tag) {
    Some(e) => Some(e.value)
    None =>
      match self.exif_find(tag) {
        Some(e) => Some(e.value)
        None =>
          match self.gps_find(tag) {
            Some(e) => Some(e.value)
            None => None
          }
      }
  }
}

///|
pub fn TiffBlock::ifd0_find(self : TiffBlock, tag : Int) -> IfdEntry? {
  find_entry(self.ifd0, tag)
}

///|
pub fn TiffBlock::exif_find(self : TiffBlock, tag : Int) -> IfdEntry? {
  find_entry(self.exif, tag)
}

///|
pub fn TiffBlock::gps_find(self : TiffBlock, tag : Int) -> IfdEntry? {
  find_entry(self.gps, tag)
}

///|
fn text_at(block : TiffBlock, tag : Int) -> String? {
  match block.get(tag) {
    Some(v) => v.text()
    None => None
  }
}

///|
/// 机身厂商（tag 0x010F）。
pub fn TiffBlock::make(self : TiffBlock) -> String? {
  text_at(self, 0x010f)
}

///|
/// 机身型号（tag 0x0110）。
pub fn TiffBlock::model(self : TiffBlock) -> String? {
  text_at(self, 0x0110)
}

///|
/// 生成软件（tag 0x0131）。
pub fn TiffBlock::software(self : TiffBlock) -> String? {
  text_at(self, 0x0131)
}

///|
/// 拍摄时间（tag 0x0132）。
pub fn TiffBlock::date_time(self : TiffBlock) -> String? {
  text_at(self, 0x0132)
}

///|
/// 原始拍摄时间（Exif tag 0x9003）。
pub fn TiffBlock::date_time_original(self : TiffBlock) -> String? {
  text_at(self, 0x9003)
}

///|
/// 作者（tag 0x013B）。
pub fn TiffBlock::artist(self : TiffBlock) -> String? {
  text_at(self, 0x013b)
}

///|
/// 版权声明（tag 0x8298）。
pub fn TiffBlock::copyright(self : TiffBlock) -> String? {
  text_at(self, 0x8298)
}

///|
/// 方向（tag 0x0112），1..8；读不到或非 SHORT 时返回 None。
pub fn TiffBlock::orientation(self : TiffBlock) -> Int? {
  match self.get(0x0112) {
    Some(Shorts(v)) if v.length() > 0 => Some(v[0])
    _ => None
  }
}

///|
/// GPS 经纬度（度，东经/北纬为正）。缺任一半或形状不对都返回 None。
pub fn TiffBlock::gps_lat_lon(self : TiffBlock) -> (Double, Double)? {
  match (dms(self, 0x0002, 0x0001), dms(self, 0x0004, 0x0003)) {
    (Some(lat), Some(lon)) => Some((lat, lon))
    _ => None
  }
}

///|
/// 度分秒 → 十进制度，并按参考系（N/S、E/W）定符号。
fn dms(block : TiffBlock, value_tag : Int, ref_tag : Int) -> Double? {
  let parts = match block.gps_find(value_tag) {
    Some(e) =>
      match e.value {
        Rationals(v) if v.length() == 3 => v
        _ => return None
      }
    None => return None
  }
  let deg = parts[0].to_double()
  let min = parts[1].to_double()
  let sec = parts[2].to_double()
  let sign = match block.gps_find(ref_tag) {
    Some(e) =>
      match e.value {
        Text(s) if s.length() > 0 =>
          if s[0] == 'S' || s[0] == 'W' {
            -1.0
          } else {
            1.0
          }
        _ => 1.0
      }
    None => 1.0
  }
  Some(sign * (deg + min / 60.0 + sec / 3600.0))
}

///|
/// 是否存在 GPS 目录（哪怕里面只有空壳）。脱敏审计的第一问。
pub fn TiffBlock::has_gps(self : TiffBlock) -> Bool {
  self.gps.length() > 0
}

// ---- 字节读取原语：全部经检查过的 get，越界一律变成带偏移的错误 ----

///|
fn byte_at(data : Bytes, off : Int) -> Byte raise MetaError {
  match data.get(off) {
    Some(b) => b
    None =>
      raise TooShort(
        1,
        if off < 0 || off >= data.length() {
          0
        } else {
          data.length() - off
        },
      )
  }
}

///|
fn u16_at(data : Bytes, off : Int, little : Bool) -> Int raise MetaError {
  let a = byte_at(data, off).to_int()
  let b = byte_at(data, off + 1).to_int()
  if little {
    a + (b << 8)
  } else {
    (a << 8) + b
  }
}

///|
fn u32_at(data : Bytes, off : Int, little : Bool) -> Int64 raise MetaError {
  let b0 = byte_at(data, off).to_int().to_int64()
  let b1 = byte_at(data, off + 1).to_int().to_int64()
  let b2 = byte_at(data, off + 2).to_int().to_int64()
  let b3 = byte_at(data, off + 3).to_int().to_int64()
  if little {
    b0 + b1 * 256L + b2 * 65536L + b3 * 16777216L
  } else {
    b0 * 16777216L + b1 * 65536L + b2 * 256L + b3
  }
}

///|
fn signed32(v : Int64, signed : Bool) -> Int64 {
  if signed && v >= 2147483648L {
    v - 4294967296L
  } else {
    v
  }
}

///|
fn check_ifd_offset(data : Bytes, off : Int64) -> Int raise MetaError {
  let len = data.length().to_int64()
  if off < 0L || off + 2L > len {
    raise IfdOffsetOutOfRange(off)
  }
  off.to_int()
}

///|
fn read_bytes(
  data : Bytes,
  voff : Int,
  count : Int,
) -> Array[Byte] raise MetaError {
  let out : Array[Byte] = []
  for i = 0; i < count; i = i + 1 {
    out.push(byte_at(data, voff + i))
  }
  out
}

///|
/// ISO-8859-1 逐字节映射：单字节 → 同名码点，无损且可逆。
/// 在第一个 NUL 处截断（TIFF 的 ASCII 类型以 NUL 结尾）。
fn read_latin1(data : Bytes, voff : Int, count : Int) -> String raise MetaError {
  let chars : Array[Char] = []
  for i = 0; i < count; i = i + 1 {
    let b = byte_at(data, voff + i)
    if b == b'\x00' {
      break
    }
    match b.to_int().to_char() {
      Some(c) => chars.push(c)
      // 0..255 必是合法码点；这一臂取不到，取到也只是丢一个字符，
      // 不值得为它 panic。
      None => ()
    }
  }
  String::from_array(chars)
}

///|
fn read_shorts(
  data : Bytes,
  voff : Int,
  count : Int,
  little : Bool,
  signed : Bool,
) -> Array[Int] raise MetaError {
  let out : Array[Int] = []
  for i = 0; i < count; i = i + 1 {
    let raw = u16_at(data, voff + 2 * i, little)
    out.push(if signed && raw >= 32768 { raw - 65536 } else { raw })
  }
  out
}

///|
fn read_longs(
  data : Bytes,
  voff : Int,
  count : Int,
  little : Bool,
  signed : Bool,
) -> Array[Int64] raise MetaError {
  let out : Array[Int64] = []
  for i = 0; i < count; i = i + 1 {
    out.push(signed32(u32_at(data, voff + 4 * i, little), signed))
  }
  out
}

///|
fn read_rationals(
  data : Bytes,
  voff : Int,
  type_code : Int,
  count : Int,
  little : Bool,
) -> Array[Rational] raise MetaError {
  let signed = type_code == 10
  let out : Array[Rational] = []
  for i = 0; i < count; i = i + 1 {
    let base = voff + 8 * i
    out.push({
      num: signed32(u32_at(data, base, little), signed),
      den: signed32(u32_at(data, base + 4, little), signed),
    })
  }
  out
}
