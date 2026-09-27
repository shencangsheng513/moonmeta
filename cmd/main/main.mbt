// moonmeta 的命令行前端。
//
// 这里刻意只做三件事：读文件、调库、把结果打成人能读的样子。
// "删什么"的判断全在库里——CLI 一旦也有一份策略，库和命令行的说法就会分叉，
// 而脱敏工具最怕的就是同一份文件两种口径。
//
// 一条硬规矩：写操作不覆盖输入文件。输出默认落在
// `<原名>.redacted.<后缀>`；想就地改必须明说 `--force`。

///|
enum Action {
  Read
  Audit
  Redact
  Strip
}

///|
struct Request {
  action : Action
  path : String
  out : String?
  policy : String
  force : Bool
  keep_bytes : Bool
  json : Bool
}

///|
/// 决定"走哪条写路"要用的三件事，打包传：旗标、容器、以及这份文件里有没有
/// 一条原地模式不碰的目录链。第三件必须一起传：只报 `dropped_thumbnail: false`
/// 说不清"没有链"和"有链但这次不动它"。
struct WriteMode {
  keep_bytes : Bool
  kind : @lib.Kind
  chain : Bool
}

///|
fn write_mode(req : Request, kind : @lib.Kind, chain : Bool) -> WriteMode {
  { keep_bytes: req.keep_bytes, kind, chain, }
}

///|
fn main {
  let code = run(strip_program_name(@env.args()))
  if code != 0 {
    @sys.exit(code)
  }
}

///|
fn strip_program_name(argv : Array[String]) -> Array[String] {
  match argv {
    [_, .. rest] => rest.to_owned()
    [] => []
  }
}

///|
/// 命令行的全部逻辑收在这里：只返回退出码，不自己退出。
/// 这样以后要给 `run` 加测试，不用先把进程杀掉。
fn run(argv : Array[String]) -> Int {
  let cmd = command()
  let parsed = cmd.parse(argv~, env=Map([])) catch {
    _ => {
      println("参数解析失败，见上方用法")
      return 2
    }
  }
  match to_request(parsed) {
    None => {
      println(cmd.render_help())
      2
    }
    Some(req) => execute(req)
  }
}

///|
fn command() -> @argparse.Command {
  @argparse.Command(
    "moonmeta",
    about="读 / 审 / 删 JPEG·PNG·TIFF 里的 EXIF 元数据",
    version="moonmeta 0.1.0",
    subcommand_required=true,
    subcommands=[
      @argparse.Command(
        "read",
        about="列出容器结构与每一条元数据，不改动文件",
        positionals=[
          @argparse.PositionArg("file", about="要看的图片文件"),
        ],
        flags=[json_flag()],
      ),
      @argparse.Command(
        "audit",
        about="只报告按策略会被删掉的条目，不改动文件",
        positionals=[
          @argparse.PositionArg("file", about="要审计的图片文件"),
        ],
        options=[policy_option()],
        flags=[json_flag()],
      ),
      @argparse.Command(
        "redact",
        about="按策略逐条删除，结果写到新文件",
        positionals=[
          @argparse.PositionArg("file", about="要脱敏的图片文件"),
        ],
        options=[policy_option(), output_option()],
        flags=[force_flag(), keep_bytes_flag()],
      ),
      @argparse.Command(
        "strip",
        about="整段摘掉元数据，结果写到新文件",
        positionals=[@argparse.PositionArg("file", about="要清空的文件")],
        options=[output_option()],
        flags=[force_flag(), keep_bytes_flag()],
      ),
    ],
  )
}

///|
fn policy_option() -> @argparse.OptionArg {
  @argparse.OptionArg(
    "policy",
    about="privacy（默认，保留时间戳）或 strict（连时间一起清）",
  )
}

///|
fn output_option() -> @argparse.OptionArg {
  @argparse.OptionArg(
    "output",
    short='o',
    about="输出路径；不给就在原名上加 .redacted / .stripped",
  )
}

///|
fn force_flag() -> @argparse.FlagArg {
  @argparse.FlagArg(
    "force",
    about="允许把结果写回输入文件，默认不允许",
  )
}

