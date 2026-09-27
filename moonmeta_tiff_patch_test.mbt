// 原位改写：`tiff_redact_inplace` / `tiff_strip_inplace`。
//
// 这一层的承诺全写在字节上——"长度不变""一个字节都不搬""没点名的还在"——
// 所以这里的断言也全落在字节上：改动只许出现在点名的区间里，像素区、
// 每张表的 next 指针、保留条目的槽位与它们的外置值，逐字节比。
//
// 夹具是手搓的：`encode_tiff` 只会产出"IFD0 在偏移 8、除元数据一无所有"
// 的布局，而那正是重写路径本来就收得下的形状。原位这条路存在的理由恰恰是
// 另一种形状——像素在前、目录在后、目录链上还挂着缩略图。
// 所有偏移由表的大小算出来，不抄常量：抄来的数字对不上时，测试会红在
// "这段不该动"上，而不是静默地比错位置。

///|
/// 一个 12 字节槽位。`value` 是正好 4 字节：内联值本身，或外置值的偏移。
fn slot(
  tag : Int,
  type_code : Int,
  count : Int,
  value : Array[Byte],
) -> Array[Byte] raise {
  let out : Array[Byte] = []
  for b in u16_le(tag) {
    out.push(b)
  }
  for b in u16_le(type_code) {
    out.push(b)
  }
  for b in u32_le(count) {
    out.push(b)
  }
  for b in value {
    out.push(b)
  }
  // 槽位必须是 12 字节：值字段短一字节，后面每一个偏移都跟着错位，
  // 那时该红的是这一句，不是某段"不该动的字节被动了"。
  @test.assert_eq(out.length(), 12)
  out
}

///|
fn u16_le(v : Int) -> Array[Byte] {
  [(v & 0xff).to_byte(), ((v >> 8) & 0xff).to_byte()]
}

///|
fn u32_le(v : Int) -> Array[Byte] {
  [
    (v & 0xff).to_byte(),
    ((v >> 8) & 0xff).to_byte(),
    ((v >> 16) & 0xff).to_byte(),
    ((v >> 24) & 0xff).to_byte(),
  ]
}

///|
/// SHORT 的内联值：写在 4 字节字段的前 2 字节。
fn in_short(v : Int) -> Array[Byte] {
  let a = u16_le(v)
  [a[0], a[1], b'\x00', b'\x00']
}

///|
/// LONG / 指针的内联值。
fn in_long(v : Int) -> Array[Byte] {
  u32_le(v)
}

///|
/// 不超过 4 字节的 ASCII：原文补 NUL 到 4 字节。
fn in_ascii(bs : Array[Byte]) -> Array[Byte] {
  let out = bs.copy()
  while out.length() < 4 {
    out.push(b'\x00')
  }
  out
}

///|
/// ASCII 串的取值区：原文 + 结尾 NUL（TIFF 的约定）。
/// 复用同包 `moonmeta_jpeg_test.mbt` 里的 `ascii`，不再自己转一遍。
fn ascii_nul(s : String) -> Array[Byte] {
  let out = ascii(s)
  out.push(b'\x00')
  out
}

///|
/// 一张表的字节数：条目数 + 槽位 + next 指针。
fn table_len(n : Int) -> Int {
  2 + 12 * n + 4
}

