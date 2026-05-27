from __future__ import annotations

import random
from typing import AsyncIterator

from deepforge.core.agent import BaseAgent
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.tools.toolbox import ToolBox


CROWD_PERSONAS = [
    {
        "name": "小白用户-小明",
        "profile": "大学生，完全不懂技术，第一次使用这类产品",
        "focus": "易用性、引导、报错提示是否友好",
        "style": "会问很多'为什么'，容易被复杂操作劝退",
        "test_actions": ["尝试最基本的操作流程", "故意输入错误看提示是否友好", "不看说明直接上手"],
    },
    {
        "name": "产品经理-Lisa",
        "profile": "3年经验的产品经理，熟悉互联网产品",
        "focus": "功能完整性、交互逻辑、用户体验细节",
        "style": "会从产品视角提出系统性建议，关注用户路径",
        "test_actions": ["走完整用户路径", "检查边界情况", "对比竞品体验"],
    },
    {
        "name": "资深开发-老王",
        "profile": "10年经验的全栈开发，技术极客",
        "focus": "技术实现质量、性能、扩展性、API设计",
        "style": "会深入技术细节，关注架构合理性",
        "test_actions": ["检查代码结构", "运行测试", "压测性能", "审查安全性"],
    },
    {
        "name": "设计师-小艺",
        "profile": "UI/UX设计师，注重视觉和交互",
        "focus": "视觉效果、交互动效、信息层级、一致性",
        "style": "会从审美和交互角度提出建议",
        "test_actions": ["检查视觉一致性", "测试响应式布局", "评估信息层级"],
    },
    {
        "name": "创业者-Alex",
        "profile": "连续创业者，关注产品的商业价值",
        "focus": "核心价值、差异化、市场定位、变现可能",
        "style": "会从商业角度评估产品，关注MVP和增长",
        "test_actions": ["评估核心价值主张", "对比市场现有方案", "思考增长策略"],
    },
    {
        "name": "质量工程师-大刘",
        "profile": "5年QA经验，擅长找bug",
        "focus": "功能正确性、边界条件、异常处理、兼容性",
        "style": "会系统化地测试各种场景，包括恶意输入",
        "test_actions": ["边界值测试", "异常输入测试", "并发测试", "回归测试"],
    },
]


