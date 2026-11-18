"""冻结评测基线：同一张图、同一批用例，每次跑出同样的数字。

只读图，不写查询日志，不碰记忆库。默认只跑公开假图用例；真实图用例放
eval.local.json（已 gitignore），加 --real 才读。

    python eval.py                                  # 公开假图
    python eval.py --real                           # 加上本机真实图用例
    python eval.py --save eval/2026-11-16.json      # 存快照，供以后 --compare
    python eval.py --compare a.json b.json          # 两个快照逐项比

同一张图跑两次，dumps() 必须逐字一致——这是"基线"两个字的全部含义。
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path

from graph import CN, EDGE_KINDS, graph_file, load
from nav import GROUPS, Navigator, dead_end, neighbors

HERE = Path(__file__).parent
PUBLIC = HERE / "eval.json"
LOCAL = HERE / "eval.local.json"
K = 3  # 固定候选数：基线要能逐字复现，不给开关

# 默认 + 每个边类各关一次 + 关回顾型引用。表里只显示和默认不同的那些。
VARIANTS: list[tuple[str, tuple[str, ...], bool]] = [("默认", (), True)]
VARIANTS += [(f"关{CN[kind]}", (kind,), True) for kind in EDGE_KINDS]
VARIANTS.append(("关回顾", (), False))


def _kinds(off: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(k for k in EDGE_KINDS if k not in off)


def load_cases(paths: list[Path]) -> dict[str, dict]:
    """把若干用例文件的 graphs 段合并；文件不存在就跳过。"""
    out: dict[str, dict] = {}
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        for name, spec in (raw.get("graphs") or {}).items():
            slot = out.setdefault(name, {"paths": [], "about": []})
            slot["paths"].extend(spec.get("paths") or [])
            slot["about"].extend(spec.get("about") or [])
    return out


def _dead_code(text: str) -> str:
    """把 dead_end 的长句压成一个稳定短码，便于进表和比较。"""
    if "被当前开关关掉" in text:
        return "断·开关切断"
    if "两端都是孤立点" in text:
        return "断·双孤岛"
    if "源节点是孤立点" in text:
        return "断·源孤岛"
    if "目标节点是孤立点" in text:
        return "断·目标孤岛"
    if "分属两个连通块" in text:
        return "断·不连通"
    return "断·其他"


def _span(note: str) -> str:
    for key, name in (
        ("全靠回顾型引用", "全回顾"),
        ("至少跨两个轮次", "跨轮"),
        ("同一个轮次里", "复述"),
        ("判不出", "判不出"),
    ):
        if key in note:
            return name
    return "—"


def _weakest(p) -> str:
    if not p.edges:
        return ""
    return min(p.edges, key=lambda e: EDGE_KINDS[e[2]][1])[2]


def _path_row(g, desc: str, src_name: str, dst_name: str) -> dict:
    row: dict = {
        "label": f"{src_name} → {dst_name}",
        "desc": desc,
        "src": src_name,
        "dst": dst_name,
        "variants": {},
    }
    src, hits_s = g.resolve(src_name)
    dst, hits_d = g.resolve(dst_name)
    if not src or not dst:
        row["status"] = "解析失败"
        row["hits"] = len(hits_s) if not src else len(hits_d)
        return row
    row["src_id"], row["dst_id"] = src, dst
    if src == dst:
        row["status"] = "同节点"
        return row
    row["status"] = "已解析"
    for vlabel, off, review in VARIANTS:
        kinds = _kinds(off)
        paths = Navigator(kinds=kinds, k=K, review=review).route(g, src, dst)
        if paths:
            p = paths[0]
            row["variants"][vlabel] = {
                "status": "通",
                "hops": len(p.nodes) - 1,
                "cost": round(p.cost, 2),
                "confidence": round(p.confidence, 2),
                "weakest": _weakest(p),
                "span": _span(p.note),
                "candidates": len(paths),
            }
        else:
            row["variants"][vlabel] = {
                "status": "断",
                "reason": _dead_code(dead_end(g, src, dst, kinds, review)),
            }
    return row


def _about_row(g, desc: str, seed: str) -> dict:
    row: dict = {"label": seed, "desc": desc, "seed": seed, "variants": {}}
    nid, hits = g.resolve(seed)
    if not nid:
        row["status"] = "解析失败"
        row["hits"] = len(hits)
        return row
    row["status"] = "已解析"
    row["node"] = nid
    for vlabel, off, review in VARIANTS:
        nb = neighbors(g, nid, _kinds(off), review)
        row["variants"][vlabel] = {group: len(nb[group]) for group in GROUPS}
    return row


def _summary(rows: list[dict], about: list[dict]) -> dict:
    default = [r["variants"]["默认"] for r in rows if r.get("variants")]
    found = [v for v in default if v["status"] == "通"]
    return {
        "paths": len(rows),
        "found": len(found),
        "dead": dict(Counter(v["reason"] for v in default if v["status"] == "断")),
        "hops": dict(Counter(v["hops"] for v in found)),
        "confidence": dict(Counter(v["confidence"] for v in found)),
        "weakest": dict(Counter(v["weakest"] for v in found)),
        "span": dict(Counter(v["span"] for v in found)),
        "seeds": len(about),
        "neighbors": sum(
            sum(r["variants"]["默认"].values()) for r in about if r.get("variants")
        ),
    }


def collect(cases: dict[str, dict]) -> dict:
    """跑完全部用例，返回可比较的快照。纯只读，不写日志。"""
    snap: dict = {"_说明": "由 eval.py 生成；同一张图两次跑应逐字一致。", "graphs": {}}
    for name, spec in cases.items():
        path = graph_file(name)
        if not path.is_file():
            snap["graphs"][name] = {"missing": True}
            continue
        g = load(path)
        rows = [
            _path_row(g, entry[2] if len(entry) > 2 else f"{entry[0]} → {entry[1]}", entry[0], entry[1])
            for entry in spec["paths"]
        ]
        about = [
            _about_row(g, entry[1] if len(entry) > 1 else entry[0], entry[0])
            for entry in spec["about"]
        ]
        snap["graphs"][name] = {
            "nodes": len(g.titles),
            "edges": len(g.edges),
            "paths": rows,
            "about": about,
            "summary": _summary(rows, about),
        }
    return snap


def dumps(snap: dict) -> str:
    return json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True)


def _w(text: str) -> int:
    """终端显示宽度：中文算两格，否则表会歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _w(text))


