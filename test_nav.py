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


def check(g, pairs, label: str, review: bool = True) -> int:
    bad = ties = diff_cand = 0
    for src, dst in pairs:
        if src == dst:
            continue
        a = Navigator(k=3, review=review).route(g, src, dst)
        b = Bidirectional(k=3, review=review).route(g, src, dst)
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


def check_notes() -> int:
    """解释口径：缺轮次归属时不许说"全程同轮"。手工造三张小图验四种说法。"""
    from graph import Edge, Graph

    def make(turns):
        ids = ["a", "b", "c", "t1", "t2"]
        return Graph(
            {i: i for i in ids},
            [Edge("a", "b", "link", 1, "q", False), Edge("b", "c", "link", 2, "q", False)],
            {i: i for i in ids},
            turns=turns,
        )

    cases = [
        ("a 缺归属", {"b": {"t1"}, "c": {"t1"}, "t1": {"t1"}}, "判不出", "同一个轮次里"),
        ("都在同一轮", {"a": {"t1"}, "b": {"t1"}, "c": {"t1"}, "t1": {"t1"}}, "同一个轮次里", "判不出"),
        ("分属两轮", {"b": {"t1"}, "c": {"t2"}, "t1": {"t1"}, "t2": {"t2"}}, "跨两个轮次", "同一个轮次里"),
        ("全都没有归属", {}, None, "轮次"),
    ]
    bad = 0
    for label, turns, want, forbid in cases:
        note = Navigator(k=1).route(make(turns), "a", "c")[0].note
        ok = (want is None or want in note) and forbid not in note
        if not ok:
            bad += 1
            print(f"  ✗ {label}: {note}")
    print(f"解释口径：{len(cases)} 例，{bad} 处不对")
    return bad


def check_invariants(g, pairs) -> int:
    """解释里的话必须和图上事实一致。这批不变量就是 Day 9 那个 bug 的护栏。"""
    bad = 0
    for src, dst in pairs:
        for rev in (True, False):
            for p in Navigator(k=3, review=rev).route(g, src, dst):
                attributed = [n for n in p.nodes if g.turns.get(n)]
                missing = len(p.nodes) - len(attributed)
                common = set(g.turns[attributed[0]]) if attributed else set()
                for n in attributed[1:]:
                    common &= g.turns[n]

                said = [x for x in ("同一个轮次里", "跨两个轮次", "判不出") if x in p.note]
                problems = []
                if len(said) > 1:
                    problems.append(f"同时说了 {said}")
                if "同一个轮次里" in p.note and (missing or not common):
                    problems.append("宣称同轮但证据不全")
                if "跨两个轮次" in p.note and not (len(attributed) >= 2 and not common):
                    problems.append("宣称跨轮但证据不足")
                if "判不出" in p.note and not (missing and attributed):
                    problems.append("说判不出但不是缺归属")
                if "全靠回顾" in p.note and not all(
                    k == "link" and g.why_of(a, b)[4] for a, b, k in p.edges
                ):
                    problems.append("宣称全靠回顾但有些边不是")
                if "None" in p.note or "；；" in p.note or "。。" in p.note:
                    problems.append("标点/占位符串了")

                cost = sum(EDGE_KINDS[k][0] for _a, _b, k in p.edges)
                if abs(round(cost, 2) - p.cost) > 1e-9:
                    problems.append(f"cost 对不上 {cost} vs {p.cost}")
                conf = min((EDGE_KINDS[k][1] for _a, _b, k in p.edges), default=1.0)
                if abs(round(conf, 2) - p.confidence) > 1e-9:
                    problems.append(f"confidence 对不上 {conf} vs {p.confidence}")

                if problems:
                    bad += 1
                    print(f"  ✗ {src} → {dst} (review={rev}): {'；'.join(problems)}")
                    print(f"    {p.note}")
    print(f"解释不变量：{len(pairs)} 对，{bad} 处不对")
    return bad


def main() -> int:
    bad = check_notes()

    fake = load(HERE / "data" / "fake_graph.json")
    pairs = list(itertools.permutations(list(fake.titles), 2))
    bad += check(fake, pairs, "假图 全对")
    bad += check_invariants(fake, pairs)

    real = HERE / "data" / "mem_graph.json"
    if real.exists():
        g = load(real)
        ids = sorted(g.titles)
        rng = random.Random(20261111)  # 固定种子：跑两次结果一样
        sample = [tuple(rng.sample(ids, 2)) for _ in range(300)]
        bad += check(g, sample, "真实图 随机 300 对")
        # 关掉回顾型引用后再验一遍：过滤只该减少边，不该让两个算法分家
        bad += check(g, sample, "真实图 300 对（排除回顾型）", review=False)
        bad += check_invariants(g, sample)
    else:
        print("真实图不在（data/mem_graph.json），跳过")

    print("正确性通过" if not bad else f"**{bad} 处错误**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
