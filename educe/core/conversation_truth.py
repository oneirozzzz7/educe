"""Conversation Truth — 单一数据源 + 投影重建

所有对话事实的唯一来源。messages 每轮从 truth 投影，不手动 append。
注入项（env/plan/situation/challenge）在 state 层，不在 records 里。
压缩 = 改 record 的 tier，配对组同进退。

解决的问题：
- messages 不再只增不减
- 压缩不再切碎 assistant/tool 配对
- 注入项不靠 content 前缀识别
- loop_ctx 影子数据问题消失（只有一个 truth）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


class RecordKind(str, Enum):
    USER_INPUT = "user_input"
    AGENT_TURN = "agent_turn"
    TOOL_RESULT = "tool_result"


class Tier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    FROZEN = "frozen"


@dataclass
class Record:
    """对话事实的原子单位。"""
    id: int
    kind: RecordKind
    role: Literal["user", "assistant"]
    content: str
    summary: Optional[str] = None
    round_idx: int = 0
    ts: float = field(default_factory=time.time)
    tier: Tier = Tier.HOT
    token_est: int = 0
    action_type: str = ""
    action_target: str = ""
    success: Optional[bool] = None
    dropped: bool = False


@dataclass
class InjectionState:
    """每轮投影时注入的状态快照。不在 records 里。"""
    env: str = ""
    pinned_plan: str = ""
    plan_protocol: str = ""
    situation: str = ""
    challenge: str = ""

    def render_suffix(self) -> str:
        blocks = []
        if self.env:
            blocks.append(self.env)
        if self.plan_protocol:
            blocks.append(f"<plan_protocol>\n{self.plan_protocol}\n</plan_protocol>")
        if self.pinned_plan:
            blocks.append(f"<current_plan>\n{self.pinned_plan}\n</current_plan>")
        if self.situation:
            blocks.append(self.situation)
        if self.challenge:
            blocks.append(self.challenge)
        return "\n\n".join(blocks)


def _estimate_tokens(text: str) -> int:
    return len(text) // 2


# ═══ 配对分组 ═══

def _group_records(records: list[Record]) -> list[list[Record]]:
    """把 assistant + 后续 tool_result 绑成一组。"""
    groups: list[list[Record]] = []
    i = 0
    active = [r for r in records if not r.dropped]
    while i < len(active):
        r = active[i]
        if r.kind == RecordKind.AGENT_TURN and r.action_type:
            # assistant with action → 找后续 result
            grp = [r]
            j = i + 1
            while j < len(active) and active[j].kind == RecordKind.TOOL_RESULT and active[j].round_idx == r.round_idx:
                grp.append(active[j])
                j += 1
            groups.append(grp)
            i = j
        else:
            groups.append([r])
            i += 1
    return groups


# ═══ Conversation Truth ═══

HOT_TOKEN_BUDGET = 8000
PROTECTED_ROUNDS = 3


class ConversationTruth:
    """对话事实的唯一来源。"""

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.records: list[Record] = []
        self.state = InjectionState()
        self._next_id = 0
        self.round_idx = 0

    def _alloc_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # ── 写入接口 ──

    def add_user(self, content: str):
        self.records.append(Record(
            id=self._alloc_id(), kind=RecordKind.USER_INPUT,
            role="user", content=content, round_idx=self.round_idx,
            token_est=_estimate_tokens(content),
        ))

    def add_agent(self, content: str, action_type: str = "", action_target: str = ""):
        self.records.append(Record(
            id=self._alloc_id(), kind=RecordKind.AGENT_TURN,
            role="assistant", content=content, round_idx=self.round_idx,
            token_est=_estimate_tokens(content),
            action_type=action_type, action_target=action_target,
        ))

    def add_tool_result(self, content: str, success: bool = True, action_type: str = ""):
        self.records.append(Record(
            id=self._alloc_id(), kind=RecordKind.TOOL_RESULT,
            role="user", content=content, round_idx=self.round_idx,
            token_est=_estimate_tokens(content),
            action_type=action_type, success=success,
        ))

    # ── 投影：truth → messages ──

    def project(self) -> list[dict]:
        """每轮调用，从 truth 重建 messages。唯一的 messages 出口。"""
        msgs: list[dict] = []

        # Slot 0: system prompt + 动态 state
        sys_content = self.system_prompt
        suffix = self.state.render_suffix()
        if suffix:
            sys_content = f"{sys_content}\n\n{suffix}"
        msgs.append({"role": "system", "content": sys_content})

        # Slot 1+: 对话历史按 tier 投影
        for r in self.records:
            m = self._project_record(r)
            if m:
                msgs.append(m)

        return msgs

    def _project_record(self, r: Record) -> Optional[dict]:
        if r.tier == Tier.FROZEN:
            # Frozen：只留一行指纹
            if r.kind == RecordKind.TOOL_RESULT:
                return None
            return {"role": r.role, "content": r.summary or f"[round {r.round_idx} elided]"}

        if r.tier == Tier.WARM:
            if r.kind == RecordKind.TOOL_RESULT:
                return None  # warm 的 tool result 已并入 agent 摘要
            return {"role": r.role, "content": r.summary or r.content[:200]}

        # HOT：完整
        return {"role": r.role, "content": r.content}

    # ── 压缩：改 tier，不切 list ──

    def compact(self):
        """从最老的 record 开始降级，直到 HOT token 预算满足。"""
        groups = _group_records(self.records)

        hot_tokens = sum(
            sum(r.token_est for r in g)
            for g in groups if all(r.tier == Tier.HOT for r in g)
        )

        if hot_tokens <= HOT_TOKEN_BUDGET:
            return

        for g in groups:
            if hot_tokens <= HOT_TOKEN_BUDGET:
                break
            if not all(r.tier == Tier.HOT for r in g):
                continue
            if g[0].round_idx >= self.round_idx - PROTECTED_ROUNDS:
                continue

            # 整组降级 HOT → WARM
            group_tokens = sum(r.token_est for r in g)
            summary = self._summarize_group(g)
            for r in g:
                r.tier = Tier.WARM
                r.summary = summary if r is g[0] else None
            hot_tokens -= group_tokens

        # WARM 超限进一步降级
        warm_tokens = sum(
            r.token_est for r in self.records if r.tier == Tier.WARM and r.summary
        )
        if warm_tokens > 3000:
            for g in groups:
                if warm_tokens <= 3000:
                    break
                if not all(r.tier == Tier.WARM for r in g):
                    continue
                for r in g:
                    r.tier = Tier.FROZEN
                    if r.summary:
                        warm_tokens -= r.token_est

    def _summarize_group(self, group: list[Record]) -> str:
        """机械摘要（不调 LLM）。"""
        first = group[0]
        if first.action_type:
            target = first.action_target[:50]
            results = [r for r in group[1:] if r.kind == RecordKind.TOOL_RESULT]
            if results:
                status = "✓" if all(r.success is True for r in results) else "✗"
            else:
                status = "?"
            return f"[R{first.round_idx}] {status} {first.action_type}({target})"
        return f"[R{first.round_idx}] {first.content[:80]}"

    # ── 辅助 ──

    @property
    def action_history(self) -> list[dict]:
        """所有执行过的 action 记录（不受压缩影响）。"""
        return [
            {"type": r.action_type, "target": r.action_target, "round": r.round_idx}
            for r in self.records
            if r.kind == RecordKind.AGENT_TURN and r.action_type
        ]

    @property
    def hot_records(self) -> list[Record]:
        return [r for r in self.records if r.tier == Tier.HOT]

    def get_findings_summary(self) -> str:
        """提取关键路径和发现用于跨轮摘要。"""
        paths = []
        for r in self.records:
            if r.action_target and r.action_target.startswith("/"):
                if r.action_target not in paths:
                    paths.append(r.action_target)
        return ", ".join(paths[-5:]) if paths else ""
