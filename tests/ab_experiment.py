"""
DeepForge 激发引擎 A/B 实验框架
对比 baseline prompt vs 激发 prompt，用数据说话

评分维度：
1. 准确度：关键事实是否正确（自动检查关键词）
2. 深度：有没有分析/推理，而非只给表面答案
3. 结构：有没有标题/列表/分段，条理是否清晰
4. 置信度标注：有没有标注不确定的部分
"""
from __future__ import annotations

import asyncio
import json
import time
import re
from pathlib import Path
from dataclasses import dataclass, field

BASELINE_PROMPT = "你是一个AI助手，请回答用户的问题。"

TEST_QUESTIONS = [
    # (问题, 领域, 必须包含的关键词列表, 不应该包含的错误)
    # 医学
    ("孩子发烧38.5度应该怎么处理", "medical",
     ["降温", "温度", "医"], []),
    ("长期失眠有什么科学的改善方法", "medical",
     ["睡眠", "规律"], []),

    # 法律
    ("劳动合同到期公司不续签需要赔偿吗", "legal",
     ["赔偿", "补偿", "劳动"], []),
    ("租房合同没到期房东要求搬走怎么办", "legal",
     ["合同", "违约"], []),

    # 数学
    ("证明：任意正整数n，n(n+1)能被2整除", "math",
     ["证明", "偶数"], []),
    ("一个袋子3红球5蓝球，不放回取2个，两个都是红球的概率", "math",
     ["概率", "3/28"], []),

    # 技术
    ("TCP三次握手的过程，第三次丢失会怎样", "tech",
     ["SYN", "ACK"], []),
    ("Redis和Memcached在高并发场景下各自优缺点", "tech",
     ["Redis", "持久化"], []),

    # 科学
    ("光速为什么不能被超越", "science",
     ["光速", "相对论"], []),
    ("mRNA疫苗和传统灭活疫苗的本质区别", "science",
     ["mRNA", "蛋白"], []),

    # 历史
    ("安史之乱为什么是唐朝由盛转衰的转折点", "history",
     ["安史", "唐"], []),
    ("秦始皇统一六国的关键因素有哪些", "history",
     ["秦", "统一"], []),

    # 心理
    ("工作三年感觉没成长很迷茫该怎么办", "psychology",
     ["职业", "成长"], []),
    ("考试前极度焦虑怎么缓解", "psychology",
     ["焦虑", "呼吸"], []),

    # 烹饪
    ("红烧肉怎么做才能肥而不腻入口即化", "cooking",
     ["五花肉", "糖"], []),
    ("糖醋排骨的正宗做法和关键步骤", "cooking",
     ["排骨", "醋"], []),

    # 金融
    ("月收入1万，存款20万，如何规划养老投资", "finance",
     ["投资", "风险"], []),
    ("什么是可转债，什么情况下适合转股", "finance",
     ["可转债", "转股"], []),

    # 教育
    ("高考数学怎么从100分提到130分", "education",
     ["练习", "题"], []),
    ("如何用费曼技巧学习复杂概念", "education",
     ["费曼", "教"], []),
]


@dataclass
class ScoreResult:
    question: str
    domain: str
    variant: str
    response: str = ""
    accuracy: float = 0.0
    depth: float = 0.0
    structure: float = 0.0
    confidence: float = 0.0
    duration: float = 0.0
    total: float = 0.0


def score_response(question: str, domain: str, response: str,
                   required_keywords: list[str], bad_keywords: list[str]) -> dict:
    """自动评分——基于规则，不依赖额外LLM调用"""
    if not response or len(response) < 20:
        return {"accuracy": 0, "depth": 0, "structure": 0, "confidence": 0}

    # 准确度：必须包含的关键词命中率
    hits = sum(1 for kw in required_keywords if kw in response)
    accuracy = (hits / len(required_keywords) * 10) if required_keywords else 5

    # 深度：回复长度 + 分析性词汇
    depth_signals = len(re.findall(r'因为|原因|导致|所以|因此|本质|核心|关键|原理|机制|根本', response))
    length_score = min(len(response) / 200, 5)
    depth = min(length_score + depth_signals * 0.5, 10)

    # 结构：标题/列表/分段
    has_headers = len(re.findall(r'(?:^|\n)#{1,3}\s|(?:^|\n)\*\*[^*]+\*\*[：:]', response)) > 0
    has_lists = len(re.findall(r'(?:^|\n)\s*[\-\•\d]+[.、]', response)) >= 2
    has_sections = response.count('\n\n') >= 2
    structure = (3 if has_headers else 0) + (3 if has_lists else 0) + (2 if has_sections else 0)
    structure = min(structure + 2, 10)

    # 置信度标注
    has_confidence = bool(re.search(r'置信度[：:]\s*\d+%|[✅⚠️]\s*\d*%?', response))
    has_uncertainty = bool(re.search(r'据我了解|不确定|需要确认|需要验证|可能有误|仅供参考|具体.*判断|结合实际', response))
    has_disclaimer = bool(re.search(r'咨询.*专业|建议.*就医|请.*律师|专业.*意见|专业.*指导', response))
    confidence = (4 if has_confidence else 0) + (3 if has_uncertainty else 0) + (3 if has_disclaimer else 0)
    confidence = min(confidence, 10)

    return {
        "accuracy": round(accuracy, 1),
        "depth": round(depth, 1),
        "structure": round(structure, 1),
        "confidence": round(confidence, 1),
    }


