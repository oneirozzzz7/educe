"""
工具流式执行注册表 — 过程透明度基础设施

管理活跃工具调用的生命周期：
- tool_id 生成
- 进程/pump task 持有
- cancel 精确命中
- 后台移交

设计决策（Opus 4.8 讨论确认）：
- tool_id 由上层生成，贯穿整个调用生命周期
- dict[tool_id] 注册表 O(1) 定位
- cancel_event 让 pump 区分"正常 EOF"和"被取消"
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

log = logging.getLogger("educe.streaming")

# ═══ 配置加载 ═══

_CONFIG_CACHE: dict | None = None


def load_stream_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config_path = Path(__file__).parent.parent / "config" / "tool_stream.yaml"
    defaults = {
        "shell": {
            "grace_period_ms": 5000,
            "stream_threshold_ms": 300,
            "timeout_s": 300,
            "max_line_bytes": 4096,
            "max_output_bytes": 512000,
        },
        "write_file": {"max_diff_lines": 5000},
        "frontend": {
            "max_render_lines": 200,
            "flush_interval_ms": 50,
            "handle_cr": True,
        },
        "cancel": {"terminate_grace_s": 3},
    }

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            for section, vals in loaded.items():
                if section in defaults and isinstance(vals, dict):
                    defaults[section].update(vals)
                else:
                    defaults[section] = vals
        except Exception as e:
            log.warning("Failed to load tool_stream.yaml: %s", e)

    _CONFIG_CACHE = defaults
    return defaults


def get_config(section: str, key: str, default: Any = None) -> Any:
    cfg = load_stream_config()
    return cfg.get(section, {}).get(key, default)


# ═══ tool_id 生成 ═══

def gen_tool_id() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


# ═══ ToolHandle — 单个活跃工具的句柄 ═══

@dataclass
class ToolHandle:
    tool_id: str
    tool: str
    proc: asyncio.subprocess.Process | None = None
    pumps: list[asyncio.Task] = field(default_factory=list)
    wait_task: asyncio.Task | None = None
    started_at: float = field(default_factory=time.monotonic)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    meta: dict = field(default_factory=dict)


# ═══ StreamingRegistry — 活跃工具注册表 ═══

class StreamingRegistry:
    def __init__(self):
        self._active: dict[str, ToolHandle] = {}

    def register(self, handle: ToolHandle) -> None:
        self._active[handle.tool_id] = handle

    def get(self, tool_id: str) -> ToolHandle | None:
        return self._active.get(tool_id)

    def unregister(self, tool_id: str) -> ToolHandle | None:
        return self._active.pop(tool_id, None)

    def active_count(self) -> int:
        return len(self._active)

    def list_active(self) -> list[ToolHandle]:
        return list(self._active.values())

    async def cancel(self, tool_id: str) -> bool:
        """取消正在执行的工具。返回是否成功取消。"""
        h = self._active.get(tool_id)
        if not h:
            return False

        h.cancel_event.set()

        if h.proc and h.proc.returncode is None:
            h.proc.terminate()
            grace = get_config("cancel", "terminate_grace_s", 3)
            try:
                await asyncio.wait_for(h.proc.wait(), timeout=grace)
            except asyncio.TimeoutError:
                h.proc.kill()
                await h.proc.wait()

        for t in h.pumps:
            if not t.done():
                t.cancel()

        self.unregister(tool_id)
        return True

    async def cancel_all(self) -> int:
        """取消所有活跃工具。返回取消数量。"""
        ids = list(self._active.keys())
        count = 0
        for tid in ids:
            if await self.cancel(tid):
                count += 1
        return count
