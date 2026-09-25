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
2. **点名的条目真的没了**——删完再解析一遍，报告里列出的编号必须查不到；
3. **报告说得出删了哪几条**——每条都带目录、tag 编号、规范名、类别。

## 快速开始：命令行

四个子命令，前两个只读：

```console
$ moon run cmd/main -- read    <文件>     # 列出容器结构与每一条元数据
$ moon run cmd/main -- audit   <文件>     # 只报告按策略会删掉哪些，不动文件
$ moon run cmd/main -- redact  <文件>     # 按策略逐条删除，写到新文件
$ moon run cmd/main -- strip   <文件>     # 整段摘掉元数据，写到新文件
```

下面几段真实输出都对着 `ci/make_fixture.py` 造的那份带 GPS 的 JPEG
（Pillow 亲手写进容器，默认落在 `.scratch/fix/`）：

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
这个文件本来就没有 EXIF。
已写出 .scratch/fix/cross.stripped.stripped.jpg
```

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
| `describe_container(data)` | 一行容器概览，给报告用 |

## 策略

`Policy` 是六个布尔开关，类别用枚举而不是 `String`：加了新类别却忘了在
策略里处理，必须是编译错误，不能是"静默不删、数据照原样发出去"。

| 类别 | 覆盖什么 | privacy | strict |
| --- | --- | --- | --- |
| `Location` | GPS 目录里的全部条目（含版本号）+ 坐标本身 | ✔ | ✔ |
| `Identity` | `Artist`、`ImageUniqueID` | ✔ | ✔ |
| `DeviceId` | 机身 / 镜头序列号 | ✔ | ✔ |
| `MakerNote` | 厂商私有块（内容不受规范约束，坐标常藏在里面） | ✔ | ✔ |
| `Comments` | `UserComment` | ✔ | ✔ |
| `Timestamps` | `DateTime` 及各 `OffsetTime*` / `SubsecTime*` / `DateTime*` | ✘ | ✔ |

另有 `empty_policy()`：什么都不删，只用作只读审计的对照。

分类明细住在 `moonmeta_tags.mbt` 的 `sensitive_tags` 表里：14 行
（每个编号都对着 exiftool 的 tag 名表核过）+ "GPS 目录整体算 `Location`"
一条规则。报告上能打名字是因为 57 个编号有规范名（IFD0 11 个、Exif 14 个、
GPS 32 个），这 57 行逐条钉在 `moonmeta_tags_test.mbt` 里；表外的编号
回吐十六进制，不拿别的目录的名字凑。`Copyright` 刻意不在任何类别里——
它是权利声明，抹掉它本身就是一种伤害。

## 不可让步的几条约定

- **错误必须带偏移。** 19 种错误变体每一种都指出坏在第几个字节：只报
  "坏了"是一个无法追问的失败。
- **读不能篡改数据。** 文本按 ISO-8859-1 逐字节可逆映射，不做
  "认不出来就替换成 `?`"。非 ASCII 的 `Make`/`Model` 是常态。
- **`RATIONAL` 的分子存成 `Int64`。** MoonBit 的 `Int` 只有 31 位可用范围，
  无符号 32 位分子用 `Int` 存会读成负数。
- **缩略图单独交代。** IFD1 常自带一份 GPS，"删了主坐标却留着缩略图"
  是最常见的假脱敏，所以 `redact` 一律丢掉 IFD1 并在报告里说明。
- **不认识的条目照样搬得走。** `type_size` 对所有 13 个规范类型码都有定义，
  包括本版本还解不了的 `FLOAT`/`DOUBLE`/`IFD`：先算得出宽度，才判得了越界，
  也才保得了原样。
- **CLI 不做判断。** "删什么"全部来自库；命令行只负责读文件、调库、打印。
  两套口径迟早会在报告里打不同的字。

## 版本边界

说清楚现在不做的事，比让人猜更安全：

- 不解析 EXIF 里的缩略图图像内容（只负责丢掉它）。
- 不解码 TIFF 类型 11/12/13（`FLOAT` / `DOUBLE` / `IFD`），遇到报
  `UnsupportedType`；字节仍会原样搬走。
- 不处理藏在压缩流之后的元数据、也不处理重复 APP1；发现时会报
  `ExtraMetadata` 而不是假装没看见。
- 不支持 HEIF / WebP / RAW；不做 XMP 解析（能认出 APP1 里哪段是 XMP，
  并保证不把它误当 EXIF 删掉）。
- 不改写像素、不做转码。

## 测试与验证

```console
moon test                     # wasm（moon.mod 的 preferred_target）
moon test --target js
moon test --target wasm-gc
```

98 个用例，三个后端全绿。此外：

- **不自己给自己打分。** `ci/make_fixture.py` 用 Pillow 造 JPEG / PNG 测试
  文件，`ci/assert_pillow_reads.py` 先证明 Pillow 读得到这些条目（读不到的
  话，后面那半天的比对一文不值），脱敏之后 `ci/assert_redacted.py` 再用
  Pillow 复查：点名的条目读不到了、未点名的还在、输入文件逐字节没动、
  像素与原图完全一致。
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
  → 995/1167 行。`cmd/main/main.mbt` 那 187 行里没被覆盖的，几乎全是真正
  读写文件的几行：`x/fs` 在非 native 后端没有文件系统，而包的测试要在三个
  后端都跑绿，所以判断逻辑（路径拼装、覆盖拒绝、策略解析）单独抽成纯函数
  测了，IO 那几行留给 CI 的 `cli` 作业。

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
