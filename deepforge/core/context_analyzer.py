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


class ContextAnalyzer:
    def analyze(self, user_input: str, conversation_turns: list,
                artifacts: dict = None) -> ContextSignals:
        signals = ContextSignals()
        artifacts = artifacts or {}

        self._detect_output_context(signals, artifacts)
        self._detect_topic_continuity(signals, user_input, conversation_turns)
        self._detect_intent(signals, user_input, artifacts)
        self._detect_conversation_stage(signals, conversation_turns)

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

    def build_context_hint(self, signals: ContextSignals) -> str:
        hint = signals.to_prompt_hint()
        if not hint:
            return ""
        return "\n[上下文信号]\n" + hint
