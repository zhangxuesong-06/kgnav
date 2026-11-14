"""CLI：输入一对节点，输出可读的路径。

§5 门槛一：从输入走到可读输出不超过 15 行，换算法只改一个字符串。
run() 现在 14 行，别往里加东西。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from graph import CN, EDGE_KINDS, Graph, load
from nav import Bidirectional, GROUPS, Navigator, concept_members, cut_kinds, dead_end, neighbors
from querylog import log_query

HERE = Path(__file__).parent
LOG = HERE / "data" / "queries.jsonl"
NAVIGATORS = {"dijkstra": Navigator, "bidirectional": Bidirectional}  # 加算法时只往这里加一项
NAVIGATOR = "dijkstra"  # ← 换算法只改这一个字符串


def run(
    g: Graph,
    src: str,
    dst: str,
    kinds: tuple[str, ...],
    k: int,
    why: bool = False,
    review: bool = True,
):
    nav = NAVIGATORS[NAVIGATOR](kinds=kinds, k=k, review=review)
    paths = nav.route(g, src, dst)
    present = {e.kind for e in g.edges if e.kind in kinds}  # 图里真有的边类，不是配置里有几类
    _header(g, src, dst, nav.name, present, kinds, review)
    if not paths:
        print(dead_end(g, src, dst, kinds, review))
        return paths
    for i, p in enumerate(paths, 1):
        print(f"路径 {i}   cost {p.cost:<6.2f} confidence {p.confidence:<5.2f} {len(p.nodes) - 1} 跳")
        print("  " + _chain(g, p, why))
        print("  " + p.note + "\n")
    if len(paths) < k:
        print(f"只找到 {len(paths)} 条走法（要 {k} 条）。缺边是常态，不为凑数降门槛。")
    return paths


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
    n, quote, _kind, (src, _dst), _rev = g.why_of(a, b)
    back = " ←反向" if n and src == b else ""  # 证据是 b 指向 a 的那句话，不是顺着走的方向
    if n:
        return f"#{n}{back}「{quote}」"
    if quote:  # 会话链、共现这类没有记录号的边，证据就是那句话本身
        return f"「{quote}」"
    return "—（这条边没有留下证据）"


def _header(
    g: Graph,
    src: str,
    dst: str,
    nav: str,
    present: set[str],
    kinds: tuple[str, ...],
    review: bool = True,
) -> None:
    shown = "/".join(CN[x] for x in EDGE_KINDS if x in present) or "无"
    flag = "" if review else "    已排除回顾型引用"
    print(f"查询：《{g.title(src)}》 → 《{g.title(dst)}》    {nav}    边类型：{shown}（{len(present)}/{len(kinds)}）{flag}")
    print("─" * 72)


def _show_method(g: Graph, name: str, kinds: tuple[str, ...] = tuple(EDGE_KINDS)) -> int:
    """以方法为中心：这个方法在哪些记录里出现过。举一反三的入口。"""
    if "method" not in kinds:
        print("方法边被开关关掉了（--no-method），先打开再看。")
        return 0
    exact = [n for n in g.titles if g.title(n) == f"方法：{name}"]
    cands = exact or [
        n for n in g.titles if g.title(n).startswith("方法：") and name in g.title(n)
    ]
    if not cands:
        print(f"没有这个方法：{name}。先看有哪些：python cli.py --methods")
        return 2
    if len(cands) > 1:
        print(f"《{name}》命中了 {len(cands)} 个方法，说清楚点：")
        for n in cands:
            print(f"  {g.title(n)}")
        return 2
    hub = cands[0]
    members = sorted(
        {
            e.src if e.dst == hub else e.dst
            for e in g.edges
            if hub in (e.src, e.dst) and e.kind == "method"
        }
    )
    print(f"《{g.title(hub)}》—— {len(members)} 条记录用过它")
    print("─" * 72)
    for m in members:
        print(f"  {m:<12}{g.title(m)}")
    return 0


def _list_methods(g: Graph) -> int:
    hubs = [n for n in g.titles if g.title(n).startswith("方法：")]
    if not hubs:
        print("图里还没有方法枢纽。检查 data/methods.json 后重新导出。")
        return 0
    for h in sorted(hubs, key=g.title):
        n = sum(1 for e in g.edges if h in (e.src, e.dst) and e.kind == "method")
        print(f"  {g.title(h)[3:]:<12}{n} 条记录")
    return 0


def _render_about(g: Graph, nb: dict, limit: int = 8, seed: str | None = None) -> list[str]:
    """把邻域渲染成行。概念在最前，每组截断并报剩余数；方法枢纽会展开一行成员。"""
    lines: list[str] = []
    for group in GROUPS:
        items = nb.get(group, [])
        if not items:
            continue
        lines.append(f"{group} · {len(items)}")
        for x in items[:limit]:
            tag = CN[x.kind]
            if group == "引用":
                tag = ("它引用 " if x.direction == "out" else "引用它的 ") + tag
            ev = f"#{x.n}「{x.evidence}」" if x.n and x.evidence else (
                f"#{x.n}" if x.n else (f"「{x.evidence}」" if x.evidence else "")
            )
            mark = "（回顾型）" if x.review else ""
            tail = f"  {ev}" if ev else ""
            lines.append(f"  · 《{g.title(x.node)}》  [{tag}]{mark}{tail}")
            # 方法枢纽再走一跳：把"还谁用过"直接写出来，否则记录种子看不到举一反三
            if group == "概念" and seed and g.title(x.node).startswith("方法："):
                members = sorted(
                    {
                        e.src if e.dst == x.node else e.dst
                        for e in g.edges
                        if x.node in (e.src, e.dst) and e.kind == "method" and seed not in (e.src, e.dst)
                    }
                )
                if members:
                    show = "".join(f"《{g.title(m)[:18]}》" for m in members[:2])
                    lines.append(f"      ↳ 另外 {len(members)} 条也用它：{show}…")
        if len(items) > limit:
            lines.append(f"  …还有 {len(items) - limit} 条")
    return lines


def _show_concept(g: Graph, name: str, kinds: tuple[str, ...] = tuple(EDGE_KINDS)) -> int:
    """以标签为中心：这个标签下有哪些记录。"""
    if "tag" not in kinds:
        print("标签边被开关关掉了（--no-tag），先打开再看。")
        return 0
    members, names = concept_members(g, name)
    if not members:
        print(f"没有唯一匹配的标签：{name}")
        print("可选：" + "、".join(names) if names else "（图里还没有标签边，先在 data/tags.json 里写）")
        return 0
    print(f"《标签：{name}》—— {len(members)} 条记录")
    print("─" * 72)
    for m in members:
        print(f"  {m:<12}{g.title(m)}")
    return 0


def _show_about(g: Graph, name: str, kinds: tuple[str, ...], review: bool, limit: int) -> int:
    if limit < 1:
        print("--about-limit 至少是 1。")
        return 2
    nid, hits = g.resolve(name)
    if not nid:
        _complain(g, name, hits)
        return 2
    nb = neighbors(g, nid, kinds, review)
    flag = "" if review else "    已排除回顾型引用"
    print(f"《{g.title(nid)}》    {nid}    1 跳邻域{flag}")
    print("─" * 72)
    lines = _render_about(g, nb, limit, nid)
    if lines:
        print("\n".join(lines))
        return 0
    cut = cut_kinds(g, nid, kinds, review)
    if cut:
        print(f"它只连着被当前开关关掉的边（{'、'.join(cut)}），换个开关再看。")
    else:
        print("这个节点没有任何边。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="在个人笔记图上做路径查询")
    ap.add_argument("src", nargs="?", help="起点：标题、#记录号、或标题片段")
    ap.add_argument("dst", nargs="?", help="终点")
    ex = ap.add_mutually_exclusive_group()
    ex.add_argument("--method", help="以某个方法为中心：看它落到哪些记录（举一反三）")
    ex.add_argument("--methods", action="store_true", help="列出所有方法枢纽")
    ex.add_argument("--about", help="以某个节点为中心：看它的邻域（新的主入口）")
    ex.add_argument("--concept", help="以某个标签为中心：看这个标签下有哪些记录")
    ap.add_argument("--about-limit", type=int, default=8, help="每组最多显示几条")
    ap.add_argument("-k", type=int, default=3, help="要几条候选路径")
    ap.add_argument("--no-semantic", action="store_true", help="整类关掉语义近邻边，再跑一遍看区别")
    ap.add_argument("--no-link", action="store_true", help="整类关掉显式链接边")
    ap.add_argument("--no-source", action="store_true", help="整类关掉同来源边")
    ap.add_argument("--graph", default="fake_graph.json", help="data/ 下的图文件名")
    ap.add_argument("--why", action="store_true", help="每一跳把那句证据也打出来")
    ap.add_argument("--no-review", action="store_true", help="整类关掉回顾型引用（后来的记录提到先前的），做对照")
    ap.add_argument("--no-session", action="store_true", help="整类关掉同会话链（同一会话里相邻两轮）")
    ap.add_argument("--no-cooccur", action="store_true", help="整类关掉共现边（被同一次查询一起问过）")
    ap.add_argument("--no-tag", action="store_true", help="整类关掉手工标签边")
    ap.add_argument("--no-method", action="store_true", help="整类关掉方法枢纽（同方法边）")
    ap.add_argument("--no-log", action="store_true", help="这次查询不写进 data/queries.jsonl（不产生共现证据）")
    a = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    off = {
        "semantic": a.no_semantic,
        "session": a.no_session,
        "cooccur": a.no_cooccur,
        "tag": a.no_tag,
        "method": a.no_method,
        "link": a.no_link,
        "source": a.no_source,
    }
    kinds = tuple(k for k in EDGE_KINDS if not off.get(k, False))
    g = load(HERE / "data" / a.graph)
    if a.methods:
        return _list_methods(g)
    if a.method:
        return _show_method(g, a.method, kinds)
    if a.about:
        return _show_about(g, a.about, kinds, not a.no_review, a.about_limit)
    if a.concept:
        return _show_concept(g, a.concept, kinds)
    if not a.src or not a.dst:
        if a.src and not a.dst:
            print(f"只给了一个节点：《{a.src}》。用 --about 看它的邻域，或补上终点找路径。")
        print("用法：")
        print("  python cli.py --about <节点>        # 看它周围有什么（主入口）")
        print("  python cli.py <src> <dst>           # 看这两条怎么连上的")
        print("  python cli.py --methods / --method <名字>")
        return 2
    src, hit_s = g.resolve(a.src)
    dst, hit_d = g.resolve(a.dst)
    if not src or not dst:
        _complain(g, a.src if not src else a.dst, hit_s if not src else hit_d)
        return 2
    if src == dst:
        print(f"同一个节点：《{g.title(src)}》，用不着找路。")
        return 0
    default = not any(off.values())
    paths = run(g, src, dst, kinds, a.k, a.why, not a.no_review)
    if not a.no_log and not log_query(LOG, Path(a.graph).name, src, dst, paths, default=default):
        print("（提示：查询日志没写进去，共现边不会增长——看看 data/ 的权限。）", file=sys.stderr)
    return 0


def _complain(g: Graph, name: str, hits: list[str]) -> None:
    if hits:
        print(f"《{name}》命中了 {len(hits)} 个节点，说清楚点：")
        for nid in hits[:10]:
            print(f"  {nid}  {g.title(nid)}")
    else:
        print(f"图里没有这个节点：{name}（共 {len(g.titles)} 个节点）")


if __name__ == "__main__":
    raise SystemExit(main())
