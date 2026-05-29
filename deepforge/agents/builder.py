"""
Builder Agent — DeepForge的核心Agent
能写代码、运行验证、看到错误、修复bug——像Claude Code一样工作
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator
from pathlib import Path

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.core.tools import (
    Tool, WriteFileTool, ReadFileTool, RunHTMLTool,
    RunPythonTool, CheckJSSyntaxTool, ALL_TOOLS, execute_tool,
)
from deepforge.core.knowledge import LayeredCache
from deepforge.tools.artifacts import ArtifactManager


class BuilderAgent(BaseAgent):
    name = "builder"
    role = "Builder"
    description = "写代码、运行验证、修复bug的全能Agent"

    def __init__(self, *args, memory_store=None, knowledge=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.artifacts = ArtifactManager()
        self.memory_store = memory_store
        self.knowledge = knowledge or LayeredCache()
        self.tools: list[Tool] = [
            WriteFileTool(),
            ReadFileTool(),
            RunHTMLTool(),
            RunPythonTool(),
            CheckJSSyntaxTool(),
        ]
        self.max_tool_rounds = 10

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        """核心循环：写代码→运行→看结果→修复→直到通过"""
        # builder需要更大token空间
        if self.model_config.max_tokens < 8192:
            self._model_config.max_tokens = 8192

        messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        output_dir = Path(".deepforge/output")
        output_dir.mkdir(parents=True, exist_ok=True)

        for round_num in range(self.max_tool_rounds):
            response = await self.call_model(messages, context)

            # 检查是否有工具调用指令
            tool_call = self._extract_tool_call(response)

            if tool_call:
                tool_name = tool_call["name"]
                tool_params = tool_call["params"]

                # 自动补全路径
                if "path" in tool_params and not tool_params["path"].startswith("/"):
                    tool_params["path"] = str(output_dir / tool_params["path"])

                result = await execute_tool(self.tools, tool_name, tool_params)

                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"工具 {tool_name} 执行结果:\n{result}"})

                # 如果写了文件，记录到artifacts
                if tool_name == "write_file" and "path" in tool_params:
                    file_path = tool_params["path"]
                    context.add_artifact("code_files", context.artifacts.get("code_files", []) + [file_path])
                    context.add_artifact("output_dir", str(output_dir))
                    if file_path.endswith(".html"):
                        context.add_artifact("project_type", "static_html")
                    elif file_path.endswith(".py"):
                        context.add_artifact("project_type", "python_script")

                continue

            # 无工具调用——检查是否有内嵌代码需要提取
            files = self._extract_files(response)
            if files:
                for filepath, content in files.items():
                    full_path = output_dir / filepath
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding="utf-8")

                    prev_files = context.artifacts.get("code_files", [])
                    context.add_artifact("code_files", prev_files + [str(full_path)])
                    context.add_artifact("output_dir", str(output_dir))
                    context.add_artifact("project_type",
                        "static_html" if filepath.endswith(".html") else "python_script" if filepath.endswith(".py") else "files")

                context.add_artifact("engineer_output", response)

                # 检测截断——HTML未闭合或Python语法不完整，请求续写
                for filepath, content in list(files.items()):
                    is_truncated = False
                    if filepath.endswith(".html") and "</html>" not in content:
                        is_truncated = True
                        hint = "缺少</html>闭合标签。请从断点继续输出剩余代码，确保有</script></body></html>。"
                    elif filepath.endswith(".py"):
                        open_parens = content.count("(") - content.count(")")
                        open_brackets = content.count("[") - content.count("]")
                        open_braces = content.count("{") - content.count("}")
                        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
                            is_truncated = True
                            hint = "代码括号未闭合。请从断点继续输出剩余代码。"

                    if is_truncated:
                        messages.append({"role": "assistant", "content": response})
                        messages.append({"role": "user", "content": "代码被截断了——{} {}".format(filepath, hint)})
                        continuation = await self.call_model(messages, context)
                        files[filepath] = content + "\n" + continuation
                        full_path = output_dir / filepath
                        full_path.write_text(files[filepath], encoding="utf-8")

                # 自动运行验证
                verify_result = await self._auto_verify(files, output_dir)
                if verify_result["has_issues"]:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": f"代码已写入，但验证发现问题:\n{verify_result['report']}\n\n请修复这些问题，重新输出完整文件。"})

                    # 记录失败到记忆
                    self._record_failure(verify_result['report'])
                    continue
                else:
                    # 验证通过——记录成功模式到知识库（进化闭环）
                    self._record_success(context.user_request, files)
                    # 把完整代码带在消息里，让前端能展示预览
                    code_content = "\n\n".join(f"```filepath:{fp}\n{code}\n```" for fp, code in files.items())
                    yield self.emit("user", code_content)
                    break
            else:
                # 纯文本回复
                context.add_artifact("engineer_output", response)
                yield self.emit("user", response)
                break

    def _extract_tool_call(self, response: str) -> dict | None:
        """从LLM回复中提取工具调用"""
        # 格式: <tool>tool_name</tool><params>{"key":"value"}</params>
        tool_match = re.search(r'<tool>(\w+)</tool>\s*<params>(.*?)</params>', response, re.DOTALL)
        if tool_match:
            try:
                return {"name": tool_match.group(1), "params": json.loads(tool_match.group(2))}
            except json.JSONDecodeError:
                return None

        # 备选格式: TOOL: tool_name PARAMS: {...}
        alt_match = re.search(r'TOOL:\s*(\w+)\s*PARAMS:\s*(\{.*?\})', response, re.DOTALL)
        if alt_match:
            try:
                return {"name": alt_match.group(1), "params": json.loads(alt_match.group(2))}
            except json.JSONDecodeError:
                return None

        return None

    async def _auto_verify(self, files: dict[str, str], output_dir: Path) -> dict:
        """自动运行验证所有产出文件"""
        issues = []
        for filepath, content in files.items():
            full_path = output_dir / filepath
            if filepath.endswith(".html"):
                tool = RunHTMLTool()
                result = await tool.execute({"path": str(full_path)})
                if "问题" in result or "错误" in result:
                    issues.append(f"{filepath}: {result}")
            elif filepath.endswith(".py"):
                tool = RunPythonTool()
                result = await tool.execute({"path": str(full_path)})
                if "失败" in result or "错误" in result or "异常" in result:
                    issues.append(f"{filepath}: {result}")

        return {
            "has_issues": len(issues) > 0,
            "report": "\n".join(issues) if issues else "全部验证通过",
        }

    def _record_failure(self, report: str):
        """记录失败到知识库"""
        triggers = self.knowledge._tokenize(report)
        self.knowledge.add(f"[失败] {report[:200]}", triggers, category="failure")

    def _record_success(self, user_request: str, files: dict):
        """记录成功模式到知识库——驱动L1编译进化"""
        triggers = self.knowledge._tokenize(user_request)
        file_types = ", ".join(f.split(".")[-1] for f in files.keys())
        self.knowledge.add(
            f"[成功] {user_request[:60]} → {file_types} ({sum(len(c) for c in files.values())}B)",
            triggers,
            category="success",
        )

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        # L1: 编译层——高频成功模式零成本注入
        l1 = self.knowledge.get_l1_compiled()
        compiled_knowledge = ""
        if l1:
            compiled_knowledge = "\n## 已验证的最佳实践\n" + "\n".join(f"- {k}" for k in l1[:5])

        # L2+L3: 召回与当前任务相关的知识
        recalled = self.knowledge.recall(context.user_request, max_results=3)
        recall_section = ""
        if recalled:
            recall_section = "\n## 相关经验\n" + "\n".join(f"- {r[:100]}" for r in recalled)

        # Skill模板
        skill_hint = ""
        skill_prompt = context.metadata.get("skill_prompt")
        if skill_prompt:
            skill_hint = f"\n## 已验证模板\n{skill_prompt}\n"

        # 上传文件
        file_section = ""
        uploaded = context.metadata.get("uploaded_files", [])
        if uploaded:
            from deepforge.core.file_handler import format_for_prompt
            file_section = format_for_prompt(uploaded)

        # 领域知识
        domain_section = context.metadata.get("domain_knowledge", "")

        return f"""你是DeepForge Builder。直接输出代码，不要描述、不要解释、不要说"我来创建"。