///|
/// 一份"相机形状"的裸 TIFF，小端。地址全在这里算出来：
///
/// ```plain
/// 0    头 8 字节
/// 8    64 字节假像素（由 IFD0 的 273/278 声明）
/// 72   IFD0 12 条   256 257 259 262 273 278 274 305 306 315 0x8769 0x8825
///      next -> 222（IFD1 缩略图目录）
/// 222  IFD1 2 条     513/514 指向 354..374 的缩略图字节
/// 252  Exif 2 条     36867 外置 + 0xa005 -> 336
/// 282  GPS  4 条     0/1 内联，2/4 外置坐标
/// 336  Interop 1 条
/// 354  缩略图 20 字节
/// 374  305 的值   383 306 的值   403 315 的值   418 36867 的值
/// 438  纬度      462 经度
/// ```
///
/// 315 是外置的删除项、305 是外置的保留项：两段命运不同，放在同一份文件里
/// 才看得出"清零"清的是谁。274 是语料逼进来的（删了它 Pillow 解出镜像），
/// 278 与 273 配成对——279 不是它计数，那是 SamplesPerPixel。
fn patch_fixture() -> Bytes raise {
  let m = fixture_map()
  let sw = ascii_nul("moonmeta")
  let dt = ascii_nul("2026:09:25 18:04:00")
  let ar = ascii_nul("Jean Cornillon")
  let org = ascii_nul("2026:09:25 18:04:00")
  let out : Array[Byte] = [b'I', b'I', b'*', b'\x00']
  for b in u32_le(m.ifd0) {
    out.push(b)
  }
  for _ in 0..<64 {
    out.push(b'\x11')
  }
  // IFD0
  for b in u16_le(12) {
    out.push(b)
  }
  for
    e in [
      slot(256, 3, 1, in_short(590)),
      slot(257, 3, 1, in_short(88)),
      slot(259, 3, 1, in_short(1)),
      slot(262, 3, 1, in_short(1)),
      slot(273, 4, 1, in_long(8)),
      slot(278, 4, 1, in_long(64)),
      slot(274, 3, 1, in_short(2)),
      slot(305, 2, sw.length(), in_long(m.sw)),
      slot(306, 2, dt.length(), in_long(m.dt)),
      slot(315, 2, ar.length(), in_long(m.ar)),
      slot(0x8769, 4, 1, in_long(m.exif)),
      slot(0x8825, 4, 1, in_long(m.gps)),
    ] {
    for b in e {
      out.push(b)
    }
  }
  for b in u32_le(m.ifd1) {
    out.push(b)
  }
  // IFD1：只登记、不改写。513/514 让缩略图字节也成为受保护区间。
  for b in u16_le(2) {
    out.push(b)
  }
  for e in [slot(513, 4, 1, in_long(m.thumb)), slot(514, 4, 1, in_long(20))] {
    for b in e {
      out.push(b)
    }
  }
  for b in u32_le(0) {
    out.push(b)
  }
  // Exif
  for b in u16_le(2) {
    out.push(b)
  }
  for
    e in [
      slot(36867, 2, org.length(), in_long(m.org)),
      slot(0xa005, 4, 1, in_long(m.interop)),
    ] {
    for b in e {
      out.push(b)
    }
  }
  for b in u32_le(0) {
    out.push(b)
  }
  // GPS
  for b in u16_le(4) {
    out.push(b)
  }
  for
    e in [
      slot(0, 1, 4, [b'\x02', b'\x03', b'\x00', b'\x00']),
      slot(1, 2, 2, in_ascii([b'N'])),
      slot(2, 5, 3, in_long(m.lat)),
      slot(4, 5, 3, in_long(m.lon)),
    ] {
    for b in e {
      out.push(b)
    }
  }
  for b in u32_le(0) {
    out.push(b)
  }
  // Interop
  for b in u16_le(1) {
    out.push(b)
  }
  for b in slot(1, 2, 3, in_ascii([b'R', b'9', b'8'])) {
    out.push(b)
  }
  for b in u32_le(0) {
    out.push(b)
  }
  // 值区
  for _ in 0..<20 {
    out.push(b'\x54')
  }
  for heap in [sw, dt, ar, org] {
    for b in heap {
      out.push(b)
    }
  }
  for v in [31, 1, 0, 1, 13, 10000, 121, 1, 0, 1, 14, 10000] {
    for b in u32_le(v) {
      out.push(b)
    }
  }
  Bytes::from_array(out)
}

///|
/// 这份夹具的地址表：断言里所有"这段必须一模一样"都从这里取。
priv struct Map {
  ifd0 : Int
  ifd1 : Int
  exif : Int
  gps : Int
  interop : Int
  thumb : Int
  sw : Int
  dt : Int
  ar : Int
  org : Int
  lat : Int
  lon : Int
}

///|
fn fixture_map() -> Map {
  let ifd0 = 72
  let ifd1 = ifd0 + table_len(12)
  let exif = ifd1 + table_len(2)
  let gps = exif + table_len(2)
  let interop = gps + table_len(4)
  let thumb = interop + table_len(1)
  let sw = thumb + 20
  let dt = sw + 9
  let ar = dt + 20
  let org = ar + 15
  let lat = org + 20
  {
    ifd0,
    ifd1,
    exif,
    gps,
    interop,
    thumb,
    sw,
    dt,
    ar,
    org,
    lat,
    lon: lat + 24,
  }
}

