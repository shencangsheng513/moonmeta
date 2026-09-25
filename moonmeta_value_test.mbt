// 值层：形状、宽度、打印。
//
// 这一层最不起眼，却撑着两条承诺：解析时判断"这个条目的值在不在块内"
// 靠 `type_size` 算宽度；`read` 打出来的每一行靠 `Show`。
// 算错宽度会把越界的坏文件当合法，打错样会把报告写成天书。

///|
/// RATIONAL 的分子是无符号 32 位，超过 MoonBit `Int` 的可用范围。
test "有理数：换算成 Double，分母为 0 也不 panic" {
  @test.assert_eq(
    ({ num: 3L, den: 4L, } : @moonmeta.Rational).to_double(),
    0.75,
  )
  // 4294967295 这个分子若按 Int 存会先变负，这里要求它照原样算出来。
  let big : @moonmeta.Rational = { num: 4294967295L, den: 1L, }
  assert_true(big.to_double() > 4294967000.0)
  let zero_den : @moonmeta.Rational = { num: 1L, den: 0L, }
  assert_true(zero_den.to_double() > 4294967295.0)
}

///|
/// `read` 的输出词汇表：五种形状各有一句人话。
test "Show：每种值都报清形状和元素个数" {
  @test.assert_eq(
    (@moonmeta.Text("NIKON") : @moonmeta.TagValue).to_string(),
    "\"NIKON\"",
  )
  @test.assert_eq(
    (@moonmeta.Shorts([1, 2]) : @moonmeta.TagValue).to_string(),
    "Shorts(2 value(s))",
  )
  @test.assert_eq(
    (@moonmeta.Longs([1L]) : @moonmeta.TagValue).to_string(),
    "Longs(1 value(s))",
  )
  @test.assert_eq(
    (
      @moonmeta.Rationals([
        { num: 1L, den: 2L, },
        { num: 3L, den: 4L, },
        { num: 5L, den: 6L, },
      ]) : @moonmeta.TagValue).to_string(),
    "Rationals(3 value(s))",
  )
  @test.assert_eq(
    (@moonmeta.Raw([b'a', b'b', b'c']) : @moonmeta.TagValue).to_string(),
    "Raw(3 byte(s))",
  )
}

///|
/// 取错形状必须返回 `None`：返回空数组会让调用方以为"这个条目没有值"，
/// 而真相是"它有的不是你想要的那种"。
test "取值助手：形状不对就明确说没有" {
  let s = @moonmeta.Shorts([1, 2, 3])
  @test.assert_eq(s.text(), None)
  @test.assert_eq(s.rationals(), None)
  @test.assert_eq(s.shorts(), Some([1, 2, 3]))
  let t = @moonmeta.Text("hi")
  @test.assert_eq(t.text(), Some("hi"))
  @test.assert_eq(t.shorts(), None)
}

///|
/// 十三个规范类型码的宽度，一个都不能缺。
///
/// 11/12/13（FLOAT / DOUBLE / IFD）本版本刻意不解码，但**必须**算得出宽度：
/// 先知道声明了多少字节，才能判断文件有没有越界，也才能原样搬走不认识的值。
test "type_size：13 个类型码全覆盖，越界返回 None" {
  let sizes : Array[(Int, Int)] = [
    (1, 1),
    (2, 1),
    (3, 2),
    (4, 4),
    (5, 8),
    (6, 1),
    (7, 1),
    (8, 2),
    (9, 4),
    (10, 8),
    (11, 4),
    (12, 8),
    (13, 4),
  ]
  for e in sizes {
    let (code, size) = e
    @test.assert_eq(@moonmeta.type_size(code), Some(size))
  }
  @test.assert_eq(@moonmeta.type_size(0), None)
  @test.assert_eq(@moonmeta.type_size(14), None)
  @test.assert_eq(@moonmeta.type_size(-1), None)
}

///|
/// 解码边界卡在 1..10：浮点要位模式转换，IFD 是指针，都不是"读一个数"。
test "type_decodable 的边界正好是 1 到 10" {
  @test.assert_eq(@moonmeta.type_decodable(0), false)
  @test.assert_eq(@moonmeta.type_decodable(1), true)
  @test.assert_eq(@moonmeta.type_decodable(10), true)
  @test.assert_eq(@moonmeta.type_decodable(11), false)
  @test.assert_eq(@moonmeta.type_decodable(12), false)
  @test.assert_eq(@moonmeta.type_decodable(13), false)
}
