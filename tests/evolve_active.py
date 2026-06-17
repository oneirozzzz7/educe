"""
Educe v0.4: 主动演化循环
不等用户使用，用合成评测主动筛选最优激发语。

流程：
1. 读取当前弱领域和 best seed
2. 对每个弱领域生成 5 个变异 seed
3. 每个变异跑 2 道该领域的 benchmark 题
4. 取得分最高的替代当前 best seed
5. 重复直到收敛或 max_generations
"""
import asyncio
import json
import time
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import DeepForgeConfig
from educe.core.activation_engine import (
    ActivationEngine, ACTIVATION_PROMPT, REASONING_CHAINS, DOMAIN_LABELS
)
from educe.core.activation_evolver import ActivationEvolver, SEED_ELEMENTS, SEED_POOL
from educe.models.router import ModelClient

# ═══ 评测题库（按领域） ═══

DOMAIN_QUESTIONS = {
    "通用": [
        ("如何有效地做时间管理", ["时间", "管理", "优先级"], ["番茄", "矩阵", "GTD"]),
        ("远程办公的利弊分析", ["远程", "办公"], ["沟通", "自律", "效率"]),
        ("如何培养批判性思维", ["批判", "思维"], ["质疑", "证据", "逻辑"]),
    ],
    "教育": [
        ("如何高效学习一门新编程语言", ["学习", "编程"], ["项目", "实践", "循序渐进"]),
        ("费曼学习法的核心原理和实践方法", ["费曼", "学习"], ["教别人", "简化", "类比"]),
        ("如何帮助孩子建立阅读习惯", ["阅读", "习惯"], ["兴趣", "环境", "坚持"]),
    ],
    "写作": [
        ("写一首关于秋天的现代诗", ["秋"], ["意象", "节奏"]),
        ("如何写好一篇技术博客的开头", ["开头", "博客"], ["问题", "吸引", "痛点"]),
        ("描述一个雨天的城市，200字", ["雨", "城市"], ["感官", "细节", "氛围"]),
    ],
    "宠物": [
        ("猫咪呕吐的常见原因和处理方法", ["呕吐", "猫"], ["毛球", "饮食", "就医"]),
        ("如何训练狗狗定点排泄", ["训练", "排泄"], ["奖励", "耐心", "时机"]),
        ("养仓鼠需要注意什么", ["仓鼠"], ["温度", "笼子", "食物"]),
    ],
    "医学": [
        ("孩子发烧38.5度应该怎么处理", ["降温", "温度", "医"], ["物理降温", "布洛芬", "就医"]),
        ("长期失眠有什么科学的改善方法", ["睡眠", "规律"], ["褪黑素", "认知行为", "光照"]),
    ],
    "技术": [
        ("Python中GIL的作用和局限性", ["GIL", "线程"], ["全局解释器锁", "多进程", "CPU密集"]),
        ("什么是CAP定理，举例说明", ["CAP", "一致性"], ["可用性", "分区容错", "分布式"]),
    ],
    "法律": [
        ("劳动合同到期公司不续签需要赔偿吗", ["赔偿", "补偿", "劳动"], ["N+1", "劳动合同法", "经济补偿"]),
        ("租房合同没到期房东要求搬走怎么办", ["合同", "违约"], ["违约金", "协商", "仲裁"]),
    ],
}

# ═══ 评分（复用 benchmark 逻辑）═══

DEPTH_SIGNALS = [
    "原因", "因为", "分析", "本质", "根本", "背后", "深层",
    "首先", "其次", "最后", "另一方面", "值得注意",
    "建议", "方案", "策略", "权衡", "取舍",
    "研究表明", "数据显示", "根据", "证据",
]

STRUCTURE_SIGNALS = ["#", "##", "**", "- ", "1.", "2.", "3."]


def score_response(response: str, keywords: list[str], depth_keywords: list[str]) -> float:
    if not response:
        return 0.0
    text = response.lower()
    all_kw = keywords + depth_keywords
    accuracy = sum(1 for kw in all_kw if kw.lower() in text) / len(all_kw) if all_kw else 0
    depth = min(sum(1 for s in DEPTH_SIGNALS if s in response) / 8.0, 1.0)
    structure = min(sum(1 for s in STRUCTURE_SIGNALS if s in response) / 4.0, 1.0)
    return accuracy * 0.4 + depth * 0.3 + structure * 0.3


# ═══ 演化核心 ═══

def generate_variants(n: int = 5) -> list[str]:
    """生成 n 个随机变异 seed"""
    rng = random.Random(time.time())
    variants = []
    for _ in range(n):
        p = rng.choice(SEED_ELEMENTS["perspective"])
        g = rng.choice(SEED_ELEMENTS["goal"])
        c = rng.choice(SEED_ELEMENTS["constraint"])
        variants.append(f"请{p}，{g}。{c}。")
    return variants


def build_prompt_with_seed(seed: str, question: str, domain_key: str) -> str:
    """用指定 seed 构建完整激发 prompt"""
    chain = REASONING_CHAINS.get(domain_key, REASONING_CHAINS["general"])
    extra = f"\n## 推理路径\n按此路径展开分析：{chain}"
    return ACTIVATION_PROMPT.format(activation_seed=seed, extra_context=extra)


