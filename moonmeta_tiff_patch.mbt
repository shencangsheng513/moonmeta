// 原位改写：只删目录里的条目，一个字节都不搬。
//
// 重写路径（`moonmeta_encode.mbt`）把整份文件由 IR 重新产出，所以裸 TIFF
// 过不了 `check_tiff_rewrite`：IFD 之间和之后的像素数据、缩略图链、
// 我们模型装不下的任何字节都会丢。这条路反过来——**字节留在原地**，
// 只做单调收缩：
//
//   * 被删条目的外置值区间逐字节清零；
//   * 保留条目的 12 字节槽位往前搬，腾出来的表尾清零；
//   * 每表开头的条目数（u16）改小，表末尾的 next 指针跟着搬到新表尾。
//
// 这三步的先后是承重的，见 `apply_plan`：一个条目的值指针可以指到本表自己的
// 槽位区（畸形输入就是这么造的），清零必须先落，否则它会落在刚搬好的条目上。
//
// next 指针那 4 字节必须跟着计数走：读侧算它的位置用的是 `off + 2 + 12n`，
// 光把 n 改小，它就落在清零的腾空表尾上，读出来是 0——缩略图链不报错，
// 只是安静地没了。这条缺陷是单测逼出来的，语料门禁当时看不见（它比的是
// "点名区间之外别多动"，而 next 落在点名的表尾里）。旧位置那 4 字节原样
// 留着：计数改小之后它已在表外，任何读侧都到不了，动它反而多出一次写。
//
// 于是"写下去会丢字节"在构造上不可能发生：输出长度永远等于输入长度，
// 改动只落在报告点名的区间里。代价是两条必须出声的边界：缩略图链
// （IFD1 及其后继）只登记不修改，像素字节一个都不碰。
//
// 落笔之前先算一份"受保护区间"：文件头、每一张只登记的目录表及其
// 所有值区间、保留条目的值区间与槽位、表末尾的 next 指针、以及像素数据
// （由 StripOffsets/StripByteCounts、TileOffsets/TileByteCounts 配对得出）。
// 要写的地方与要清零的地方都不能和它们相交——相交就拒绝，而不是猜。
// 104 份陌生 Pillow TIFF 两条腿各跑一遍（2026-09-25），守卫这一族（Shared）
// 一份都没逼出来——它挡的是形状上的可能，两格单测用手工夹具各造了一遍"值
// 压在像素上"和"两个条目共用一段字节"。语料真逼出来的是另外三种：目录成环
// 2 份、像素声明读不懂 strict 腿 6 份 / strip 腿 26 份、类型码这一版不解码 1 份。

///|
/// 一张走过的目录表。
priv struct PTable {
  off : Int
  entries : Array[IfdEntry]
  /// 与 `entries` 一一对应。内联值（<=4 字节）的区间落在自己的槽位里。
  spans : Array[(Int, Int)]
  /// 表末尾 next 指针的值，0 = 没有后继。
  next : Int64
}

///|
/// 本库负责改写的那几张表，带着它的目录身份。
priv struct Mine {
  dir : Dir
  table : PTable
}

///|
/// 一个文件的目录图：可改写的四张 + 只登记不碰的后继链。
priv struct Patch {
  little : Bool
  mine : Array[Mine]
  /// IFD0 的后继链（缩略图目录）与每张表的后继。只登记为受保护区间。
  foreign : Array[PTable]
}

///|
/// 一张改写表的活儿。
priv struct Job {
  /// 表头偏移。
  off : Int
  /// 原表的条目数：搬完之后 [新终点, 旧终点) 要清零。
  old : Int
  /// 保留条目的下标，按原顺序。
  keep : Array[Int]
}

///|
priv enum GuardKind {
  Header
  ForeignTable
  ForeignValue
  KeptValue
  KeptSlot
  Pixel
} derive(Eq)

///|
/// 一段不许被碰的字节。`owner` 是它所在目录表的偏移，判豁免时用它认出
/// "同一张表自己那些已经搬走的槽位"。
priv struct Guard {
  from : Int
  to : Int
  owner : Int
  kind : GuardKind
}

