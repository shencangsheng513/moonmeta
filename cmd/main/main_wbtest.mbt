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
  "\{action} \{r.path} \{r.policy} -o=\{out}\{force}"
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
