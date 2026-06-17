"""
Educe 激发引擎 A/B/C 对比实验
验证框架核心价值：激发 prompt 是否让模型产出更好的回答

三组对比：
  A: Baseline — 最简 system prompt
  B: 激发引擎 — ActivationEngine.build_activation_prompt()
  C: 激发+推理链 — B + REASONING_CHAINS 注入

评分维度：
  1. 准确度 — 关键词命中率
  2. 深度 — 分析/推理信号词
  3. 结构 — 标题/列表/分段
  4. 专业度 — 术语使用、逻辑性
"""
import asyncio
import json
import time
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

from deepforge.core.config import DeepForgeConfig
from deepforge.core.activation_engine import (
    ActivationEngine, REASONING_CHAINS, DEFAULT_ACTIVATION_SEED
)
from deepforge.models.router import ModelClient

# ═══ 测试集 ═══

TEST_QUESTIONS = [
    # (问题, 领域, 必须包含的关键词, 深度关键词)
    ("孩子发烧38.5度应该怎么处理", "medical",
     ["降温", "温度", "医"], ["物理降温", "布洛芬", "就医"]),
    ("长期失眠有什么科学的改善方法", "medical",
     ["睡眠", "规律"], ["褪黑素", "认知行为", "光照"]),

    ("劳动合同到期公司不续签需要赔偿吗", "legal",
     ["赔偿", "补偿", "劳动"], ["N+1", "劳动合同法", "经济补偿"]),
    ("租房合同没到期房东要求搬走怎么办", "legal",
     ["合同", "违约"], ["违约金", "协商", "仲裁"]),

    ("证明：任意正整数n，n(n+1)能被2整除", "math",
     ["证明", "偶数"], ["奇偶", "连续", "必有一个"]),
    ("一个袋子3红球5蓝球，不放回取2个，两个都是红球的概率", "math",
     ["概率"], ["3/28", "组合", "C"]),

    ("Python中GIL的作用和局限性", "tech",
     ["GIL", "线程"], ["全局解释器锁", "多进程", "CPU密集"]),
    ("什么是CAP定理，举例说明", "tech",
     ["CAP", "一致性"], ["可用性", "分区容错", "分布式"]),

    ("如何用50万在2024年做资产配置", "finance",
     ["配置", "风险"], ["股债", "分散", "流动性"]),
    ("可转债的核心价值是什么", "finance",
     ["可转债"], ["下有保底", "转股", "溢价"]),

    ("清朝闭关锁国政策的深层原因和后果", "history",
     ["闭关锁国", "清"], ["自给自足", "鸦片战争", "技术落后"]),
    ("二战后马歇尔计划的真实目的", "history",
     ["马歇尔", "援助"], ["遏制", "市场", "冷战"]),

    ("量子纠缠的通俗解释", "science",
     ["量子", "纠缠"], ["超距", "测量", "贝尔不等式"]),
    ("为什么天空是蓝色的", "science",
     ["散射", "蓝"], ["瑞利散射", "波长", "大气"]),

    ("写一首关于秋天的现代诗", "writing",
     ["秋"], ["意象", "节奏"]),

    ("孩子不愿意上学怎么沟通", "psychology",
     ["沟通", "孩子"], ["倾听", "情绪", "原因"]),

    ("做红烧肉的关键步骤和诀窍", "cooking",
     ["红烧肉", "糖色"], ["五花肉", "小火", "冰糖"]),

    ("如何高效学习一门新编程语言", "education",
     ["学习", "编程"], ["项目", "实践", "循序渐进"]),

    ("解释区块链的工作原理", "tech",
     ["区块链", "去中心化"], ["哈希", "共识", "不可篡改"]),

    ("比较React和Vue的优劣", "tech",
     ["React", "Vue"], ["虚拟DOM", "生态", "学习曲线"]),
]

# ═══ Prompt 变体 ═══

BASELINE_PROMPT = "你是一个AI助手，请回答用户的问题。"


def build_variant_b_prompt(question: str, domain: str) -> str:
    """激发引擎 prompt（不含推理链）"""
    engine = ActivationEngine()
    return engine.build_activation_prompt(question, "", [], inject_chain=False)


def build_variant_c_prompt(question: str, domain: str) -> str:
    """激发引擎 + 推理链"""
    engine = ActivationEngine()
    return engine.build_activation_prompt(question, "", [], inject_chain=True)


# ═══ 评分 ═══

DEPTH_SIGNALS = [
    "原因", "因为", "分析", "本质", "根本", "背后", "深层",
    "首先", "其次", "最后", "另一方面", "值得注意",
    "建议", "方案", "策略", "权衡", "取舍",
    "研究表明", "数据显示", "根据", "证据",
    "需要注意", "风险", "前提", "假设",
]

STRUCTURE_SIGNALS = ["#", "##", "**", "- ", "1.", "2.", "3."]


@dataclass
class Score:
    accuracy: float = 0.0   # 关键词命中率
    depth: float = 0.0      # 深度信号词密度
    structure: float = 0.0  # 结构化程度
    length: int = 0         # 回答长度

    @property
    def total(self) -> float:
        return self.accuracy * 0.4 + self.depth * 0.3 + self.structure * 0.3


