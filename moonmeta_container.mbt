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
/// JPEG / PNG：只换掉装元数据的那一段，其余字节原样搬回去。
/// 裸 TIFF：整份文件都由 IR 重新产出，所以先要过 `check_tiff_rewrite`
/// 那道"能不能原样复现"的判据。
pub fn redact_any(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => jpeg_redact(data, p)
    Some(Png) => png_redact(data, p)
    Some(Tiff) => {
      // JPEG/PNG 只换掉装元数据的那一段，裸 TIFF 没有"那一段"可以换：
      // 整份文件都要由 IR 重建，而 IR 里只有元数据。判据见 check_tiff_rewrite。
      check_tiff_rewrite(data, decode_tiff(data))
      redact_tiff(data, p)
    }
  }
}

///|
/// 裸 TIFF 能否安全重写：**只有**把解码结果原样再编一次、字节与输入完全相同
/// 时才算能。不相同就说明文件里有一段我们的模型装不下的东西——绝大多数情况
/// 就是 IFD 之间和之后的像素数据，写回去会得到一个"元数据干净但图像打不开"
/// 的文件。那比不脱敏更糟：用户以为处理过了。
///
/// 真实照片几乎都过不了这一关（相机把 IFD0 放在图像数据之后），所以这条
/// 判据的实际作用是划出边界而不是放行：裸 TIFF 的读、审都支持，写不支持。
fn check_tiff_rewrite(data : Bytes, block : TiffBlock) -> Unit raise MetaError {
  let rebuilt = encode_tiff(block)
  if rebuilt != data {
    raise TiffNotByteExact(
      u32_at(data, 4, block.little),
      data.length(),
      rebuilt.length(),
    )
  }
}

///|
/// 一次 `strip` 摘掉了什么。
///
/// 两个 Bool 不能并成一个：只说"有东西被摘了"，就看不出 XMP 还在不在，
/// 而这正是"摘干净"与"看着摘干净"的区别。
pub(all) struct Strip {
  had_exif : Bool
  dropped_xmp : Bool
} derive(Debug, Eq)

///|
pub extend Strip with Eq::{not_equal, equal}

///|
pub extend Strip with @debug.Debug::{to_repr}

///|
/// 把元数据整段摘掉（不是逐条目删），并报告原本有没有。
///
/// 与 `redact_any` 的区别值得留在 API 里：`strip` 之后文件里不会再有
/// 任何 EXIF 结构，也不会有 XMP 包；而 `redact` 之后仍是一份合法但精简过的 EXIF。
pub fn strip_any(data : Bytes) -> (Bytes, Strip) raise MetaError {
  match sniff(data) {
    None => raise UnknownFormat(0)
    Some(Jpeg) => {
      let (no_exif, had) = jpeg_remove_exif(data)
      let (out, dropped) = jpeg_drop_xmp(no_exif)
      (out, { had_exif: had, dropped_xmp: dropped, })
    }
    Some(Png) => {
      let (no_exif, had) = png_remove_exif(data)
      let (out, dropped) = png_drop_xmp(no_exif)
      (out, { had_exif: had, dropped_xmp: dropped, })
    }
    Some(Tiff) => {
      // 裸 TIFF 没有"容器"可拆：只能把每一类都清掉，剩下一个合法的空壳。
      // 空壳装不下像素数据，所以重写前要和 redact_any 过同一道判据。
      let block = decode_tiff(data)
      let left = block.ifd0.length() +
        block.exif.length() +
        block.gps.length() +
        block.interop.length()
      if left == 0 && !block.has_ifd1 {
        (data, { had_exif: false, dropped_xmp: false, })
      } else {
        check_tiff_rewrite(data, block)
        // 载体条目（XMP / Photoshop / IPTC-NAA）就在 IFD0 里，
        // 清空目录时一起没了，所以 dropped_xmp 只需要看有没有 0x02bc。
        let had_carrier = find_entry(block.ifd0, 0x02bc) != None
        let emptied : TiffBlock = {
          little: block.little,
          ifd0: [],
          exif: [],
          gps: [],
          interop: [],
          has_ifd1: false,
        }
        (encode_tiff(emptied), { had_exif: true, dropped_xmp: had_carrier, })
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
