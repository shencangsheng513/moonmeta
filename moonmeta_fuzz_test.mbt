// 畸形输入的系统扫描。三条性质，每条都能复算：
//
//   1. 不许 panic。解析器可以拒绝任何输入，但拒绝必须是错误，不能是崩溃。
//      这一条对脱敏工具尤其要紧：崩溃的用户拿不到任何解释，
//      而且"这个文件让解析器挂了"在隐私语境里等同于"没检查出来"。
//   2. 每条错误都要能追问。报"坏了"不够，得说出坏在第几个字节，
//      而且那个偏移必须真的落在被读的这一块里（指针类错误除外，见 locator）。
//   3. 脱敏不许把文件删坏。redact / strip 一旦声称成功，产物必须
//      自己被读得回来、再审一遍一条敏感都不剩、再删一次一个字节都不动。
//
// 为什么不是随机 fuzz：随机的输入集每次跑都不一样，红一次就没法复现，
// 也没人知道到底扫过了什么。这里全是系统枚举——每个种子的每一个前缀、
// 每个字节的每一处单字节改写——扫过的数量由测试自己打印出来，
// 读者可以对着种子文件手算，地板断言再钉住"扫描真的跑了"。
//
// 偏移一律按"相对这一块"算：APP1 里的 TIFF 块从 "Exif\0\0" 之后开始编号，
// 所以错误说的第 N 字节是块内偏移而不是文件偏移。这是设计，不是漏了。
//
// 每条断言都用一次"往库里注入坏"验过它会红（每次都当场改回原样再跑全量）：
//   byte_at 的偏移 +1000        → 红在"声称坏在第 1022 字节，可那块只有 22 字节长"
//   不过滤 GPS 目录             → 红在"脱敏之后还能审出 4 条敏感条目"
//   空收获也重编码 EXIF 段      → 红在"一条都没删，产物却和输入不同（293B→134B）"
//   strip 时跳过 XMP 包         → 红在"strip 之后容器里还有元数据段"
//   decode_tiff 里越界读数组    → 红，且不是被本文件的 catch 吞掉：
//                                MoonBit 的 `try ... catch` 不接运行时崩溃，
//                                所以"不许 panic"这一条是真的在被测。
// 反例记在这里：`1 / 0` 在这个工具链上不出声也不红，它不是崩溃的合格探针。

///|
/// 错误里那个数字有几种性质，判据不同，所以先分类再断言。
///
/// `Site(off)` 是出错时正在读的那个字节，必须落在块内；
/// `Pointer` 是被指控"指向块外"的那个指针值本身，报出来就因为它不在块内，
/// 拿块长去要求它反而是错的；
/// `TagOnly` 是回写期的错误，那时没有"坏字节"，定位靠 tag。
enum Locator {
  Site(Int)
  /// 被指控"指向块外"的那个指针值本身；三条指针类错误各自的不成立判据不同，
  /// 这里只数数，不拿块长去要求它。
  Pointer
  TagOnly
}

///|
/// 23 个变体一个一个表态，故意为没有 `_` 的穷尽匹配。
///
/// 以后新增一条错误，编译器会逼着在这里说它是哪一类——
/// "每条错误都带定位信息"这句话才不会只剩文案里的一句承诺。
fn locator(e : @moonmeta.MetaError) -> Locator {
  match e {
    @moonmeta.TooShort(off, _, _) => Site(off)
    @moonmeta.BadTiffHeader(off) => Site(off)
    @moonmeta.BadByteOrder(off) => Site(off)
    @moonmeta.IfdOffsetOutOfRange(_) => Pointer
    @moonmeta.EntryTooLarge(off, _, _, _) => Site(off)
    @moonmeta.ValueOffsetOutOfRange(_, _) => Pointer
    @moonmeta.UnsupportedType(_, _) => TagOnly
    @moonmeta.SubIfdOutOfRange(_, _) => Pointer
    @moonmeta.UnencodableText(_, _) => TagOnly
    @moonmeta.TypeMismatch(_, _) => TagOnly
    @moonmeta.ValueOutOfRange(_, _) => TagOnly
    @moonmeta.NotJpeg(off) => Site(off)
    @moonmeta.SegmentTooLarge(off, _, _) => Site(off)
    @moonmeta.TruncatedAt(off) => Site(off)
    @moonmeta.SegmentOverflow(off, _, _) => Site(off)
    @moonmeta.ExtraMetadata(off) => Site(off)
    @moonmeta.NotPng(off) => Site(off)
    @moonmeta.BadChecksum(off, _, _) => Site(off)
    // ifd0 偏移过 check_ifd_offset 的验，所以这一条是块内偏移而不是指针
    @moonmeta.TiffNotByteExact(off, _, _) => Site(off.to_int())
    // 冲突区间的起点出自守卫清单，清单里的偏移都过了解析侧的边界检查。
    @moonmeta.TiffInplaceShared(_, from, _, _, _) => Site(from)
    // 走到第二次的那张表，偏移同样来自已过界的指针。
    @moonmeta.TiffInplaceCycle(off) => Site(off)
    // 这一条反过来：报错就是因为像素声明里那两个数字不可信，
    // 拿块长去要求它反而是错的。定位只能靠 tag。
    @moonmeta.TiffInplaceOpaque(_, _) => TagOnly
    @moonmeta.UnknownFormat(off) => Site(off)
  }
}

