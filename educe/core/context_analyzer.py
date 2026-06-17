"""
DeepForge ContextAnalyzer
分析对话上下文，生成辅助判断信号，帮助弱模型做出更准确的意图理解。

核心理念：不替代模型做决策，而是给模型更完整的上下文信息。
弱模型的判断力不足，但如果框架把隐含的上下文信号显式化，模型能做出更好的判断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextSignals:
    last_output_type: str = ""
    topic_continuity: str = ""
    user_intent_hint: str = ""
    conversation_stage: str = ""
    signals: list[str] = field(default_factory=list)

    def to_prompt_hint(self) -> str:
        if not self.signals:
            return ""
        return "\n".join(self.signals)


MODIFY_PATTERNS = re.compile(
    r"改成|改为|换成|修改|调整|加个|去掉|加上|优化|变成|"
    r"改一下|改下|换个|调一下|大一点|小一点|亮一点|暗一点|"
    r"颜色|字体|大小|位置|样式|布局|间距|边框|背景|圆角"
)

TOPIC_SWITCH_PATTERNS = re.compile(
    r"另外|对了|换个话题|还有个问题|顺便问|不说这个了|"
    r"我想问|请问|有个问题|突然想到"
)

CONTINUE_PATTERNS = re.compile(
    r"这个|这篇|这段|上面|上文|刚才|前面|"
    r"继续|接着|详细|展开|深入|更多|举例|"
    r"为什么|怎么理解|什么意思"
)

CODE_REQUEST_PATTERNS = re.compile(
    r"做一个|做个|写一个|写个|生成|创建|搭建|开发|实现|"
    r"网页|网站|工具|游戏|脚本|程序|应用|APP|app|"
    r"可视化|图表|看板|仪表盘|dashboard|"
    r"HTML|html|Python|python|JavaScript|javascript"
)

QUESTION_PATTERNS = re.compile(
    r"什么是|是什么|怎么理解|如何理解|为什么|怎么样|"
    r"有哪些|有什么|能不能|可以吗|对吗|"
    r"介绍|解释|说说|讲讲|分析|比较"
)


BACK_REFERENCE_PATTERNS = re.compile(
    r"你(?:的|刚才的|之前的|上次的)?(?:总结|分析|回答|解释|说的|评价|建议|方案)|"
    r"(?:你觉得|你认为).*(?:到位|准确|对|正确)|"
    r"(?:刚才|之前|上面|前面)(?:那个|的|说的)"
)


class ContextAnalyzer:
    def analyze(self, user_input: str, conversation_turns: list,
                artifacts: dict = None) -> ContextSignals:
        signals = ContextSignals()
        artifacts = artifacts or {}

        self._detect_output_context(signals, artifacts)
        self._detect_topic_continuity(signals, user_input, conversation_turns)
        self._detect_intent(signals, user_input, artifacts)
        self._detect_conversation_stage(signals, conversation_turns)
        self._detect_user_style(signals, conversation_turns)
        self._resolve_back_reference(signals, user_input, conversation_turns)

        return signals

    def _detect_output_context(self, signals: ContextSignals, artifacts: dict):
        if artifacts.get("engineer_output"):
            signals.last_output_type = "code"
            code_files = artifacts.get("code_files", [])
            if code_files:
                filenames = [f.split("/")[-1] for f in code_files[:3]]
                signals.signals.append(
                    "上一轮生成了代码文件: {}".format(", ".join(filenames))
                )
        elif artifacts.get("last_text_domain"):
            signals.last_output_type = "text"
            signals.signals.append(
                "上一轮是文字回答，领域: {}".format(artifacts["last_text_domain"])
            )

    def _detect_topic_continuity(self, signals: ContextSignals,
                                  user_input: str, turns: list):
        if not turns:
            signals.topic_continuity = "new"
            return

        if TOPIC_SWITCH_PATTERNS.search(user_input):
            signals.topic_continuity = "switch"
            signals.signals.append("用户切换了话题，当前请求与之前无关")
            return

        if CONTINUE_PATTERNS.search(user_input):
            signals.topic_continuity = "continue"
            return

        if len(user_input) < 10 and not CODE_REQUEST_PATTERNS.search(user_input):
            signals.topic_continuity = "continue"
            signals.signals.append("用户输入很短，可能是在延续上一个话题")
            return

        signals.topic_continuity = "unclear"

    def _detect_intent(self, signals: ContextSignals, user_input: str,
                       artifacts: dict):
        has_prev_code = bool(artifacts.get("engineer_output"))
        is_modify = MODIFY_PATTERNS.search(user_input)
        is_code_request = CODE_REQUEST_PATTERNS.search(user_input)
        is_question = QUESTION_PATTERNS.search(user_input)

        if has_prev_code and is_modify and not TOPIC_SWITCH_PATTERNS.search(user_input):
            signals.user_intent_hint = "modify_code"
            signals.signals.append("用户可能要修改之前生成的代码")
        elif is_code_request:
            signals.user_intent_hint = "new_code"
        elif is_question:
            signals.user_intent_hint = "question"
        else:
            signals.user_intent_hint = "unclear"

    def _detect_conversation_stage(self, signals: ContextSignals, turns: list):
        turn_count = len(turns)
        if turn_count == 0:
            signals.conversation_stage = "opening"
        elif turn_count <= 4:
            signals.conversation_stage = "early"
        elif turn_count <= 12:
            signals.conversation_stage = "middle"
        else:
            signals.conversation_stage = "deep"

    def _detect_user_style(self, signals: ContextSignals, turns: list):
        user_turns = [t for t in turns if t.role == "user"]
        if len(user_turns) < 3:
            return

        avg_len = sum(len(t.content) for t in user_turns) / len(user_turns)
        if avg_len < 15:
            signals.signals.append("该用户习惯简短表达，请注意理解简短指令的完整意图")
        elif avg_len > 80:
            signals.signals.append("该用户习惯详细描述，回答也可以更详细深入")

    def _resolve_back_reference(self, signals: ContextSignals,
                                 user_input: str, turns: list):
        if not BACK_REFERENCE_PATTERNS.search(user_input):
            return
        if len(turns) < 4:
            return

        input_keywords = set(re.findall(r'[一-鿿]{2,}', user_input))
        if not input_keywords:
            return

        best_turn_idx = -1
        best_score = 0
        best_question = ""

        user_assistant_pairs = []
        for i, t in enumerate(turns):
            if t.role == "user":
                asst_content = ""
                if i + 1 < len(turns) and turns[i + 1].role == "assistant":
                    asst_content = turns[i + 1].content
                user_assistant_pairs.append((i, t.content, asst_content))

        for pair_idx, (turn_idx, question, answer) in enumerate(user_assistant_pairs):
            if pair_idx == len(user_assistant_pairs) - 1:
                continue

            q_keywords = set(re.findall(r'[一-鿿]{2,}', question))
            overlap = len(input_keywords & q_keywords)
            if overlap > best_score:
                best_score = overlap
                best_turn_idx = turn_idx
                best_question = question

        if best_score >= 2 and best_turn_idx >= 0:
            signals.signals.append(
                "用户可能在追问之前的对话：\"{}\"，请围绕该话题回答，不要混淆其他话题".format(
                    best_question[:50]))

    def build_context_hint(self, signals: ContextSignals) -> str:
        hint = signals.to_prompt_hint()
        if not hint:
            return ""
        return "\n[上下文信号]\n" + hint
