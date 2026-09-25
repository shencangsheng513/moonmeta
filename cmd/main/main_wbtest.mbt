// 命令行这一层的测试只测"纯"的部分：参数怎么变成一次动作、输出路径怎么定、
// 编号怎么印。
//
// 没有一条测试真的碰文件。原因很实际：`x/fs` 在非 native 后端没有文件系统，
// 而这个包要在三个后端上都跑绿。读写那几行留给人工验收；判断逻辑一旦有 bug，
// 后果比"少了个文件"严重得多——它会把用户的原图改掉。

///|
fn act(argv : Array[String]) -> String {
  let parsed = try command().parse(argv~, env=Map([])) catch {
    _ => None
  } noraise {
    m => Some(m)
  }
  match parsed {
    None => "解析失败"
    Some(m) =>
      match to_request(m) {
        None => "无请求"
        Some(r) => describe(r)
      }
  }
}

///|
/// 一个请求压成一行：测试里比字段更直观，改坏了也能一眼看出改了哪一段。
fn describe(r : Request) -> String {
  let action = match r.action {
    Read => "read"
    Audit => "audit"
    Redact => "redact"
    Strip => "strip"
  }
  let out = match r.out {
    None => "-"
    Some(o) => o
  }
  let force = if r.force { " force" } else { "" }
  let json = if r.json { " json" } else { "" }
  "\{action} \{r.path} \{r.policy} -o=\{out}\{force}\{json}"
}

///|
/// 给需要拿到 `Request` 本身的测试用：解析不出来就直接 fail，
/// 免得断言在一个 `None` 上绕圈子。
fn request_of(argv : Array[String]) -> Request raise {
  let parsed = try command().parse(argv~, env=Map([])) catch {
    _ => None
  } noraise {
    m => Some(m)
  }
  let req = match parsed {
    None => None
    Some(m) => to_request(m)
  }
  match req {
    Some(r) => r
    None => fail("这些参数本该拼出一个动作")
  }
}

///|
test "四个子命令各自落到自己的动作上" {
  @test.assert_eq(act(["read", "a.jpg"]), "read a.jpg privacy -o=-")
  @test.assert_eq(act(["audit", "a.jpg"]), "audit a.jpg privacy -o=-")
  @test.assert_eq(act(["redact", "a.jpg"]), "redact a.jpg privacy -o=-")
  @test.assert_eq(act(["strip", "a.jpg"]), "strip a.jpg privacy -o=-")
}

///|
test "不给策略就是 privacy，不给输出就留 None" {
  // 默认值必须是那个"删隐私但留时间戳"的档，而不是最松或最紧
  @test.assert_eq(act(["redact", "a.jpg"]), "redact a.jpg privacy -o=-")
  @test.assert_eq(act(["audit", "a.jpg"]), "audit a.jpg privacy -o=-")
}

///|
test "--policy 与 -o 与 --force 各归各位" {
  @test.assert_eq(
    act(["strip", "a.jpg", "-o", "b.jpg", "--force"]),
    "strip a.jpg privacy -o=b.jpg force",
  )
  @test.assert_eq(
    act(["redact", "a.jpg", "--policy", "strict"]),
    "redact a.jpg strict -o=-",
  )
}

///|
test "打错的策略名要在执行前就拦下来" {
  // 这里悄悄退回 privacy 的话，用户会以为时间戳也被清了
  @test.assert_eq(policy_of("strick"), None)
  @test.assert_eq(policy_of("privacy") != None, true)
  @test.assert_eq(policy_of("strict") != None, true)
}

///|
test "没给 -o 时的输出路径绝不撞上输入" {
  let r = request_of(["redact", "a.jpg"])
  @test.assert_eq(output_path(r), Some("a.redacted.jpg"))
  let s = request_of(["strip", "photo.png"])
  @test.assert_eq(output_path(s), Some("photo.stripped.png"))
}

///|
test "无扩展名、点开头、多级点号：都往后缀而不是切碎名字" {
  @test.assert_eq(with_suffix("Makefile", ".redacted"), "Makefile.redacted")
  @test.assert_eq(with_suffix(".hidden", ".stripped"), ".hidden.stripped")
  @test.assert_eq(
    with_suffix("archive.tar.gz", ".redacted"),
    "archive.tar.redacted.gz",
  )
  @test.assert_eq(
    with_suffix("dir/v1.2.jpg", ".redacted"),
    "dir/v1.2.redacted.jpg",
  )
}

