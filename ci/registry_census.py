# -*- coding: utf-8 -*-
"""逐词数 mooncakes registry：申报书查重表的那 13 个词，两个口径一起打。

为什么要有这个脚本：查重结论是这份申报书最吃重的一格（前两次初审都栽在
"检索结论与实际不符"），而"13 个词各查一遍、数出模块数与自述提及数"这句话
此前只住在我本机的临时探针里——`.scratch/` 在 `.gitignore` 里，评审 clone 不到。
不可复算的计数等于没有计数。

两处口径写死在这里，因为 2026-09-27 那一趟就是栽在口径上：那次记的 `xmp 1 / 0`
与 `metadata 100 / 0` 说的是"子包带标记的个数"，而它数的是**模块层**——同一个
`moonbitlang/pdflite` 命中里，它的 `metadata` 子包自述逐字写着
`a minimal XML tree representation used for XMP metadata`。所以这里两数并打，
并把带标记的模块名点出来，谁对不上都能一眼看见。

服务端口径（2026-09-24 起实测，写在申报书里的那三条）：
- `GET /api/v0/search?kw=<单个词>&limit=100` 返回**模块列表**（不是包列表），
  每个模块带 `matched_packages[]`，里面有子包路径与 `summary`。
- `limit` 上限 100（传 200 回 `422 Invalid limit`），所以 100 是封顶不是总数。
- 多词查询（`kw=foo%20bar`）恒返回 `[]`，只能逐词单查。

跑法（仓库根目录，联网只读，不发任何凭证）：

    python ci/registry_census.py                 # 13 个词，逐个打三个数 + 收尾两行
    python ci/registry_census.py --words exif,xmp,iptc
    python ci/registry_census.py --selftest      # 不打网，只验计数器与形状闸（15 格）

2026-09-29 起收尾多了两行：本申报项目自己已发布在 mooncakes 上，`kw=exif`·`kw=iptc`
这些词从此也会命中它。查重讲的是"别人的重叠面"，所以逐词那一行标出命中里有没有我、
收尾再打"扣掉它之后还剩几个模块、落在几个词上、模块名是谁"。这个扣减由脚本算，
不由申报书作者手算——手算的那一份腐烂得比正文还快。
"""

import argparse
import json
import sys
import time
import urllib.request

WORDS = [
    "exif", "xmp", "tiff", "gps", "privacy", "thumbnail", "jpeg", "png",
    "metadata", "redact", "tag", "iptc", "id3",
]
MARKS = ("exif", "iptc", "xmp", "id3")
BASE = "https://mooncakes.io/api/v0/search?kw={}&limit=100"
# 发布之后（2026-09-29 占上 0.1.0），这 13 个词里大多数都会命中申报人自己的模块。
# 不把它从"别人重叠面"里扣掉，那张表就会把自己算成重复项。
SELF = "shencangsheng513/moonmeta"


def summarize(rows, self_name=SELF):
    """把逐词结果折成"扣掉自己之后还剩多少重叠面"。

    rows 的每一项是 `(词, 模块数, 带标记模块数, 带标记子包数, 命中模块名)`。
    """
    others = [(w, [n for n in names if n != self_name])
              for w, _, _, _, names in rows]
    return {
        "words": len(rows),
        "words_with_self": sum(1 for _, _, _, _, names in rows if self_name in names),
        "other_marked_mods": sum(len(v) for _, v in others),
        "words_with_others": sum(1 for _, v in others if v),
        "other_names": sorted({n for _, v in others for n in v}),
    }