def _cell(v: dict) -> str:
    if v["status"] == "断":
        return v["reason"]
    tail = f" {v['span']}" if v["span"] and v["span"] != "—" else ""
    return f"{v['hops']}跳 {v['confidence']:.2f}{tail}"


def _about_cell(counts: dict) -> str:
    return "/".join(str(counts[group]) for group in GROUPS)


def _path_cells(rows: list[dict]) -> list[tuple[str, str, str]]:
    out = []
    for r in rows:
        if r.get("variants"):
            base = r["variants"]["默认"]
            cell = _cell(base)
            changes = "；".join(
                f"{v}→{_cell(x)}"
                for v, x in r["variants"].items()
                if v != "默认" and x != base
            ) or "—"
        elif r["status"] == "解析失败":
            cell, changes = f"解析失败（命中 {r.get('hits', 0)} 个）", "—"
        else:
            cell, changes = r["status"], "—"
        out.append((r["label"], cell, changes))
    return out


def _about_cells(rows: list[dict]) -> list[tuple[str, str, str]]:
    out = []
    for r in rows:
        if not r.get("variants"):
            out.append((r["label"], f"解析失败（命中 {r.get('hits', 0)} 个）", "—"))
            continue
        base = r["variants"]["默认"]
        changes = "；".join(
            f"{v}→{_about_cell(x)}"
            for v, x in r["variants"].items()
            if v != "默认" and x != base
        ) or "—"
        out.append((r["label"], _about_cell(base), changes))
    return out


def _table(head: tuple[str, str, str], rows: list[tuple[str, str, str]]) -> list[str]:
    c1 = max([_w(head[0])] + [_w(r[0]) for r in rows]) + 2
    c2 = max([_w(head[1])] + [_w(r[1]) for r in rows]) + 2
    return [_pad(head[0], c1) + _pad(head[1], c2) + head[2]] + [
        _pad(a, c1) + _pad(b, c2) + c for a, b, c in rows
    ]