///|
test "目录里带点、文件名不带点：点号不能被当成扩展名" {
  @test.assert_eq(
    with_suffix("my.dir/photo", ".redacted"),
    "my.dir/photo.redacted",
  )
}

///|
test "反斜杠路径同样认得分隔符" {
  @test.assert_eq(
    with_suffix("C:\\pics\\a.jpg", ".redacted"),
    "C:\\pics\\a.redacted.jpg",
  )
}

///|
test "显式 -o 指回输入文件：这就是那条不加 --force 必须拒绝的判定" {
  let r = request_of(["strip", "a.jpg", "-o", "a.jpg"])
  @test.assert_eq(output_path(r), Some(r.path))
  let ok = request_of(["strip", "a.jpg", "-o", "a.jpg", "--force"])
  @test.assert_eq(ok.force, true)
}

///|
test "缩略图那句话只在真丢了的时候说" {
  @test.assert_eq(
    thumbnail_note(true),
    "，并丢掉可能自带坐标的缩略图",
  )
  @test.assert_eq(thumbnail_note(false), "")
}

///|
test "XMP 那句话说的是三件事，不是一件事" {
  // 摘掉了：要报告，否则下一次没人知道这里原本有过一整包元数据
  @test.assert_eq(xmp_note(true, true), "，并整包摘除 XMP")
  // 策略不覆盖：要警告，否则"删除 12 条"读起来像已经干净了
  @test.assert_eq(
    xmp_note(true, false),
    "；警告：XMP 包还在，当前策略不碰它",
  )
  // 本来就没有：一个字都不许多说
  @test.assert_eq(xmp_note(false, false), "")
  // 三态两两不同：摘除、警告、无事可做不能折叠成同一句
  @test.assert_eq(xmp_note(true, true) != xmp_note(true, false), true)
  @test.assert_eq(xmp_note(true, false) != xmp_note(false, false), true)
}

///|
/// 这句话是 `ci/crosscheck_real.py` 的 strip 那一关要解析的对象：
/// 四个状态各有一句，改措辞必须先红在这里，而不是红在一次跑批里。
test "strip 那句话按载体点名，否定那句也不能多说" {
  @test.assert_eq(
    strip_said({ had_exif: true, dropped_xmp: true, }),
    "元数据已整段摘除：EXIF,XMP 包。",
  )
  @test.assert_eq(
    strip_said({ had_exif: true, dropped_xmp: false, }),
    "元数据已整段摘除：EXIF。",
  )
  @test.assert_eq(
    strip_said({ had_exif: false, dropped_xmp: true, }),
    "元数据已整段摘除：XMP 包。",
  )
  let absent = strip_said({ had_exif: false, dropped_xmp: false, })
  @test.assert_eq(
    absent, "这个文件本来就没有 EXIF，也没有 XMP 包。",
  )
  // 否定那句里同样写着 EXIF 与 XMP 两个字面：
  // 对拍脚本因此按"点名了哪些载体"判，不做子串查找。
  @test.assert_eq(absent.contains("EXIF"), true)
  @test.assert_eq(absent.contains("XMP 包"), true)
}

///|
/// 这句话问的是策略，不是"删了没有"：内置的 privacy / strict 都覆盖载体，
/// 但在库里自己拼 `Policy` 的人能让它不覆盖。那时候若还说"会整包摘除"，
/// 就是替用户许下一个策略并没有许的承诺。
test "carrier_note 跟着策略走，不跟着默认值走" {
  @test.assert_eq(
    carrier_note(@lib.strict_policy()),
    "另含 XMP 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。",
  )
  let warning = carrier_note(@lib.empty_policy())
  assert_true(warning.contains("当前策略不碰它"))
  @test.assert_eq(warning == carrier_note(@lib.strict_policy()), false)
}

///|
/// `read` 只摊开 EXIF 目录。没有 EXIF 不等于没有元数据，
/// 所以"没有 EXIF"那一句后面必须把包着的那一份补上。
test "read 不许把没有 EXIF 说成没有元数据" {
  @test.assert_eq(
    read_xmp_note(false),
    "  但容器里另有一包 XMP：read 只摊开 EXIF 目录，包里的东西用 audit 看。",
  )
  @test.assert_eq(
    read_xmp_note(true),
    "  另含 XMP 包：read 不摊开它，逐条清单里也永远不会出现它。",
  )
}

