"""
OrganModel — 阶段4：多反射弧协同形成器官

器官 = 反射弧之间的关系结构（带状态的图遍历器）。
- 节点是已有反射弧（或原子动作）的引用
- 边是因果转移（condition 来自运行时观测）
- 支持环（反馈环是器官与管道的质变区分）

设计原则（Opus 4.8 讨论确认）：
- 器官不是"更高级的 Skill"——它寄生在已有反射弧上，自身只持有拓扑
- 公理五：器官的所有"知识"在它引用的反射弧/动作里，器官自己只是机制
- 完成判据：移除任意单个节点，整体功能崩溃（涌现性）
- 触发：序列匹配（情境进入某个 pattern）
- 执行：状态机 / 图遍历，每步 Guard 决策 + 上下文传递
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("educe.organ")


@dataclass
class OrganEdge:
    """器官内的因果转移边"""
    from_node: str
    to_node: str
    condition: str       # 触发条件表达式（读取上一步输出）
    extract: str = ""    # 从上一步输出中提取变量的表达式

    def to_dict(self) -> dict:
        return {"from": self.from_node, "to": self.to_node,
                "condition": self.condition, "extract": self.extract}


@dataclass
class OrganNode:
    """器官内的节点（原子动作或反射弧引用）"""
    node_id: str
    action_type: str     # "shell" | "reflex_ref" | "done" | "escalate"
    template: str = ""   # 动作模板，含 ${var} 占位符
    is_terminal: bool = False

    def to_dict(self) -> dict:
        return {"id": self.node_id, "action_type": self.action_type,
                "template": self.template, "is_terminal": self.is_terminal}


@dataclass
class OrganModel:
    """
    器官 = 反射弧关系图。

    拓扑结构：有向图，可含环。
    状态：运行时上下文变量（跨节点传递）。
    """
    organ_id: str
    name: str
    description: str = ""

    nodes: list[dict] = field(default_factory=list)   # [OrganNode.to_dict()]
    edges: list[dict] = field(default_factory=list)   # [OrganEdge.to_dict()]
    entry_node: str = ""                              # 图的入口节点 ID

    # 触发条件
    trigger_pattern: str = ""     # 情境匹配模式
    trigger_scope: list[str] = field(default_factory=list)

    # 统计
    stats: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OrganModel":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class OrganState:
    """器官执行时的运行状态"""
    organ_id: str
    current_node: str = ""
    variables: dict = field(default_factory=dict)   # 跨节点状态
    history: list[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 5     # 防止无限循环

    @property
    def is_done(self) -> bool:
        return self.current_node == "__DONE__" or self.iteration >= self.max_iterations


class OrganExecutor:
    """
    器官执行器 — 带状态的图遍历器。

    每一步：
    1. 获取当前节点
    2. 用 variables 渲染动作模板
    3. 执行动作
    4. 根据输出匹配边的 condition
    5. 从输出中 extract 变量到 state
    6. 沿匹配的边移动到下一节点
    """

    def __init__(self, organ: OrganModel):
        self._organ = organ
        self._nodes = {n["id"]: n for n in organ.nodes}
        self._edges_from: dict[str, list[dict]] = {}
        for e in organ.edges:
            self._edges_from.setdefault(e["from"], []).append(e)

    def start(self, initial_vars: dict | None = None) -> OrganState:
        """初始化器官执行状态"""
        state = OrganState(
            organ_id=self._organ.organ_id,
            current_node=self._organ.entry_node,
            variables=initial_vars or {},
        )
        return state

    def get_next_action(self, state: OrganState) -> dict | None:
        """获取当前节点应执行的动作（渲染模板后）"""
        if state.is_done:
            return None

        node = self._nodes.get(state.current_node)
        if not node:
            return None

        if node.get("is_terminal"):
            state.current_node = "__DONE__"
            return None

        template = node.get("template", "")
        rendered = self._render_template(template, state.variables)

        return {
            "node_id": node["id"],
            "action_type": node["action_type"],
            "command": rendered,
        }

    def advance(self, state: OrganState, output: str, exit_code: int = 0) -> None:
        """根据执行结果推进状态机"""
        state.iteration += 1
        state.history.append(state.current_node)

        # 从输出中提取变量
        edges = self._edges_from.get(state.current_node, [])
        matched_edge = None

        for edge in edges:
            if self._evaluate_condition(edge["condition"], output, exit_code, state.variables):
                matched_edge = edge
                break

        if matched_edge:
            # 提取变量
            if matched_edge.get("extract"):
                extracted = self._extract_variable(matched_edge["extract"], output)
                if extracted:
                    state.variables.update(extracted)

            state.current_node = matched_edge["to"]
            log.info(f"Organ {self._organ.name}: {state.history[-1]} → {state.current_node} "
                     f"(vars={list(state.variables.keys())})")
        else:
            # 无匹配边 → 终止
            state.current_node = "__DONE__"
            log.info(f"Organ {self._organ.name}: no matching edge from {state.history[-1]}, done")

    @staticmethod
    def _render_template(template: str, variables: dict) -> str:
        """将模板中的 ${var} 替换为变量值"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"${{{key}}}", str(value))
        return result

    @staticmethod
    def _evaluate_condition(condition: str, output: str, exit_code: int, variables: dict) -> bool:
        """评估边的触发条件"""
        if condition == "always":
            return True
        if condition == "exit_ok":
            return exit_code == 0
        if condition == "exit_fail":
            return exit_code != 0
        if condition.startswith("contains:"):
            pattern = condition[len("contains:"):]
            return pattern in output
        if condition.startswith("exit_fail_and_contains:"):
            pattern = condition[len("exit_fail_and_contains:"):]
            return exit_code != 0 and pattern in output
        return False

    @staticmethod
    def _extract_variable(extract_expr: str, output: str) -> dict | None:
        """从输出中提取变量"""
        import re
        if extract_expr.startswith("regex:"):
            pattern = extract_expr[len("regex:"):]
            m = re.search(pattern, output)
            if m:
                return m.groupdict() if m.groupdict() else {"_match": m.group(1) if m.groups() else m.group(0)}
        return None


