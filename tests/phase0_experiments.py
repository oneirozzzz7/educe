"""
Phase 0 假设验证实验
不修改框架代码，独立实验脚本
"""
import asyncio
import json
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, ".")

from deepforge.core.config import DeepForgeConfig
from deepforge.models.router import ModelClient

config = DeepForgeConfig.load()
client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)

RESULTS_DIR = Path("docs/experiments")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════
# 假设1：弱模型能否从conversation history正确理解跨轮意图
# ═══════════════════════════════════════

JUDGE_PROMPT = """判断用户是否需要你编写代码/网页/工具/游戏。
- 需要编程 → 只回复：NEED_CODE
- 不需要 → 只回复：NO_CODE"""

SCENARIOS_H1 = [
    {
        "name": "代码后聊天",
        "turns": [
            {"role": "user", "content": "做一个番茄钟网页"},
            {"role": "assistant", "content": "```filepath:index.html\n<!DOCTYPE html><html><head><title>番茄钟</title></head><body><h1>番茄钟</h1><script>/* timer code */</script></body></html>\n```"},
            {"role": "user", "content": "什么是人工智能"},
        ],
        "expected": "NO_CODE",
        "reason": "问AI知识，不需要代码",
    },
    {
        "name": "代码后修改",
        "turns": [
            {"role": "user", "content": "做一个计算器"},
            {"role": "assistant", "content": "```filepath:calculator.html\n<!DOCTYPE html><html><head><title>计算器</title></head><body>...</body></html>\n```"},
            {"role": "user", "content": "改成红色主题"},
        ],
        "expected": "NEED_CODE",
        "reason": "要修改刚才的代码",
    },
    {
        "name": "代码后感谢",
        "turns": [
            {"role": "user", "content": "做一个贪吃蛇游戏"},
            {"role": "assistant", "content": "```filepath:snake.html\n<!DOCTYPE html>...\n```"},
            {"role": "user", "content": "谢谢，很好玩"},
        ],
        "expected": "NO_CODE",
        "reason": "感谢，不需要代码",
    },
    {
        "name": "聊天后要做工具",
        "turns": [
            {"role": "user", "content": "量子计算是什么"},
            {"role": "assistant", "content": "量子计算是利用量子力学原理进行计算的技术..."},
            {"role": "user", "content": "帮我做一个密码生成器"},
        ],
        "expected": "NEED_CODE",
        "reason": "明确要做工具",
    },
    {
        "name": "代码→聊天→再改代码",
        "turns": [
            {"role": "user", "content": "做一个BMI计算器"},
            {"role": "assistant", "content": "```filepath:bmi.html\n<!DOCTYPE html>...\n```"},
            {"role": "user", "content": "今天天气怎么样"},
            {"role": "assistant", "content": "我无法查看实时天气，建议查看天气预报APP。"},
            {"role": "user", "content": "把刚才的BMI计算器加个历史记录功能"},
        ],
        "expected": "NEED_CODE",
        "reason": "回到之前的代码修改",
    },
    {
        "name": "论文讨论不是代码",
        "turns": [
            {"role": "user", "content": "做一个坦克大战游戏"},
            {"role": "assistant", "content": "```filepath:tank-battle.html\n<!DOCTYPE html>...\n```"},
            {"role": "user", "content": "上面提及的论文对自进化有什么参考价值吗"},
        ],
        "expected": "NO_CODE",
        "reason": "问论文，不是改代码（即使上一轮是代码）",
    },
    {
        "name": "模糊请求-帮我看看",
        "turns": [
            {"role": "user", "content": "红烧肉怎么做"},
            {"role": "assistant", "content": "红烧肉做法：1. 五花肉切块..."},
            {"role": "user", "content": "帮我看看这个问题"},
        ],
        "expected": "NO_CODE",
        "reason": "模糊请求但上下文是聊天",
    },
    {
        "name": "模糊请求-帮我搞一下",
        "turns": [
            {"role": "user", "content": "做一个待办清单"},
            {"role": "assistant", "content": "```filepath:todo.html\n<!DOCTYPE html>...\n```"},
            {"role": "user", "content": "帮我搞一下，加个删除功能"},
        ],
        "expected": "NEED_CODE",
        "reason": "模糊请求但上下文是代码修改",
    },
]

