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


def main() -> int:
    bad = check_cases() + check_determinism() + check_compare()
    print("全部通过" if not bad else f"**{bad} 处失败**")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
