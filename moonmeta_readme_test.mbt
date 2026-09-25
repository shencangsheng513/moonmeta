// README 里那段库用法示例的可执行版本。
//
// 文档最大的风险不是写错一次，是写对之后代码改了、文档还留着。
// 所以示例逐字搬进这里当测试：接口一改，构建就红。

///|
fn audit_and_clean(data : Bytes) -> Bytes raise {
  let (_kind, block) = @moonmeta.decode_any(data)
  let findings = match block {
    Some(b) => b.findings(@moonmeta.strict_policy())
    None => []
  }
  for r in findings {
    println("\{r.dir.label()}/\{r.name} → \{r.category.label()}")
  }
  let (clean, report) = @moonmeta.redact_any(data, @moonmeta.strict_policy())
  @test.assert_eq(report.removed.length(), findings.length())
  clean
}

///|
test "README 示例：同一份元数据在三种容器里都跑得通" {
  for (name, data) in all_three() {
    let clean = audit_and_clean(data) catch {
      e => fail("\{name} 走完示例流程失败：\{e}")
    }
    let (_, left) = @moonmeta.decode_any(clean) catch {
      e => fail("\{name} 的产物读不回去了：\{e}")
    }
    match left {
      Some(b) =>
        @test.assert_eq(b.findings(@moonmeta.strict_policy()).length(), 0)
      None => ()
    }
  }
}
