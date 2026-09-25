# moonmeta

读写 JPEG / PNG / TIFF 里的 EXIF 元数据，并且能按策略把它删干净。

纯 MoonBit 实现：解析、回写、脱敏三层都不出 MoonBit 类型系统，`moon test`
在 wasm / JavaScript / wasm-gc 三个后端上跑的是同一套断言。

## 它解决哪一件事

一张手机或相机拍出来的 JPEG，EXIF 里通常带着 GPS 坐标、机身与镜头序列号、
拍摄时间、厂商私有块。把这些发出去之前要删干净，而"删干净"很难自证：
删错了没人报错，删剩了看不出来。

这个包把承诺写成可以断言的三句话：

1. **改完还是合法文件**——只重写装元数据的那一段，像素数据逐字节搬回去；
   搬不动的时候拒绝出手，而不是交出一个打不开的文件；
2. **点名的条目真的没了**——删完再解析一遍，报告里列出的编号必须查不到；
3. **报告说得出删了哪几条**——每条都带目录、tag 编号、规范名、类别。

## 快速开始：命令行

四个子命令，前两个只读、都认 `--json`：

```console
$ moon run cmd/main -- read    <文件>     # 列出容器结构与每一条元数据
$ moon run cmd/main -- audit   <文件>     # 只报告按策略会删掉哪些，不动文件
$ moon run cmd/main -- redact  <文件>     # 按策略逐条删除，写到新文件
$ moon run cmd/main -- strip   <文件>     # 整段摘掉元数据，写到新文件
```

下面几段真实输出都对着 `ci/make_fixture.py` 造的五份文件（Pillow 亲手写进
容器，默认落在 `.scratch/fix/`）：`cross.jpg` / `cross.png` / `cross.tiff`
是同一份元数据的三种装法，`cross_xmp.jpg` 在此基础上另带一包 XMP，
`xmp_only.jpg` 则只有那包 XMP、没有 EXIF。

```console
$ python ci/make_fixture.py
```

`read` 把容器结构与每一条元数据摊开：

```console
$ moon run cmd/main -- read .scratch/fix/cross.jpg
.scratch/fix/cross.jpg：jpeg
  IFD0 目录（5 条）
    0x010f Make = "NIKON CORPORATION"
    0x0110 Model = "NIKON D850"
    0x0131 Software = "MoonMeta CrossCheck 1.0"
    0x013b Artist = "Zhang San"
    0x8298 Copyright = "(C) 2026 Someone"
  Exif 目录（7 条）
    0x9003 DateTimeOriginal = "2026:09:24 15:51:00"
    ...
    0xa431 BodySerialNumber = "BODY-0001234567"
  GPS 目录（5 条）
    0x0002 GPSLatitude = Rationals(3 value(s))
    ...
  折算坐标：31.00375, 121.00241666666666
  GPS 目录存在。
  相机：NIKON CORPORATION NIKON D850
```

`audit` 把"会删哪些"摊开成人能读的一行一条：

```console
$ moon run cmd/main -- audit .scratch/fix/cross.jpg --policy strict
.scratch/fix/cross.jpg: 策略 strict 命中 12 条。
  IFD0/Artist (0x013b) → identity
  Exif/DateTimeOriginal (0x9003) → timestamps
  ...
  GPS/GPSLongitude (0x0004) → location
```

XMP 是另一种形状：它不是 IFD 里的一条，逐条清单天然装不下它。所以 `read`
在两种文件上说的不是同一句话——"这个文件里没有 EXIF"和"这个文件里没有
元数据"是两回事，把前者说成后者就等于替用户签了一张空白担保：

```console
$ moon run cmd/main -- read .scratch/fix/xmp_only.jpg
.scratch/fix/xmp_only.jpg：jpeg
  这个文件里没有 EXIF。
  但容器里另有一包 XMP：read 只摊开 EXIF 目录，包里的东西用 audit 看。
```

```console
$ moon run cmd/main -- read .scratch/fix/cross_xmp.jpg
.scratch/fix/cross_xmp.jpg：jpeg
  IFD0 目录（5 条）
  ...
  相机：NIKON CORPORATION NIKON D850
  另含 XMP 包：read 不摊开它，逐条清单里也永远不会出现它。
```

