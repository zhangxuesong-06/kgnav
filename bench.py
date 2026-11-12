"""同一批查询，两个算法各跑一遍。

比三件事：
  1. 结果一不一样（必须一样：双向只是省展开，不是改答案）
  2. 各展开多少节点（换算法唯一可测的差别）
  3. 有多少查询根本此路不通（这才是真瓶颈）

用法：
  python bench.py                       # 用 queries.json 里的默认批次
  python bench.py --queries 我的.json   # 换一批
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from graph import load
from nav import Bidirectional, Navigator

HERE = Path(__file__).parent
NAVS = {"dijkstra": Navigator, "bidirectional": Bidirectional}


def run_one(cls, g, src, dst, k, review):
    nav = cls(k=k, review=review)
    t0 = time.perf_counter()
    paths = nav.route(g, src, dst)
    ms = (time.perf_counter() - t0) * 1000
    return paths, nav.expansions, ms


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=str(HERE / "queries.json"))
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--no-review", action="store_true", help="整类关掉回顾型引用，做对照")
    a = ap.parse_args(argv)

    batches = json.loads(Path(a.queries).read_text(encoding="utf-8"))
    for gname, pairs in batches.items():
        path = HERE / "data" / gname
        if not path.exists():
            print(f"\n== {gname}：没有这张图，跳过（先跑 from_memory.py 生成）")
            continue
        g = load(path)
        print(f"\n== {gname}（{len(g.titles)} 节点 / {len(g.edges)} 边）")
        print(f"{'查询':<26}{'算法':<15}{'路径':>4}{'跳':>4}{'cost':>8}{'conf':>6}{'展开':>7}{'ms':>8}  一致")
        for src_name, dst_name, label in pairs:
            src, hit_s = g.resolve(src_name)
            dst, hit_d = g.resolve(dst_name)
            if not src or not dst:
                miss = src_name if not src else dst_name
                hits = hit_s if not src else hit_d
                print(f"{label[:24]:<26}解析不了「{miss}」（命中 {len(hits)} 个）")
                continue
            results = {}
            for name, cls in NAVS.items():
                paths, exp, ms = run_one(cls, g, src, dst, a.k, not a.no_review)
                results[name] = paths
                hits = len(paths)
                hops = len(paths[0].nodes) - 1 if paths else 0
                cost = paths[0].cost if paths else 0
                conf = paths[0].confidence if paths else 0
                print(
                    f"{label[:24]:<26}{name:<15}{hits:>4}{hops:>4}{cost:>8.2f}{conf:>6.2f}"
                    f"{exp:>7}{ms:>8.2f}"
                )
            same = _same(results["dijkstra"], results["bidirectional"])
            print(f"{'':<26}{'':<15}{'':>4}{'':>4}{'':>8}{'':>6}{'':>7}{'':>8}  {same}")
    return 0


def _same(a, b) -> str:
    """只比最短路代价和候选代价集合。平局时节点序列不同是合法的，不算错。"""
    if not a or not b:
        return "一样（都没路）" if not a and not b else "**一边有路**"
    if abs(a[0].cost - b[0].cost) > 1e-9:
        return f"**代价不同 {a[0].cost} vs {b[0].cost}**"
    if a[0].nodes != b[0].nodes:
        return "同价不同路（平局）"
    if sorted(round(p.cost, 6) for p in a) != sorted(round(p.cost, 6) for p in b):
        return "候选集不同"
    return "一样"


if __name__ == "__main__":
    raise SystemExit(main())