///|
test "tag 编号补齐到四位十六进制" {
  @test.assert_eq(hex_tag(0x0002), "0x0002")
  @test.assert_eq(hex_tag(0x927c), "0x927c")
  @test.assert_eq(hex_tag(0xffff), "0xffff")
  @test.assert_eq(hex_tag(0x10f), "0x010f")
}

///|
test "程序名不进参数表" {
  @test.assert_eq(strip_program_name(["moonmeta", "read", "a.jpg"]), [
    "read", "a.jpg",
  ])
  @test.assert_eq(strip_program_name([]), [])
}

///|
test "裸命令、未知子命令、缺文件名：三种失败各有各的出口" {
  // 空参数在解析器那一关就被 `subcommand_required` 拦下，压根到不了请求层
  @test.assert_eq(act([]), "解析失败")
  @test.assert_eq(act(["nope", "x"]), "解析失败")
  // 认得出子命令却没给文件：这才轮到请求层说"我不知道该干什么"
  @test.assert_eq(act(["read"]), "无请求")
}

///|
/// 手搓一个块。编号 2 在 IFD0 没有规范名（回吐 `0x0002`），
/// 在 GPS 目录是 `GPSLatitude`；编号 1 在 GPS 是 `GPSLatitudeRef`，
/// 在 Interop 目录是 `InteropIndex`——名字是按条目所在目录查的，
/// 写死一个目录就会成片报错名字。Interop 留一条真条目，是为了让金标准里
/// 第四张表的位置、标签拼写、名字查表三件事一起被钉住。
fn block(little : Bool, gps : Array[@lib.IfdEntry]) -> @lib.TiffBlock {
  {
    little,
    ifd0: [{ tag: 2, type_code: 3, value: @lib.Shorts([8]), }],
    exif: [],
    gps,
    interop: [{ tag: 1, type_code: 2, value: @lib.Text("R98"), }],
    has_ifd1: false,
  }
}

///|
/// 整行断言，不是"包含某个子串"：键序、括号、每处转义都在比对范围内。
/// 这份输出是对外承诺的机读格式，改一个字就算破坏兼容。
test "read --json 是金标准：四个目录、键序固定、查名字各按各的目录" {
  let want = "{\"file\":\"x.jpg\",\"container\":\"jpeg\",\"xmp\":false,\"exif\":true,\"byte_order\":\"II\",\"directories\":[{\"dir\":\"IFD0\",\"entries\":[{\"tag\":2,\"name\":\"0x0002\",\"type\":3,\"value\":\"Shorts(1 value(s))\"}]},{\"dir\":\"Exif\",\"entries\":[]},{\"dir\":\"GPS\",\"entries\":[{\"tag\":2,\"name\":\"GPSLatitude\",\"type\":5,\"value\":\"Rationals(0 value(s))\"}]},{\"dir\":\"Interop\",\"entries\":[{\"tag\":1,\"name\":\"InteropIndex\",\"type\":2,\"value\":\"\\\"R98\\\"\"}]}],\"has_ifd1\":false,\"gps\":null}"
  let got = read_json(
    "x.jpg",
    @lib.Jpeg,
    Some(block(true, [{ tag: 2, type_code: 5, value: @lib.Rationals([]), }])),
    false,
  )
  @test.assert_eq(got, want)
}

///|
/// 机器读者不该比人拿到的更少：text 输出里那句"另含 XMP 包"在这个键上。
/// 空清单 + `xmp:false` 说的是"没有元数据"，+ `xmp:true` 说的是
/// "敏感东西在逐条清单装不下的那个包里"。
test "read --json 的 xmp 键：没有元数据 ≠ 没有元数据" {
  @test.assert_eq(
    read_json("x.jpg", @lib.Jpeg, None, true),
    "{\"file\":\"x.jpg\",\"container\":\"jpeg\",\"xmp\":true,\"exif\":false}",
  )
}

///|
test "大端块要说 MM，别一律报 II" {
  let be = read_json("x.tif", @lib.Tiff, Some(block(false, [])), false)
  let le = read_json("x.tif", @lib.Tiff, Some(block(true, [])), false)
  assert_true(contains_byte_order(be, "MM"))
  assert_true(contains_byte_order(le, "II"))
}

