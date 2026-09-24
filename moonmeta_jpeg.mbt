// 容器层 · JPEG。
//
// EXIF 住在 APP1 段里，前面顶着 6 字节标识 "Exif\0\0"。麻烦在于 XMP 也住 APP1，
// 只按段号找"第一个 APP1"就把别人的 XMP 一起毁了——所以这里按载荷前缀认人。
//
// 走查在第一个 SOS（熵编码数据起点）处停下：元数据按规范只可能在图像数据之前，
// 而一旦踏进压缩流就没有可靠的方式走出来。停下来之后会对剩余字节做一次
// 元数据标识扫描：如果那里还有一份，宁可报错也不假装删干净了。

///|
/// `FF E1` + 2 字节长度域 + 6 字节标识：TIFF 块之前被占掉的字节数。
let app1_overhead : Int = 10

///|
/// APP1 里标识"这一段是 EXIF"的头。
let exif_head : Array[Byte] = [b'E', b'x', b'i', b'f', b'\x00', b'\x00']

///|
/// APP1 里标识"这一段是 XMP"的头。
let xmp_head : Array[Byte] = [
  b'h', b't', b't', b'p', b':', b'/', b'/', b'n', b's', b'.', b'a', b'd', b'o', b'b',
  b'e', b'.', b'c', b'o', b'm', b'/', b'x', b'a', b'p', b'/', b'1', b'.', b'0', b'/',
]

///|
/// JPEG 里的一个段。`offset` 是段首那个 0xff 的位置，`length` 是整段的字节数，
/// 所以段本身是 `[offset, offset+length)`。
pub(all) struct JpegSegment {
  marker : Int
  offset : Int
  length : Int
} derive(Debug, Eq)

///|
pub extend JpegSegment with Eq::{not_equal, equal}

///|
pub extend JpegSegment with @debug.Debug::{to_repr}

///|
/// 段表。
///
/// `exif` 是 APP1 里那段 TIFF 块的 `[起, 止)`；`has_xmp` 是"这个文件还带着
/// XMP，本版本不碰它"的诚实交代——脱敏工具最怕让人以为已经删干净了。
pub(all) struct JpegMap {
  segments : Array[JpegSegment]
  exif : (Int, Int)?
  has_xmp : Bool
} derive(Debug, Eq)

///|
pub extend JpegMap with Eq::{not_equal, equal}

///|
pub extend JpegMap with @debug.Debug::{to_repr}

///|
/// 走一遍 JPEG 的段表：找到 EXIF 的落点，顺便看清还有没有别的东西。
pub fn jpeg_inspect(data : Bytes) -> JpegMap raise MetaError {
  let n = data.length()
  let bad_start = n < 2 ||
    byte_at(data, 0).to_int() != 0xff ||
    byte_at(data, 1).to_int() != 0xd8
  if bad_start {
    raise NotJpeg(0)
  }
  let segments : Array[JpegSegment] = [{ marker: 0xd8, offset: 0, length: 2, }]
  let mut exif : (Int, Int)? = None
  let mut has_xmp = false
  let mut p = 2
  let mut scan_end = n
  let mut done = false
  while p < n && !done {
    if byte_at(data, p).to_int() != 0xff {
      raise TruncatedAt(p)
    }
    // 段边界之间可以塞任意多个 0xff 填充，跳过它们才看得到真正的段码
    let mut k = p + 1
    while k < n && byte_at(data, k).to_int() == 0xff {
      k = k + 1
    }
    if k >= n {
      raise TruncatedAt(k)
    }
    let marker = byte_at(data, k).to_int()
    if marker == 0xd9 {
      // EOI：整个文件到此为止
      segments.push({ marker, offset: p, length: k + 1 - p, })
      scan_end = k + 1
      done = true
    } else if standalone_marker(marker) {
      segments.push({ marker, offset: p, length: k + 1 - p, })
      p = k + 1
    } else {
      // 变长段：段码之后是 2 字节大端长度，长度域把自己算在内
      let seg_len = u16_at(data, k + 1, false)
      let left = n - k - 2
      if seg_len < 2 || seg_len - 2 > left {
        raise SegmentTooLarge(p, seg_len, left)
      }
      let span = k - p + 1 + seg_len
      if marker == 0xda {
        // SOS：段头之后就是压缩流，元数据走查到此为止
        segments.push({ marker, offset: p, length: span, })
        scan_end = p + span
        done = true
      } else {
        if marker == 0xe1 {
          let payload = k + 3
          if starts_with(data, payload, exif_head) {
            match exif {
              Some(_) => raise ExtraMetadata(payload)
              None => exif = Some((payload + 6, p + span))
            }
          } else if starts_with(data, payload, xmp_head) {
            has_xmp = true
          }
        }
        segments.push({ marker, offset: p, length: span, })
        p = p + span
      }
    }
  }
  check_no_metadata_after(data, scan_end)
  { segments, exif, has_xmp, }
}