///|
/// 裸 TIFF 的两条写路：重建整份文件（默认），或者一个字节都不搬、
/// 只把目录表原地收缩。后者能处理真实照片（IFD 后面就是像素），
/// 代价是缩略图链与像素都不碰，所以删不完的东西也就不假装删完了。
fn keep_bytes_flag() -> @argparse.FlagArg {
  @argparse.FlagArg(
    "keep-bytes",
    about="裸 TIFF 改为原位收缩目录：文件长度不变，像素与缩略图一个字节不动",
  )
}

///|
/// 给人看的措辞以后还会改，脚本不该依赖它。`--json` 输出稳定、纯 ASCII，
/// 供 CI 与外部工具（如 Pillow 对拍）机读。
fn json_flag() -> @argparse.FlagArg {
  @argparse.FlagArg(
    "json",
    about="以单行 JSON 输出，供脚本与对拍使用",
  )
}

///|
fn to_request(matches : @argparse.Matches) -> Request? {
  match matches.subcommand {
    None => None
    Some((name, sub)) => {
      let action = match name {
        "read" => Read
        "audit" => Audit
        "redact" => Redact
        "strip" => Strip
        _ => return None
      }
      match one(sub, "file") {
        None => None
        Some(path) =>
          Some({
            action,
            path,
            out: one(sub, "output"),
            policy: or_else(one(sub, "policy"), "privacy"),
            force: sub.flags.get("force") == Some(true),
            keep_bytes: sub.flags.get("keep-bytes") == Some(true),
            json: sub.flags.get("json") == Some(true),
          })
      }
    }
  }
}

///|
fn one(m : @argparse.Matches, key : String) -> String? {
  match m.values.get(key) {
    Some(v) if v.length() > 0 => Some(v[0])
    _ => None
  }
}

///|
fn or_else(o : String?, d : String) -> String {
  match o {
    Some(s) => s
    None => d
  }
}

///|
fn execute(req : Request) -> Int {
  let data = @fs.read_file_to_bytes(req.path) catch {
    e => {
      println("\{req.path}: 读取失败：\{io_text(e)}")
      return 1
    }
  }
  let p = match policy_of(req.policy) {
    None => {
      println("未知策略 \{req.policy}：可用的是 privacy 或 strict")
      return 2
    }
    Some(p) => p
  }
  let decoded = @lib.decode_any(data) catch {
    e => {
      println("\{req.path}: \{e}")
      return 1
    }
  }
  dispatch(req, data, decoded.0, decoded.1, p)
}

///|
/// 打错字的策略不能悄悄退回默认值：`--policy strick` 若按 privacy 执行，
/// 用户会以为时间戳也清了。
fn policy_of(name : String) -> @lib.Policy? {
  match name {
    "privacy" => Some(@lib.privacy_policy())
    "strict" => Some(@lib.strict_policy())
    _ => None
  }
}

///|
fn io_text(e : @fs.IOError) -> String {
  @debug.to_string(e)
}

///|
/// 容器层面"逐条清单装不下"的那几件事，一次走查取回。
///
/// `xmp`/`iptc` 是成包的副本，策略覆盖载体时会被整包摘除；
/// `unread` 是我们既读不了也不会删的段/块。三种状态各有各的一句话，
/// 都不能从 `findings` 的长度推出来——那正是"报告上一切正常、实际什么都没脱"
/// 那种事故的形状。
struct Notes {
  xmp : Bool
  iptc : Bool
  unread : Array[String]
}

///|
fn empty_notes() -> Notes {
  { xmp: false, iptc: false, unread: [], }
}

