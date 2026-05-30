"""
DeepForge ChecklistJudge — 动态checklist验证

替代打分式judge（天花板效应严重）。
核心思路：不问"好不好"，问"该有的有没有"。

流程：
1. 根据问题自动生成"好回答应有的3-5个关键要点"
2. 逐条检查回答是否覆盖
3. 覆盖率 = 质量分

验证数据：
- Good vs Bad：60% vs 20%（40个百分点差距，无天花板）
- checklist生成质量：5/5高质量
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


CHECKLIST_GEN_SYSTEM = (
    "为以下问题列出一个好回答应该包含的3-5个关键要点。"
    "每行一个要点，用数字编号。只列要点不解释。"
)

CHECKLIST_VERIFY_SYSTEM = (
    "检查回答是否覆盖了以下要点。"
    "逐条判断，每条回复Y（覆盖）或N（未覆盖）。"
    "格式：1.Y 2.N 3.Y ..."
)


@dataclass
class ChecklistResult:
    question: str = ""
    checklist_items: list = field(default_factory=list)
    covered: list = field(default_factory=list)
    coverage: float = 0.0

    def to_dict(self) -> dict:
        return {
            "question": self.question[:60],
            "items": len(self.checklist_items),
            "covered_count": sum(self.covered),
            "coverage": self.coverage,
            "details": list(zip(
                [c[:40] for c in self.checklist_items],
                self.covered)),
        }


async def generate_checklist(client, model: str, question: str) -> list:
    try:
        raw = await client.chat(
            messages=[
                {"role": "system", "content": CHECKLIST_GEN_SYSTEM},
                {"role": "user", "content": question},
            ],
            model=model, max_tokens=150, temperature=0.0)

        items = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                cleaned = re.sub(r'^\d+[.、)\s]+', '', line).strip()
                if cleaned:
                    items.append(cleaned)
        return items[:5]
    except Exception:
        return []


async def verify_checklist(client, model: str, checklist: list,
                           response: str) -> list:
    if not checklist:
        return []

    checklist_text = "\n".join(
        "{}. {}".format(i + 1, item) for i, item in enumerate(checklist))

    try:
        raw = await client.chat(
            messages=[
                {"role": "system", "content": CHECKLIST_VERIFY_SYSTEM},
                {"role": "user", "content": "要点：\n{}\n\n回答：\n{}".format(
                    checklist_text, response[:500])},
            ],
            model=model, max_tokens=50, temperature=0.0)

        covered = []
        for i in range(len(checklist)):
            pattern = r'{}[.、):\s]*[Yy]'.format(i + 1)
            covered.append(bool(re.search(pattern, raw)))
        return covered
    except Exception:
        return [False] * len(checklist)


async def evaluate(client, model: str, question: str,
                   response: str) -> ChecklistResult:
    checklist = await generate_checklist(client, model, question)
    if not checklist:
        return ChecklistResult(question=question)

    covered = await verify_checklist(client, model, checklist, response)
    coverage = sum(covered) / len(covered) if covered else 0.0

    return ChecklistResult(
        question=question,
        checklist_items=checklist,
        covered=covered,
        coverage=round(coverage, 3),
    )


async def compare(client, model: str, question: str,
                  response_a: str, response_b: str) -> dict:
    checklist = await generate_checklist(client, model, question)
    if not checklist:
        return {"winner": "tie", "coverage_a": 0, "coverage_b": 0}

    covered_a = await verify_checklist(client, model, checklist, response_a)
    covered_b = await verify_checklist(client, model, checklist, response_b)

    cov_a = sum(covered_a) / len(covered_a) if covered_a else 0
    cov_b = sum(covered_b) / len(covered_b) if covered_b else 0

    if cov_a > cov_b:
        winner = "A"
    elif cov_b > cov_a:
        winner = "B"
    else:
        winner = "tie"

    a_only = [checklist[i] for i in range(len(checklist))
              if i < len(covered_a) and i < len(covered_b)
              and covered_a[i] and not covered_b[i]]
    b_only = [checklist[i] for i in range(len(checklist))
              if i < len(covered_a) and i < len(covered_b)
              and covered_b[i] and not covered_a[i]]

    return {
        "winner": winner,
        "coverage_a": round(cov_a, 3),
        "coverage_b": round(cov_b, 3),
        "delta": round(cov_a - cov_b, 3),
        "a_advantages": a_only,
        "b_advantages": b_only,
    }
