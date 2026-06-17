"""
ExplorationLedger — 追踪模型探索行为的信息饱和度

设计原则（Opus 4.8 讨论）：
- 不用轮次（rounds）做判断，用信息增益
- 模型反复读已读区域 = 高冗余 = 该 nudge
- 模型读新内容 = 低冗余 = 别打断
- nudge 不是阻止 action，而是注入"你已知什么"的镜子
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExplorationLedger:
    """追踪 action_loop 中模型的探索行为"""
    files_read: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    symbols_found: set[str] = field(default_factory=set)
    actions_history: list[dict] = field(default_factory=list)
    nudge_count: int = 0
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
        # 从输出中提取 "文件: xxx (第M-N行)"
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

    def should_nudge(self, window: int = 3) -> bool:
        """检测是否该注入探索反射"""
        if self.has_edit_action:
            return False
        recent = self.actions_history[-window:]
        if len(recent) < window:
            return False

        # 条件0：轮次过多无修改 → 强制 nudge（弱模型探索焦虑）
        total_actions = len(self.actions_history)
        if total_actions >= 8 and not self.has_edit_action:
            return True

        # 条件1：最近 window 个 action 全是读类操作（无修改意图）
        read_types = {"read_lines", "read_file", "read_dir", "search_in_file", "use_tool"}
        if not all(a["type"] in read_types for a in recent):
            return False

        # 条件2：检测冗余——最近读的区域和之前有显著重叠
        if self._redundancy_score() > 0.6:
            return True

        # 条件3：连续在同一个文件读不同段（已定位到目标，在犹豫）
        recent_reads = [a for a in recent if a["type"] == "read_lines"]
        if len(recent_reads) >= 2:
            paths = set()
            for a in recent_reads:
                first_line = a["params"].split("\n")[0] if "\n" in a["params"] else ""
                if first_line:
                    paths.add(first_line)
            if len(paths) == 1:
                return True

        return False

    def _redundancy_score(self) -> float:
        """计算读取区域的重叠度"""
        if not self.files_read:
            return 0.0

        total_new = 0
        total_overlap = 0

        for path, ranges in self.files_read.items():
            if len(ranges) < 2:
                continue
            # 计算最后一个 range 和之前 ranges 的重叠
            last = ranges[-1]
            prev_coverage = set()
            for r in ranges[:-1]:
                prev_coverage.update(range(r[0], r[1] + 1))

            last_lines = set(range(last[0], last[1] + 1))
            overlap = last_lines & prev_coverage
            new_lines = last_lines - prev_coverage

            total_overlap += len(overlap)
            total_new += len(new_lines)

        total = total_overlap + total_new
        return total_overlap / total if total > 0 else 0.0

    def build_reflection(self) -> str:
        """构建收敛提示——第一次温和引导，第二次强制填空模板"""
        parts = ["[系统观察] 你已经检查了以下内容："]

        for path, ranges in self.files_read.items():
            merged = self._merge_ranges(ranges)
            range_desc = ", ".join(f"第{s}-{e}行" for s, e in merged[:5])
            parts.append(f"- {path}: {range_desc}")

        if self.symbols_found:
            symbols = list(self.symbols_found)[:8]
            parts.append(f"- 找到的关键符号: {', '.join(symbols)}")

        parts.append("")

        self.nudge_count += 1

        if self.nudge_count <= 1:
            # 第一次：温和引导
            parts.append("信息已经足够。请直接执行修改（用 edit_file），或说明你还缺什么。")
        else:
            # 第二次及以后：强制填空模板，剥夺继续探索的选项
            parts.append("⚠️ 不允许再执行 read/search 操作。请直接填写以下模板执行修改：")
            parts.append("")
            parts.append("```edit_file")
            # 用已知的第一个文件路径作为提示
            first_file = next(iter(self.files_read.keys()), "目标文件路径")
            parts.append(f"path: {first_file}")
            parts.append("<<<<<<< OLD")
            parts.append("（粘贴你要替换的原文，从你已读的内容中选取）")
            parts.append("=======")
            parts.append("（写入修改后的新代码）")
            parts.append(">>>>>>> NEW")
            parts.append("```")

        return "\n".join(parts)

    def _merge_ranges(self, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """合并重叠的行号范围"""
        if not ranges:
            return []
        sorted_r = sorted(ranges)
        merged = [sorted_r[0]]
        for start, end in sorted_r[1:]:
            if start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def should_restrict_actions(self, max_rounds: int, current_round: int) -> bool:
        """安全网：nudge 反复失败后限制 read 类 action"""
        return (
            current_round > 0.75 * max_rounds
            and self.nudge_count >= 2
            and not self.has_edit_action
        )