///|
/// 容器里另有一包 XMP / IPTC 吗？还有哪些段/块是我们没解析的？
fn notes_of(data : Bytes, kind : @lib.Kind) -> Notes {
  match kind {
    @lib.Jpeg =>
      try @lib.jpeg_inspect(data) catch {
        // 走查失败的文件在调用方那一侧本来就要报错，这里不额外发明第二套说法。
        _ => empty_notes()
      } noraise {
        m =>
          {
            xmp: m.has_xmp,
            iptc: m.has_iptc,
            unread: m.unread.map(s => "\{s.name()}@\{s.offset}"),
          }
      }
    @lib.Png =>
      try @lib.png_inspect(data) catch {
        _ => empty_notes()
      } noraise {
        m =>
          {
            xmp: m.has_xmp,
            // PNG 侧没有"成包的 IPTC"可摘：那套住在 Raw profile 文本块里，
            // 本库不解析它，它会以 `tEXt@偏移` 的形式出现在 unread 里。
            iptc: false,
            unread: m.unread.map(c => "\{c.kind}@\{c.offset}"),
          }
      }
    // 裸 TIFF 的 XMP / IPTC 都是 IFD0 里的一条（0x02bc / 0x83bb），
    // 逐条清单本来就看得见它们，所以这里不再重复交代一遍。
    @lib.Tiff => empty_notes()
  }
}

///|
fn dispatch(
  req : Request,
  data : Bytes,
  kind : @lib.Kind,
  block : @lib.TiffBlock?,
  p : @lib.Policy,
) -> Int {
  let notes = notes_of(data, kind)
  let mode = write_mode(req, kind, has_chain(block))
  match req.action {
    Read =>
      if req.json {
        println(read_json(req.path, kind, block, notes))
        0
      } else {
        show_read(req.path, kind, block, notes)
      }
    Audit =>
      if req.json {
        println(audit_json(req.path, req.policy, block, p, notes))
        0
      } else {
        show_audit(req.path, req.policy, block, p, notes)
      }
    Redact => redact_file(req, data, mode, p, notes)
    Strip => strip_file(req, data, mode)
  }
}

///|
/// `read --json` 的形状（键序固定，便于逐字节比对）：
/// {"file":..,"container":..,"xmp":false,"iptc":false,"unread":[],"exif":false}
/// 有 EXIF 时再给 byte_order / directories / has_ifd1 / gps。
/// `xmp`/`iptc`/`unread` 与 text 输出里那几句"另含…包""未解析段…"是同一件事：
/// 机器读者不该比人拿到的更少。
/// 坐标以字符串给出：`Double` 可能打印成非有限值，那会把整行 JSON 变成非法的。
fn read_json(
  path : String,
  kind : @lib.Kind,
  block : @lib.TiffBlock?,
  notes : Notes,
) -> String {
  let head = "{\"file\":" +
    json_str(path) +
    ",\"container\":" +
    json_str(kind_name(kind)) +
    ",\"xmp\":" +
    bool_json(notes.xmp) +
    ",\"iptc\":" +
    bool_json(notes.iptc) +
    ",\"unread\":" +
    arr_json(notes.unread)
  match block {
    None => head + ",\"exif\":false}"
    Some(b) =>
      head +
      ",\"exif\":true,\"byte_order\":" +
      json_str(if b.little { "II" } else { "MM" }) +
      ",\"directories\":[" +
      dir_json(@lib.Ifd0, b.ifd0) +
      "," +
      dir_json(@lib.Exif, b.exif) +
      "," +
      dir_json(@lib.Gps, b.gps) +
      "," +
      dir_json(@lib.Interop, b.interop) +
      "],\"has_ifd1\":" +
      bool_json(b.has_ifd1) +
      ",\"gps\":" +
      gps_json(b) +
      "}"
  }
}

///|
fn kind_name(kind : @lib.Kind) -> String {
  match kind {
    Jpeg => "jpeg"
    Png => "png"
    Tiff => "tiff"
  }
}

///|
fn gps_json(b : @lib.TiffBlock) -> String {
  match b.gps_lat_lon() {
    None => "null"
    Some((lat, lon)) => json_str(lat.to_string() + "," + lon.to_string())
  }
}

///|
fn dir_json(dir : @lib.Dir, entries : Array[@lib.IfdEntry]) -> String {
  let parts : Array[String] = []
  for e in entries {
    parts.push(entry_json(dir, e))
  }
  "{\"dir\":" +
  json_str(dir.label()) +
  ",\"entries\":[" +
  join_comma(parts) +
  "]}"
}

