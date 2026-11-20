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


def test_turn_requires_session_and_id() -> int:
    recs = [
        episode(1, "session", None, None, "缺轮次标识的摘录"),
        message(2, "session", None, "未归属的对话"),
        episode(3, None, "turn", None, "缺会话标识的摘录"),
        message(4, None, "turn", "另一条未归属的对话"),
    ]
    graph, stats = build(recs, use_window=False)
    ok = not edges_of(graph, "source") and stats["exact"] == 0
    print(f"缺会话或轮次标识不建立归属：{'通过' if ok else '失败'}")
    return int(not ok)


def test_link_direction_matches_evidence() -> int:
    recs = [
        message(1, "session", "turn", "原话提及 #2"),
        episode(2, "session", "turn", 1, "来源 #1：当时的任务"),
    ]
    graph, _ = build(recs, use_window=False)
    edge = edges_of(graph, "link")[0]
    ok = edge["from"] == f"r{edge['n']}"
    print(f"导出引用方向与证据一致：{'通过' if ok else '失败'}")
    return int(not ok)


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
    originals = {rec["n"]: rec["text"] for rec in recs}
    if not all(e["n"] in originals and originals[e["n"]] in e["quote"] for e in me):
        bad += 1
        print(f"  ✗ 方法边缺少可回查的记录号或原话：{me}")
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


def test_method_alias_word_boundary() -> int:
    """英文别名必须按词匹配：storage 里的 rag 不是"提到 RAG"；中文仍是子串。"""
    bad = 0
    recs = [
        message(1, "s1", "t1", "我们讨论 storage 方案"),
        message(2, "s2", "t2", "这次用 RAG 检索"),
        message(3, "s3", "t3", "再试一次 rag"),
        message(4, "s4", "t4", "idempotent 写入，失败了再重试"),
    ]
    g, stats = build(
        recs, use_window=False, methods={"RAG": ["rag"], "幂等": ["idempotent"]}
    )
    members = {e["from"] for e in g["links"] if e["kind"] == "method"}
    if "r1" in members:
        bad += 1
        print("  ✗ storage 里的 rag 被当成提到 RAG 了")
    if {"r2", "r3", "r4"} - members:
        bad += 1
        print(f"  ✗ 独立单词的别名应该命中：{members}")
    if stats["method_edges"] != 3:
        bad += 1
        print(f"  ✗ 应有 3 条方法边，实际 {stats['method_edges']}")
    # 中文别名不受词边界影响
    g2, _ = build(
        [message(1, "s1", "t1", "这次要手眼标定一下")],
        use_window=False,
        methods={"手眼标定": ["手眼标定"]},
    )
    if not any(e["kind"] == "method" for e in g2["links"]):
        bad += 1
        print("  ✗ 中文子串匹配被误伤")
    print(f"方法别名边界：{'通过' if not bad else '失败'}")
    return bad


def test_ref_boundaries() -> int:
    """#N 只认独立引用：abc#1、#1abc、URL 片段、围栏代码块里的都不算。"""
    bad = 0
    recs = [
        message(1, "s1", "t1", "第一条，什么都不提"),
        message(2, "s2", "t2", "见 #1 这条"),
        message(3, "s3", "t3", "abc#1 不是引用"),
        message(4, "s4", "t4", "#1abc 也不是"),
        message(5, "s5", "t5", "http://x/#1 不是引用"),
        message(6, "s6", "t6", "```\n#1 代码块里\n```\n正文没有引用"),
        message(7, "s7", "t7", "中文紧贴 #1这轮 应该算"),
    ]
    g, stats = build(recs, use_window=False)
    got = {(e["from"], e["to"]) for e in g["links"] if e["kind"] == "link"}
    want = {("r2", "r1"), ("r7", "r1")}
    if got != want:
        bad += 1
        print(f"  ✗ 引用边应是 {want}，实际 {got}")
    if stats.get("refs_in_code") != 1:
        bad += 1
        print(f"  ✗ 应报出代码块里跳过 1 处引用，实际 {stats.get('refs_in_code')}")
    print(f"#号引用边界：{'通过' if not bad else '失败'}")
    return bad


