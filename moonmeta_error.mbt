///|
/// 解析一个字节流时能出错的每一种方式。
///
/// 每条错误都带偏移：报"坏了"不够，要能指出坏在第几个字节，
/// 否则用户拿到的是一个无法追问的失败。
pub suberror MetaError {
  /// 字节流比声明的长度短：(需要, 实有)
  TooShort(Int, Int)
  /// TIFF 头不在给定偏移处：(偏移)
  BadTiffHeader(Int)
  /// 字节序标记既不是 "II" 也不是 "MM"：(偏移)
  BadByteOrder(Int)
  /// IFD 偏移指向块外：(偏移)
  IfdOffsetOutOfRange(Int64)
  /// 条目声明的字节数超过剩余空间：(tag, 声明, 可用)
  EntryTooLarge(Int, Int, Int)
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
} derive(Debug)

///|
pub impl Show for MetaError with fn output(self : MetaError, logger) {
  match self {
    TooShort(need, have) =>
      logger.write_string(
        "need \{need} byte(s) but the block holds only \{have}",
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
    EntryTooLarge(tag, declared, available) =>
      logger.write_string(
        "tag \{tag_hex(tag)} declares \{declared} byte(s), only \{available} left",
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
