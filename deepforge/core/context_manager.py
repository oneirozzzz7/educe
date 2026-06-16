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
    surface: str = "web",
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
        '⚠️ 路径规则：所有文件路径必须用相对路径（如 myproject/app.py），不要用 /tmp/ 或 /home/ 等绝对路径。\n'
        'shell 命令也用相对路径（cd myproject && python app.py），不要 cd 到绝对路径。\n\n'
        '执行命令（可以连续多个，框架自动逐个执行）：\n'
        '```shell\nmkdir -p myproject\n```\n\n'
        '```shell\ncd myproject && pip install -e .\n```\n\n'
        '读取目录/文件：\n'
        '```read_dir\nmyproject\n```\n\n'
        '```read_file\nmyproject/app.py\n```\n\n'
        '写文件（path + 分隔线 + 内容，不需要JSON转义）：\n'
        '```write_file\npath: myproject/app.py\n---\nimport os\nprint("hello world")\n```\n\n'
        '搜索文件内容（定位修改点）：\n'
        '```search_in_file\nmyproject/app.py\ndef hello\n```\n\n'
        '读取文件指定行（看局部上下文）：\n'
        '```read_lines\nmyproject/app.py\n10-30\n```\n\n'
        '编辑文件（局部修改，不需要重写整个文件）：\n'
        '```edit_file\npath: myproject/app.py\n<<<<<<< OLD\ndef hello():\n    print("hi")\n=======\ndef hello(name="world"):\n    print(f"hi {name}")\n>>>>>>> NEW\n```\n\n'
        '记忆：\n'
        '```memorize\n用户喜欢暗色主题\n```\n\n'
        '构建产物（网页/工具/应用）：\n'
        '```build\n做一个计数器网页\n```\n\n'
        '检索记忆：\n'
        '```recall\n关键词\n```\n\n'
        '⚠️ 决策规则：\n'
        '- 纯知识问答 → 直接用文字回答，不用代码块\n'
        '- 在系统上执行操作（克隆/安装/运行/测试）→ shell（可以连续多个）\n'
        '- 创建文件（代码/配置/脚本）→ write_file（一个一个写，每个文件一个代码块）\n'
        '- 修改已有文件 → 先 search_in_file 定位，再 read_lines 看上下文，最后 edit_file 局部修改\n'
        '- 生成完整网页（HTML/前端应用）→ build\n'
        '- shell 执行后框架会返回结果，你可以继续发下一条 shell\n\n'
        '⚡ 行动前判断：\n'
        '- 意图明确（如"运行这个""把X改成Y"）→ 直接执行\n'
        '- 有歧义但选错了容易改 → 选最合理方案执行，声明假设（"我按X来做，需要调整告诉我"）\n'
        '- 有歧义且选错代价大（架构选型、多文件重构、不可逆操作）→ 先问清楚再动手\n'
        '  提问时给封闭式选项+默认值："用 CLI 还是 Web？没偏好的话我默认做 CLI"\n\n'
        '⚡ 执行原则：\n'
        '- 动手时用代码块执行，不要只用文字解释方案\n'
        '- 多文件项目：用 shell 建目录，再逐个 write_file 创建文件，最后 shell 验证\n'
        '- 不要把代码贴在普通文字里"展示"给用户——那不会执行任何操作\n'
        '- build 仅用于独立的前端网页/HTML应用。Python/CLI/后端项目用 write_file + shell\n'
        '\n🚫 运行环境约束（重要）：\n'
        '- shell 是非交互式的，没有 stdin。不要写 input()、readline() 等需要用户输入的代码\n'
        '- 测试 Python 程序用 python -c "from xxx import ...; 函数调用" 或命令行参数\n'
        '- 测试服务用 nohup 后台启动 + curl 验证，不要前台阻塞运行\n'
        '- 如果用户要求"交互式"程序（CLI菜单），创建文件后告知用户如何本地运行，不要在 shell 中测试\n'
        '- 多文件 Python 项目：同目录内 import 用相对路径（from service import X），不要 from 目录名.module（会找不到包）\n'
        '- curl 测试时直接看输出，不要管道到 python -m json.tool 或 jq（空响应会导致管道失败）\n'
        '- 启动 HTTP 服务时用 8000 以上的端口（低端口可能被系统占用），启动后 sleep 1-2 秒再 curl\n'
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

    # 输出渠道自知（SurfaceManifest）
    surface_section = ""
    if surface == "web":
        surface_section = (
            '\n## 你的输出渠道\n'
            '用户通过 web 浏览器看你的回复。你能展示：\n'
            '- Markdown 格式文本、代码块、表格\n'
            '- HTML（通过 build 产物可嵌入预览）\n'
            '- shell 命令的 stdout 文本输出\n\n'
            '你不能展示：终端颜色(ANSI)、GUI窗口、音频、图片（除非生成HTML）。\n'
            '当用户要求"看效果"时，确保选择的 demo 在纯文本输出中就能体现价值。\n'
            '如果某个库的效果必须依赖终端/GUI才能看到，主动说明并提供替代方案。\n'
        )
    elif surface == "terminal":
        surface_section = (
            '\n## 你的输出渠道\n'
            '用户在终端中与你交互。支持 ANSI 颜色、完整的终端输出。\n'
        )

    return (
        identity
        + seed_section
        + surface_section
        + session_section
        + pattern_section
        + knowledge_index
        + tools_section
        + connectors_section
        + action_format
    )
