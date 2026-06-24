"""Effect Stream — 框架的自知

框架是所有 I/O 的唯一通道。每次 I/O 同步产生一条 Effect，
形成完整的会话感知流。框架不"观测"自己——它在做事时声明。

Situation = 从 Effect 流增量折叠出的实时态势快照。
"""

import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Effect:
    kind: str           # model | file_read | file_write | file_edit | shell | user_in | ui_push
    intent: dict        # 输入：我要做什么
    outcome: dict       # 输出：实际发生了什么
    ts: float = field(default_factory=time.time)
    session_id: str = ""
    round_idx: int = -1


@dataclass
class Situation:
    """框架的实时态势感知——从 Effect 流增量计算。全是事实，零判断。"""

    rounds_total: int = 0
    rounds_since_user_msg: int = 0
    text_replies: int = 0
    model_calls: int = 0
    files_written: list = field(default_factory=list)   # [{path, size, mode, round}]
    files_read: list = field(default_factory=list)      # [{path, round}]
    shells_run: list = field(default_factory=list)      # [{cmd, exit_code, round}]
    repeated_reads: dict = field(default_factory=dict)  # {path: count}
    consecutive_failures: int = 0
    last_user_msg: str = ""
    last_user_msg_round: int = 0

    def to_dict(self) -> dict:
        return {
            "rounds_total": self.rounds_total,
            "rounds_since_user_msg": self.rounds_since_user_msg,
            "text_replies": self.text_replies,
            "model_calls": self.model_calls,
            "files_written": self.files_written,
            "shells_run": self.shells_run[-5:],
            "repeated_reads": {k: v for k, v in self.repeated_reads.items() if v >= 2},
            "consecutive_failures": self.consecutive_failures,
            "last_user_msg": self.last_user_msg[:100],
        }

    def render_for_model(self) -> str:
        """序列化为模型可读的态势描述。第一轮不注入。"""
        if self.rounds_total <= 1:
            return ""

        lines = [f"turn: {self.rounds_total}"]
        lines.append(f'task: "{self.last_user_msg[:100]}" (since turn {self.last_user_msg_round})')
        lines.append(f"your_text_replies: {self.text_replies}")

        if self.repeated_reads:
            reps = {k: v for k, v in self.repeated_reads.items() if v >= 2}
            if reps:
                lines.append("repeated_reads:")
                for p, c in reps.items():
                    lines.append(f"  - {p}: {c} times")

        if self.files_written:
            lines.append("files_produced:")
            for f in self.files_written:
                lines.append(f"  - {f['path']} ({f['size']}B, {f['mode']})")

        if self.consecutive_failures > 0:
            lines.append(f"consecutive_command_failures: {self.consecutive_failures}")

        return "<situation>\n" + "\n".join(lines) + "\n</situation>"


class EffectStream:
    """框架的感知流。所有 I/O 同步写入，态势增量更新。"""

    def __init__(self):
        self._effects: list[Effect] = []
        self._session_id: str = ""
        self._round_idx: int = 0
        self.situation = Situation()

    def set_context(self, session_id: str, round_idx: int = 0):
        self._session_id = session_id
        self._round_idx = round_idx

    def set_round(self, round_idx: int):
        self._round_idx = round_idx
        self.situation.rounds_total = round_idx + 1
        self.situation.rounds_since_user_msg = round_idx - self.situation.last_user_msg_round

    def emit(self, kind: str, intent: dict, outcome: dict) -> Effect:
        e = Effect(
            kind=kind,
            intent=intent,
            outcome=outcome,
            session_id=self._session_id,
            round_idx=self._round_idx,
        )
        self._effects.append(e)
        self._update_situation(e)
        return e

    def _update_situation(self, e: Effect):
        """增量更新态势。每个 Effect 到来时 O(1) 更新。"""
        s = self.situation

        if e.kind == "user_in":
            s.last_user_msg = e.outcome.get("message", "")
            s.last_user_msg_round = e.round_idx
            s.rounds_since_user_msg = 0
            s.text_replies = 0

        elif e.kind == "model":
            s.model_calls += 1
            if e.outcome.get("has_reply"):
                s.text_replies += 1

        elif e.kind == "file_write":
            if e.outcome.get("success"):
                s.files_written.append({
                    "path": Path(e.outcome.get("path", "")).name,
                    "size": e.outcome.get("size", 0),
                    "mode": e.outcome.get("mode", "created"),
                    "round": e.round_idx,
                })

        elif e.kind == "file_read":
            path = e.intent.get("path", "")
            s.files_read.append({"path": path, "round": e.round_idx})
            s.repeated_reads[path] = s.repeated_reads.get(path, 0) + 1

        elif e.kind == "shell":
            cmd = e.intent.get("cmd", "")[:60]
            exit_code = e.outcome.get("exit_code", 0)
            s.shells_run.append({"cmd": cmd, "exit_code": exit_code, "round": e.round_idx})
            if exit_code != 0:
                s.consecutive_failures += 1
            else:
                s.consecutive_failures = 0

    def query(self, kind: Optional[str] = None, round_idx: Optional[int] = None) -> list[Effect]:
        results = self._effects
        if kind:
            results = [e for e in results if e.kind == kind]
        if round_idx is not None:
            results = [e for e in results if e.round_idx == round_idx]
        return results

    def artifacts(self) -> list[dict]:
        """所有 file_write/file_edit 产生的文件产物。"""
        arts = []
        seen = set()
        for e in self._effects:
            if e.kind in ("file_write", "file_edit"):
                path = e.outcome.get("path", "")
                if path and path not in seen and e.outcome.get("success"):
                    seen.add(path)
                    arts.append({
                        "path": path,
                        "filename": Path(path).name,
                        "size": e.outcome.get("size", 0),
                        "mode": e.outcome.get("mode", "created"),
                        "round": e.round_idx,
                    })
        return arts

    def summary(self) -> dict:
        by_kind = {}
        for e in self._effects:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        return {
            "total": len(self._effects),
            "by_kind": by_kind,
            "artifacts_count": len(self.artifacts()),
            "rounds": self._round_idx,
        }

    @property
    def effects(self) -> list[Effect]:
        return self._effects

    def to_dicts(self, last_n: int = 20) -> list[dict]:
        return [asdict(e) for e in self._effects[-last_n:]]

