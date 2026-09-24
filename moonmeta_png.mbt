// 容器层 · PNG。
//
// PNG 的 EXIF 住在 `eXIf` 块里（注册过的扩展块），载荷就是一整段 TIFF 块，
// 没有 JPEG 那个 "Exif\0\0" 头。XMP 则住在 `iTXt`/`tEXt` 里，
// 关键字是 "XML:com.adobe.xmp"。
//
// 每个 PNG 块自带 CRC，校验和不对的块会被解码器整块拒收，所以回写必须重算。
// 校验和只在动过的块上验：一个跟元数据无关的坏 `tEXt` 不该让人删不掉坐标，
// 但元数据块自己 CRC 对不上，就是必须停下来的事。

///|
let png_sig : Array[Byte] = [
  b'\x89', b'P', b'N', b'G', b'\r', b'\n', b'\x1a', b'\n',
]

///|
let chunk_exif : Array[Byte] = [b'e', b'X', b'I', b'f']

///|
let chunk_iext : Array[Byte] = [b'i', b'T', b'X', b't']

///|
let chunk_text : Array[Byte] = [b't', b'E', b'X', b't']

///|
let chunk_iend : Array[Byte] = [b'I', b'E', b'N', b'D']

///|
/// iTXt/tEXt 里带 XMP 的那个关键字。
let xmp_keyword : Array[Byte] = [
  b'X', b'M', b'L', b':', b'c', b'o', b'm', b'.', b'a', b'd', b'o', b'b', b'e', b'.',
  b'x', b'm', b'p',
]

///|
/// 一个 PNG 块：类型、起始偏移、载荷字节数（不含长度域、类型和校验和）。
pub(all) struct PngChunk {
  kind : String
  offset : Int
  length : Int
} derive(Debug, Eq)

///|
pub extend PngChunk with Eq::{not_equal, equal}

///|
pub extend PngChunk with @debug.Debug::{to_repr}

///|
/// 块表。`exif` 是 `eXIf` 块载荷的 `[起, 止)`，也就是那段 TIFF 块。
pub(all) struct PngMap {
  chunks : Array[PngChunk]
  exif : (Int, Int)?
  has_xmp : Bool
} derive(Debug, Eq)

///|
pub extend PngMap with Eq::{not_equal, equal}

///|
pub extend PngMap with @debug.Debug::{to_repr}

///|
/// 走一遍 PNG 的块表，顺手验一下 `eXIf` 的校验和。
pub fn png_inspect(data : Bytes) -> PngMap raise MetaError {
  let n = data.length()
  for i = 0; i < 8; i = i + 1 {
    if byte_at(data, i) != png_sig[i] {
      raise NotPng(i)
    }
  }
  let chunks : Array[PngChunk] = []
  let mut exif : (Int, Int)? = None
  let mut has_xmp = false
  let mut p = 8
  let mut done = false
  while p < n && !done {
    let here = p
    // 长度域(4) + 类型(4) + 载荷 + 校验和(4)
    let avail = n - p - 12
    if avail < 0 {
      raise TruncatedAt(here)
    }
    let declared = u32_at(data, p, false)
    if declared > 2147483647L || declared.to_int() > avail {
      raise SegmentTooLarge(here, declared.to_int(), avail)
    }
    let len = declared.to_int()
    let body = p + 4
    let end = body + len + 8
    if kind_is(data, body, chunk_exif) {
      verify_crc(data, here, body, len)
      match exif {
        Some(_) => raise ExtraMetadata(here)
        None => exif = Some((body + 4, body + 4 + len))
      }
    } else if has_xmp_keyword(data, body, len) {
      has_xmp = true
    }
    chunks.push({ kind: chunk_kind(data, body), offset: here, length: len, })
    if kind_is(data, body, chunk_iend) {
      done = true
    }
    p = end
  }
  { chunks, exif, has_xmp, }
}

///|
fn kind_is(data : Bytes, at : Int, kind : Array[Byte]) -> Bool {
  starts_with(data, at, kind)
}

///|
/// `iTXt`/`tEXt` 里带 XMP 关键字的那一种。只在当前块的载荷里找。
fn has_xmp_keyword(data : Bytes, body : Int, len : Int) -> Bool {
  let text = kind_is(data, body, chunk_iext) || kind_is(data, body, chunk_text)
  text && find_bytes(data, body + 4, body + 4 + len, xmp_keyword) != None
}

///|
fn chunk_kind(data : Bytes, at : Int) -> String raise MetaError {
  let c0 = byte_at(data, at).to_int().unsafe_to_char()
  let c1 = byte_at(data, at + 1).to_int().unsafe_to_char()
  let c2 = byte_at(data, at + 2).to_int().unsafe_to_char()
  let c3 = byte_at(data, at + 3).to_int().unsafe_to_char()
  "\{c0}\{c1}\{c2}\{c3}"
}

