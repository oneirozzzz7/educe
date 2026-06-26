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
    "search_in_file", "read_lines",
    "create_file", "run", "exec",
    "memorize", "build", "plan", "recall", "search", "use_tool",
    "clarify",
}

# 别名映射：模型可能使用的变体 → 规范 type
_ACTION_ALIASES = {
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

# 自然 XML 格式：<read_dir>/path</read_dir>（模型更倾向输出这种）
_NATURAL_XML_TYPES = "|".join(_VALID_ACTION_TYPES)
_NATURAL_XML_PATTERN = re.compile(
    rf'<({_NATURAL_XML_TYPES})>([\s\S]*?)</\1>',
    re.IGNORECASE,
)


def _looks_executable(code: str) -> bool:
    """判断 python 代码块是否像可执行脚本（非纯定义/展示）"""
    lines = code.strip().split("\n")
    if len(lines) < 2:
        return False
    first_line = lines[0].strip()
    if first_line.startswith(("class ", "def ", "from ", "import ")):
        if not any("print(" in line for line in lines):
            return False
    executable_signals = ("print(", "print (", "result =", "import ", "open(", "input(")
    return any(any(sig in line for sig in executable_signals) for line in lines)


def _quote_for_shell(code: str) -> str:
    """将 Python 代码包装为 shell 安全的单引号字符串"""
    escaped = code.replace("'", "'\\''")
    return f"'{escaped}'"


def parse_actions(text: str) -> tuple[str, list[ParsedAction]]:
    """从模型输出中提取 action 和纯文字部分。

    解析优先级：Markdown code block > 原生 tool call > XML (旧格式)
    Markdown 和 native tool call 同时解析并合并（模型可能混用格式）。
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

    # 并行：原生 tool call 格式（Kimi K2 等模型的特殊 token 格式）
    # 与 Markdown 格式合并（模型可能在同一个 response 中混用两种格式）
    _NATIVE_JSON = re.compile(
        r'(?:<\|tool_call_begin\|>.*?<\|tool_call_end\|>)?'
        r'tool:([\w.]+)\s*\n'
        r'(\{[^}]*\})'
        r'(?:<\|tool_call_argument_begin\|>)?',
        re.DOTALL
    )
    for m in _NATIVE_JSON.finditer(text):
        tool_name = m.group(1).strip()
        params = m.group(2).strip()
        actions.append(ParsedAction(type="use_tool", params=params, name=tool_name))

    # Pattern B: special_tokens + bare action name + raw params (hybrid)
    if not actions:
        _NATIVE_BARE = re.compile(
            r'<\|tool_call_begin\|>.*?<\|tool_call_end\|>'
            r'([\w][\w.]*)\n'
            r'([\s\S]*?)(?:```|<\|tool_call_argument_begin\|>|$)',
        )
        for m in _NATIVE_BARE.finditer(text):
            tool_name = m.group(1).strip()
            params = m.group(2).strip()
            if tool_name and params:
                actions.append(ParsedAction(type="use_tool", params=params, name=tool_name))

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

    # 自然 XML：<read_dir>/path</read_dir>（模型自然输出的格式）
    if not actions:
        for m in _NATURAL_XML_PATTERN.finditer(text):
            action_type = m.group(1).lower()
            body = m.group(2).strip()
            canonical = _ACTION_ALIASES.get(action_type, action_type)
            actions.append(ParsedAction(type=canonical, params=body, name=""))

        if not actions:
            _NATIVE_BARE = re.compile(
                r'<\|tool_call_begin\|>.*?<\|tool_call_end\|>'
                r'([\w][\w.]*)\n'
                r'([\s\S]*?)(?:```|<\|tool_call_argument_begin\|>|$)',
            )
            for m in _NATIVE_BARE.finditer(text):
                tool_name = m.group(1).strip()
                params = m.group(2).strip()
                if tool_name and params:
                    actions.append(ParsedAction(type="use_tool", params=params, name=tool_name))

    # 清理 reply_text（去掉 action 代码块、XML 标签、native tool call tokens）
    reply_text = text
    for m in reversed(list(_MD_ACTION_PATTERN.finditer(text))):
        lang = m.group(1).lower()
        if lang not in _CODE_ONLY_LANGS:
            reply_text = reply_text[:m.start()] + reply_text[m.end():]
    reply_text = _XML_ACTION_PATTERN.sub("", reply_text)
    reply_text = _NATURAL_XML_PATTERN.sub("", reply_text)
    # 清理 native tool call 特殊 token
    reply_text = re.sub(r'<\|tool_call_begin\|>.*?<\|tool_call_argument_begin\|>', '', reply_text, flags=re.DOTALL)
    reply_text = re.sub(r'<\|tool_call_begin\|>.*?<\|tool_call_end\|>', '', reply_text, flags=re.DOTALL)
    reply_text = re.sub(r'tool:[\w.]+\s*\n\{[^}]*\}', '', reply_text)
    reply_text = reply_text.strip()

    # Code-block promotion: 如果无 action 但有可执行的 python/bash 代码块，提升为 shell
    if not actions:
        for m in _MD_ACTION_PATTERN.finditer(text):
            lang = m.group(1).lower()
            body = m.group(2).strip()
            if lang in ("python", "py") and _looks_executable(body):
                actions.append(ParsedAction(type="shell", params=f"python3 -c {_quote_for_shell(body)}", name=""))
                break
            elif lang in ("bash", "sh") and body:
                actions.append(ParsedAction(type="shell", params=body, name=""))
                break

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