于是"清单是空的"这一种文件也有话说：

```console
$ moon run cmd/main -- audit .scratch/fix/xmp_only.jpg --policy strict
.scratch/fix/xmp_only.jpg: 没有 EXIF，无需脱敏。
另含 XMP 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。
```

真删的时候，逐条清单与整包摘除分开报——一个是 12 行，一个是 1 包：

```console
$ moon run cmd/main -- redact .scratch/fix/cross_xmp.jpg --policy strict
  - IFD0/Artist (identity)
  ...
  - GPS/GPSLongitude (location)
删除 12 条，并整包摘除 XMP。
已写出 .scratch/fix/cross_xmp.redacted.jpg
```

`read` 与 `audit` 认 `--json`，一行一个文件、键序固定。机读输出说的不该比
人读输出少：`xmp` 这个键就是人读那两句"另含 XMP 包"的同一个事实。
`findings` 里的 `tag` 是十进制整数（`315` 即 `0x013b`）：

```console
$ moon run cmd/main -- read .scratch/fix/xmp_only.jpg --json
{"file":".scratch/fix/xmp_only.jpg","container":"jpeg","xmp":true,"exif":false}
```

```console
$ moon run cmd/main -- audit .scratch/fix/cross_xmp.jpg --policy strict --json
{"file":".scratch/fix/cross_xmp.jpg","policy":"strict","xmp":true,"exif":true,"findings":[{"dir":"IFD0","tag":315,"name":"Artist","category":"identity"},{"dir":"Exif","tag":36867,"name":"DateTimeOriginal","category":"timestamps"},{"dir":"Exif","tag":36868,"name":"DateTimeDigitized","category":"timestamps"},{"dir":"Exif","tag":36881,"name":"OffsetTimeOriginal","category":"timestamps"},{"dir":"Exif","tag":37500,"name":"MakerNote","category":"maker_note"},{"dir":"Exif","tag":42033,"name":"BodySerialNumber","category":"device_id"},{"dir":"Exif","tag":42037,"name":"LensSerialNumber","category":"device_id"},{"dir":"GPS","tag":0,"name":"GPSVersionID","category":"location"},{"dir":"GPS","tag":1,"name":"GPSLatitudeRef","category":"location"},{"dir":"GPS","tag":2,"name":"GPSLatitude","category":"location"},{"dir":"GPS","tag":3,"name":"GPSLongitudeRef","category":"location"},{"dir":"GPS","tag":4,"name":"GPSLongitude","category":"location"}]}
```

`findings` 里只有命中的条目：策略没点名的东西（`Make`、`Copyright`）不出现，
整包的 XMP 也不出现。前者是"留不留由人决定"，后者是"留了却没人说"——
所以包必须有自己那个键。

写操作默认不覆盖输入文件；`-o` 指回输入会被拒绝（退出码 `2`），
除非显式加 `--force`：

```console
$ moon run cmd/main -- redact .scratch/fix/cross.png -o .scratch/fix/cross.png
  - IFD0/Artist (identity)
  ...
删除 9 条。
拒绝覆盖输入文件 .scratch/fix/cross.png；就地修改请加 --force
```

打错的策略名在执行前拦下，不会悄悄退回默认值（`--policy strick` 若按
`privacy` 跑，用户会以为时间戳也被清了）。这条也是退出码 `2`：

```console
$ moon run cmd/main -- audit .scratch/fix/cross.png --policy strick
未知策略 strick：可用的是 privacy 或 strict
```

第二次 `strip` 一个已经没有元数据的文件，它说的是"本来就没有"，
不是"已清除"：

```console
$ moon run cmd/main -- strip .scratch/fix/cross.stripped.jpg
这个文件本来就没有 EXIF，也没有 XMP 包。
已写出 .scratch/fix/cross.stripped.stripped.jpg
```

"删掉了"与"本来就没有"是两句话。一个已经清干净的文件再 `strip` 一次，
它说的是后者，不会把上一轮的功劳再报一遍——混为一谈的脱敏工具没法验收。

