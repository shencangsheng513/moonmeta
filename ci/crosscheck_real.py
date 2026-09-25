"""真实照片语料对拍：不再只给自己造的 fixture 打分。

仓库里的测试文件全是我用 Pillow 亲手造的，所以"Pillow 同意"有一半是
自己给自己打分。这个脚本换掉语料来源：喂给它的是相机与手机产出的
真实 JPEG / PNG / TIFF（外站语料，本仓库不收录），对拍两件事：

1. **读得到对不对**——我们枚举的条目编号集合，和 Pillow 看到的集合，
   两个方向都比（我们漏了 / 我们凭空报了）。
2. **删得干净不干净**——按策略脱敏之后，用 Pillow 复查：点名的条目读不到了、
   没点名的还在、像素没动、输入文件逐字节没动。
3. **整包 XMP 有没有被绕开**——脱敏产物里不许再搜到 XMP 包标记，也不许搜到
   包里的敏感键；摘除了就必须由 CLI 说出来。这一条是上一轮跑批抓出来的真漏
   （82 个产物里 13 个还带着完整的第二份元数据），所以它长在这里，
   不长在 .scratch 的一次性脚本里。
4. **两档策略都跑**——写侧不只验 strict，也验 CLI 的缺省档 privacy：
   用户不打 `--policy` 时拿到的就是它，而它先前一条真实语料证据都没有。
   privacy 的期望不另抄一份敏感表，从同一个文件的 strict findings 按
   category 推（两档只差 `timestamps`）；外加一条逐字节比对，
   钉住"缺省产物 == 显式 --policy privacy 的产物"。

"点名哪些条目"这件事刻意不在这个脚本里再抄一份策略：它取自 `audit --json`
的输出。策略只有一个来源（库），这个脚本只负责"另一个人怎么看"。

用法（第一个参数是必填的语料目录，脚本绝不硬编码任何个人路径）：

    python ci/crosscheck_real.py 语料目录 [-o 输出目录] [--moon moon可执行文件]

只读语料：写出的脱敏文件全部落在 -o 指定的目录（默认 .scratch/crosscheck/）。
退出码 0 = 没有 need-triage 失败；非 0 = 至少一条。

分桶口径（每个桶都要单独解读，混在一起看会骗人）：
- `ok`：读侧集合一致，且脱敏产物过了下面 2 的全部复查。
- `refused-rewrite`：读侧一致，但裸 TIFF 的重写判据主动拒绝（写侧因此**没有**被验证）。
- `designed-refusal`：读侧就落在库明说的"这一步我不做"名单里。
- `unreadable-by-pillow`：量尺自己打不开，不进任何比率。
- `triage`：以上都不是，需要人看。
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Pillow 的 EXIF 接口用十进制编号指子目录
EXIF_POINTER = 0x8769
GPS_POINTER = 0x8825
INTEROP_POINTER = 0xA005

# 三张表变四张的那一刻，对拍脚本里所有硬编码的目录列表都要跟着改。
POINTERS = (EXIF_POINTER, GPS_POINTER, INTEROP_POINTER)
DIRS = ("IFD0", "Exif", "GPS", "Interop")

# 容器里 XMP 包的字节标记。裸 TIFF 也用它：0x02bc 那条的载荷就是同一个 URI 开头。
XMP_MARKS = (
    b"http://ns.adobe.com/xap/1.0/",
    b"XML:com.adobe.xmp",
    b"<x:xmpmeta",
)

# XMP 里"能定位到人/时间/地点"的键，且必须是 strict 策略确实覆盖的那几类。
# 机型、厂商名（tiff:Make / tiff:Model）刻意不在这里——库里默认不把它们算敏感，
# 放进名单就等于让闸去报一个合法保留的键，红就成了噪声。
XMP_SENSITIVE = (
    b"exif:GPSLatitude",
    b"exif:GPSLongitude",
    b"exif:GPSAltitude",
    b"exif:GPSImgDirection",
    b"exif:GPSSpeed",
    b"exif:DateTimeOriginal",
    b"exif:DateTimeDigitized",
    b"tiff:DateTime",
    b"aux:OwnerName",
    b"aux:SerialNumber",
    b"xmpMM:DocumentID",
    b"xmpMM:InstanceID",
    b"dc:creator",
    b"Iptc4xmpCore:Creator",
    b"Iptc4xmpCore:Location",
    b"MP:RegionInfo",  # 微软 XMP 里的人脸区域
)

# 这些错误名字是库明说的"这一步我不做"，属于设计内拒绝，不算对拍失败
DESIGNED_REFUSALS = (
    "UnsupportedType",  # 还解不了 FLOAT / DOUBLE / IFD 这三种类型码
    "ExtraMetadata",  # 压缩流之后还有元数据、或重复 APP1
    "UnknownFormat",  # 容器认不出来
    "NotJpeg",
    "NotPng",
    "BadTiffHeader",
    "BadByteOrder",
    "TooShort",
)


def run_moon(moon, args, cwd):
    """跑一次 CLI，拿它 stdout 的原始字节。

    构建进度走 stderr，这里只认 stdout；--json 的输出是纯 ASCII，
    所以 utf-8 解码不可能碰到控制台编码问题。
    """
    proc = subprocess.run(
        [moon, "run", "cmd/main", "--", *args],
        cwd=str(cwd),
        capture_output=True,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def read_json(moon, repo, path):
    code, out = run_moon(moon, ["read", str(path), "--json"], repo)
    line = out.strip().splitlines()[-1] if out.strip() else ""
    if code != 0:
        return None, line
    try:
        return json.loads(line), None
    except json.JSONDecodeError as e:
        return None, "JSON 解析失败: {} / 原文 {!r}".format(e, line[:200])


def pillow_dirs(path):
    """Pillow 看到的四张目录：{目录名: set(编号)}。读不出来返回 None。

    Pillow 12 会把它认识的条目用枚举成员（如 `Base.Orientation`）当键返回，
    那种键和整数 274 在集合运算里不相等——不归一化就会报出一片"我们漏了"，
    其实是量尺花了。
    """
    with Image.open(path) as im:
        ex = im.getexif()
        out = {name: set() for name in DIRS}
        out["IFD0"] = {int(k) for k in ex.keys()} - set(POINTERS)
        for name, pointer in (
            ("Exif", EXIF_POINTER),
            ("GPS", GPS_POINTER),
            ("Interop", INTEROP_POINTER),
        ):
            try:
                sub = ex.get_ifd(pointer)
                out[name] = {int(k) for k in sub.keys()} - set(POINTERS)
            except Exception:
                out[name] = set()
        return out


def ours_dirs(doc):
    out = {}
    for d in doc["directories"]:
        out[d["dir"]] = {e["tag"] for e in d["entries"]}
    return out


def pixel_hash(path):
    with Image.open(path) as im:
        return hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def xmp_residue(
    dst,
    src_blob,
    red_out,
    stats,
    policy="strict",
    redacted_key="redacted",
    dropped_key="xmp_dropped",
):
    """产物字节里的 XMP 残留，加上"摘了有没有说"。空列表 = 这一关过了。

    计数器键按策略分开：`redacted` / `xmp_dropped` 记的是 strict 那一趟，
    privacy 那一趟另用 `redacted_privacy` / `xmp_dropped_privacy`。
    共用一个键会把"产物复查 N 个"的分母翻倍，那行数字就没有意义了。
    """
    stats[redacted_key] = stats.get(redacted_key, 0) + 1
    out = []
    blob = dst.read_bytes()
    marks = [m.decode() for m in XMP_MARKS if m in blob]
    keys = [k.decode() for k in XMP_SENSITIVE if k in blob]
    if marks:
        out.append("{} 之后产物里还有 XMP 包: {}".format(policy, marks))
    if keys:
        out.append(
            "{} 之后产物字节里还搜得到 XMP 敏感键: {}".format(policy, keys)
        )
    # 摘了却不说，和没摘一样危险：下一次有人会以为这个文件本来就干净。
    if any(m in src_blob for m in XMP_MARKS) and not marks:
        if "XMP" not in red_out:
            out.append("{}：整包 XMP 已被摘除，但 CLI 没有披露".format(policy))
        else:
            stats[dropped_key] = stats.get(dropped_key, 0) + 1
    return out


# `read --json` 的 `xmp` 键是一个文件"有没有整包元数据"的唯一机读说法。
# 它必须能用这个文件自己的字节复核，两个方向都要红：说有而字节里没有是假警报，
# 字节里有却说没有，就是当初那 13 个产物泄漏的同一件事。
PACKET_MARKS = {
    "jpeg": (b"http://ns.adobe.com/xap/1.0/",),
    "png": (b"XML:com.adobe.xmp",),
}


def xmp_flag_problems(kind, blob, flag):
    """这个文件的 `xmp` 键与原始字节的不一致清单（空 = 一致）。"""
    marks = PACKET_MARKS.get(kind)
    if marks is None:
        # 裸 TIFF 的载体是 IFD 里的一条，逐条清单本来就看得见它
        return []
    if flag is None:
        return ["read --json 少了 xmp 键"]
    seen = any(m in blob for m in marks)
    if flag and not seen:
        return ["说在有：xmp=true，原始字节里却搜不到包标记"]
    if seen and not flag:
        return ["说在无：原始字节里搜得到包标记，xmp 却是 false（走查漏了一包）"]
    return []


# Pillow 的 get_ifd(0x8825) 只从 IFD0 取 GPSInfo 指针；而 Pillow 自己的写出器
# 常把这个指针挂在 Exif 子目录里（我们那五份 fixture 就是它写的）。
# 于是"我们多报了一整个 GPS 目录"其实是量尺不肯跳这一跳。
# 判据不许靠猜：拿 Pillow 自己的 IFD 解析器去读那个偏移，
# 它列出的编号必须把我们多报的每一个都包含在内。
GPS_TAG_MAX = 0x1E  # GPS IFD 用过的编号上界（0x0000–0x001E）


def nested_gps_entries(path):
    """Pillow 按 Exif 子目录里的 GPSInfo 指针能读到哪些编号；读不到返回 None。"""
    with Image.open(path) as im:
        ex = im.getexif()
        try:
            offset = ex.get_ifd(EXIF_POINTER).get(GPS_POINTER)
        except Exception:
            return None
        if offset is None:
            return None
        try:
            ifd = ex._get_ifd_dict(offset, GPS_POINTER)
        except Exception:
            return None
        return None if ifd is None else {int(k) for k in ifd.keys()}


def gps_via_exif_pointer(extra, nested):
    """纯判据：多报的 GPS 条目是否就是 Pillow 在那个偏移上读到的那一套。"""
    if not extra or nested is None:
        return False
    if not all(0 <= t <= GPS_TAG_MAX for t in extra):
        return False
    return extra <= nested


def zero_length_entries(doc, dir_name, tags):
    """多出来的条目是否都是 count=0 的空声明。

    Pillow 遍历 IFD 时对 count 为 0 的条目直接跳过（`TiffImagePlugin.py`
    里的 `if type_num != 0 and values_offset ... and count != 0`），
    所以"我们多报了"其实可以是"它不列空值条目"。
    判据用值本身：我们的解码器把 count=0 的 ASCII 解成空串。
    """
    for group in doc.get("directories", []):
        if group["dir"] != dir_name:
            continue
        seen = {e["tag"]: e["value"] for e in group["entries"]}
        return all(seen.get(t) in ('""', "Raw(0 byte(s))") for t in tags)
    return False


def xmp_injected(src_blob, dir_name, tags, doc):
    """缺的这几条是不是 Pillow 从 XMP 包里读进来、又混进 getexif 的。

    Pillow 12 会把 XMP 里的 tiff:Orientation / flash / ImageNumber 合并进
    `getexif()` 的结果（`Image.py` 里那段 `r'tiff:Orientation(=\"|>)([0-9])'`）。
    那是另一个载体里的值，不是 EXIF 段里的条目——我们只报段里有的。
    判据：包里真的写着这个条目名。
    """
    if dir_name != "IFD0":
        return False
    if not any(m in src_blob for m in XMP_MARKS):
        return False
    names = set()
    for group in doc.get("directories", []):
        if group["dir"] == "IFD0":
            names = {e["name"] for e in group["entries"]}
    for t in tags:
        name = KNOWN_IFD0_NAMES.get(t)
        if name is None or ("tiff:" + name).encode() not in src_blob:
            return False
        if name in names:  # 段里另有一条同名的，就不是注入问题
            return False
    return True


# 只用来把编号换回 XMP 里的属性名；策略一律不从这里读。
KNOWN_IFD0_NAMES = {0x0112: "Orientation"}


def audit_findings(moon, repo, path, policy):
    """跑一次 `audit --json`，只拿 findings 那一项。"""
    code, out = run_moon(
        moon, ["audit", str(path), "--policy", policy, "--json"], repo
    )
    assert code == 0, "audit 在 {} 上失败了: {}".format(path, out)
    return json.loads(out.strip().splitlines()[-1])["findings"]


def privacy_expectations(findings, their, after, explained):
    """默认策略该删什么、该留什么——全部从这个文件的 strict findings 推。

    `privacy` 与 `strict` 唯一的差别是 `timestamps` 那一格，所以这里不需要
    第二份敏感表（抄一份，就会有一份过时不候的期望）。返回 (残留, 误删)：

    - 残留：非时间戳的被点名条目，在 privacy 产物里 Pillow 还读得到。
    - 误删：时间戳条目，Pillow 在**原图**里读得到、在产物里读不到了——
      默认策略删时间戳，就是替用户把照片的拍摄时间弄没了。

    `explained` 是上一段拿字节证据归因过的格子，只用在误删这一方向：
    那种值住在 XMP 包里，两档策略都会连包一起摘，产物里读不到它是预期。
    残留这一方向刻意不减 `explained`、也不加 `t in their` 门槛：
    产物里读得到就是读得到（strict 那条 `still` 同理）。
    """
    residue = []
    ts_lost = []
    for f in findings:
        d, t = f["dir"], f["tag"]
        if f["category"] == "timestamps":
            if (d, t) in explained:
                continue
            if t in their[d] and t not in after.get(d, set()):
                ts_lost.append((d, t, f["name"]))
        elif t in after.get(d, set()):
            residue.append((d, t, f["name"]))
    return residue, ts_lost


def check_one(moon, repo, src, out_dir, stats):
    """一个文件的五条结论。返回 (状态桶, 需要分诊的说明列表)。"""
    notes = []
    src_blob = src.read_bytes()
    if any(m in src_blob for m in XMP_MARKS):
        stats["xmp_src"] = stats.get("xmp_src", 0) + 1
    doc, err = read_json(moon, repo, src)
    if doc is None:
        text = err or ""
        if any(name in text for name in DESIGNED_REFUSALS):
            return "designed-refusal", []
        if "没有 EXIF" in text:
            return "unreadable-by-pillow", []
        return "triage", ["read 失败但不在设计内拒绝名单里: " + text[:160]]

    their = pillow_dirs(src)
    if their is None:  # pragma: no cover - Pillow 打不开的文件在上面就滤掉了
        return "unreadable-by-pillow", []

    bucket = "ok"

    # 0) 机读那一位的 `xmp` 键，先跟这个文件的字节对一遍
    if doc.get("container") in PACKET_MARKS:
        stats["xmp_flag"] = stats.get("xmp_flag", 0) + 1
        flag_problems = xmp_flag_problems(
            doc["container"], src_blob, doc.get("xmp")
        )
        if flag_problems:
            notes.extend(flag_problems)
            bucket = "triage"

    # 1) 有没有 EXIF 这件事，两边得一致
    if bool(their["IFD0"]) != doc["exif"] and not any(their.values()):
        notes.append(
            "EXIF 有无不一致：我们 exif={}，Pillow IFD0 非空={}".format(
                doc["exif"], bool(their["IFD0"])
            )
        )
        bucket = "triage"

    if doc["exif"]:
        # 2) 条目编号集合，双向比
        mine = ours_dirs(doc)
        # 目录少一张，比较就会悄悄变窄：先钉住"两边都比了四张"。
        assert set(mine) == set(DIRS), "CLI 报的目录集合变了: {}".format(
            sorted(mine)
        )
        explained = set()
        for name in DIRS:
            missing = their[name] - mine[name]
            extra = mine[name] - their[name]
            # 先归因再定罪：三种已知的量尺行为都要拿这个文件的字节当证据，
            # 证据不成立就照样红。按下文件名来豁免等于没有闸。
            if missing and xmp_injected(src_blob, name, missing, doc):
                stats["scale-xmp-injected"] = (
                    stats.get("scale-xmp-injected", 0) + len(missing)
                )
                notes.append(
                    "{} 少的 {} 条已归因：Pillow 把 XMP 包里的值注进 getexif，"
                    "EXIF 段里本来就没有".format(name, sorted(missing))
                )
                explained |= {(name, t) for t in missing}
                missing = set()
            if extra and zero_length_entries(doc, name, extra):
                stats["scale-zero-length"] = (
                    stats.get("scale-zero-length", 0) + len(extra)
                )
                notes.append(
                    "{} 多的 {} 条已归因：count=0 的空声明，"
                    "Pillow 不列这种条目".format(name, sorted(extra))
                )
                explained |= {(name, t) for t in extra}
                extra = set()
            if name == "GPS" and extra and gps_via_exif_pointer(
                extra, nested_gps_entries(src)
            ):
                stats["scale-gps-nested"] = (
                    stats.get("scale-gps-nested", 0) + len(extra)
                )
                notes.append(
                    "GPS 多的 {} 条已归因：GPSInfo 指针挂在 Exif 子目录里，"
                    "Pillow 的 get_ifd 只从 IFD0 找；那一套编号它自己读得出".format(
                        sorted(extra)
                    )
                )
                explained |= {(name, t) for t in extra}
                extra = set()
            if missing or extra:
                bucket = "triage"
                notes.append(
                    "{} 目录不一致：我们缺 {}，我们多 {}".format(
                        name, sorted(missing), sorted(extra)
                    )
                )

        # 3) 脱敏效果：点名清单来自 audit，观察来自 Pillow
        findings = audit_findings(moon, repo, src, "strict")
        named = {(f["dir"], f["tag"]) for f in findings}
        # 按目录分桶比：0x0001 在 GPS 里是纬度引用，在 Interop 里是 InteropIndex。
        # 拿裸编号跨目录比，会把没点名的条目算成残留。
        named_in = {
            name: {tag for (d, tag) in named if d == name} for name in DIRS
        }

        dst = out_dir / (src.stem + ".redacted" + src.suffix)
        before_input = sha256(src)
        try:
            pixels_before = pixel_hash(src)
        except OSError:
            pixels_before = None

        code, red_out = run_moon(
            moon, ["redact", str(src), "--policy", "strict", "-o", str(dst)], repo
        )
        if code != 0:
            # CLI 打出来的是 Show 的措辞，不是变体名，所以只能按那句话匹配。
            # 那句话由 moonmeta_error_wbtest.mbt 钉住：改措辞会先红在测试里。
            if "refusing to rewrite this bare TIFF" in red_out and bucket == "ok":
                # 裸 TIFF 的重写判据主动拒绝：读侧已经比过，写侧按设计不做。
                # 单独一个桶，不许混进 ok——那一格的写侧从没被验过。
                # 拒绝必须干净：不能留下一个"看着像产物"的坏文件。
                bucket = "refused-rewrite"
                if dst.exists():
                    notes.append("拒绝改写却仍然写出了 {}".format(dst.name))
                    bucket = "triage"
                return bucket, notes
            bucket = "triage"
            notes.append("redact 退出码 {}: {}".format(code, red_out.strip()[:160]))
            return bucket, notes

        if sha256(src) != before_input:
            bucket = "triage"
            notes.append("redact 改动了输入文件本身")

        after_doc, after_err = read_json(moon, repo, dst)
        if after_doc is None:
            bucket = "triage"
            notes.append("脱敏结果我们自己读不回来: " + (after_err or "")[:160])
        else:
            residue = audit_findings(moon, repo, dst, "strict")
            if residue:
                bucket = "triage"
                notes.append(
                    "脱敏之后还剩 {} 条敏感条目：{}".format(
                        len(residue), [r["name"] for r in residue][:8]
                    )
                )

        after = pillow_dirs(dst)
        still = sorted(
            (name, t) for name in DIRS for t in after[name] if t in named_in[name]
        )
        if still:
            bucket = "triage"
            notes.append("Pillow 仍读得到被点名的条目: {}".format(still))

        # 4) XMP 残留。这一关是语料逼出来的：逐条清单全绿的同时，
        #    产物里可以整整齐齐躺着第二份元数据——XMP 包不按条目编号露自己，
        #    所以这里不看编号，直接查产物字节。
        for note in xmp_residue(dst, src_blob, red_out, stats):
            notes.append(note)
            bucket = "triage"

        kept_before = {
            (name, t)
            for name in DIRS
            for t in their[name]
            if t not in named_in[name]
        }
        kept_after = {(name, t) for name in DIRS for t in after[name]}
        # 已经拿字节证据归因过的格子先扣掉：那种值本来住在 XMP 包里，
        # strict 摘完整包之后 Pillow 读不到它是预期结果，不是二次损失。
        lost = sorted(kept_before - kept_after - explained)
        if lost:
            bucket = "triage"
            notes.append("未点名的条目反而没了: {}".format(lost))

        if pixels_before is not None:
            try:
                if pixel_hash(dst) != pixels_before:
                    bucket = "triage"
                    notes.append("像素动了")
            except OSError as e:
                notes.append("像素无法比对（脱敏结果解不开）: {}".format(e))
                bucket = "triage"

        # 5) 默认策略那一档。上面四步全跑在 strict 上，而用户不打 `--policy`
        #    时拿到的是 privacy——它在此之前没有一条真实语料证据。两档只差
        #    `timestamps` 一格，所以期望不必另抄一份敏感表：从同一个文件的
        #    strict findings 按 category 分一下就是它的验收单。
        p_dst = out_dir / (src.stem + ".privacy" + src.suffix)
        d_dst = out_dir / (src.stem + ".default" + src.suffix)
        p_code, p_out = run_moon(
            moon,
            ["redact", str(src), "--policy", "privacy", "-o", str(p_dst)],
            repo,
        )
        if p_code != 0:
            # strict 刚在同一个文件上写过产物：写不出 privacy 只可能是
            # privacy 自己那档的问题。
            bucket = "triage"
            notes.append(
                "privacy 在 strict 能改写的文件上退出码 {}: {}".format(
                    p_code, p_out.strip()[:160]
                )
            )
        else:
            stats["privacy"] = stats.get("privacy", 0) + 1
            before_input_p = sha256(src)

            # "缺省就是 privacy"这句主张得用字节说：产物必须逐字节相同。
            d_code, d_out = run_moon(
                moon, ["redact", str(src), "-o", str(d_dst)], repo
            )
            if d_code != 0:
                bucket = "triage"
                notes.append(
                    "不带 --policy 的 redact 退出码 {}: {}".format(
                        d_code, d_out.strip()[:160]
                    )
                )
            elif sha256(d_dst) != sha256(p_dst):
                bucket = "triage"
                notes.append("缺省策略的产物与 --policy privacy 逐字节不一致")

            # 同策略闭合：拿 privacy 再审自己的产物，一条都不许剩
            p_left = audit_findings(moon, repo, p_dst, "privacy")
            if p_left:
                bucket = "triage"
                notes.append(
                    "privacy 之后还剩 {} 条敏感条目：{}".format(
                        len(p_left), [r["name"] for r in p_left][:8]
                    )
                )

            p_residue, ts_lost = privacy_expectations(
                findings, their, pillow_dirs(p_dst), explained
            )
            if p_residue:
                bucket = "triage"
                notes.append(
                    "privacy 没删掉被点名的条目：{}".format(p_residue)
                )
            if ts_lost:
                bucket = "triage"
                notes.append(
                    "privacy 把该保留的时间戳删了：{}".format(ts_lost)
                )

            for note in xmp_residue(
                p_dst,
                src_blob,
                p_out,
                stats,
                policy="privacy",
                redacted_key="redacted_privacy",
                dropped_key="xmp_dropped_privacy",
            ):
                notes.append(note)
                bucket = "triage"

            if sha256(src) != before_input_p:
                bucket = "triage"
                notes.append("privacy 改动了输入文件本身")
            if pixels_before is not None:
                try:
                    if pixel_hash(p_dst) != pixels_before:
                        bucket = "triage"
                        notes.append("privacy 动了像素")
                except OSError as e:
                    bucket = "triage"
                    notes.append("privacy 产物解不开: {}".format(e))
    else:
        # 没有 EXIF 不等于没有元数据：整包 XMP 可以单独存在，
        # 而那种文件的逐条清单天然是空的。不单独跑这一趟，闸就永远绿。
        if any(m in src_blob for m in XMP_MARKS):
            dst = out_dir / (src.stem + ".redacted" + src.suffix)
            before_input = sha256(src)
            try:
                pixels_before = pixel_hash(src)
            except OSError:
                pixels_before = None
            code, red_out = run_moon(
                moon,
                ["redact", str(src), "--policy", "strict", "-o", str(dst)],
                repo,
            )
            if code != 0:
                if "refusing to rewrite this bare TIFF" not in red_out:
                    bucket = "triage"
                    notes.append(
                        "只有 XMP 的文件 redact 退出码 {}: {}".format(
                            code, red_out.strip()[:160]
                        )
                    )
            else:
                for note in xmp_residue(dst, src_blob, red_out, stats):
                    notes.append(note)
                    bucket = "triage"
                if sha256(src) != before_input:
                    bucket = "triage"
                    notes.append("redact 改动了输入文件本身")
                # 这一趟删掉的是整包（实测最大的一个 12 KB 级），
                # "没碰到画面"这句主张在这类文件上最该验。
                if pixels_before is not None:
                    try:
                        if pixel_hash(dst) != pixels_before:
                            bucket = "triage"
                            notes.append("像素动了")
                    except OSError as e:
                        bucket = "triage"
                        notes.append("产物解不开: {}".format(e))

                # 默认策略在这一形状上同样是 carrier: true，而"13 个产物带着
                # 第二份元数据"就出在这一形状上：privacy 必须在这里也摘干净。
                p_dst = out_dir / (src.stem + ".privacy" + src.suffix)
                p_code, p_out = run_moon(
                    moon,
                    ["redact", str(src), "--policy", "privacy", "-o", str(p_dst)],
                    repo,
                )
                if p_code != 0:
                    bucket = "triage"
                    notes.append(
                        "privacy 在只有 XMP 的文件上退出码 {}: {}".format(
                            p_code, p_out.strip()[:160]
                        )
                    )
                else:
                    stats["privacy"] = stats.get("privacy", 0) + 1
                    for note in xmp_residue(
                        p_dst,
                        src_blob,
                        p_out,
                        stats,
                        policy="privacy",
                        redacted_key="redacted_privacy",
                        dropped_key="xmp_dropped_privacy",
                    ):
                        notes.append(note)
                        bucket = "triage"
                    if sha256(src) != before_input:
                        bucket = "triage"
                        notes.append("privacy 改动了输入文件本身")

    return bucket, notes


def main():
    ap = argparse.ArgumentParser(description="真实照片语料对拍")
    ap.add_argument("corpus", help="语料目录（递归扫，只读）")
    ap.add_argument("-o", "--out", default=None, help="脱敏产物目录，默认 .scratch/crosscheck")
    ap.add_argument("--moon", default="moon", help="moon 可执行文件")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个文件，调试用")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print("语料目录不存在：{}".format(corpus))
        return 2
    out_dir = Path(args.out) if args.out else repo / ".scratch" / "crosscheck"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(
        p
        for p in corpus.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    if args.limit:
        files = files[: args.limit]

    # 分母先自证清白：Pillow 自己打不开的那些，不参与任何比率
    usable, unreadable = [], []
    for p in files:
        try:
            with Image.open(p) as im:
                im.verify()
            usable.append(p)
        except Exception:
            unreadable.append(p)

    buckets = {}
    triage = []
    stats = {}
    for p in usable:
        bucket, notes = check_one(args.moon, repo, p, out_dir, stats)
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if bucket == "triage":
            triage.append((p, notes))
        print("{}: {}{}".format(bucket, p.name, "" if not notes else " ← " + notes[0]))
        sys.stdout.flush()

    print()
    print("语料：扫到 {} 个图片文件，Pillow 可打开 {} 个，打不开 {} 个".format(
        len(files), len(usable), len(unreadable)))
    for name in sorted(buckets):
        print("  {:<20} {}".format(name, buckets[name]))
    print(
        "XMP 闸：语料里带包 {} 个，产物复查 {} 个，摘除并披露 {} 个".format(
            stats.get("xmp_src", 0),
            stats.get("redacted", 0),
            stats.get("xmp_dropped", 0),
        )
    )
    print(
        "默认策略（privacy）：产物复查 {} 个，摘除并披露 {} 个"
        "（分母与 strict 分开记，两档各验各的）".format(
            stats.get("redacted_privacy", 0),
            stats.get("xmp_dropped_privacy", 0),
        )
    )
    print(
        "xmp 键复核：jpeg/png 共 {} 个，两个方向都跟各自字节比过".format(
            stats.get("xmp_flag", 0)
        )
    )
    print(
        "量尺归因：XMP 注入 {} 格，count=0 空声明 {} 格，GPS 指针挂在 Exif 里 {} 格"
        "（每一格都是按这个文件的字节判的，数字变了要重看）".format(
            stats.get("scale-xmp-injected", 0),
            stats.get("scale-zero-length", 0),
            stats.get("scale-gps-nested", 0),
        )
    )
    if triage:
        print()
        print("需要分诊的 {} 个：".format(len(triage)))
        for p, notes in triage:
            print("  {}".format(p.name))
            for n in notes:
                print("      {}".format(n))
    return 1 if triage else 0


if __name__ == "__main__":
    sys.exit(main())