///|
/// 名字要按**这条条目所在的目录**查：编号 2 在 IFD0 是 `BitsPerSample`，
/// 在 GPS 目录是 `GPSLatitude`。写死一个目录会成片报错名字。
fn entry_json(dir : @lib.Dir, e : @lib.IfdEntry) -> String {
  "{\"tag\":" +
  e.tag.to_string() +
  ",\"name\":" +
  json_str(@lib.tag_name(dir, e.tag)) +
  ",\"type\":" +
  e.type_code.to_string() +
  ",\"value\":" +
  json_str(e.value.to_string()) +
  "}"
}

///|
fn join_comma(parts : Array[String]) -> String {
  let mut s = ""
  let n = parts.length()
  for i in 0..<n {
    s = s + parts[i]
    if i + 1 < n {
      s = s + ","
    }
  }
  s
}

///|
fn bool_json(b : Bool) -> String {
  if b {
    "true"
  } else {
    "false"
  }
}

///|
/// 字符串数组转 JSON 数组。每个元素都过 `json_str`：段名里也可能有非 ASCII，
/// 直接拼会把一整行 JSON 变成非法的。
fn arr_json(items : Array[String]) -> String {
  "[" + join_comma(items.map(s => json_str(s))) + "]"
}

///|
fn audit_json(
  path : String,
  name : String,
  block : @lib.TiffBlock?,
  p : @lib.Policy,
  notes : Notes,
) -> String {
  let found : Array[@lib.Removed] = match block {
    None => []
    Some(b) => b.findings(p)
  }
  let parts : Array[String] = []
  for r in found {
    parts.push(
      "{\"dir\":" +
      json_str(r.dir.label()) +
      ",\"tag\":" +
      r.tag.to_string() +
      ",\"name\":" +
      json_str(r.name) +
      ",\"category\":" +
      json_str(r.category.label()) +
      "}",
    )
  }
  // "xmp"/"iptc"/"unread" 是给机器读的那句"这里还有 findings 装不下的东西"。
  // 少了它们，findings 为空就分不清三种状态："没有敏感东西"、
  // "敏感东西在策略管不到的包里"、"在我们不读也不删的那些段里"。
  "{\"file\":" +
  json_str(path) +
  ",\"policy\":" +
  json_str(name) +
  ",\"xmp\":" +
  bool_json(notes.xmp) +
  ",\"iptc\":" +
  bool_json(notes.iptc) +
  ",\"unread\":" +
  arr_json(notes.unread) +
  ",\"exif\":" +
  bool_json(block != None) +
  ",\"findings\":[" +
  join_comma(parts) +
  "]}"
}

///|
/// 整串转义成纯 ASCII：非 ASCII 一律走 `\uXXXX`（超出 BMP 的拆成代理对）。
/// 中文文件名、ISO-8859-1 的 Make/Model 都不会把非法字节漏进输出。
fn json_str(s : String) -> String {
  let mut out = "\""
  for c in s.to_array() {
    let code = c.to_int()
    if c == '"' {
      out = out + "\\\""
    } else if c == '\\' {
      out = out + "\\\\"
    } else if code == 8 {
      out = out + "\\b"
    } else if code == 12 {
      out = out + "\\f"
    } else if code == 10 {
      out = out + "\\n"
    } else if code == 13 {
      out = out + "\\r"
    } else if code == 9 {
      out = out + "\\t"
    } else if code < 32 {
      out = out + "\\u00" + hex_nibbles(code, 2)
    } else if code < 128 {
      out = out + c.to_string()
    } else if code <= 0xFFFF {
      out = out + "\\u" + hex_nibbles(code, 4)
    } else {
      let v = code - 0x10000
      out = out +
        "\\u" +
        hex_nibbles(0xD800 + (v >> 10), 4) +
        "\\u" +
        hex_nibbles(0xDC00 + (v & 0x3FF), 4)
    }
  }
  out + "\""
}

///|
fn hex_nibbles(v : Int, count : Int) -> String {
  let mut s = ""
  let mut i = count - 1
  while i >= 0 {
    s = s + nibble((v >> (4 * i)) & 0xf)
    i = i - 1
  }
  s
}

