"""
Decision Mixin — 从 orchestrator.py 抽取。
"""
from __future__ import annotations

import logging

log = logging.getLogger("educe.orchestrator")


class DecisionMixin:
    """Decision methods for Orchestrator."""

    async def _decide(self, user_input: str) -> dict:
        """深度意图理解——让模型思考用户真正想要什么，不做关键词匹配。"""
        cs = getattr(self, 'cognitive_state', None)
        client = self._get_client()
        if not client:
            return {"action": "reply", "content": "请先配置模型。"}

        has_files = bool(self.context.metadata.get("uploaded_files"))
        file_hint = ""
        if has_files:
            files = self.context.metadata["uploaded_files"]
            names = [f.name for f in files]
            file_hint = "\n（用户上传了文件：{}）".format(", ".join(names))

        # 构建意图理解 prompt —— 给模型思考空间
        intent_system = (
            "你是任务理解专家。分析用户意图并决定处理方式。\n\n"
            "先思考：\n"
            "1. 用户真正想要什么？（深层需求，不只是字面意思）\n"
            "2. 期望的产出形态？（代码文件/文字分析/需要追问确认？操作记忆系统？）\n"
            "3. 如果有已有产物，是想改进还是在讨论别的？\n\n"
            "输出格式（严格）：\n"
            "ACTION: build | reply | clarify | memorize\n"
            "INTENT: 一句话描述用户真实意图\n"
            "- build: 需要产出可运行的文件（网页/工具/游戏/脚本/演示/可视化等）\n"
            "- reply: 纯文字对话（提问/分析/翻译/闲聊）\n"
            "- clarify: 意图模糊需要追问（如'继续优化'但不知道优化什么方向）\n"
            "- memorize: 操作记忆/知识系统（记住/查看/删除偏好、规则、记忆）\n"
        )

        # 构建用户消息——注入上下文让模型有足够信息判断
        has_prev_code = bool(self.context.artifacts.get("engineer_output"))
        user_msg = user_input + file_hint

        # 注入对话历史摘要（最近3轮）
        recent_turns = []
        for t in self.conversation.turns[-6:]:
            recent_turns.append("{}: {}".format(t.role, t.content[:100]))
        if recent_turns:
            user_msg += "\n\n[对话历史]\n" + "\n".join(recent_turns)

        # 注入当前产物状态
        if has_prev_code:
            code_files = self.context.artifacts.get("code_files", [])
            file_names = [f.split("/")[-1] for f in code_files[:3]]
            prev_request = ""
            for t in reversed(self.conversation.turns):
                if t.role == "user" and t.content != user_input:
                    prev_request = t.content
                    break
            # 提取产物结构摘要
            structure = self._get_artifact_structure()
            user_msg += "\n\n[当前产物] 文件: {} | 原始需求: {}\n结构: {}".format(
                ", ".join(file_names) if file_names else "无",
                prev_request[:80],
                structure[:200] if structure else "未知")

        try:
            log.info("_decide | user_input=%s", user_input[:80])
            log.debug("_decide | intent_system=%s", intent_system[:200])
            log.debug("_decide | user_msg=%s", user_msg[:300])
            result = await client.chat(
                messages=[
                    {"role": "system", "content": intent_system},
                    {"role": "user", "content": user_msg},
                ],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.0,
            )
            log.info("_decide | raw_response=%s", result[:200])
            decision = self._parse_intent(result)
        except Exception as e:
            log.error("_decide | exception: %s", str(e)[:100])
            decision = {"action": "reply", "intent": user_input, "form": ""}

        log.info("_decide | decision=%s", decision)
        self.context.metadata["_route_decision"] = decision
        self.context.metadata["_user_intent"] = decision.get("intent", user_input)
        _sid = self.context.metadata.get("session_id", "")
        log_activity(_sid, "decide",
                    action=decision.get("action", "?"),
                    intent=decision.get("intent", "")[:80])

        if decision["action"] == "reply":
            return await self._direct_reply(user_input, file_hint)
        if decision["action"] == "clarify":
            return {"action": "clarify", "question": await self._generate_clarify(user_input, decision)}
        if decision["action"] == "memorize":
            return await self._handle_memorize(user_input)
        return {"action": "code", "intent": decision.get("intent", user_input)}

    def _parse_intent(self, response: str) -> dict:
        """解析意图理解模型的结构化输出"""
        import re
        result = {"action": "reply", "intent": "", "form": "", "context": ""}

        action_m = re.search(r'ACTION:\s*(build|reply|clarify|memorize)', response, re.IGNORECASE)
        if action_m:
            result["action"] = action_m.group(1).lower()

        intent_m = re.search(r'INTENT:\s*(.+)', response)
        if intent_m:
            result["intent"] = intent_m.group(1).strip()

        form_m = re.search(r'FORM:\s*(.+)', response)
        if form_m:
            result["form"] = form_m.group(1).strip()

        context_m = re.search(r'CONTEXT:\s*(.+)', response)
        if context_m:
            result["context"] = context_m.group(1).strip()

        return result

    def _get_artifact_structure(self) -> str:
        """提取当前产物的结构摘要（不是全部代码）"""
        import re
        code_files = self.context.artifacts.get("code_files", [])
        if not code_files:
            return ""
        from pathlib import Path
        for fp in code_files[:1]:
            p = Path(fp)
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="ignore")[:5000]
                # 提取关键结构
                titles = re.findall(r'<title>(.*?)</title>', content)
                buttons = re.findall(r'<button[^>]*>([^<]*)</button>', content)[:5]
                sections = re.findall(r'<(?:section|div)[^>]*(?:id|class)="([^"]*)"', content)[:8]
                funcs = re.findall(r'function\s+(\w+)', content)[:8]
                parts = []
                if titles:
                    parts.append("标题: " + titles[0])
                if buttons:
                    parts.append("按钮: " + ", ".join(buttons))
                if sections:
                    parts.append("模块: " + ", ".join(sections))
                if funcs:
                    parts.append("函数: " + ", ".join(funcs))
                return "; ".join(parts) if parts else "HTML文件 {}行".format(content.count("\n"))
        return ""

    async def _generate_clarify(self, user_input: str, decision: dict) -> str:
        """生成智能追问——基于当前产物结构，让模型自己决定问什么"""
        client = self._get_client()
        if not client:
            return "能具体说说你想怎么改进吗？"

        structure = self._get_artifact_structure()
        prompt = (
            "用户说：\"{}\"\n"
            "我理解的意图：{}\n"
            "当前产物结构：{}\n\n"
            "用户的指令不够明确，请生成一个简短的追问（2-3句话），"
            "帮助用户明确方向。要基于当前产物的具体内容给出具体的选项建议。"
            "直接输出追问文本，不要其他内容。"
        ).format(user_input, decision.get("intent", ""), structure or "无产物")

        try:
            clarify_text = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.config.default_model.model,
                max_tokens=200, temperature=0.3,
            )
            return clarify_text.strip()
        except Exception:
            return "能具体说说你想怎么改进吗？"

    def _build_confidence_context(self, user_input: str, cs) -> str:
        signals = []

        skill = self._match_skill(user_input)
        if skill:
            signals.append("技能库有匹配模板，此类任务有成功经验")

        if cs:
            if cs.task_success_rate >= 0.8:
                signals.append("该领域历史表现良好（{:.0f}%）".format(cs.task_success_rate * 100))
            elif cs.task_success_rate < 0.4 and cs.task_success_rate > 0:
                signals.append("该领域历史表现不佳")

            if cs.user_expertise == "advanced":
                signals.append("用户是有经验的用户，意图通常比较明确")

            if bool(self.context.artifacts.get("engineer_output")):
                signals.append("之前已生成过代码，用户可能在迭代改进")

        return "\n".join("- " + s for s in signals) if signals else ""

    # ═══════════════════════════════════════
    #  Agent执行器
    # ═══════════════════════════════════════