def render(snap: dict) -> str:
    lines: list[str] = []
    for name, g in snap["graphs"].items():
        if g.get("missing"):
            lines.append(f"== {name}：图不在，跳过")
            continue
        lines.append(f"== {name}（{g['nodes']} 节点 / {g['edges']} 边）")
        if g["paths"]:
            lines.append(f"路径 · {len(g['paths'])} 条")
            lines += _table(("用例", "默认", "变化"), _path_cells(g["paths"]))
            s = g["summary"]
            parts = [f"通 {s['found']}/{s['paths']}"]
            if s["dead"]:
                parts.append("断：" + "、".join(f"{k} {v}" for k, v in sorted(s["dead"].items())))
            if s["hops"]:
                parts.append("跳数 " + "、".join(f"{k}:{v}" for k, v in sorted(s["hops"].items())))
            if s["confidence"]:
                parts.append(
                    "conf " + "、".join(f"{k:.2f}:{v}" for k, v in sorted(s["confidence"].items()))
                )
            if s["weakest"]:
                parts.append(
                    "最弱环 "
                    + "、".join(f"{CN.get(k, k)}:{v}" for k, v in sorted(s["weakest"].items()))
                )
            if s["span"]:
                parts.append("口径 " + "、".join(f"{k}:{v}" for k, v in sorted(s["span"].items())))
            lines.append("汇总：" + "；".join(parts))
        if g["about"]:
            lines.append("")
            lines.append(f"展开 · {len(g['about'])} 个种子")
            lines += _table(("种子", "概念/引用/同源/共现/近邻", "变化"), _about_cells(g["about"]))
            lines.append(f"汇总：{g['summary']['seeds']} 个种子，默认开关下共 {g['summary']['neighbors']} 条邻居")
        lines.append("")
    return "\n".join(lines).rstrip()


def diff(old: dict, new: dict) -> list[tuple[str, str, str, str, object, object]]:
    """逐用例、逐开关比两个快照；返回 (图, 段, 用例, 开关, 旧, 新)。"""
    out: list[tuple[str, str, str, str, object, object]] = []
    for gname in sorted(set(old.get("graphs", {})) | set(new.get("graphs", {}))):
        og = old.get("graphs", {}).get(gname, {})
        ng = new.get("graphs", {}).get(gname, {})
        if og.get("missing") != ng.get("missing"):
            out.append((gname, "图", gname, "存在", not og.get("missing"), not ng.get("missing")))
        for section in ("paths", "about"):
            old_rows = {r["label"]: r for r in og.get(section, [])}
            new_rows = {r["label"]: r for r in ng.get(section, [])}
            for label in sorted(set(old_rows) | set(new_rows)):
                if label not in old_rows:
                    out.append((gname, section, label, "新增", "", new_rows[label]))
                    continue
                if label not in new_rows:
                    out.append((gname, section, label, "消失", old_rows[label], ""))
                    continue
                ov, nv = old_rows[label].get("variants", {}), new_rows[label].get("variants", {})
                for variant in sorted(set(ov) | set(nv)):
                    a, b = ov.get(variant), nv.get(variant)
                    if a != b:
                        out.append((gname, section, label, variant, a, b))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="冻结评测基线：固定用例 × 全部开关，输出可比快照")
    ap.add_argument("--real", action="store_true", help="加上 eval.local.json 里的本机真实图用例")
    ap.add_argument("--save", help="把本次快照写成 JSON，供以后 --compare")
    ap.add_argument("--compare", nargs=2, metavar=("旧快照", "新快照"), help="只比较两个快照，不跑图")
    a = ap.parse_args(argv)

    if a.compare:
        old = json.loads(Path(a.compare[0]).read_text(encoding="utf-8"))
        new = json.loads(Path(a.compare[1]).read_text(encoding="utf-8"))
        changes = diff(old, new)
        if not changes:
            print("两个快照完全一样。")
            return 0
        print(f"差异 {len(changes)} 处：")
        for gname, section, label, variant, before, after in changes:
            print(f"  {gname} · {section} · {label} · {variant}")
            print(f"    旧：{before}")
            print(f"    新：{after}")
        return 0

    files = [PUBLIC]
    if a.real:
        if LOCAL.exists():
            files.append(LOCAL)
        else:
            print(f"（没有 {LOCAL.name}，跳过真实图用例；模板见 eval.local.example.json）")
    cases = load_cases(files)
    if not cases:
        print("没有可跑的用例。")
        return 2
    snap = collect(cases)
    print(render(snap))
    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dumps(snap) + "\n", encoding="utf-8")
        print(f"\n快照：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
