"""
DeepForge Judge — 多维度回答质量评估

替代原有的规则打分(score_response)和简单pairwise comparison。
用弱模型自身做三维度打分：准确性、深度、实用性。

验证数据：
- 大差距pair：3次100%一致（Good 14/15 vs Bad 7/15）
- 小差距pair：能区分1分差异（13 vs 12）
- 比pairwise（只输出A/B）分辨率高
"""
from __future__ import annotations

import re
from dataclasses import dataclass


JUDGE_SYSTEM = (
    "你是回答质量评估器。从三个维度评分（每维度1-5分）：\n"
    "- 准确性：信息是否正确、有无事实错误\n"
    "- 深度：是否深入分析本质、有无洞察\n"
    "- 实用性：用户能否据此采取行动或加深理解\n\n"
    "严格按格式输出，不要解释：准确X 深度X 实用X"
)


@dataclass
class JudgeScore:
    accuracy: int = 3
    depth: int = 3
    utility: int = 3

    @property
    def total(self) -> int:
        return self.accuracy + self.depth + self.utility

    @property
    def normalized(self) -> float:
        return round(self.total / 15.0, 3)

    def to_dict(self) -> dict:
        return {
            "accuracy": self.accuracy,
            "depth": self.depth,
            "utility": self.utility,
            "total": self.total,
            "normalized": self.normalized,
        }


def parse_judge_output(text: str) -> JudgeScore:
    nums = re.findall(r'[准确精确].*?(\d)', text)
    depth_nums = re.findall(r'深度.*?(\d)', text)
    util_nums = re.findall(r'实用.*?(\d)', text)

    if not nums or not depth_nums or not util_nums:
        all_nums = re.findall(r'(\d)', text[:60])
        if len(all_nums) >= 3:
            return JudgeScore(
                accuracy=min(int(all_nums[0]), 5),
                depth=min(int(all_nums[1]), 5),
                utility=min(int(all_nums[2]), 5),
            )
        return JudgeScore()

    return JudgeScore(
        accuracy=min(int(nums[0]), 5),
        depth=min(int(depth_nums[0]), 5),
        utility=min(int(util_nums[0]), 5),
    )


async def judge_response(client, model: str, question: str,
                         response: str) -> JudgeScore:
    try:
        result = await client.chat(
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": "问题：{}\n回答：{}".format(
                    question, response[:500])},
            ],
            model=model,
            max_tokens=30,
            temperature=0.0,
        )
        return parse_judge_output(result)
    except Exception:
        return JudgeScore()


async def compare_responses(client, model: str, question: str,
                            response_a: str, response_b: str) -> dict:
    score_a = await judge_response(client, model, question, response_a)
    score_b = await judge_response(client, model, question, response_b)

    if score_a.total > score_b.total:
        winner = "A"
    elif score_b.total > score_a.total:
        winner = "B"
    else:
        winner = "tie"

    return {
        "score_a": score_a.to_dict(),
        "score_b": score_b.to_dict(),
        "winner": winner,
        "delta": score_a.total - score_b.total,
        "dimension_deltas": {
            "accuracy": score_a.accuracy - score_b.accuracy,
            "depth": score_a.depth - score_b.depth,
            "utility": score_a.utility - score_b.utility,
        },
    }