退出码：`0` 成功 / `1` 文件读不了或格式不认识 / `2` 用法不对。

## 库用法

```moonbit nocheck
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
  let (clean, _report) = @moonmeta.redact_any(data, @moonmeta.strict_policy())
  clean
}
```

上面这段是可执行文档：它逐字住在 `moonmeta_readme_test.mbt` 里当测试跑，
接口一改构建就红。它对着 `moonmeta_tiff_test.mbt` 里那份手算 fixture
（同一份元数据分别装进 JPEG、PNG、裸 TIFF）各打出这 5 行：

```console
Exif/DateTimeOriginal → timestamps
GPS/GPSLatitudeRef → location
GPS/GPSLatitude → location
GPS/GPSLongitudeRef → location
GPS/GPSLongitude → location
```

主要入口：

| 函数 | 作用 |
| --- | --- |
| `sniff(data)` | 只看魔数判容器，认不出来返回 `None`（不猜） |
| `decode_any(data)` | → `(Kind, TiffBlock?)`，容器自适应 |
| `TiffBlock::findings(policy)` | 只读审计，返回将被删除的条目清单 |
| `redact_any(data, policy)` | 逐条删除 + 报告，容器自适应 |
| `strip_any(data)` | 整段摘除，并报告原本有没有 |
| `decode_tiff` / `encode_tiff` | 裸 TIFF 块的读与回写 |
| `jpeg_*` / `png_*` | 容器层的段表 / 块表走查与原位替换 |
| `jpeg_inspect` / `png_inspect` | 段表 / 块表，含 `has_xmp` 与每包的偏移区间 |
| `jpeg_drop_xmp` / `png_drop_xmp` | 整包摘除，返回 `(新文件, 真摘了没有)` |
| `Policy::covers(category)` | 这个策略管不管这一类；报告的话术由它决定，不另写一份 |
| `describe_container(data)` | 一行容器概览，给报告用 |

## 策略

`Policy` 是七个布尔开关，类别用枚举而不是 `String`：加了新类别却忘了在
策略里处理，必须是编译错误，不能是"静默不删、数据照原样发出去"。

| 类别 | 覆盖什么 | privacy | strict |
| --- | --- | --- | --- |
| `Location` | GPS 目录里的全部条目（含版本号）+ 坐标本身 | ✔ | ✔ |
| `Identity` | `Artist`、`ImageUniqueID` | ✔ | ✔ |
| `DeviceId` | 机身 / 镜头序列号 | ✔ | ✔ |
| `MakerNote` | 厂商私有块（内容不受规范约束，坐标常藏在里面） | ✔ | ✔ |
| `Comments` | `UserComment` | ✔ | ✔ |
| `Timestamps` | `DateTime` 及各 `OffsetTime*` / `SubsecTime*` / `DateTime*` | ✘ | ✔ |
| `Carrier` | 容器里成包的 XMP（JPEG APP1、PNG `tEXt`/`iTXt`），以及 TIFF 里装整包的 `0x02bc` / `0x02bd` / `0x8773` | ✔ | ✔ |

`Carrier` 和上面六类不是同一种东西：其余六类删的是 IFD 里的一条条目，
它删的是另一整套元数据。这一类是被真实语料逼出来的——逐条策略删干净之后，
82 个产物里仍有 13 个能搜到 `exif:DateTimeOriginal`、`dc:creator`、
`aux:SerialNumber`：同一批事实的第二份副本，住在 XMP 包里，
逐条清单永远不会把它列出来。所以现在它是一等公民：能点名、能删、
删了要在报告与命令行里说出来（`Redaction::dropped_xmp`）。

另有 `empty_policy()`：什么都不删，只用作只读审计的对照，连 XMP 包也不碰
（`dropped_xmp` 因此是 `false`，不是"没有包"）。命令行目前只认 `privacy` 与
`strict`，两者都覆盖载体；那句"警告：当前策略不碰它"是给在库里自己拼
`Policy` 的人准备的，两个分支都钉在 `cmd/main/main_wbtest.mbt` 里。