# ═══════════════════════════════════════
#  预定义器官：修复器官（手工种子）
# ═══════════════════════════════════════

REPAIR_ORGAN = OrganModel(
    organ_id="organ_repair_module",
    name="模块修复器官",
    description="执行脚本→检测 ModuleNotFoundError→自动 pip install→重试",
    entry_node="run",
    trigger_pattern="exit_fail_and_contains:ModuleNotFoundError",
    trigger_scope=["CODE", "SHELL"],
    nodes=[
        {"id": "run", "action_type": "shell", "template": "${cmd}", "is_terminal": False},
        {"id": "install", "action_type": "shell", "template": "pip install ${pkg}", "is_terminal": False},
        {"id": "retry", "action_type": "shell", "template": "${cmd}", "is_terminal": False},
        {"id": "done", "action_type": "done", "template": "", "is_terminal": True},
        {"id": "escalate", "action_type": "escalate", "template": "", "is_terminal": True},
    ],
    edges=[
        {"from": "run", "to": "done", "condition": "exit_ok", "extract": ""},
        {"from": "run", "to": "install",
         "condition": "exit_fail_and_contains:No module named",
         "extract": "regex:No module named ['\"]?(?P<pkg>\\w+)"},
        {"from": "run", "to": "escalate", "condition": "exit_fail", "extract": ""},
        {"from": "install", "to": "retry", "condition": "exit_ok", "extract": ""},
        {"from": "install", "to": "escalate", "condition": "exit_fail", "extract": ""},
        {"from": "retry", "to": "done", "condition": "exit_ok", "extract": ""},
        {"from": "retry", "to": "escalate", "condition": "exit_fail", "extract": ""},
    ],
)
