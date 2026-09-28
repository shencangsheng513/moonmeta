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

写操作另认 `-o`（输出路径）、`--force`（就地覆盖）与 `--keep-bytes`
（只作用于裸 TIFF，见下面"裸 TIFF 的出路"那一节）。

下面几段真实输出都对着 `ci/make_fixture.py` 造的六份文件（Pillow 亲手写进
容器，默认落在 `.scratch/fix/`）：`cross.jpg` / `cross.png` / `cross.tiff`
是同一份元数据的三种装法，`cross_xmp.jpg` 在此基础上另带一包 XMP，
`xmp_only.jpg` 则只有那包 XMP、没有 EXIF，`bare_gps.tiff` 是这批里唯一
"带元数据的裸 TIFF"（下面 `--keep-bytes` 那一节用它）。

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
人读输出少：`xmp` / `iptc` 两个键就是人读那两句"另含 XMP 包""另含
IPTC/Photoshop 包"的同一个事实，`unread` 那一栏则是"这几段我们认不出来、
也就没碰"——它既不是"已处理"，也不是"没有东西"。
`findings` 里的 `tag` 是十进制整数（`315` 即 `0x013b`）：

```console
$ moon run cmd/main -- read .scratch/fix/xmp_only.jpg --json
{"file":".scratch/fix/xmp_only.jpg","container":"jpeg","xmp":true,"iptc":false,"unread":[],"exif":false}
```

```console
$ moon run cmd/main -- audit .scratch/fix/cross_xmp.jpg --policy strict --json
{"file":".scratch/fix/cross_xmp.jpg","policy":"strict","xmp":true,"iptc":false,"unread":[],"exif":true,"findings":[{"dir":"IFD0","tag":315,"name":"Artist","category":"identity"},{"dir":"Exif","tag":36867,"name":"DateTimeOriginal","category":"timestamps"},{"dir":"Exif","tag":36868,"name":"DateTimeDigitized","category":"timestamps"},{"dir":"Exif","tag":36881,"name":"OffsetTimeOriginal","category":"timestamps"},{"dir":"Exif","tag":37500,"name":"MakerNote","category":"maker_note"},{"dir":"Exif","tag":42033,"name":"BodySerialNumber","category":"device_id"},{"dir":"Exif","tag":42037,"name":"LensSerialNumber","category":"device_id"},{"dir":"GPS","tag":0,"name":"GPSVersionID","category":"location"},{"dir":"GPS","tag":1,"name":"GPSLatitudeRef","category":"location"},{"dir":"GPS","tag":2,"name":"GPSLatitude","category":"location"},{"dir":"GPS","tag":3,"name":"GPSLongitudeRef","category":"location"},{"dir":"GPS","tag":4,"name":"GPSLongitude","category":"location"}]}
```

`findings` 里只有命中的条目：策略没点名的东西（`Make`、`Copyright`）不出现，
整包的 XMP 与 IPTC/Photoshop 包也不出现——它们不归 IFD 条目管，各用自己的键
（`xmp` / `iptc`）交代。前者是"留不留由人决定"，后者是"留了却没人说"——
所以包必须有自己那个键。只有包、没有 EXIF 的文件就走这条分支：
`exif` 是 `false`，而那份隐私副本确实在里面。

一张同时带着两种包、外加一段认不出来的东西的照片，能把这三键一次说全
（下面这个文件来自 `ianare/exif-samples`，来路见"测试与验证"里那一段；
仓库里不带它）：

```console
$ moon run cmd/main -- audit .scratch/exif-samples/jpg/orientation/landscape_1.jpg --policy strict
.scratch/exif-samples/jpg/orientation/landscape_1.jpg: 策略 strict 命中 0 条。
另含 XMP 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。
另含 IPTC/Photoshop 包：逐条清单里看不到它；策略覆盖载体，会整包摘除。
  未解析段 1 段（本库不读也不删）：APP12@102
```

逐条清单命中 0 条，而这个文件里躺着两份完整副本——这就是为什么"命中几条"
不能当脱敏的依据。摘完之后：

```console
$ moon run cmd/main -- strip .scratch/exif-samples/jpg/orientation/landscape_1.jpg -o .scratch/d9e_doc/l1.jpg
元数据已整段摘除：EXIF,XMP 包,IPTC/Photoshop 包。
已写出 .scratch/d9e_doc/l1.jpg
$ moon run cmd/main -- read .scratch/d9e_doc/l1.jpg --json
{"file":".scratch/d9e_doc/l1.jpg","container":"jpeg","xmp":false,"iptc":false,"unread":["APP12@2"],"exif":false}
```

`unread` 在产物里仍然指着那一段 APP12——**它换了偏移**（102 → 2），因为它前面
那几段被摘掉了，而这一段我们既没读也没删。这一栏要说的是这个文件此刻的样子，
不是"处理完了"：认不出来的东西只点名，绝不声称删掉了。

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

### 裸 TIFF 的出路：`--keep-bytes`

裸 TIFF 在默认那条写路上是**按设计拒绝**的：整份重编码会把这一版没建模的字节
丢掉（三方语料里实测最少 1148、最多 1152 字节），库宁可拒绝也不写一个不能证明
逐字节等价的产物。`--keep-bytes` 是给它的那条出路——只改目录表那一段（把命中的
条目从表里摘掉、外置的值清零），其余字节原样留着，所以文件长度不变：

```console
$ moon run cmd/main -- redact .scratch/fix/bare_gps.tiff --keep-bytes --policy strict -o out.tif
原位模式：文件长度不变（1530 字节），像素与缩略图链一个字节未动（这个文件没有缩略图目录链）。
  - IFD0/Artist (identity)
  - GPS/GPSLongitude (location)
  ...
删除 7 条。
已写出 out.tif
```

`strip` 在同一份文件上说的还是那句"整段摘除在这里做不到"，只是它现在能把
不参与解码的那部分真摘掉（下面这份 IFD0 里除了图像结构什么都不剩，于是连这一步
都无事可做）：

```console
$ moon run cmd/main -- strip .scratch/fix/bare_gps.tiff --keep-bytes -o out.tif
原位模式：文件长度不变（1530 字节），像素与缩略图链一个字节未动（这个文件没有缩略图目录链）。
原位摘除非解码条目：EXIF。IFD0 里留着 10 条图像解码必需的字段（宽高/压缩/条带位置…）：裸 TIFF 的图像说明与元数据在同一张表里，'整段摘除'在这里做不到。
已写出 out.tif
$ moon run cmd/main -- strip .scratch/fix/cross.tiff --keep-bytes -o out.tif
原位模式：文件长度不变（1292 字节），像素与缩略图链一个字节未动（这个文件没有缩略图目录链）。
这个文件的 IFD0 里没有不参与解码的条目，一个字节都没改。IFD0 里留着 10 条图像解码必需的字段（宽高/压缩/条带位置…）：裸 TIFF 的图像说明与元数据在同一张表里，'整段摘除'在这里做不到。
已写出 out.tif
```

那句"长度不变"是**落笔之后**才说的：原位模式会在半路拒绝（某个条目的类型码这一版
不解码），话先说出去就成了"长度不变"+"我没做"两句同时成立。

JPEG / PNG 加这个旗标什么都不改——它们本来就已经只换装元数据那一段。这时候 CLI
要当面说一句"这里不适用"，而不是安静地按原路走：安静地接受一个被忽略的旗标，
等于教会用户相信它生效了。

```console
$ moon run cmd/main -- redact .scratch/fix/cross.jpg --keep-bytes --policy strict -o out.jpg
这个容器是 jpeg，本来就不搬字节：--keep-bytes 在这里不改变任何行为。
  - IFD0/Artist (identity)
  ...
删除 12 条。
已写出 out.jpg
```

