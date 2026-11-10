"""CLI：输入一对节点，输出可读的路径。

§5 门槛一：从输入走到可读输出不超过 15 行，换算法只改一个字符串。
run() 现在 13 行，别往里加东西。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from graph import CN, EDGE_KINDS, Graph, load
from nav import Navigator, dead_end

HERE = Path(__file__).parent
NAVIGATORS = {"dijkstra": Navigator}  # 加算法时只往这里加一项
NAVIGATOR = "dijkstra"  # ← 换算法只改这一个字符串


def run(g: Graph, src: str, dst: str, kinds: tuple[str, ...], k: int, why: bool = False) -> int:
    nav = NAVIGATORS[NAVIGATOR](kinds=kinds, k=k)
    paths = nav.route(g, src, dst)
    present = {e.kind for e in g.edges if e.kind in kinds}  # 图里真有的边类，不是配置里有几类
    _header(g, src, dst, nav.name, present)
    if not paths:
        print(dead_end(g, src, dst, kinds))
        return 0
    for i, p in enumerate(paths, 1):
        print(f"路径 {i}   cost {p.cost:<6.2f} confidence {p.confidence:<5.2f} {len(p.nodes) - 1} 跳")
        print("  " + _chain(g, p, why))
        print("  " + p.note + "\n")
    if len(paths) < k:
        print(f"只找到 {len(paths)} 条走法（要 {k} 条）。缺边是常态，不为凑数降门槛。")
    return 0


def _chain(g: Graph, p, why: bool = False) -> str:
    parts = [f"《{g.title(p.nodes[0])}》"]
    for a, b, kind in p.edges:
        # (逆)：那句话其实在 B 里，是 B 提到了 A，不是 A 指向 B。
        # 后来的记录提到先前的记录，常只是在讨论，不是真关系——标出来让人自己判。
        back = "(逆)" if kind == "link" and g.why_of(a, b)[3][0] == b else ""
        parts.append(f" ─{CN[kind]}{back}→ 《{g.title(b)}》")
    line = "".join(parts)
    if why:
        line += "\n" + "\n".join("   证据 " + _ev(g, a, b) for a, b, _k in p.edges)
    return line


def _ev(g: Graph, a: str, b: str) -> str:
    n, quote, _kind, (src, _dst) = g.why_of(a, b)
    if not n:
        return "—（这条边没有留下证据）"
    back = " ←反向" if src == b else ""  # 证据是 b 指向 a 的那句话，不是顺着走的方向
    return f"#{n}{back}「{quote}」"


def _header(g: Graph, src: str, dst: str, nav: str, present: set[str]) -> None:
    kinds = "/".join(CN[x] for x in EDGE_KINDS if x in present) or "无"
    print(f"查询：《{g.title(src)}》 → 《{g.title(dst)}》    {nav}    边类型：{kinds}（{len(present)}/{len(EDGE_KINDS)}）")
    print("─" * 72)


def main() -> int:
    ap = argparse.ArgumentParser(description="在个人笔记图上做路径查询")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("-k", type=int, default=3, help="要几条候选路径")
    ap.add_argument("--no-semantic", action="store_true", help="整类关掉语义近邻边，再跑一遍看区别")
    ap.add_argument("--graph", default="fake_graph.json", help="data/ 下的图文件名")
    ap.add_argument("--why", action="store_true", help="每一跳把那句证据也打出来")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    kinds = tuple(k for k in EDGE_KINDS if not (a.no_semantic and k == "semantic"))
    g = load(HERE / "data" / a.graph)
    src, hit_s = _resolve(g, a.src)
    dst, hit_d = _resolve(g, a.dst)
    if not src or not dst:
        _complain(g, a.src if not src else a.dst, hit_s if not src else hit_d)
        return 2
    if src == dst:
        print(f"同一个节点：《{g.title(src)}》，用不着找路。")
        return 0
    return run(g, src, dst, kinds, a.k, a.why)


def _resolve(g: Graph, name: str) -> tuple[str | None, list[str]]:
    """精确 id → 精确标题 → 唯一子串 → 二字组近似。命中多个就列出来，不猜。"""
    if name in g.titles:
        return name, []
    if name in set(g.titles.values()):
        return next(k for k, v in g.titles.items() if v == name), []
    hits = [k for k, v in g.texts.items() if name in v]
    if not hits:
        hits = _fuzzy(g, name)
    return (hits[0], hits) if len(hits) == 1 else (None, hits)


def _fuzzy(g: Graph, name: str, limit: int = 5) -> list[str]:
    q = {name[i : i + 2] for i in range(len(name) - 1)}
    scored = [(len(q & {t[i : i + 2] for i in range(len(t) - 1)}), k) for k, t in g.texts.items()]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(reverse=True)
    return [k for _, k in scored[:limit]]


def _complain(g: Graph, name: str, hits: list[str]) -> None:
    if hits:
        print(f"《{name}》命中了 {len(hits)} 个节点，说清楚点：")
        for nid in hits[:10]:
            print(f"  {nid}  {g.title(nid)}")
    else:
        print(f"图里没有这个节点：{name}（共 {len(g.titles)} 个节点）")


if __name__ == "__main__":
    raise SystemExit(main())
