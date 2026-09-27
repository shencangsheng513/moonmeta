# -*- coding: utf-8 -*-
"""从一份 Pillow 克隆里按规则挑出第二/三/四批语料，落进一个目录并交出清单。

为什么要有这个脚本：申报书和 README 让评审 `git clone` 一份 Pillow 来复算那三批
语料，可"从几千个文件里怎么挑出这 55 个"此前只住在我本机的 `.scratch/grab_*.py`
里——而 `.scratch` 在 `.gitignore` 里。挑选规则不可复算，语料计数就退化成
"作者说多少是"。这里把规则写成代码，并且把**没挑上的**按原因计数打出来：
"这个目录里没有这种文件"必须是一个数出来的结论，不是静默丢。

三批的规则（口径与被它们替代的那三个抓取脚本一致）。**三批都只看 `Tests/images`
根下那一层**：子目录（`jpeg/`、`tiff_gray_2_4_bpp/`、`misplaced-transcode/` 等）按
Pillow 自己的用途分类，混进来会让"这批有多少张"取决于别人怎么摆目录。

- `tiff`：根下的 `.tif`/`.tiff`，留下开头真是 TIFF 6.0 经典魔数（`II*` 或 `MM*`）的，
  BigTIFF 的 `II+` 不在内。根层今天有 106 个候选，两个被魔数筛掉，剩下 104——
  与跑过对拍的那批一字不差。
- `jpeg`：根下的 `.jpg`/`.jpeg`，留下以 `FFD8` 开头的。今天 55 个，全留。
- `png`：根下的 `.png`，只留下命中 `PNG_MARKS` 那四个字面量之一的。绝大多数 PNG
  四种标记都没有，对这一关没有信息量；今天根下 319 张里留下 5 张。

只看包标记不解析包：这个脚本的职责是"把语料摆到磁盘上"，解析归引擎与对拍脚本。

跑法（仓库根目录）：

    python ci/grab_corpus.py .scratch/pillow-clone --batch tiff --out .scratch/tif-samples
    python ci/grab_corpus.py .scratch/pillow-clone --batch jpeg --out .scratch/jpg-samples
    python ci/grab_corpus.py .scratch/pillow-clone --batch png  --out .scratch/png-samples
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
# PNG 里有元数据的露法有四种：`eXIf` 块名，以及 XMP 包的三种露面方式（`iTXt`/`tEXt`
# 的关键字、包里的 xap URI、包根元素）。
# 只查 URI 会漏——实测漏掉 `xmp_tags_orientation.png`（那份 175414 字节的文件
# 两种 URI 字面量都不在，只有关键字与 `<x:xmpmeta`）。判据宁可宽：宽了顶多多扫
# 几张没有信息的图，窄了会静默少一批语料。
PNG_MARKS = (b"eXIf", b"XML:com.adobe.xmp", b"http://ns.adobe.com/xap/1.0/", b"<x:xmpmeta")

# 每批：允许的扩展名、`root_only`（True = 只看 `Tests/images` 根下那一层）、认容器的魔数。
BATCHES = {
    "tiff": {"exts": (".tif", ".tiff"), "root_only": True, "magic": TIFF_MAGIC},
    "jpeg": {"exts": (".jpg", ".jpeg"), "root_only": True, "magic": (b"\xff\xd8",)},
    "png": {"exts": (".png",), "root_only": True, "magic": (b"\x89PNG\r\n\x1a\n",)},
}


def candidates(images : Path, batch : str):
    """按批次的规则列出候选，返回 (留下基名->路径, 丢弃计数)。

    去重在读字节之前做：子目录里的同基名文件是同一份图片的两个住处，
    数两遍会让分母虚高。
    """
    spec = BATCHES[batch]
    found = []
    for ext in spec["exts"]:
        if spec["root_only"]:
            found += sorted(images.glob("*" + ext))
        else:
            found += sorted(images.rglob("*" + ext))
    seen, kept, skipped = set(), {}, {}
    for p in found:
        base = p.name
        if base in seen:
            skipped["dup-basename"] = skipped.get("dup-basename", 0) + 1
            continue
        seen.add(base)
        blob = p.read_bytes()
        if not any(blob.startswith(m) for m in spec["magic"]):
            skipped["magic-mismatch"] = skipped.get("magic-mismatch", 0) + 1
            continue
        if batch == "png" and not any(m in blob for m in PNG_MARKS):
            skipped["no metadata mark"] = skipped.get("no metadata mark", 0) + 1
            continue
        kept[base] = p
    return kept, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pillow", help="Pillow 克隆目录（含 Tests/images）")
    ap.add_argument("--batch", required=True, choices=sorted(BATCHES))
    ap.add_argument("--out", required=True, help="语料落盘目录（在对拍产物目录之外）")
    ap.add_argument(
        "--expect",
        type=int,
        default=0,
        help="挑中份数的地板；0 = 不检查。上游在动，这份数会变，所以默认只打印不判定",
    )
    args = ap.parse_args(argv)

    images = Path(args.pillow) / "Tests" / "images"
    if not images.is_dir():
        print("没有 {}：先 git clone --depth 1 https://github.com/python-pillow/Pillow.git".format(images))
        return 2
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print("输出目录 {} 已经非空——不往别人正在用的目录里盖文件。".format(out))
        print("这一批的名单在：{}".format(out / "corpus_{}.json".format(args.batch)))
        return 2
    kept, skipped = candidates(images, args.batch)
    out.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for base, src in sorted(kept.items()):
        dst = out / base
        shutil.copyfile(src, dst)
        sizes[base] = dst.stat().st_size
    (out / "corpus_{}.json".format(args.batch)).write_text(
        json.dumps(
            {
                "batch": args.batch,
                "source": str(images),
                "kept": len(sizes),
                "skipped": skipped,
                "bytes_total": sum(sizes.values()),
                "files": sizes,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(
        "{}：扫到 {} 个候选，留下 {} 个，丢弃 {}（按原因）".format(
            args.batch, len(kept) + sum(skipped.values()), len(kept), skipped or "无"
        )
    )
    print("字节合计 {}，名单落在 {}".format(sum(sizes.values()), out / "corpus_{}.json".format(args.batch)))
    if args.expect and len(kept) < args.expect:
        print("低于地板 {}：上游删过文件，还是扫描根写错了？".format(args.expect))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