边界也必须由这同一个文件的结构说出来：原位模式不碰像素，也不碰缩略图目录链，
而链里可能另有一份坐标。`--keep-bytes` 出来的文件不等于默认那条路的产物，
CLI 把这一句打印在承诺里。两句各钉一边：带链要说"还有一条缩略图目录链…要连它
一起清只能走不带 `--keep-bytes` 的那条路，而那条路要求整份文件能被逐字节重建"，
不带链的那份不许冒认"链还在"——`cmd/main/main_wbtest.mbt`
把 `inplace_said` 的两个分支各调一次、逐句断言（连同 `has_chain` 在"根本没有 TIFF
块"时的第三种回答）。这条路上每份产物还要过一把独立门禁：`ci/inplace_crosscheck.py`
把施工区间之外的字节一段段核回去，见「测试与验证」。

那句"链还在"2026-09-27 第一次在陌生文件上打印出来：第三批 104 个外来裸 TIFF 里有 12 个
带着下一张目录的链，其中 `multipage.tiff`（816 字节）与 `compression.tif`
（646 字节）都说了那句边界。但同一轮实测记着另一半：这两份文件**不带**旗标时，
默认那条整段重写路按设计拒绝（重建与原文件分别差 246、262 字节）——也就是说
带链的外来裸 TIFF 2026-09-28 两条路都清不到链里那份第二副本。那句话原先犯的正是
"文案指向一条代码不会兑现的出路"：它叫用户"别加 `--keep-bytes`"，而这条路对本类
文件实测零放行。本轮把它改成当句说出前提与失败方式（"只能走不带 `--keep-bytes`
的那条路，而那条路要求整份文件能被逐字节重建；重建不了的裸 TIFF 会在落笔前拒绝
并说出会丢多少字节，那种文件两条路都清不到链里这一份"），并在 `multipage.tiff`
上原地复跑：加旗标打的就是这句新话，同一份文件去掉旗标退码 1、拒绝句里的数字
仍是 246 字节。限制本身一点没动——它只是不再被一句话藏起来。

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

上面这段是可执行文档：它的函数体住在 `moonmeta_readme_test.mbt` 里当测试跑，那份只比这里多
一句断言——把 `_report` 接成 `report`，再钉一行 `@test.assert_eq(report.removed.length(), findings.length())`，
也就是"报告说删了几条，产物里就得真少几条"。接口一改构建就红，把流程改坏也红。
它对着 `moonmeta_tiff_test.mbt` 里那份手算 fixture
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
| `tiff_redact_inplace(data, policy)` | 就地脱敏：只改目录表那一段，长度不变 |
| `tiff_strip_inplace(data)` | 就地摘除非解码条目，并说明"整段"为何做不到 |
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
| `Carrier` | 容器里成包的第二份副本：JPEG 的 XMP APP1 与 APP13（`Photoshop 3.0` 资源包，IPTC-IIM 住在里面）、PNG 里关键字为 `XML:com.adobe.xmp` 的 `tEXt`/`iTXt`，以及 TIFF 里装整包的 `0x02bc` / `0x02bd` / `0x83bb` | ✔ | ✔ |

`Carrier` 和上面六类不是同一种东西：其余六类删的是 IFD 里的一条条目，
它删的是另一整套元数据。这一类是被真实语料逼出来的——逐条策略删干净之后，
82 个产物里仍有 13 个能搜到 `exif:DateTimeOriginal`、`dc:creator`、
`aux:SerialNumber`：同一批事实的第二份副本，住在 XMP 包里，
逐条清单永远不会把它列出来。所以现在它是一等公民：能点名、能删、
删了要在报告与命令行里说出来（`Redaction::dropped_xmp`）。

同一件事在另一种包上又来了一遍：JPEG 的 APP13 里那份 `Photoshop 3.0` 资源包
（IPTC-IIM 住在里面，署名、版权、联系人常在这儿）在逐条清单里同样看不见，
两批外来 JPEG 语料里各有 10 张 / 20 张带着它，而以前 `read` 只报 `xmp` 一位——
于是那种文件会读成"什么都没有了"。现在它有 `Redaction::dropped_iptc` 与
`read --json` 的 `iptc` 键，两档策略都连它一起摘、摘了都要说出来。
这一位在 PNG 与裸 TIFF 上**必须**恒为 `false`：前者的 IPTC 走的是没解析的
文本块（由 `unread` 逐段点名），后者是 IFD0 里的一条（逐条清单本来就看得见），
两处报 `true` 都是无中生有，判据在 `ci/crosscheck_real.py` 里双向钉着。

另有 `empty_policy()`：什么都不删，只用作只读审计的对照，连 XMP 包也不碰
（`dropped_xmp` 因此是 `false`，不是"没有包"）。命令行目前只认 `privacy` 与
`strict`，两者都覆盖载体；那句"警告：当前策略不碰它"是给在库里自己拼
`Policy` 的人准备的，两个分支都钉在 `cmd/main/main_wbtest.mbt` 里。

分类明细住在 `moonmeta_tags.mbt` 的 `sensitive_tags` 表里：17 行
（每个编号都对着 exiftool 的 tag 名表核过）+ "GPS 目录整体算 `Location`"
一条规则。报告上能打名字是因为 65 个编号有规范名（IFD0 15 个、Exif 14 个、
GPS 32 个、Interop 4 个），这 65 行逐条钉在 `moonmeta_tags_test.mbt` 里；表外的编号
回吐十六进制，不拿别的目录的名字凑。`Copyright` 刻意不在任何类别里——
它是权利声明，抹掉它本身就是一种伤害。

## 不可让步的几条约定

- **错误必须说得出地方。** 23 种错误变体分三类：15 种报出坏在第几个字节
  （`TooShort` 与 `EntryTooLarge` 现在也各自带偏移，不只报数额），3 种报出
  那个把读者带出块外的指针值本身（它被拒绝就是因为它不在块内，拿块长要求它
  反而是错的），5 种是回写期的错误、拿条目 tag 定位。只报"坏了"是一个无法
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
  `TiffNotByteExact`。这条限制有多严，外来语料量过：Pillow 测试目录里 104 个
  陌生 TIFF，通过判据的 **0 个**（86 个得到 `TiffNotByteExact`、2 个在读侧就因
  类型 11/12/13 停下），实测那种文件 `redact` 与 `strip` 都是退出码 1 加一句带数字
  的拒绝（IFD0 在哪、会丢多少字节），且不落任何产物——宁可不动，也不写一个
  不能证明逐字节等价的产物。**这一轮给它加了一条出路**：`--keep-bytes` 走原位
  （只改目录表那一段，长度不变），同一批 104 份上 strict 腿写出 15 份产物、68 份
  无事可做（D15 之前是 19 / 63，差的四份见下面 D15 那一段）、
  strip 腿 49 份，每份由 `ci/inplace_crosscheck.py` 反着核过；它的代价与边界写在
  上面那一节（不碰像素、也不碰缩略图目录链）。至于"带像素的整份重产出"，
  完整支持它要在重写时重算 `StripOffsets` / `TileOffsets` / 缩略图指针这一组
  偏移，那是下一版的事。
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

163 个用例。三个后端各跑一遍，2026-09-27 实测都是 `Total tests: 163, passed: 163,
failed: 0`（wasm / js / wasm-gc 各一次，退码都是 0）。此外：

- **不自己给自己打分。** `ci/make_fixture.py` 用 Pillow 造 JPEG / PNG 测试
  文件，`ci/assert_pillow_reads.py` 先证明 Pillow 读得到这些条目（读不到的
  话，后面那半天的比对一文不值），脱敏之后 `ci/assert_redacted.py` 再用
  Pillow 复查：点名的条目读不到了、未点名的还在、输入文件逐字节没动、
  像素与原图完全一致。