分类明细住在 `moonmeta_tags.mbt` 的 `sensitive_tags` 表里：17 行
（每个编号都对着 exiftool 的 tag 名表核过）+ "GPS 目录整体算 `Location`"
一条规则。报告上能打名字是因为 64 个编号有规范名（IFD0 14 个、Exif 14 个、
GPS 32 个、Interop 4 个），这 64 行逐条钉在 `moonmeta_tags_test.mbt` 里；表外的编号
回吐十六进制，不拿别的目录的名字凑。`Copyright` 刻意不在任何类别里——
它是权利声明，抹掉它本身就是一种伤害。

## 不可让步的几条约定

- **错误必须说得出地方。** 20 种错误变体分三类：13 种报出坏在第几个字节
  （`TooShort` 与 `EntryTooLarge` 现在也各自带偏移，不只报数额），3 种报出
  那个把读者带出块外的指针值本身（它被拒绝就是因为它不在块内，拿块长要求它
  反而是错的），4 种是回写期的错误、拿条目 tag 定位。只报"坏了"是一个无法
  追问的失败。这个分类不是文档里的说法，是 `moonmeta_fuzz_test.mbt` 里一个
  没有 `_` 的穷尽匹配：新增一条错误而没交代它是哪一类，编译就过不去。
- **读不能篡改数据。** 文本按 ISO-8859-1 逐字节可逆映射，不做
  "认不出来就替换成 `?`"。非 ASCII 的 `Make`/`Model` 是常态。
- **`RATIONAL` 的分子存成 `Int64`。** MoonBit 的 `Int` 只有 31 位可用范围，
  无符号 32 位分子用 `Int` 存会读成负数。
- **缩略图单独交代。** IFD1 常自带一份 GPS，"删了主坐标却留着缩略图"
  是最常见的假脱敏，所以 `redact` 一律丢掉 IFD1 并在报告里说明。
- **一条都没删，就不许重排文件。** 空策略、或者策略一条都没命中时，
  容器层直接跳过重写：我们的编码器按自己的布局重排偏移（实测把那份手算
  fixture 重编码会长 4 个字节），"顺手规范化一下"会把一次无改动的调用
  变成一次没人要求的改写。钉在 `moonmeta_container_test.mbt` 里那句
  `out == file`，并且同一条判据在 12000 份畸形输入上逐份重验
  （`moonmeta_fuzz_test.mbt`）。
- **同一批事实的第二份副本也要说出来。** XMP 包里常原样抄着拍摄时间、
  机型、署名、序列号，而逐条清单天然装不下它。所以它跟缩略图同一条规矩：
  删了要报（`dropped_xmp`、命令行那句"并整包摘除 XMP"），没删也要报
  （`xmp` 键、`read` 最后那一句）。"清单是空的"与"该删的都删了"
  在脱敏工具里是两个完全不同的结论。
- **重写整份文件之前，先要能原样复现它。** 裸 TIFF（不是装在 JPEG/PNG 里
  的那段 EXIF）的每一个字节都由 IR 重新产出，而 IR 里只有元数据：所以
  `redact_any`/`strip_any` 要求 `encode(decode(x))` 与 `x` 逐字节相同才动手，
  否则报 `TiffNotByteExact`，说清 IFD0 在第几个字节、文件多少字节、模型能
  重建多少字节。真实相机的 TIFF 常把 IFD0 放在像素数据之后，这类文件一律
  拒绝改写（读、审照常）。这条判据是被对拍逼出来的：加了它之前，我们的
  产物里有一个 6925 字节的 TIFF 缩成了 533 字节，Pillow 报
  `decoder error -2`，而我们自己的 `read` 读它还是全绿。
- **不认识的条目照样搬得走。** `type_size` 对所有 13 个规范类型码都有定义，
  包括本版本还解不了的 `FLOAT`/`DOUBLE`/`IFD`：先算得出宽度，才判得了越界，
  也才保得了原样。
- **CLI 不做判断。** "删什么"全部来自库；命令行只负责读文件、调库、打印。
  两套口径迟早会在报告里打不同的字。

## 版本边界

说清楚现在不做的事，比让人猜更安全：