///|
/// 一个条目的槽位起点（在某张表里按编号找）。找不到就 fail：
/// 夹具改了、测试没跟上，不该悄悄比到别的字节上。
fn slot_at(data : Bytes, table : Int, tag : Int) -> Int raise {
  let n = le16(data, table)
  let mut i = 0
  while i < n {
    if le16(data, table + 2 + 12 * i) == tag {
      return table + 2 + 12 * i
    }
    i = i + 1
  }
  fail("夹具里编号 \{tag} 不在这张表")
}

///|
/// 把槽位里的值字段（偏移 +8）改成另一个 4 字节数。
/// 内联与外置只由 count × 类型宽度决定，所以这样改能造出"两个条目共用一段值"。
fn retarget(data : Bytes, table : Int, tag : Int, at : Int) -> Bytes raise {
  let off = slot_at(data, table, tag) + 8
  poke(data, off, u32_le(at))
}

///|
fn poke(data : Bytes, off : Int, bytes : Array[Byte]) -> Bytes {
  let arr = data.to_array()
  for i = 0; i < bytes.length(); i = i + 1 {
    arr[off + i] = bytes[i]
  }
  Bytes::from_array(arr)
}

///|
fn le16(data : Bytes, at : Int) -> Int {
  let a = span(data, at, at + 2)
  a[0].to_int() + (a[1].to_int() << 8)
}

///|
fn le32(data : Bytes, at : Int) -> Int {
  let a = span(data, at, at + 4)
  a[0].to_int() +
  (a[1].to_int() << 8) +
  (a[2].to_int() << 16) +
  (a[3].to_int() << 24)
}

///|
fn byte_at(data : Bytes, at : Int) -> Int {
  span(data, at, at + 1)[0].to_int()
}

///|
/// 这句红的时候要说清"是谁"。`@test.assert_eq(x, true)` 只回一句
/// `false != true`，看不出是哪段承诺没兑现。
fn assert_true(cond : Bool) -> Unit raise {
  @test.assert_eq(cond, true)
}

///|
/// 逐字节相同。`Bytes` 没有现成的 Eq，比对就写在这里，别处不重复。
fn identical(a : Bytes, b : Bytes) -> Bool {
  a.length() == b.length() &&
  first_diff(a.to_array(), b.to_array()) == a.length()
}

///|
/// 这段必须和输入逐字节一样。名字带上"哪一段"，红的时候能说清是谁被动了。
fn untouched(
  out : Bytes,
  data : Bytes,
  what : String,
  from : Int,
  to : Int,
) -> Unit raise {
  if span(out, from, to) != span(data, from, to) {
    let at = first_diff(span(out, from, to), span(data, from, to))
    fail(
      "\{what}（\{from}..\{to}）被动了：第一处差异在这段的第 \{at} 字节",
    )
  }
}

///|
fn first_diff(a : Array[Byte], b : Array[Byte]) -> Int {
  let n = if a.length() < b.length() { a.length() } else { b.length() }
  let mut i = 0
  while i < n {
    if a[i] != b[i] {
      return i
    }
    i = i + 1
  }
  n
}

///|
/// 这段必须全是零。被删条目的外置值不清零，等于把敏感内容留在原地。
fn zeroed(data : Bytes, what : String, from : Int, to : Int) -> Unit raise {
  let mut i = from
  while i < to {
    if byte_at(data, i) != 0 {
      fail(
        "\{what}（\{from}..\{to}）该清零，偏移 \{i} 还剩 \{byte_at(data, i)}",
      )
    }
    i = i + 1
  }
}

///|
fn redact_or_fail(
  data : Bytes,
  p : @moonmeta.Policy,
) -> (Bytes, @moonmeta.Redaction) raise {
  @moonmeta.tiff_redact_inplace(data, p) catch {
    e => fail("原位改写不该拒绝: \{e}")
  }
}

///|
fn err_of(data : Bytes, p : @moonmeta.Policy) -> String {
  try @moonmeta.tiff_redact_inplace(data, p) catch {
    e => e.to_string()
  } noraise {
    _ => "没有报错"
  }
}

