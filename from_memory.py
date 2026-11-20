"""从记忆库抽图——**只读**。

这是一个适配器，不是库的一部分：核心（graph.py / nav.py / cli.py）不认识任何具体的记忆存储。
所以要显式告诉它数据在哪：

    python from_memory.py --mem-home ~/某个记忆库

也可以设 OPENCODE_MEM_HOME。没有默认路径——通用的东西不该猜某台机器上的私有目录。

数据源是 JSONL：stream.jsonl 是记录本体（顺序即 #NNNN 记录号），episodes/tools/marks/assoc
只在拍指纹时用到。
本文件只 open(..., "r")，不写、不改、不迁移源数据；输出默认落在 kgnav/data/ 里。
真跑之前对源文件拍一遍 sha256，跑完再拍一遍，必须一模一样——见 verify_source()。

抽三类东西：
  link    文本里的 #NNNN 引用（谁提到了谁），以及 episode 自带的 id 列表
  source  记录 → 同一轮任务的 episode（episode 就是那一轮的"来源"）
节点去重：同内容只留一个（同一段回复可能被反复存成多份）；
产物按文件路径合并成一个节点（同一文件写了 50 版，不该是 50 个节点）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from bisect import bisect_right
from collections import Counter, defaultdict, deque
from pathlib import Path

from querylog import QueryRef, read_queries

HERE = Path(__file__).parent
DEFAULT_OUT = HERE / "data" / "mem_graph.json"

# 只认独立的 #N：前面不能贴着字母/数字/下划线/&/斜杠（挡掉 abc#123、&#123、URL 片段），
# 后面不能贴着 ASCII 字母/数字/下划线（挡掉 #123abc）；中文紧跟（#123这轮）仍算引用。
REF = re.compile(r"(?<![A-Za-z0-9_&#/])#(\d+)(?![A-Za-z0-9_])")
FENCE = re.compile(r"^\s*(```|~~~)")


class ConfigError(Exception):
    """标签/方法词表文件存在但读不出来。静默当空会让「文件写坏了」看起来像「没有配置」。"""


def _code_spans(text: str) -> list[tuple[int, int]]:
    """围栏代码块 [start, end) 区间。里面的 #N 是代码或注释，不是"提到了这条记录"。"""
    spans: list[tuple[int, int]] = []
    start = None
    pos = 0
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            if start is None:
                start = pos
            else:
                spans.append((start, pos + len(line)))
                start = None
        pos += len(line)
    if start is not None:
        spans.append((start, len(text)))
    return spans


def iter_refs(text: str):
    """正文里的 #N 引用，跳过围栏代码块里那些。"""
    spans = _code_spans(text)
    i = 0
    for m in REF.finditer(text):
        while i < len(spans) and spans[i][1] <= m.start():
            i += 1
        if i < len(spans) and spans[i][0] <= m.start() < spans[i][1]:
            continue
        yield m


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:  # 只读
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_source(mem: Path) -> dict[str, str]:
    """给源文件拍指纹。跑之前拍一次，跑完再拍一次，必须一模一样。"""
    out = {}
    for name in ("stream.jsonl", "episodes.jsonl", "tools.jsonl", "marks.jsonl", "assoc.json"):
        p = mem / name
        out[name] = sha256_file(p) if p.exists() else "-"
    return out


