"""
A/B 实验：裸 LLM vs 全功能 Educe

核心假设验证：进化层（反射/技能/器官）是否为用户创造了可测量的价值？

实验方法：
- 同一组任务分别在 BARE_MODE=1（裸 LLM）和 BARE_MODE=0（全功能）下执行
- 度量：token 消耗、延迟、成功率、action 步数
- 使用 Kimi-K2 模型（产品运行模型）

使用：
  python tests/ab_bare_vs_full.py
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import EduceConfig
from educe.core.orchestrator import Orchestrator


# 测试任务集（覆盖多种场景）
TEST_TASKS = [
    # 简单 readonly（L3 反射的优势场景）
    {"input": "看看 educe/paths.py 的代码", "category": "readonly"},
    {"input": "读一下 README.md", "category": "readonly"},
    # 写+执行（CompositeSkill 的优势场景）
    {"input": "写一个 /tmp/ab_sum.py 计算 1+2+...+100 并打印结果，然后运行", "category": "write_exec"},
    {"input": "写一个 /tmp/ab_hello.py 打印 Hello World，然后运行", "category": "write_exec"},
    # 搜索（多步探索）
    {"input": "搜索项目里 OrganModel 类的定义在哪个文件", "category": "search"},
    # 需要器官修复的场景
    {"input": "写一个 /tmp/ab_figlet.py 用 pyfiglet 打印 AB-TEST，然后运行", "category": "organ"},
    # 纯对话（进化层不应该有任何效果）
    {"input": "解释一下什么是递归", "category": "chat"},
    # 多步任务
    {"input": "在 /tmp/ab_project 下创建目录，写一个 main.py 打印当前时间，然后运行", "category": "multi_step"},
]


async def run_single_task(config: EduceConfig, task: dict, bare_mode: bool) -> dict:
    """执行单个任务并收集指标"""
    os.environ["EDUCE_BARE_MODE"] = "1" if bare_mode else "0"

    orchestrator = Orchestrator(config)
    orchestrator.context.metadata["session_id"] = f"ab_{'bare' if bare_mode else 'full'}_{int(time.time())}"

    t0 = time.time()
    try:
        result = await orchestrator.run(task["input"])
        latency = time.time() - t0

        # 收集指标
        messages = result.messages if hasattr(result, 'messages') else []
        final_reply = ""
        for msg in reversed(messages):
            if hasattr(msg, 'content') and msg.content:
                final_reply = msg.content
                break

        # 从 session logger 获取 token 计数
        token_count = orchestrator.context.metadata.get("_total_tokens", 0)
        action_count = orchestrator.context.metadata.get("_action_count", 0)

        success = bool(final_reply and len(final_reply) > 10)

        return {
            "task": task["input"][:50],
            "category": task["category"],
            "mode": "bare" if bare_mode else "full",
            "latency_s": round(latency, 2),
            "token_count": token_count,
            "reply_len": len(final_reply),
            "success": success,
            "has_reflex": "[反射执行]" in final_reply if final_reply else False,
            "has_organ": "[器官修复]" in final_reply if final_reply else False,
        }
    except Exception as e:
        return {
            "task": task["input"][:50],
            "category": task["category"],
            "mode": "bare" if bare_mode else "full",
            "latency_s": round(time.time() - t0, 2),
            "error": str(e)[:100],
            "success": False,
        }


async def run_ab_experiment():
    """运行完整 A/B 实验"""
    config = EduceConfig.load()

    print("=" * 70)
    print("A/B 实验：裸 LLM vs 全功能 Educe")
    print("=" * 70)
    print(f"任务数: {len(TEST_TASKS)}")
    print(f"模型: {config.default_model.model}")
    print()

    results = []

    for i, task in enumerate(TEST_TASKS):
        print(f"\n--- Task {i+1}/{len(TEST_TASKS)}: {task['input'][:40]}... [{task['category']}] ---")

        # 裸模式
        print("  [BARE] running...", end="", flush=True)
        bare_result = await run_single_task(config, task, bare_mode=True)
        print(f" done ({bare_result.get('latency_s', '?')}s)")
        results.append(bare_result)

        await asyncio.sleep(1)  # 避免限流

        # 全功能模式
        print("  [FULL] running...", end="", flush=True)
        full_result = await run_single_task(config, task, bare_mode=False)
        print(f" done ({full_result.get('latency_s', '?')}s)")
        results.append(full_result)

        await asyncio.sleep(1)

    # 分析结果
    print("\n" + "=" * 70)
    print("结果分析")
    print("=" * 70)

    bare_results = [r for r in results if r.get("mode") == "bare"]
    full_results = [r for r in results if r.get("mode") == "full"]

    bare_latency = [r["latency_s"] for r in bare_results if "latency_s" in r]
    full_latency = [r["latency_s"] for r in full_results if "latency_s" in r]

    bare_success = sum(1 for r in bare_results if r.get("success"))
    full_success = sum(1 for r in full_results if r.get("success"))

    full_reflex = sum(1 for r in full_results if r.get("has_reflex"))
    full_organ = sum(1 for r in full_results if r.get("has_organ"))

    print(f"\n{'Metric':<25} {'BARE':<15} {'FULL':<15} {'Delta':<15}")
    print("-" * 70)
    print(f"{'Success rate':<25} {bare_success}/{len(bare_results):<14} {full_success}/{len(full_results):<14}")
    if bare_latency and full_latency:
        avg_bare = sum(bare_latency) / len(bare_latency)
        avg_full = sum(full_latency) / len(full_latency)
        print(f"{'Avg latency (s)':<25} {avg_bare:<15.2f} {avg_full:<15.2f} {avg_full - avg_bare:+.2f}")
    print(f"{'Reflex hits':<25} {'N/A':<15} {full_reflex:<15}")
    print(f"{'Organ activations':<25} {'N/A':<15} {full_organ:<15}")

    # 按类别分析
    print(f"\n{'Category':<15} {'BARE lat':<12} {'FULL lat':<12} {'BARE ok':<10} {'FULL ok':<10}")
    print("-" * 60)
    categories = set(t["category"] for t in TEST_TASKS)
    for cat in sorted(categories):
        cat_bare = [r for r in bare_results if r.get("category") == cat]
        cat_full = [r for r in full_results if r.get("category") == cat]
        b_lat = sum(r.get("latency_s", 0) for r in cat_bare) / max(len(cat_bare), 1)
        f_lat = sum(r.get("latency_s", 0) for r in cat_full) / max(len(cat_full), 1)
        b_ok = sum(1 for r in cat_bare if r.get("success"))
        f_ok = sum(1 for r in cat_full if r.get("success"))
        print(f"{cat:<15} {b_lat:<12.2f} {f_lat:<12.2f} {b_ok}/{len(cat_bare):<9} {f_ok}/{len(cat_full)}")

    # 保存
    output_path = Path(".educe/experiments") / f"ab_bare_vs_full_{int(time.time())}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果保存: {output_path}")

    # 判定
    print("\n" + "=" * 70)
    if full_success > bare_success:
        print("结论: 全功能模式成功率更高 → 进化层有正向价值")
    elif full_success == bare_success:
        if full_latency and bare_latency and sum(full_latency) < sum(bare_latency) * 0.9:
            print("结论: 成功率相同但全功能更快 → 进化层有效率价值")
        else:
            print("结论: 无显著差异 → 进化层的价值尚未被证实")
    else:
        print("结论: 裸模式反而更好 → 进化层可能产生了负效应")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_ab_experiment())
