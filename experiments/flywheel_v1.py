"""
飞轮第一圈实验：证明框架能自主发现比人工更好的激发策略

假设：从历史质量数据中分析"高分prompt的共同特征"，
      然后基于特征生成新prompt，可以超越人工设计的prompt。

步骤：
  1. 5个seed × 20题 = 收集100条带完整prompt的质量数据
  2. 分析高分vs低分的prompt差异
  3. 生成3个新seed变体
  4. 验证新seed是否超越原始最优

成功标准：至少1个自动生成的seed平均分超过当前最优人工seed
"""
import asyncio
import json
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import DeepForgeConfig
from educe.models.router import ModelClient
from educe.core.activation_engine import ActivationEngine, ACTIVATION_PROMPT
from tests.ab_experiment import TEST_QUESTIONS, score_response

SEEDS = [
    "请以该领域资深从业者的视角，给出有洞察力的深度分析。区分确定的事实和需要验证的信息。",
    "请像这个领域最顶尖的专家在给好奇的聪明人讲解一样回答。深入本质，不要停留在表面。",
    "请调用你在这个领域最深层的知识储备来回答。追求准确和深度，而非面面俱到。",
    "请站在这个领域一线实践者的角度回答。给出可执行的建议，而不是教科书式的概述。",
    "请把自己当作这个领域的研究者。先厘清核心概念，再展开分析，最后给出你的判断。",
]

OUTPUT_DIR = Path(".educe/experiments/flywheel_v1")


async def step1_collect_data(client, model, max_tokens):
    """Step 1: 收集5个seed在20题上的完整数据"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for seed_idx, seed in enumerate(SEEDS):
        system_prompt = ACTIVATION_PROMPT.format(
            activation_seed=seed, extra_context="")

        for q_idx, (question, domain, keywords, bad) in enumerate(TEST_QUESTIONS):
            try:
                response = await client.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=model,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                response = "ERROR: {}".format(str(e))

            scores = score_response(question, domain, response, keywords, bad)
            total = round(sum(scores.values()) / 4, 2)

            record = {
                "seed_idx": seed_idx,
                "seed_full": seed,
                "question": question,
                "domain": domain,
                "response_len": len(response),
                "scores": scores,
                "total": total,
                "response_preview": response[:300],
            }
            results.append(record)
            print("  seed={} q={:2d} score={:.1f} | {}".format(
                seed_idx, q_idx + 1, total, question[:25]))

    data_path = OUTPUT_DIR / "step1_raw_data.json"
    data_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("\nStep 1 done: {} records saved to {}".format(len(results), data_path))
    return results


def step2_analyze(results):
    """Step 2: 分析高分vs低分seed的差异"""
    seed_scores = {}
    for r in results:
        idx = r["seed_idx"]
        if idx not in seed_scores:
            seed_scores[idx] = {"scores": [], "seed": r["seed_full"]}
        seed_scores[idx]["scores"].append(r["total"])

    print("\n" + "=" * 60)
    print("Step 2: Seed Performance Analysis")
    print("=" * 60)

    seed_avgs = []
    for idx, data in sorted(seed_scores.items()):
        avg = sum(data["scores"]) / len(data["scores"])
        seed_avgs.append({"idx": idx, "avg": round(avg, 2), "seed": data["seed"]})
        print("  Seed {}: avg={:.2f} | {}...".format(idx, avg, data["seed"][:40]))

    seed_avgs.sort(key=lambda x: -x["avg"])
    best = seed_avgs[0]
    worst = seed_avgs[-1]

    print("\n  Best:  Seed {} ({:.2f}): {}".format(best["idx"], best["avg"], best["seed"][:50]))
    print("  Worst: Seed {} ({:.2f}): {}".format(worst["idx"], worst["avg"], worst["seed"][:50]))

    # 按领域分析
    domain_seed_scores = {}
    for r in results:
        key = (r["domain"], r["seed_idx"])
        if key not in domain_seed_scores:
            domain_seed_scores[key] = []
        domain_seed_scores[key].append(r["total"])

    print("\n  By domain (best seed for each):")
    domains = sorted(set(r["domain"] for r in results))
    for domain in domains:
        domain_avgs = []
        for idx in range(len(SEEDS)):
            scores = domain_seed_scores.get((domain, idx), [])
            if scores:
                domain_avgs.append((idx, sum(scores) / len(scores)))
        domain_avgs.sort(key=lambda x: -x[1])
        if domain_avgs:
            print("    {:10s} best=seed{} ({:.2f})".format(
                domain, domain_avgs[0][0], domain_avgs[0][1]))

    analysis = {
        "seed_rankings": seed_avgs,
        "best_seed": best,
        "worst_seed": worst,
        "gap": round(best["avg"] - worst["avg"], 2),
    }
    (OUTPUT_DIR / "step2_analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2))
    return analysis


def step3_generate_prompt():
    """Step 3: 生成分析prompt（让Claude/人来分析差异并设计新seed）"""
    analysis_path = OUTPUT_DIR / "step2_analysis.json"
    if not analysis_path.exists():
        print("Run step2 first")
        return

    analysis = json.loads(analysis_path.read_text())
    best = analysis["best_seed"]
    worst = analysis["worst_seed"]

    prompt = """基于以下A/B测试数据，分析高效激发prompt的关键特征，并设计3个更好的变体。