///|
/// 一次原位改写的施工单。
priv struct Plan {
  removed : Array[Removed]
  jobs : Array[Job]
  /// 要逐字节清零的外置值区间。
  scrub : Array[(Int, Int)]
  little : Bool
  /// 真的被删掉的条目数。不能由 `removed` 的长度代替：`strip` 全删，
  /// 但报告只点名有敏感类别可归的那几条，剩下的删了也没名字可报。
  dropped : Int
  /// IFD0 里有没有 XMP 载体条目（0x02bc）。全删时它必然跟着没。
  carrier : Bool
}

///|
/// 删法：按策略删，还是像 `strip` 那样全删。
priv enum Drop {
  ByPolicy(Policy)
  All
}

///|
/// 按策略原位清目录，交出与重写路径同一份报告。
///
/// `removed` 必须与 `TiffBlock::findings` 逐条相同：两条路共用
/// `sensitive_category`，却各走各的字节，这个一致性由测试钉住。
///
/// `dropped_thumbnail` 在这里永远是 `false`：原位模式不丢缩略图链，
/// 这正是它存在的理由，也是它的边界——缩略图里可能自带坐标，
/// 要连它一起清就走不带 `--keep-bytes` 的那条路。
pub fn tiff_redact_inplace(
  data : Bytes,
  p : Policy,
) -> (Bytes, Redaction) raise MetaError {
  let plan = make_plan(data, ByPolicy(p))
  if plan.dropped == 0 {
    (data, { removed: [], dropped_thumbnail: false, dropped_xmp: false, })
  } else {
    (
      apply_plan(data, plan),
      { removed: plan.removed, dropped_thumbnail: false, dropped_xmp: false, },
    )
  }
}

///|
/// 原位整段摘除：归本库管的四张表清空，像素与缩略图链原样留在文件里。
///
/// 与 `tiff_redact_inplace` 的分工沿用 `strip` 一贯的承诺：摘完不再声明
/// 任何 EXIF 结构（表还在，条目数为 0）。
pub fn tiff_strip_inplace(data : Bytes) -> (Bytes, Strip) raise MetaError {
  let plan = make_plan(data, All)
  if plan.dropped == 0 {
    (data, { had_exif: false, dropped_xmp: false, })
  } else {
    // 与 `strip_any` 的裸 TIFF 分支同源：载体条目（XMP / Photoshop /
    // IPTC-NAA）就在 IFD0 里，看它在不在，而不是看它归哪一类。
    (apply_plan(data, plan), { had_exif: true, dropped_xmp: plan.carrier, })
  }
}

///|
/// IFD0 里有没有 XMP 载体条目。
fn has_carrier(entries : Array[IfdEntry]) -> Bool {
  find_entry(entries, 0x02bc) != None
}

///|
/// 读目录图 + 定删法 + 算守卫 + 逐区间判冲突。
fn make_plan(data : Bytes, drop : Drop) -> Plan raise MetaError {
  let patch = scan(data)
  let jobs : Array[Job] = []
  let removed : Array[Removed] = []
  // 被删条目的值区间，等守卫算出来以后再判冲突。
  let doomed : Array[(Int, Int, Int)] = []
  let mut dropped = 0
  let mut carrier = false
  for m in patch.mine {
    let t = m.table
    if m.dir == Ifd0 && has_carrier(t.entries) {
      carrier = true
    }
    let keep : Array[Int] = []
    for i = 0; i < t.entries.length(); i = i + 1 {
      let e = t.entries[i]
      if drops(m.dir, e.tag, drop) {
        dropped = dropped + 1
        match removed_record(m.dir, e.tag) {
          Some(r) => removed.push(r)
          None => ()
        }
        let (from, to) = t.spans[i]
        doomed.push((from, to, e.tag))
      } else {
        keep.push(i)
      }
    }
    jobs.push({ off: t.off, old: t.entries.length(), keep, })
  }
  if dropped == 0 {
    // 无事可做就别去审判像素声明：这一条路在这里一个字节都不写（两个入口
    // 都在 `dropped == 0` 时原样交回输入），而"读不懂像素在哪"这种风险，
    // 只在真要落笔时才成立。
    return {
      removed,
      jobs: [],
      scrub: [],
      little: patch.little,
      dropped,
      carrier,
    }
  }
  let guards = guards_of(data, patch, jobs)
  let scrub : Array[(Int, Int)] = []
  for (from, to, tag) in doomed {
    // 内联值跟着槽位一起消失；外置值要单独清零，那一刀必须无人认领。
    if to > from + 4 {
      check_free(from, to, tag, guards, -1)
      scrub.push((from, to))
    }
  }
  // 施工区：新条目区（含改小的条目数）与搬空后清零的表尾。
  for j in jobs {
    let dest_to = j.off + 2 + 12 * j.keep.length()
    check_free(j.off, dest_to, 0, guards, j.off)
    check_free(dest_to, j.off + 2 + 12 * j.old, 0, guards, j.off)
  }
  { removed, jobs, scrub, little: patch.little, dropped, carrier, }
}

