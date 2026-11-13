"""查询日志：本地记录"你问过什么"，供导出器生成共现边。

只写自己的 data/queries.jsonl（已 gitignore），不碰记忆库。
坏行、坏编码、坏类型一律跳过——日志坏了不该让导出失败。
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def log_query(
    path: Path | None,
    graph: str,
    src: str,
    dst: str,
    paths,
    default: bool = True,
) -> bool:
    """记一笔。返回是否写成功；`--no-log` 时 path 传 None。"""
    if path is None:
        return False
    row = {
        "ts": int(time.time()),
        "graph": graph,
        "src": src,
        "dst": dst,
        "found": bool(paths),
        "hops": [len(p.nodes) - 1 for p in paths],
        "default": bool(default),  # 只有默认开关下的查询才算"注意力"
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False  # 记不上不影响查询本身


def read_queries(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 坏行跳过，不连累整份日志
                if not isinstance(row, dict):
                    continue
                if not isinstance(row.get("src"), str) or not isinstance(row.get("dst"), str):
                    continue  # 类型不对的一律不收，免得后面 unhashable
                out.append(row)
    except OSError:
        return []
    return out
