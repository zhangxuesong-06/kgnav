"""导出器测试：假的记录喂进去，看边抽得对不对。

不碰真实记忆库，不依赖网络。`python test_build.py` 直接跑。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from from_memory import build

DAY = 86400


def episode(n, sid, turn, seq, text):
    return {
        "n": n,
        "kind": "episode",
        "who": "system",
        "sid": sid,
        "turnID": turn,
        "requestSeq": seq,
        "seq": n,
        "text": text,
    }


def message(n, sid, turn, text):
    return {"n": n, "kind": "message", "who": "user", "sid": sid, "turnID": turn, "text": text}


def edges_of(graph, kind):
    return [e for e in graph["links"] if e["kind"] == kind]


def pairs(edges):
    return {(e["from"], e["to"]) if e["from"] < e["to"] else (e["to"], e["from"]) for e in edges}


def q(src, dst, day, found=True, default=True, graph="g.json"):
    return {"graph": graph, "src": src, "dst": dst, "ts": day * DAY, "found": found, "default": default}


def test_session_chain() -> int:
    bad = 0
    # 记录顺序和 requestSeq 故意错开：谁排在前面由 seq 决定，不由行号决定
    recs = [
        episode(1, "s1", "t1", 9, "任务摘录：第三轮"),
        episode(2, "s1", "t2", 3, "任务摘录：第一轮"),
        episode(3, "s1", "t3", 7, "任务摘录：第二轮"),
    ]
    g, _ = build(recs, use_window=False)
    chain = edges_of(g, "session")
    got = pairs(chain)
    want = {("r2", "r3"), ("r1", "r3")}
    if got != want:
        bad += 1
        print(f"  ✗ 会话链应是 {want}，实际 {got}")
    if "r1" in {e.get("n") for e in chain if e.get("quote", "").find("第三轮") >= 0}:
        pass  # quote 里本来就只有 sid 尾号，不做过度断言
    if not all(e.get("quote") for e in chain):
        bad += 1
        print("  ✗ session 边没有证据说明")
    print(f"同会话链：{'通过' if not bad else '失败'}")
    return bad


def test_session_skips_bad_keys() -> int:
    bad = 0
    recs = [
        episode(1, None, "t1", 1, "任务摘录：无 sid"),
        episode(2, "", "t2", 2, "任务摘录：空 sid"),
        episode(3, "s9", "t3", 0, "任务摘录：requestSeq=0"),
        episode(4, "s9", "t4", None, "任务摘录：requestSeq 缺失"),
        episode(5, "s9", "t5", 3, "任务摘录：正常一轮"),
    ]
    g, _ = build(recs, use_window=False)
    if edges_of(g, "session"):
        bad += 1
        print(f"  ✗ 缺 sid / 无效 requestSeq 的记录被连了：{edges_of(g, 'session')}")
    print(f"会话链跳过坏键：{'通过' if not bad else '失败'}")
    return bad


def test_cooccur() -> int:
    bad = 0
    recs = [
        message(1, "s1", "t1", "第一条完全不同的记录，讲甲"),
        message(2, "s2", "t2", "第二条完全不同的记录，讲乙"),
        message(3, "s3", "t3", "第三条完全不同的记录，讲丙"),
    ]
    queries = [
        q("r1", "r2", 100, found=True),           # 第 1 天
        q("r2", "r1", 101, found=False),          # 第 2 天（方向反过来也算同一对）
        q("r2", "r3", 100, found=True), q("r2", "r3", 100, found=True),  # 同一天问两次
        q("r1", "r3", 100, default=False),        # 消融实验：不算
        q("r3", "r1", 100, graph="别的图.json"),   # 别的图：不算
    ]
    g, _ = build(recs, use_window=False, queries=queries, graph_tag="g.json")
    co = edges_of(g, "cooccur")
    got = pairs(co)
    if got != {("r1", "r2"), ("r2", "r3")}:
        bad += 1
        print(f"  ✗ 共现边应是 r1-r2 与 r2-r3，实际 {got}")
    quotes = {(frozenset((e["from"], e["to"]))): e["quote"] for e in co}
    q12 = quotes.get(frozenset(("r1", "r2")), "")
    q23 = quotes.get(frozenset(("r2", "r3")), "")
    if "2 天" not in q12 or "1 次没找到路" not in q12:
        bad += 1
        print(f"  ✗ r1-r2 证据没说清跨几天/几次没路：{q12!r}")
    if "2 次" not in q23:
        bad += 1
        print(f"  ✗ r2-r3 证据没说清次数：{q23!r}")
    print(f"共现边：{'通过' if not bad else '失败'}")
    return bad


def test_cooccur_skips_strongly_linked() -> int:
    bad = 0
    recs = [
        message(1, "s1", "t1", "甲提到了 #2 这条（指向未来的引用，不是回顾型）"),
        message(2, "s2", "t2", "乙"),
    ]
    queries = [q("r1", "r2", 100), q("r1", "r2", 101)]
    g, _ = build(recs, use_window=False, queries=queries, graph_tag="g.json")
    if edges_of(g, "cooccur"):
        bad += 1
        print("  ✗ 已经有非回顾型引用的两个节点又加了共现边，纯噪声")
    print(f"共现跳过已连：{'通过' if not bad else '失败'}")
    return bad


def test_cooccur_allowed_when_link_is_review() -> int:
    bad = 0
    # r2 提到更早的 #1 → 这条 link 是回顾型，--no-review 时会被关掉，共现应该还能兜底
    recs = [
        message(1, "s1", "t1", "甲"),
        message(2, "s2", "t2", "乙后来说起 #1 那条"),
    ]
    queries = [q("r1", "r2", 100), q("r1", "r2", 101)]
    g, _ = build(recs, use_window=False, queries=queries, graph_tag="g.json")
    link = [e for e in edges_of(g, "link") if {e["from"], e["to"]} == {"r1", "r2"}]
    if not link or not link[0].get("review"):
        bad += 1
        print(f"  ✗ 前置条件不对：这条 link 应该是回顾型 {link}")
    if not edges_of(g, "cooccur"):
        bad += 1
        print("  ✗ 回顾型边不该挡住共现兜底")
    print(f"回顾型不挡共现：{'通过' if not bad else '失败'}")
    return bad


def test_tags_end_to_end() -> int:
    """tags.json 的三种键写法都要能用，落到图上就是 tag 边，而且带证据。"""
    from graph import load

    bad = 0
    recs = [
        message(1, "s1", "t1", "甲"),
        message(2, "s2", "t2", "乙"),
        message(3, "s3", "t3", "丙"),
    ]
    tag_map = {"项目X": ["r1", "#2", "#3 丙"]}
    g, stats = build(recs, use_window=False, tag_map=tag_map)
    if stats["tags_applied"] != 3:
        bad += 1
        print(f"  ✗ 三个键应全部命中，实际 {stats['tags_applied']}")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "g.json"
        p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
        gg = load(p)
        te = [e for e in gg.edges if e.kind == "tag"]
        if len(te) != 3:
            bad += 1
            print(f"  ✗ 三个节点同标签应产生 3 条边，实际 {len(te)}")
        elif not all("项目X" in e.quote for e in te):
            bad += 1
            print(f"  ✗ tag 边没有带上标签名作证据：{[e.quote for e in te]}")
    print(f"手工标签：{'通过' if not bad else '失败'}")
    return bad


def test_tags_unknown_and_oversized() -> int:
    bad = 0
    recs = [message(i, f"s{i}", f"t{i}", f"内容{i}") for i in range(1, 15)]
    tag_map = {"X": ["不存在的节点"], "大标签": [f"r{i}" for i in range(1, 14)]}
    _, stats = build(recs, use_window=False, tag_map=tag_map)
    if stats["tags_unknown"] != 1:
        bad += 1
        print(f"  ✗ 点不出来的键应计数为 1，实际 {stats['tags_unknown']}")
    if stats["tags_dropped"] != 1:
        bad += 1
        print(f"  ✗ 13 个节点的标签应被丢弃（防团块），实际丢弃 {stats['tags_dropped']}")
    print(f"标签坏键/过大：{'通过' if not bad else '失败'}")
    return bad


def test_tags_block_cooccur() -> int:
    """已经同标签的一对，不该再多一条共现（同样的信息说两遍）。"""
    bad = 0
    recs = [message(1, "s1", "t1", "甲"), message(2, "s2", "t2", "乙")]
    queries = [q("r1", "r2", 100), q("r1", "r2", 101)]
    g, _ = build(
        recs, use_window=False, queries=queries, graph_tag="g.json", tag_map={"某标签": ["r1", "r2"]}
    )
    if edges_of(g, "cooccur"):
        bad += 1
        print(f"  ✗ 同标签的一对又加了共现：{edges_of(g, 'cooccur')}")
    print(f"标签挡住共现：{'通过' if not bad else '失败'}")
    return bad


def test_method_hub() -> int:
    """方法词表：同一方法（含别名）在不同记录里出现，通过一个"方法"枢纽连起来。"""
    bad = 0
    recs = [
        message(1, "s1", "t1", "用幂等键挡住重复请求"),
        message(2, "s2", "t2", "idempotent 写入，失败了再重试"),
        message(3, "s3", "t3", "今天天气不错"),
    ]
    methods = {"幂等": ["幂等", "idempotent"]}
    g, stats = build(recs, use_window=False, methods=methods)
    hubs = [n for n in g["nodes"] if n["id"].startswith("m") and n.get("kind") == "concept"]
    if len(hubs) != 1 or "幂等" not in hubs[0]["title"]:
        bad += 1
        print(f"  ✗ 应有一个「方法：幂等」枢纽，实际 {hubs}")
    me = [e for e in g["links"] if e["kind"] == "method"]
    if len(me) != 2:
        bad += 1
        print(f"  ✗ 应连 2 条（r1、r2），实际 {len(me)}: {me}")
    if not all("幂等" in e.get("quote", "") for e in me):
        bad += 1
        print(f"  ✗ 证据里没写方法名：{[e.get('quote') for e in me]}")
    if stats["method_hubs"] != 1:
        bad += 1
        print(f"  ✗ 统计不对：{stats['method_hubs']}")
    print(f"方法枢纽：{'通过' if not bad else '失败'}")
    return bad


def test_method_skips_oversized() -> int:
    bad = 0
    recs = [message(i, f"s{i}", f"t{i}", f"都在讲同一个通用词{i}") for i in range(1, 46)]
    g, stats = build(recs, use_window=False, methods={"通用词": ["通用词"]})
    if [n for n in g["nodes"] if n["id"].startswith("m")]:
        bad += 1
        print("  ✗ 39 个节点的方法不该建枢纽（会变成大团块）")
    if stats["method_hubs"] != 0:
        bad += 1
        print("  ✗ 统计不对")
    print(f"方法过大跳过：{'通过' if not bad else '失败'}")
    return bad


def test_log_roundtrip() -> int:
    """CLI 写的日志必须能被导出器原样读回来。"""
    from querylog import log_query, read_queries

    bad = 0
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "queries.jsonl"
        log_query(p, "g.json", "r1", "r2", [], default=False)
        p.write_text(p.read_text(encoding="utf-8") + "{坏行\n", encoding="utf-8")  # 模拟损坏
        rows = read_queries(p)
        if len(rows) != 1 or rows[0]["src"] != "r1" or rows[0]["default"] is not False:
            bad += 1
            print(f"  ✗ 坏行没被跳过或字段丢了：{rows}")
        if read_queries(Path(td) / "不存在.jsonl") != []:
            bad += 1
            print("  ✗ 文件不存在时应返回空列表")
        # 非 UTF-8 也不该炸
        p.write_bytes("不是UTF8".encode("gbk"))
        if read_queries(p) != []:
            bad += 1
            print("  ✗ 坏编码应返回空列表")
        # 类型不对的行不该进
        p.write_text('{"src": [], "dst": "x"}\n', encoding="utf-8")
        if read_queries(p) != []:
            bad += 1
            print("  ✗ 类型不对的行被收进来了")
    print(f"日志读写：{'通过' if not bad else '失败'}")
    return bad


def main() -> int:
    bad = 0
    for fn in (
        test_session_chain,
        test_session_skips_bad_keys,
        test_cooccur,
        test_cooccur_skips_strongly_linked,
        test_cooccur_allowed_when_link_is_review,
        test_tags_end_to_end,
        test_tags_unknown_and_oversized,
        test_tags_block_cooccur,
        test_method_hub,
        test_method_skips_oversized,
        test_log_roundtrip,
    ):
        bad += fn()
    print("全部通过" if not bad else f"**{bad} 处失败**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
