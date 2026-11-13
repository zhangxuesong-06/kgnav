"""路径查询：Dijkstra 和双向搜索，外加多条候选和模板化解释。

换算法只替换 Navigator 子类：route 的签名和 Path 的形状不变，调用方一行不动。

这里**没有 A\\***，不是漏了。A\\* 需要一个可采纳的启发式，而这个图里唯一候选的
"语义距离"根本不存在（没有 embedding）。拿 h=0 冒充 A*，跑出来和 Dijkstra 一模一样，
那就只是给同一件事起了个新名字。等语义层真的有了再加，且必须能验证它不退化解。
"""

from __future__ import annotations

import heapq
from collections import Counter
from dataclasses import dataclass

from graph import CN, EDGE_KINDS, Graph


@dataclass
class Path:
    nodes: list[str]
    edges: list[tuple[str, str, str]]  # (from, to, relation)
    cost: float
    confidence: float
    note: str


class Navigator:
    name = "dijkstra"

    def __init__(
        self,
        kinds: tuple[str, ...] = tuple(EDGE_KINDS),
        k: int = 3,
        penalty: float = 5.0,
        review: bool = True,
    ) -> None:
        self.kinds = tuple(kinds)
        self.k = k
        self.penalty = penalty  # 已用过的边涨价，逼出第二条、第三条不同的走法
        self.review = review  # False = 整类关掉"回顾型引用"，用来对照污染有多大
        self.expansions = 0  # 弹出并结算过几个节点：换算法的唯一可测差别

    # ---- 主入口 -------------------------------------------------------
    def route(self, g: Graph, src: str, dst: str, k: int | None = None) -> list[Path]:
        k = self.k if k is None else k
        adj = self._adjacency(g)
        penalty: dict[tuple[str, str, str], float] = {}
        out: list[Path] = []
        self.expansions = 0
        for _ in range(k * 4):  # 允许空转几次：罚过价的边会被跳过，得再找
            if len(out) >= k:
                break
            p = self._best(g, adj, src, dst, penalty)
            if p is None:
                break
            for a, b, kind in p.edges:
                key = _key(a, b, kind)
                penalty[key] = penalty.get(key, 1.0) * self.penalty
            if p.nodes in (q.nodes for q in out):  # 同一串节点原样再来一遍，不算新路径
                continue
            out.append(p)
            near_j, near_d = 0, 99
            for j, q in enumerate(out[:-1], 1):
                d = len(set(p.nodes) ^ set(q.nodes))
                if d < near_d:
                    near_j, near_d = j, d
            if near_j and near_d <= 2:  # 只在原路线上多绕一两个点，别当第二种解释摆着
                p.note += f"（与路径 {near_j} 只差 {near_d} 个节点，算同一类解释）"
        return out

    # ---- 内部 ---------------------------------------------------------
    def _adjacency(self, g: Graph) -> dict[str, list[tuple[str, str, float, float]]]:
        adj: dict[str, list[tuple[str, str, float, float]]] = {n: [] for n in g.titles}
        best: dict[tuple[str, str], tuple[float, float, str]] = {}
        for e in g.edges:
            if e.kind not in self.kinds:
                continue
            if not self.review and e.review:
                continue
            cost, conf = EDGE_KINDS[e.kind]
            key = (e.src, e.dst) if e.src <= e.dst else (e.dst, e.src)
            # 同一对节点之间只留最强的那条边：否则"同来源"和"显式链接"会各出一条路，
            # 看着是三条候选，其实是同一件事说了三遍。
            if key not in best or conf > best[key][1]:
                best[key] = (cost, conf, e.kind)
        for (a, b), (cost, conf, kind) in best.items():
            adj[a].append((b, kind, cost, conf))
            adj[b].append((a, kind, cost, conf))  # 关系按无向走，方向照原样记录
        return adj

    def _best(self, g, adj, src, dst, penalty) -> Path | None:
        if src not in adj or dst not in adj:
            return None
        dist = {src: 0.0}
        prev: dict[str, tuple[str, str]] = {}
        heap = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            self.expansions += 1
            if u == dst:
                break
            for v, kind, cost, _conf in adj[u]:
                nd = d + cost * penalty.get(_key(u, v, kind), 1.0)
                if nd < dist.get(v, float("inf")) - 1e-12:
                    dist[v] = nd
                    prev[v] = (u, kind)
                    heapq.heappush(heap, (nd, v))
        if dst not in dist:
            return None

        nodes = [dst]
        kinds_seq: list[str] = []
        cur = dst
        while cur != src:
            p, kind = prev[cur]
            kinds_seq.append(kind)
            nodes.append(p)
            cur = p
        nodes.reverse()
        kinds_seq.reverse()
        return self._finish(g, nodes, kinds_seq)

    def _finish(self, g: Graph, nodes: list[str], kinds_seq: list[str]) -> Path:
        edges = [(nodes[i], nodes[i + 1], kinds_seq[i]) for i in range(len(kinds_seq))]
        # 可信度取最弱一环，而不是各边相乘：跳数已经单独显示，再乘一遍等于罚长度；
        # 而且取 min 时，note 里那句"最弱一环"就是这条路的分数本身，可对账。
        real_cost = sum(EDGE_KINDS[e[2]][0] for e in edges)
        conf = min((EDGE_KINDS[e[2]][1] for e in edges), default=1.0)

        p = Path(nodes, edges, round(real_cost, 2), round(conf, 2), "")
        p.note = _note(g, p)
        return p

    # ---- 解释（模板，禁止模型生成）--------------------------------------
    def note(self, g: Graph, p: Path) -> str:
        return _note(g, p)