async def evaluate_seed(client: ModelClient, model: str, seed: str, domain_key: str, questions: list) -> float:
    """对一个 seed 在给定领域跑所有题目，返回平均分"""
    scores = []
    for question, keywords, depth_kw in questions:
        prompt = build_prompt_with_seed(seed, question, domain_key)
        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": question},
                ],
                model=model, temperature=0.3, max_tokens=1500,
            )
            s = score_response(response or "", keywords, depth_kw)
            scores.append(s)
        except Exception:
            scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0


async def evolve_domain(client: ModelClient, model: str, domain_key: str, domain_label: str,
                        current_best_seed: str, questions: list, n_variants: int = 5) -> dict:
    """对一个领域做一轮主动演化"""
    print(f"\n  [{domain_label}] 当前 best seed: \"{current_best_seed[:40]}...\"")

    # 评估当前 best
    best_score = await evaluate_seed(client, model, current_best_seed, domain_key, questions)
    print(f"    当前得分: {best_score:.3f}")

    # 生成变异并评估
    variants = generate_variants(n_variants)
    best_variant = None
    best_variant_score = best_score

    for i, variant in enumerate(variants):
        score = await evaluate_seed(client, model, variant, domain_key, questions)
        marker = "★" if score > best_variant_score else " "
        print(f"    变异{i+1}: {score:.3f} {marker} \"{variant[:50]}...\"")
        if score > best_variant_score:
            best_variant_score = score
            best_variant = variant

    improvement = best_variant_score - best_score
    if best_variant:
        print(f"    ✓ 发现更优 seed! +{improvement:.3f}")
    else:
        print(f"    · 未超越当前 best")

    return {
        "domain": domain_label,
        "domain_key": domain_key,
        "previous_best_score": best_score,
        "new_best_score": best_variant_score,
        "improvement": improvement,
        "new_seed": best_variant,
        "all_variants_scores": [],  # simplified
    }


async def main():
    cfg = DeepForgeConfig.load()
    model = cfg.default_model.model
    client = ModelClient(api_key=cfg.default_model.api_key, base_url=cfg.default_model.base_url)

    # Load evolver state
    evolver = ActivationEvolver()
    stats = evolver.get_stats()

    print("═══ Educe v0.4: 主动演化循环 ═══")
    print(f"模型: {model}")
    print(f"当前代数: {stats['generation']}")
    print(f"已优化领域: {stats['domains_optimized']}")
    print()

    # Find weak domains from domain_stats
    domain_stats_path = Path(".educe/feedback/domain_stats.json")
    if domain_stats_path.exists():
        domain_stats = json.loads(domain_stats_path.read_text())
        avg_quality = sum(d["avg_quality"] for d in domain_stats.values()) / len(domain_stats)
        weak_domains = [(label, d) for label, d in domain_stats.items()
                        if d["avg_quality"] < avg_quality - 0.03]
        weak_domains.sort(key=lambda x: x[1]["avg_quality"])
    else:
        weak_domains = [("通用", {"avg_quality": 0.5}), ("写作", {"avg_quality": 0.4})]

    print(f"全局平均质量: {avg_quality:.3f}")
    print(f"弱领域 ({len(weak_domains)}):")
    for label, d in weak_domains:
        print(f"  {label}: {d['avg_quality']:.3f}")

    # Run evolution for each weak domain
    MAX_GENERATIONS = 3
    N_VARIANTS = 5
    results = []

    for gen in range(MAX_GENERATIONS):
        print(f"\n{'═'*50}")
        print(f"  Generation {stats['generation'] + gen + 1}")
        print(f"{'═'*50}")

        gen_improved = False
        for domain_label, dstats in weak_domains[:4]:
            # Map label to key
            domain_key = next((k for k, v in DOMAIN_LABELS.items() if v == domain_label), "general")
            questions = DOMAIN_QUESTIONS.get(domain_key, DOMAIN_QUESTIONS.get("通用"))
            if not questions:
                continue

            # Get current best seed for this domain
            current_best = evolver._state.get("domain_best_seeds", {}).get(domain_label, SEED_POOL[0])

            result = await evolve_domain(
                client, model, domain_key, domain_label,
                current_best, questions, N_VARIANTS
            )
            results.append(result)

            # Update evolver state if improved
            if result["new_seed"]:
                evolver._state.setdefault("domain_best_seeds", {})[domain_label] = result["new_seed"]
                evolver._state.setdefault("seed_pool", []).append(result["new_seed"])
                gen_improved = True

        evolver._state["generation"] = evolver._state.get("generation", 0) + 1
        evolver._state["last_evolved"] = time.time()
        evolver._save_state()

        if not gen_improved:
            print(f"\n  收敛：本代无改善，停止演化")
            break

    # Summary
    print(f"\n\n{'═'*50}")
    print(f"  演化总结")
    print(f"{'═'*50}")
    improved_count = sum(1 for r in results if r["new_seed"])
    print(f"  总轮次: {len(results)}")
    print(f"  成功改善: {improved_count}")
    print()
    for r in results:
        marker = "✓" if r["new_seed"] else "·"
        print(f"  {marker} [{r['domain']}] {r['previous_best_score']:.3f} → {r['new_best_score']:.3f} ({'+' if r['improvement']>0 else ''}{r['improvement']:.3f})")
        if r["new_seed"]:
            print(f"      新seed: \"{r['new_seed'][:60]}...\"")

    # Save report
    output_dir = Path(".educe/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"evolution_v04_{ts}.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n  报告保存: {report_path}")
    print(f"  最终代数: {evolver._state.get('generation', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