///|
/// 扫过的每一格都记在这里，最后既打印又设地板。
///
/// 地板不是装饰：输入集一旦被改小（少一个种子、少一轮截断），
/// 上面三条性质会同时变成空话而测试仍然全绿。
struct Sweep {
  mut inputs : Int
  mut raised : Int
  mut sites : Int
  mut pointers : Int
  mut tag_only : Int
  mut decoded : Int
  mut redacted : Int
  mut stripped : Int
  mut inplace_redacted : Int
  mut inplace_stripped : Int
}

///|
fn new_sweep() -> Sweep {
  {
    inputs: 0,
    raised: 0,
    sites: 0,
    pointers: 0,
    tag_only: 0,
    decoded: 0,
    redacted: 0,
    stripped: 0,
    inplace_redacted: 0,
    inplace_stripped: 0,
  }
}

///|
/// 一条被拒的错误：先按性质归类，再当场验它说得出地方。
fn tally(
  e : @moonmeta.MetaError,
  len : Int,
  at : String,
  s : Sweep,
) -> Unit raise {
  s.raised = s.raised + 1
  match locator(e) {
    Site(off) => {
      s.sites = s.sites + 1
      if off < 0 || off > len {
        fail(
          "\{at} 报的错误声称坏在第 \{off} 字节，可那块只有 \{len} 字节长：\{e}",
        )
      }
    }
    Pointer => s.pointers = s.pointers + 1
    TagOnly => s.tag_only = s.tag_only + 1
  }
}

///|
fn no_span(o : (Int, Int)?) -> Bool {
  match o {
    None => true
    Some(_) => false
  }
}

///|
/// 性质 3 的前两半：产物读得回来，而且再审一遍一条敏感都没有。
fn check_redacted(
  data : Bytes,
  out : Bytes,
  rep : @moonmeta.Redaction,
  at : String,
  s : Sweep,
) -> Unit raise {
  s.redacted = s.redacted + 1
  try @moonmeta.decode_any(out) catch {
    e =>
      fail(
        "\{at} 的脱敏产物自己读不回来（\{data.length()}B→\{out.length()}B）：\{e}",
      )
  } noraise {
    (_, block) =>
      match block {
        None => ()
        Some(b) => {
          let left = b.findings(@moonmeta.strict_policy())
          if left.length() > 0 {
            fail(
              "\{at} 脱敏之后还能审出 \{left.length()} 条敏感条目",
            )
          }
        }
      }
  }
  // 什么都没删，就不许动文件：这条对畸形输入同样成立，不是只对夹具成立。
  let untouched = rep.removed.length() == 0 &&
    !rep.dropped_xmp &&
    !rep.dropped_thumbnail
  if untouched && out != data {
    fail(
      "\{at} 一条都没删，产物却和输入不同（\{data.length()}B→\{out.length()}B）",
    )
  }
  // 幂等：第二次删不许有任何新收获——有的话第一次就是假脱敏。
  try @moonmeta.redact_any(out, @moonmeta.strict_policy()) catch {
    e => fail("\{at} 的产物过不了第二次脱敏：\{e}")
  } noraise {
    (out2, rep2) => {
      let rewrote = out2 != out
      let gained = rep2.removed.length() > 0 ||
        rep2.dropped_xmp ||
        rep2.dropped_thumbnail
      if rewrote || gained {
        fail(
          "\{at} 脱敏不幂等：第二次又删掉 \{rep2.removed.length()} 条",
        )
      }
    }
  }
}

