"""
引用记忆 — 文件引用信号沉淀

每次用户 @ 引用文件时记录事件。频率达阈值后沉淀为 L2"常读文件"。
供 @ 选择器置顶 + 未来主动召回。

设计原则：
- 这不是"文件管理"，是"注意力信号的沉淀"
- Claude Code 读完就忘，Educe 记得你读过什么
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("educe.reference_memory")

REFERENCE_LOG_PATH = Path(".educe/memory/reference_log.jsonl")
FREQUENT_THRESHOLD = 3  # 引用 N 次后沉淀为"常读文件"


def record_file_reference(file_path: str, context: str = "") -> None:
    """记录一次文件引用事件"""
    REFERENCE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "path": file_path,
        "ts": time.time(),
        "context": context[:100],
    }
    with open(REFERENCE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_frequent_files(top_n: int = 10) -> list[dict]:
    """返回频繁引用的文件列表（按次数排序）"""
    if not REFERENCE_LOG_PATH.exists():
        return []

    counts: dict[str, int] = {}
    last_context: dict[str, str] = {}

    for line in REFERENCE_LOG_PATH.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            path = entry["path"]
            counts[path] = counts.get(path, 0) + 1
            last_context[path] = entry.get("context", "")
        except Exception:
            pass

    results = []
    for path, count in sorted(counts.items(), key=lambda x: -x[1])[:top_n]:
        results.append({
            "path": path,
            "count": count,
            "is_frequent": count >= FREQUENT_THRESHOLD,
            "last_context": last_context.get(path, ""),
        })
    return results


def get_frequent_file_paths() -> list[str]:
    """返回超过频率阈值的文件路径列表（供选择器置顶）"""
    return [f["path"] for f in get_frequent_files() if f["is_frequent"]]
