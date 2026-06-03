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
        """核心循环：需求分析→构建→验证→修复"""
        if self.model_config.max_tokens < 32768:
            self._model_config.max_tokens = 32768

        # 检查是否有用户选择的决策（协作式构建Phase 2）
        user_decisions = context.metadata.get("_user_decisions")

        if not user_decisions and not context.metadata.get("_skip_analysis"):
            analysis = await self._analyze_requirements(message.content, context)
            if analysis.get("decisions"):
                import json
                yield self.emit("user", "__DECISION_REQUEST__" + json.dumps(
                    analysis["decisions"], ensure_ascii=False),
                    msg_type=MessageType.SYSTEM)
                context.metadata["_pending_decisions"] = True
                return

        # 构建prompt
        if user_decisions:
            decisions_text = "\n".join(
                "- {}: {}".format(d.get("question", ""), d.get("choice", ""))
                for d in user_decisions)
            build_input = "{}\n\n用户已确认的选择：\n{}".format(
                message.content, decisions_text)
            messages = [{"role": "user", "content": self._build_prompt(
                Message(type=message.type, sender=message.sender,
                       receiver=message.receiver, content=build_input),
                context)}]
        else:
            messages = [{"role": "user", "content": self._build_prompt(message, context)}]

        session_id = context.metadata.get("session_id", "default")
        output_dir = Path(".deepforge/output") / session_id[:16]
        output_dir.mkdir(parents=True, exist_ok=True)

        # 根据复杂度动态调整迭代深度
        complexity = context.metadata.get("_task_complexity", "simple")
        max_turns = 12 if complexity == "complex" else 6
        exec_timeout = 60 if complexity == "complex" else 15

        from deepforge.core.agentic_loop import AgenticLoop
        agentic = AgenticLoop(output_dir=output_dir, max_turns=max_turns, exec_timeout=exec_timeout)

        user_request = message.content
        if user_decisions:
            decisions_text = "\n".join(
                "- {}: {}".format(d.get("question", ""), d.get("choice", ""))
                for d in user_decisions)
            user_request = "{}\n\n用户已确认:\n{}".format(message.content, decisions_text)

        # 实时事件推送——通过context的notify回调
        notify_fn = context.metadata.get("_notify_fn")
        chunk_fn = context.metadata.get("_chunk_fn")

        def on_chunk(text: str):
            if chunk_fn:
                chunk_fn("builder", text)

        def on_tool_event(evt: dict):
            if notify_fn:
                import json as _json
                msg = self.emit("user", "__TOOL_EVENT__" + _json.dumps(evt, ensure_ascii=False),
                               msg_type=MessageType.SYSTEM)
                notify_fn(msg)

        async def call_model_fn(msgs: list[dict]) -> str:
            return await self.model_client.chat(
                messages=msgs,
                model=self.model_config.model,
                temperature=self.model_config.temperature,
                max_tokens=self.model_config.max_tokens,
            )

        async def stream_model_fn(msgs: list[dict]):
            async for chunk in self.model_client.chat_stream(
                messages=msgs,
                model=self.model_config.model,
                temperature=self.model_config.temperature,
                max_tokens=self.model_config.max_tokens,
            ):
                yield chunk

        yield self.emit("user", "__BUILD_PROGRESS__开始构建...",
                       msg_type=MessageType.SYSTEM)

        # 复杂任务走分步构建：拆解→逐步生成→每步验证
        if complexity == "complex":
            from deepforge.core.step_builder import StepBuilder

            build_system = (
                "你是一个编程助手。输出完整、可直接运行的代码。\n"
                "优先输出单个HTML文件（内嵌CSS和JS），除非任务明确需要其他格式。\n"
                "代码不截断、不省略、不用TODO占位。用```filepath:文件名 格式包裹输出。"
            )

            async def call_model_simple(prompt: str) -> str:
                return await self.model_client.chat(
                    messages=[
                        {"role": "system", "content": build_system},
                        {"role": "user", "content": prompt},
                    ],
                    model=self.model_config.model,
                    temperature=self.model_config.temperature,
                    max_tokens=self.model_config.max_tokens,
                )

            def on_step_progress(msg: str):
                on_tool_event({"event": "thinking", "content": msg})

            sb = StepBuilder(max_steps=5, max_fix_per_step=3)
            steps = await sb.plan_steps(user_request, call_model_simple)
            on_tool_event({"event": "thinking", "content": "分{}步构建: {}".format(len(steps), "; ".join(s[:20] for s in steps))})

            final_files = await sb.build_incremental(
                steps=steps,
                call_model_fn=call_model_simple,
                output_dir=output_dir,
                original_request=user_request,
                on_progress=on_step_progress,
            )
        else:
            # 简单任务走 AgenticLoop（快速单文件生成）
            final_files = await agentic.run(
                user_request=user_request,
                call_model_fn=call_model_fn,
                on_chunk=on_chunk,
                stream_model_fn=stream_model_fn,
                on_tool_event=on_tool_event,
            )

        # Smoke test: headless browser check for HTML files
        if final_files:
            html_files = [f for f in final_files if f.endswith(".html")]
            if html_files:
                from deepforge.core.execution_loop import ExecutionLoop
                loop = ExecutionLoop()
                html_path = output_dir / html_files[0]
                if html_path.exists():
                    smoke_errors = await loop._smoke_test_html(html_path)
                    if smoke_errors and notify_fn:
                        err_desc = "; ".join(e.message for e in smoke_errors[:2])
                        yield self.emit("user", f"__BUILD_PROGRESS__冒烟测试发现问题: {err_desc[:100]}，修复中...",
                                       msg_type=MessageType.SYSTEM)
                        fix_prompt = "代码运行时有问题：\n" + "\n".join(
                            f"- {e.message}" for e in smoke_errors
                        ) + "\n\n请修复代码中的运行时错误。确保页面能正常加载且不产生JS报错。"
                        fix_files = await agentic.run(
                            user_request=fix_prompt,
                            call_model_fn=call_model_fn,
                            on_tool_event=on_tool_event,
                        )
                        if fix_files:
                            final_files.update(fix_files)

        if final_files:
            # Ensure index.html exists for preview server
            html_files = [f for f in final_files if f.endswith(".html")]
            if html_files and "index.html" not in final_files:
                import shutil
                src = output_dir / html_files[0]
                dst = output_dir / "index.html"
                if src.exists() and not dst.exists():
                    shutil.copy2(str(src), str(dst))

            for filepath, code in final_files.items():
                full_path = output_dir / filepath
                prev_files = context.artifacts.get("code_files", [])
                context.add_artifact("code_files", prev_files + [str(full_path)])
            context.add_artifact("output_dir", str(output_dir))
            context.add_artifact("engineer_output", "agentic build")
            self._record_success(context.user_request, final_files)
            code_content = "\n\n".join(
                "```filepath:{}\n{}\n```".format(fp, code)
                for fp, code in final_files.items())
            yield self.emit("user", code_content)
        else:
            yield self.emit("user", "未能生成代码文件，请更具体描述需求。")

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

    async def _analyze_requirements(self, user_request: str, context: WorkContext) -> dict:
        """让模型分析需求的不确定点——不硬编码，模型自己决定"""
        analysis_prompt = (
            "分析以下编程需求，找出影响实现方向的关键不确定点。\n\n"
            "简单、功能明确的工具（如计算器、番茄钟、倒计时器、密码生成器、待办清单等）"
            "需求已经足够明确，直接回复：[READY]\n\n"
            "复杂项目（如游戏、管理系统、完整应用等）可能有多种实现方向，"
            "用以下格式列出关键决策点（最多3个）：\n"
            "[DECISION] 问题描述\n"
            "- 选项1\n"
            "- 选项2\n"
            "- 选项3（可选）\n\n"
            "用户需求：{}".format(user_request)
        )

        cs = context.metadata.get("_cognitive_state", {})
        if cs.get("task_success_rate", 1.0) < 0.6:
            analysis_prompt += "\n\n注意：这类任务历史成功率较低，建议仔细确认需求。"

        try:
            response = await self.model_client.chat(
                messages=[{"role": "user", "content": analysis_prompt}],
                model=self.model_config.model,
                max_tokens=300,
                temperature=0.0,
            )
            return self._parse_decisions(response)
        except Exception:
            return {"decisions": []}

    def _parse_decisions(self, response: str) -> dict:
        """解析模型输出的决策点"""
        import re
        if "[READY]" in response:
            return {"decisions": []}

        decisions = []
        parts = re.split(r'\[DECISION\]\s*', response)
        for part in parts[1:]:
            lines = [l.strip() for l in part.strip().split("\n") if l.strip()]
            if not lines:
                continue
            question = lines[0]
            options = []
            for line in lines[1:]:
                line = re.sub(r'^[-•]\s*', '', line)
                opt = re.sub(r'^选项\d+[：:]\s*', '', line)
                if opt and len(opt) > 2:
                    options.append(opt)
            if question and options:
                decisions.append({"question": question, "options": options[:4]})

        return {"decisions": decisions[:3]}

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
## 核心要求
1. 第一行就开始写代码，不要任何前言或废话
2. 输出完整、可直接运行的代码——不能有截断、不能有TODO占位
3. 安全优先：用户输入必须转义(防XSS)、正则操作需超时保护、不信任外部数据
4. 功能完整：所有UI交互、事件处理、错误处理都要实现，不遗漏

## 输出格式
- 用```filepath:文件名格式包裹代码
- 单HTML文件优先（内嵌CSS+JS），确保DOCTYPE和完整闭合标签
- 在代码中标注进度：<!-- STEP: 描述当前完成的部分 -->

## 你可以使用的工具（可选）
- 写文件: <tool>write_file</tool><params>{{"path":"文件名.html","content":"完整代码"}}</params>
- 验证HTML: <tool>run_html</tool><params>{{"path":"文件名.html"}}</params>
- 运行Python: <tool>run_python</tool><params>{{"path":"脚本.py"}}</params>
- 读文件: <tool>read_file</tool><params>{{"path":"文件路径"}}</params>"""

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
