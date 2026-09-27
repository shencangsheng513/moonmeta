// 回写：把 IR 重新编码成一段合法的 TIFF 字节块。
//
// 与"把整段 APP1 换掉"的区别在于逐条目重发：本库不认识的 tag
// （包括厂商私有 tag）会原样带上，只重算偏移。有意丢弃的只有两样：
// 缩略图目录链，以及指向旧布局的缩略图指针 tag。

///|
priv struct Enc {
  tag : Int
  type_code : Int
  count : Int
  bytes : Array[Byte]
  /// >= 0 时这是一个指向第 `ptr` 个子目录的指针，偏移在布局定下后回填。
  ptr : Int
}

///|
priv struct Planned {
  enc : Enc
  /// >= 0 时值放在外部值区的这个偏移；-1 表示 4 字节内联。
  ext : Int
}

///|
/// 重新编码。字节序沿用 `block.little`；tag 按升序写入（TIFF 要求）。
pub fn encode_tiff(block : TiffBlock) -> Bytes raise MetaError {
  let little = block.little
  let dir0 = entries_of(block.ifd0, true, little)
  let dire = entries_of(block.exif, false, little)
  let dirg = entries_of(block.gps, false, little)
  let diri = entries_of(block.interop, false, little)
  let has_g = dirg.length() > 0
  let has_i = diri.length() > 0
  // 只有 Interop 没有别的 Exif 条目时也得造一张 Exif 表：0xA005 挂在那里。
  let has_e = dire.length() > 0 || has_i
  if has_e {
    dir0.push(ptr_entry(tag_exif_ifd, 0))
  }
  if has_g {
    dir0.push(ptr_entry(tag_gps_ifd, 1))
  }
  if has_i {
    dire.push(ptr_entry(tag_interop_ifd, 2))
  }
  dir0.sort_by(by_tag)
  dire.sort_by(by_tag)
  dirg.sort_by(by_tag)
  diri.sort_by(by_tag)
  let size0 = 2 + 12 * dir0.length() + 4
  let size_e = 2 + 12 * dire.length() + 4
  let size_g = 2 + 12 * dirg.length() + 4
  let size_i = 2 + 12 * diri.length() + 4
  let offe = 8 + size0
  let offg = offe + (if has_e { size_e } else { 0 })
  let offi = offg + (if has_g { size_g } else { 0 })
  let vstart = offi + (if has_i { size_i } else { 0 })
  let (p0, cur) = plan_dir(dir0, vstart)
  let (pe, cur2) = plan_dir(dire, cur)
  let (pg, cur3) = plan_dir(dirg, cur2)
  let (pi, _) = plan_dir(diri, cur3)
  let out : Array[Byte] = []
  if little {
    out.push(b'I')
    out.push(b'I')
  } else {
    out.push(b'M')
    out.push(b'M')
  }
  put_u16(out, 42, little)
  put_u32(out, 8L, little)
  let sub_offs = [offe, offg, offi]
  emit_dir(out, p0, sub_offs, little)
  if has_e {
    emit_dir(out, pe, sub_offs, little)
  }
  if has_g {
    emit_dir(out, pg, sub_offs, little)
  }
  if has_i {
    emit_dir(out, pi, sub_offs, little)
  }
  emit_values(out, [p0, pe, pg, pi], vstart)
  Bytes::from_array(out)
}

///|
fn by_tag(a : Enc, b : Enc) -> Int {
  a.tag - b.tag
}

///|
fn entries_of(
  entries : Array[IfdEntry],
  drop_thumb_ptrs : Bool,
  little : Bool,
) -> Array[Enc] raise MetaError {
  let out : Array[Enc] = []
  for e in entries {
    if drop_thumb_ptrs &&
      (e.tag == tag_thumb_offset || e.tag == tag_thumb_length) {
      // 缩略图字节不会被重发，指针留着就是悬空引用。
      continue
    }
    out.push(enc_entry(e, little))
  }
  out
}

///|
fn enc_entry(e : IfdEntry, little : Bool) -> Enc raise MetaError {
  let (count, bytes) = value_bytes(e.tag, e.type_code, e.value, little)
  { tag: e.tag, type_code: e.type_code, count, bytes, ptr: -1, }
}

///|
fn ptr_entry(tag : Int, which : Int) -> Enc {
  {
    tag,
    type_code: 4,
    count: 1,
    bytes: [b'\x00', b'\x00', b'\x00', b'\x00'],
    ptr: which,
  }
}

///|
/// 给每个条目定下放不下的下标：4 字节以内内联，否则进值区（4 字节对齐）。
fn plan_dir(entries : Array[Enc], cursor_in : Int) -> (Array[Planned], Int) {
  let out : Array[Planned] = []
  let mut cursor = cursor_in
  for e in entries {
    let n = e.bytes.length()
    if n <= 4 {
      out.push({ enc: e, ext: -1, })
    } else {
      out.push({ enc: e, ext: cursor, })
      cursor = cursor + (n + 3) / 4 * 4
    }
  }
  (out, cursor)
}

