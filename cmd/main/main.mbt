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
      ),
      @argparse.Command(
        "audit",
        about="只报告按策略会被删掉的条目，不改动文件",
        positionals=[
          @argparse.PositionArg("file", about="要审计的图片文件"),
        ],
        options=[policy_option()],
      ),
      @argparse.Command(
        "redact",
        about="按策略逐条删除，结果写到新文件",
        positionals=[
          @argparse.PositionArg("file", about="要脱敏的图片文件"),
        ],
        options=[policy_option(), output_option()],
        flags=[force_flag()],
      ),
      @argparse.Command(
        "strip",
        about="整段摘掉元数据，结果写到新文件",
        positionals=[@argparse.PositionArg("file", about="要清空的文件")],
        options=[output_option()],
        flags=[force_flag()],
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
fn dispatch(
  req : Request,
  data : Bytes,
  kind : @lib.Kind,
  block : @lib.TiffBlock?,
  p : @lib.Policy,
) -> Int {
  match req.action {
    Read => show_read(req.path, kind, block)
    Audit => show_audit(req.path, req.policy, block, p)
    Redact => redact_file(req, data, p)
    Strip => strip_file(req, data)
  }
}

///|
fn show_read(path : String, kind : @lib.Kind, block : @lib.TiffBlock?) -> Int {
  println("\{path}：\{kind.to_string()}")
  match block {
    None => {
      println("  这个文件里没有 EXIF。")
      0
    }
    Some(b) => {
      dump_dir(@lib.Ifd0, b.ifd0)
      dump_dir(@lib.Exif, b.exif)
      dump_dir(@lib.Gps, b.gps)
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
      0
    }
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
) -> Int {
  match block {
    None => {
      println("\{path}: 没有 EXIF，无需脱敏。")
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
      0
    }
  }
}

///|
fn redact_file(req : Request, data : Bytes, p : @lib.Policy) -> Int {
  let (bytes, report) = @lib.redact_any(data, p) catch {
    e => {
      println("\{req.path}: \{e}")
      return 1
    }
  }
  for r in report.removed {
    println("  - \{r.dir.label()}/\{r.name} (\{r.category.label()})")
  }
  let n = report.removed.length()
  println("删除 \{n} 条\{thumbnail_note(report.dropped_thumbnail)}。")
  write_result(req, bytes)
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
fn strip_file(req : Request, data : Bytes) -> Int {
  let (bytes, had) = @lib.strip_any(data) catch {
    e => {
      println("\{req.path}: \{e}")
      return 1
    }
  }
  // "本来就没有"和"已清除"是两回事；说错这一句，整个工具就没人敢信了。
  println(
    if had {
      "元数据已整段摘除。"
    } else {
      "这个文件本来就没有 EXIF。"
    },
  )
  write_result(req, bytes)
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