def read_records(mem: Path) -> list[dict]:
    recs = []
    with (mem / "stream.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["n"] = len(recs) + 1  # 记录号：文件里的顺序就是 #NNNN
            recs.append(r)
    return recs


def title_of(rec: dict) -> str:
    text = norm(rec.get("text"))
    episode = text.startswith("任务摘录")
    text = re.sub(r"^任务摘录[：:]\s*", "", text)
    text = re.sub(r"^[#>*\-\s]+", "", text)
    text = text[:30] + ("…" if len(text) > 30 else "")
    tag = "〔轮次〕" if episode else ""
    return f"{tag}#{rec['n']} {text}"


def short_path(p: str) -> str:
    file = Path(p)
    return "/".join([x for x in re.split(r"[\\/]+", str(file)) if x][-2:])


def _window_ep(starts: list[tuple[int, str, int]] | None, n: int) -> tuple[str, int, int] | None:
    """同一 sid 里，起点最晚且不晚于这条记录的 episode → (节点, 记录号, requestSeq)。"""
    if not starts:
        return None
    i = bisect_right(starts, (n, "\uffff", 0)) - 1
    return starts[i] if i >= 0 else None


def _turn_key(rec: dict) -> tuple[str, str] | None:
    session, turn = rec.get("sid"), rec.get("turnID")
    if isinstance(session, str) and session and isinstance(turn, str) and turn:
        return session, turn
    return None


def _snippet(text: str, start: int, end: int, pad: int = 40) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return ("…" if a else "") + norm(text[a:b]) + ("…" if b < len(text) else "")


MAX_TAG_NODES = 12  # 一个标签最多挂几个节点；再多就是团块，不是关系
MAX_METHOD_NODES = 40  # 一个方法最多挂几条记录；再通用就失去区分度


def _resolve_key(key: str, nodes: dict[str, dict]) -> str | None:
    """tags.json 的键：节点 id / #记录号 / 精确标题 / 唯一的标题片段。认不出就返回 None。"""
    if key in nodes:
        return key
    m = re.fullmatch(r"#(\d+)", key.strip())
    if m and f"r{m.group(1)}" in nodes:
        return f"r{m.group(1)}"
    for nid, n in nodes.items():
        if n["title"] == key:
            return nid
    hits = [nid for nid, n in nodes.items() if key in n["title"]]
    return hits[0] if len(hits) == 1 else None


resolve_tag_key = _resolve_key  # 给 tags.py 用


def read_methods(path: Path) -> dict[str, list[str]]:
    """读方法词表：{方法名: [别名/写法, ...]}。不存在就当没有；存在但坏了报 ConfigError。"""
    return read_tags(path)  # 结构完全一样，复用同一套校验


def read_tags(path: Path) -> dict[str, list[str]]:
    """读手工标签文件：{标签: [节点键, ...]}。

    文件不存在 → 空表（标签本来就可以不写）；存在但读不出来 → 报错。
    否则一次手滑改坏 JSON，导出会安静地丢掉全部标签和全部方法。
    """
    try:
        text = path.read_text(encoding="utf-8-sig")  # 记事本存的 UTF-8 BOM 不该被当成坏文件
    except FileNotFoundError:
        return {}
    except UnicodeDecodeError as e:
        raise ConfigError(f"{path} 不是 UTF-8 编码（第 {e.start} 字节）：另存为 UTF-8 再试") from e
    except OSError as e:
        raise ConfigError(f"{path} 读不了：{e}") from e
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} 不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列）：{e.msg}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} 顶层应是对象 {{名称: [...]}}，实际是 {type(raw).__name__}")
    out: dict[str, list[str]] = {}
    for tag, keys in raw.items():
        if str(tag).startswith("_"):
            continue
        if not isinstance(keys, list):
            raise ConfigError(f"{path} 里「{tag}」的值应是列表，实际是 {type(keys).__name__}")
        out[str(tag)] = [k for k in keys if isinstance(k, str) and k.strip()]
    return out


_ASCII_ONLY = re.compile(r"\A[\x00-\x7f]+\Z")


def _alias_pattern(term: str) -> re.Pattern[str]:
    """英文/符号别名按词边界匹配：storage 里的 rag 不是"提到 RAG"。

    中文没有空格分词，词边界会把正常写法挡掉，所以含非 ASCII 的别名仍用子串。
    """
    body = re.escape(term)
    if _ASCII_ONLY.match(term):
        return re.compile(r"(?<![A-Za-z0-9_])" + body + r"(?![A-Za-z0-9_])", re.IGNORECASE | re.ASCII)
    return re.compile(body, re.IGNORECASE)


