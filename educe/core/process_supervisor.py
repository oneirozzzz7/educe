"""
Process Supervisor — Session-scoped 后台进程管理

设计原则：
- 模型无感知（继续写普通 shell 命令）
- 框架通过行为检测（5s内是否退出）判断前台/后台
- 后台进程有 TTL、session 绑定、并发上限
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("educe.process_supervisor")


@dataclass
class ProcessEntry:
    proc: asyncio.subprocess.Process
    cmd: str
    session_id: str
    started_at: float = field(default_factory=time.time)
    work_dir: str = ""
    max_ttl: float = 600.0  # 10 min

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.started_at) > self.max_ttl

    @property
    def is_alive(self) -> bool:
        return self.proc.returncode is None


class ProcessSupervisor:
    """管理 session 级别的后台进程"""

    MAX_PER_SESSION = 3
    GRACE_PERIOD = 5.0  # 5s 内退出视为正常命令
    MAX_TTL = 600       # 后台进程最长存活 10 分钟

    def __init__(self):
        self._processes: dict[int, ProcessEntry] = {}
        self._watchdog_task: asyncio.Task | None = None

    def start_watchdog(self):
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._ttl_watchdog())

    def register(self, proc: asyncio.subprocess.Process, cmd: str,
                 session_id: str, work_dir: str = "") -> ProcessEntry:
        entry = ProcessEntry(
            proc=proc, cmd=cmd, session_id=session_id, work_dir=work_dir
        )
        self._processes[proc.pid] = entry
        log.info("Registered background process PID=%d cmd=%s session=%s",
                 proc.pid, cmd[:60], session_id)
        return entry

    def is_full(self, session_id: str) -> bool:
        alive = [e for e in self._processes.values()
                 if e.session_id == session_id and e.is_alive]
        return len(alive) >= self.MAX_PER_SESSION

    def list_session(self, session_id: str) -> list[ProcessEntry]:
        return [e for e in self._processes.values()
                if e.session_id == session_id and e.is_alive]

    async def cleanup_session(self, session_id: str):
        """Session 结束时清理所有后台进程"""
        for pid, entry in list(self._processes.items()):
            if entry.session_id == session_id:
                await self._terminate(entry)
                del self._processes[pid]

    async def _terminate(self, entry: ProcessEntry):
        if not entry.is_alive:
            return
        try:
            entry.proc.terminate()
            await asyncio.wait_for(entry.proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            entry.proc.kill()
            await entry.proc.wait()
        log.info("Terminated PID=%d cmd=%s", entry.pid, entry.cmd[:40])

    async def _ttl_watchdog(self):
        """定期清理过期进程"""
        while True:
            await asyncio.sleep(30)
            for pid, entry in list(self._processes.items()):
                if entry.is_expired or not entry.is_alive:
                    if entry.is_alive:
                        await self._terminate(entry)
                    del self._processes[pid]
