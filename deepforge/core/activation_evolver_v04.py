"""
激发引擎 v0.4 — 主动演化循环 MVP

可验证评分 + 定向变异 + hold-out 验证
领域：逻辑推理（答案可机械判定）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("deepforge.evolution")

BASE_URL = os.environ.get("DEEPFORGE_BASE_URL", "")
API_KEY = os.environ.get("DEEPFORGE_API_KEY", "")


# ═══ Benchmark 题库（可验证，答案唯一）═══

TRAIN_QUESTIONS = [
    {"q": "一个农夫有17只羊，除了9只以外都死了，还剩几只？", "a": "9", "domain": "logic"},
    {"q": "如果3个人3分钟能做3个产品，那100个人100分钟能做多少个产品？", "a": "10000", "domain": "math"},
    {"q": "一个房间有4个角落，每个角落有1只猫，每只猫面前有3只猫，请问房间里一共有几只猫？", "a": "4", "domain": "logic"},
    {"q": "鱼缸里有10条鱼，死了2条，还有几条在鱼缸里？", "a": "10", "domain": "logic"},
    {"q": "一只蜗牛在10米的井底，白天爬3米，晚上滑2米。第几天能爬出来？", "a": "8", "domain": "math"},
    {"q": "树上有10只鸟，猎人打死了1只，还有几只在树上？", "a": "0", "domain": "logic"},
    {"q": "一个数除以2余1，除以3余2，除以5余4。这个数最小是几？", "a": "29", "domain": "math"},
    {"q": "小明比小红大5岁，20年后小明比小红大几岁？", "a": "5", "domain": "logic"},
    {"q": "1+2+3+...+100等于多少？", "a": "5050", "domain": "math"},
    {"q": "一根绳子对折3次后剪一刀，变成几段？", "a": "9", "domain": "logic"},
]

HOLDOUT_QUESTIONS = [
    {"q": "小明有5个苹果，给了小红2个，小红又给了小明1个。小明现在有几个？", "a": "4", "domain": "logic"},
    {"q": "100的阶乘末尾有多少个零？", "a": "24", "domain": "math"},
    {"q": "从1到100中，包含数字7的数有多少个？", "a": "19", "domain": "math"},
    {"q": "一辆公交车上有7个人，到第一站下了2个上了5个，到第二站下了3个上了1个，现在车上有几个人？", "a": "8", "domain": "logic"},
    {"q": "两个父亲两个儿子分3条鱼，每人分1条刚好。为什么？", "a": "祖孙三代", "domain": "logic"},
]


# ═══ Seed 定义 ═══

@dataclass
class Seed:
    id: str
    text: str  # 注入 system prompt 的思维引导语
    generation: int = 0
    fitness: float = 0.0
    parent_id: Optional[str] = None

BASELINE_SEED = Seed(
    id="baseline",
    text="请仔细思考题目的每个条件，注意可能的陷阱和常识误区。一步步推理，最后给出明确的数字答案。",
    generation=0,
)


# ═══ 模型调用 ═══

async def call_model(session: aiohttp.ClientSession, system: str, user_msg: str) -> str:
    payload = {
        "model": "qwen36",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        "max_tokens": 500, "temperature": 0.3,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200: return ""
            data = await resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return ""


# ═══ 评分（可验证，零主观）═══

def extract_answer(response: str) -> str:
    """从模型回复中提取数字答案"""
    # 尝试找最后一个独立数字
    numbers = re.findall(r'\b(\d+)\b', response)
    if numbers:
        return numbers[-1]
    # 尝试中文数字
    cn_nums = re.findall(r'[零一二三四五六七八九十百千万]+', response)
    if cn_nums:
        return cn_nums[-1]
    return response.strip()[-10:]


def check_answer(response: str, correct: str) -> bool:
    """判定答案是否正确"""
    extracted = extract_answer(response)
    # 直接匹配
    if extracted == correct:
        return True
    # 答案在回复中出现
    if correct in response:
        return True
    return False


# ═══ 评估 ═══

async def evaluate_seed(session: aiohttp.ClientSession, seed: Seed, questions: list[dict]) -> tuple[float, list[dict]]:
    """评估一个 seed 在题库上的表现，返回 (pass_rate, details)"""
    system = f"你是一个善于逻辑推理的助手。\n\n## 思维引导\n{seed.text}"
    results = []

    for q in questions:
        resp = await call_model(session, system, q["q"])
        correct = check_answer(resp, q["a"])
        results.append({"q": q["q"], "a": q["a"], "response": resp[:100], "correct": correct})
        await asyncio.sleep(0.3)

    pass_rate = sum(1 for r in results if r["correct"]) / len(results)
    return pass_rate, results


# ═══ 定向变异 ═══

async def mutate_seed(session: aiohttp.ClientSession, parent: Seed, failed_questions: list[dict], n: int = 4) -> list[Seed]:
    """基于失败题目定向生成变异 seed"""
    failed_desc = "\n".join(f"- {q['q']}（正确答案：{q['a']}）" for q in failed_questions[:3])

    mutants = []
    for i in range(n):
        prompt = f"""当前的思维引导语是：
"{parent.text}"

但在以下题目上失败了：
{failed_desc}