- **四批外来语料的来路**（都是别人的仓库，克隆 + 一条采集命令即可复算；下面两条
  `git ls-remote` 2026-09-27 与 2026-09-28 各自实跑过，都拿得到 `refs/heads`）。
  `git clone --depth 1 https://github.com/ianare/exif-samples.git` 出第一批；
  `git clone --depth 1 https://github.com/python-pillow/Pillow.git` 出第二、三、
  四批，用 `python -u ci/grab_corpus.py <克隆目录> --batch tiff|jpeg|png --out <目录>`
  挑——规则住在代码里（都只看 `Tests/images` 根下那一层，再按容器魔数和"字节里到底
  有没有元数据标记"筛），没挑上的按原因计数打印而不是静默丢。2026-09-28 从真克隆跑出来是
  TIFF 106 候选留 104（被筛掉的那两个都以 `II+` 开头，是 BigTIFF）、JPEG 55 全留、
  PNG 319 候选留 5，与跑对拍用的那三份目录逐字节相同（sha256 逐个比过）。
  扫描器按 `IMAGE_SUFFIXES` 过滤后缀，所以 exif-samples 那一批进分母的是 `jpg/`
  与 `tiff/` 下的 91 张 JPEG + 8 张裸 TIFF = 99，`heic/` 那 6 个后缀不在表里、
  不进分母（2026-09-28 从真克隆数一遍 IMAGE_SUFFIXES 命中的也是 99，文件名集合与本机那份
  完全一致）。拿到目录就跑
  `python -u ci/crosscheck_real.py <语料目录> -o <产物目录> --moon <moon 路径>`；
  原位那条腿单独跑
  `python -u ci/inplace_crosscheck.py <TIFF 目录> --strip -o <产物目录> --moon <moon 路径>`。
  两条门禁的产物目录都要在语料目录之外、且各用各的（strict 与 strip 的产物同名）。
