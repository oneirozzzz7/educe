"""
DeepForge 反幻觉审计层
模型回答后自动做事实审计：声明拆解 → 置信度自评 → 标注/删除不可靠内容

核心原则：宁可诚实说"不确定"，也不胡编乱造
"""
from __future__ import annotations

import re
import json
from typing import Any

AUDIT_PROMPT = """你是一个严格的事实审计员。请审查以下回答，找出可能不准确的内容。

## 用户问题
{question}

## 待审查的回答
{response}

## 审计要求
对回答中的每个事实性声明（日期、数字、人名、技术细节、因果关系等）做置信度评估：

1. 逐条列出关键事实声明
2. 对每条标注置信度：
   - CERTAIN：你完全确定这是正确的
   - LIKELY：大概率正确但不100%确定
   - UNSURE：不确定，可能有误
   - WRONG：你知道这是错误的
3. 对UNSURE和WRONG的声明，给出修正建议或标注"建议用户自行验证"

## 输出格式（严格JSON）
```json
{{
  "claims": [
    {{"text": "声明内容", "confidence": "CERTAIN/LIKELY/UNSURE/WRONG", "correction": "修正或null"}}
  ],
  "has_issues": true/false,
  "revised_response": "修正后的完整回答（如果has_issues=true）或null"
}}
```

只输出JSON，不要其他内容。"""

QUICK_CHECK_PROMPT = """审查这段回答是否有明显的事实错误、编造数据、或不该给的建议。
如果有问题，在对应位置插入【⚠️ 此处信息需要验证】标注。
如果涉及医学、法律、金融建议，在末尾加上"💡 以上为AI参考，重要决策请咨询专业人士"。
如果全文可靠，原样返回不做修改。

回答内容：
{response}

直接输出处理后的文本，不要解释你做了什么。"""


async def audit_response(question: str, response: str, model_client: Any,
                         model: str, max_tokens: int = 4096,
                         mode: str = "quick") -> str:
    """审计模型回答，标注或修正不可靠内容

    Args:
        question: 用户原始问题
        response: 模型的回答
        model_client: ModelClient实例
        model: 模型名
        max_tokens: 最大token
        mode: "quick"(轻量标注) 或 "deep"(完整声明拆解)

    Returns:
        审计后的回答
    """
    if not response or len(response) < 30:
        return response

    if _is_code_or_tool(response):
        return response

    try:
        if mode == "deep":
            return await _deep_audit(question, response, model_client, model, max_tokens)
        else:
            return await _quick_audit(response, model_client, model, max_tokens)
    except Exception:
        return response


async def _quick_audit(response: str, model_client: Any,
                       model: str, max_tokens: int) -> str:
    """轻量审计——标注可疑处+专业建议提醒"""
    prompt = QUICK_CHECK_PROMPT.format(response=response)
    result = await model_client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
    )
    if not result or len(result) < 20:
        return response
    return result


async def _deep_audit(question: str, response: str, model_client: Any,
                      model: str, max_tokens: int) -> str:
    """深度审计——声明拆解+置信度+修正"""
    prompt = AUDIT_PROMPT.format(question=question, response=response)
    result = await model_client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
    )

    parsed = _parse_audit_result(result)
    if not parsed:
        return response

    if parsed.get("has_issues") and parsed.get("revised_response"):
        return parsed["revised_response"]

    return response


def _parse_audit_result(text: str) -> dict | None:
    """解析审计结果JSON"""
    json_match = re.search(r'```json\s*([\s\S]*?)```', text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    json_match = re.search(r'\{[\s\S]*"claims"[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _is_code_or_tool(response: str) -> bool:
    """检测是否是代码/工具输出——这些不需要审计"""
    indicators = ["```filepath:", "<!DOCTYPE", "<html", "```python", "```javascript",
                  "<tool>", "TOOL:", "VERDICT:"]
    return any(ind in response for ind in indicators)