def fetch(word):
    """一个词一次 GET。返回服务端给的原始 JSON。"""
    url = BASE.format(word)
    req = urllib.request.Request(url, headers={"User-Agent": "moonmeta-doc-check"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_census(words, fetch_one=fetch, out=print):
    """逐词普查。返回取不到的词——一个都不能少，否则这句"13 个词都查过"不成立。"""
    missing = []
    rows = []
    for word in words:
        body = None
        for attempt in range(3):
            if attempt and fetch_one is fetch:
                time.sleep(1.5 * attempt)
            try:
                body = fetch_one(word)
                break
            except Exception as exc:  # noqa: BLE001 - 网络这一环坏了要重试，重试完再说出来
                if attempt == 2:
                    out("kw={} 查不了：{}".format(word, exc))
        if body is None:
            missing.append(word)
            continue
        total, mods, subs, names = census(body)
        rows.append((word, total, mods, subs, names))
        out("kw={} 模块={} 自述提及的模块={} 自述提及的子包={}{}".format(
            word, total, mods, subs,
            "（含本申报项目）" if SELF in names else ""))
        for n in names:
            out("    命中：{}".format(n))
    s = summarize(rows)
    out("\n本申报项目出现在 {} 个词的命中里（它 2026-09-29 才发布，不算重叠面）".format(
        s["words_with_self"]))
    out("扣掉它之后：带标记的别人的命中 {} 次（按词累加）＝去重后 {} 个模块，落在 {} 个词上；模块名：{}".format(
        s["other_marked_mods"], len(s["other_names"]), s["words_with_others"],
        "、".join(s["other_names"]) if s["other_names"] else "无"))
    # 分母写在收尾，而且不满就红：一次只取回 6 个词的普查不能读成"13 个词都查过了"。
    out("分母：{} 个词里取回 {} 个".format(len(words), len(words) - len(missing)))
    if missing:
        out("取不到的词：{}".format("、".join(missing)))
    return missing


def census(body):
    """数出三个数：模块数、带标记的模块数、带标记的子包数。

    形状不认识就出声，不许静默返回 0——2026-09-27 那两个错数正是"数错了层"
    还能打出一句看起来完整的话。
    """
    if not isinstance(body, list):
        raise ValueError(
            "服务端回的不是模块列表，而是 {}：口径变了，先重看 API 再信这些数".format(
                type(body).__name__
            )
        )
    marked_mods = 0
    marked_subs = 0
    names = []
    for mod in body:
        if not isinstance(mod, dict) or "name" not in mod:
            raise ValueError("列表里有一项不是带 name 的模块对象：口径变了")
        subs = mod.get("matched_packages") or []
        n = sum(
            1
            for s in subs
            if any(k in (s.get("summary") or "").lower() for k in MARKS)
        )
        if n:
            marked_mods += 1
            marked_subs += n
            names.append(mod["name"])
    return len(body), marked_mods, marked_subs, names


def run_selftest():
    """计数器与形状闸的真值表：不要网，只要这两样东西不撒谎。"""
    problems = []
    cells = [0]

    def expect(what, got, want):
        cells[0] += 1
        if got != want:
            problems.append("{}：得到 {!r}，期望 {!r}".format(what, got, want))
        else:
            print("  OK {}".format(what))

    one_sub = {
        "name": "a/b",
        "matched_packages": [{"package": "meta", "summary": "uses XMP metadata"}],
    }
    two_subs = {
        "name": "c/d",
        "matched_packages": [
            {"package": "p1", "summary": "an XML tree for XMP"},
            {"package": "p2", "summary": "same sub-package, one more mark: exif"},
        ],
    }
    no_mark = {"name": "e/f", "matched_packages": [{"package": "q", "summary": "pdf only"}]}
    no_subs = {"name": "g/h"}

    expect("一个模块一个带标记子包", census([one_sub])[1:], (1, 1, ["a/b"]))
    expect("同一模块两个带标记子包：模块层记 1、子包层记 2（两数分得开，才数得清 09-27 那种错）",
           census([two_subs])[1:], (1, 2, ["c/d"]))
    expect("无标记模块不计入", census([no_mark])[1:], (0, 0, []))
    expect("没有 matched_packages 的模块不崩", census([no_subs])[1:], (0, 0, []))
    expect("空列表（kw=iptc 就是这个）", census([])[1:], (0, 0, []))
    expect("模块数与带标记数同时报", census([one_sub, two_subs, no_mark])[:3], (3, 2, 3))

    for bad, why in (({"unexpected": 1}, "顶层是对象"), (["plain string"], "列表里混进字符串")):
        cells[0] += 1
        try:
            census(bad)
            problems.append("{}：本该出声，却安静返回了".format(why))
        except ValueError:
            print("  OK {} -> 出声".format(why))

    # 分母闸：这三格不打网，走的是同一个 run_census（注入取数函数）。
    quiet = lambda s: None  # noqa: E731
    ok_mod = [{"name": "a/b", "matched_packages": [{"package": "p", "summary": "xmp"}]}]

    def fetcher_fails(calls):
        def one(w):
            calls[w] = calls.get(w, 0) + 1
            if w == "jpeg":
                raise OSError("模拟断连")
            return ok_mod
        return one

    calls = {}
    missing = run_census(["exif", "jpeg"], fetcher_fails(calls), out=quiet)
    cells[0] += 1
    if missing != ["jpeg"]:
        problems.append("分母闸：一个词取不到时应点名它，得到 {!r}".format(missing))
    else:
        print("  OK 分母闸：取不到的词被点名，不被当成 0")
    cells[0] += 1
    if calls.get("jpeg") != 3:
        problems.append("重试：坏词应试满 3 次，实际 {} 次".format(calls.get("jpeg")))
    else:
        print("  OK 重试：坏词试满 3 次才认输")
    cells[0] += 1
    full = run_census(["exif", "xmp"], lambda w: ok_mod, out=quiet)
    if full != []:
        problems.append("分母闸：全取回时不该有缺词，得到 {!r}".format(full))
    else:
        print("  OK 分母闸：全取回时放行")

    # 扣自身这一层：发布之后"13 个词都查过了"这句话里，大多数命中是我自己。
    def picks(rows, self_name=SELF):
        s = summarize(rows, self_name)
        return (s["words_with_self"], s["other_marked_mods"], s["words_with_others"])

    expect("命中里有自己时，重叠面要扣掉它",
           picks([("exif", 3, 3, 4, [SELF, "a/b"])]), (1, 1, 1))
    expect("命中里没有自己时不许凭空扣",
           picks([("exif", 2, 2, 3, ["a/b", "c/d"])]), (0, 2, 1))
    expect("一个别人的命中都没有：三个数归零、模块名空",
           picks([("id3", 0, 0, 0, []), ("iptc", 1, 1, 2, [SELF])]), (1, 0, 0))
    expect("模块名去重后排序（同一邻居命中多个词，只点一次）",
           summarize([("exif", 3, 2, 2, [SELF, "a/b"]),
                      ("gps", 6, 2, 3, [SELF, "a/b"])])["other_names"],
           ["a/b"])

    # 地板 15 = 6 格计数器 + 2 格形状闸 + 3 格分母/重试闸 + 4 格"扣掉自己"。
    # 少了任何一格都只能是名单被删短了，而那种删法会把"自测：通过"变成半句空话。
    if cells[0] != 15:
        problems.append("自测名单只剩 {} 格，地板是 15 格".format(cells[0]))
    print("registry_census 自测真值表：{} 格，错 {} 格".format(cells[0], len(problems)))
    for p in problems:
        print("  问题 {}".format(p))
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--words", help="逗号分隔，覆盖默认那 13 个词")
    ap.add_argument("--selftest", action="store_true", help="不打网，只验计数器")
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest()

    words = [w.strip() for w in args.words.split(",")] if args.words else WORDS
    missing = run_census(words)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