- **真实照片语料对拍。** 上面那些 fixture 是自己造的，尺子也在自己手里，所以另有
  `ci/crosscheck_real.py`：拿 99 张不为这个库造的照片（`ianare/exif-samples`：
  91 张 JPEG + 8 张裸 TIFF）一张一张和 Pillow 对——逐条编号两个方向都要一致，
  然后**两档策略各脱一次敏**（`strict` 与 CLI 的缺省档 `privacy`），
  再**整段摘一次**（`strip`），产物读回来、再审一遍、和输入比字节、和原图比像素。
  分母先自证：扫到 99、Pillow 打得开 99、打不开 0。最近一次全量实测 5 分 13 秒
  （每个文件起 10 次 `moon run cmd/main`：读、strict 审、strict 脱、产物再读、
  产物再审、privacy 脱、不带 `--policy` 脱、privacy 审、strip 摘、strip 产物再读；
  构建缓存已热）：**ok 91 / refused-rewrite 8 / triage 0**。
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
  `--policy privacy` 的产物"。
  这一批里 IPTC 那一关的账另记一本：**语料里带 APP13 包 10 个，摘除并且被 CLI
  说出来的 10 个，缺省档那一趟同样是 10 个**——这一次没有差额要解释：那 8 个
  按设计拒绝改写的都是裸 TIFF，而 10 个带包的文件全在 `jpg/` 里（这一点是拿
  这个文件自己的字节数的，不是按后缀推的）。`iptc` 键在全部 99 个文件上都与
  原始字节双向核过（包括那 8 个没有产物的），`unread` 键在这一批里点出 12 段
  本库不读也不删的段，每一段的名字与偏移都回到原文件字节上验过。
  缺省档那四句判据都往库里注入过对应的坏并且确认它红：
  `privacy_policy` 的 `timestamps` 改 true → "privacy 把该保留的时间戳删了"
  （4 个文件）；`location` 改 false → "privacy 没删掉被点名的条目"（3 个）；
  `carrier` 改 false → "privacy 之后产物里还有 XMP 包"（3 个，含只有 XMP
  没有 EXIF 的那个分支）；`main.mbt` 的缺省策略改 strict → "缺省策略的产物与
  --policy privacy 逐字节不一致"（4 个）。同策略闭合那一查（拿 privacy 再审
  自己的产物）在 `location` 注入下**不**红——策略不针对地点时审计自然觉得
  干净，这正是"闭合"与"独立量尺"两查都得在场的原因。
  `strip` 那一趟是这一轮新补的：写侧四步里它一直是零真实语料证据（脚本从前不跑它）。
  分母单独打印：**写侧产物 89 个，其中源文件带着 XMP 包 34 个**，与 strict 那一档的
  "产物复查 89 / 摘除并披露 34"逐格同宽——这就是这一关要的性质：凡 `strict redact`
  写得出的文件，`strip` 也必须写得出来。六路观察各自独立、任何一路红都不需要另一路
  背书：产物被我们自己的 `read` 判成 `exif=false` 且 `xmp`、`iptc` 都不为真、
  被 Pillow 读不出四张目录里的任何条目、字节里既搜不到包标记（XMP 的与 IPTC 的）
  也搜不到那 16 个敏感键、CLI 那句话点名的
  载体与这个文件的事实一致、输入逐字节没动、像素与原图一致。
  "句与事实"那一判刻意不做子串查找：否定那句"这个文件本来就没有 EXIF，也没有 XMP 包"
  里 EXIF 和 XMP 两个词都在，查子串会把一条谎当成实话；那句话因此从 `strip_file`
  里抽成了 `strip_said`，四个状态各一句、由 `main_wbtest.mbt` 逐字钉住。
  这几路各注入过一次坏并确认它红（跑的是这批语料的前 4~5 个文件）：jpeg 的 strip
  跳过 XMP 包 → 1 个文件同时红三句（产物里还有包、`read` 还报得出 XMP、那句话没交代
  摘除它）；png 侧同样跳过 → 4 个文件红；摘干净了却报告"本来就没有" → 4 个文件红，
  而且**只**红在句上（字节与 Pillow 两路都不报，说明这一路不是替上一路顶岗）；
  让 strip 对 JPEG 一律拒绝改写 → 3 个文件红在"redact 写得出的文件，strip 退出码"
  那一句（这一路不比对错误措辞，比对的是两个动作得共用同一道判据）；
  把这一关整个短路 → 一格都没跑，脚本自己打印"strip 这一关一个文件都没跑到"并
  返回 1：全绿不等于测过。D9-E 之后又补了两格同样形状的坏：jpeg 的 strip 跳过
  APP13 → 1 个文件同时红两句（`read` 还报得出 IPTC 包、字节里还搜得到那个头），
  摘干净却不交代 → 1 个文件**只**红在"源文件带着 IPTC/Photoshop 包，strip 却没有
  交代摘除它"那一句。**这两格不是加进去就有效的**：带 APP13 的文件在这批语料的
  字典序里排在第 11、31、32、51、77……位，`--limit 4` 一步都走不到它们，于是驱动
  多了一个 `--only` 透传（对拍脚本本来就支持），两格都点到 `landscape_1.jpg`——
  实测各"分诊 1 个"，这一句是"那条分支真的跑到了"的证据，没有它这两格是死闸。
  每次注入都在 `finally` 里按字节还原并核对 sha，七处跑完再复跑一次真绿
  （实测 rc=0、分诊 0 个）。收尾那句以前硬写着"五处坏各处红一次"，改成派生数字的
  同时给判定器补了一条计数闸：`期望表态 N 处 / 抓到 M 处` 两个数必须相等，
  否则把正则从"五处"放宽成"若干处"会让少红一格照样算绿（这一条正反各占真值表一格）。
  还没被语料覆盖的那一半得说清：`strip` 对裸 TIFF 的分支在这批语料里 0 格
  （那 8 个全在重写判据那儿按设计停了），那一支由库内测试和 12000 份性质测试
  （`strip_any` 是七个入口之一）覆盖，不是这条语料闸。**这一句是当时那批的口径**：
  第三批的 `strip` 腿同样一格没跑到（重写判据零放行），真正给这一支补上外来
  语料证据的是本轮的原位路——`--keep-bytes` 下同一批 104 份写出 49 份产物，
  每份由 `ci/inplace_crosscheck.py` 反着核过。
  两处分歧最后查下来是量尺的问题，脚本按文件打印字节证据后才归因：
  Canon_DIGITAL_IXUS_400.jpg 的 IFD0 里 Pillow 多报 1 条 274，那个值住在 XMP 包里；
  kodak-dc210.jpg 我们多报 2 条 (270, 33432)，那是 count=0 的空声明，Pillow 不列。
  第三种已知分歧（GPS 子目录挂在 Exif 子目录里，Pillow 的 `get_ifd(0x8825)` 只跟
  IFD0 那根指针）在这批语料里 0 格，在我们自己的 fixture 里 15 格。
  PNG 不在这批语料里，所以另外拿 Pillow 自己的测试语料（638 张 PNG，也全部不是
  本仓库造的）扫了一遍：字节里有 `eXIf` 块或有 XMP 包标记的只有 5 张（0.8%，
  其余 633 张两种标记都不在）——PNG 生态里 `eXIf` 本来就薄，
  这条限制现在有数了。那 5 张跑的是同一个脚本（6 秒）：**ok 5 / triage 0**，XMP 闸
  4 带包 / 5 产物复查 / 4 摘除并披露，缺省档那一趟同样是 5 产物复查 / 4 摘除并披露，
  `strip` 那一趟 5 个产物、其中 4 个源文件带着包，`xmp` 键复核 5 份，量尺归因 0 格。
  这一轮的 IPTC 闸在 PNG 上是**要求它恒为 0** 的那一半：带包 0 / 摘除并披露 0 /
  缺省档 0，而 `iptc` 键仍然逐份与这个文件的字节比过（5 份）——PNG 没有成包的
  IPTC 载体，所以这一格要钉的不是"摘得干净"，是"不许无中生有地说有"；
  `unread` 在这一批里点出 8 段。
  PNG 的两种形状各撞到一次：`exif.png` 是外部工具写的真 `eXIf` 块（Pillow 读出
  1 条 274，我们读出同一条，逐条比对真的跑起来了）；另外 4 张只有住在
  `tEXt`/`iTXt` 里的 XMP 包——那种文件 Pillow 会从包里造出一个 `Orientation`，
  而我们的 `exif` 键说 false，走的正是"没有 EXIF 不等于没有元数据"那条分支。
  裸 TIFF 的回写判据到这一步只见过我们自己造的字节（上面那 8 个全在判据前停了），
  于是另抓第三批外来语料专门问这一个问题：`check_tiff_rewrite` 在陌生人的文件上
  到底放不放行。语料是 Pillow 自己测试目录里的 TIFF（`Tests/images` 下魔数真对得
  上的 104 个，含 `crash-*` / `oom-*` 那批畸形件与 `hopper*`、`ifd_tag_type` 等，
  没有一个为本仓库而造）。实测答案是一个都不放行：分母自证——扫到 104、Pillow
  `verify()` 通得过 98、其中连像素也解得开 88（只有这 88 个进分母）、完全打不开 6；
  这 88 个里 **ok 0 / 按设计拒绝 86 / 读侧因类型 11、12、13 停下 2 / triage 0**。
  那 86 句里 48 个的 IFD0 根本不在偏移 8，"写下去会丢"的字节数最少 36、最多
  4128411（min/max 由脚本按文件算完再汇总打印，不是挑出来的好看数字）。
  所以前面那句"`strip` 对裸 TIFF 的分支在这批语料里 0 格"不是那 99 张照片的偶然：
  外来裸 TIFF 上这道判据同样一次都没让路，库宁可把整个文件原样留着，也不写一个
  它不能证明逐字节等价的产物。这一批的绿因此**不**包含裸 TIFF 写侧，脚本自己就把
  这句话打印出来并返回 1（"strip 这一关一个文件都没跑到"）——全绿不等于测过。
  这一批的 IPTC 闸同样是"要求它恒为 0"那一半：带包 0 / 摘除并披露 0 / 缺省档 0，
  `unread` 点出 0 段，而 `iptc` 键在进分母的 86 个文件上都与原文件字节核过。
  裸 TIFF 上 IPTC 不住在"成包"里，而是 IFD0 的一条（`IptcNaa` 0x83bb、
  `PhotoshopSettings` 0x02bd——逐条清单本来就看得见它们），所以这一位在裸 TIFF 上
  按设计恒为 false，报 true 就是无中生有：这一格钉的正是"不许说在有"。
  跟着第三批补上的是脚本口径的一次升级：库里每一句"这一步我不做"都带着数字
  （IFD0 在哪个偏移、文件多少字节、模型重建出多少字节、哪个 tag 用了哪个类型码、
  指针越到哪个偏移），这些数以前是**信库说的**，等于让被检方自己填报告。现在每一
  个都由这个文件自己的字节反着算：脚本自己走一遍 IFD 链，按 TIFF 6.0 的宽度表
  算出每条条目的类型码、声明字节数与值偏移（那张表刻意抄规范、不 import 库的常量
  ——拿被检方自己的表去检被检方等于没检），复核不上就落回 triage。这一步当场抓出
  **脚本自己**的一个假红：`designed-malformed-pointer` 从前要求"指针本身越过文件尾"，
  库的判据却是 `指针 + 声明字节数 > 块长`，16 个量尺进不去的文件里有 4 个因此被
  冤枉成"数字撒谎"（那 4 个是真越界，错的是复核它的尺子）。另外两支是缺的：
  `EntryTooLarge` 那句（"某个偏移之后声明的字节放不下"）以前没有匹配分支，
  一句合法拒绝被记成"没有任何一句形状能被字节复核"；`IfdOffsetOutOfRange` 的文案
  写着"或者没对齐"，而代码里没有任何一处做对齐检查——那是库在替一次不存在的检查
  背书，先删文案，脚本的匹配句与库内那条整句钉死的测试（`moonmeta_error_wbtest.mbt`
  现在逐字钉 17 句）跟着改。量尺进不去的那 16 个也不当免检：`read` 照跑、每一句
  读侧拒绝照核（这类判据只需要这个文件自己的字节，不需要一把能解像素的尺子），
  计数单记 `secondpass-*`、不进任何比率的分母。实测这 16 个里 11 个复核通过
  （类型编号不存在 4、值指针越界 6、声明字节放不下 1）、5 个是"引擎读得通而无尺
  可核"（按文件点名，不冒充成通过）、复核不上 0 个——三个以前 0 格的桶第一次有了
  真实语料的格子。**仍然 0 格的也说清**：`designed-wrong-magic` 三批语料都没有，
  子目录指针与 IFD 偏移那两支只有合成用例钉着。这六处谎报各往库里注入过一次并
  确认它红（`ci/mutations/mut_d8.py`，语料用这批里跨两趟的 6 个文件）：IFD0 偏移 +1000
  → 2 个文件红在"文件头自己写的是"、重建长度报成文件长度 → 2 个红在"那句会丢字节
  就不成立"、文件长度多报 1 → 2 个红在"实际"、类型码谎报一位 → 1 个红在"复核不上"、
  把越界指针报成块内偏移 → 1 个红在"复核不上"、目录表谎报声明字节数 → 1 个红在
  "那个数字复核不上"（后两处只有第二趟抓得到，第一趟的分母里没有它们）。每处
  `finally` 按字节还原并核对 sha，六处跑完复跑一次真绿（分诊 0 个；那批语料的
  退出码按设计是 1，所以判红看的是分诊数而不是退出码）。
  "旧结论一格没动"这一句这次是按文件核的，不是看退出码：把四批跑批里每个文件
  自己那一行判据（`ok:` / `designed-*:` / `refused-rewrite:` / `triage:` 开头那些）
  抽出来排序，与升级前的快照逐行 diff——99 张照片、5 张 PNG、104 个裸 TIFF 三批
  共 208 行**逐字一致**，只有第四批那 55 行里恰好 8 行变了，而且变的正是这轮要
  修的 8 个待查（`hopper_bad_exif.jpg` 从"连 TIFF 头都不是，无从复核"变成
  `designed-truncated-value`，其余七个同理）。退出码：四条对拍腿 0 / 0 / 0 / 1，
  前三条与上一轮相同，第四批那条从首测的 1 变成这一轮的 0（就是那 8 格拿到了
  字节尺），最后一条 1 是按设计出声——`strip` 对裸 TIFF 一格都没跑到。原位两条腿
  各 104 份、分母自证通过：strict 腿 ok 19 / 无事可做 63 / 设计内拒绝 9 /
  我们读不通 13，strip 腿 ok 49 / 13 / 29 / 13，两腿 triage 都是 0。
  第四批语料专门问容器：Pillow `Tests/images` 里的 55 个 JPEG（同样没有一个为本
  仓库而造），首测 **ok 44 / triage 8**——八个待查不是八个坏文件，是复核它们的
  尺子错了。根因只有一句：库里那些读侧拒绝报的偏移是**块内**偏移（JPEG 是 APP1
  去掉 `Exif\0\0` 那 6 字节之后的一段，PNG 是 `eXIf` 的载荷），而脚本一直拿整个
  容器文件去比——于是"这个文件连 TIFF 头都不是"对 JPEG 永远为真，每一条合法拒绝
  都被判成"数字无从复核"。现在块由脚本自己定：走一遍 JPEG 段表（`FF <码> <2 字节
  大端长度> <载荷>`，无长度域的段码单列一张表）或 PNG 块表（长度+类型+载荷+CRC），
  块内的数字核块长，块外的句子按容器分别数——第二份元数据在 JPEG 数的是签名偏移
  （`Exif\0\0` 与 XMP 的 URI 并集），在 PNG 数的是 `eXIf` 块起点，两处口径本来就
  不同，合成用例各钉一边。新增三个桶（`designed-second-metadata-block` /
  `designed-truncated-segments` / `designed-short-block`），`designed-truncated-value`
  也第一次能在容器上判。本轮实测 rc=0、triage 0，分母自证：扫到 55、verify 全过、
  连像素也解得开 53 才进分母，分桶是 ok 44 / 第二份元数据块 3 / 断在段表中间 3 /
  声明字节放不下 1 / 块装不下 1 / 容器魔数不对 1；`designed-wrong-magic`
  （`invalid-exif.jpg`）是那一支在**四批语料上的第一格真实证据**，先前那句"三批
  都没有"到此作废；仍然只有合成用例的还剩两支：子目录指针与 IFD 偏移越界。
  这一批的第二趟是 2 个 no-scale（`truncated_jpeg.jpg`、`ultrahdr.jpg`：引擎读得通、
  量尺解不开），复核不上 0 个。三把新尺子都遵守同一条保守规矩：证据凑不齐
  （块边界算不出来、签名数不出来、停下的原因对不上）就返回"无从复核"落回 triage，
  绝不静默放行。
  这一批的 IPTC 闸终于有了非零的一格：**带包 20 / 摘除并披露 15 / 缺省档那一趟
  15**，`iptc` 键在进分母的 44 个文件上都按字节双向核过，`unread` 点出 3 段。
  20 与 15 差的那 5 个不是漏网，是一个字节都没写出去的那 5 个文件——
  `hopper_bad_exif.jpg`、`invalid-exif.jpg`、`photoshop-200dpi-broken.jpg`、
  `truncated_app14.jpg`、`truncated_exif_dpi.jpg`，正好是这一批 8 个按设计拒绝
  改写的文件里带包的哪些（这个名字表是拿产物目录与语料字节对出来的，不是推的）。
  产物侧另补了一次穷扫：这一轮的 125 份产物（32 份 `.stripped` + 32 份
  `.redacted` + 32 份 `.privacy` + 29 份 `.default`）里，逐份读字节，
  含 `Photoshop 3.0\0` 的 0 份。
  顺手抓到的还有一个更难看的东西：第二趟的兜底文案就地抄了一遍第一趟那句话，
  抄来了一个该作用域里不存在的名字——那条路一旦命中不是红，是整批崩在
  `NameError` 上；而四批语料没有一格走到它，所以它一直活着。现在两趟共用
  `no_shape_note`，并且它成了自测里的一格（引擎那一句必须原样出现在兜底里、
  拿不到错误句时也不许崩）——"每个红分支都要有变异走到"这一条，第一次是往
  **文案**上用的：`ci/mutations/mut_d12.py` 里新加的 M9（文案不带引擎那一句）
  与 M10（去掉 `None` 保护）各打红一次。
  这一轮还把变异驱动本身搬了家：正文引用的 `.scratch/mut_d7.py`、`mut_d8.py`
  一直在 `.gitignore` 的 `.scratch/` 里，也就是说文档里那句"证据在这儿"在克隆
  出来之后是断的（比 untracked 更静默——`git ls-files .scratch` 是 0 个文件）。
  五个驱动（`mut_d7` / `mut_d8` / `mut_explain` / `mut_d11b` / `mut_d12`）现在
  都在 `ci/mutations/` 下（那是搬家当天的名单，2026-09-28 这个目录里有九个驱动，
  下文收尾判定那一段说的是全集），跑法仍然是在仓库根目录 `python ci/mutations/<名字>.py`。
  搬家当天就抓到一次真错：那两个语料级驱动用 `parents[1]` 反推仓库根，从
  `.scratch/` 挪到 `ci/mutations/` 之后深度多了一层，它们把 `.scratch` 找成了
  `ci/.scratch`，崩在 `DUMP.mkdir` 那一行——崩溃发生在任何注入之前，所以库里
  没留下变异，但这种错本来可以悄悄变成"跑过了"。现在按 `moon.mod` 往上找模块根，
  搬多远都不会指错；三个纯 python 驱动（不需要语料、不需要 moon）从新路径复跑
  实测：`mut_d12` 10/10 抓到、`mut_d11b` 5/5 抓到、`mut_explain` 五处全抓到，
  三者还原后自测都回到 `Ran 112 tests` + `OK`（那是当天的格数，2026-09-28 同一条命令是 141）。
  同一批东西的**收尾判定**也搬进了仓库：`ci/mutations/run_all.py` 串行跑完
  `ci/mutations/` 下的每一个驱动（驱动名单是从目录里发现的，不另抄一份），
  逐个打印"测得 / 问题"。它不是图省事的 wrapper——判定这一层本身会错，而且错的方向
  是"把绿读成红"和"把红读成绿"都会：按子串扫 `FAIL` 抓不到绿，2026-09-27 那份判成绿的
  `mut_explain` 日志里就有 5 行 `FAILED`（那是每处注入本该打出来的红，unittest 的
  收尾行照样带着它）；按子串扫"对不上"会误伤，2026-09-27 那份判成绿的 `mut_d13` 日志里
  "对不上"出现 4 次——都在 CAUGHT 行里，那句是驱动把它期望的文案整句打出来的结果。
  所以现在只认每个驱动**顶格**
  那几行自己的收尾语，外加两组必须相等的计数（`期望表态 N 处 / 抓到 M 处`、
  `开跑前锚点清点 A/B`）。判定器自己有一张真值表（`--selftest`：纯函数、
  不起子进程、不需要语料，变异行一律喂 rc=0，否则"红"是退码给的不是被测那道闸给的），
  2026-09-28 实测 `判定器真值表：31 格，错 0 格`（比 2026-09-27 那句"30 格"多的
  一格是 M6 的负例：`期望表态 6 处，抓到 5 处` 必须判红）。它的形状是：每个驱动两格打底（正例判绿、
  注入出来的红句必须翻红），再加几格专钉判定器自己的松紧——把"抓到 M 处"比
  "期望表态 N 处"少一格的输出喂进来必须判红（`mut_d7` 这一轮正是把收尾语从硬写的
  "五处"换成派生数字，没有这条负例，放宽正则就等于放宽判定），退码非 0 而收尾语
  说绿的也必须判红；最后一格钉 CI 名单：
  `SPECS` 里声明的驱动与 `NEEDS_CORPUS` 里表态的驱动做**双向**差集（2026-09-28 9 对 9，
  两个方向都为空才算过），少一边就是"新驱动悄悄不进 CI"。这一格 2026-09-28 加硬过一刀：
  双向差集只证明两份名单对齐，不证明新驱动真被判定器验过，所以正例那半边改成
  只认从盘上真日志抄进来的收尾语——把 `mut_d15` 那一行正例删掉再跑 `--selftest`，
  它现在打的是 `FAIL … 缺正例：mut_d15.py` 并退 1（第一版只数名字集合，删了照过，
  也就是"少一层验证"这件事本身不咬）。真值表那一格进了 CI 的
  命令行作业；另有 `--report <目录>` 只判定盘上已有的日志、不起子进程。
  2026-09-27 上午的全量复跑实测：七个驱动 `7/7 GREEN`（当时 `mut_d7` 五处、
  `mut_d8` 六处、`mut_d10` 9/9、`mut_d11b` 5/5、`mut_d12` 10/10、`mut_d13` 5/5、
  `mut_explain` 五处全抓到），跑完 `git status --porcelain` 为空——注入过的文件
  都按字节回去了。
  **D9-E 加完那一层之后按"旧变异集必须复跑"再跑一遍，第一个红就是 `mut_d7`**：
  它的三个锚点钉在 `moonmeta_container.mbt` 的 strip arm 上，而 IPTC 给那个
  `match` 分支多了一行 `dropped_iptc`，于是三处注入点各命中 0 次。驱动自己没有
  假装跑过（打印"注入点命中 0 次，跳过"），收尾判据因此缺席，`run_all` 把它判成
  RED——这一格值得记的是**方向**：锚点漂了不是失败，漂了之后静默跳过才算。
  修法是更新锚点、按 IPTC 之后的现句重写三处注入，再补两格只有 APP13 才打得到的
  坏（见上面 strip 那一段）。修完单独实跑：`期望表态 7 处，抓到 7 处`，
  七处跑完的复跑 rc=0、分诊 0 个。
  然后在干净工作树上把整批重跑了一遍收口：`8 个驱动里绿 8 个（期望 8）`，
  跑完 `git status --porcelain` 为空。`ci.yml` 里那一步用的命令本机也原样跑过
  （`python ci/mutations/run_all.py --ci`）：`5 个语料无关的驱动里绿 5 个`、rc=0
  ——那几个是 CI 上没有外来语料也能实跑的，也就是说 CI 上这一关不是空过：
  `mut_d9e` 那十六处注入就在里面。
  **D15 是这一层的第二次用处，也是它第一次抓到一个"所有闸都看不见"的错位**：
  `sensitive_tags` 与规范名表把 IPTC-NAA 的编号写成了 `0x8773`，而 `0x8773` 是
  ICC 色彩配置文件（`InterColorProfile`），真 IPTC-NAA 是 `0x83bb`。两头同时错：
  那批外来裸 TIFF 里带 `0x8773` 的有 14 份（按 TIFF 6.0 走一遍 IFD0 普查出来的份数），
  其中 9 份走得进条目层——旧表那一行 `(Ifd0, 0x8773, Carrier)` 就落在这 9 份上，而唯一一份真 IPTC
  （`hopper.Lab.tif` 的 `0x83bb`，type 7、count 15）一条都不报。逐份实跑的是修后的
  口径：`audit --policy strict` 现在在这 9 份上报出的清单
  里没有一条 `0x8773`（命中只剩 `DateTime` / `XMP`），另外 5 份是 Pillow 的 `crash-*`
  回归件，读取侧按设计先停下，实测第一份是 `tag 0xa480 points to offset 4048,
  outside the block`；修后 `hopper.Lab.tif` 报出 3 条（`DateTime` / `XMP` / `IptcNaa`）。
  这错位唯一一次落到字节上是在原位那条腿：同一批 104 份在 2026-09-27 重跑，strict 腿从 19 份产物
  变成 15 份，逐份比输入字节找出差的那四份——`hopper.iccprofile.tif`、
  `hopper.iccprofile_binary.tif`、`pport_g4.tif`、`tiff_tiled_ycbcr_jpeg_1x1_sampling.tif`，
  它们在 `strict` 下唯一的收获就是那份 ICC，修后统统变成"无事可做、原样交回"；
  另有一份（`tiff_strip_ycbcr_jpeg_1x1_sampling.tif`）从"设计内拒绝"挪进"无事可做"，
  因为不再有要动的条目。所以"会改坏颜色"不是文案层的比喻：那四份文件的目录表真的被
  清过一遍。
  这一类错位对当时每一道闸都是隐身的：原位门禁那份"该删哪些"直接取自
  `audit --json`（它自己独立算的是目录图与落笔区间），逐条名字表又只跟库自己比——
  拿被检方自己的清单检被检方，等于没检。所以补的不是又一层文本闸，而是两条
  由规范编号与文件字节说话、方向相反的断言：`moonmeta_tags_test.mbt` 里
  `0x83bb → Carrier` 与 `0x8773 → 不属于任何类别` 一删一留成对，
  `moonmeta_redact_test.mbt` 里"TIFF 里的 IPTC 要摘掉，ICC 要原样留下"端到端比字节。
  新驱动 `ci/mutations/mut_d15.py` 钉这两道闸真的会咬：三格注入（类别表退回
  `0x8773` / 两条都留在表里 / 名字表退回），实测 `期望表态 7 处，抓到 7 处`、
  锚点 `3/3 唯一在位`、还原 sha 对账一致；中间那一格是区分度——两条都留在表里时
  "七个类别"那条断言必须仍然绿，否则三格会红成同一句话。当天干净工作树上的收口：
  `9 个驱动里绿 9 个（期望 9）`、跑完 `git status --porcelain` 为空，
  `run_all.py --ci` 那一路 `6 个语料无关的驱动里绿 6 个`，三个后端各 `163/163`。
  对拍脚本自己也有尺子：`ci/crosscheck_selftest.py` 141 个用例（实测
  `Ran 141 tests`、`OK`、rc=0；两轮前是 45 个，那一轮加的 40 个全部钉当时的
  "数字复核"：条目走查算出的
  类型码／声明字节数／值偏移、值指针的四种真值（越过文件尾 / 在文件内但加上宽度越出、
  两种都放行；两种都落得进、数字根本不在字节里）、子目录指针、IFD 偏移、
  目录表声明长度，以及那张 13 项宽度表本身——规范没给的编号不许有宽度）。
  其中 8 个钉的是缺省档那条纯判据——"时间戳被误删"这一格在正常库里
  永远是空的，语料全绿不说明它在工作，所以四个门槛各往宽里改过一次（去掉
  "原图看得到"那一前置、去掉归因豁免、让归因豁免渗到残留方向、按目录比改成
  拿裸编号跨目录比），每一次都由指名用例接住。另有 8 个钉的是 `strip` 那句话与
  事实的判据（四态真值表）：这批语料里只会出现其中两种说法（两个载体都有、
  只有 XMP），另外几种全绿的跑批查不出来——有一格专门钉那个陷阱：
  "这个文件本来就没有 EXIF，也没有 XMP 包"这句里两个词都在，
  判据退化成子串查找就会把一条谎说成实话。另有 4 个钉的是分母自己喂自己的
  那道拒绝：产物目录嵌在语料目录里时脚本现在直接退出码 2 拒绝开跑——2026-09-27 真
  踩了一次，`-o` 指到语料下面，把 13 份 fixture 扫成了 33 份（这一轮写的
  `.redacted` / `.privacy` / `.default` / `.stripped` 被下一轮当语料读了），嵌套与同级两种
  布局各钉一次，`cli` 作业那种同级布局照常放行（复跑实测 rc=0）。
  上一轮再加 8 个，分两簇：5 个钉"缩略图指针消失只在命令行当场说过才豁免"那个
  判据的四个方向（说过→豁免、没说→那两格都红、别的编号不许被同一句话放行、
  同一个编号挂在 GPS 目录里也不放行——0x0201 在那儿是 `GPSLatitude`，它没了
  绝不是缩略图的事）加"输出为空一律不豁免"那一格；3 个钉 `pillow_dirs` 读不通时
  **返回 None 而不抛**——上一批外来语料里我们的产物不是合法 JPEG，抛出去等于让
  整批跑批在 12/55 处崩掉，一个红都数不到，看着像脚本坏了而不是我们写坏了文件
  （反向对照同时钉住：只写 `return None` 的实现会让每一格都变成"跳过"，全绿）。
  这一轮再加 19 个，17 + 2。那 17 个是容器级的三把尺子，每一把都正反两向钉：
  签名单按容器各自数（JPEG 数 `Exif\0\0` 与 XMP URI 的并集、PNG 数 `eXIf` 块起点、
  裸 TIFF 一律空），"第二份"要么对得上、要么是第一份（要红）、偏移根本不在任何
  签名上（要红）、XMP 包当第二份（要认）；断表那句要么与脚本自己走段表停下的
  位置一致、要么谎报断点（要红），而"段长越出文件尾"不算断在段表中间（那是另一
  种坏法，不许混进这一桶）；块长要么与脚本定的块一致、要么谎报（要红）、装得下
  却说不行（要红）。其中一格是这一轮的题眼：**容器里的块内偏移核的是块长**，
  拿整个文件长凑出来的"剩余字节数"必须红——这一格就是把 8 个待查冤枉掉的那个
  判据本身。另一格钉保守方向：块边界算不出来的时候不许当通过，落回 triage。
  那 2 个钉兜底文案（引擎原句必须在场、错误句缺失不许崩），前面说过为什么只能
  在这里钉：语料没有一格走到它。
  这一轮再加 29 个，钉的是 D9-E 那三条新判据**本身**：`iptc` 键的双向（字节里有
  却说无要红、PNG 与裸 TIFF 上说在有要红、键整个不见了要出声）、`unread` 的每一段
  （名字与段码对不上要红、偏移不是段首要红、一段坏不许掩盖另一段坏、同一份字节
  不许报两遍）、`strip` 那句话的第三个载体（带着包却没点名要红、三样都没有却说
  摘了东西要红、IPTC 那一趟不许去碰共用的分母）。
  这三判据还各自被往里打过一次坏：新驱动 `ci/mutations/mut_d9e.py` 十六处，
  靶子是 `ci/crosscheck_real.py`，跑的是 `crosscheck_selftest`（不起 moon、不碰
  语料，所以它也是 `--ci` 那一步里的五个之一），要求退码非 0 **且** stderr 里出现
  指名那一格的用例名——只看退码的话，"坏法没打到那一格、却把别的用例弄崩了"也算红。
  本轮实测 `期望表态 16 处，抓到 16 处`、开跑前锚点清点 16/16 恰好在位一次、
  每处 `finally` 按字节还原（sha `9adf15e4f410` 与基线一致）。其中 N6、N9 两格
  钉的是"正例也得一起塌"：把 PNG 块类型的偏移从类型域挪到长度域、或者让段码不再
  与名字比对，连"这一句本来就是对的"那格都会红——这才说明正例断言真的站在数值上，
  而不是只查了个非空。
  原位那条路另有一把尺子：`ci/inplace_crosscheck.py` 自带 14 格自测（`--selftest`
  实测 rc=0，输出逐格打印"期望 / 测得"）——2 条来路闸先证明"合法产物本身"与"在合法产物上再动一格受保护区间
  内的字节"这两格测得出来，6 条反向闸各把一种坏法注入一次并要求它红：施工区间外
  改一格、改 TIFF 头、改像素声明覆盖的字节、被删条目的外置值没清零、`next` 指针
  没跟着条目数搬到新表尾、长度变了。再加 6 条分母闸，钉的是"这个脚本有没有资格
  报数"：产物目录嵌在语料目录里、产物目录就是语料目录、语料目录不存在、扫到 0 份
  ——这四种都要求拒绝开跑**并且一个字节都没落笔**，产物目录与语料目录同级、
  扫到 1 份这两种则要求照常放行（只钉拒绝会退化成"什么都拒"，所以放行那一侧
  同样要出声）。夹具是这个脚本自己手写的 185 字节裸 TIFF
  （头 + 64 字节假像素 + 带外置值的 IFD0 + 一条内联条目的 IFD1），其中"链在不在"
  由一条前提闸打印出来：夹具一旦不含缩略图链，那条链闸就当场宣布"全是空跑"。
  那 14 格打的是门禁脚本自己，而它的夹具由它自己手写——只验字符串不验真产物。
  2026-09-28 给它补了最后一层：**14 这个数字本身由代码数出来**，收尾那句从
  `inplace_crosscheck 自测：通过` 换成 `inplace_crosscheck 自测真值表：N 格，错 M 格`
  （N 是当场跑过的格数，M 是按格计的坏数），并把地板 14 写死——名单被删短一格时
  剩下十三格照样全绿，那句"通过"就成了半句空话。这一格由 `ci/mutations/mut_d11b.py`
  的 **M6** 钉：注入"把 `改 TIFF 头` 那一格从名单里删掉"，实测自测打出
  `自测名单只剩 13 格，地板是 14 格` 并退 1。同一批六处坏法 2026-09-28 复跑实测
  `期望表态 6 处，抓到 6 处`，还原后 sha 与基线一致。这里记两笔而不是把旧数圆说：
  加完计数闸那一版是 `c7ab086f9eea`，同一天给它补完分组注释后本回合复跑那一版是
  `c4bc70f9cad1`——被引用文件的指纹要连它后来的改动一起算，否则下一个复跑的人会对不上。
  引擎那一侧另有驱动：`python -u ci/mutations/mut_d10.py --moon <moon 路径>`
  六格，N1（引擎忘了把 `next` 搬到新表尾）要求 `moon test` 与那一个带链的真文件
  **两路**都红，N2（搬完又从新表尾开始清零）红在库测试，N3–N5 分别打门禁的独立
  实现、链那一闸、自测夹具。本轮实测 `期望表态 9 处，抓到 9 处`，每处 `finally`
  按字节还原、跑完 sha 复算一致（`inplace_crosscheck.py=13d0f7e76d27`、
  `moonmeta_tiff_patch.mbt=618020547249`；这两个值是这一回合从盘上重新量的——
  上一版这里写的是 `c313e1b6706e`，那是 IPTC 那一笔改动之前的文件，
  引用文件指纹就得连自己后来的改动一起算）。N6 那一路缺 moon 或缺外来裸 TIFF 语料时
  是停下出声，不是跳过：只有门禁自测那三格能红的话，剩下的"红"全指向我手打的字节。
  `cli` 作业那一整条链子这一轮不再是"我按顺序手跑了一遍"，而是有一个机械复放器：
  `python ci/replay_cli.py --moon D:/moonbit/bin/moon.exe` 直接从
  `.github/workflows/ci.yml` 解析出 `cli` 作业的 run 步骤并逐条执行，开跑前先过两道
  对账闸（步骤数按缩进数、命令条数按命令名前缀数，两个口径都要和解析器取出的一致，
  D13 那一轮实测 `清单对账：11 个步骤、28 条命令，两个口径一致`；这之后往 `cli` 作业里
  加了三步——"变异判定器真值表"、"刷新包索引（`moon update`）"、D9-E 补的
  "语料无关的注入驱动实跑（`run_all.py --ci`）"——
  这一轮同一条命令实测 `清单对账：14 个步骤、31 条命令，两个口径一致`），本机环境复放不了的
  3 条（`curl` 装工具链、`echo` 写 GITHUB_PATH、`pip` 装 Pillow）逐条打印
  `[SKIP-ENV]` 而不是悄悄少一条。上一轮（那时 `cli` 作业还是 13 步）整条复放实测
  `复放清单：13 个步骤、27 条命令
  …非 0 的 0 条`（27 + 3 = 那一轮的 30）。其中对拍脚本对着 fixture 目录跑（CLI 那一步留下的产物一并算进去
  共 14 份，输出目录像计划文件那样放在语料目录之外，否则上一轮的产物会被这一轮当
  语料）报 ok 12 / 按设计拒绝 2（两个裸 TIFF），拒绝复核那一行的数字也复核过：
  写下去会丢的字节最少 1148、最多 1152；第二份元数据块 / 断在段表中间 / 块装不下
  这三把新尺子在 fixture 上都是 0 格（它们是给第四批那 55 张用的，这里只证明
  不冤枉好文件），XMP 闸 2 带包 / 7 产物复查 / 2 摘除并披露，缺省档同样是 7 产物
  复查 / 2 摘除并披露，strip 那一趟 7 个产物 / 2 个带包，`xmp` 键复核 12 份，GPS
  指针挂在 Exif 里 15 格。原位两条腿各 2 份（产物复查通过 1、无事可做原样交回 1）、
  分母自证 2 vs 2 通过、triage 0，`--selftest` 那 14 格同样在这一步里跑过（rc=0，
  逐格打印"期望 / 测得"）。复放器自己也被打过红：`ci/mutations/mut_d13.py` 五处
  单点坏法（块缩进阈值 +2、`- name:` 认不出、作业名指错、第二口径不看内联 `run:`、
  缩进前缀少一格）实测 5/5 抓到，驱动要求 stdout 里有指名那一格的句子而不只看退出
  码，跑完按字节还原并核对 sha（本轮 `5b42f2563a3e` 与基线一致，还原后 `--check-only`
  复跑回到 rc=0）。
