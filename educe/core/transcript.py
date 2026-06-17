"""
TaskTranscript — 任务过程记录
模型和用户看到同一份 Transcript：模型知道自己在哪，用户也知道。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TranscriptEntry:
    phase: str
    role: str  # "system" | "model" | "user"
    content: str
    elapsed: float = 0.0
    timestamp: float = field(default_factory=time.time)


class TaskTranscript:
    PHASES = ["analyze", "plan", "build", "verify"]
    PHASE_LABELS = {"analyze": "分析", "plan": "规划", "build": "构建", "verify": "验证"}

    def __init__(self, user_request: str):
        self.user_request = user_request
        self.current_phase = "analyze"
        self.entries: list[TranscriptEntry] = []
        self.plan_summary = ""
        self.step_plan: list[str] = []
        self.current_step = 0
        self.on_update: Callable[[dict], None] | None = None

    def add(self, phase: str, role: str, content: str, elapsed: float = 0.0) -> None:
        entry = TranscriptEntry(phase=phase, role=role, content=content, elapsed=elapsed)
        self.entries.append(entry)
        self.current_phase = phase
        if self.on_update:
            self.on_update(self.render_event(entry))

    def render_for_model(self) -> str:
        lines = ["═══ 任务 Transcript ═══"]
        lines.append("任务: {}".format(self.user_request[:100]))
        if self.plan_summary:
            lines.append("方案: {}".format(self.plan_summary))

        # Phase progress bar
        phase_parts = []
        for p in self.PHASES:
            label = self.PHASE_LABELS[p]
            completed_phases = {e.phase for e in self.entries}
            if p == self.current_phase:
                if p == "build" and self.step_plan:
                    phase_parts.append("[{}: 步骤{}/{}]".format(label, self.current_step, len(self.step_plan)))
                else:
                    phase_parts.append("[{}]".format(label))
            elif p in completed_phases:
                phase_parts.append("{}✓".format(label))
            else:
                phase_parts.append(label)
        lines.append("阶段: {}".format(" → ".join(phase_parts)))

        # Completed entries
        if self.entries:
            lines.append("")
            lines.append("已完成:")
            for entry in self.entries:
                label = self.PHASE_LABELS.get(entry.phase, entry.phase)
                elapsed_str = " ({:.1f}s)".format(entry.elapsed) if entry.elapsed > 0 else ""
                if entry.phase == "build" and "步骤" in entry.content:
                    lines.append("  [{}] {}{}".format(label, entry.content, elapsed_str))
                else:
                    lines.append("  [{}] {}{}".format(label, entry.content, elapsed_str))

        # Current + next
        if self.current_phase == "build" and self.step_plan and self.current_step > 0:
            if self.current_step <= len(self.step_plan):
                lines.append("")
                lines.append("当前: 构建·步骤{} — {}".format(
                    self.current_step, self.step_plan[self.current_step - 1][:50]))
            remaining = self.step_plan[self.current_step:]
            if remaining:
                lines.append("后续: {}".format(", ".join(s[:30] for s in remaining[:3])))

        lines.append("═══════════════════════")
        return "\n".join(lines)

    def render_event(self, entry: TranscriptEntry) -> dict:
        return {
            "event": "transcript",
            "phase": entry.phase,
            "role": entry.role,
            "content": entry.content,
            "elapsed": round(entry.elapsed, 1),
            "step": self.current_step,
            "total_steps": len(self.step_plan),
            "step_plan": [s[:50] for s in self.step_plan] if self.step_plan else [],
        }
