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
        "只有通过特定格式的代码块发出的指令才会被框架真正执行（执行命令、写入文件、记忆等）。"
        "如果你想做事，必须用代码块格式（如 ```shell / ```write_file 等），否则什么都不会发生。\n\n"
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

    # Markdown-native Action Protocol
    action_format = (
        '\n## 你可以做的事（用代码块格式）\n\n'
        '当你需要执行操作时，用 Markdown 代码块表达。框架会识别并执行。\n\n'
        '执行命令（可以连续多个，框架自动逐个执行）：\n'
        '```shell\ngit clone https://...\n```\n\n'
        '```shell\npip install -e .\n```\n\n'
        '读取目录/文件：\n'
        '```read_dir\n/path/to/dir\n```\n\n'
        '```read_file\n/path/to/file\n```\n\n'
        '写文件（path + 分隔线 + 内容，不需要JSON转义）：\n'
        '```write_file\npath: /tmp/demo.py\n---\nimport os\nprint("hello world")\n```\n\n'
        '记忆：\n'
        '```memorize\n用户喜欢暗色主题\n```\n\n'
        '构建产物（网页/工具/应用）：\n'
        '```build\n做一个计数器网页\n```\n\n'
        '检索记忆：\n'
        '```recall\n关键词\n```\n\n'
        '⚠️ 决策规则：\n'
        '- 纯知识问答 → 直接用文字回答，不用代码块\n'
        '- 在系统上执行操作（克隆/安装/运行/测试）→ shell（可以连续多个）\n'
        '- 生成代码产物（网页/工具/应用）→ build\n'
        '- shell 执行后框架会返回结果，你可以继续发下一条 shell\n'
    )

    # 连接器概要（Level 1）
    connectors_section = ""
    if connectors_summary:
        connectors_section = (
            '\n## 可用连接器\n'
            f'{connectors_summary}\n\n'
            '调用连接器：\n'
            '```tool:connector名.工具名\n{{"参数":"值"}}\n```\n'
            '例如：\n'
            '```tool:filesystem.search_files\n{{"path":".","pattern":"关键词"}}\n```\n'
        )

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