- **畸形输入的性质测试。** `moonmeta_fuzz_test.mbt` 不用随机数：7 个种子文件的
  每一个前缀、每一个字节的 8 种单字节改写、再加尾部追加，共 12000 份输入，
  每份都过 `sniff` / `decode_any` / `describe_container` / `redact_any` /
  `strip_any` / `tiff_redact_inplace` / `tiff_strip_inplace` 七个入口。三条性质：
  不许 panic；每条错误都说得出地方，报出的偏移必须真的落在块内；`redact` /
  `strip` 声称成功之后，产物必须自己被读得回来、再审一条敏感都不剩、再删一个
  字节都不动。原位那两条入口另加它自己的两句：长度必须一个字节不差（搬了字节
  就不叫原位，哪怕产物本身没问题）、一条都没删就不许动文件；"产物读得回来且
  审不剩敏感"只对 `decode_any` 本来就吃得下的输入断言——原位这条路故意能吃下
  不认识的类型码，拿这句去要求那一类输入是把两种口径混成一种。实测这 12000 份里
  拒绝 45119 次、读通 6084 次、脱敏产出 4889 份、拆解产出 6133 份，定位分类
  37685 / 5882 / 1552，原位两路产出 1233 / 1226——这些数字测试自己打印出来，
  每一格都设了地板（取基线的约三分之二，只朝一个方向咬），扫描被改小就会红，
  不会悄悄变成空话。每条断言都往库里注入过一次坏并确认它红（偏移 +1000、
  GPS 目录不过滤、空收获也重编码、strip 跳过 XMP、`decode_tiff` 里越界读），
  注入的崩溃没被 `try ... catch` 吞掉，所以"不许 panic"这一条是真的在被测。
  一个反面结论也记在那里：`1 / 0` 在这个工具链上不出声也不红，不是合格的崩溃探针。