async def test_hypothesis_1():
    """假设1：弱模型能否从history判断意图"""
    print("\n" + "=" * 60)
    print("假设1：弱模型能否从conversation history理解跨轮意图")
    print("=" * 60)

    results = []
    for scenario in SCENARIOS_H1:
        # 把history+当前问题一起发给模型判断
        messages = [{"role": "system", "content": JUDGE_PROMPT}]
        messages.extend(scenario["turns"])

        try:
            response = await client.chat(
                messages=messages,
                model=config.default_model.model,
                max_tokens=10,
                temperature=0.0,
            )
            judgment = "NEED_CODE" if "NEED_CODE" in response else "NO_CODE"
        except Exception as e:
            judgment = f"ERROR: {e}"

        correct = judgment == scenario["expected"]
        results.append({
            "name": scenario["name"],
            "expected": scenario["expected"],
            "got": judgment,
            "correct": correct,
            "reason": scenario["reason"],
        })

        print(f"  {'✅' if correct else '❌'} {scenario['name']}: "
              f"期望{scenario['expected']} 得到{judgment}")

    accuracy = sum(1 for r in results if r["correct"]) / len(results)
    print(f"\n  准确率: {accuracy:.0%} ({sum(1 for r in results if r['correct'])}/{len(results)})")

    conclusion = ""
    if accuracy >= 0.875:  # 7/8
        conclusion = "弱模型能从history理解意图——不需要ContextAnalyzer"
    elif accuracy >= 0.625:  # 5/8
        conclusion = "弱模型部分理解——需要轻量辅助但不需要完整ContextAnalyzer"
    else:
        conclusion = "弱模型不能理解——需要框架辅助路由"

    print(f"  结论: {conclusion}")

    return {"hypothesis": 1, "accuracy": accuracy, "conclusion": conclusion, "details": results}


# ═══════════════════════════════════════
# 假设4：激发语差异是否大于随机噪声
# （先跑假设4因为不需要多轮对话，更快）
# ═══════════════════════════════════════

SEEDS = [
    "请像这个领域最顶尖的专家在给好奇的聪明人讲解一样回答。深入本质，不要停留在表面。",
    "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。",
    "请调用你在这个领域最深层的知识储备来回答。追求准确和深度，而非面面俱到。",
]

H4_QUESTIONS = [
    ("光速为什么不能被超越", ["光速", "相对论"]),
    ("TCP三次握手的过程", ["SYN", "ACK"]),
    ("红烧肉怎么做才好吃", ["五花肉", "糖"]),
    ("什么是量子纠缠", ["量子", "纠缠"]),
    ("劳动合同到期不续签", ["赔偿", "补偿"]),
]

async def test_hypothesis_4():
    """假设4：激发语差异 vs 随机噪声"""
    print("\n" + "=" * 60)
    print("假设4：激发语差异是否大于LLM输出的随机噪声")
    print("=" * 60)

    # 每个变体×每题×跑2次（本来应该3次但时间有限）
    all_scores = {i: [] for i in range(len(SEEDS))}

    for seed_idx, seed in enumerate(SEEDS):
        for run in range(2):
            run_scores = []
            for q, keywords in H4_QUESTIONS:
                try:
                    r = await client.chat(
                        messages=[
                            {"role": "system", "content": f"你是DeepForge智能助手。{seed}"},
                            {"role": "user", "content": q},
                        ],
                        model=config.default_model.model,
                        max_tokens=4096,
                    )
                    # 简单评分：关键词命中 + 长度
                    kw_score = sum(1 for kw in keywords if kw in r) / len(keywords) * 5
                    len_score = min(len(r) / 500, 5)
                    score = kw_score + len_score
                    run_scores.append(score)
                except:
                    run_scores.append(0)

            avg = sum(run_scores) / len(run_scores)
            all_scores[seed_idx].append(avg)
            print(f"  变体{seed_idx} run{run+1}: {avg:.2f}")

    # 计算变体间方差 vs 同变体方差
    import statistics

    variant_means = [statistics.mean(scores) for scores in all_scores.values()]
    variant_variance = statistics.variance(variant_means) if len(variant_means) > 1 else 0

    within_variances = []
    for scores in all_scores.values():
        if len(scores) > 1:
            within_variances.append(statistics.variance(scores))
    avg_within_variance = statistics.mean(within_variances) if within_variances else 0

    print(f"\n  变体间方差: {variant_variance:.4f}")
    print(f"  同变体内方差(随机噪声): {avg_within_variance:.4f}")

    significant = variant_variance > avg_within_variance * 2
    conclusion = ""
    if significant:
        conclusion = "激发语差异显著——值得做演化优化"
    else:
        conclusion = "激发语差异不显著——不需要在演化方向投入"

    print(f"  结论: {conclusion}")

    return {
        "hypothesis": 4,
        "variant_variance": variant_variance,
        "within_variance": avg_within_variance,
        "significant": significant,
        "conclusion": conclusion,
        "variant_means": variant_means,
    }


async def main():
    print("╔══════════════════════════════════╗")
    print("║  Phase 0: 基础假设验证           ║")
    print(f"║  模型: {config.default_model.model:<25}║")
    print("╚══════════════════════════════════╝")

    all_results = {}

    # 假设1
    h1 = await test_hypothesis_1()
    all_results["hypothesis_1"] = h1

    # 假设4（先跑这个，快）
    h4 = await test_hypothesis_4()
    all_results["hypothesis_4"] = h4

    # 保存结果
    output = RESULTS_DIR / "phase0_results.json"
    with open(output, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n结果保存: {output}")

    # 假设2和3需要WebSocket和更复杂的setup，单独跑
    print("\n假设2（知识注入效果）和假设3（信号检测准确率）需要后端运行，稍后验证。")


if __name__ == "__main__":
    asyncio.run(main())
