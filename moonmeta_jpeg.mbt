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
/// 分块存放的扩展 XMP 的头。同一份文档可能被切成好几段，每段都顶这个标识。
///
/// 只认标准那一种，等于让另一份副本安安静静地留在文件里，
/// 而报告上说"XMP 已删"。
let xmp_ext_head : Array[Byte] = [
  b'h', b't', b't', b'p', b':', b'/', b'/', b'n', b's', b'.', b'a', b'd', b'o', b'b',
  b'e', b'.', b'c', b'o', b'm', b'/', b'x', b'm', b'p', b'/', b'e', b'x', b't', b'e',
  b'n', b's', b'i', b'o', b'n', b'/',
]

///|
/// APP13 里 Photoshop 资源块的头（含结尾那个 NUL）。
///
/// IPTC-IIM 记录（署名、版权、联系人）就住在这包里，而它和 IFD0 里的
/// `0x83bb` 是同一类东西：整包载体，逐条判断不了，只能整包丢。
let iptc_head : Array[Byte] = [
  b'P', b'h', b'o', b't', b'o', b's', b'h', b'o', b'p', b' ', b'3', b'.', b'0', b'\x00',
]

///|
/// 公认"不装元数据"的几种载荷前缀：JFIF/JFXX 的应用标识、ICC 色彩描述子、
/// Adobe 的量化与色彩变换。它们不出声。
///
/// 这份名单是逐条定的，不按段号整段放行：APP0 里也能塞一份真 EXIF，
/// APP2 里除了 ICC 还有 MPF（缩略图链，常常自带坐标）。
let structural_heads : Array[Array[Byte]] = [
  [b'J', b'F', b'I', b'F', b'\x00'],
  [b'J', b'F', b'X', b'X', b'\x00'],
  [b'I', b'C', b'C', b'_', b'P', b'R', b'O', b'F', b'I', b'L', b'E', b'\x00'],
  [b'A', b'd', b'o', b'b', b'e', b'\x00'],
  [b'A', b'd', b'o', b'b', b'e', b'_', b'C', b'M', b'\x00'],
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
/// `exif` 是 APP1 里那段 TIFF 块的 `[起, 止)`；`xmp` 是每一段 APP1/XMP 的位置。
/// 记下来是为了如实交代：XMP 里常是同一批事实的第二份副本，
/// 逐条清单看不见它，脱敏工具最怕让人以为已经删干净了。
pub(all) struct JpegMap {
  segments : Array[JpegSegment]
  exif : (Int, Int)?
  has_xmp : Bool
  /// 每一段 APP1/XMP 的 `[起, 止)`，含段码与长度域。
  ///
  /// 走查时才知道确切的边界（段边界之前可能有任意多个 0xff 填充），
  /// 所以在这里记下来，删除时不再重新推导一遍。
  /// `has_xmp` 与它是同一件事的两种问法：`has_xmp == !xmp.is_empty()`。
  /// 分块扩展 XMP 也算在这一项里：那是同一份文档的另一写法，不是另一件事。
  xmp : Array[(Int, Int)]
  /// APP13 里 Photoshop 资源包（IPTC-IIM 住在里面）的段区间。
  ///
  /// 和 XMP 一样是"整包"，条目清单里永远看不见它，所以同样要单独记一项。
  iptc : Array[(Int, Int)]
  has_iptc : Bool
  /// 我们既没读、也不会删的段：逐段点名，不替它编一句"应该没事"。
  ///
  /// 判据是载荷前缀，不是段号——见 `structural_heads` 那一段的理由。
  /// 这一项为空的 JPEG，才是"除 EXIF/XMP/IPTC 之外没有别的地方藏东西"。
  unread : Array[JpegSegment]
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
  let xmp_spans : Array[(Int, Int)] = []
  let mut has_iptc = false
  let iptc_spans : Array[(Int, Int)] = []
  let unread : Array[JpegSegment] = []
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
        let payload = k + 3
        let is_xmp = marker == 0xe1 &&
          (
            starts_with(data, payload, xmp_head) ||
            starts_with(data, payload, xmp_ext_head)
          )
        let is_iptc = marker == 0xed && starts_with(data, payload, iptc_head)
        let unreadable = may_hold_metadata(marker) &&
          !structural_payload(data, payload)
        if marker == 0xe1 && starts_with(data, payload, exif_head) {
          match exif {
            Some(_) => raise ExtraMetadata(payload)
            None => exif = Some((payload + 6, p + span))
          }
        } else if is_xmp {
          has_xmp = true
          xmp_spans.push((p, p + span))
        } else if is_iptc {
          has_iptc = true
          iptc_spans.push((p, p + span))
        } else if unreadable {
          unread.push({ marker, offset: p, length: span, })
        }
        segments.push({ marker, offset: p, length: span, })
        p = p + span
      }
    }
  }
  check_no_metadata_after(data, scan_end)
  {
    segments,
    exif,
    has_xmp,
    xmp: xmp_spans,
    has_iptc,
    iptc: iptc_spans,
    unread,
  }
}