///|
fn contains_byte_order(json : String, order : String) -> Bool {
  json.contains("\"byte_order\":\"" + order + "\"")
}

///|
test "没有 EXIF 的文件：exif 是 false，且根本不给 directories 键" {
  @test.assert_eq(
    read_json("plain.png", @lib.Png, None, false),
    "{\"file\":\"plain.png\",\"container\":\"png\",\"xmp\":false,\"exif\":false}",
  )
}

///|
test "audit --json：一条没命中也要给空数组，不能把键省掉" {
  @test.assert_eq(
    audit_json(
      "x.jpg",
      "privacy",
      Some(block(true, [])),
      @lib.empty_policy(),
      false,
    ),
    "{\"file\":\"x.jpg\",\"policy\":\"privacy\",\"xmp\":false,\"exif\":true,\"findings\":[]}",
  )
  // 空清单 + xmp:false 与 空清单 + xmp:true 是两个结论，必须都能表达：
  // 后者说的是"敏感东西在策略管不到的包里"。
  @test.assert_eq(
    audit_json(
      "x.jpg",
      "privacy",
      Some(block(true, [])),
      @lib.empty_policy(),
      true,
    ),
    "{\"file\":\"x.jpg\",\"policy\":\"privacy\",\"xmp\":true,\"exif\":true,\"findings\":[]}",
  )
}

///|
/// 坐标走字符串就是为了让这行永远合法：0 分母的有理数会折算成非有限
/// `Double`，而 JSON 里没有 `inf` 这个字面量。
test "GPS 坐标以字符串给出，缺坐标是 null" {
  @test.assert_eq(gps_json(block(true, [])), "null")
  let lat = @lib.Rationals([
    { num: 31L, den: 1L, },
    { num: 0L, den: 1L, },
    { num: 13L, den: 10000L, },
  ])
  let lon = @lib.Rationals([
    { num: 121L, den: 1L, },
    { num: 0L, den: 1L, },
    { num: 14L, den: 10000L, },
  ])
  let entries : Array[@lib.IfdEntry] = [
    { tag: 1, type_code: 2, value: @lib.Text("N"), },
    { tag: 2, type_code: 5, value: lat, },
    { tag: 3, type_code: 2, value: @lib.Text("E"), },
    { tag: 4, type_code: 5, value: lon, },
  ]
  let s = gps_json(block(true, entries))
  assert_true(s.has_prefix("\"31.0"))
  assert_true(s.contains(",121.0"))
}

///|
test "JSON 里的字符串一律转成 ASCII：引号、反斜杠、控制符、非 ASCII、代理对" {
  @test.assert_eq(json_str("nik\"on"), "\"nik\\\"on\"")
  @test.assert_eq(json_str("C:\\pics\\a.jpg"), "\"C:\\\\pics\\\\a.jpg\"")
  @test.assert_eq(json_str("a\nb"), "\"a\\nb\"")
  @test.assert_eq(json_str("a\tb"), "\"a\\tb\"")
  @test.assert_eq(json_str("\u{1}"), "\"\\u0001\"")
  @test.assert_eq(json_str("上海"), "\"\\u4e0a\\u6d77\"")
  @test.assert_eq(json_str("😀"), "\"\\ud83d\\ude00\"")
}

///|
test "中文文件名不会把非法字节漏进 JSON 输出" {
  let s = read_json("C:\\图\\a.jpg", @lib.Jpeg, None, false)
  let non_ascii = s.to_array().filter(c => c.to_int() >= 128)
  @test.assert_eq(non_ascii.length(), 0)
  assert_true(s.contains("\\u56fe"))
}

///|
test "--json 只挂在 read 与 audit 上，写操作不认这个旗标" {
  @test.assert_eq(
    act(["read", "a.jpg", "--json"]),
    "read a.jpg privacy -o=- json",
  )
  @test.assert_eq(
    act(["audit", "a.jpg", "--json"]),
    "audit a.jpg privacy -o=- json",
  )
  @test.assert_eq(act(["redact", "a.jpg", "--json"]), "解析失败")
  @test.assert_eq(act(["strip", "a.jpg", "--json"]), "解析失败")
}
