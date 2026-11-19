"""评测基线自身要可信：两次跑出同样结果、公开用例都能解析、比较模式能报差异。

`python test_eval.py` 直接跑。只碰公开假图；真实图用例不在这里跑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import eval as ev

HERE = Path(__file__).parent


def check_cases() -> int:
    bad = 0
    cases = ev.load_cases([HERE / "eval.json"])
    if "fake_graph.json" not in cases:
        bad += 1
        print("  ✗ eval.json 里没有假图用例")
        return bad
    if "mem_graph.json" in cases:
        bad += 1
        print("  ✗ 公开用例里混进了真实图（默认不该读本机数据）")
    snap = ev.collect(cases)
    g = snap["graphs"]["fake_graph.json"]
    if g.get("missing"):
        bad += 1
        print("  ✗ 假图不在")
        return bad
    variants = {v[0] for v in ev.VARIANTS}
    for section in ("paths", "about"):
        for row in g[section]:
            if row.get("status") == "解析失败":
                bad += 1
                print(f"  ✗ {section} 用例解析失败：{row['label']}")
                continue
            if set(row.get("variants", {})) != variants:
                bad += 1
                print(f"  ✗ {section} 用例开关不全：{row['label']}")
    print(f"基线用例：{'通过' if not bad else '失败'}")
    return bad


def check_determinism() -> int:
    bad = 0
    cases = ev.load_cases([HERE / "eval.json"])
    a, b = ev.dumps(ev.collect(cases)), ev.dumps(ev.collect(cases))
    if a != b:
        bad += 1
        print("  ✗ 同一张图两次跑出的快照不一致")
    print(f"基线可复现：{'通过' if not bad else '失败'}")
    return bad


def check_compare() -> int:
    bad = 0
    cases = ev.load_cases([HERE / "eval.json"])
    snap = ev.collect(cases)
    if ev.diff(snap, snap):
        bad += 1
        print("  ✗ 自己和自己比还有差异")
    changed = json.loads(ev.dumps(snap))
    row = changed["graphs"]["fake_graph.json"]["paths"][0]
    row["variants"]["默认"]["hops"] += 1
    hits = [d for d in ev.diff(snap, changed) if d[2] == row["label"] and d[3] == "默认"]
    if not hits:
        bad += 1
        print("  ✗ 改动一条结果后比较模式没报出来")
    print(f"基线比较：{'通过' if not bad else '失败'}")
    return bad


def check_synth_method_bridge() -> int:
    """方法桥：甲经枢纽找到乙；关方法边就断，独立共现不受影响。"""
    bad = 0
    snap = ev.collect(ev.load_cases([HERE / "eval.json"]))
    rows = {r["label"]: r for r in snap["graphs"]["eval_synth.json"]["paths"]}
    ab = rows["a → b"]
    if ab["variants"]["默认"]["status"] != "通" or ab["variants"]["默认"]["hops"] != 2:
        bad += 1
        print(f"  ✗ 方法桥应是 2 跳：{ab['variants']['默认']}")
    if ab["variants"]["关同方法"]["status"] != "断":
        bad += 1
        print(f"  ✗ 关掉方法边后方法桥没断：{ab['variants']['关同方法']}")
    hops = ab.get("hops_detail") or []
    if len(hops) != 2 or any(h["kind"] != "method" for h in hops):
        bad += 1
        print(f"  ✗ 逐跳应是两条同方法边：{hops}")
    if any(h["evidence_missing"] for h in hops):
        bad += 1
        print(f"  ✗ 合成图的方法边不该缺证据：{hops}")
    if not all("提到" in (h["quote"] or "") for h in hops):
        bad += 1
        print(f"  ✗ 证据应写“提到”而不是“用过”：{hops}")
    ac = rows["a → c"]
    if ac["variants"]["关同方法"]["status"] != "通" or ac["variants"]["关同方法"]["hops"] != 1:
        bad += 1
        print(f"  ✗ 独立共现被方法开关误伤：{ac['variants']['关同方法']}")
    print(f"方法桥：{'通过' if not bad else '失败'}")
    return bad


def check_about_identity() -> int:
    """展开要记到人和证据：同组换错人时数量不变，只看计数抓不住。"""
    bad = 0
    snap = ev.collect(ev.load_cases([HERE / "eval.json"]))
    about = {r["label"]: r for r in snap["graphs"]["eval_synth.json"]["about"]}
    base = about["a"]["variants"]["默认"]
    if [x["node"] for x in base["概念"]] != ["hub"]:
        bad += 1
        print(f"  ✗ 概念组应只有方法枢纽：{base['概念']}")
    elif not base["概念"][0]["evidence"].startswith("提到"):
        bad += 1
        print(f"  ✗ 概念证据应写“提到”：{base['概念'][0]['evidence']}")
    ref = {x["node"]: x["direction"] for x in base["引用"]}
    if ref != {"d": "in", "e": "out"}:
        bad += 1
        print(f"  ✗ 引用方向不对：{ref}")
    if [x["node"] for x in base["共现"]] != ["c"]:
        bad += 1
        print(f"  ✗ 共现组不对：{base['共现']}")
    off = about["a"]["variants"]["关同方法"]
    if off["概念"] or [x["node"] for x in off["共现"]] != ["c"]:
        bad += 1
        print(f"  ✗ 关方法后概念应清空、共现应保留：{off}")
    hub = {x["node"]: x for x in about["hub"]["variants"]["默认"]["概念"]}
    if "尚未实施" not in hub.get("b", {}).get("title", ""):
        bad += 1
        print(f"  ✗ 方法成员应带可核对的标题：{hub.get('b')}")
    if "提到" not in hub.get("b", {}).get("evidence", ""):
        bad += 1
        print(f"  ✗ “尚未实施”的记录应只说提到，不断言用过：{hub.get('b')}")
    print(f"展开身份与证据：{'通过' if not bad else '失败'}")
    return bad


def check_same_count_wrong_member() -> int:
    """数量相同、成员换错：--compare 必须标出来，否则基线是瞎的。"""
    bad = 0
    snap = ev.collect(ev.load_cases([HERE / "eval.json"]))
    changed = json.loads(ev.dumps(snap))
    about = next(r for r in changed["graphs"]["eval_synth.json"]["about"] if r["label"] == "a")
    concept = about["variants"]["默认"]["概念"]
    before = [x["node"] for x in concept]
    concept[0]["node"] = "c"  # 组内换人，数量不变
    if [x["node"] for x in concept] == before:
        bad += 1
        print("  ✗ 对照没构造出来")
    hits = [d for d in ev.diff(snap, changed) if d[2] == "a" and d[3] == "默认"]
    if not hits:
        bad += 1
        print("  ✗ 同数换错人时比较模式没报差异")
    print(f"同数换错人：{'通过' if not bad else '失败'}")
    return bad


def check_evidence_traceability() -> int:
    """旧边没留下原话要明说；合成图的边都带原话。"""
    bad = 0
    snap = ev.collect(ev.load_cases([HERE / "eval.json"]))
    fake = snap["graphs"]["fake_graph.json"]
    if fake["summary"]["hops_without_evidence"] <= 0:
        bad += 1
        print("  ✗ 假图的旧链接没有证据，汇总应标出来")
    if not any(h["evidence_missing"] for r in fake["paths"] for h in r.get("hops_detail", [])):
        bad += 1
        print("  ✗ 假图的逐跳记录没标证据缺失")
    synth = snap["graphs"]["eval_synth.json"]
    if synth["summary"]["hops_without_evidence"] or synth["summary"]["neighbors_without_evidence"]:
        bad += 1
        print(f"  ✗ 合成图不该有证据缺口：{synth['summary']}")
    print(f"证据回溯：{'通过' if not bad else '失败'}")
    return bad


def main() -> int:
    bad = (
        check_cases()
        + check_determinism()
        + check_compare()
        + check_synth_method_bridge()
        + check_about_identity()
        + check_same_count_wrong_member()
        + check_evidence_traceability()
    )
    print("全部通过" if not bad else f"**{bad} 处失败**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
