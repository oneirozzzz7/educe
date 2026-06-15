"""
ActionExecutor：解析模型输出中的 action，执行对应操作，返回结果。

Markdown-native Action Protocol:
  模型用 Markdown 代码块表达 action：
  ```shell
  git clone https://...
  ```
  ```write_file
  path: /tmp/demo.py
  ---
  文件内容
  ```

  向后兼容旧 XML 格式（<action type="...">...</action>）
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


# ═══ Markdown-native 格式（主格式）═══
_MD_ACTION_PATTERN = re.compile(r'```(\w[\w.:]*)\n([\s\S]*?)```')

# 普通代码块语言标识（不是 action，跳过）
_CODE_ONLY_LANGS = {
    "python", "py", "javascript", "js", "go", "java", "html", "css",
    "json", "yaml", "yml", "toml", "bash", "sh", "sql", "rust", "rs",
    "typescript", "ts", "tsx", "jsx", "c", "cpp", "ruby", "rb",
    "swift", "kotlin", "scala", "php", "markdown", "md", "text", "txt",
    "xml", "csv", "ini", "dockerfile", "makefile", "plaintext",
}

# 合法的 action type（用于二次验证）
_VALID_ACTION_TYPES = {
    "shell", "read_dir", "read_file", "write_file", "edit_file",
    "create_file", "run", "exec",
    "memorize", "build", "plan", "recall", "search", "use_tool",
}

# 别名映射：模型可能使用的变体 → 规范 type
_ACTION_ALIASES = {
    "edit_file": "write_file",
    "create_file": "write_file",
    "run": "shell",
    "exec": "shell",
    "search": "recall",
}

# ═══ 旧 XML 格式（向后兼容）═══
_XML_ACTION_PATTERN = re.compile(
    r'<action\s+([^>]*?)(?:/>|>([\s\S]*?)</action>)',
    re.IGNORECASE,
)
_ATTR_PATTERN = re.compile(r'(\w+)\s*=\s*["\']?([^"\'\s>]+)["\']?')


def parse_actions(text: str) -> tuple[str, list[ParsedAction]]:
    """从模型输出中提取 action 和纯文字部分。

    优先解析 Markdown 代码块格式，fallback 到旧 XML 格式。
    返回 (reply_text, actions)。
    """
    actions = []

    # 主格式：Markdown 代码块
    for m in _MD_ACTION_PATTERN.finditer(text):
        lang = m.group(1).lower()
        body = m.group(2).strip()
        if lang in _CODE_ONLY_LANGS:
            continue
        # tool:connector.capability 格式
        if lang.startswith("tool:"):
            actions.append(ParsedAction(type="use_tool", params=body, name=lang[5:]))
        elif lang in _VALID_ACTION_TYPES:
            canonical = _ACTION_ALIASES.get(lang, lang)
            actions.append(ParsedAction(type=canonical, params=body, name=""))
        # 兼容 AgenticLoop 的 action:xxx 格式
        elif lang.startswith("action:"):
            atype = lang[7:]
            if atype in _VALID_ACTION_TYPES:
                canonical = _ACTION_ALIASES.get(atype, atype)
                actions.append(ParsedAction(type=canonical, params=body, name=""))

    # Fallback：旧 XML 格式（向后兼容）
    if not actions:
        for m in _XML_ACTION_PATTERN.finditer(text):
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

    # 清理 reply_text（去掉 action 代码块和 XML 标签）
    reply_text = text
    for m in reversed(list(_MD_ACTION_PATTERN.finditer(text))):
        lang = m.group(1).lower()
        if lang not in _CODE_ONLY_LANGS:
            reply_text = reply_text[:m.start()] + reply_text[m.end():]
    reply_text = _XML_ACTION_PATTERN.sub("", reply_text).strip()
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
