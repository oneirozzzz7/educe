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
        {"from": "retry", "to": "install",
         "condition": "exit_fail_and_contains:No module named",
         "extract": "regex:No module named ['\"]?(?P<pkg>\\w+)"},
        {"from": "retry", "to": "escalate", "condition": "exit_fail", "extract": ""},
    ],
)


# ═══════════════════════════════════════
#  器官注册表
# ═══════════════════════════════════════

class OrganRegistry:
    """
    器官注册表——持久化管理所有已验证的器官。

    职责：
    - 注册/卸载器官
    - 根据触发模式匹配器官
    - 持久化到 JSON
    - 启动时自动注册预定义器官
    """

    def __init__(self, base_dir: Path | None = None):
        self._dir = base_dir or Path(".educe/organs")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "registry.json"
        self._organs: dict[str, OrganModel] = {}
        self._load()
        self._ensure_builtins()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                for d in data:
                    organ = OrganModel.from_dict(d)
                    self._organs[organ.organ_id] = organ
            except Exception:
                pass

    def _save(self) -> None:
        data = [o.to_dict() for o in self._organs.values()]
        self._file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _ensure_builtins(self) -> None:
        """确保预定义器官已注册"""
        if REPAIR_ORGAN.organ_id not in self._organs:
            self._organs[REPAIR_ORGAN.organ_id] = REPAIR_ORGAN
            self._save()

    def register(self, organ: OrganModel) -> bool:
        """注册器官（需通过验证）"""
        verifier = OrganVerifier()
        result = verifier.verify(organ)
        if not result["is_organ"]:
            log.warning(f"OrganRegistry: rejected '{organ.name}' — failed verification")
            return False
        self._organs[organ.organ_id] = organ
        self._save()
        log.info(f"OrganRegistry: registered '{organ.name}' ({organ.organ_id})")
        return True

    def unregister(self, organ_id: str) -> None:
        self._organs.pop(organ_id, None)
        self._save()

    def match(self, output: str, exit_code: int) -> OrganModel | None:
        """根据执行结果匹配可触发的器官"""
        if exit_code == 0:
            return None

        for organ in self._organs.values():
            pattern = organ.trigger_pattern
            if not pattern:
                continue
            if OrganExecutor._evaluate_condition(pattern, output, exit_code, {}):
                return organ

        return None

    def all(self) -> list[OrganModel]:
        return list(self._organs.values())

    @property
    def count(self) -> int:
        return len(self._organs)


# ═══════════════════════════════════════
#  器官验证器：涌现性判定
# ═══════════════════════════════════════

class OrganVerifier:
    """
    验证 OrganModel 是否满足"器官"的形式化判据。

    判据（Opus 4.8 确认）：
    1. 含反馈环（有回边，不是纯 DAG）
    2. 移除任意非终端节点，整体功能崩溃（涌现性）
    3. 跨节点状态传递（至少一条边有 extract）
    """

    def verify(self, organ: OrganModel) -> dict:
        """返回验证报告"""
        results = {
            "organ_id": organ.organ_id,
            "name": organ.name,
            "has_feedback_loop": self._check_feedback_loop(organ),
            "has_state_transfer": self._check_state_transfer(organ),
            "node_removal_test": self._check_node_removal(organ),
            "is_organ": False,
        }
        results["is_organ"] = (
            results["has_feedback_loop"]
            and results["has_state_transfer"]
            and results["node_removal_test"]["all_critical"]
        )
        return results

    def _check_feedback_loop(self, organ: OrganModel) -> bool:
        """检测图中是否有环（回边）"""
        adj: dict[str, list[str]] = {}
        for edge in organ.edges:
            adj.setdefault(edge["from"], []).append(edge["to"])

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor in in_stack:
                    return True  # 回边 = 环
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
            in_stack.discard(node)
            return False

        for node_d in organ.nodes:
            nid = node_d["id"]
            if nid not in visited:
                if dfs(nid):
                    return True
        return False

    def _check_state_transfer(self, organ: OrganModel) -> bool:
        """检测是否有跨节点状态传递（边含 extract）"""
        return any(e.get("extract", "") for e in organ.edges)

    def _check_node_removal(self, organ: OrganModel) -> dict:
        """
        移除节点测试：对每个非终端节点，检查移除后是否削弱器官功能。

        "削弱" = 从 entry 到 done 的路径数减少（某条执行路径断裂）。
        全部节点都"关键"（移除任何一个都减少路径数） = 涌现性成立。
        """
        terminal_ids = {n["id"] for n in organ.nodes if n.get("is_terminal")}
        non_terminal = [n["id"] for n in organ.nodes if not n.get("is_terminal")]

        # 基线：完整图中的路径数
        base_paths = self._count_paths(organ, exclude_node=None, terminal_ids=terminal_ids)

        removal_results = {}
        for remove_id in non_terminal:
            reduced_paths = self._count_paths(organ, exclude_node=remove_id, terminal_ids=terminal_ids)
            is_critical = reduced_paths < base_paths
            removal_results[remove_id] = {
                "critical": is_critical,
                "base_paths": base_paths,
                "reduced_paths": reduced_paths,
            }

        all_critical = all(r["critical"] for r in removal_results.values())
        return {
            "all_critical": all_critical,
            "details": removal_results,
        }

    def _count_paths(
        self, organ: OrganModel, exclude_node: str | None, terminal_ids: set[str]
    ) -> int:
        """计算从 entry 到任意终端的路径数（简单 DFS，有上限防爆）"""
        if organ.entry_node == exclude_node:
            return 0

        adj: dict[str, list[str]] = {}
        for edge in organ.edges:
            if exclude_node and (edge["from"] == exclude_node or edge["to"] == exclude_node):
                continue
            adj.setdefault(edge["from"], []).append(edge["to"])

        count = 0
        max_count = 100

        def dfs(node: str, visited: set[str]) -> None:
            nonlocal count
            if count >= max_count:
                return
            if node in terminal_ids:
                count += 1
                return
            if node in visited:
                return
            visited.add(node)
            for neighbor in adj.get(node, []):
                dfs(neighbor, visited.copy())

        dfs(organ.entry_node, set())
        return count