///|
/// 这个条目要不要删。
///
/// 子目录指针是结构不是数据：删掉它等于让整张子表失联，两种删法都不动它。
///
/// 全删法还有一条更硬的边界：裸 TIFF 里"这张图怎么解出来"和元数据住在
/// 同一张 IFD0 表里。把 256/259/262/273/278 一起删掉，产物就不再是一张图
/// ——门禁在 104 份陌生 TIFF 里量到 81 份因此解不出像素。所以这条路做不到
/// `strip` 在 JPEG / PNG 上那句"整段摘除"，它的上限是**删掉所有不参与解码
/// 的条目**，见 `image_shape`。
fn drops(dir : Dir, tag : Int, drop : Drop) -> Bool {
  if tag == tag_exif_ifd || tag == tag_gps_ifd || tag == tag_interop_ifd {
    false
  } else {
    match drop {
      All => !(dir == Ifd0 && is_image_shape(tag))
      ByPolicy(p) =>
        match sensitive_category(dir, tag) {
          Some(cat) => p.covers(cat)
          None => false
        }
    }
  }
}

///|
/// 解一张裸 TIFF 的像素绕不开的条目（TIFF 6.0 的图像结构字段：尺寸、位深、
/// 压缩、色彩解释、条带/瓦片的偏移与长度，以及解码参数）。
///
/// 274 Orientation 也在这一份里，是语料把它逼进来的：删掉它之后 Pillow 不再
/// 翻转，产物的解码像素正好是输入的水平镜像（`g4_orientation_2.tif`）——
/// "这条目只管显示方向"是错的，删了图就变。反过来，282/283/296 那几个分辨率
/// 条目不在清单里：门禁逐份比过像素哈希，删掉它们一个像素都不动。
///
/// 这里头没有任何一条说的是"谁拍的、什么时候、在哪儿"：GeoTIFF 那几个
/// 带位置的字段（33550/33922/34735…）故意不在清单里。
///
/// 346/347 也是同一批语料逼进来的：JPEG 压缩的 TIFF 把公共量化表放在 347
/// （JPEGTables），条带里只存差分表，删掉它 Pillow 直接报 `decoder error -2`
/// （4 份），346 是同一家族的变换提示——按 274 那次的教训，不再猜"它只是显示用"。
let image_shape : Array[Int] = [
  256, 257, 258, 259, 262, 266, 273, 274, 277, 278, 279, 284, 317, 320, 322, 323,
  324, 325, 326, 338, 339, 340, 341, 346, 347, 530, 531, 532,
]

///|
fn is_image_shape(tag : Int) -> Bool {
  image_shape.contains(tag)
}

///|
fn removed_record(dir : Dir, tag : Int) -> Removed? {
  sensitive_category(dir, tag).map(cat => {
    dir,
    tag,
    name: tag_name(dir, tag),
    category: cat,
  })
}