///|
/// 原位模式存在的理由：同一份文件，重写路径按设计拒绝，它收下。
///
/// 这一条先证明夹具真的落在那道判据的"拒绝"一侧——否则下面每一条都在空跑。
/// 要打在 `redact_any` 上：`redact_tiff` 是它下面那一层，绕过了
/// `check_tiff_rewrite`，对任何输入都不拒绝。
test "重写路径拒绝的相机形状，原位改写放行" {
  let data = patch_fixture()
  let refused = try
    @moonmeta.redact_any(data, @moonmeta.strict_policy())
  catch {
    e => e.to_string()
  } noraise {
    _ => "没有拒绝"
  }
  assert_true(refused.has_prefix("refusing to rewrite this bare TIFF"))
  let (out, _) = redact_or_fail(data, @moonmeta.strict_policy())
  @test.assert_eq(out.length(), data.length())
}

///|
/// 一个字节都不搬：除点名的区间外，每一段都得逐字节相同。
/// 这份清单是这条路的承诺本体——"长度不变"之外，还要"别处没动"。
test "改动只落在点名的区间里，别处一个字节都不许多动" {
  let data = patch_fixture()
  let m = fixture_map()
  let (out, _) = redact_or_fail(data, @moonmeta.strict_policy())
  untouched(out, data, "文件头", 0, 8)
  untouched(out, data, "像素数据", 8, m.ifd0)
  untouched(out, data, "IFD0 的 next 指针", m.ifd0 + 146, m.ifd0 + 150)
  untouched(out, data, "整张缩略图目录", m.ifd1, m.exif)
  untouched(out, data, "Exif 的 next 指针", m.exif + 26, m.exif + 30)
  untouched(out, data, "GPS 的 next 指针", m.gps + 50, m.gps + 54)
  untouched(out, data, "Interop 整张表", m.interop, m.thumb)
  untouched(out, data, "缩略图字节", m.thumb, m.sw)
  // 305 保留：它的外置值一个字节都不许动。strict 不删 Software。
  untouched(out, data, "保留条目 Software 的值", m.sw, m.dt)
  // 表里搬剩下的槽位也一样：被删的是第 8/9 条，前面那些槽位内容不变
  untouched(out, data, "IFD0 前 8 个槽位", m.ifd0 + 2, m.ifd0 + 2 + 12 * 8)
}

///|
/// 被删条目的外置值逐字节清零，保留条目的外置值原样。
/// 两条必须同时成立：只做到前者会连 Software 一起抹了，
/// 只做到后者等于什么都没删。
test "删掉的外置值清零，保留的外置值原样" {
  let data = patch_fixture()
  let m = fixture_map()
  let (out, red) = redact_or_fail(data, @moonmeta.strict_policy())
  @test.assert_eq(red.removed.length(), 7)
  zeroed(out, "被删的 DateTime 值", m.dt, m.ar)
  zeroed(out, "被删的 Artist 值", m.ar, m.org)
  zeroed(out, "被删的 DateTimeOriginal 值", m.org, m.lat)
  zeroed(out, "被删的纬度", m.lat, m.lon)
  zeroed(out, "被删的经度", m.lon, m.lon + 24)
  untouched(out, data, "Software 的值（策略不删它）", m.sw, m.dt)
}

///|
/// 每表开头的条目数改小、保留的槽位往前搬、腾空的表尾归零，
/// 而 next 指针跟着计数重落到新表尾——读侧按 `off + 2 + 12n` 找它，
/// 少了这一刀，缩略图链就静默变 0。旧位置那 4 字节原样留着。
test "条目数改小、表尾腾空归零、next 指针跟着搬到新表尾" {
  let data = patch_fixture()
  let m = fixture_map()
  let (out, _) = redact_or_fail(data, @moonmeta.strict_policy())
  @test.assert_eq(le16(out, m.ifd0), 10)
  @test.assert_eq(le16(out, m.exif), 1)
  @test.assert_eq(le16(out, m.gps), 0)
  @test.assert_eq(le16(out, m.interop), 1)
  // IFD0 删了 306/315 两条：搬完剩 10 条，[next 之后, 原 12 条末尾) 归零
  let kept_end = m.ifd0 + 2 + 12 * 10
  zeroed(out, "IFD0 腾空的表尾", kept_end + 4, m.ifd0 + 2 + 12 * 12)
  // 搬完的第一个槽位还是 256，最后一个保留的是 0x8825 指针
  @test.assert_eq(le16(out, m.ifd0 + 2), 256)
  @test.assert_eq(le16(out, kept_end - 12), 0x8825)
  // next 指针在新表尾，还是指向 IFD1
  @test.assert_eq(le32(out, kept_end), m.ifd1)
  // GPS 全删：整段槽位区归零，条目数为 0（next 重落到表头之后，值本来就是 0）
  zeroed(out, "GPS 的槽位区", m.gps + 2, m.gps + 2 + 12 * 4)
  // 解码侧的后果：链还在。这一句才是上面那 4 字节存在的理由。
  @test.assert_eq(decode_ok(out).has_ifd1, true)
}

