"""
DeepForge ResponseValidator
通用语义验证层——回答后验证"是否在回答用户的问题"。

不加规则，加能力。不解决单点，解决共性。

设计原则：
- 不枚举case为规则，用LLM自判断"回答是否对题"
- 不是每次都验证（成本），只在风险条件下触发
- 验证失败后带反馈重新生成，而不是打补丁
- 验证结果feed进QualityTracker，形成自检闭环
"""
from __future__ import annotations

import re


def should_validate(user_input: str, response: str, conversation_turns: list) -> bool:
    if len(conversation_turns) < 6:
        return False

    if len(user_input) > 40:
        return False

    input_keywords = set(re.findall(r'[一-鿿]{2,}', user_input))
    response_keywords = set(re.findall(r'[一-鿿]{2,}', response[:500]))

    if not input_keywords or not response_keywords:
        return False

    overlap = len(input_keywords & response_keywords)
    ratio = overlap / len(input_keywords) if input_keywords else 1.0

    return ratio < 0.15


async def validate_response(client, model: str, user_input: str, response: str,
                            conversation_summary: str = "") -> dict:
    system = (
        "你是回答质量检查器。判断助手的回答是否在回答用户的问题。\n"
        "- 如果回答紧扣用户问题 -> YES\n"
        "- 如果回答偏题（回答了别的问题）-> NO:简述偏题原因\n"
        "只回复YES或NO:原因"
    )
    user_msg = "用户问：{}\n\n助手回答（前300字）：{}".format(
        user_input, response[:300])
    if conversation_summary:
        user_msg = "对话背景：{}\n\n{}".format(conversation_summary, user_msg)

    try:
        result = await client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            model=model,
            max_tokens=50,
            temperature=0.0,
        )

        is_relevant = result.strip().startswith("YES")
        reason = ""
        if not is_relevant and ":" in result:
            reason = result.split(":", 1)[1].strip()
        elif not is_relevant and "：" in result:
            reason = result.split("：", 1)[1].strip()

        return {
            "relevant": is_relevant,
            "reason": reason,
            "raw": result.strip()[:100],
        }
    except Exception:
        return {"relevant": True, "reason": "", "raw": "validation_skipped"}


def build_retry_prompt(user_input: str, validation_result: dict,
                       conversation_turns: list) -> str:
    reason = validation_result.get("reason", "回答偏题")
    recent_topics = []
    for t in reversed(conversation_turns):
        if t.role == "user" and len(t.content) > 5:
            recent_topics.append(t.content[:40])
            if len(recent_topics) >= 3:
                break

    topics_hint = ""
    if recent_topics:
        topics_hint = "\n最近的对话话题：{}".format("、".join(reversed(recent_topics)))

    return (
        "你刚才的回答偏题了（{}）。{}请重新回答以下问题，"
        "注意紧扣用户的实际意图：\n\n{}".format(reason, topics_hint, user_input)
    )