class Bidirectional(Navigator):
    """两头一起搜。给出的路径必须和 Dijkstra 一模一样，省的是展开的节点数。"""

    name = "bidirectional"

    def _best(self, g, adj, src, dst, penalty) -> Path | None:
        if src not in adj or dst not in adj:
            return None
        inf = float("inf")
        df, db = {src: 0.0}, {dst: 0.0}
        pf: dict[str, tuple[str, str]] = {}  # 前向：指向 src 一侧
        pb: dict[str, tuple[str, str]] = {}  # 后向：指向 dst 一侧
        hf, hb = [(0.0, src)], [(0.0, dst)]
        done_f, done_b = set(), set()
        best, meet = inf, None

        while hf and hb and hf[0][0] + hb[0][0] < best:
            if hf[0][0] <= hb[0][0]:
                d, u = heapq.heappop(hf)
                if u in done_f:
                    continue
                done_f.add(u)
                self.expansions += 1
                if u in db and d + db[u] < best:
                    best, meet = d + db[u], u
                for v, kind, cost, _c in adj[u]:
                    nd = d + cost * penalty.get(_key(u, v, kind), 1.0)
                    if nd < df.get(v, inf) - 1e-12:
                        df[v] = nd
                        pf[v] = (u, kind)
                        heapq.heappush(hf, (nd, v))
            else:
                d, u = heapq.heappop(hb)
                if u in done_b:
                    continue
                done_b.add(u)
                self.expansions += 1
                if u in df and d + df[u] < best:
                    best, meet = d + df[u], u
                for v, kind, cost, _c in adj[u]:
                    nd = d + cost * penalty.get(_key(u, v, kind), 1.0)
                    if nd < db.get(v, inf) - 1e-12:
                        db[v] = nd
                        pb[v] = (u, kind)
                        heapq.heappush(hb, (nd, v))

        if meet is None:
            return None

        nodes, kinds_seq = [meet], []
        cur = meet
        while cur != src:  # 往 src 走
            p, kind = pf[cur]
            kinds_seq.append(kind)
            nodes.append(p)
            cur = p
        nodes.reverse()
        kinds_seq.reverse()
        cur = meet
        while cur != dst:  # 往 dst 走
            nxt, kind = pb[cur]
            kinds_seq.append(kind)
            nodes.append(nxt)
            cur = nxt
        return self._finish(g, nodes, kinds_seq)


@dataclass(frozen=True)
class Neighbor:
    node: str
    kind: str
    direction: str  # 只有引用边有意义：out = 它引用，in = 引用它
    evidence: str
    confidence: float
    n: int | None = None
    review: bool = False


GROUPS = ("概念", "引用", "同源", "共现", "近邻")
GROUP_OF = {
    "tag": "概念",
    "method": "概念",
    "link": "引用",
    "source": "同源",
    "session": "同源",
    "cooccur": "共现",
    "semantic": "近邻",
}


def neighbors(
    g: Graph,
    node: str,
    kinds: tuple[str, ...] = tuple(EDGE_KINDS),
    review: bool = True,
) -> dict[str, list[Neighbor]]:
    """一个种子的有界邻域，按四组分开。概念排在最前——它是解释力的来源。"""
    out: dict[str, list[Neighbor]] = {name: [] for name in GROUPS}
    seen: set[tuple[str, str, str]] = set()
    for e in g.edges:
        if e.kind not in kinds or (not review and e.review):
            continue
        if e.src == node:
            other, direction = e.dst, "out"
        elif e.dst == node:
            other, direction = e.src, "in"
        else:
            continue
        if other not in g.titles:  # 悬空端点：坏数据不该冒充邻居
            continue
        key = (other, e.kind, direction)
        if key in seen:
            continue
        seen.add(key)
        group = GROUP_OF.get(e.kind)
        if group is None:
            continue
        out[group].append(
            Neighbor(
                other,
                e.kind,
                direction if group == "引用" else "",
                e.quote or "",
                EDGE_KINDS[e.kind][1],
                e.n,
                e.review,
            )
        )
    for name in out:
        # 同一可信度下，有方向的引用优先显示"它引用"；其余按标题稳定排序
        out[name].sort(key=lambda x: (-x.confidence, x.direction != "out", g.title(x.node)))
    # 同一个邻居只出现在最靠前的组里：概念 > 引用 > 同源 > 共现 > 近邻。
    # 否则一个文件会同时以"引用它的"和"同来源"出现两次，纯噪音。
    seen_nodes: set[str] = set()
    for name in GROUPS:
        kept = []
        for x in out[name]:
            if x.node in seen_nodes:
                continue
            seen_nodes.add(x.node)
            kept.append(x)
        out[name] = kept
    return out