///|
/// 报告必须与读侧同源：`removed` 与 `TiffBlock::findings` 逐条相同。
/// 两条路共用 `sensitive_category`、各走各的字节，这一条钉住它们没分家。
test "removed 与 findings 逐条相同" {
  let data = patch_fixture()
  let block = decode_ok(data)
  let (_, red) = redact_or_fail(data, @moonmeta.strict_policy())
  @test.assert_eq(red.removed, block.findings(@moonmeta.strict_policy()))
  @test.assert_eq(red.dropped_thumbnail, false)
}

///|
/// 两条写路的分工不该改变"删了什么"：同一块元数据、同一条策略，
/// 原位产物解回 IR 再走一次重写路径，除缩略图链外逐字段相同。
/// （重写路径在这份夹具上拒绝，所以比的是它自己收得下的那份 IR。）
///
/// 链这一格必须单独说：原位产物留着链（`has_ifd1` 为真），重写路径装不下
/// 它、丢掉并出声。前一条断言写成"整份 IR 相等"时，只有链被锯断的产物
/// 才通得过——那是缺陷的合影，不是一致性。
test "原位产物与重写路径在 IR 上一致，除了各自该丢的链" {
  let p = @moonmeta.strict_policy()
  let data = patch_fixture()
  let (out, _) = redact_or_fail(data, p)
  let inplace = decode_ok(out)
  @test.assert_eq(inplace.has_ifd1, true)
  let (again, red2) = inplace.redact(p)
  // 条目层面已经无事可做：该删的上一条路删完了
  @test.assert_eq(red2.removed.length(), 0)
  // 该出声的那一件出了声
  @test.assert_eq(red2.dropped_thumbnail, true)
  @test.assert_eq(again.has_ifd1, false)
  // 抹掉链这一个字段，其余 IR 逐字段相同
  let expect : @moonmeta.TiffBlock = {
    little: inplace.little,
    ifd0: inplace.ifd0,
    exif: inplace.exif,
    gps: inplace.gps,
    interop: inplace.interop,
    has_ifd1: false,
  }
  @test.assert_eq(again, expect)
  @test.assert_eq(inplace.gps_lat_lon(), None)
  @test.assert_eq(inplace.artist(), None)
  @test.assert_eq(inplace.date_time(), None)
  // 没点名的还在
  @test.assert_eq(inplace.software(), Some("moonmeta"))
  @test.assert_eq(inplace.orientation(), Some(2))
}

///|
/// 原位 strip 的承诺和 JPEG / PNG 那条不一样：图像解码必需的字段留下，
/// 其余全删。删掉 256/259/262/273/278 的产物不再是图——Pillow 连格式都认不出。
test "strip 留下解码字段，删掉其余，像素与缩略图链不动" {
  let data = patch_fixture()
  let m = fixture_map()
  let (out, st) = @moonmeta.tiff_strip_inplace(data) catch {
    e => fail("原位 strip 不该拒绝: \{e}")
  }
  @test.assert_eq(st.had_exif, true)
  @test.assert_eq(st.dropped_xmp, false)
  // IFD0：7 条解码字段 + 2 个指针留着（305/306/315 没了）
  @test.assert_eq(le16(out, m.ifd0), 9)
  @test.assert_eq(le16(out, m.exif), 1)
  @test.assert_eq(le16(out, m.gps), 0)
  @test.assert_eq(le16(out, m.interop), 0)
  let block = decode_ok(out)
  @test.assert_eq(block.ifd0.length(), 7)
  @test.assert_eq(block.software(), None)
  @test.assert_eq(block.orientation(), Some(2))
  @test.assert_eq(block.has_ifd1, true)
  untouched(out, data, "像素数据", 8, m.ifd0)
  untouched(out, data, "整张缩略图目录", m.ifd1, m.exif)
  untouched(out, data, "缩略图字节", m.thumb, m.sw)
  // 被删条目的外置值一律清零，包括策略不碰的 Software
  zeroed(out, "被删的 Software 值", m.sw, m.dt)
  zeroed(out, "被删的 Artist 值", m.ar, m.org)
}