///|
/// 走一遍这个文件的目录图。
///
/// 目录发现顺序与 `decode_tiff` 一致（GPS 指针先 IFD0 后 Exif，Interop 在
/// Exif 里），两条路才不会看见两张不同的图。
fn scan(data : Bytes) -> Patch raise MetaError {
  if data.length() < 8 {
    raise TooShort(0, 8, data.length())
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
  let seen : Array[Int] = []
  let mine : Array[Mine] = []
  let foreign : Array[PTable] = []
  let ifd0 = read_table(
    data,
    check_ifd_offset(data, u32_at(data, 4, little)),
    little,
    seen,
  )
  mine.push({ dir: Ifd0, table: ifd0, })
  walk_chain(data, ifd0.next, little, seen, foreign)
  let exif = match sub_dir_offset(data, ifd0.entries, tag_exif_ifd) {
    Some(off) => Some(read_table(data, off, little, seen))
    None => None
  }
  match exif {
    Some(t) => {
      mine.push({ dir: Exif, table: t, })
      walk_chain(data, t.next, little, seen, foreign)
    }
    None => ()
  }
  let gps_off = match sub_dir_offset(data, ifd0.entries, tag_gps_ifd) {
    Some(off) => Some(off)
    None =>
      match exif {
        Some(t) => sub_dir_offset(data, t.entries, tag_gps_ifd)
        None => None
      }
  }
  match gps_off {
    Some(off) => adopt(data, off, Gps, little, seen, mine, foreign)
    None => ()
  }
  let interop_off = match exif {
    Some(t) => sub_dir_offset(data, t.entries, tag_interop_ifd)
    None => None
  }
  match interop_off {
    Some(off) => adopt(data, off, Interop, little, seen, mine, foreign)
    None => ()
  }
  { little, mine, foreign, }
}

///|
/// 读一张归本库管的子表，登记它、再登记它后面那条只读链。
fn adopt(
  data : Bytes,
  off : Int,
  dir : Dir,
  little : Bool,
  seen : Array[Int],
  mine : Array[Mine],
  foreign : Array[PTable],
) -> Unit raise MetaError {
  let t = read_table(data, off, little, seen)
  mine.push({ dir, table: t, })
  walk_chain(data, t.next, little, seen, foreign)
}

///|
/// 沿 next 指针走链。这些表一律只登记、不改写。
fn walk_chain(
  data : Bytes,
  start : Int64,
  little : Bool,
  seen : Array[Int],
  out : Array[PTable],
) -> Unit raise MetaError {
  let mut next = start
  while next > 0L && next + 2L <= data.length().to_int64() {
    let t = read_table(data, next.to_int(), little, seen)
    out.push(t)
    next = t.next
  }
}

///|
fn read_table(
  data : Bytes,
  off : Int,
  little : Bool,
  seen : Array[Int],
) -> PTable raise MetaError {
  for v in seen {
    if v == off {
      // 两张表叠在一起：谁改写都对，但没人说得清哪一份是真的。
      raise TiffInplaceCycle(off)
    }
  }
  seen.push(off)
  let raw = parse_dir(data, off, little)
  {
    off,
    entries: raw.entries,
    spans: entry_spans(data, off, raw.entries, little),
    next: raw.next,
  }
}

///|
/// 逐条算值的字节区间。判内联/外置与 `parse_entry` 同源：
/// 分量数 × 单字节数 <= 4 就是内联，落在槽位偏移 +8 处。
fn entry_spans(
  data : Bytes,
  off : Int,
  entries : Array[IfdEntry],
  little : Bool,
) -> Array[(Int, Int)] raise MetaError {
  let out : Array[(Int, Int)] = []
  for i = 0; i < entries.length(); i = i + 1 {
    let e = entries[i]
    let size = match type_size(e.type_code) {
      Some(s) => s
      None => raise UnsupportedType(e.tag, e.type_code)
    }
    let total = value_len(e.value) * size
    let slot = off + 2 + 12 * i
    if total <= 4 {
      out.push((slot + 8, slot + 12))
    } else {
      let voff = u32_at(data, slot + 8, little).to_int()
      out.push((voff, voff + total))
    }
  }
  out
}

///|
/// 一个值有多少个分量。`decode_value` 按声明的 count 读，所以分量数
/// 就是 count；ASCII 读的是逐字节（含结尾 NUL），也等于 count。
fn value_len(v : TagValue) -> Int {
  match v {
    Text(s) => s.length()
    Raw(bs) => bs.length()
    Shorts(a) => a.length()
    Longs(a) => a.length()
    Rationals(a) => a.length()
  }
}

///|
/// 谁不许被碰。清单见文件顶上那段。
fn guards_of(
  data : Bytes,
  patch : Patch,
  jobs : Array[Job],
) -> Array[Guard] raise MetaError {
  let out : Array[Guard] = [{ from: 0, to: 8, owner: 0, kind: Header, }]
  for t in patch.foreign {
    let body = t.off + 2 + 12 * t.entries.length()
    out.push({ from: t.off, to: body + 4, owner: t.off, kind: ForeignTable, })
    for s in t.spans {
      let (from, to) = s
      if to > from + 4 {
        out.push({ from, to, owner: t.off, kind: ForeignValue, })
      }
    }
  }
  for m in patch.mine {
    let t = m.table
    // 改写表的槽位区是施工场地；表末尾那 4 字节 next 指针不是。
    let body = t.off + 2 + 12 * t.entries.length()
    out.push({ from: body, to: body + 4, owner: t.off, kind: ForeignTable, })
  }
  for j in jobs {
    let spans = spans_of(patch, j.off)
    for i in j.keep {
      let slot = j.off + 2 + 12 * i
      out.push({ from: slot, to: slot + 12, owner: j.off, kind: KeptSlot, })
      let (from, to) = spans[i]
      if to > from + 4 {
        out.push({ from, to, owner: j.off, kind: KeptValue, })
      }
    }
  }
  for g in pixel_guards_of(data, patch) {
    out.push(g)
  }
  out
}

///|
fn spans_of(patch : Patch, off : Int) -> Array[(Int, Int)] {
  for m in patch.mine {
    if m.table.off == off {
      return m.table.spans
    }
  }
  []
}

///|
/// 像素数据声明在哪儿，哪儿就不许碰。
///
/// 认三对标准 tag：条带（273/278）、瓦片（324/325）、缩略图（0x0201/0x0202）。
/// 声明看不懂就报拒绝，而不是"那就清零试试"：不知道像素在哪的原位改写，
/// 比不脱敏更糟。只有半边也算看不懂——单独一个数字无从解释。
///
/// "看不懂"有四种，各说各的句子，不许共用：缺半边、伙伴条数不等、
/// 声明的区间越出文件末尾、值本身不是偏移表。把前两种混成一句
/// 就是在替一个没发生的状况编理由（伙伴明明在，只是两边数不出一样多的数）。
fn pixel_guards_of(data : Bytes, patch : Patch) -> Array[Guard] raise MetaError {
  let out : Array[Guard] = []
  let all : Array[PTable] = []
  for t in patch.foreign {
    all.push(t)
  }
  for m in patch.mine {
    all.push(m.table)
  }
  let pairs : Array[(Int, Int)] = [
    (tag_strip_offsets, tag_strip_counts),
    (tag_tile_offsets, tag_tile_counts),
    (tag_thumb_offset, tag_thumb_length),
  ]
  for t in all {
    for (o_tag, c_tag) in pairs {
      let offs = find_entry(t.entries, o_tag)
      let cnts = find_entry(t.entries, c_tag)
      match (offs, cnts) {
        (Some(o), Some(c)) => guard_pixel(out, data, t.off, o, c)
        (Some(o), None) => raise TiffInplaceOpaque(o.tag, 0)
        (None, Some(c)) => raise TiffInplaceOpaque(c.tag, 0)
        (None, None) => ()
      }
    }
  }
  out
}

///|
fn guard_pixel(
  out : Array[Guard],
  data : Bytes,
  owner : Int,
  offs : IfdEntry,
  cnts : IfdEntry,
) -> Unit raise MetaError {
  let from_list = number_values(offs)
  let len_list = number_values(cnts)
  if from_list.length() != len_list.length() {
    raise TiffInplaceOpaque(offs.tag, -1)
  }
  for i = 0; i < from_list.length(); i = i + 1 {
    let from = from_list[i]
    let len = len_list[i]
    if from < 0 || len < 0 || from + len > data.length() {
      raise TiffInplaceOpaque(offs.tag, -2)
    }
    if len > 0 {
      out.push({ from, to: from + len, owner, kind: Pixel, })
    }
  }
}

///|
let tag_strip_offsets : Int = 273

///|
/// StripByteCounts 是 278。279 是 SamplesPerPixel——它和 273 一样是个数组，
/// 配错了不会报错，只会把"像素在哪"读成一小段莫名其妙的区间。
let tag_strip_counts : Int = 278

///|
let tag_tile_offsets : Int = 324

///|
let tag_tile_counts : Int = 325

///|
fn number_values(e : IfdEntry) -> Array[Int] raise MetaError {
  match e.value {
    Shorts(a) => a
    Longs(a) => a.map(x => x.to_int())
    Text(_) | Raw(_) | Rationals(_) =>
      raise TiffInplaceOpaque(e.tag, e.type_code)
  }
}

///|
/// [from, to) 这段要写的地方有没有被认领。
///
/// `self_off` >= 0 时豁免"这张表自己的保留槽位"：那些字节是先读后盖的源，
/// 搬完就该被覆盖。被删条目的外置值清零传 -1，一分豁免都不给。
fn check_free(
  from : Int,
  to : Int,
  tag : Int,
  guards : Array[Guard],
  self_off : Int,
) -> Unit raise MetaError {
  if from >= to {
    return ()
  }
  for g in guards {
    let exempt = self_off >= 0 && g.kind == KeptSlot && g.owner == self_off
    if from < g.to && g.from < to && !exempt {
      raise TiffInplaceShared(tag, from, to - from, g.owner, region_desc(g))
    }
  }
}

///|
/// 这段被保护的字节在报告里叫什么。写这句是要用户能决定下一步：
/// 撞的是像素，就该走重写那条路；撞的是另一张目录表，就是文件本身有歧义。
fn region_desc(g : Guard) -> String {
  match g.kind {
    Header => "the file's own TIFF header"
    ForeignTable => "a directory this mode only reads"
    ForeignValue =>
      "a value of a directory this mode only reads, at offset \{g.from}"
    KeptValue => "a value this run keeps, at offset \{g.from}"
    KeptSlot => "an entry slot this run keeps, at offset \{g.from}"
    Pixel => "the image data itself, declared at offset \{g.from}"
  }
}

///|
/// 落笔。顺序要紧：**先清被删条目的外置值，再搬槽位**。
///
/// 反过来越界过一次，是畸形输入逼出来的：一个条目的值指针可以指向**本表
/// 自己的槽位区**（把某个 ASCII 条目的偏移字段改小几位就得到），而受保护
/// 清单里本来就没有"本表要写的那一段"——那是施工场地，不是别人的字节。
/// 先搬再清，那一刀清零就落在刚写好的保留条目上，产物当场读不回来。
///
/// 先清之所以安全：施工场地 [off, 旧表尾) 的每一格都会在下一步被重新赋值
/// ——条目数被 poke、保留槽位从**原始的 `data`** 逐字节抄过来（不是从 `buf`，
/// 所以抄到的永远是动笔之前的值）、next 那 4 字节同样从 `data` 取、剩下的
/// 表尾一律清零。既然整段都会被覆写，落在其中的清零就是白做，而不做坏事。
fn apply_plan(data : Bytes, plan : Plan) -> Bytes raise MetaError {
  let buf = data.to_array()
  for s in plan.scrub {
    let (from, to) = s
    for p = from; p < to; p = p + 1 {
      buf[p] = b'\x00'
    }
  }
  for j in plan.jobs {
    let mut w = j.off + 2
    for i in j.keep {
      let src = j.off + 2 + 12 * i
      for k = 0; k < 12; k = k + 1 {
        buf[w + k] = byte_at(data, src + k)
      }
      w = w + 12
    }
    poke_u16(buf, j.off, j.keep.length(), plan.little)
    // next 指针跟着计数走：读侧按 `off + 2 + 12n` 找它，所以搬完槽位要把
    // 那 4 字节重落到新表尾。源一律从 `data` 读——`buf` 里那个位置可能刚
    // 被我们当成某个保留槽位的源用过，值还是老值，但别指望它。
    let old_body = j.off + 2 + 12 * j.old
    for k = 0; k < 4; k = k + 1 {
      buf[w + k] = byte_at(data, old_body + k)
    }
    for p = w + 4; p < old_body; p = p + 1 {
      buf[p] = b'\x00'
    }
  }
  Bytes::from_array(buf)
}

///|
/// 在指定偏移写一个 u16。`moonmeta_encode.mbt` 的 `put_u16` 是往尾部追加，
/// 原位模式要的是"就在这一格"。
fn poke_u16(buf : Array[Byte], off : Int, v : Int, little : Bool) -> Unit {
  let lo = (v & 0xff).to_byte()
  let hi = ((v >> 8) & 0xff).to_byte()
  if little {
    buf[off] = lo
    buf[off + 1] = hi
  } else {
    buf[off] = hi
    buf[off + 1] = lo
  }
}