- 不解析 EXIF 里的缩略图图像内容（只负责丢掉它）。
- **裸 TIFF 能读能审，不一定能改写。** JPEG / PNG 是"换掉那一段元数据"，
  裸 TIFF 是"整份文件重新产出"。只有当这份 TIFF 除了四张目录里的条目
  就没有别的东西时才动手（判据见上一节）；带像素数据的 TIFF 会得到
  `TiffNotByteExact`。完整支持它要在重写时重算 `StripOffsets` /
  `TileOffsets` / 缩略图指针这一组偏移，那是下一版的事。
- 不解码 TIFF 类型 11/12/13（`FLOAT` / `DOUBLE` / `IFD`），遇到报
  `UnsupportedType`；字节仍会原样搬走。
- 不处理藏在压缩流之后的元数据、也不处理重复 APP1；发现时会报
  `ExtraMetadata` 而不是假装没看见。
- 不支持 HEIF / WebP / RAW。
- **XMP 只摘不读。** 能认出 JPEG APP1、PNG `tEXt`/`iTXt` 与 TIFF `0x02bc`
  里的那一包，策略覆盖载体时整包摘掉并说出来；但不解析包里的字段，
  所以逐条清单里永远没有 XMP 的位置（这一条由 `xmp` 那个键补上）。
  一个文件里有多包时（扩展协议的第二段就靠同一个前缀认出来）每一包都在
  移除名单里——只摘第一份就是假脱敏。语料 99 个图像文件里这种分段的包 0 个。
- 不改写像素、不做转码。

## 测试与验证

```console
moon test                     # wasm（moon.mod 的 preferred_target）
moon test --target js
moon test --target wasm-gc
```

125 个用例。三个后端各跑一遍，最近一次实测都是 125 passed、0 failed。此外：

- **不自己给自己打分。** `ci/make_fixture.py` 用 Pillow 造 JPEG / PNG 测试
  文件，`ci/assert_pillow_reads.py` 先证明 Pillow 读得到这些条目（读不到的
  话，后面那半天的比对一文不值），脱敏之后 `ci/assert_redacted.py` 再用
  Pillow 复查：点名的条目读不到了、未点名的还在、输入文件逐字节没动、
  像素与原图完全一致。