///|
/// `eXIf` 块的 CRC 必须和字节对得上。
///
/// 对不上就不回写：在一段已经坏了的元数据上报告"脱敏成功"，
/// 等于把自己的正确性建立在一个没人能打开的文件上。
fn verify_crc(
  data : Bytes,
  here : Int,
  body : Int,
  len : Int,
) -> Unit raise MetaError {
  let crc_at = body + 4 + len
  let want = u32_at(data, crc_at, false)
  let got = crc32(slice_bytes(data, body, crc_at))
  if want != got {
    raise BadChecksum(here, want, got)
  }
}

///|
/// PNG 用的 CRC-32（IEEE 802.3 反射式，初值与末值取反）。
///
/// 结果会超过 31 位，所以一路带 Int64。
pub fn crc32(data : Bytes) -> Int64 {
  let mut c = 4294967295L
  for b in data {
    c = c ^ b.to_int().to_int64()
    let mut i = 0
    while i < 8 {
      let odd = (c & 1L) == 1L
      c = c >> 1
      if odd {
        c = c ^ 3988292384L
      }
      i = i + 1
    }
  }
  c ^ 4294967295L
}

///|
/// 取出 `eXIf` 块里的 TIFF 块。
pub fn png_exif(data : Bytes) -> Bytes? raise MetaError {
  match png_inspect(data).exif {
    None => None
    Some((s, e)) => Some(slice_bytes(data, s, e))
  }
}

///|
/// 读出 PNG 里的 EXIF。没有就是 `None`。
pub fn png_decode(data : Bytes) -> TiffBlock? raise MetaError {
  match png_exif(data) {
    None => None
    Some(tiff) => Some(decode_tiff(tiff))
  }
}

///|
/// 替换 `eXIf` 块；原本没有就插在 `IHDR` 之后。校验和重算。
pub fn png_replace_exif(data : Bytes, tiff : Bytes) -> Bytes raise MetaError {
  let map = png_inspect(data)
  let seg = exif_chunk(tiff)
  let body = data.to_array()
  let (from, to) = replace_range(map)
  let out : Array[Byte] = []
  push_all(out, body, 0, from)
  push_all(out, seg, 0, seg.length())
  push_all(out, body, to, body.length())
  Bytes::from_array(out)
}

///|
/// 要被替换掉的字节区间：`eXIf` 整块，含长度域与校验和。
/// 没有该块时，退回插入点上的空区间。
fn replace_range(map : PngMap) -> (Int, Int) {
  match map.exif {
    Some((s, e)) => (s - 8, e + 4)
    None => {
      let at = after_ihdr(map)
      (at, at)
    }
  }
}

///|
/// 没有 `eXIf` 时新块的落点：`IHDR` 之后。规范只要求它在 `IDAT` 之前，
/// 紧跟 `IHDR` 是最稳的位置。
fn after_ihdr(map : PngMap) -> Int {
  match map.chunks.get(0) {
    Some(c) => c.offset + 12 + c.length
    None => 8
  }
}

///|
/// 摘掉 `eXIf` 块，并报告原本有没有。
pub fn png_remove_exif(data : Bytes) -> (Bytes, Bool) raise MetaError {
  let map = png_inspect(data)
  match map.exif {
    None => (data, false)
    Some((s, e)) => {
      let body = data.to_array()
      let out : Array[Byte] = []
      push_all(out, body, 0, s - 8)
      push_all(out, body, e + 4, body.length())
      (Bytes::from_array(out), true)
    }
  }
}

///|
/// 解析 → 按策略删 → 回写。
pub fn png_redact(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  let map = png_inspect(data)
  match map.exif {
    None => (data, { removed: [], dropped_thumbnail: false, })
    Some((s, e)) => {
      let block = decode_tiff(slice_bytes(data, s, e))
      let (kept, report) = block.redact(p)
      (png_replace_exif(data, encode_tiff(kept)), report)
    }
  }
}

///|
/// 造一个 `eXIf` 块：长度(4) + 类型(4) + 载荷 + 校验和(4)。
fn exif_chunk(tiff : Bytes) -> Array[Byte] {
  let out : Array[Byte] = []
  put_u32(out, tiff.length().to_int64(), false)
  push_all(out, chunk_exif, 0, 4)
  let body = tiff.to_array()
  push_all(out, body, 0, body.length())
  let head : Array[Byte] = []
  push_all(head, out, 4, out.length())
  let crc = crc32(Bytes::from_array(head))
  put_u32(out, crc, false)
  out
}

///|
/// 一行块表，给 CLI 的审计输出用。
pub fn PngMap::describe(self : PngMap) -> String {
  let mut head = "PNG"
  for c in self.chunks {
    head = head + " \{c.kind}@\{c.offset}(\{c.length}B)"
  }
  if self.has_xmp {
    head + " ; 另含 XMP，本版本不解析也不删除"
  } else {
    head
  }
}