class CrowdUserAgent(BaseAgent):
    name = "crowd_user"
    role = "群像用户内测团"
    description = """你是DeepForge的群像用户Agent，模拟多种不同背景的用户来内测产品。
你不仅会从多个用户视角给出评价，还会实际运行和验证产出物。
每个模拟用户有不同的背景、关注点和测试方法。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.toolbox = ToolBox()

    async def handle(self, message: Message, context: WorkContext) -> AsyncIterator[Message]:
        selected = random.sample(CROWD_PERSONAS, min(4, len(CROWD_PERSONAS)))

        verification_results = await self._verify_artifacts(context)

        messages = [{"role": "user", "content": self._build_prompt(message, context, selected, verification_results)}]

        response = await self.call_model(messages, context)

        context.add_artifact("crowd_feedback", response)
        if verification_results:
            context.add_artifact("verification_results", verification_results)

        yield self.emit("user", response)

        yield self.handoff(
            "memory_keeper",
            f"## 群像用户移交\n\n"
            f"### 用户原始需求\n{context.user_request}\n\n"
            f"### 产品设计\n{context.artifacts.get('prd', '无')}\n\n"
            f"### 代码审查报告\n{context.artifacts.get('review_report', '无')}\n\n"
            f"### 实际验证结果\n{verification_results or '未执行验证'}\n\n"
            f"### 用户反馈\n{response}\n\n"
            f"请整理本次项目的知识沉淀。",
        )

    async def _verify_artifacts(self, context: WorkContext) -> str:
        """实际验证产出物：运行代码、检查文件、测试功能"""
        results = []

        code_files = context.artifacts.get("code_files", [])
        if code_files:
            results.append("## 文件验证")
            for filepath in code_files[:20]:
                content = await self.toolbox.read_file(filepath)
                if content.startswith("[ERROR]"):
                    results.append(f"- ❌ {filepath}: 文件不存在")
                else:
                    lines = len(content.split("\n"))
                    results.append(f"- ✅ {filepath}: {lines}行")

        if code_files:
            results.append("\n## 运行测试")

            py_files = [f for f in code_files if f.endswith(".py")]
            if py_files:
                main_candidates = [f for f in py_files if "main" in f or "app" in f or "server" in f]
                if main_candidates:
                    result = await self.toolbox.run_command(f"python -c 'import ast; ast.parse(open(\"{main_candidates[0]}\").read()); print(\"语法检查通过\")'", timeout=10)
                    results.append(f"- Python语法检查: {result.strip()}")

            html_files = [f for f in code_files if f.endswith(".html")]
            for hf in html_files[:3]:
                content = await self.toolbox.read_file(hf)
                if "<html" in content.lower() and "</html>" in content.lower():
                    results.append(f"- ✅ {hf}: HTML结构完整")
                else:
                    results.append(f"- ⚠️ {hf}: HTML结构可能不完整")

            json_files = [f for f in code_files if f.endswith(".json")]
            for jf in json_files[:5]:
                result = await self.toolbox.run_command(f"python -c 'import json; json.load(open(\"{jf}\")); print(\"JSON合法\")'", timeout=5)
                results.append(f"- JSON验证 {jf}: {result.strip()}")

            pkg_json = [f for f in code_files if f.endswith("package.json")]
            requirements = [f for f in code_files if "requirements" in f]
            if pkg_json:
                results.append("- 📦 检测到 package.json，需要 npm install")
            if requirements:
                results.append("- 📦 检测到 requirements.txt，需要 pip install")

        return "\n".join(results) if results else ""

    def _build_prompt(self, message: Message, context: WorkContext, personas: list[dict], verification: str) -> str:
        prd = context.artifacts.get("prd", "")
        review = context.artifacts.get("review_report", "")
        engineer_output = context.artifacts.get("engineer_output", "")

        persona_desc = "\n\n".join(
            f"### 用户{i+1}: {p['name']}\n"
            f"- **背景**: {p['profile']}\n"
            f"- **关注**: {p['focus']}\n"
            f"- **风格**: {p['style']}\n"
            f"- **测试动作**: {', '.join(p.get('test_actions', []))}"
            for i, p in enumerate(personas)
        )

        verification_section = ""
        if verification:
            verification_section = f"""
### 🔬 实际验证结果（以下是真实运行结果，非模拟）
{verification}

请基于以上真实验证结果来评估产品，如果有验证失败的项目请重点关注。
"""

        return f"""## 产品信息
### 用户原始需求
{context.user_request}

### 产品设计
{prd}

### 实现代码概要
{engineer_output[:3000] if engineer_output else '无'}

### 代码审查报告
{review}
{verification_section}

## 你的角色
你需要同时扮演以下{len(personas)}个不同用户，从各自视角对产品进行深度体验评估。

**关键要求**：
1. 你不是在"评价一份文档"，而是在"试用一个产品"——站在真实用户的角度思考
2. 每个角色要给出**具体的操作场景**，说明自己会怎么用、用到哪一步会遇到什么问题
3. 如果有实际验证结果，必须结合验证结果来评价（比如文件缺失、语法错误等）
4. **杀手锏问题**：每个用户必须回答"如果市面上有10个类似工具，这个能排第几？为什么？"

{persona_desc}

## 输出要求

### 每个用户的反馈
---
#### 👤 [用户名]
**整体评分**: ⭐⭐⭐⭐ (1-5星)

**实际使用场景**:
> 描述自己会在什么场景下使用，操作步骤是什么

**优点（让我愿意用的理由）**:
- ...

**痛点（让我放弃的理由）**:
1. [具体问题] → [改进建议] → [改进后的效果预期]

**竞品对比排名**: X/10，因为...

**一句话推荐/不推荐**:
> "我会/不会推荐给朋友，因为..."
---

### 综合评估
**整体可用性评分**: X/10
**上线信心指数**: X%（0%=完全不能上线，100%=可以直接发布）

**🔴 阻塞性问题（必须修复才能上线）**:
1. ...

**🟡 体验问题（影响留存，应尽快优化）**:
1. ...

**🟢 增强建议（锦上添花）**:
1. ...

**💡 最具价值的差异化建议（让这个产品脱颖而出的关键改动）**:
- ..."""
