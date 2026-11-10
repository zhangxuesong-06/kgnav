"""图装载与边定义。

原则：手写的数据里只有节点和显式链接，能派生的边（同来源、同标签）一律派生，
不靠人往 JSON 里抄。这样 Day 3 把假图换成真笔记时，只要换数据源，派生逻辑不动。
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# 边类型 -> (cost, confidence)。
# 弱边不靠后天调参压制，靠这两列先天就贵、先天就不信。
EDGE_KINDS: dict[str, tuple[float, float]] = {
    "link": (1.0, 0.90),      # 显式链接：wikilink / 文内引用
    "source": (1.2, 0.85),    # 同来源：同一篇论文拆出的笔记
    "tag": (1.5, 0.70),       # 同标签：手工标签
    "semantic": (3.0, 0.35),  # 语义近邻：最脏，必须能整类关掉
}

CN = {
    "link": "显式链接",
    "source": "同来源",
    "tag": "同标签",
    "semantic": "语义近邻",
}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str
    n: int | None = None  # 证据来自哪条记录
    quote: str = ""  # 那句原话 / 那条归属说明


@dataclass
class Graph:
    titles: dict[str, str]
    edges: list[Edge]
    texts: dict[str, str] = field(default_factory=dict)  # 检索用全文，显示仍用 title
    why: dict[tuple[str, str], tuple[int | None, str, str, tuple[str, str]]] = field(default_factory=dict)

    def title(self, node: str) -> str:
        return self.titles.get(node, node)

    def has(self, node: str) -> bool:
        return node in self.titles

    def why_of(self, a: str, b: str) -> tuple[int | None, str, str, tuple[str, str]]:
        return self.why.get((a, b) if a <= b else (b, a), (None, "", "", ("", "")))


def _derived_edges(nodes: list[dict]) -> list[Edge]:
    """同来源、同标签：凡是共享一个 source / tag 的节点两两连边。"""
    out: list[Edge] = []
    for field, kind in (("source", "source"), ("tags", "tag")):
        buckets: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            vals = n.get(field) or []
            if isinstance(vals, str):
                vals = [vals]
            for v in vals:
                buckets[v].append(n["id"])
        for group in buckets.values():
            for a, b in itertools.combinations(group, 2):
                out.append(Edge(a, b, kind))
    return out


def load(path: str | Path) -> Graph:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    titles = {n["id"]: n["title"] for n in raw["nodes"]}
    texts = {n["id"]: n.get("text") or n["title"] for n in raw["nodes"]}
    edges = [
        Edge(e["from"], e["to"], e["kind"], e.get("n"), e.get("quote") or "")
        for e in raw.get("links", [])
    ]
    edges += _derived_edges(raw["nodes"])

    seen: set[tuple[str, str, str]] = set()
    unique: list[Edge] = []
    for e in edges:
        if e.src == e.dst:
            continue
        key = (e.src, e.dst, e.kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    g = Graph(titles, unique, texts)
    for e in unique:  # 同一对节点只留最有把握那条边的证据，和路线选择的口径一致
        key = (e.src, e.dst) if e.src <= e.dst else (e.dst, e.src)
        old = g.why.get(key)
        if old is None or EDGE_KINDS[e.kind][1] > EDGE_KINDS[old[2]][1]:
            g.why[key] = (e.n, e.quote, e.kind, (e.src, e.dst))
    return g