## 用户需求
{message.content}
{file_section}{domain_section}{skill_hint}{compiled_knowledge}{recall_section}
## 规则
- 第一行就开始写代码，不要任何前言
- 不要说"让我先看看"、"我来创建"等废话
- 如果验证发现问题，你会收到错误信息，请修复
- 反复迭代直到验证通过

## 你也可以使用工具（可选）
- 写文件: <tool>write_file</tool><params>{{"path":"文件名.html","content":"完整代码"}}</params>
- 验证HTML: <tool>run_html</tool><params>{{"path":"文件名.html"}}</params>
- 运行Python: <tool>run_python</tool><params>{{"path":"脚本.py"}}</params>
- 读文件: <tool>read_file</tool><params>{{"path":"文件路径"}}</params>

## 绝对规则
- 必须输出完整可运行的代码文件，不要输出描述或摘要
- 用```filepath:文件名格式包裹代码
- 单HTML文件优先（内嵌CSS+JS）
- CSS必须用:root变量系统（--primary、--bg、--text等），不要硬编码颜色
- CSS必须有@keyframes动画（loading、pulse、fadeIn等至少1个）
- 精致UI：渐变、阴影、圆角、hover动效(transition:0.2s)、响应式(@media)
- 完整功能：try/catch错误处理、localStorage持久化、复制按钮(navigator.clipboard)
- HTML必须有DOCTYPE和完整闭合标签
- JS不能有语法错误

## 输出格式
直接输出代码，用```filepath:文件名格式包裹。"""

    def _extract_files(self, content: str) -> dict[str, str]:
        files = {}
        for match in re.finditer(r'```filepath:([^\n]+)\n([\s\S]*?)```', content, re.DOTALL):
            filepath = match.group(1).strip()
            code = match.group(2).strip()
            if code and len(code) > 20:
                files[filepath] = code

        if not files:
            for match in re.finditer(r'```(?:html|htm)\n([\s\S]*?)```', content, re.DOTALL | re.IGNORECASE):
                code = match.group(1).strip()
                if code and len(code) > 20 and ('<html' in code.lower() or '<!doctype' in code.lower()):
                    files["index.html"] = code
                    break

        if not files:
            html_match = re.search(r'(<!DOCTYPE[\s\S]*?</html>)', content, re.IGNORECASE)
            if html_match:
                files["index.html"] = html_match.group(1)

        return files