///|
fn show_read(
  path : String,
  kind : @lib.Kind,
  block : @lib.TiffBlock?,
  notes : Notes,
) -> Int {
  println("\{path}：\{kind.to_string()}")
  match block {
    None => {
      println("  这个文件里没有 EXIF。")
      print_if(notes.xmp, read_xmp_note(false))
      print_if(notes.iptc, read_iptc_note(false))
      print_unread(notes)
      0
    }
    Some(b) => {
      dump_dir(@lib.Ifd0, b.ifd0)
      dump_dir(@lib.Exif, b.exif)
      dump_dir(@lib.Gps, b.gps)
      dump_dir(@lib.Interop, b.interop)
      match b.gps_lat_lon() {
        Some((lat, lon)) =>
          println("  折算坐标：\{lat.to_string()}, \{lon.to_string()}")
        None => ()
      }
      print_if(b.has_gps(), "  GPS 目录存在。")
      print_if(
        b.has_ifd1,
        "  另有缩略图目录（IFD1）：任何写操作都会整段丢掉它",
      )
      print_line(
        "  相机：\{or_else(b.make(), "?")} \{or_else(b.model(), "?")}",
      )
      print_if(notes.xmp, read_xmp_note(true))
      print_if(notes.iptc, read_iptc_note(true))
      print_unread(notes)
      0
    }
  }
}

///|
/// `read` 只摊开 EXIF 目录。包着的那一份它看不见，所以必须说出来——
/// "这个文件里没有 EXIF"和"这个文件没有元数据"是两回事。
fn read_xmp_note(has_exif : Bool) -> String {
  if has_exif {
    "  另含 XMP 包：read 不摊开它，逐条清单里也永远不会出现它。"
  } else {
    "  但容器里另有一包 XMP：read 只摊开 EXIF 目录，包里的东西用 audit 看。"
  }
}

///|
/// IPTC/Photoshop 包的同构那一句。
///
/// 不能省也不能和 XMP 混成一句：两者在写侧是同一条待遇（策略覆盖载体时都整包摘），
/// 但读侧是两个不同的包，只报一个就等于另一半没说。
fn read_iptc_note(has_exif : Bool) -> String {
  if has_exif {
    "  另含 IPTC/Photoshop 包：read 不摊开它，逐条清单里也永远不会出现它。"
  } else {
    "  但容器里另有一包 IPTC/Photoshop：read 只摊开 EXIF 目录，包里的东西用 audit 看。"
  }
}

///|
/// 我们没解析、也不会删的那些段/块，逐件点名。
///
/// 这一句是"未解析"三个字的兑现：不点名，用户看到"删除 0 条"就以为整个文件干净了。
fn print_unread(notes : Notes) -> Unit {
  if !notes.unread.is_empty() {
    println(
      "  未解析段 \{notes.unread.length()} 段（本库不读也不删）：\{join_comma(notes.unread)}",
    )
  }
}

///|
fn print_if(cond : Bool, line : String) -> Unit {
  if cond {
    println(line)
  }
}

///|
fn print_line(line : String) -> Unit {
  println(line)
}

///|
fn dump_dir(dir : @lib.Dir, entries : Array[@lib.IfdEntry]) -> Unit {
  println("  \{dir.label()} 目录（\{entries.length()} 条）")
  for e in entries {
    println(
      "    \{hex_tag(e.tag)} \{@lib.tag_name(dir, e.tag)} = \{e.value.to_string()}",
    )
  }
}

///|
fn show_audit(
  path : String,
  name : String,
  block : @lib.TiffBlock?,
  p : @lib.Policy,
  notes : Notes,
) -> Int {
  match block {
    None => {
      println("\{path}: 没有 EXIF，无需脱敏。")
      print_if(notes.xmp, carrier_note(p))
      print_if(notes.iptc, iptc_carrier_note(p))
      print_unread(notes)
      0
    }
    Some(b) => {
      let found = b.findings(p)
      println("\{path}: 策略 \{name} 命中 \{found.length()} 条。")
      for r in found {
        println(
          "  \{r.dir.label()}/\{r.name} (\{hex_tag(r.tag)}) → \{r.category.label()}",
        )
      }
      print_if(notes.xmp, carrier_note(p))
      print_if(notes.iptc, iptc_carrier_note(p))
      print_unread(notes)
      0
    }
  }
}