///|
/// 无事可做时不许去审判像素声明：这一条路在这里一个字节都不写，
/// "读不懂像素在哪儿"只在真要落笔时才成立。
test "没东西可删时，读不懂的像素声明不拦路" {
  let data = pairless_fixture(false)
  let (out, red) = redact_or_fail(data, @moonmeta.privacy_policy())
  @test.assert_eq(red.removed.length(), 0)
  @test.assert_eq(identical(out, data), true)
  let (same, st) = @moonmeta.tiff_strip_inplace(data) catch {
    e => fail("空目录的 strip 也不该拒绝: \{e}")
  }
  @test.assert_eq(st.had_exif, false)
  @test.assert_eq(identical(same, data), true)
}

///|
/// 要清零的地方压在像素上：删了就等于削图像。拒绝，而不是猜。
test "被删条目的值压在像素声明上：拒绝" {
  let m = fixture_map()
  let data = retarget(patch_fixture(), m.ifd0, 315, 40)
  let msg = err_of(data, @moonmeta.strict_policy())
  assert_true(msg.contains("refusing to write this bare TIFF in place"))
  assert_true(msg.contains("the image data itself"))
}

///|
/// 两个条目共用一段外置值：清零谁都不对，保留又等于没删。
test "被删条目的值与保留条目的值是同一段字节：拒绝" {
  let m = fixture_map()
  let data = retarget(patch_fixture(), m.ifd0, 315, m.sw)
  let msg = err_of(data, @moonmeta.strict_policy())
  assert_true(msg.contains("a value this run keeps"))
  assert_true(
    msg.contains("it will not guess which of the two uses is the real one"),
  )
}

///|
/// 被删条目的值指针指回**本表自己那些搬空了的槽位**：受保护清单里没有那一段
/// （那是施工场地，不是别人的字节），于是守卫放行，而清零那一刀落在了
/// 刚搬好的保留条目上——产物当场读不回来。这一格是 12000 份性质扫描
/// 报出来的第一红（`TIFF/MM 第33字节→第4号值`），钉的就是"先清后搬"这个顺序。
///
/// 反向那一格同时钉住：指针压到**保留条目**的槽位上仍然是拒绝。这条修复
/// 只许改顺序，不许把 KeptSlot 从清单里删掉来"通过"上一格。
test "被删条目的值指回自己的表：先清零，搬好的条目还在，产物读得回来" {
  let data = patch_fixture()
  let m = fixture_map()
  // 315 Artist 的外置值改指到 306 的原槽位：那张表被删的正是 305/306/315
  // 三条，它们的槽位没人认领，而搬完之后那段要落上保留条目
  let aliased = retarget(data, m.ifd0, 315, slot_at(data, m.ifd0, 306))
  let (out, st) = @moonmeta.tiff_strip_inplace(aliased) catch {
    e => fail("值指针压在自己的表上不该拒绝: \{e}")
  }
  @test.assert_eq(st.had_exif, true)
  @test.assert_eq(out.length(), aliased.length())
  // IFD0 留 9 条：第 8、9 格是两张子目录指针，正是被那一刀吃掉的地方
  @test.assert_eq(le16(out, m.ifd0), 9)
  @test.assert_eq(le16(out, m.ifd0 + 2 + 12 * 7), 0x8769)
  @test.assert_eq(le32(out, m.ifd0 + 2 + 12 * 7 + 8), m.exif)
  @test.assert_eq(le16(out, m.ifd0 + 2 + 12 * 8), 0x8825)
  @test.assert_eq(le32(out, m.ifd0 + 2 + 12 * 8 + 8), m.gps)
  // next 指针跟着计数搬到新表尾，也在被改小的那几条之内
  @test.assert_eq(le32(out, m.ifd0 + 2 + 12 * 9), m.ifd1)
  let block = decode_ok(out)
  @test.assert_eq(block.ifd0.length(), 7)
  @test.assert_eq(block.has_ifd1, true)
  @test.assert_eq(block.findings(@moonmeta.strict_policy()).length(), 0)
  // 腾空的那段表尾一律归零：这里也是那一刀点名的地方
  zeroed(out, "腾空的表尾", m.ifd0 + 2 + 12 * 9 + 4, m.ifd0 + 2 + 12 * 12)
}