请改写思维引导语，使其能帮助答对这类题目。要求：
- 保持简洁（1-3句话）
- 加入能避免这类错误的思维策略
- 变体{i+1}：{'尝试完全不同的角度' if i >= 2 else '在原有基础上微调'}

只输出改写后的引导语，不要解释："""

        resp = await call_model(session, "你是一个 prompt 优化专家。", prompt)
        if resp:
            mutants.append(Seed(
                id=f"gen{parent.generation+1}-mut{i}",
                text=resp.strip().strip('"').strip("'")[:200],
                generation=parent.generation + 1,
                parent_id=parent.id,
            ))
        await asyncio.sleep(0.3)

    return mutants


# ═══ 主循环 ═══

async def run_evolution(max_generations: int = 5):
    """主动演化循环"""
    print("=" * 60)
    print("  激发引擎 v0.4 — 主动演化循环 MVP")
    print(f"  训练题: {len(TRAIN_QUESTIONS)} | Hold-out: {len(HOLDOUT_QUESTIONS)}")
    print(f"  最大代数: {max_generations} | 变异体/代: 4")
    print("=" * 60)

    connector = aiohttp.TCPConnector(limit=5)
    best = BASELINE_SEED
    history = []
    no_improve_count = 0

    async with aiohttp.ClientSession(connector=connector) as session:
        # Gen 0: 评估 baseline
        print(f"\n[Gen 0] 评估 baseline seed...")
        best.fitness, details = await evaluate_seed(session, best, TRAIN_QUESTIONS)
        failed = [TRAIN_QUESTIONS[i] for i, d in enumerate(details) if not d["correct"]]
        print(f"  Baseline pass rate: {best.fitness:.0%} ({int(best.fitness*len(TRAIN_QUESTIONS))}/{len(TRAIN_QUESTIONS)})")
        print(f"  失败题: {len(failed)}")
        for d in details:
            status = "✓" if d["correct"] else "✗"
            print(f"    {status} {d['q'][:30]}... → {d['response'][:30]}")

        history.append({"gen": 0, "best_id": best.id, "fitness": best.fitness, "text": best.text[:80]})

        # 演化循环
        for gen in range(1, max_generations + 1):
            if not failed:
                print(f"\n[Gen {gen}] 完美通过，无需演化！")
                break

            if no_improve_count >= 3:
                print(f"\n[Gen {gen}] 连续3代无改善，收敛停止。")
                break

            print(f"\n[Gen {gen}] 定向变异（{len(failed)} 题失败）...")
            mutants = await mutate_seed(session, best, failed)
            print(f"  生成 {len(mutants)} 个变异体")

            # 评估所有变异体
            best_candidate = best
            for mut in mutants:
                mut.fitness, _ = await evaluate_seed(session, mut, TRAIN_QUESTIONS)
                print(f"    {mut.id}: {mut.fitness:.0%} | {mut.text[:50]}...")
                if mut.fitness > best_candidate.fitness:
                    best_candidate = mut

            # 选拔
            if best_candidate.fitness > best.fitness:
                print(f"  ✓ 新 best: {best_candidate.id} ({best.fitness:.0%} → {best_candidate.fitness:.0%})")
                best = best_candidate
                no_improve_count = 0
                # 重新评估失败题
                _, details = await evaluate_seed(session, best, TRAIN_QUESTIONS)
                failed = [TRAIN_QUESTIONS[i] for i, d in enumerate(details) if not d["correct"]]
            else:
                print(f"  ○ 无改善，保持 best ({best.fitness:.0%})")
                no_improve_count += 1

            history.append({"gen": gen, "best_id": best.id, "fitness": best.fitness, "text": best.text[:80]})

        # Hold-out 验证
        print(f"\n{'='*60}")
        print("  Hold-out 验证（防过拟合）")
        print(f"{'='*60}")

        baseline_holdout, _ = await evaluate_seed(session, BASELINE_SEED, HOLDOUT_QUESTIONS)
        best_holdout, holdout_details = await evaluate_seed(session, best, HOLDOUT_QUESTIONS)

        print(f"  Baseline hold-out: {baseline_holdout:.0%}")
        print(f"  Final best hold-out: {best_holdout:.0%}")
        improvement = best_holdout - baseline_holdout
        print(f"  改善: {improvement:+.0%}")
        print(f"  验证: {'✅ 通过' if improvement > 0 else '⚠️ 未提升（可能过拟合）'}")

        for d in holdout_details:
            status = "✓" if d["correct"] else "✗"
            print(f"    {status} {d['q'][:40]}... → {d['response'][:30]}")

    # 记录
    print(f"\n{'='*60}")
    print("  演化历史")
    print(f"{'='*60}")
    for h in history:
        print(f"  Gen {h['gen']}: {h['fitness']:.0%} | {h['best_id']} | {h['text']}")

    print(f"\n  Final best seed: {best.text}")

    # 保存结果
    output = {
        "version": "v0.4-mvp",
        "baseline_train": BASELINE_SEED.fitness,
        "final_train": best.fitness,
        "baseline_holdout": baseline_holdout,
        "final_holdout": best_holdout,
        "improvement_holdout": improvement,
        "generations": len(history),
        "final_seed": best.text,
        "history": history,
    }
    output_path = Path(".deepforge/evolution_v04_result.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n  结果保存: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_evolution(max_generations=5))