def _key(a: str, b: str, kind: str) -> tuple[str, str, str]:
    return (a, b, kind) if a <= b else (b, a, kind)


def cut_kinds(g: Graph, node: str, kinds: tuple[str, ...], review: bool = True) -> list[str]:
    """这个节点上、被当前开关关掉的边类型。说清"没边"和"被开关切了"的区别。"""
    out: list[str] = []
    for e in g.edges:
        if e.src != node and e.dst != node:
            continue
        if e.kind not in kinds or (not review and e.review):
            out.append(CN[e.kind])
    return list(dict.fromkeys(out))


def dead_end(g: Graph, src: str, dst: str, kinds: tuple[str, ...], review: bool = True) -> str:
    """说清为什么此路不通。孤岛、被开关切断、"缺边"是三回事，别混成一句'没找到'。"""
    adj = Navigator(kinds=kinds, review=review)._adjacency(g)

    def why_isolated(node: str) -> str | None:
        if adj.get(node):
            return None
        cut = cut_kinds(g, node, kinds, review)
        if cut:  # 本来有边，只是全被当前开关关掉了
            return f"它只连着被当前开关关掉的边（{'、'.join(cut)}），换个开关再看"
        return "没有任何记录引用它，也不在任何已归档的轮次里"

    a_iso, b_iso = why_isolated(src), why_isolated(dst)
    if a_iso and b_iso:
        return f"此路不通。两端都是孤立点：源{a_iso}；目标{b_iso}。"
    if a_iso:
        return f"此路不通。源节点是孤立点：{a_iso}。"
    if b_iso:
        return f"此路不通。目标节点是孤立点：{b_iso}。"
    reach = _bfs(adj, src)
    if dst in reach:
        return "此路不通。可两端其实是连着的——这是搜索本身的问题，不是数据问题，记一笔。"
    other = _bfs(adj, dst)
    return (
        f"此路不通。两端都有边，但分属两个连通块（{len(reach)} 个节点 / {len(other)} 个节点）。"
        "中间缺的那条边在数据里不存在，不是没找到。"
    )


def _bfs(adj: dict[str, list], start: str) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        for nxt, *_ in adj[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _note(g: Graph, p: Path) -> str:
    if not p.edges:
        return f"《{g.title(p.nodes[0])}》就是它自己。"
    counts = Counter(e[2] for e in p.edges)
    kinds = "、".join(f"{CN[k]}×{c}" for k, c in counts.items())
    weakest = min(p.edges, key=lambda e: EDGE_KINDS[e[2]][1])
    wk, wc = CN[weakest[2]], EDGE_KINDS[weakest[2]][1]
    ev = list(dict.fromkeys(f"#{g.why_of(a, b)[0]}" for a, b, _k in p.edges if g.why_of(a, b)[0]))
    if ev:
        tail = f"；证据 {'、'.join(ev)}。"
    elif any(k == "cooccur" for _a, _b, k in p.edges):
        tail = "；证据是查询记录本身。"
    else:
        tail = "。"
    # 这条路径能不能整条落进同一个轮次里。只能拿有归属的节点判，
    # 而且"同轮"必须所有节点都有归属才敢说——少一个就是判不了，不是同轮。
    attributed = [n for n in p.nodes if g.turns.get(n)]
    common = set(g.turns[attributed[0]]) if attributed else set()
    for n in attributed[1:]:
        common &= g.turns[n]
    missing = len(p.nodes) - len(attributed)
    rev = sum(1 for a, b, k in p.edges if k == "link" and g.why_of(a, b)[4])  # 只有 link 才可能回顾
    span = ""
    if rev == len(p.edges):  # 全靠回顾型：比轮次更值得先说
        span = "；全靠回顾型引用撑着（后来的记录在讨论它们），不是原任务里的关系"
    elif len(attributed) >= 2 and not common:
        span = "；至少跨两个轮次"  # 有两个节点各自归属不同轮次，这是硬证据
    elif attributed and not missing and common:
        span = "；全程落在同一个轮次里——这是复述来源，不是新关系"
    elif attributed:
        span = f"；{missing}/{len(p.nodes)} 个节点没有轮次归属，判不出是不是同一轮"
    return (
        f"《{g.title(p.nodes[0])}》连到《{g.title(p.nodes[-1])}》，{len(p.nodes) - 1} 条边："
        f"{kinds}；最弱一环 {wk}（{wc:.2f}）就是这条路的可信度{span}{tail}"
    )
