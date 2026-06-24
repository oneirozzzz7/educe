"""Runtime Facts — 框架的镜子

每轮 LLM 调用前，聚合当前会话的动作账本，以 <runtime_facts> 格式注入 prompt。
让模型看到自己的飞行数据（重复、停滞、未回复），自行纠正。

设计原则：只陈述事实（计数/时序），不做判断（不说"你应该停"）。
"""

from dataclasses import dataclass, field


@dataclass
class RuntimeFacts:
    """会话内的实时飞行数据聚合器。"""

    task_anchor: str = ""
    turn: int = 0
    assistant_replies: int = 0
    actions: list = field(default_factory=list)  # [(type, params_normalized, round)]
    blocked_actions: list = field(default_factory=list)  # [(type, params_short, round)]

    def set_anchor(self, user_input: str):
        self.task_anchor = user_input
        self.turn = 0
        self.assistant_replies = 0
        self.actions = []
        self.blocked_actions = []

    def record_action(self, action_type: str, params: str, round_idx: int):
        normalized = self._normalize_params(action_type, params)
        self.actions.append((action_type, normalized, round_idx))

    def record_reply(self):
        self.assistant_replies += 1

    def record_blocked(self, action_type: str, params: str, round_idx: int):
        self.blocked_actions.append((action_type, params[:80], round_idx))

    def advance_turn(self):
        self.turn += 1

    def build_injection(self, env_observer=None) -> str:
        """生成 <runtime_facts> 注入文本。第一轮不注入。"""
        if self.turn <= 1:
            return ""

        lines = [f"turn: {self.turn}"]

        if self.task_anchor:
            lines.append(f'task_anchor: "{self.task_anchor[:100]}" (since turn 1)')

        lines.append(f"assistant_replies_since_anchor: {self.assistant_replies}")

        repeated = self._find_repeated()
        if repeated:
            lines.append("repeated_actions:")
            for (atype, params), count in repeated.items():
                lines.append(f"  - {atype}({params}): {count} times")

        if self.blocked_actions:
            last = self.blocked_actions[-1]
            lines.append(f'last_blocked: {last[0]}("{last[1]}") — BLOCKED by confirm (pending)')

        if env_observer:
            obs_facts = env_observer.build_observation_facts()
            if obs_facts:
                lines.append(obs_facts)

        return "<runtime_facts>\n" + "\n".join(lines) + "\n</runtime_facts>"

    def _find_repeated(self) -> dict:
        """找出重复执行的 action（次数 >= 2）。"""
        counts: dict = {}
        for atype, params, _ in self.actions:
            key = (atype, params)
            counts[key] = counts.get(key, 0) + 1
        return {k: v for k, v in counts.items() if v >= 2}

    def _normalize_params(self, action_type: str, params: str) -> str:
        """规范化参数用于去重比较。"""
        p = params.strip()
        if action_type in ("read_file", "read_dir", "read_lines"):
            return p.split("\n")[0][:60]
        if action_type == "shell":
            return p.split("\n")[0][:60]
        return p[:60]