- **真实照片语料对拍。** 上面那些 fixture 是自己造的，尺子也在自己手里，所以另有
  `ci/crosscheck_real.py`：拿 99 张不为这个库造的照片（`ianare/exif-samples`：
  91 张 JPEG + 8 张裸 TIFF）一张一张和 Pillow 对——逐条编号两个方向都要一致，
  然后**两档策略各脱一次敏**（`strict` 与 CLI 的缺省档 `privacy`），产物读回来、
  再审一遍、和输入比字节、和原图比像素。
  分母先自证：扫到 99、Pillow 打得开 99、打不开 0。最近一次全量实测 5 分 14 秒
  （每个文件起 8 次 `moon run cmd/main`：读、strict 审、strict 脱、产物再读、
  产物再审、privacy 脱、不带 `--policy` 脱、privacy 审；构建缓存已热）：
  **ok 91 / refused-rewrite 8 / triage 0**。
  那 8 个是裸 TIFF，重写判据按设计主动拒绝，脚本同时要求"拒绝必须干净"——
  留下一个看着像产物的坏文件就落进 triage。XMP 那一关单独计数：语料里带包 35 个、
  产物复查 89 个、摘除并且被 CLI 说出来的 34 个。35 与 34 差的那个是
  Arbitro.tiff，它的包住在 IFD 条目里（逐条清单本来就看得见它），而裸 TIFF 按上面
  那句不重写；89 比 91 少的两个（olympus-d320l.jpg、sony-powershota5.jpg）是连
  Pillow 都读出 0 条的文件，两边在"这个文件没有元数据"上一致、因而不写产物，
  它们的写侧没被这一趟验过。缺省档那一趟的分母单独打印，不与 strict 合并计数：
  这一轮是 **产物复查 89 / 摘除并披露 34**，与 strict 同宽。
  这一档以前一条真实语料证据都没有——四步写侧全跑在 strict 上，而用户不打
  `--policy` 时拿到的恰好是 `privacy`。它的期望不另抄一份敏感表：两档只差
  `timestamps` 一格，所以期望直接从同一个文件的 strict 审计结果按类别推
  （非时间戳的被点名条目必须在产物里读不到了、时间戳条目 Pillow 在原图看得到
  就还得在产物里看得到），再加一条逐字节比对钉住"缺省产物 == 显式
  `--policy privacy` 的产物"。这四句都往库里注入过对应的坏并且确认它红：
  `privacy_policy` 的 `timestamps` 改 true → "privacy 把该保留的时间戳删了"
  （4 个文件）；`location` 改 false → "privacy 没删掉被点名的条目"（3 个）；
  `carrier` 改 false → "privacy 之后产物里还有 XMP 包"（3 个，含只有 XMP
  没有 EXIF 的那个分支）；`main.mbt` 的缺省策略改 strict → "缺省策略的产物与
  --policy privacy 逐字节不一致"（4 个）。同策略闭合那一查（拿 privacy 再审
  自己的产物）在 `location` 注入下**不**红——策略不针对地点时审计自然觉得
  干净，这正是"闭合"与"独立量尺"两查都得在场的原因。
  两处分歧最后查下来是量尺的问题，脚本按文件打印字节证据后才归因：
  Canon_DIGITAL_IXUS_400.jpg 的 IFD0 里 Pillow 多报 1 条 274，那个值住在 XMP 包里；
  kodak-dc210.jpg 我们多报 2 条 (270, 33432)，那是 count=0 的空声明，Pillow 不列。
  第三种已知分歧（GPS 子目录挂在 Exif 子目录里，Pillow 的 `get_ifd(0x8825)` 只跟
  IFD0 那根指针）在这批语料里 0 格，在我们自己的 fixture 里 15 格。
  PNG 不在这批语料里，所以另外拿 Pillow 自己的测试语料（638 张 PNG，也全部不是
  本仓库造的）扫了一遍：字节里有 `eXIf` 块或有 XMP 包标记的只有 5 张（0.8%，
  其余 633 张两种标记都不在）——PNG 生态里 `eXIf` 本来就薄，
  这条限制现在有数了。那 5 张跑的是同一个脚本：**ok 5 / triage 0**，XMP 闸
  4 带包 / 5 产物复查 / 4 摘除并披露，缺省档那一趟同样是 5 产物复查 / 4 摘除并披露，
  `xmp` 键复核 5 份，量尺归因 0 格。
  PNG 的两种形状各撞到一次：`exif.png` 是外部工具写的真 `eXIf` 块（Pillow 读出
  1 条 274，我们读出同一条，逐条比对真的跑起来了）；另外 4 张只有住在
  `tEXt`/`iTXt` 里的 XMP 包——那种文件 Pillow 会从包里造出一个 `Orientation`，
  而我们的 `exif` 键说 false，走的正是"没有 EXIF 不等于没有元数据"那条分支。
  对拍脚本自己也有尺子：`ci/crosscheck_selftest.py` 33 个用例（实测 33 passed、
  rc=0）。其中 8 个钉的是缺省档那条纯判据——"时间戳被误删"这一格在正常库里
  永远是空的，语料全绿不说明它在工作，所以四个门槛各往宽里改过一次（去掉
  "原图看得到"那一前置、去掉归因豁免、让归因豁免渗到残留方向、按目录比改成
  拿裸编号跨目录比），每一次都由指名用例接住。
  今天还按 `.github/workflows/ci.yml` 的 `cli` 作业把六步在本机整条复跑了一遍
  （造 fixture → Pillow 读回 → 12 次命令行 → Pillow 验收脱敏结果 → 对拍脚本 → 自测），
  每一步退出码都是 0；其中对拍脚本对着 fixture 目录跑（CLI 那一步留下的产物一并算进去
  共 13 份，输出目录像计划文件那样放在语料目录之外，否则上一轮的产物会被这一轮当语料）
  报 ok 12 / 按设计拒绝 1，XMP 闸 2 带包 / 7 产物复查 / 2 摘除并披露，
  缺省档同样是 7 产物复查 / 2 摘除并披露，`xmp` 键复核 12 份，GPS 指针挂在 Exif 里 15 格。