///|
/// 没有长度域、也不带载荷的段码。
fn standalone_marker(marker : Int) -> Bool {
  marker == 0x01 ||
  marker == 0xd8 ||
  (marker >= 0xd0 && marker <= 0xd7) ||
  (marker >= 0x08 && marker <= 0x0f)
}

///|
/// 压缩流之后不许再藏元数据：只处理第一份就是假脱敏。
fn check_no_metadata_after(data : Bytes, from : Int) -> Unit raise MetaError {
  let to = data.length()
  match find_bytes(data, from, to, exif_head) {
    Some(off) => raise ExtraMetadata(off)
    None => ()
  }
  match find_bytes(data, from, to, xmp_head) {
    Some(off) => raise ExtraMetadata(off)
    None => ()
  }
}

///|
/// 取出 APP1 里的 TIFF 块。文件没有 EXIF 是 `None`，不是错误。
pub fn jpeg_exif(data : Bytes) -> Bytes? raise MetaError {
  match jpeg_inspect(data).exif {
    None => None
    Some((s, e)) => Some(slice_bytes(data, s, e))
  }
}

///|
/// 读出 JPEG 里的 EXIF。没有 EXIF 时返回 `None`。
pub fn jpeg_decode(data : Bytes) -> TiffBlock? raise MetaError {
  match jpeg_exif(data) {
    None => None
    Some(tiff) => Some(decode_tiff(tiff))
  }
}

///|
/// 用新的 TIFF 块替换 APP1；原本没有 EXIF 就插在 SOI 之后。
/// 其余字节——XMP、注释、每一个与元数据无关的段——按原样搬过去。
pub fn jpeg_replace_exif(data : Bytes, tiff : Bytes) -> Bytes raise MetaError {
  let map = jpeg_inspect(data)
  let body = data.to_array()
  let (from, to) = match map.exif {
    Some((s, e)) => (s - app1_overhead, e)
    None => {
      let at = insert_point(map)
      (at, at)
    }
  }
  let seg = app1_segment(tiff, from)
  let out : Array[Byte] = []
  push_all(out, body, 0, from)
  push_all(out, seg, 0, seg.length())
  push_all(out, body, to, body.length())
  Bytes::from_array(out)
}

///|
/// 原本没有 EXIF 时的插入点：APP0 之后，其次才紧跟 SOI。
///
/// JFIF 要求 APP0 是 SOI 之后的第一段，把 EXIF 插到它前面会让
/// 一部分读取器直接不认这个文件——写出去的东西得让别人打得开。
fn insert_point(map : JpegMap) -> Int {
  match map.segments.get(1) {
    Some(s) if s.marker == 0xe0 => s.offset + s.length
    _ => 2
  }
}

///|
/// 整段摘掉 APP1/EXIF，并报告"原本确实有一段"。
///
/// 那个 Bool 不是装饰：调用方要能区分"删掉了"和"本来就没有"。
/// 把"本来就没有"说成"已清除"的工具没人敢信。
pub fn jpeg_remove_exif(data : Bytes) -> (Bytes, Bool) raise MetaError {
  let map = jpeg_inspect(data)
  match map.exif {
    None => (data, false)
    Some((s, e)) => {
      let body = data.to_array()
      let out : Array[Byte] = []
      push_all(out, body, 0, s - app1_overhead)
      push_all(out, body, e, body.length())
      (Bytes::from_array(out), true)
    }
  }
}