async def run_ab_test(model_client, model: str, max_tokens: int = 4096):
    """跑完整A/B测试"""
    results: list[ScoreResult] = []

    for question, domain, keywords, bad in TEST_QUESTIONS:
        for variant, system_prompt in [("baseline", BASELINE_PROMPT), ("activation", None)]:
            if variant == "activation":
                from deepforge.core.activation_engine import ActivationEngine
                engine = ActivationEngine()
                system_prompt = engine.build_activation_prompt(question)

            start = time.time()
            try:
                response = await model_client.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=model,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                response = f"ERROR: {e}"
            dur = round(time.time() - start, 1)

            scores = score_response(question, domain, response, keywords, bad)
            total = round(sum(scores.values()) / 4, 1)

            r = ScoreResult(
                question=question, domain=domain, variant=variant,
                response=response, duration=dur, total=total, **scores,
            )
            results.append(r)
            print(f"  [{variant:10s}] {domain:10s} | {total:4.1f} | {dur}s | {question[:25]}")

    return results


def generate_report(results: list[ScoreResult]) -> str:
    """生成实验报告"""
    baseline = [r for r in results if r.variant == "baseline"]
    activation = [r for r in results if r.variant == "activation"]

    def avg(items, field):
        vals = [getattr(r, field) for r in items if getattr(r, field) > 0]
        return round(sum(vals) / max(len(vals), 1), 2)

    report = []
    report.append("=" * 60)
    report.append("  DeepForge 激发引擎 A/B 实验报告")
    report.append("=" * 60)
    report.append(f"\n  测试问题: {len(TEST_QUESTIONS)} 个 × 10 领域")
    report.append(f"  对比: baseline (通用prompt) vs activation (激发prompt)")

    report.append(f"\n  {'维度':10s} {'Baseline':>10s} {'Activation':>12s} {'提升':>8s}")
    report.append(f"  {'-'*42}")
    for dim in ["accuracy", "depth", "structure", "confidence", "total"]:
        b = avg(baseline, dim)
        a = avg(activation, dim)
        delta = round(a - b, 2)
        sign = "+" if delta > 0 else ""
        report.append(f"  {dim:10s} {b:10.2f} {a:12.2f} {sign}{delta:>7.2f}")

    report.append(f"\n  按领域对比:")
    domains = sorted(set(r.domain for r in results))
    for d in domains:
        b = avg([r for r in baseline if r.domain == d], "total")
        a = avg([r for r in activation if r.domain == d], "total")
        delta = round(a - b, 2)
        sign = "+" if delta > 0 else ""
        report.append(f"    {d:12s} {b:.1f} → {a:.1f} ({sign}{delta})")

    report.append(f"\n  响应时间:")
    report.append(f"    Baseline avg: {avg(baseline, 'duration')}s")
    report.append(f"    Activation avg: {avg(activation, 'duration')}s")

    report.append("\n" + "=" * 60)
    return "\n".join(report)


async def main():
    import sys
    sys.path.insert(0, ".")

    from deepforge.core.config import DeepForgeConfig
    from deepforge.models.router import ModelClient

    config = DeepForgeConfig.load()
    client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)

    print("🧪 DeepForge A/B 实验开始")
    print(f"  模型: {config.default_model.model}")
    print(f"  问题数: {len(TEST_QUESTIONS)}")
    print()

    results = await run_ab_test(client, config.default_model.model)

    report = generate_report(results)
    print(report)

    # 保存结果
    output_dir = Path(".deepforge/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    with open(output_dir / f"ab_test_{ts}.json", "w") as f:
        json.dump([{
            "question": r.question, "domain": r.domain, "variant": r.variant,
            "accuracy": r.accuracy, "depth": r.depth, "structure": r.structure,
            "confidence": r.confidence, "total": r.total, "duration": r.duration,
            "response_len": len(r.response),
        } for r in results], f, ensure_ascii=False, indent=2)

    with open(output_dir / f"ab_report_{ts}.txt", "w") as f:
        f.write(report)

    print(f"\n  结果保存: {output_dir}/ab_test_{ts}.json")
    print(f"  报告保存: {output_dir}/ab_report_{ts}.txt")


if __name__ == "__main__":
    asyncio.run(main())
