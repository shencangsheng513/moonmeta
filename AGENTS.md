# Project Agents.md Guide

This is a [MoonBit](https://docs.moonbitlang.com) project.

You can browse and install extra skills here:
<https://github.com/moonbitlang/skills>

## Project Structure

- MoonBit packages are organized per directory; each directory contains a
  `moon.pkg` file listing its dependencies. Each package has its files and
  blackbox test files (ending in `_test.mbt`) and whitebox test files (ending in
  `_wbtest.mbt`).

- In the toplevel directory, there is a `moon.mod` file listing module
  metadata.

## Coding convention

- MoonBit code is organized in block style, each block is separated by `///|`,
  the order of each block is irrelevant. In some refactorings, you can process
  block by block independently.

- Try to keep deprecated blocks in file called `deprecated.mbt` in each
  directory.

## Tooling

- `moon fmt` is used to format your code properly.

- `moon ide` provides project navigation helpers like `peek-def`, `outline`, and
  `find-references`. See $moonbit-agent-guide for details.

- `moon info` is used to update the generated interface of the package, each
  package has a generated interface file `.mbti`, it is a brief formal
  description of the package. If nothing in `.mbti` changes, this means your
  change does not bring the visible changes to the external package users, it is
  typically a safe refactoring.

- In the last step, run `moon info && moon fmt` to update the interface and
  format the code. Check the diffs of `.mbti` file to see if the changes are
  expected.

- Run `moon test` to check tests pass. MoonBit supports snapshot testing; when
  changes affect outputs, run `moon test --update` to refresh snapshots.

- Prefer `assert_eq` or `assert_true(pattern is Pattern(...))` for results that
  are stable or very unlikely to change. For snapshot tests that record
  structured debugging output, derive `Debug` and use `debug_inspect`, rather
  than deriving `Show` for debugging. For solid, well-defined results (e.g.
  scientific computations), prefer assertion tests. You can use
  `moon coverage analyze > uncovered.log` to see which parts of your code are
  not covered by tests.

## 这个仓库额外要守的（每条都有它存在的原因，不是装饰）

### moon 的跑法

- `moon test --target` 只吃 `wasm | wasm-gc | js | native | llvm | all`，**没有 `default`**。
  三后端矩阵是 `wasm`/`js`/`wasm-gc`；`native` 在本机跑不了，因为 `moonbitlang/x/fs`
  带 native C stub 而这台机器没有 C 编译器。这是文档里写明的已知缺口，不是忘了跑。
- `x/fs` 在非 native 后端没有文件系统：测试里一条真实文件读写都跑不了。可行解法是把
  判断（路径拼装、覆盖拒绝、策略解析）抽成纯函数单测，IO 那几行交给命令行端到端作业，
  并在测试文件头写明为什么故意不覆盖。
- **moon 批处理一律串行**：`_build` 是共享目录，两个批处理同时在跑时读数不能当证据。
  起 `moon` 之前先清点有没有别的 moon/test 进程在跑（这台机器上常有并行会话）。

### MoonBit 语言层：报错信息完全指不到真因的那几处

- labelled 实参用 `=`，不是 `:`：`OptionArg("output", short='o', ...)`。写成 `short: 'o'`
  报 "requires 1 positional arguments, but is given 2"。结构体字面量里才是 `field: value`。
- `import { ... }` 只能出现在 `moon.pkg`；写在 `.mbt` 里报 "Invalid import declaration here"。
- `-> T raise String` 非法（"Type String is not an error type"）。错误类型必须是
  `pub suberror`。
- `pub suberror` 的变体是包内可见：白盒 `_wbtest.mbt` 里 `BadChecksum(...)` 直接用，
  黑盒 `_test.mbt` 里要 `@pkg.MetaError::BadChecksum` 或走 `Show`。
- 只 `derive(Debug)` 没有 `Show` 的值（`Bytes`、`@fs.IOError` 这类）：`println("\{e}")`
  编译失败，`e.to_repr()` 已废弃 → 用 `@debug.to_string(e)`，并给 `moon.pkg` 加
  `moonbitlang/core/debug`。
- `try e catch { _ => None }` 整体仍是 raise 表达式；要拿到 `Option` 必须补
  `noraise { v => Some(v) }`。
- 一个 `match` 的 scrutinee 位置上不能再内联另一个 `match`——先 `let x = match ...` 再 match 它。
- 字符串字面量里插值不能跨行；多行 `if ... else` 拼进 `"\{...}"` 会炸成
  "unterminated string literal" → 把那句话提成独立 `fn`。
- 数组切片模式 `[_, .. rest] => rest` 给的是 `ArrayView`，赋给 `Array[String]` 要 `rest.to_owned()`。

### 文档是被测试钉住的

- README 里那段库用法示例的函数体住在 `moonmeta_readme_test.mbt` 里当测试跑（那个文件第一行
  就这么写着），那份只比 README 多一句 `@test.assert_eq(report.removed.length(), findings.length())`。
  改示例代码必须同步改它，否则 `moon test` 红。
- README 里那些 ```console 块（2026-09-28 实测 22 段，`grep -c '```console' README.mbt.md`，命令与真输出都在里面）大体**没有**逐字断言的测试，
  靠人工与屏幕比对 + `ci/replay_cli.py`
  复放 CI 里同一批命令（它验命令与退码，不验那几行文字）。例外是 CLI 那几句整句文案——
  `cmd/main/main_wbtest.mbt` 把它们逐字钉住了（例如测试里那句 `contains("两条路都清不到链里这一份")`
  与"另含 XMP 包：read 不摊开它，逐条清单里也永远不会出现它。"），改这几句要先红在测试里。
- README 的 65 个 tag 规范名逐条断言在 `moonmeta_tags_test.mbt` 里。
- README 里 ```console 那些真实输出对着 `python ci/make_fixture.py` 造的六份文件
  （默认落 `.scratch/fix/`，CI 落 `/tmp/fix`）。换 fixture 名字或路径 ⇒ 示例要重跑、
  贴真输出，不许留旧输出。
- 文档里不写"某件东西不存在 / 从没跑过 / 还没接上"，除非当场跑过一条能证明它的命令。
  引用产物只能指到 clone 之后还存在的路径：`.scratch/` 在 `.gitignore` 里，
  写进正文就是断链（这批变异驱动就是这么从 `.scratch/` 搬进 `ci/mutations/` 的）。
- 提交前跑 `moon fmt && moon info`。CI 用 `git diff --exit-code` 卡这两处的漂移。

### 门禁（都不要求语料在位；除 `registry_census.py` 那一行要联网之外，都在 CI 里复现）

| 命令 | 判据 |
| --- | --- |
| `python ci/crosscheck_selftest.py` | 归因判据的真值表（`Ran N tests` / `OK`；N 以当回合输出为准，最近一次实测 141） |
| `python ci/inplace_crosscheck.py --selftest` | 原位门禁自己有没有眼睛（逐格 OK + 收尾"inplace_crosscheck 自测真值表：N 格，错 0 格"，名单被删短会红在 N 上；地板 14） |
| `python ci/mutations/run_all.py --selftest` | 变异判定器真值表（收尾"判定器真值表：N 格，错 0 格"） |
| `python ci/registry_census.py --selftest` | 查重计数器的真值表（11 格：计数两层、形状闸、分母闸；不打网） |
| `python ci/registry_census.py` | 申报书查重表那 13 个词的复算（要网；收尾"分母：13 个词里取回 13 个"，取不满退 1） |
| `python ci/mutations/mut_d9e.py` | 语料闸那三判据的区分度（16 处注入各处红一次；纯 python，不要语料也不要 moon） |
| `python ci/replay_cli.py --check-only` | CI 的 `cli` 作业步骤/命令行清单对账（两个口径必须一致） |

全量变异集是 `python ci/mutations/run_all.py`（要语料在位、串行、跑完 `git status --porcelain`
必须为空；每处注入都是"改坏 → 确认红在那一格 → `finally` 按字节还原并核对 sha"）。
判定只认每个驱动顶格那几行自己的收尾语与两组必须相等的计数，**按子串扫 `FAIL`/`对不上` 会把绿读成红**。

### 语料

- 四批外来语料：第一批是 `ianare/exif-samples` 整份 clone（按 `ci/crosscheck_real.py`
  里 `IMAGE_SUFFIXES` 那五个后缀命中）；第二/三/四批用
  `python ci/grab_corpus.py --batch {tiff,jpeg,png} --out <目录> <Pillow 克隆>` 从上游挑，
  只看 `Tests/images` 根下那一层，再按容器魔数与"字节里到底有没有元数据标记"筛。
- 上游在动，所以挑中份数默认只打印不判定（`--expect` 是地板）。
- 语料与全部产物落 `.scratch/`（已 gitignore），**不入库**；入库的只有 `ci/` 里的代码和文档。

### CI

- `.github/workflows/ci.yml` 三个作业各自都要有一步 `moon update`：全新 runner 的注册表索引
  是空的，缺它就红在 `Failed to resolve registry dependency moonbitlang/x`。这一格本机
  复现不到（开发机的索引早就落地过，`moon check`/`moon test` 从来不联网）。
- push 触发同时列了 `main` 和 `master`。