///|
fn emit_dir(
  out : Array[Byte],
  planned : Array[Planned],
  sub_offs : Array[Int],
  little : Bool,
) -> Unit {
  put_u16(out, planned.length(), little)
  for p in planned {
    put_u16(out, p.enc.tag, little)
    put_u16(out, p.enc.type_code, little)
    put_u32(out, p.enc.count.to_int64(), little)
    if p.enc.ptr >= 0 {
      put_u32(out, sub_offs[p.enc.ptr].to_int64(), little)
    } else if p.ext >= 0 {
      put_u32(out, p.ext.to_int64(), little)
    } else {
      let mut i = 0
      while i < 4 {
        out.push(
          if i < p.enc.bytes.length() {
            p.enc.bytes[i]
          } else {
            b'\x00'
          },
        )
        i = i + 1
      }
    }
  }
  // 下一目录指针：缩略图链被有意丢弃，所以恒为 0。
  put_u32(out, 0L, little)
}

///|
/// 值区：按目录顺序把外部值依次落位。传目录列表而不是逐个参数，
/// 是为了让"加了第四张表却忘了写它的值"这类错误不可能发生。
fn emit_values(
  out : Array[Byte],
  dirs : Array[Array[Planned]],
  vstart : Int,
) -> Unit {
  let mut written = vstart
  for d in dirs {
    for p in d {
      written = spill(out, p, written)
    }
  }
}

///|
fn spill(out : Array[Byte], p : Planned, written : Int) -> Int {
  if p.ext < 0 {
    written
  } else {
    let mut w = written
    while w < p.ext {
      // plan_dir 按 4 字节对齐推进，这里补齐空洞。
      out.push(b'\x00')
      w = w + 1
    }
    for b in p.enc.bytes {
      out.push(b)
      w = w + 1
    }
    w
  }
}

///|
/// 值的字节与组件个数。`(type_code, value)` 形状不配对就报错——
/// `IfdEntry` 是可以外部构造的，静默写坏照片是最坏的结果。
fn value_bytes(
  tag : Int,
  type_code : Int,
  value : TagValue,
  little : Bool,
) -> (Int, Array[Byte]) raise MetaError {
  match (type_code, value) {
    (2, Text(s)) => {
      let bytes : Array[Byte] = []
      for ch in s {
        let cp = ch.to_int()
        if cp > 255 {
          raise UnencodableText(tag, cp)
        }
        bytes.push(cp.to_byte())
      }
      // 一个字节都不补：读侧已经把 count 个字节（含结尾 NUL、含填充 NUL）
      // 原样交过来了，这里再补一个就会把"没有结尾 NUL"的条目撑长一字节。
      // 自己构造 Text 又要符合 EXIF 惯例的话，结尾的 NUL 由构造方带上。
      (bytes.length(), bytes)
    }
    (1 | 6 | 7, Raw(bs)) => {
      let bytes : Array[Byte] = []
      for b in bs {
        bytes.push(b)
      }
      (bytes.length(), bytes)
    }
    (3 | 8, Shorts(vs)) => {
      let bytes : Array[Byte] = []
      for n in vs {
        check_u16(tag, type_code, n)
        put_u16(bytes, n, little)
      }
      (vs.length(), bytes)
    }
    (4 | 9, Longs(vs)) => {
      let bytes : Array[Byte] = []
      for n in vs {
        check_u32(tag, type_code, n)
        put_u32(bytes, wrap32(n, type_code), little)
      }
      (vs.length(), bytes)
    }
    (5 | 10, Rationals(rs)) => {
      let bytes : Array[Byte] = []
      for r in rs {
        check_u32(tag, type_code, r.num)
        check_u32(tag, type_code, r.den)
        put_u32(bytes, wrap32(r.num, type_code), little)
        put_u32(bytes, wrap32(r.den, type_code), little)
      }
      (rs.length(), bytes)
    }
    _ =>
      match type_size(type_code) {
        None => raise UnsupportedType(tag, type_code)
        Some(_) => raise TypeMismatch(tag, type_code)
      }
  }
}

///|
/// 有符号类型码下的值可能为负；写进文件前绕回无符号表示。
fn wrap32(v : Int64, type_code : Int) -> Int64 {
  if type_code == 9 || type_code == 10 {
    if v < 0L {
      v + 4294967296L
    } else {
      v
    }
  } else {
    v
  }
}

///|
fn check_u16(tag : Int, type_code : Int, v : Int) -> Unit raise MetaError {
  let lo = if type_code == 8 { -32768 } else { 0 }
  let hi = if type_code == 8 { 32767 } else { 65535 }
  if v < lo || v > hi {
    raise ValueOutOfRange(tag, v.to_int64())
  }
}

///|
fn check_u32(tag : Int, type_code : Int, v : Int64) -> Unit raise MetaError {
  let lo = if type_code == 9 || type_code == 10 { -2147483648L } else { 0L }
  let hi = if type_code == 9 || type_code == 10 {
    2147483647L
  } else {
    4294967295L
  }
  if v < lo || v > hi {
    raise ValueOutOfRange(tag, v)
  }
}

///|
fn put_u16(out : Array[Byte], v : Int, little : Bool) -> Unit {
  let lo = (v & 0xff).to_byte()
  let hi = ((v >> 8) & 0xff).to_byte()
  if little {
    out.push(lo)
    out.push(hi)
  } else {
    out.push(hi)
    out.push(lo)
  }
}

///|
fn put_u32(out : Array[Byte], v : Int64, little : Bool) -> Unit {
  let b0 = (v & 255L).to_byte()
  let b1 = ((v >> 8) & 255L).to_byte()
  let b2 = ((v >> 16) & 255L).to_byte()
  let b3 = ((v >> 24) & 255L).to_byte()
  if little {
    out.push(b0)
    out.push(b1)
    out.push(b2)
    out.push(b3)
  } else {
    out.push(b3)
    out.push(b2)
    out.push(b1)
    out.push(b0)
  }
}