///|
/// `strip` 之后，从一个读者的角度看文件里不该再有元数据。
fn check_stripped(out : Bytes, at : String, s : Sweep) -> Unit raise {
  s.stripped = s.stripped + 1
  try @moonmeta.decode_any(out) catch {
    e => fail("\{at} 拆完的产物自己读不回来：\{e}")
  } noraise {
    (_, block) =>
      match block {
        None => ()
        Some(b) => {
          let left = b.ifd0.length() +
            b.exif.length() +
            b.gps.length() +
            b.interop.length()
          if left > 0 || b.has_ifd1 {
            fail("\{at} strip 之后目录里还剩 \{left} 条")
          }
        }
      }
  }
  // 目录空了还不够：容器里那段 EXIF / 那一包 XMP 也得真的不在。
  match @moonmeta.sniff(out) {
    Some(@moonmeta.Jpeg) =>
      try @moonmeta.jpeg_inspect(out) catch {
        e => fail("\{at} 拆完之后连段表都走不动：\{e}")
      } noraise {
        m =>
          if !no_span(m.exif) || m.has_xmp || m.xmp.length() > 0 {
            fail(
              "\{at} strip 之后容器里还有元数据段：" + m.describe(),
            )
          }
      }
    Some(@moonmeta.Png) =>
      try @moonmeta.png_inspect(out) catch {
        e => fail("\{at} 拆完之后连块表都走不动：\{e}")
      } noraise {
        m =>
          if !no_span(m.exif) || m.has_xmp {
            fail(
              "\{at} strip 之后容器里还有元数据块：" + m.describe(),
            )
          }
      }
    _ => ()
  }
}

///|
/// 原位那条路的检查。
///
/// 长度不变是它对用户的全部承诺，所以这一格先钉字节、再钉读得回来：
/// 搬了字节就不叫原位，哪怕产物本身没问题。
/// 剩下的条目不许是敏感条目——这一条与重写路径同宽；至于像素声明那一批
/// 必须留着，那是 `ci/inplace_crosscheck.py` 对着真文件核的事，
/// 拿它当"审不剩敏感"来断言会把两种口径混成一种。
fn check_inplace(
  data : Bytes,
  out : Bytes,
  removed : Bool,
  decoded : Bool,
  at : String,
) -> Unit raise {
  if out.length() != data.length() {
    fail(
      "\{at} 说好了不搬字节，长度却从 \{data.length()} 变成 \{out.length()}",
    )
  }
  // 什么都没删就不许动文件——空策略、以及策略只覆盖时间戳却喂 strict 之外
  // 的输入，两种形状都从这里过。
  if !removed && out != data {
    fail("\{at} 一条都没删，产物却和输入不同")
  }
  if !decoded {
    // 原位这条路故意能吃下 decode_any 会拒绝的文件（不认识的类型码也要
    // 能摘掉），所以输入本身读不回来时，后面那两句没有对象。
    return
  }
  try @moonmeta.decode_any(out) catch {
    e => fail("\{at} 的产物自己读不回来：\{e}")
  } noraise {
    (_, block) =>
      match block {
        None => ()
        Some(b) => {
          let left = b.findings(@moonmeta.strict_policy())
          if left.length() > 0 {
            fail("\{at} 之后还能审出 \{left.length()} 条敏感条目")
          }
        }
      }
  }
}

///|
/// 一份输入进来，七个入口全部走一遍。
///
/// `sniff` 是全函数，没有 catch：它一旦抛，整个测试进程当场挂掉，
/// 那正是性质 1 要的样子。
fn probe(data : Bytes, at : String, s : Sweep) -> Unit raise {
  s.inputs = s.inputs + 1
  let len = data.length()
  let _ = @moonmeta.sniff(data)
  let decoded_at = s.decoded
  try @moonmeta.decode_any(data) catch {
    e => tally(e, len, "\{at} decode_any", s)
  } noraise {
    _ => s.decoded = s.decoded + 1
  }
  // 读不通的输入不是"删完还读得回来"这句话的对象：原位那两条入口故意
  // 能吃下 decode_any 拒绝的文件（不认识的类型码也要能摘掉），所以这一票
  // 只能按输入自己能不能读来打。
  let decoded = s.decoded > decoded_at
  try @moonmeta.describe_container(data) catch {
    e => tally(e, len, "\{at} describe_container", s)
  } noraise {
    _ => ()
  }
  try @moonmeta.redact_any(data, @moonmeta.strict_policy()) catch {
    e => tally(e, len, "\{at} redact_any", s)
  } noraise {
    (out, rep) => check_redacted(data, out, rep, at, s)
  }
  try @moonmeta.strip_any(data) catch {
    e => tally(e, len, "\{at} strip_any", s)
  } noraise {
    (out, _) => check_stripped(out, at, s)
  }
  try @moonmeta.tiff_redact_inplace(data, @moonmeta.strict_policy()) catch {
    e => tally(e, len, "\{at} tiff_redact_inplace", s)
  } noraise {
    (out, rep) => {
      s.inplace_redacted = s.inplace_redacted + 1
      check_inplace(
        data,
        out,
        rep.removed.length() > 0 || rep.dropped_xmp,
        decoded,
        "\{at} tiff_redact_inplace",
      )
    }
  }
  try @moonmeta.tiff_strip_inplace(data) catch {
    e => tally(e, len, "\{at} tiff_strip_inplace", s)
  } noraise {
    (out, had) => {
      s.inplace_stripped = s.inplace_stripped + 1
      check_inplace(
        data,
        out,
        had.had_exif || had.dropped_xmp,
        decoded,
        "\{at} tiff_strip_inplace",
      )
    }
  }
}

