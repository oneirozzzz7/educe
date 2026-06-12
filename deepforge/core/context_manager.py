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
    connectors_summary: str = "",
) -> str:
    """构建完整的 system prompt context。

    不硬编码判断逻辑，只根据当前状态如实编排信息。
    """
    identity = (
        "你是 Educe，一个有记忆力、创造力和判断力的智能助手。\n\n"
        "你运行在一个框架中。你的文字回复会展示给用户，但不会改变任何系统状态。"
        "只有通过 <action> 标签发出的指令才会被框架真正执行（写入记忆、构建代码、检索信息等）。"
        "如果你想记住什么、删除什么、构建什么，必须用 action 标签，否则什么都不会发生。\n\n"
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

    # 行为表达格式（A1d方案 — 压力测试90%，chat/build/read/memorize全100%）
    action_format = (
        '\n## 决策流程（严格按顺序）\n\n'
        '第零步：用户是纯粹问知识还是让你做事？\n'
        '  → 纯知识问答（什么是X / 解释X / X和Y区别 / X怎么样 / 闲聊寒暄）→ 直接回答，不用 action\n'
        '  → 让你做事 → 继续\n\n'
        '第一步：用户想「了解项目/文件」还是「改变/创造什么」？\n'
        '  → 了解项目 → <action type="read_dir">路径</action> 或 '
        '<action type="read_file">文件</action> 或 '
        '<action type="recall">关键词</action>\n'
        '  → 改变/创造 → 进入第二步\n\n'
        '第二步：一步能做完，还是需要多步？\n'
        '  → 一步 → <action type="shell">命令</action> 或 '
        '<action type="write_file">...</action> 或 '
        '<action type="memorize">...</action>\n'
        '  → 多步/构建 → <action type="build">完整需求描述</action>\n\n'
        '⚠️ 核心规则：\n'
        '- 「帮我写/做/建/实现/创建X」→ build\n'
        '- 「帮我规划/计划/分步做X」→ build（框架自动拆步骤）\n'
        '- 「帮我记住X」/「记一下X」→ memorize\n'
        '- 「什么是X」/「解释X」/「X和Y区别」→ 直接回答，禁用 action\n'
        '- 永远不用纯文字描述步骤。要做事必须 action。\n\n'
        '示例：\n'
        '❌ "什么是微服务？" → memorize（错！直接回答）\n'
        '✅ "什么是微服务？" → 文字解释\n'
        '❌ "帮我规划部署" → 文字列步骤\n'
        '✅ "帮我规划部署" → <action type="build">规划并执行部署</action>\n'
        '✅ "记住我喜欢暗色" → <action type="memorize">{"op":"add","content":"喜欢暗色主题"}</action>\n\n'
        '安全级别：read_dir/read_file/recall 直接执行；其余需确认。\n'
        '连续多轮：先 read_dir/read_file 了解，再决定下一步。\n'
    )

    # 连接器概要（Level 1）
    connectors_section = ""
    if connectors_summary:
        connectors_section = f"\n## 可用连接器\n{connectors_summary}\n"

    return (
        identity
        + seed_section
        + session_section
        + pattern_section
        + knowledge_index
        + tools_section
        + connectors_section
        + action_format
    )