///|
/// 可能藏元数据的段号：厂商应用段 APP0–APP15 与注释段 COM。
///
/// 其余段码（SOF/DHT/DQT/SOS/…）是编码结构与参数，不在"可能藏东西"的范围内。
fn may_hold_metadata(marker : Int) -> Bool {
  (marker >= 0xe0 && marker <= 0xef) || marker == 0xfe
}

///|
/// 载荷前缀在"公认不装元数据"那份名单上。名单按前缀逐条定，见 `structural_heads`。
fn structural_payload(data : Bytes, at : Int) -> Bool {
  for head in structural_heads {
    if starts_with(data, at, head) {
      return true
    }
  }
  false
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
  for head in [exif_head, xmp_head, xmp_ext_head, iptc_head] {
    match find_bytes(data, from, to, head) {
      Some(off) => raise ExtraMetadata(off)
      None => ()
    }
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
/// 补集搬运：把这些段区间之外的字节原样搬过去。
///
/// 之所以是"搬"而不是"重建文件"：压缩流、量化表、注释段一概不重新编码，
/// 所以像素不可能被动到。
fn drop_spans(data : Bytes, spans : Array[(Int, Int)]) -> Bytes {
  let body = data.to_array()
  let out : Array[Byte] = []
  let mut cursor = 0
  for (s, e) in spans {
    push_all(out, body, cursor, s)
    cursor = e
  }
  push_all(out, body, cursor, body.length())
  Bytes::from_array(out)
}

///|
/// 整段摘掉 APP1/XMP，并报告"原本确实有一段"。
///
/// 为什么必须动这一段：XMP 里是同一批事实的第二份副本——真实语料里
/// `exif:DateTimeOriginal`、`tiff:Make/Model`、`dc:creator`、`aux:SerialNumber`
/// 都出现过。EXIF 删干净、XMP 原样留着，报告上一切正常，实际什么都没脱。
pub fn jpeg_drop_xmp(data : Bytes) -> (Bytes, Bool) raise MetaError {
  let spans = jpeg_inspect(data).xmp
  if spans.is_empty() {
    (data, false)
  } else {
    (drop_spans(data, spans), true)
  }
}

///|
/// 整段摘掉 APP13 的 Photoshop 资源包（IPTC-IIM 住在里面），并报告"原本确实有一段"。
///
/// 和 XMP 同一个道理，也同一条待遇：整包判断不了里面哪条敏不敏感，
/// 但"留着整包"一定比"整包丢掉"更糟——IFD0 里的 `0x83bb`/`0x02bd` 早就是整条丢的，
/// 只差 JPEG 这一份副本没说。不认它，`strip` 那句"摘干净"就是假的。
///
/// 只动带 `Photoshop 3.0\0` 头的那几段：APP13 里还有 Adobe 的色彩管理包，
/// 删它会把颜色改掉，而它一条隐私都不装。
pub fn jpeg_drop_iptc(data : Bytes) -> (Bytes, Bool) raise MetaError {
  let spans = jpeg_inspect(data).iptc
  if spans.is_empty() {
    (data, false)
  } else {
    (drop_spans(data, spans), true)
  }
}

///|
/// 解析 → 按策略删 → 回写，一步到位。没有 EXIF 的文件原样退回。
pub fn jpeg_redact(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  let map = jpeg_inspect(data)
  let (out, report) = match map.exif {
    None =>
      (
        data,
        {
          removed: [],
          dropped_thumbnail: false,
          dropped_xmp: false,
          dropped_iptc: false,
        },
      )
    Some((s, e)) => {
      let block = decode_tiff(slice_bytes(data, s, e))
      let (kept, report) = block.redact(p)
      // 一条没删就不重写这个段：我们的编码器按自己的布局排偏移，
      // 和相机原来的字节布局不保证相同（实测重编码会长 4 个字节）。
      // 空策略必须是恒等，不能顺手把文件规范化一遍。
      if report.removed.is_empty() && !report.dropped_thumbnail {
        (data, report)
      } else {
        (jpeg_replace_exif(data, encode_tiff(kept)), report)
      }
    }
  }
  // 第二趟、第三趟都重新走查一遍，不沿用上一趟的偏移：EXIF 段的长度已经变了，
  // 记在旧偏移上的 XMP 段位置这时候是错的；摘掉 XMP 之后 IPTC 的偏移又错了一次。
  if !p.covers(Carrier) {
    (out, report)
  } else {
    let (out2, dropped) = jpeg_drop_xmp(out)
    let (out3, dropped_iptc) = jpeg_drop_iptc(out2)
    (out3, { ..report, dropped_xmp: dropped, dropped_iptc, })
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
    head = head + " ; 另含 XMP 包 \{self.xmp.length()} 段"
  }
  if self.has_iptc {
    head = head + " ; 另含 IPTC/Photoshop 包 \{self.iptc.length()} 段"
  }
  if !self.unread.is_empty() {
    let names = self.unread.map(s => "\{s.name()}@\{s.offset}").join(" ")
    head + " ; 未解析段 \{self.unread.length()} 段：\{names}"
  } else {
    head
  }
}
