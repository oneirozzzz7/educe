"""
Context Manager（激发引擎）

为模型构建最优的 context。不替模型做判断，管理模型看到什么。
索引式知识呈现 + 作用域隔离 + 分层容量 + 模型主动检索。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionMemory:
    """当前会话的临时记忆（优先级最高，会话结束消亡）"""
    items: list[str] = field(default_factory=list)

    def add(self, item: str):
        if item not in self.items:
            self.items.append(item)

    def render(self) -> str:
        if not self.items:
            return ""
        lines = "\n".join(f"- {item}" for item in self.items)
        return f"\n## 本次会话信息\n{lines}\n"


def build_knowledge_index(catalog: list[dict]) -> str:
    """从知识系统 catalog 生成索引（只包含 experience 及以上）"""
    # 按 domain 聚合
    domain_groups: dict[str, list[dict]] = {}
    for entry in catalog:
        if entry.get("maturity") in ("observation",):
            continue  # observation 不出现在索引中
        domain = entry.get("domain") or "通用"
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(entry)

    if not domain_groups:
        return "\n你当前没有存储的记忆。\n"

    lines = []
    for domain, entries in domain_groups.items():
        categories = set(e.get("category", "") for e in entries)
        desc = "、".join(categories) if categories else "相关经验"
        lines.append(f"- [{domain}] {desc}（{len(entries)}条）")

    return "\n## 你的记忆索引\n以下是你存储的记忆，需要时可用 recall 检索具体内容：\n" + "\n".join(lines) + "\n"


def build_pattern_section(catalog: list[dict], max_items: int = 5) -> str:
    """提取 pattern 级知识直接写入 context（本能层）"""
    patterns = [e for e in catalog if e.get("maturity") == "pattern"]
    if not patterns:
        return ""
    # 按 usage_count 排序取 top N
    patterns.sort(key=lambda x: x.get("usage_count", 0) * x.get("success_rate", 0), reverse=True)
    items = [e["preview"] for e in patterns[:max_items]]
    lines = "\n".join(f"- {item}" for item in items)
    return f"\n## 你确定知道的\n以下是经过验证的规则，构建时直接运用：\n{lines}\n"


def build_tools_index(tools: list[dict] | None = None) -> str:
    """构建工具索引"""
    if not tools:
        return "\n你当前没有外部工具可用。\n"
    lines = [f"- {t['name']}: {t['description']}" for t in tools]
    return "\n## 你的工具\n" + "\n".join(lines) + "\n"


def build_context(
    session_memory: SessionMemory | None = None,
    catalog: list[dict] | None = None,
    tools: list[dict] | None = None,
    seed: str = "",
) -> str:
    """构建完整的 system prompt context。

    不硬编码判断逻辑，只根据当前状态如实编排信息。
    """
    identity = (
        "你是 Educe，一个有记忆力、创造力和判断力的智能助手。\n\n"
        "在回应之前先想清楚：\n"
        "- 用户真正想要什么？结合上下文有什么变化需要注意？\n"
        "- 我需要哪些信息才能做好这件事？不确定就先确认或检索。\n"
    )

    seed_section = ""
    if seed:
        seed_section = f"\n## 思维引导\n{seed}\n"

    # session 临时记忆（优先级最高）
    session_section = ""
    if session_memory:
        session_section = session_memory.render()

    # pattern 级知识直接写入（本能层）
    pattern_section = ""
    if catalog:
        pattern_section = build_pattern_section(catalog)

    # experience+ 级知识索引（模型按需检索）
    knowledge_index = ""
    if catalog:
        knowledge_index = build_knowledge_index(catalog)
    else:
        knowledge_index = "\n你当前没有存储的记忆。\n"

    # 工具索引
    tools_section = build_tools_index(tools)

    # 行为表达格式
    action_format = (
        "\n## 行为表达\n"
        "当你需要执行操作时：\n"
        '<action type="memorize">{"op":"add/list/delete", ...}</action>\n'
        '<action type="build">需求描述</action>\n'
        '<action type="recall">检索关键词</action>\n'
        '<action type="use_tool" name="工具名">参数</action>\n\n'
        "不需要操作时直接回复用户。\n"
    )

    return (
        identity
        + seed_section
        + session_section
        + pattern_section
        + knowledge_index
        + tools_section
        + action_format
    )