最优seed (平均{best_avg}分):
"{best_seed}"

最差seed (平均{worst_avg}分):
"{worst_seed}"

分差: {gap}分

所有seed排名:
{rankings}

任务：
1. 分析：为什么最优seed比最差seed好？关键差异是什么？
2. 设计3个新的激发seed，尝试超越当前最优。
3. 每个新seed一行，不要其他内容。

格式：
NEW_SEED_1: [新seed内容]
NEW_SEED_2: [新seed内容]
NEW_SEED_3: [新seed内容]
""".format(
        best_avg=best["avg"], best_seed=best["seed"],
        worst_avg=worst["avg"], worst_seed=worst["seed"],
        gap=analysis["gap"],
        rankings="\n".join("  {}. ({:.2f}) {}".format(
            i+1, s["avg"], s["seed"][:60]) for i, s in enumerate(analysis["seed_rankings"]))
    )

    prompt_path = OUTPUT_DIR / "step3_analysis_prompt.txt"
    prompt_path.write_text(prompt)
    print("\nStep 3: Analysis prompt saved to {}".format(prompt_path))
    print("Use this prompt with a strong model to generate new seeds.")
    print("\n" + prompt)
    return prompt


async def step4_validate_new_seeds(client, model, max_tokens, new_seeds):
    """Step 4: 验证新seed是否超越原始最优"""
    print("\n" + "=" * 60)
    print("Step 4: Validating {} new seeds".format(len(new_seeds)))
    print("=" * 60)

    new_results = []
    for seed_idx, seed in enumerate(new_seeds):
        system_prompt = ACTIVATION_PROMPT.format(
            activation_seed=seed, extra_context="")
        seed_scores = []

        for q_idx, (question, domain, keywords, bad) in enumerate(TEST_QUESTIONS):
            try:
                response = await client.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=model,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                response = "ERROR: {}".format(str(e))

            scores = score_response(question, domain, response, keywords, bad)
            total = round(sum(scores.values()) / 4, 2)
            seed_scores.append(total)

        avg = round(sum(seed_scores) / len(seed_scores), 2)
        new_results.append({"seed": seed, "avg": avg, "scores": seed_scores})
        print("  New seed {}: avg={:.2f} | {}...".format(seed_idx, avg, seed[:40]))

    # Compare with original best
    analysis = json.loads((OUTPUT_DIR / "step2_analysis.json").read_text())
    original_best = analysis["best_seed"]["avg"]

    print("\n  Original best: {:.2f}".format(original_best))
    beaten = False
    for i, nr in enumerate(new_results):
        delta = nr["avg"] - original_best
        status = "BETTER" if delta > 0 else "WORSE"
        print("  New seed {}: {:.2f} ({}{:.2f}) → {}".format(
            i, nr["avg"], "+" if delta > 0 else "", delta, status))
        if delta > 0:
            beaten = True

    if beaten:
        print("\n  FLYWHEEL SUCCESS: Auto-generated seed beat human-designed seed!")
    else:
        print("\n  FLYWHEEL NOT YET: No auto-generated seed beat the best human seed.")
        print("  Need to improve analysis method or seed generation approach.")

    (OUTPUT_DIR / "step4_validation.json").write_text(
        json.dumps({"new_results": new_results, "original_best": original_best,
                    "success": beaten}, ensure_ascii=False, indent=2))
    return beaten


async def main():
    config = DeepForgeConfig.load()
    client = ModelClient(
        api_key=config.default_model.api_key,
        base_url=config.default_model.base_url)
    model = config.default_model.model
    max_tokens = config.default_model.max_tokens

    print("Flywheel V1 Experiment")
    print("Model: {}".format(model))
    print("Seeds: {}".format(len(SEEDS)))
    print("Questions: {}".format(len(TEST_QUESTIONS)))
    print()

    # Step 1: Collect data
    print("=" * 60)
    print("Step 1: Collecting data ({}x{} = {} LLM calls)".format(
        len(SEEDS), len(TEST_QUESTIONS), len(SEEDS) * len(TEST_QUESTIONS)))
    print("=" * 60)
    results = await step1_collect_data(client, model, max_tokens)

    # Step 2: Analyze
    analysis = step2_analyze(results)

    # Step 3: Generate prompt for new seeds
    step3_generate_prompt()

    print("\n" + "=" * 60)
    print("NEXT: Use the analysis prompt above to generate new seeds,")
    print("then run step4 with the new seeds to validate.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