///|
/// 种子：库能读出来的每一种形状，各自都带敏感数据（或故意不带）。
fn seeds() -> Array[(String, Bytes)] raise {
  let t = fixture()
  let jpg = jpeg_with(Some(t))
  let both = append_xmp_app1(jpg) catch {
    e => fail("造不出 EXIF+XMP 双包夹具：\{e}")
  }
  [
    ("TIFF/MM", t),
    ("TIFF/interop", interop_fixture()),
    ("JPEG+EXIF", jpg),
    ("JPEG 无元数据", jpeg_with(None)),
    ("JPEG+EXIF+XMP", both),
    ("PNG+EXIF+XMP", png_with(Some(t))),
    ("PNG 只有 XMP", png_with(None)),
  ]
}

///|
/// 单字节改写的取值：0x00 最小化、0x01 最小非零、0x02 与 0x05 是 ASCII / RATIONAL
/// 两个最常用的类型码、0x0f 把 SHORT 改成不可解的 15、0x80 是符号位、
/// 0xe1 是 APP1 段码、0xff 是段码与计数域的饱和值。
fn patch_values() -> Array[Byte] {
  [0x00, 0x01, 0x02, 0x05, 0x0f, 0x80, 0xe1, 0xff]
}

///|
/// 覆盖地板。少了哪一格，上面三条性质就有对应的部分正在变成空话。
fn floor(what : String, got : Int, least : Int) -> Unit raise {
  if got < least {
    fail(
      "扫描覆盖不足：\{what} 只跑到 \{got}，地板 \{least}——性质断言正在变成空话",
    )
  }
}

///|
test "畸形输入：不 panic、错误可追问、删完还读得回来" {
  let s = new_sweep()
  let pv = patch_values()
  for seed in seeds() {
    let (name, data) = seed
    let n = data.length()
    // 1) 空文件与每一个前缀：截断是最常见的畸形
    for i = 0; i <= n; i = i + 1 {
      probe(Bytes::from_array(span(data, 0, i)), "\{name} 前\{i}B", s)
    }
    // 2) 每一个字节的单字节改写：长度域、计数、类型码、指针都在这轮里被撒谎
    let all = data.to_array()
    for i = 0; i < n; i = i + 1 {
      for k = 0; k < pv.length(); k = k + 1 {
        let v = pv[k]
        if all[i] != v {
          // 每一份都现拼：共享底层数组会让上一处改写漏进下一份输入
          let buf : Array[Byte] = []
          push(buf, span(data, 0, i))
          push(buf, [v])
          push(buf, span(data, i + 1, n))
          probe(
            Bytes::from_array(buf),
            "\{name} 第\{i}字节→第\{k}号值",
            s,
          )
        }
      }
    }
    // 3) 追加一个字节：让声明的长度和真实长度错开
    for k = 0; k < pv.length(); k = k + 1 {
      let tail = data.to_array()
      tail.push(pv[k])
      probe(Bytes::from_array(tail), "\{name} 尾部+第\{k}号值", s)
    }
  }
  println(
    "畸形输入扫描：输入 \{s.inputs} 份，拒绝 \{s.raised} 次，读通 \{s.decoded} 次，脱敏产出 \{s.redacted} 份，拆解产出 \{s.stripped} 份",
  )
  println(
    "  定位分类：块内偏移 \{s.sites} 条，越界指针 \{s.pointers} 条，只有 tag \{s.tag_only} 条",
  )
  println(
    "  原位两路：脱敏产出 \{s.inplace_redacted} 份，拆解产出 \{s.inplace_stripped} 份",
  )
  // 地板：扫描一旦不再覆盖这些形状，上面所有断言都会悄悄变成空话。
  // 数值取实测基线的约三分之二（基线：12000 / 45119 / 37685 / 5882 / 1552 /
  // 6084 / 4889 / 6133 / 原位 1233 / 1226），只朝一个方向咬：覆盖率掉了才红，
  // 加了不会红。
  floor("输入份数", s.inputs, 8000)
  floor("被拒次数", s.raised, 15000)
  floor("块内偏移条数", s.sites, 12000)
  floor("越界指针条数", s.pointers, 2000)
  floor("只有 tag 的条数", s.tag_only, 500)
  floor("读通次数", s.decoded, 3000)
  floor("脱敏产出次数", s.redacted, 2500)
  floor("拆解产出次数", s.stripped, 3000)
  floor("原位脱敏产出次数", s.inplace_redacted, 800)
  floor("原位拆解产出次数", s.inplace_stripped, 800)
}