///|
/// XMP 包那一句交代，只在真的带包时打印（调用方用 print_if 把关）。
///
/// 这句话不能省：XMP 不是一条 IFD 条目，逐条清单里永远不会出现它。
fn carrier_note(p : @lib.Policy) -> String {
  if p.covers(@lib.Carrier) {
    "另含 XMP 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。"
  } else {
    "警告：另含 XMP 包，当前策略不碰它。里面常是同一批事实的第二份副本——拍摄时间、机型、署名。"
  }
}

///|
/// IPTC/Photoshop 包的同构那一句：写侧与 XMP 同一条待遇，所以两种状态都要说。
fn iptc_carrier_note(p : @lib.Policy) -> String {
  if p.covers(@lib.Carrier) {
    "另含 IPTC/Photoshop 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。"
  } else {
    "警告：另含 IPTC/Photoshop 包，当前策略不碰它。署名、版权与联系人常就在这包里。"
  }
}

///|
fn redact_file(
  req : Request,
  data : Bytes,
  mode : WriteMode,
  p : @lib.Policy,
  notes : Notes,
) -> Int {
  let (bytes, report) = redact_by(data, mode, p) catch {
    e => {
      println("\{req.path}: \{e}")
      return 1
    }
  }
  for r in report.removed {
    println("  - \{r.dir.label()}/\{r.name} (\{r.category.label()})")
  }
  let n = report.removed.length()
  println(
    "删除 \{n} 条\{thumbnail_note(report.dropped_thumbnail)}\{xmp_note(notes.xmp, report.dropped_xmp)}\{iptc_note(notes.iptc, report.dropped_iptc)}。",
  )
  print_unread(notes)
  write_result(req, bytes)
}

///|
/// 走哪条写路。
///
/// `--keep-bytes` 只有裸 TIFF 需要：JPEG / PNG 本来就是"只换装元数据的那一段"，
/// 其余字节原样搬回去。在那两种容器上这个旗标什么都不改，所以要说一句
/// "这里不适用"，而不是安静地按原路走——安静地接受一个被忽略的旗标，
/// 等于教会用户相信它生效了。
fn redact_by(
  data : Bytes,
  mode : WriteMode,
  p : @lib.Policy,
) -> (Bytes, @lib.Redaction) raise @lib.MetaError {
  if !choose_inplace(mode) {
    @lib.redact_any(data, p)
  } else {
    // 先落笔再声明：那句"长度不变"是做完的凭证。原位模式在半路拒绝时
    // （语料里真有一例：某个条目的类型码这一版不解码）如果话已经先说出去，
    // 用户拿到的就是"长度不变"+"我没做"两句同时成立的话。
    let done = @lib.tiff_redact_inplace(data, p)
    println(inplace_said(data.length(), mode.chain))
    done
  }
}

///|
/// 同上的 strip 版。那句承诺同样只能在落笔成功之后说。
fn strip_by(
  data : Bytes,
  mode : WriteMode,
) -> (Bytes, @lib.Strip) raise @lib.MetaError {
  if !choose_inplace(mode) {
    @lib.strip_any(data)
  } else {
    let done = @lib.tiff_strip_inplace(data)
    println(inplace_said(data.length(), mode.chain))
    done
  }
}

///|
fn choose_inplace(mode : WriteMode) -> Bool {
  if !mode.keep_bytes {
    false
  } else if mode.kind == @lib.Tiff {
    true
  } else {
    println(
      "这个容器是 \{mode.kind}，本来就不搬字节：--keep-bytes 在这里不改变任何行为。",
    )
    false
  }
}

///|
/// 原位模式做完了要当场声明自己的边界：长度没变是它的承诺，
/// 像素与缩略图链没动是它的代价。不说这一句，用户会以为
/// `--keep-bytes` 出来的文件和默认那条路等价。
///
/// "这一条链还在"必须由文件本身的结构说出来：`dropped_thumbnail` 在原地
/// 模式下永远是 false，它的意思是"这一次什么都没丢"，不是"这文件里没有"。
/// 把两者混为一谈，就是让用户以为缩略图里的第二份坐标也没了。
fn inplace_said(len : Int, chain : Bool) -> String {
  if chain {
    "原位模式：文件长度不变（\{len} 字节）。这份文件还有一条缩略图目录链，原位模式不碰它——里面可能另有一份坐标。要连它一起清只能走不带 --keep-bytes 的那条路，而那条路要求整份文件能被逐字节重建；重建不了的裸 TIFF 会在落笔前拒绝并说出会丢多少字节，那种文件两条路都清不到链里这一份。"
  } else {
    "原位模式：文件长度不变（\{len} 字节），像素与缩略图链一个字节未动（这个文件没有缩略图目录链）。"
  }
}