- 第三份 fixture 是裸 TIFF 对照，用来钉住"这个文件本来就没有 EXIF"和
  "元数据已清除"这两条分支——混为一谈的脱敏工具没有可信的理由。
  注意裸 TIFF 的 IFD0 就是图像本身的结构，"没有 EXIF"指的是没有 34665 指针。
- 这些脚本的调用顺序就是 `.github/workflows/ci.yml` 里 `cli` 作业的顺序，
  本地可以逐条复跑。**工作流本身 2026-09-27 也在 GitHub 上真跑过了**：仓库已经建了公开
  远端 `https://github.com/shencangsheng513/moonmeta`（分支 `master`，触发条件
  同时列了 `main` 与 `master`），push 之后 `gh run list` 实测三次——前两次
  （`36302587947`、`36302738605`）各 18 秒、**五个作业全红在同一句**
  `Failed to resolve registry dependency \`moonbitlang/x\` ... module was not
  found in the registry`，第三次（`36302932437`）五个作业全绿、56 秒。
  根因是三个作业都缺一步 `moon update`，而**这一格在本机永远复现不到**：开发机的
  注册表索引早就落地过，`moon check` 根本不联网。更难看的一点是 `moon new` 生成的
  `copilot-setup-steps.yml` 里本来就有这一步，是手写这个 `ci.yml` 时把它丢了。
  所以这一串"本机逐条复放全 0"的证据链，当时离"CI 真的会绿"还差着一步——而那一步
  只有推出去才知道。
- 测试矩阵是 wasm / JavaScript / wasm-gc，没有 native：`x/fs` 带 C stub，
  `moon test --target native` 要先装一个 C 编译器。三个后端跑的是同一套
  断言，一个后端过、另一个不过，说明代码里混进了只在某个运行时装得起来的
  行为。
- 覆盖率：`moon test --enable-coverage && moon coverage analyze -- -f summary`
  → 1559/1799 行（86.7%，同一条命令实测 `Total tests: 163, passed: 163, failed: 0`）。
  未覆盖的 240 行里有 176 行在 `cmd/main/main.mbt`（260/436），
  没覆盖的几乎全是真正读写文件的几行：`x/fs` 在非 native 后端没有文件系统，
  而包的测试要在三个后端都跑绿，所以判断逻辑（路径拼装、覆盖拒绝、策略解析、
  这一轮新加的原位模式分流与那句边界声明）单独抽成纯函数测了，IO 那几行留给
  CI 的 `cli` 作业。
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
