"""两个算法必须给出同一条**代价**的最短路，而且返回的路径必须是合法的。

不引 pytest，`python test_nav.py` 直接跑。图不存在就跳过那部分。

注意：同价的路径可能不止一条，两个算法的平局断法不同，节点序列会不一样。
所以这里不要求"节点序列相同"，只要求：
  1. 最短路代价相同（这是正确性）
  2. 每条返回的路径都真的存在于图里，且代价加起来等于报的 cost（这是自洽）
平局和候选集差异单独计数，不当失败——它们是事实，不是错误。
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

from graph import EDGE_KINDS, load
from nav import Bidirectional, Navigator

HERE = Path(__file__).parent


def valid(g, p) -> bool:
    total = 0.0
    for a, b, kind in p.edges:
        if not any({e.src, e.dst} == {a, b} and e.kind == kind for e in g.edges):
            return False
        total += EDGE_KINDS[kind][0]
    return abs(round(total, 2) - p.cost) < 1e-6


def check(g, pairs, label: str) -> int:
    bad = ties = diff_cand = 0
    for src, dst in pairs:
        if src == dst:
            continue
        a = Navigator(k=3).route(g, src, dst)
        b = Bidirectional(k=3).route(g, src, dst)
        if not a and not b:
            continue
        if not a or not b:
            bad += 1
            print(f"  ✗ 一边有路一边没有：{src} → {dst}")
            continue
        if abs(a[0].cost - b[0].cost) > 1e-9:
            bad += 1
            print(f"  ✗ 最短路代价不同 {src} → {dst}: {a[0].cost} vs {b[0].cost}")
            continue
        if a[0].nodes != b[0].nodes:
            ties += 1  # 同价不同路：合法，但值得知道有这么多
        if sorted(round(p.cost, 6) for p in a) != sorted(round(p.cost, 6) for p in b):
            diff_cand += 1
        for p in a + b:
            if not valid(g, p):
                bad += 1
                print(f"  ✗ 路径不自洽 {src} → {dst}: {p.cost} {p.nodes}")
                break
    print(f"{label}：{len(pairs)} 对，错 {bad} 处；同价不同路 {ties} 对；候选集不同 {diff_cand} 对")
    return bad


def main() -> int:
    bad = 0

    fake = load(HERE / "data" / "fake_graph.json")
    bad += check(fake, list(itertools.permutations(list(fake.titles), 2)), "假图 全对")

    real = HERE / "data" / "mem_graph.json"
    if real.exists():
        g = load(real)
        ids = sorted(g.titles)
        rng = random.Random(20261111)  # 固定种子：跑两次结果一样
        bad += check(g, [tuple(rng.sample(ids, 2)) for _ in range(300)], "真实图 随机 300 对")
    else:
        print("真实图不在（data/mem_graph.json），跳过")

    print("正确性通过" if not bad else f"**{bad} 处错误**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