def score_response(response: str, keywords: list[str], depth_keywords: list[str]) -> Score:
    if not response:
        return Score()

    text = response.lower()

    # 准确度：必须关键词 + 深度关键词
    all_kw = keywords + depth_keywords
    hits = sum(1 for kw in all_kw if kw.lower() in text)
    accuracy = hits / len(all_kw) if all_kw else 0

    # 深度：信号词密度
    depth_hits = sum(1 for s in DEPTH_SIGNALS if s in response)
    depth = min(depth_hits / 8.0, 1.0)  # 8+ 信号词 = 满分

    # 结构：有无标题/列表
    struct_hits = sum(1 for s in STRUCTURE_SIGNALS if s in response)
    structure = min(struct_hits / 4.0, 1.0)

    return Score(accuracy=accuracy, depth=depth, structure=structure, length=len(response))


# ═══ 实验运行 ═══

async def run_experiment(variant: str, model_name: str, client: ModelClient):
    results = []

    for i, (question, domain, keywords, depth_kw) in enumerate(TEST_QUESTIONS):
        # Build prompt
        if variant == "baseline":
            system = BASELINE_PROMPT
        elif variant == "activation":
            system = build_variant_b_prompt(question, domain)
        elif variant == "activation_chain":
            system = build_variant_c_prompt(question, domain)
        else:
            raise ValueError(f"Unknown variant: {variant}")

        # Call model
        try:
            response = await client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                model=model_name,
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as e:
            response = f"[ERROR: {e}]"

        # Score
        s = score_response(response, keywords, depth_kw)
        results.append({
            "question": question,
            "domain": domain,
            "response": response,
            "score": {"accuracy": s.accuracy, "depth": s.depth, "structure": s.structure, "total": s.total, "length": s.length},
        })

        status = "✓" if s.total > 0.5 else "·"
        print(f"  {status} [{domain:10}] {question[:20]}... acc={s.accuracy:.2f} dep={s.depth:.2f} str={s.structure:.2f} total={s.total:.2f}")

    return results


async def main():
    cfg = DeepForgeConfig.load()
    model_name = cfg.default_model.model
    client = ModelClient(api_key=cfg.default_model.api_key, base_url=cfg.default_model.base_url)

    print(f"═══ Educe 激发引擎对比实验 ═══")
    print(f"模型: {model_name}")
    print(f"题目: {len(TEST_QUESTIONS)} 题")
    print(f"温度: 0.3 (固定)")
    print()

    all_results = {}

    for variant in ["baseline", "activation", "activation_chain"]:
        print(f"\n{'─'*50}")
        print(f"  组别: {variant.upper()}")
        print(f"{'─'*50}")

        results = await run_experiment(variant, model_name, client)
        all_results[variant] = results

        avg_total = sum(r["score"]["total"] for r in results) / len(results)
        avg_acc = sum(r["score"]["accuracy"] for r in results) / len(results)
        avg_dep = sum(r["score"]["depth"] for r in results) / len(results)
        avg_str = sum(r["score"]["structure"] for r in results) / len(results)
        avg_len = sum(r["score"]["length"] for r in results) / len(results)

        print(f"\n  平均: total={avg_total:.3f} acc={avg_acc:.3f} dep={avg_dep:.3f} str={avg_str:.3f} len={avg_len:.0f}")

    # ═══ 对比报告 ═══
    print(f"\n\n{'═'*60}")
    print(f"  对比报告")
    print(f"{'═'*60}")

    variants = list(all_results.keys())
    header = f"{'维度':<12}" + "".join(f"{v:<18}" for v in variants) + "  Δ(B-A)    Δ(C-A)"
    print(header)
    print("─" * len(header))

    for dim in ["total", "accuracy", "depth", "structure"]:
        avgs = [sum(r["score"][dim] for r in all_results[v]) / len(all_results[v]) for v in variants]
        delta_b = avgs[1] - avgs[0]
        delta_c = avgs[2] - avgs[0]
        sign_b = "+" if delta_b >= 0 else ""
        sign_c = "+" if delta_c >= 0 else ""
        row = f"{dim:<12}" + "".join(f"{a:<18.3f}" for a in avgs) + f"  {sign_b}{delta_b:.3f}    {sign_c}{delta_c:.3f}"
        print(row)

    # Length
    avgs_len = [sum(r["score"]["length"] for r in all_results[v]) / len(all_results[v]) for v in variants]
    print(f"{'length':<12}" + "".join(f"{a:<18.0f}" for a in avgs_len))

    # Per-domain breakdown
    print(f"\n  按领域对比 (total score)")
    domains = sorted(set(q[1] for q in TEST_QUESTIONS))
    print(f"{'领域':<12}" + "".join(f"{v:<14}" for v in variants))
    for domain in domains:
        row = f"{domain:<12}"
        for v in variants:
            domain_results = [r for r in all_results[v] if r["domain"] == domain]
            avg = sum(r["score"]["total"] for r in domain_results) / len(domain_results) if domain_results else 0
            row += f"{avg:<14.3f}"
        print(row)

    # Save results
    output_dir = Path(".educe/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"activation_benchmark_{ts}.json"
    output_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n  结果保存: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
