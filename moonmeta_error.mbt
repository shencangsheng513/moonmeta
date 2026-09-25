///|
/// 解析一个字节流时能出错的每一种方式。
///
/// 每条错误都带定位信息。报"坏了"不够，要能指出坏在哪里，
/// 否则用户拿到的是一个无法追问的失败：
/// 读字节流时错的都带字节偏移，回写时错的都带所在条目的 tag。
pub suberror MetaError {
  /// 字节流比声明的长度短：(偏移, 需要, 实有)
  /// 偏移是这次读取想落在的位置；它已经落在块外时实有记 0。
  TooShort(Int, Int, Int)
  /// TIFF 头不在给定偏移处：(偏移)
  BadTiffHeader(Int)
  /// 字节序标记既不是 "II" 也不是 "MM"：(偏移)
  BadByteOrder(Int)
  /// IFD 偏移指向块外：(偏移)
  IfdOffsetOutOfRange(Int64)
  /// 条目声明的字节数超过剩余空间：(偏移, tag, 声明, 可用)
  /// 偏移与可用配对：偏移 + 可用 = 块长。整张目录表放不下时没有具体条目，
  /// tag 记 0，偏移就是表体的第一字节。
  EntryTooLarge(Int, Int, Int, Int)
  /// 条目的值偏移落在块外：(tag, 偏移)
  ValueOffsetOutOfRange(Int, Int64)
  /// 规范里有、但本版本还不打算解的类型：(tag, 类型码)
  UnsupportedType(Int, Int)
  /// 子 IFD 指针非法：(父 tag, 偏移)
  SubIfdOutOfRange(Int, Int64)
  /// 回写时文本值含有无法映射成单字节的码点：(tag, 码点)
  UnencodableText(Int, Int)
  /// 回写时声明的类型与值的形状不配对：(tag, 类型码)
  TypeMismatch(Int, Int)
  /// 回写时数值超出该类型码的宽度：(tag, 值)
  ValueOutOfRange(Int, Int64)
  /// 文件开头不是 JPEG 的 SOI：(偏移)
  NotJpeg(Int)
  /// 段声明的长度超出文件剩余：(段偏移, 声明, 可用)
  SegmentTooLarge(Int, Int, Int)
  /// 走到文件尾也没读到段码：(偏移)
  TruncatedAt(Int)
  /// 回写时段长字段放不下这份载荷：(段偏移, 上限, 需要)
  SegmentOverflow(Int, Int, Int)
  /// 还有第二份元数据是本版本够不着的（重复 APP1，或藏在压缩流之后）：(偏移)
  ExtraMetadata(Int)
  /// 文件开头不是 PNG 的 8 字节签名：(偏移)
  NotPng(Int)
  /// PNG 块的 CRC 与字节对不上：(块偏移, 声明, 实算)
  BadChecksum(Int, Int64, Int64)
  /// 裸 TIFF 的字节不止元数据：重建只能覆盖一部分，写回去就是丢掉其余
  /// （通常是像素数据）。拒绝写回：(IFD0 偏移, 文件长度, 重建长度)
  TiffNotByteExact(Int64, Int, Int)
  /// 开头既不是 JPEG 也不是 PNG 也不是 TIFF：(偏移)
  UnknownFormat(Int)
} derive(Debug)

///|
pub impl Show for MetaError with fn output(self : MetaError, logger) {
  match self {
    TooShort(off, need, have) =>
      logger.write_string(
        "need \{need} byte(s) at offset \{off} but the block holds only \{have}",
      )
    BadTiffHeader(off) =>
      logger.write_string("no TIFF header ('II' or 'MM') at offset \{off}")
    BadByteOrder(off) =>
      logger.write_string(
        "byte-order mark at offset \{off} is neither 'II' nor 'MM'",
      )
    IfdOffsetOutOfRange(off) =>
      logger.write_string(
        "IFD offset \{off} points outside the block or is misaligned",
      )
    EntryTooLarge(off, tag, declared, available) =>
      logger.write_string(
        "tag \{tag_hex(tag)} at offset \{off} declares \{declared} byte(s), only \{available} left",
      )
    ValueOffsetOutOfRange(tag, off) =>
      logger.write_string(
        "tag \{tag_hex(tag)} points to offset \{off}, outside the block",
      )
    UnsupportedType(tag, code) =>
      logger.write_string(
        "tag \{tag_hex(tag)} uses TIFF type \{code}, which this version does not decode",
      )
    SubIfdOutOfRange(parent, off) =>
      logger.write_string(
        "sub-IFD pointer of tag \{tag_hex(parent)} points to offset \{off}, outside the block",
      )
    UnencodableText(tag, cp) =>
      logger.write_string(
        "tag \{tag_hex(tag)} holds U+\{cp}, which has no single-byte ISO-8859-1 form",
      )
    TypeMismatch(tag, code) =>
      logger.write_string(
        "tag \{tag_hex(tag)} declares TIFF type \{code} but its value has a different shape",
      )
    ValueOutOfRange(tag, v) =>
      logger.write_string(
        "tag \{tag_hex(tag)} holds \{v}, which does not fit its declared TIFF type",
      )
    NotJpeg(off) =>
      logger.write_string(
        "no JPEG start-of-image marker (0xffd8) at offset \{off}",
      )
    SegmentTooLarge(off, declared, available) =>
      logger.write_string(
        "segment at offset \{off} declares \{declared} byte(s), only \{available} left in the file",
      )
    TruncatedAt(off) =>
      logger.write_string(
        "the file runs out at offset \{off}, in the middle of a segment table",
      )
    SegmentOverflow(off, limit, needed) =>
      logger.write_string(
        "the segment at offset \{off} can hold \{limit} byte(s); this payload needs \{needed}",
      )
    ExtraMetadata(off) =>
      logger.write_string(
        "a second metadata block sits at offset \{off}; removing only the first one would be a fake redaction",
      )
    NotPng(off) =>
      logger.write_string(
        "not a PNG: the 8-byte signature differs at offset \{off}",
      )
    BadChecksum(off, declared, computed) =>
      logger.write_string(
        "chunk at offset \{off} declares CRC \{hex32(declared)} but its bytes hash to \{hex32(computed)}",
      )
    TiffNotByteExact(ifd0, len, rebuilt) =>
      logger.write_string(
        "refusing to rewrite this bare TIFF: its IFD0 sits at offset \{ifd0}, and the file's \{len} byte(s) are not what the metadata model rebuilds (\{rebuilt} byte(s)); the difference is bytes the model does not hold, and writing would drop them",
      )
    UnknownFormat(off) =>
      logger.write_string(
        "none of the JPEG, PNG or TIFF magics is at offset \{off}; the container cannot be identified",
      )
  }
}

///|
pub extend MetaError with @debug.Debug::{to_repr}

///|
pub extend MetaError with Show::{to_string, output}

///|
fn tag_hex(tag : Int) -> String {
  "0x" +
  ((tag >> 8) & 0xff).to_byte().to_hex() +
  (tag & 0xff).to_byte().to_hex()
}

///|
/// 32 位无符号数写成 `0x........`。CRC 会超过 31 位，所以一路用 Int64。
fn hex32(v : Int64) -> String {
  let b0 = ((v >> 24) & 255L).to_byte().to_hex()
  let b1 = ((v >> 16) & 255L).to_byte().to_hex()
  let b2 = ((v >> 8) & 255L).to_byte().to_hex()
  let b3 = (v & 255L).to_byte().to_hex()
  "0x" + b0 + b1 + b2 + b3
}
