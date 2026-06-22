"""
引用记忆 — 文件引用信号沉淀

每次用户 @ 引用文件时记录事件。频率达阈值后沉淀为 L2"常读文件"。
供 @ 选择器置顶 + 未来主动召回。

设计原则：
- 全局 vs 项目分层：路径自动判定（项目内/外）
- 遗忘衰减：热度 = hits * exp(-Δt/τ)，读时计算
- 不硬删除：衰减到不可见，但记录保留
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

log = logging.getLogger("educe.reference_memory")

REFERENCE_LOG_PATH = Path(".educe/memory/reference_log.jsonl")
GLOBAL_REFERENCE_LOG_PATH = Path.home() / ".educe" / "global" / "reference_log.jsonl"
FREQUENT_THRESHOLD = 3  # 引用 N 次后沉淀为"常读文件"
DECAY_TAU_DAYS = 14.0   # 半衰期约 10 天（τ=14 → 50% at ~10 days）


def _get_project_root() -> Path:
    try:
        import educe
        return Path(educe.__file__).parent.parent
    except Exception:
        return Path.cwd()


def _is_project_file(file_path: str) -> bool:
    """判断文件是否属于当前项目"""
    abs_path = Path(file_path).resolve() if Path(file_path).is_absolute() else (_get_project_root() / file_path).resolve()
    project_root = _get_project_root().resolve()
    try:
        abs_path.relative_to(project_root)
        return True
    except ValueError:
        return False


def record_file_reference(file_path: str, context: str = "") -> None:
    """记录一次文件引用事件（自动分层：项目/全局）"""
    is_project = _is_project_file(file_path)
    log_path = REFERENCE_LOG_PATH if is_project else GLOBAL_REFERENCE_LOG_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "path": file_path,
        "ts": time.time(),
        "context": context[:100],
        "scope": "project" if is_project else "global",
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception as e:
                log.debug("suppressed: %s", e)
    return entries


def _compute_scores(entries: list[dict]) -> list[dict]:
    """计算带衰减的热度分数"""
    now = time.time()
    counts: dict[str, list[float]] = {}
    last_context: dict[str, str] = {}

    for e in entries:
        path = e["path"]
        counts.setdefault(path, []).append(e.get("ts", 0))
        last_context[path] = e.get("context", "")

    results = []
    for path, timestamps in counts.items():
        score = 0.0
        for ts in timestamps:
            days_ago = (now - ts) / 86400
            score += math.exp(-days_ago / DECAY_TAU_DAYS)
        results.append({
            "path": path,
            "raw_count": len(timestamps),
            "score": round(score, 3),
            "is_frequent": score >= FREQUENT_THRESHOLD * 0.5,  # 衰减后阈值降低
            "last_context": last_context.get(path, ""),
        })

    results.sort(key=lambda x: -x["score"])
    return results


def get_frequent_files(top_n: int = 10, include_global: bool = True) -> list[dict]:
    """返回频繁引用的文件列表（项目+全局，按衰减热度排序）"""
    project_entries = _load_log(REFERENCE_LOG_PATH)
    results = _compute_scores(project_entries)

    if include_global:
        global_entries = _load_log(GLOBAL_REFERENCE_LOG_PATH)
        global_results = _compute_scores(global_entries)
        for g in global_results:
            g["scope"] = "global"
        for r in results:
            r["scope"] = "project"
        results = sorted(results + global_results, key=lambda x: -x["score"])

    return results[:top_n]


def get_frequent_file_paths() -> list[str]:
    """返回超过频率阈值的文件路径列表（供选择器置顶）"""
    return [f["path"] for f in get_frequent_files() if f["is_frequent"]]