def test_config_error() -> int:
    """标签/方法文件坏了必须报错，不能静默当空——否则"词表写坏"看起来像"没有词表"。"""
    bad = 0
    from from_memory import ConfigError, read_methods, read_tags

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cases = [
            ("坏 JSON", "{ 坏", "JSON"),
            ("顶层不是对象", "[1, 2]", "对象"),
            ("值不是列表", '{"X": "r1"}', "列表"),
        ]
        for label, text, want in cases:
            p = d / "bad.json"
            p.write_text(text, encoding="utf-8")
            for reader in (read_tags, read_methods):
                try:
                    reader(p)
                except ConfigError as e:
                    if want not in str(e):
                        bad += 1
                        print(f"  ✗ {label}：错误信息没说清原因：{e}")
                else:
                    bad += 1
                    print(f"  ✗ {label}：{reader.__name__} 静默通过了")
        if read_tags(d / "不存在.json") != {}:
            bad += 1
            print("  ✗ 文件不存在时应返回空表（可选配置）")
        gbk = d / "gbk.json"
        gbk.write_bytes("不是UTF8".encode("gbk"))
        try:
            read_tags(gbk)
        except ConfigError as e:
            if "UTF-8" not in str(e):
                bad += 1
                print(f"  ✗ 非 UTF-8 文件应提示编码问题：{e}")
        else:
            bad += 1
            print("  ✗ 非 UTF-8 文件静默通过了")
        bom = d / "bom.json"
        bom.write_bytes('{"X": ["r1"]}'.encode("utf-8-sig"))  # 记事本常见的带 BOM 写法
        if read_tags(bom) != {"X": ["r1"]}:
            bad += 1
            print("  ✗ 带 UTF-8 BOM 的合法文件被挡住了")
        ok = d / "ok.json"
        ok.write_text('{"_注释": "x", "X": ["r1", ""]}', encoding="utf-8")
        if read_tags(ok) != {"X": ["r1"]}:
            bad += 1
            print(f"  ✗ 正常文件解析不对：{read_tags(ok)}")
    print(f"配置文件错误：{'通过' if not bad else '失败'}")
    return bad


def test_method_skipped_reported() -> int:
    """被跳过的方法要说清原因，写进 stats 和图的顶层，别只留一个 0。"""
    bad = 0
    recs = [message(i, f"s{i}", f"t{i}", f"都在讲同一个通用词{i}") for i in range(1, 46)]
    g, stats = build(
        recs,
        use_window=False,
        methods={"通用词": ["通用词"], "空方法": [], "没有命中": ["zzz"]},
    )
    skip = stats.get("method_skipped") or {}
    if "通用词" not in skip or "40" not in skip["通用词"]:
        bad += 1
        print(f"  ✗ 超上限的方法应报出命中数和上限：{skip}")
    if "空方法" not in skip:
        bad += 1
        print(f"  ✗ 没有别名的方法应报出原因：{skip}")
    if "没有命中" not in skip:
        bad += 1
        print(f"  ✗ 没有命中记录的方法应报出原因：{skip}")
    if (g.get("methods_skipped") or {}) != skip:
        bad += 1
        print(f"  ✗ 跳过原因没写进图的顶层：{g.get('methods_skipped')}")
    print(f"方法跳过上报：{'通过' if not bad else '失败'}")
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
        malformed = {**q("r1", "r2", 100), "ts": "写坏的时间戳"}
        p.write_text(json.dumps(malformed) + "\n", encoding="utf-8")
        recs = [message(1, "s1", "t1", "甲"), message(2, "s2", "t2", "乙")]
        try:
            graph, _ = build(recs, queries=read_queries(p), graph_tag="g.json")
        except (ValueError, TypeError):
            bad += 1
            print("  ✗ 坏时间戳让导出失败")
        else:
            if edges_of(graph, "cooccur"):
                bad += 1
                print("  ✗ 坏时间戳被计入共现")
    print(f"日志读写：{'通过' if not bad else '失败'}")
    return bad


def main() -> int:
    bad = 0
    for fn in (
        test_session_chain,
        test_session_skips_bad_keys,
        test_turn_requires_session_and_id,
        test_link_direction_matches_evidence,
        test_cooccur,
        test_cooccur_skips_strongly_linked,
        test_cooccur_allowed_when_link_is_review,
        test_tags_end_to_end,
        test_tags_unknown_and_oversized,
        test_tags_block_cooccur,
        test_method_hub,
        test_method_skips_oversized,
        test_method_alias_word_boundary,
        test_ref_boundaries,
        test_config_error,
        test_method_skipped_reported,
        test_log_roundtrip,
    ):
        bad += fn()
    print("全部通过" if not bad else f"**{bad} 处失败**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
