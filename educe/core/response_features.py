"""
Response Feature Extraction + Effect Dimension Inference

零成本计算模型输出的可测量特征，用于 Output-Metric Attribution。
"""
from __future__ import annotations

import re
from typing import Optional


def compute_response_features(response: str) -> dict[str, float]:
    """从模型回复中提取可测量特征向量（纯字符串处理，零 API 成本）"""
    text_only = re.sub(r'```[\s\S]*?```', '', response)

    sentences = [s.strip() for s in re.split(r'[。！？\n]', text_only) if len(s.strip()) > 3]

    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
        r'\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF\U00002600-\U000027BF]')

    return {
        "length": float(len(response)),
        "sentence_count": float(len(sentences)),
        "emoji_count": float(len(emoji_pattern.findall(response))),
        "code_block_count": float(response.count("```") // 2),
        "heading_count": float(len(re.findall(r'^#+\s', response, re.MULTILINE))),
        "list_item_count": float(len(re.findall(r'^[\-\*]\s|^\d+\.\s', response, re.MULTILINE))),
        "chinese_ratio": _chinese_ratio(text_only),
        "has_import": float(bool(re.search(r'\b(import|from\s+\w+\s+import|package\s)', response))),
    }


def _chinese_ratio(text: str) -> float:
    cn = len(re.findall(r'[一-鿿]', text))
    en = len(re.findall(r'[a-zA-Z]', text))
    total = cn + en
    return cn / total if total > 0 else 0.0


# ═══════════════════════════════════════
# Effect Dimension Inference
# ═══════════════════════════════════════

# 关键词 → (dimension, direction) 映射
# direction: -1 = 规则要求减少, +1 = 规则要求增加
DIMENSION_PATTERNS: list[tuple[list[str], str, int]] = [
    # 长度/简洁
    (["简洁", "简短", "精简", "字以内", "句话", "concise", "short", "brief"],
     "length", -1),
    # Emoji
    (["emoji", "表情", "表情符号"],
     "emoji_count", -1),
    # 代码完整性
    (["import", "完整可运行", "main函数", "完整代码", "runnable"],
     "has_import", +1),
    # 中文
    (["中文", "chinese", "全中文"],
     "chinese_ratio", +1),
    # 英文
    (["英文", "English", "全英文"],
     "chinese_ratio", -1),
    # Markdown 标题
    (["标题", "heading", "###"],
     "heading_count", -1),
    # 列表
    (["列表", "有序", "numbered"],
     "list_item_count", +1),
    # 代码块
    (["代码示例", "代码", "code example"],
     "code_block_count", +1),
]


def infer_effect_dimension(directive: str) -> tuple[Optional[str], int]:
    """从规则的 directive 文本推断它影响的输出维度

    Returns:
        (dimension_name, direction) 或 (None, 0) 如果无法推断
    """
    directive_lower = directive.lower()
    for keywords, dimension, direction in DIMENSION_PATTERNS:
        if any(kw in directive_lower for kw in keywords):
            return dimension, direction
    return None, 0
