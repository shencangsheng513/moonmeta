// Whitebox tests run within the package scope.
// Use them to validate internal helpers or invariants.
// Keep them focused; public behavior belongs in `_test.mbt`.

///|
/// 白盒不变量：敏感表点名的每个 (目录, 编号) 都必须有规范名，且不重复。
///
/// 报告里的名字是人用来决定"删了什么"的依据。一条打成 `0xa431` 的
/// 位置类记录，意味着两张表脱节了——而这种脱节没人会肉眼发现。
test "敏感表点名的每个编号都有规范名，且不重复" {
  let seen : Array[(Dir, Int)] = []
  for e in sensitive_tags {
    let (dir, tag, _) = e
    if tag_name(dir, tag) == tag_hex(tag) {
      fail("表里有名字缺：" + dir.label() + " " + tag_hex(tag))
    }
    for s in seen {
      let (d, t) = s
      if d == dir && t == tag {
        fail("表里有重复条目：" + dir.label() + " " + tag_hex(tag))
      }
    }
    seen.push((dir, tag))
  }
  @test.assert_eq(seen.length(), sensitive_tags.length())
}
