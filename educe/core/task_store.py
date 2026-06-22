"""
任务持久化——保存/加载任务历史和产出物
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger("educe.core.task_store")


class TaskStore:
    def __init__(self, storage_dir: str = ".educe/tasks"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_task(self, task_id: str, data: dict) -> Path:
        path = self.storage_dir / f"{task_id}.json"
        data["saved_at"] = time.time()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return path

    def load_task(self, task_id: str) -> dict | None:
        path = self.storage_dir / f"{task_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_tasks(self, limit: int = 20) -> list[dict]:
        tasks = []
        for path in sorted(self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text())
                tasks.append({
                    "id": path.stem,
                    "request": data.get("request", "")[:60],
                    "project_type": data.get("project_type", ""),
                    "created_at": data.get("created_at", 0),
                    "file_count": data.get("file_count", 0),
                })
            except Exception as e:
                log.debug("suppressed: %s", e)
            if len(tasks) >= limit:
                break
        return tasks

    def save_from_context(self, task_id: str, context, response: str = "") -> Path:
        """从WorkContext保存任务——支持文本回复和代码任务"""
        has_code = bool(context.artifacts.get("engineer_output"))
        data = {
            "id": task_id,
            "request": context.user_request,
            "response": response[:10000] if response else "",
            "type": "code" if has_code else "text",
            "project_type": context.artifacts.get("project_type", ""),
            "output_dir": context.artifacts.get("output_dir", ""),
            "file_count": len(context.artifacts.get("code_files", [])),
            "code_files": context.artifacts.get("code_files", []),
            "engineer_output": context.artifacts.get("engineer_output", "")[:10000],
            "created_at": time.time(),
        }
        return self.save_task(task_id, data)
