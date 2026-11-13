"""预览 / 校验标签文件：把 r1、f47402b3 这类 id 翻成人话。

不写任何东西，只读图和标签文件。

    python tags.py                 # 看 data/tags.json
    python tags.py --tags 草稿.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from from_memory import read_tags, resolve_tag_key
from graph import load

HERE = Path(__file__).parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把标签文件里的 id 翻成标题")
    ap.add_argument("--tags", default=str(HERE / "data" / "tags.json"))
    ap.add_argument("--graph", default="mem_graph.json")
    a = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    tags_path = Path(a.tags)
    if not tags_path.exists():
        print(f"没有 {tags_path.name}。先复制模板：")
        print("  Copy-Item data\\tags.example.json data\\tags.json")
        return 2

    g = load(HERE / "data" / a.graph)
    nodes = {nid: {"title": t} for nid, t in g.titles.items()}
    raw = read_tags(tags_path)

    unknown: list[tuple[str, str]] = []
    by_tag: dict[str, list[tuple[str, str]]] = {}
    for tag, keys in raw.items():
        for key in keys:
            nid = resolve_tag_key(key, nodes)
            if nid is None:
                unknown.append((tag, key))
                continue
            by_tag.setdefault(tag, []).append((key, g.title(nid)))

    print(f"标签文件：{tags_path}")
    for tag in sorted(by_tag):
        print(f"\n【{tag}】{len(by_tag[tag])} 个节点 → 派生 {len(by_tag[tag]) * (len(by_tag[tag]) - 1) // 2} 条边")
        for key, title in by_tag[tag]:
            print(f"  {title}")
        if len(by_tag[tag]) > 12:
            print("  ⚠️ 超过 12 个，导出时会被整条丢弃")

    if unknown:
        print("\n认不出的键（不会生效）：")
        for tag, k in unknown:
            print(f"  【{tag}】{k}")
        return 1
    print("\n全部键都能对上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
