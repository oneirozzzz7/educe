"""Loop Context — 三层滑动窗口 + Pinned Plan

管理 action loop 的 messages 上下文：
- Hot: 最近 5 轮完整保留
- Warm: 5~20 轮单行摘要（机械模板，不调 LLM）
- Frozen: 20+ 轮批量摘要

确保 1000+ 轮会话 token 不爆炸。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from educe.core.plan_parser import Plan


# ═══ 配置 ═══

HOT_TURNS = 5
WARM_TURNS = 15
FROZEN_BLOCK_SIZE = 20
TOKEN_SOFT_LIMIT = 20000
TOKEN_HARD_LIMIT = 25000

PIN_LABEL = "📌 当前计划（实时更新，请基于此继续）："


# ═══ 数据结构 ═══

@dataclass
class TurnRecord:
    """一轮完整记录：assistant output + action result"""
    round_idx: int
    assistant_raw: str
    action_type: str = ""
    action_params: str = ""
    result_output: str = ""
    success: bool = True


@dataclass
class FrozenBlock:
    """远期压缩块"""
    turn_range: tuple[int, int] = (0, 0)
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class LoopContext:
    """管理 action loop 的 messages 上下文窗口。"""

    def __init__(self):
        self.frozen: list[FrozenBlock] = []
        self.warm: list[str] = []
        self.hot: list[TurnRecord] = []
        self.current_plan: Optional[Plan] = None

    def add_turn(self, record: TurnRecord):
        """新一轮结束后调用。"""
        self.hot.append(record)
        self._slide_windows()

    def _slide_windows(self):
        """维护 hot → warm → frozen 滑动。"""
        while len(self.hot) > HOT_TURNS:
            old = self.hot.pop(0)
            self.warm.append(_summarize_turn(old))

        if len(self.warm) >= FROZEN_BLOCK_SIZE + WARM_TURNS:
            batch = self.warm[:FROZEN_BLOCK_SIZE]
            self.frozen.append(_freeze_block(batch))
            self.warm = self.warm[FROZEN_BLOCK_SIZE:]

    def build_messages(self, system_prompt: str, user_input: str,
                       situation_text: str = "") -> list[dict]:
        """构造本轮 LLM 调用的 messages。"""
        msgs: list[dict] = [{"role": "system", "content": system_prompt}]

        # 用户原始输入
        msgs.append({"role": "user", "content": user_input})

        # Frozen 历史
        for blk in self.frozen:
            msgs.append({"role": "user", "content":
                f"[历史摘要 T{blk.turn_range[0]}-T{blk.turn_range[1]}]\n{blk.summary}"})

        # Warm 历史
        if self.warm:
            warm_text = "\n".join(self.warm[-WARM_TURNS:])
            msgs.append({"role": "user", "content": f"[近期操作记录]\n{warm_text}"})

        # Hot 历史（完整 assistant + result 对）
        for turn in self.hot:
            msgs.append({"role": "assistant", "content": turn.assistant_raw})
            if turn.result_output:
                msgs.append({"role": "user", "content":
                    f"[系统] {'✓' if turn.success else '✗'} {turn.action_type} 结果：{turn.result_output[:500]}"})

        # Pinned Plan（倒数第二位）
        if self.current_plan:
            msgs.append({"role": "user", "content": f"{PIN_LABEL}\n{self.current_plan.to_block()}"})

        # Situation（最后位置，离模型决策最近）
        if situation_text:
            msgs.append({"role": "user", "content": situation_text})

        return msgs

    def update_plan(self, new_plan: Optional[Plan]):
        """模型产出新 plan 时调用。None = 沿用旧的。"""
        if new_plan is not None:
            self.current_plan = new_plan

    def is_done(self) -> bool:
        """模型是否声明任务完成。"""
        return self.current_plan is not None and self.current_plan.status == "done"

    def compress_if_needed(self):
        """检查 token 预算，触发压缩。"""
        total = self._estimate_tokens()
        if total > TOKEN_HARD_LIMIT:
            self._aggressive_compress()
        elif total > TOKEN_SOFT_LIMIT:
            self._mechanical_compress()

    def _estimate_tokens(self) -> int:
        """粗估 token 数（中文约 1.5 char/token，取平均 2 char/token）。"""
        total_chars = 0
        for blk in self.frozen:
            total_chars += len(blk.summary)
        total_chars += sum(len(s) for s in self.warm)
        for turn in self.hot:
            total_chars += len(turn.assistant_raw) + len(turn.result_output)
        if self.current_plan:
            total_chars += len(self.current_plan.to_block())
        return total_chars // 2

    def _mechanical_compress(self):
        """软压缩：plan 去重 + 加速 warm→frozen 滑动。"""
        if self.current_plan:
            self.current_plan.compress()

        while len(self.warm) > WARM_TURNS:
            batch = self.warm[:FROZEN_BLOCK_SIZE]
            if len(batch) < 5:
                break
            self.frozen.append(_freeze_block(batch))
            self.warm = self.warm[len(batch):]

    def _aggressive_compress(self):
        """硬压缩：frozen 块截断 + hot result 截断。"""
        self._mechanical_compress()

        for blk in self.frozen:
            if len(blk.summary) > 200:
                blk.summary = blk.summary[:200] + "..."

        for turn in self.hot:
            if len(turn.result_output) > 300:
                turn.result_output = turn.result_output[:200] + f"...[截断,原{len(turn.result_output)}字]"


# ═══ 辅助函数 ═══

def _summarize_turn(turn: TurnRecord) -> str:
    """机械模板生成单轮摘要。不调 LLM。"""
    params_brief = turn.action_params[:40] if turn.action_params else ""
    status = "✓" if turn.success else "✗"
    out_brief = turn.result_output[:100] if turn.result_output else ""
    return f"[T{turn.round_idx}] {status} {turn.action_type}({params_brief}) → {out_brief}"


def _freeze_block(warm_items: list[str]) -> FrozenBlock:
    """将一批 warm 摘要合并为 frozen 块。"""
    first_turn = 0
    last_turn = 0
    if warm_items:
        m = re.match(r"\[T(\d+)\]", warm_items[0])
        if m:
            first_turn = int(m.group(1))
        m2 = re.match(r"\[T(\d+)\]", warm_items[-1])
        if m2:
            last_turn = int(m2.group(1))

    artifacts = []
    errors = []
    for item in warm_items:
        if "write_file" in item or "edit_file" in item:
            m = re.search(r"\(([^)]+)\)", item)
            if m:
                artifacts.append(m.group(1)[:60])
        if "✗" in item:
            errors.append(item[:80])

    summary = "\n".join(warm_items)
    if len(summary) > 500:
        summary = summary[:500] + f"...[共{len(warm_items)}条]"

    return FrozenBlock(
        turn_range=(first_turn, last_turn),
        summary=summary,
        artifacts=artifacts,
        errors=errors,
    )