def build(
    recs: list[dict],
    use_window: bool = True,
    queries: list[dict] | None = None,
    graph_tag: str = "",
    tag_map: dict[str, list[str]] | None = None,
    methods: dict[str, list[str]] | None = None,
) -> tuple[dict, dict]:
    nodes: dict[str, dict] = {}
    rec2node: dict[int, str] = {}

    # 1) 产物按路径合并
    path2node: dict[str, str] = {}
    for r in recs:
        if r.get("kind") == "artifact" and r.get("path"):
            p = r["path"]
            if p not in path2node:
                nid = "f" + _sha1(p)[:7]  # 由路径算出来，重建图也不会变
                path2node[p] = nid
                nodes[nid] = {"id": nid, "title": short_path(p), "text": p, "path": p, "count": 0}
            nodes[path2node[p]]["count"] += 1
            rec2node[r["n"]] = path2node[p]

    # 2) 其余记录按内容去重
    content2node: dict[str, str] = {}
    ep_by_turn: dict[tuple, str] = {}  # 同一轮被总结了两次：并成一个节点，别当成两条笔记
    for r in recs:
        if r["n"] in rec2node:
            continue
        key = _sha1(norm(r.get("text")))
        turn = _turn_key(r) if r.get("kind") == "episode" else None
        if turn is not None and turn in ep_by_turn:
            rec2node[r["n"]] = ep_by_turn[turn]
            nodes[ep_by_turn[turn]]["count"] += 1
            continue
        if key in content2node:
            rec2node[r["n"]] = content2node[key]
            nodes[content2node[key]]["count"] += 1
            continue
        nid = f"r{r['n']}"
        content2node[key] = nid
        rec2node[r["n"]] = nid
        if turn is not None:
            ep_by_turn[turn] = nid
        nodes[nid] = {
            "id": nid,
            "title": title_of(r),
            "text": norm(r.get("text"))[:600],
            "kind": r.get("kind"),
            "who": r.get("who"),
            "first": r["n"],
            "count": 1,
        }

    # 3) 边。每条边都带证据：哪条记录（#N）+ 那句原话，方便回 L0 核对。
    edges: list[dict] = []
    seen: dict[tuple[str, str, str], dict] = {}  # 方向无关的键 → 已存下的那条边
    # 轮次摘录的行首结构位才是真引用："产物 #1595：路径"、"助手摘录 #1593：…"。
    # 摘录正文里出现的 #N 是"引用之引用"——那段话本身在讨论别的记录，不该算这条边。
    STRUCT_LABELS = {"产物", "助手摘录", "来源", "请求"}

    def add(
        a: str, b: str, kind: str, n: int | None = None, quote: str = "", review: bool = False,
        *, query_refs: list[QueryRef] | None = None,
    ) -> bool:
        if a == b:
            return False
        key = (a, b, kind) if a <= b else (b, a, kind)
        old = seen.get(key)
        if old is not None:
            if review is False:  # 同一对边只要有一条不是回顾型的，就不该被标成回顾型
                old.update({"from": a, "to": b, "review": False, "n": n, "quote": quote})
            return False
        edge = {"from": a, "to": b, "kind": kind, "n": n, "quote": quote, "review": review}
        if query_refs:
            edge["query_refs"] = query_refs
        seen[key] = edge
        edges.append(edge)
        return True

    refs_in_code = 0
    for r in recs:
        src = rec2node[r["n"]]
        text = r.get("text") or ""
        is_ep = r.get("kind") == "episode"
        refs = list(iter_refs(text))
        refs_in_code += len(REF.findall(text)) - len(refs)
        for m in refs:
            tgt_n = int(m.group(1))
            tgt = rec2node.get(tgt_n)
            if tgt is None:
                continue
            # 回顾型（可整类关掉）有两种：
            #   1. 普通记录在正文里提到更早的记录 —— 多半是"后来在讨论它"
            #   2. 轮次摘录的正文里出现的引用 —— 那是摘录内容在讨论别的记录，是引用之引用
            if is_ep:
                line_start = text.rfind("\n", 0, m.start()) + 1
                review = text[line_start : m.start()].strip() not in STRUCT_LABELS
            else:
                review = tgt_n < r["n"]
            add(src, tgt, "link", r["n"], _snippet(text, m.start(), m.end()), review)

    # 3b) episode 自己记着这轮的 sourceIDs / answerIDs / artifactIDs（UUID），
    #     这些是真·精确引用，比正文里的 #N 更硬，而且能救回没有 turnID 的记录。
    id2node = {r["id"]: rec2node[r["n"]] for r in recs if r.get("id") and r["n"] in rec2node}
    id_edges = 0
    for r in recs:
        if r.get("kind") != "episode":
            continue
        src = rec2node[r["n"]]
        for field in ("sourceIDs", "answerIDs", "artifactIDs"):
            for u in r.get(field) or []:
                if u in id2node and add(src, id2node[u], "link", r["n"], f"这一轮的 {field} 里列了它"):
                    id_edges += 1

    # 4) 同一轮的任务摘录当"来源"枢纽。
    #    turnID 对不上时退一步：episode 自己记了 requestSeq（那一轮从哪条记录开始），
    #    同一 sid 里取"起点早于它、且最晚的那条 episode"。这是照抄记录里的边界，不是猜。
    turn2ep: dict[tuple[str, str], tuple[str, int]] = {}
    by_sid: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    for r in recs:
        if r.get("kind") != "episode":
            continue
        nid = rec2node[r["n"]]
        turn = _turn_key(r)
        if turn is not None:
            turn2ep[turn] = nid, r["n"]
        sid, seq = r.get("sid"), r.get("requestSeq")
        if isinstance(sid, str) and sid and type(seq) is int and seq > 0:
            by_sid[sid].append((seq, nid, r["n"]))
    for starts in by_sid.values():
        starts.sort()

    exact = window = miss = 0
    node_turns: dict[str, set[str]] = defaultdict(set)
    for r in recs:
        hit = turn2ep.get(_turn_key(r))
        why = "同一轮：turnID 对得上"
        if hit is not None:
            exact += 1
        elif use_window and isinstance(r.get("sid"), str):
            found = _window_ep(by_sid.get(r["sid"]), r["n"])
            if found:
                seq, node, ep_n = found
                window += 1
                hit, why = (node, ep_n), f"同一轮：按它记的 requestSeq={seq} 归过来"
        if hit is None:
            miss += 1
            continue
        add(rec2node[r["n"]], hit[0], "source", hit[1], why)
        node_turns[rec2node[r["n"]]].add(hit[0])

    for nid, turns in node_turns.items():
        nodes[nid]["turns"] = sorted(turns)  # 这个节点属于哪几轮：判断路径是否只是复述来源

    # 4b) 手工标签：唯一一类"概念边"，因为标签是你的断言，不是从文本猜的。
    #     文件是「标签 → 节点列表」；键可以是节点 id、#记录号、标题或唯一的标题片段。
    #     一个标签挂太多节点会变成团块，超过 MAX_TAG_NODES 就整条丢弃并报出来。
    tags_applied = tags_unknown = tags_dropped = 0
    tag_edges = 0
    tag_pairs: set[tuple[str, str]] = set()
    if tag_map:
        for tag, keys in tag_map.items():
            ids: set[str] = set()
            for key in keys:
                nid = resolve_tag_key(str(key), nodes)
                if nid is None:
                    tags_unknown += 1
                    continue
                tags_applied += 1
                ids.add(nid)
            if not ids:
                continue
            if len(ids) > MAX_TAG_NODES:
                tags_dropped += 1
                continue
            tag_edges += len(ids) * (len(ids) - 1) // 2  # 加载时会派生出来的边数
            ordered = sorted(ids)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1 :]:
                    tag_pairs.add((a, b))
            for nid in ids:
                nodes[nid].setdefault("tags", []).append(str(tag))
        for n in nodes.values():
            if "tags" in n:
                n["tags"] = sorted(set(n["tags"]))

    # 4c) 方法索引：一份方法词表（含别名）→ 每个方法建一个"方法"枢纽节点。
    #     这就是"举一反三"：同一个方法在不同项目、不同时间的记录，都接到同一个枢纽上。
    #     枢纽没有轮次归属，所以路径会说"判不出是不是同一轮"——这是对的，它跨时间。
    method_hubs = method_edges = 0
    method_skipped: dict[str, str] = {}  # 方法名 → 为什么没建枢纽（静默跳过等于骗人）
    if methods:
        for name, terms in methods.items():
            keys = [t.strip() for t in terms if isinstance(t, str) and t.strip()]
            if not keys:
                method_skipped[str(name)] = "没有可用别名"
                continue
            pats = [_alias_pattern(term) for term in keys]
            member: dict[str, tuple[int, str]] = {}
            for r in recs:
                nid = rec2node[r["n"]]
                if nid in member:
                    continue
                text = r.get("text") or ""
                for pattern in pats:
                    match = pattern.search(text)
                    if match:
                        snippet = _snippet(text, match.start(), match.end())
                        member[nid] = r["n"], f"提到「{match[0]}」（方法：{name}） 原话：{snippet}"
                        break
            if not member:
                method_skipped[str(name)] = "没有记录提到"
                continue
            if len(member) > MAX_METHOD_NODES:
                method_skipped[str(name)] = (
                    f"命中 {len(member)} 条，超过上限 {MAX_METHOD_NODES}，会变成大团块"
                )
                continue
            hub = "m" + _sha1(name)[:7]
            nodes[hub] = {
                "id": hub,
                "title": f"方法：{name}",
                "text": name,
                "kind": "concept",
                "first": 0,
                "count": 1,
            }
            method_hubs += 1
            for nid, (number, quote) in member.items():
                if add(nid, hub, "method", number, quote):
                    method_edges += 1

    # 5) 同会话链：同一 sid 里相邻的两轮连一条。sid 和 requestSeq 都是记录里本来就有的，
    #    这不是推断，是把"同一次会话里先后聊过"这件事显式化。比"同一轮"弱，所以单独一类。
    #    没有 sid 或不带有效 requestSeq 的轮次不参与——顺序不可靠就不猜，宁可少一条边。
    session_edges = 0
    for sid, lst in by_sid.items():
        prev: tuple[int, str] | None = None
        for seq, node, n in lst:
            if prev and prev[0] < seq:  # 序号相同 = 同一轮的两份摘要，不连
                if add(prev[1], node, "session", n, f"同一会话里紧接着的下一轮（…{sid[-6:]}）"):
                    session_edges += 1
            if prev is None or prev[0] < seq:
                prev = (seq, node)

    # 6) 共现：被同一次查询一起问过的两个节点。这是"只有你才有"的那类信号，
    #    词频伪造不出来，代价是要用起来才有。
    #    只认同一张图、默认开关下的查询；证据写清问过几次、跨几天。
    cooccur_edges = 0
    if queries:
        query_refs: dict[tuple[str, str], deque[QueryRef]] = defaultdict(lambda: deque(maxlen=3))
        days: dict[tuple[str, str], set[int]] = defaultdict(set)
        times: Counter[tuple[str, str]] = Counter()
        missed: Counter[tuple[str, str]] = Counter()
        for q in queries:
            if graph_tag and q.get("graph") != graph_tag:
                continue
            if q.get("default") is not True:  # 消融/对照跑出来的查询不算注意力
                continue
            a, b = q.get("src"), q.get("dst")
            if not isinstance(a, str) or not isinstance(b, str) or a == b:
                continue
            if a not in nodes or b not in nodes:
                continue
            try:
                ts = int(q.get("ts"))
            except (TypeError, ValueError, OverflowError):
                continue
            key = (a, b) if a <= b else (b, a)
            days[key].add(ts // 86400)
            times[key] += 1
            ref = q.get("_query_ref")
            if ref is not None:
                query_refs[key].append(ref)
            if not q.get("found"):
                missed[key] += 1
        linked = {
            (min(e["from"], e["to"]), max(e["from"], e["to"]))
            for e in edges
            if not e.get("review")  # 回顾型边会被 --no-review 关掉，不该挡住兜底的共现
        } | tag_pairs  # 已经同标签的，再加共现只是重复
        for (a, b), n in times.items():
            if (a, b) in linked:
                continue
            d = len(days[(a, b)])
            head = f"你在 {d} 天里问过 {n} 次" if d > 1 else f"你问过 {n} 次"
            tail = f"，其中 {missed[(a, b)]} 次没找到路" if missed[(a, b)] else ""
            if add(a, b, "cooccur", quote=head + tail, query_refs=list(query_refs.get((a, b), ()))):
                cooccur_edges += 1

    graph = {
        "_说明": "由 from_memory.py 只读抽取，勿手改。重新生成会覆盖。",
        "nodes": list(nodes.values()),
        "links": edges,
        # 被跳过的方法留在图上，CLI 才能说清"为什么 --methods 里没有它"
        "methods_skipped": method_skipped,
    }
    base = health(nodes, edges)
    no_rev = health(nodes, [e for e in edges if not e.get("review")])
    stats = {
        "records": len(recs),
        "nodes": len(nodes),
        "edges": Counter(e["kind"] for e in edges),
        "id_references": id_edges,
        "collapsed": sum(v["count"] - 1 for v in nodes.values()),
        "exact": exact,
        "window": window,
        "no_episode": miss,
        "review": sum(1 for e in edges if e.get("review")),
        "session_edges": session_edges,
        "cooccur_edges": cooccur_edges,
        "tags_applied": tags_applied,
        "tags_unknown": tags_unknown,
        "tags_dropped": tags_dropped,
        "tag_edges": tag_edges,
        "method_hubs": method_hubs,
        "method_edges": method_edges,
        "method_skipped": method_skipped,
        "refs_in_code": refs_in_code,
        "isolated": base["isolated"],
        "biggest": base["biggest"],
        "isolated_no_review": no_rev["isolated"],
        "biggest_no_review": no_rev["biggest"],
    }
    return graph, stats


def health(nodes: dict, edges: list[dict]) -> dict:
    """孤岛数、最大连通块。孤岛是这张图唯一的硬伤，每次抽图都报一遍。"""
    adj: dict[str, set[str]] = {i: set() for i in nodes}
    for e in edges:
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])
    isolated = sum(1 for v in adj.values() if not v)
    seen: set[str] = set()
    biggest = 0
    for i in adj:
        if i in seen:
            continue
        stack, size = [i], 0
        seen.add(i)
        while stack:
            u = stack.pop()
            size += 1
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        biggest = max(biggest, size)
    return {"isolated": isolated, "biggest": biggest}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从记忆库 JSONL 抽一张图（只读源数据）")
    ap.add_argument(
        "--mem-home",
        default=os.environ.get("OPENCODE_MEM_HOME"),
        help="记忆库目录，里面要有 stream.jsonl；也可用 OPENCODE_MEM_HOME",
    )
    ap.add_argument("-o", "--out", default=str(DEFAULT_OUT), help="输出图 JSON")
    ap.add_argument("--queries", default=str(HERE / "data" / "queries.jsonl"), help="查询日志，用来生成共现边")
    ap.add_argument("--tags", default=str(HERE / "data" / "tags.json"), help="手工标签文件，用来生成同标签边")
    ap.add_argument("--methods", default=str(HERE / "data" / "methods.json"), help="方法词表，用来生成方法枢纽")
    ap.add_argument("--no-window", action="store_true", help="只认严格 turnID，不用 requestSeq 时间窗回填")
    a = ap.parse_args(argv)

    if not a.mem_home:
        print("没有指定记忆库位置。用法：python from_memory.py --mem-home <目录>")
        print("（或设 OPENCODE_MEM_HOME。这里故意不给默认路径——通用工具不该猜私有目录。）")
        return 2
    mem = Path(a.mem_home).expanduser()
    if not (mem / "stream.jsonl").exists():
        print(f"{mem} 下面没有 stream.jsonl，读不了。")
        return 2
    out = Path(a.out).expanduser()
    try:
        out.resolve().relative_to(mem.resolve())
        print("输出路径落在记忆库目录里，拒绝写入——这个工具对记忆库只读。")
        return 2
    except ValueError:
        pass

    before = verify_source(mem)
    recs = read_records(mem)
    queries = read_queries(Path(a.queries))
    try:
        tag_map = read_tags(Path(a.tags))
        methods = read_methods(Path(a.methods))
    except ConfigError as e:
        print(f"配置读不了，先修好再导出：{e}")
        return 2
    graph, stats = build(
        recs,
        use_window=not a.no_window,
        queries=queries,
        graph_tag=out.name,
        tag_map=tag_map,
        methods=methods,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    after = verify_source(mem)

    print(f"源：{mem}")
    print(f"记录 {stats['records']} → 节点 {stats['nodes']}（合并掉 {stats['collapsed']} 份重复/多版本）")
    print("边：" + "、".join(f"{k} {v}" for k, v in stats["edges"].items()))
    if stats["refs_in_code"]:
        print(f"  代码块里另有 {stats['refs_in_code']} 处 #号引用，未当作引用")
    print(f"外挂信号：同会话链 {stats['session_edges']} 条，共现 {stats['cooccur_edges']} 条（来自 {len(queries)} 次查询）")
    print(
        f"手工标签：命中 {stats['tags_applied']} 个键"
        f"、认不出 {stats['tags_unknown']} 个"
        f"、过大丢弃 {stats['tags_dropped']} 个标签"
        f"、将派生 {stats['tag_edges']} 条同标签边"
    )
    print(f"方法索引：{stats['method_hubs']} 个方法枢纽，{stats['method_edges']} 条「同方法」边")
    if stats["method_skipped"]:
        items = list(stats["method_skipped"].items())
        head = f"跳过 {len(items)} 个方法" if len(items) > 5 else "跳过的方法"
        print(f"  {head}：" + "；".join(f"{k}（{v}）" for k, v in items[:5]) + ("…" if len(items) > 5 else ""))
    print(
        f"归属：turnID 对上 {stats['exact']}"
        f"、seq 窗口补 {stats['window']}"
        f"、仍无归属 {stats['no_episode']}"
        f"；episode 的 id 列表另抽出 {stats['id_references']} 条精确引用"
    )
    print(
        f"健康：孤岛 {stats['isolated']}/{stats['nodes']}"
        f"（{stats['isolated'] / stats['nodes']:.0%}），最大连通块 {stats['biggest']}"
    )
    print(
        f"回顾型引用 {stats['review']} 条（{stats['review'] / max(1, len(graph['links'])):.0%}）；"
        f"整类关掉后：孤岛 {stats['isolated_no_review']}，最大连通块 {stats['biggest_no_review']}"
    )
    same = before == after
    print("源文件指纹：" + ("跑前跑后一致，未改动" if same else "**变了，停手**"))
    if not same:
        for k in before:
            if before[k] != after[k]:
                print(f"  {k}: {before[k][:12]} → {after[k][:12]}")
        return 1
    print(f"输出：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
