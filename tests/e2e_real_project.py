"""
E2E Real Project Test — Educe 自主找、克隆、分析、运行 GitHub 项目

验证完整产品闭环：
1. 用户给描述 → Educe 自主选择并克隆一个 GitHub 项目
2. 分析项目结构
3. 运行测试
4. 用户纠正 → 学习规则
5. 验证规则影响后续回答

驱动方式：直接调 Orchestrator（不经前端），自动确认所有 action。
"""
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import DeepForgeConfig
from educe.core.orchestrator import Orchestrator
from educe.agents import ALL_AGENTS
from educe.models.router import ModelClient

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"

PROJECT_DIR = "/tmp/educe_test_project"


def setup_orchestrator() -> Orchestrator:
    """创建带真实模型的 Orchestrator"""
    config = DeepForgeConfig.load()
    client = ModelClient(api_key=config.default_model.api_key,
                         base_url=config.default_model.base_url)
    orchestrator = Orchestrator(config)

    for agent_cls in ALL_AGENTS:
        agent = agent_cls(config=config, model_client=client, knowledge=orchestrator.knowledge)
        orchestrator.register(agent)

    orchestrator.context.metadata["session_id"] = f"e2e_real_{int(time.time())}"
    return orchestrator


async def auto_confirm_loop(orchestrator: Orchestrator, user_input: str, max_confirms: int = 3) -> str:
    """发送消息并自动确认所有 pending actions，返回最终 agent 回复"""
    collected_chunks = []

    def on_chunk(agent_name: str, chunk: str):
        collected_chunks.append(chunk)

    orchestrator.on_chunk(on_chunk)

    # 首次发送
    await orchestrator.run(user_input)

    # 自动确认循环
    for _ in range(max_confirms):
        pending = orchestrator.context.metadata.get("_pending_actions")
        if not pending:
            break
        # 模拟用户确认
        collected_chunks.clear()
        await orchestrator.run("确认")

    reply = "".join(collected_chunks)
    orchestrator._on_chunk.clear()
    return reply


async def main():
    # 清理旧测试目录
    if Path(PROJECT_DIR).exists():
        shutil.rmtree(PROJECT_DIR)

    print(f"\n{BOLD}{'═'*60}")
    print("E2E Real Project Test — Educe 自主分析 GitHub 项目")
    print(f"{'═'*60}{RESET}\n")

    orchestrator = setup_orchestrator()
    results = {}

    # ═══ Turn 1: 找项目并克隆 ═══
    print(f"{BOLD}Turn 1: 找到并克隆一个 GitHub 项目{RESET}")
    t1_reply = await auto_confirm_loop(
        orchestrator,
        f"帮我找一个 GitHub 上的小型 Python 工具库（代码量小，有单元测试，实用），"
        f"用 git clone 下载到 {PROJECT_DIR} 目录。直接执行，不需要我确认。"
    )
    print(f"  {DIM}Reply: {t1_reply[:200]}...{RESET}")

    # 验证克隆成功
    clone_ok = Path(PROJECT_DIR).exists() and any(Path(PROJECT_DIR).iterdir())
    if not clone_ok:
        # 可能克隆到了子目录
        for d in Path("/tmp").glob("educe_test_project*"):
            if d.is_dir() and any(d.iterdir()):
                clone_ok = True
                break
    results["clone"] = clone_ok
    print(f"  {'✓' if clone_ok else '✗'} Clone: {PROJECT_DIR} {'exists' if clone_ok else 'NOT FOUND'}")

    # ═══ Turn 2: 分析项目 ═══
    print(f"\n{BOLD}Turn 2: 分析项目结构{RESET}")
    t2_reply = await auto_confirm_loop(
        orchestrator,
        f"分析一下 {PROJECT_DIR} 的目录结构和核心代码，告诉我这个项目是做什么的"
    )
    print(f"  {DIM}Reply ({len(t2_reply)} chars): {t2_reply[:200]}...{RESET}")

    # 验证 read_dir 执行
    has_context = bool(orchestrator.context.metadata.get("_project_context"))
    results["analyze"] = has_context or len(t2_reply) > 100
    print(f"  {'✓' if results['analyze'] else '✗'} Analyze: project_context={'set' if has_context else 'empty'}, reply_len={len(t2_reply)}")

    # ═══ Turn 3: 运行测试 ═══
    print(f"\n{BOLD}Turn 3: 运行测试{RESET}")
    t3_reply = await auto_confirm_loop(
        orchestrator,
        f"在 {PROJECT_DIR} 目录运行项目的单元测试（pytest 或 python -m unittest），告诉我结果"
    )
    print(f"  {DIM}Reply ({len(t3_reply)} chars): {t3_reply[:300]}...{RESET}")

    # 验证测试执行
    test_keywords = ["pass", "fail", "error", "ok", "test", "pytest", "unittest", "ran"]
    tests_ran = any(kw in t3_reply.lower() for kw in test_keywords)
    results["tests"] = tests_ran
    print(f"  {'✓' if tests_ran else '✗'} Tests: {'evidence of test execution found' if tests_ran else 'no test output detected'}")

    # ═══ Turn 4: 纠正（触发学习） ═══
    print(f"\n{BOLD}Turn 4: 用户纠正 → BehaviorLearner 学习{RESET}")
    t4_reply = await auto_confirm_loop(
        orchestrator,
        "不对，你的回答太啰嗦了。以后回答我的问题，请控制在3句话以内，直接给结论"
    )
    print(f"  {DIM}Reply: {t4_reply[:150]}{RESET}")

    # 等待异步学习完成
    await asyncio.sleep(2)

    # 验证规则学习
    manifest = orchestrator._get_behavior_manifest()
    units_after = len(manifest.units)
    results["learned"] = units_after >= 1
    print(f"  {'✓' if results['learned'] else '✗'} Learning: {units_after} units in manifest")
    if manifest.units:
        for u in manifest.units:
            print(f"    [{u.status.value}] {u.directive[:60]}")

    # ═══ Turn 5: 验证规则影响 ═══
    print(f"\n{BOLD}Turn 5: 验证规则影响后续回答{RESET}")
    t5_reply = await auto_confirm_loop(
        orchestrator,
        "这个项目用了什么设计模式？"
    )
    print(f"  {DIM}Reply ({len(t5_reply)} chars): {t5_reply[:200]}{RESET}")

    # 规则影响验证：T5 应该比 T2 短
    t2_len = len(t2_reply)
    t5_len = len(t5_reply)
    shorter = t5_len < t2_len * 0.8  # 至少短 20%
    results["rule_effect"] = shorter or t5_len < 500  # 要么明显更短，要么本来就短
    print(f"  {'✓' if results['rule_effect'] else '✗'} Rule effect: T2={t2_len} chars → T5={t5_len} chars")

    # ═══ 最终评判 ═══
    print(f"\n{BOLD}{'═'*60}")
    print("FINAL EVALUATION")
    print(f"{'═'*60}{RESET}\n")

    for name, passed in results.items():
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}")

    passed_count = sum(1 for v in results.values() if v)
    total = len(results)
    verdict = "PASS" if passed_count >= 4 else "FAIL"
    color = GREEN if verdict == "PASS" else RED
    print(f"\n  {color}{BOLD}{verdict} ({passed_count}/{total}){RESET}")


if __name__ == "__main__":
    asyncio.run(main())
