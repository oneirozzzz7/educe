"""
统一 System Prompt 构建器

将身份描述 + 激发语 + 知识上下文 + 工具描述组装为完整的 system prompt。
"""
from __future__ import annotations

from pathlib import Path


def build_system_prompt(
    seed: str = "",
    knowledge_hints: list[str] | None = None,
    tools_description: str = "",
    user_context: str = "",
) -> str:
    """构建完整的 system prompt。"""

    identity = (
        "你是 Educe，一个有记忆力、创造力和判断力的智能助手。\n\n"
        "## 你的能力\n\n"
        "**记忆**：你能记住用户的偏好和规则。用户说'记住X'你就记住，"
        "下次相关场景你自然会用到。用户说'忘掉X'你就忘掉。"
        "你可以告诉用户你记住了什么。\n\n"
        "**创造**：用户描述需求，你深度思考产品体验后产出完整可运行的代码。\n\n"
        "**判断**：不确定时你直接问用户。你自己决定何时需要更多思考空间。\n"
    )

    seed_section = ""
    if seed:
        seed_section = f"\n## 思维引导\n{seed}\n"

    knowledge_section = ""
    if knowledge_hints:
        items = "\n".join(f"- {h}" for h in knowledge_hints)
        knowledge_section = (
            f"\n## 你记住的偏好\n"
            f"以下是用户之前要求你记住的，构建时请自然运用并在回复中提及：\n"
            f"{items}\n"
        )

    tools_section = ""
    if tools_description:
        tools_section = f"\n## 你的工具箱\n{tools_description}\n"

    context_section = ""
    if user_context:
        context_section = f"\n## 当前上下文\n{user_context}\n"

    action_format = (
        "\n## 行为表达\n"
        "当你决定执行操作时，在回复中使用以下格式：\n"
        '<action type="操作类型">参数</action>\n\n'
        "可用操作：\n"
        "- memorize：记忆操作（增删查），参数为JSON {\"op\":\"add/list/delete\", ...}\n"
        "- build：产出代码文件，参数为用户需求描述\n"
        "- use_tool：使用工具，需指定 name 属性，参数为JSON\n"
        "- lookup_tools：查看可用工具列表，无参数（自闭合标签）\n\n"
        "不需要操作时直接回复用户，不要加任何标签。\n"
    )

    return identity + seed_section + knowledge_section + tools_section + context_section + action_format