///|
fn has_chain(block : @lib.TiffBlock?) -> Bool {
  match block {
    Some(b) => b.has_ifd1
    None => false
  }
}

///|
/// XMP 包同样要单独交代：它不在逐条清单里，不写这一句就等于删了一整包没人知道。
///
/// 三个状态都要有落点："本来没有"什么都不说，"有但这份策略不删"必须警告。
/// 把后者按前者处理，就是让用户以为已经删干净。
fn xmp_note(present : Bool, dropped : Bool) -> String {
  if dropped {
    "，并整包摘除 XMP"
  } else if present {
    "；警告：XMP 包还在，当前策略不碰它"
  } else {
    ""
  }
}

///|
/// IPTC/Photoshop 包的同一段话。形状与 `xmp_note` 一模一样，但不共用函数：
/// 两句话要各自被测试逐字钉住，合并成一句参数的版本会让其中一格失去落点。
fn iptc_note(present : Bool, dropped : Bool) -> String {
  if dropped {
    "，并整包摘除 IPTC/Photoshop 包"
  } else if present {
    "；警告：IPTC/Photoshop 包还在，当前策略不碰它"
  } else {
    ""
  }
}

///|
/// 缩略图必须单独交代：它常自带一份 GPS，"删了主坐标却留着缩略图"
/// 是最常见的假脱敏。
fn thumbnail_note(dropped : Bool) -> String {
  if dropped {
    "，并丢掉可能自带坐标的缩略图"
  } else {
    ""
  }
}

///|
fn strip_file(req : Request, data : Bytes, mode : WriteMode) -> Int {
  let (bytes, had) = strip_by(data, mode) catch {
    e => {
      println("\{req.path}: \{e}")
      return 1
    }
  }
  println(
    if inplace_mode(mode) {
      inplace_strip_said(had, bytes)
    } else {
      strip_said(had)
    },
  )
  write_result(req, bytes)
}

///|
/// 走没走原位那条路。与 `choose_inplace` 同一判据，但不印任何东西：
/// 这句话要说两遍，第二遍不该把"这里不适用"再播报一次。
fn inplace_mode(mode : WriteMode) -> Bool {
  mode.keep_bytes && mode.kind == @lib.Tiff
}

///|
/// 原位 strip 说的是另一句话，因为它的承诺不一样。
///
/// 裸 TIFF 的图像说明（宽高、压缩、条带位置……）和元数据住在同一张 IFD0
/// 表里：把它们一起删，产物就不再是一张图——门禁在 104 份陌生 TIFF 里量到
/// 81 份因此解不出像素。所以这条路不许说"整段摘除"，它只能说"删掉所有不
/// 参与解码的条目"，并且把留下的那些数出来。数字从产物里读回来，
/// 不是从计划里抄：抄来的数只说明我们打算留什么。
fn inplace_strip_said(had : @lib.Strip, out : Bytes) -> String {
  let kept = kept_image_entries(out)
  let head = if had.had_exif || had.dropped_xmp || had.dropped_iptc {
    "原位摘除非解码条目：" + join_comma(strip_parts(had)) + "。"
  } else {
    "这个文件的 IFD0 里没有不参与解码的条目，一个字节都没改。"
  }
  if kept > 0 {
    "\{head}IFD0 里留着 \{kept} 条图像解码必需的字段（宽高/压缩/条带位置…）：裸 TIFF 的图像说明与元数据在同一张表里，'整段摘除'在这里做不到。"
  } else {
    head
  }
}

///|
/// 产物里 IFD0 还剩几条条目。子目录指针不算：`decode_tiff` 把它们当成结构
/// 摘出去了，剩下能数到的就真是"这张图怎么解出来"那部分。
fn kept_image_entries(out : Bytes) -> Int {
  let parsed = try @lib.decode_any(out) catch {
    _ => None
  } noraise {
    (_, b) => b
  }
  match parsed {
    Some(b) => b.ifd0.length()
    None => 0
  }
}

