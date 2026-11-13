"""邻域测试：四组邻居要分对、方向要对、开关要生效、渲染顺序要固定。

`python test_about.py` 直接跑。
"""

from __future__ import annotations

import sys

from graph import Edge, Graph
from nav import GROUPS, neighbors


def make() -> Graph:
    titles = {
        "a": "A 种子",
        "b": "B 被它引用",
        "c": "C 引用了它",
        "d": "D 同标签",
        "h": "方法：X",
        "t": "T 同轮（也有引用）",
        "s": "S 只有同来源",
        "u": "U 只有同会话",
        "v": "V 语义近邻",
        "e": "E 共现过",
        "f": "F 回顾型引用",
    }
    edges = [
        Edge("a", "h", "method", None, "提到「x」（方法：X）", False),
        Edge("a", "d", "tag", None, "同标签：Z", False),
        Edge("a", "b", "link", 1, "A 提到 B", False),
        Edge("c", "a", "link", 2, "C 提到 A", False),
        Edge("f", "a", "link", 3, "F 后来提到 A", True),
        Edge("a", "t", "source", 4, "同一轮：turnID 对得上", False),
        Edge("a", "t", "link", 5, "A 也提到了这一轮", False),
        Edge("a", "s", "source", 6, "同一轮：另一条", False),
        Edge("a", "u", "session", 7, "同一会话的下一轮", False),
        Edge("a", "v", "semantic", None, "embedding 邻居", False),
        Edge("a", "e", "cooccur", None, "你问过 2 次", False),
    ]
    return Graph(titles, edges, dict(titles), turns={"t": {"t"}})


def check() -> int:
    bad = 0
    g = make()
    nb = neighbors(g, "a")
    if set(nb) != set(GROUPS):
        bad += 1
        print(f"  ✗ 分组应是 {GROUPS}，实际 {set(nb)}")

    if {x.node for x in nb["概念"]} != {"h", "d"}:
        bad += 1
        print(f"  ✗ 概念组应为 h/d，实际 {[x.node for x in nb['概念']]}")

    out = {x.node for x in nb["引用"] if x.direction == "out"}
    inn = {x.node for x in nb["引用"] if x.direction == "in"}
    if out != {"b", "t"} or inn != {"c", "f"}:
        bad += 1
        print(f"  ✗ 引用方向不对：out={out} in={inn}")

    # t 同时有 source 和 link：只应出现在引用组，不该在同源组重复
    if {x.node for x in nb["同源"]} != {"s", "u"}:
        bad += 1
        print(f"  ✗ 同源组应为 s/u，实际 {[x.node for x in nb['同源']]}")
    if any(x.direction for x in nb["同源"]):
        bad += 1
        print("  ✗ 非引用组不该带方向")

    if {x.node for x in nb["近邻"]} != {"v"}:
        bad += 1
        print(f"  ✗ 语义边应归到近邻组：{[x.node for x in nb['近邻']]}")
    if {x.node for x in nb["共现"]} != {"e"}:
        bad += 1
        print(f"  ✗ 共现组不对：{[x.node for x in nb['共现']]}")

    # review=False：只去掉回顾型，其他引用还在
    nb2 = neighbors(g, "a", review=False)
    ref2 = {x.node for x in nb2["引用"]}
    if "f" in ref2:
        bad += 1
        print("  ✗ review=False 时回顾型边没被排除")
    if {"b", "c"} - ref2:
        bad += 1
        print(f"  ✗ review=False 误伤了普通引用：{ref2}")
    if [x.node for x in nb2["概念"]] != [x.node for x in nb["概念"]]:
        bad += 1
        print("  ✗ review=False 影响了概念组")

    # 关掉语义类：近邻组应消失
    kinds = tuple(k for k in ("tag", "method", "link", "source", "session", "cooccur"))
    nb3 = neighbors(g, "a", kinds=kinds)
    if nb3["近邻"]:
        bad += 1
        print("  ✗ 关掉 semantic 后近邻组还在")

    # 缺节点：五组都在，但都是空的
    nb4 = neighbors(g, "不存在")
    if any(nb4.values()) or set(nb4) != set(GROUPS):
        bad += 1
        print(f"  ✗ 缺节点应返回空组：{nb4}")

    # 证据与标记：引用 b 应带记录号，f 应标回顾型
    b = next(x for x in nb["引用"] if x.node == "b")
    f = next(x for x in nb["引用"] if x.node == "f")
    if b.n != 1 or not b.evidence:
        bad += 1
        print(f"  ✗ 邻居没带记录号/证据：{b}")
    if not f.review:
        bad += 1
        print(f"  ✗ 回顾型没被标记：{f}")

    print(f"邻域分组：{'通过' if not bad else '失败'}")
    return bad


def check_render() -> int:
    """渲染：顺序固定、每组截断并报剩余数、回顾型有标记。"""
    bad = 0
    from cli import _render_about

    g = make()
    text = "\n".join(_render_about(g, neighbors(g, "a"), limit=10))
    idx = [text.index(name) for name in GROUPS if name in text]
    if idx != sorted(idx):
        bad += 1
        print(f"  ✗ 组顺序不对：{text}")
    if "（回顾型）" not in text:
        bad += 1
        print("  ✗ 回顾型邻居没有标记")

    # 截断：13 个 tag 邻居里 n0 还有 method（去重后 12），显示 5 剩 7
    titles = {"a": "A 种子", **{f"n{i}": f"N{i}" for i in range(12)}}
    edges = [Edge("a", f"n{i}", "tag", None, f"同标签：Z{i % 2}", False) for i in range(12)]
    edges.append(Edge("a", "n0", "method", None, "方法", False))
    g2 = Graph(titles, edges, dict(titles), turns={})
    text2 = "\n".join(_render_about(g2, neighbors(g2, "a"), limit=5))
    if "还有 7 条" not in text2:
        bad += 1
        print(f"  ✗ 截断后没报剩余数：\n{text2}")
    bullets = [l for l in text2.splitlines() if l.strip().startswith("·")]
    if len(bullets) != 5:
        bad += 1
        print(f"  ✗ 应只显示 5 条，实际 {len(bullets)}")
    print(f"邻域渲染：{'通过' if not bad else '失败'}")
    return bad


def main() -> int:
    bad = check() + check_render()
    print("全部通过" if not bad else f"**{bad} 处失败**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
