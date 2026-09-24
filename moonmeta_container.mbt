// 容器分派：先认文件是什么，再决定用哪一层。
//
// 只认魔数，不认扩展名。一个叫 .jpg 的 PNG 会被当成 PNG 处理——
// 元数据的位置由文件内容决定，由文件名决定只会出错。

///|
pub(all) enum Kind {
  Jpeg
  Png
  Tiff
} derive(Debug, Eq)

///|
pub extend Kind with Eq::{not_equal, equal}

///|
pub extend Kind with @debug.Debug::{to_repr}

///|
pub impl Show for Kind with fn output(self : Kind, logger) {
  match self {
    Jpeg => logger.write("jpeg")
    Png => logger.write("png")
    Tiff => logger.write("tiff")
  }
}

///|
pub extend Kind with Show::{to_string, output}

///|
let jpeg_sig : Array[Byte] = [b'\xff', b'\xd8']

///|
/// `II` + 42（低位在前）。
let tiff_le_sig : Array[Byte] = [b'I', b'I', b'*', b'\x00']

///|
/// `MM` + 42（高位在前）。
let tiff_be_sig : Array[Byte] = [b'M', b'M', b'\x00', b'*']

///|
/// 只看开头几个字节就判定容器。认不出来返回 `None`，不抛错——
/// "这是什么格式"是一个可以回答"不知道"的问题。
pub fn sniff(data : Bytes) -> Kind? {
  if starts_with(data, 0, png_sig) {
    Some(Png)
  } else if starts_with(data, 0, jpeg_sig) {
    Some(Jpeg)
  } else if tiff_magic(data) {
    Some(Tiff)
  } else {
    None
  }
}

///|
fn tiff_magic(data : Bytes) -> Bool {
  starts_with(data, 0, tiff_le_sig) || starts_with(data, 0, tiff_be_sig)
}

///|
/// 读出元数据，顺带告诉调用方文件是什么容器。
pub fn decode_any(data : Bytes) -> (Kind, TiffBlock?) raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => (Jpeg, jpeg_decode(data))
    Some(Png) => (Png, png_decode(data))
    Some(Tiff) => (Tiff, Some(decode_tiff(data)))
  }
}

///|
/// 解析 → 按策略删 → 原位回写，容器自适应。
///
/// 三个容器的语义是一致的：只动装元数据的那一段，其余字节原样搬回去。
pub fn redact_any(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => jpeg_redact(data, p)
    Some(Png) => png_redact(data, p)
    Some(Tiff) => redact_tiff(data, p)
  }
}

///|
/// 把元数据整段摘掉（不是逐条目删），并报告原本有没有。
///
/// 与 `redact_any` 的区别值得留在 API 里：`strip` 之后文件里不会再有
/// 任何 EXIF 结构，而 `redact` 之后仍是一份合法但精简过的 EXIF。
pub fn strip_any(data : Bytes) -> (Bytes, Bool) raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => jpeg_remove_exif(data)
    Some(Png) => png_remove_exif(data)
    Some(Tiff) => {
      // 裸 TIFF 没有"容器"可拆：只能把每一类都清掉，剩下一个合法的空壳。
      let block = decode_tiff(data)
      let left = block.ifd0.length() + block.exif.length() + block.gps.length()
      if left == 0 && !block.has_ifd1 {
        (data, false)
      } else {
        let emptied : TiffBlock = {
          little: block.little,
          ifd0: [],
          exif: [],
          gps: [],
          has_ifd1: false,
        }
        (encode_tiff(emptied), true)
      }
    }
  }
}

///|
/// 一行容器概览，给 CLI 的审计输出用。
pub fn describe_container(data : Bytes) -> String raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => jpeg_inspect(data).describe()
    Some(Png) => png_inspect(data).describe()
    Some(Tiff) =>
      "TIFF 裸块 \{data.length()}B, \{decode_tiff(data).ifd0.length()} 条 IFD0 条目"
  }
}
