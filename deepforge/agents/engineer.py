from __future__ import annotations

import json
import re
from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.tools.toolbox import ToolBox
from deepforge.tools.artifacts import ArtifactManager


class EngineerAgent(BaseAgent):
    name = "engineer"
    role = "全栈工程师"
    description = """你是DeepForge的全栈工程师Agent。
你的唯一职责是输出完整可运行的代码。
禁止输出规划、描述、解释——只要代码。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.toolbox = ToolBox()
        self.artifacts = ArtifactManager()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        iteration = message.data.get("iteration", 1)

        if iteration > 1 and "审查反馈" in message.content:
            prompt = self._build_fix_prompt(message, context)
        else:
            prompt = self._build_prompt(message, context)

        messages = [{"role": "user", "content": prompt}]

        on_chunk = context.metadata.get("on_chunk")

        async def chunk_cb(chunk):
            if on_chunk:
                on_chunk(self.name, chunk)

        try:
            response = await self.call_model_streaming(messages, context, on_chunk=chunk_cb)
        except Exception:
            response = await self.call_model(messages, context)

        files = self._extract_files(response)

        if not files:
            retry_prompt = self._build_retry_prompt(context, response)
            retry_messages = [{"role": "user", "content": retry_prompt}]
            retry_response = await self.call_model(retry_messages, context)
            retry_files = self._extract_files(retry_response)
            if retry_files:
                files = retry_files
                response = retry_response

        if files:
            saved = self.artifacts.save_files(files)
            project_type = self.artifacts.detect_project_type(files)

            validation = await self._validate_output(files, project_type)

            prev_files = context.artifacts.get("code_files", [])
            all_files = list(set(prev_files + [str(p) for p in saved]))
            context.add_artifact("code_files", all_files)
            context.add_artifact("engineer_output", response)
            context.add_artifact("project_type", project_type)
            context.add_artifact("output_dir", str(self.artifacts.work_dir))
            context.add_artifact("validation", validation)

            file_summary = "\n".join(f"- {f}" for f in files.keys())
            status = "✅" if validation["passed"] else "⚠️"
            yield self.emit("user", f"{status} 已生成 {len(files)} 个文件 ({project_type}):\n{file_summary}\n验证: {validation['summary']}")
        else:
            context.add_artifact("engineer_output", response)
            yield self.emit("user", response)

        if not self._is_iterative_mode(context):
            yield self.handoff(
                "reviewer",
                f"## 工程师移交\n\n"
                f"### 用户原始需求\n{context.user_request}\n\n"
                f"### 实现代码\n{response[:3000]}\n\n"
                f"### 创建的文件\n{json.dumps(list(files.keys()) if files else [], ensure_ascii=False)}\n\n"
                f"请对以上代码进行全面审查。",
            )

    def _is_iterative_mode(self, context: WorkContext) -> bool:
        return context.metadata.get("iteration", 0) > 0

    def _build_prompt(self, message: Message, context: WorkContext) -> str:
        architecture = context.artifacts.get("architecture", "")
        prd = context.artifacts.get("prd", "")

        arch_brief = architecture[:2000] if architecture else "无"
        prd_brief = prd[:1500] if prd else "无"

        return f"""你是编码机器。你的输出只有代码，没有解释。

## 用户需求
{context.user_request}

## 参考设计
{prd_brief}

{arch_brief}

## 绝对铁律
1. 你必须输出完整可运行的代码文件
2. 禁止输出计划、分析、描述、大纲
3. 每个文件用这个格式：

```filepath:文件名.扩展名
完整代码（从第一行到最后一行）
```

4. 如果用户要的是网页/工具，优先做成单个HTML文件（内嵌CSS和JS）
5. 代码必须能直接运行——双击HTML能打开，python xxx.py能执行
6. 不要写TODO、不要省略、不要"其余类似"