///|
/// 摘除之后怎么说。对拍脚本要拿这句话跟文件本身的事实比对，
/// 所以四个状态各有一句、且都不许多说。
fn strip_said(had : @lib.Strip) -> String {
  // "本来就没有"和"已清除"是两回事；说错这一句，整个工具就没人敢信了。
  // 三件事分开说：EXIF 摘干净而 XMP 或 IPTC 留着，都不叫摘干净。
  if had.had_exif || had.dropped_xmp || had.dropped_iptc {
    "元数据已整段摘除：" + join_comma(strip_parts(had)) + "。"
  } else {
    "这个文件本来就没有 EXIF，也没有 XMP 包与 IPTC 包。"
  }
}

///|
fn strip_parts(had : @lib.Strip) -> Array[String] {
  let parts : Array[String] = []
  if had.had_exif {
    parts.push("EXIF")
  }
  if had.dropped_xmp {
    parts.push("XMP 包")
  }
  if had.dropped_iptc {
    parts.push("IPTC/Photoshop 包")
  }
  parts
}

///|
fn write_result(req : Request, bytes : Bytes) -> Int {
  match output_path(req) {
    None => {
      println(
        "输出路径与输入相同；确实要就地修改请加 --force",
      )
      2
    }
    Some(path) =>
      if path == req.path && !req.force {
        println(
          "拒绝覆盖输入文件 \{req.path}；就地修改请加 --force",
        )
        2
      } else {
        let _ = @fs.write_bytes_to_file(path, bytes) catch {
          e => {
            println("写入 \{path} 失败：\{io_text(e)}")
            return 1
          }
        }
        println("已写出 \{path}")
        0
      }
  }
}

///|
/// 默认输出路径：在扩展名前加 `.redacted` / `.stripped`，这样绝不撞输入文件。
fn output_path(req : Request) -> String? {
  match req.out {
    Some(p) => Some(p)
    None => {
      let suffix = match req.action {
        Redact => ".redacted"
        Strip => ".stripped"
        _ => ""
      }
      if suffix == "" {
        None
      } else {
        Some(with_suffix(req.path, suffix))
      }
    }
  }
}

///|
fn with_suffix(path : String, suffix : String) -> String {
  match split_ext(path) {
    None => path + suffix
    Some((stem, ext)) => stem + suffix + ext
  }
}

///|
/// 在最后一个 `.` 处切开。点号必须落在最后一个分隔符之后，否则那是
/// `.hidden`、`..` 这类没有扩展名的路径，直接往后加后缀。
fn split_ext(path : String) -> (String, String)? {
  let chars = path.to_array()
  let sep = last_separator(chars)
  match last_index(chars, '.') {
    None => None
    Some(dot) =>
      if dot == 0 || (sep != None && dot < sep.unwrap()) {
        None
      } else {
        Some((take(chars, 0, dot), take(chars, dot, chars.length())))
      }
  }
}

///|
fn last_separator(chars : Array[Char]) -> Int? {
  let mut found : Int? = None
  let mut i = 0
  while i < chars.length() {
    if chars[i] == '/' || chars[i] == '\\' {
      found = Some(i)
    }
    i = i + 1
  }
  found
}

///|
fn last_index(chars : Array[Char], c : Char) -> Int? {
  let mut i = chars.length() - 1
  while i >= 0 {
    if chars[i] == c {
      return Some(i)
    }
    i = i - 1
  }
  None
}

///|
fn take(chars : Array[Char], from : Int, to : Int) -> String {
  let mut s = ""
  let mut i = from
  while i < to {
    s = s + chars[i].to_string()
    i = i + 1
  }
  s
}

///|
fn hex_tag(tag : Int) -> String {
  "0x" +
  nibble((tag >> 12) & 0xf) +
  nibble((tag >> 8) & 0xf) +
  nibble((tag >> 4) & 0xf) +
  nibble(tag & 0xf)
}

///|
fn nibble(v : Int) -> String {
  let digits = "0123456789abcdef"
  digits.to_array()[v & 0xf].to_string()
}