- **畸形输入的性质测试。** `moonmeta_fuzz_test.mbt` 不用随机数：7 个种子文件的
  每一个前缀、每一个字节的 8 种单字节改写、再加尾部追加，共 12000 份输入，
  每份都过 `sniff` / `decode_any` / `describe_container` / `redact_any` /
  `strip_any` 五个入口。三条性质：不许 panic；每条错误都说得出地方，报出的
  偏移必须真的落在块内；`redact` / `strip` 声称成功之后，产物必须自己被读得
  回来、再审一条敏感都不剩、再删一个字节都不动。实测这 12000 份里拒绝 23598
  次、读通 6084 次、脱敏产出 4879 份、拆解产出 6123 份，定位分类 17926 / 4476
  / 1196——这些数字测试自己打印出来，每个都设了地板，扫描被改小就会红，
  不会悄悄变成空话。每条断言都往库里注入过一次坏并确认它红（偏移 +1000、
  GPS 目录不过滤、空收获也重编码、strip 跳过 XMP、`decode_tiff` 里越界读），
  注入的崩溃没被 `try ... catch` 吞掉，所以"不许 panic"这一条是真的在被测。
  一个反面结论也记在那里：`1 / 0` 在这个工具链上不出声也不红，不是合格的崩溃探针。
- 第三份 fixture 是裸 TIFF 对照，用来钉住"这个文件本来就没有 EXIF"和
  "元数据已清除"这两条分支——混为一谈的脱敏工具没有可信的理由。
  注意裸 TIFF 的 IFD0 就是图像本身的结构，"没有 EXIF"指的是没有 34665 指针。
- 这些脚本的调用顺序就是 `.github/workflows/ci.yml` 里 `cli` 作业的顺序，
  本地可以逐条复跑。工作流本身还没在 GitHub 上跑过：仓库目前没有配远端。
- 测试矩阵是 wasm / JavaScript / wasm-gc，没有 native：`x/fs` 带 C stub，
  `moon test --target native` 要先装一个 C 编译器。三个后端跑的是同一套
  断言，一个后端过、另一个不过，说明代码里混进了只在某个运行时装得起来的
  行为。
- 覆盖率：`moon test --enable-coverage && moon coverage analyze -- -f summary`
  → 1197/1393 行（85.9%）。`cmd/main/main.mbt` 那 333 行可执行语句里覆盖到的 196 行，
  没覆盖的几乎全是真正读写文件的几行：`x/fs` 在非 native 后端没有文件系统，
  而包的测试要在三个后端都跑绿，所以判断逻辑（路径拼装、覆盖拒绝、策略解析）
  单独抽成纯函数测了，IO 那几行留给 CI 的 `cli` 作业。
  分母里有一条谁都到不了的分支：`moonmeta_tiff.mbt` 里 `parse_entry` 的第二次
  长度检查——它上面那两道检查已经保证了它不成立，源码里就写着这句话，
  免得后来人把它当成"被测过的行为"。

## 怎么拿到这个包

本模块还没发布到 mooncakes，所以 `moon add shencangsheng513/moonmeta`
现在取不到。下面两条取用方式都实际跑过：

拿源码直接用它自带的命令行（在仓库根目录）：

```console
$ moon run cmd/main -- audit 一张照片.jpg --policy strict
```

当依赖装进别的模块：`moon.mod` 不支持本地路径依赖，官方给的替代是
workspace。在两个模块的共同上级放一个 `moon.work`：

```console
$ moon work init
$ moon work use 本仓库的路径 你的模块的路径
```

然后在你的 `src/.../moon.pkg` 里写

```moonbit nocheck
///|
import {
  "shencangsheng513/moonmeta",
}
```

`moon check` 就会把 `@moonmeta` 解析到本地源码。发布之后这一步可以省掉，
直接 `moon add shencangsheng513/moonmeta`。

## 许可

Apache-2.0。