///|
/// 同一种改指，压到保留条目的槽位上就是要拒绝。
test "被删条目的值指到保留条目的槽位：仍然拒绝" {
  let m = fixture_map()
  let data = retarget(
    patch_fixture(),
    m.ifd0,
    315,
    slot_at(patch_fixture(), m.ifd0, 274),
  )
  let msg = err_of(data, @moonmeta.strict_policy())
  assert_true(msg.contains("an entry slot this run keeps"))
}

///|
/// 两张指针指向同一张表：改哪一份都对，但没人说得清哪一份是真的。
test "目录图成环：拒绝" {
  let m = fixture_map()
  let data = poke(patch_fixture(), m.ifd0 + 2 + 12 * 12, u32_le(m.exif))
  let msg = err_of(data, @moonmeta.strict_policy())
  assert_true(msg.contains("is reached twice"))
  assert_true(msg.contains("offset \{m.exif}"))
}

///|
/// 像素声明只给半边就是不知道像素在哪儿，这时候落笔比不脱敏更糟。
test "像素声明只给半边：拒绝落笔" {
  let msg = err_of(pairless_fixture(true), @moonmeta.strict_policy())
  assert_true(msg.contains("declares where the pixel data sits"))
  assert_true(msg.contains("its partner entry is missing"))
}

///|
/// 同一份声明的条数对不上也是看不懂：273 给 1 个偏移、278 给 2 个计数，
/// 谁也不知道第二个计数属于谁。这一种不许塌回"伙伴条目不在"——
/// 伙伴明明在，只是两边数不出一样多的数。
test "偏移表与计数表条数不等：拒绝落笔" {
  let m = fixture_map()
  let data = patch_fixture()
  let off = slot_at(data, m.ifd0, 278)
  // 278 的 count（槽位 +4）从 1 改成 2：外置值要 8 字节，读回来的是一串像素
  let wide = poke(data, off + 4, u32_le(2))
  let msg = err_of(wide, @moonmeta.strict_policy())
  assert_true(msg.contains("declares where the pixel data sits"))
  assert_true(
    msg.contains("its partner entry lists a different number of values"),
  )
}

///|
/// 类型码不认识就不是"能读的字节"：这一版按边界条款不解码那些类型，
/// 而原位模式要在算值区间时撞上它——拒绝得越早越好。
test "读不懂的类型码：拒绝，一句都不承诺" {
  let m = fixture_map()
  // 第 8 槽是 305 Software：把它的类型码改成 11（Float）
  let typed = poke(patch_fixture(), m.ifd0 + 2 + 12 * 7 + 2, u16_le(11))
  let msg = err_of(typed, @moonmeta.strict_policy())
  assert_true(msg.contains("which this version does not decode"))
  assert_true(msg.contains("TIFF type 11"))
}

///|
/// 只有半边像素声明（273 在、278 不在）的小文件。两种用法：
/// 不带 315 时它什么都不会被动，是"无事可做"那一格的输入；带 315 时
/// strict 真要删一条，这时才轮到"读不懂像素在哪"拦路。
///
/// ```plain
/// 0..8    头，IFD0 在 24
/// 8..24   16 字节假像素（只有 273 说得出它在哪，278 缺席）
/// 24..    IFD0：256 内联 / 273=8 / （315 外置，值紧贴在表后）
/// ```
fn pairless_fixture(with_artist : Bool) -> Bytes raise {
  let ifd0_at = 24
  let n = if with_artist { 3 } else { 2 }
  let artist_at = ifd0_at + table_len(n)
  let out : Array[Byte] = [b'I', b'I', b'*', b'\x00']
  for b in u32_le(ifd0_at) {
    out.push(b)
  }
  for _ in 0..<16 {
    out.push(b'\x11')
  }
  for b in u16_le(n) {
    out.push(b)
  }
  for e in [slot(256, 3, 1, in_short(8)), slot(273, 4, 1, in_long(8))] {
    for b in e {
      out.push(b)
    }
  }
  if with_artist {
    for b in slot(315, 2, 15, in_long(artist_at)) {
      out.push(b)
    }
  }
  for b in u32_le(0) {
    out.push(b)
  }
  if with_artist {
    for b in ascii_nul("Jean Cornillon") {
      out.push(b)
    }
  }
  Bytes::from_array(out)
}
