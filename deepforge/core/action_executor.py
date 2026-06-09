"""
ActionExecutor：解析模型输出中的 <action> 标签，执行对应操作，返回结果。

模型输出格式：
  纯文字（无标签）→ 直接回复用户
  <action type="memorize">{"op":"add","content":"..."}</action> → 记忆操作
  <action type="build">需求描述</action> → 构建代码
  <action type="use_tool" name="xxx">{"param":"value"}</action> → 调用工具
  <action type="lookup_tools"/> → 查看可用工具列表
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class ParsedAction:
    type: str
    params: str = ""
    name: str = ""      # use_tool 时的工具名


@dataclass
class ActionResult:
    success: bool
    output: str
    data: dict = field(default_factory=dict)


# 解析 <action> 标签的正则——容错：允许属性顺序不同、引号缺失
_ACTION_PATTERN = re.compile(
    r'<action\s+([^>]*?)(?:/>|>([\s\S]*?)</action>)',
    re.IGNORECASE,
)
_ATTR_PATTERN = re.compile(r'(\w+)\s*=\s*["\']?([^"\'\s>]+)["\']?')


def parse_actions(text: str) -> tuple[str, list[ParsedAction]]:
    """从模型输出中提取 action 标签和纯文字部分。

    返回 (reply_text, actions)：
    - reply_text：去掉 action 标签后的纯文字（给用户看的）
    - actions：解析出的 action 列表
    """
    actions = []
    for m in _ACTION_PATTERN.finditer(text):
        attrs_str = m.group(1)
        body = (m.group(2) or "").strip()
        attrs = dict(_ATTR_PATTERN.findall(attrs_str))
        action_type = attrs.get("type", "")
        if action_type:
            actions.append(ParsedAction(
                type=action_type,
                params=body,
                name=attrs.get("name", ""),
            ))

    reply_text = _ACTION_PATTERN.sub("", text).strip()
    return reply_text, actions


class ActionExecutor:
    """执行 action，返回结果。各 handler 由外部注入。"""

    def __init__(self):
        self._handlers: dict[str, callable] = {}

    def register(self, action_type: str, handler: callable):
        self._handlers[action_type] = handler

    async def execute(self, action: ParsedAction) -> ActionResult:
        handler = self._handlers.get(action.type)
        if not handler:
            return ActionResult(success=False, output=f"未知操作类型: {action.type}")
        try:
            return await handler(action)
        except Exception as e:
            return ActionResult(success=False, output=f"执行失败: {str(e)[:100]}")