///|
/// 解析 → 按策略删 → 回写，一步到位。没有 EXIF 的文件原样退回。
pub fn jpeg_redact(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  let map = jpeg_inspect(data)
  match map.exif {
    None => (data, { removed: [], dropped_thumbnail: false, })
    Some((s, e)) => {
      let block = decode_tiff(slice_bytes(data, s, e))
      let (kept, report) = block.redact(p)
      let tiff = encode_tiff(kept)
      (jpeg_replace_exif(data, tiff), report)
    }
  }
}

///|
/// 造一个 APP1/EXIF 段：`FF E1` + 长度 + 标识 + TIFF 块。
///
/// 段长字段只有 16 位，装不下就直接拒绝。写一个截断的长度域，
/// 等于交出一个别人打不开却说自己合法的文件。
fn app1_segment(tiff : Bytes, at : Int) -> Array[Byte] raise MetaError {
  let total = 2 + exif_head.length() + tiff.length()
  if total > 65535 {
    raise SegmentOverflow(at, 65535, total)
  }
  let out : Array[Byte] = [b'\xff', b'\xe1']
  out.push((total >> 8).to_byte())
  out.push((total & 0xff).to_byte())
  push_all(out, exif_head, 0, exif_head.length())
  let body = tiff.to_array()
  push_all(out, body, 0, body.length())
  out
}

// ---- 字节小工具 ----

///|
fn push_all(out : Array[Byte], src : Array[Byte], from : Int, to : Int) -> Unit {
  let mut i = from
  while i < to {
    out.push(src[i])
    i = i + 1
  }
}

///|
fn slice_bytes(data : Bytes, from : Int, to : Int) -> Bytes raise MetaError {
  let out : Array[Byte] = []
  let mut i = from
  while i < to {
    out.push(byte_at(data, i))
    i = i + 1
  }
  Bytes::from_array(out)
}

///|
fn starts_with(data : Bytes, at : Int, head : Array[Byte]) -> Bool {
  let n = head.length()
  if at < 0 || at + n > data.length() {
    false
  } else {
    let mut i = 0
    let mut same = true
    while i < n && same {
      same = match data.get(at + i) {
        Some(b) => b == head[i]
        None => false
      }
      i = i + 1
    }
    same
  }
}

///|
/// 在 `[from, to)` 里找子串。边界由调用方给：
/// "整份文件扫一遍"和"只扫这一段载荷"是两个不同的问题，答案差得很远。
fn find_bytes(data : Bytes, from : Int, to : Int, needle : Array[Byte]) -> Int? {
  let n = to
  let m = needle.length()
  if m == 0 || from + m > n {
    None
  } else {
    let mut p = from
    while p + m <= n {
      if starts_with(data, p, needle) {
        return Some(p)
      }
      p = p + 1
    }
    None
  }
}

///|
/// 段码的规范短名。认不出来就打编号，不猜。
pub fn marker_name(marker : Int) -> String {
  if marker >= 0xe0 && marker <= 0xef {
    "APP\{marker - 0xe0}"
  } else if marker >= 0xd0 && marker <= 0xd7 {
    "RST\{marker - 0xd0}"
  } else {
    match marker {
      0x01 => "TEM"
      0x08 => "JPG0"
      0xc0 => "SOF0"
      0xc1 => "SOF1"
      0xc2 => "SOF2"
      0xc3 => "SOF3"
      0xc4 => "DHT"
      0xc8 => "JPG"
      0xcc => "DAC"
      0xd8 => "SOI"
      0xd9 => "EOI"
      0xda => "SOS"
      0xdb => "DQT"
      0xdc => "DNL"
      0xdd => "DRI"
      0xfe => "COM"
      _ => "0x\{marker.to_byte().to_hex()}"
    }
  }
}

///|
pub fn JpegSegment::name(self : JpegSegment) -> String {
  marker_name(self.marker)
}

///|
/// 一行段表，给 CLI 的审计输出用。
pub fn JpegMap::describe(self : JpegMap) -> String {
  let mut head = "JPEG"
  for s in self.segments {
    head = head + " \{s.name()}@\{s.offset}"
  }
  if self.has_xmp {
    head + " ; 另含 XMP，本版本不解析也不删除"
  } else {
    head
  }
}