## 代码质量标准（从历史项目经验中学到）
- HTML必须有完整的DOCTYPE和闭合标签
- 暗色模式：优先使用 prefers-color-scheme 或默认暗色
- 防抖自动保存：input事件1s防抖写localStorage
- Canvas动画：维护唯一requestAnimationFrame ID，新动画前cancel旧帧
- 高DPI适配：canvas.width=clientWidth*devicePixelRatio
- 事件监听：方向键/空格必须preventDefault防止页面滚动

## 现在开始写代码"""

    def _build_fix_prompt(self, message: Message, context: WorkContext) -> str:
        prev_output = context.artifacts.get("engineer_output", "")
        return f"""审查发现问题，你需要修复。

## 问题
{message.content[:2000]}

## 上一版代码
{prev_output[:3000]}

## 要求
输出修复后的完整文件，用 ```filepath:文件名 格式。
只输出代码，不要解释。"""

    def _build_retry_prompt(self, context: WorkContext, failed_response: str) -> str:
        return f"""你刚才的回答没有包含可提取的代码文件。
用户需求是：{context.user_request}

请直接输出完整代码。用这个格式：

```filepath:文件名.html
<!DOCTYPE html>
<html>
...完整代码...
</html>
```

不要解释，不要规划，直接写代码。现在开始："""

    def _extract_files(self, content: str) -> dict[str, str]:
        files = {}

        pattern1 = r'```filepath:([^\n]+)\n([\s\S]*?)```'
        for match in re.finditer(pattern1, content, re.DOTALL):
            filepath = match.group(1).strip()
            code = match.group(2).strip()
            if code and len(code) > 20:
                files[filepath] = code

        if files:
            return files

        lang_tags = (
            "html", "css", "javascript", "js", "python", "py",
            "json", "yaml", "yml", "typescript", "ts", "jsx", "tsx",
            "shell", "bash", "sh", "sql", "xml", "svg",
        )
        pattern2 = r'```(\w*)\n([\s\S]*?)```'
        for match in re.finditer(pattern2, content, re.DOTALL):
            lang = match.group(1).strip().lower()
            code = match.group(2).strip()
            if not code or len(code) < 50:
                continue
            if "<!DOCTYPE" in code or "<html" in code:
                files["index.html"] = code
            elif lang == "python" or lang == "py":
                if "def main" in code or "if __name__" in code:
                    files["main.py"] = code
            elif lang in ("js", "javascript"):
                files["app.js"] = code
            elif lang == "json" and "name" in code:
                files["package.json"] = code

        if files:
            return files

        html_match = re.search(r'(<!DOCTYPE[^>]*>[\s\S]*?</html>)', content, re.IGNORECASE)
        if html_match:
            files["index.html"] = html_match.group(1)

        return files

    async def _validate_output(self, files: dict[str, str], project_type: str) -> dict:
        """验证产出物质量——空壳和语法错误直接标记"""
        issues = []
        checks_passed = 0
        checks_total = 0

        for filepath, content in files.items():
            if filepath.endswith(".html"):
                checks_total += 4
                if "<!DOCTYPE" in content or "<!doctype" in content:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: 缺少DOCTYPE")
                if "</html>" in content:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: HTML未闭合")
                if "<script" in content and len(content) > 500:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: 缺少JS逻辑或内容过少")
                if "TODO" not in content and "// ..." not in content:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: 包含TODO/占位符")

            elif filepath.endswith(".py"):
                checks_total += 2
                try:
                    compile(content, filepath, "exec")
                    checks_passed += 1
                except SyntaxError as e:
                    issues.append(f"{filepath}: Python语法错误 L{e.lineno}")
                if len(content) > 100:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: 内容过少")

            elif filepath.endswith(".js"):
                checks_total += 1
                if len(content) > 50:
                    checks_passed += 1
                else:
                    issues.append(f"{filepath}: JS内容过少")

        passed = checks_total == 0 or (checks_passed / checks_total >= 0.75)
        summary = f"{checks_passed}/{checks_total} 检查通过" if checks_total else "无可验证文件"
        if issues:
            summary += f", 问题: {'; '.join(issues[:3])}"

        return {"passed": passed, "checks_passed": checks_passed, "checks_total": checks_total, "issues": issues, "summary": summary}
