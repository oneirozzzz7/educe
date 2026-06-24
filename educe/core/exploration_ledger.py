"""
ExplorationLedger — 追踪模型探索行为的统计信息

提供 action 历史记录和文件读取追踪，供 Situation 态势感知消费。
框架不基于这些统计做决策——事实注入给模型，由模型自行判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExplorationLedger:
    """追踪 action_loop 中模型的探索行为"""
    files_read: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    symbols_found: set[str] = field(default_factory=set)
    actions_history: list[dict] = field(default_factory=list)
    has_edit_action: bool = False

    def record(self, action_type: str, params: str, result_output: str, success: bool):
        self.actions_history.append({
            "type": action_type, "params": params[:200], "success": success
        })
        if action_type in ("edit_file", "write_file") and success:
            self.has_edit_action = True

        if action_type == "read_lines" and success:
            self._track_read_range(params, result_output)
        elif action_type == "search_in_file" and success:
            self._track_search(result_output)

    def _track_read_range(self, params: str, output: str):
        """从 read_lines 结果中提取文件路径和行范围"""
        import re
        m = re.search(r'文件:\s*(\S+)\s*\(第(\d+)-(\d+)行', output)
        if m:
            path = m.group(1)
            start, end = int(m.group(2)), int(m.group(3))
            self.files_read.setdefault(path, []).append((start, end))

    def _track_search(self, output: str):
        """从 search_in_file 结果中提取符号"""
        import re
        for m in re.finditer(r'→\s*\d+\s*\|\s*(.+)', output):
            line = m.group(1).strip()[:40]
            self.symbols_found.add(line)

    @property
    def turns_without_edit(self) -> int:
        """返回从最后一次 edit/write 以来经过的 action 数"""
        if self.has_edit_action:
            for i, a in enumerate(reversed(self.actions_history)):
                if a["type"] in ("edit_file", "write_file") and a["success"]:
                    return i
        return len(self.actions_history)
