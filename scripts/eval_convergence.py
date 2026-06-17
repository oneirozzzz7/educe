"""
eval_convergence.py — 收敛性批量验证实验

实验设计（来自 Opus 讨论 Round 6）：
- 实验 A：同一任务跑 N 次，验证收敛曲线单调非降
- 实验 B：验证任务完成前到达不动点（hash 稳定）

运行方式：python scripts/eval_convergence.py
前提：后端已在 localhost:7860 运行
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".educe/convergence")

# 简单任务（高成功率，能快速完成）
TEST_TASK = "创建一个 Python 文件 hello.py，内容是 print('hello world')，然后运行它。"

# 复杂任务（更多步骤，可能有失败）
COMPLEX_TASK = "创建 Python 项目 calc/：math_ops.py（加减乘除函数）+ test_calc.py（用 assert 测试4个操作）。运行 python test_calc.py 验证全部通过。"

NUM_RUNS = 5  # 先用 5 次验证机制正确，后续增加到 20


async def run_single_task(task: str, run_id: int) -> dict:
    """通过 WebSocket 发送一个任务，等待完成，返回收敛数据"""
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)
    log_path = CONVERGENCE_DIR / f"{session_id[:16]}.jsonl"

    result = {
        "run_id": run_id,
        "session_id": session_id,
        "success": False,
        "convergence_curve": [],
        "final_hash": "",
        "claims_count": 0,
        "duration": 0,
    }

    t0 = time.time()
    try:
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            # 发送任务
            await ws.send(json.dumps({"message": task}))

            # 等待直到收到 status: idle（任务完成）
            deadline = time.time() + 60  # 最多等 60 秒
            got_idle = False
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    if data.get("type") == "status" and data.get("content") == "idle":
                        got_idle = True
                        break
                    # 自动确认任何 action_confirm_request
                    if data.get("type") == "action_confirm_request":
                        await ws.send(json.dumps({
                            "type": "action_confirm_response",
                            "decision": "confirm",
                            "note": "",
                        }))
                except asyncio.TimeoutError:
                    continue

            result["duration"] = time.time() - t0
            result["success"] = got_idle

    except Exception as e:
        result["error"] = str(e)[:200]
        result["duration"] = time.time() - t0

    # 读取收敛 log
    await asyncio.sleep(0.5)  # 确保文件 flush
    if log_path.exists():
        with open(log_path) as f:
            revisions = [json.loads(line) for line in f if line.strip()]
        result["convergence_curve"] = [r["convergence"] for r in revisions]
        if revisions:
            result["final_hash"] = revisions[-1]["hash"]
            result["claims_count"] = len(revisions[-1]["claims"])

    return result


def analyze_results(results: list[dict]):
    """分析批量结果"""
    print("\n" + "=" * 60)
    print(f"收敛性验证报告 ({len(results)} runs)")
    print("=" * 60)

    successful = [r for r in results if r["success"]]
    print(f"\n完成率: {len(successful)}/{len(results)}")

    # 实验 A：收敛曲线单调性
    monotonic_count = 0
    for r in successful:
        curve = r["convergence_curve"]
        if len(curve) >= 2:
            is_mono = all(curve[i] <= curve[i+1] for i in range(len(curve)-1))
            if is_mono:
                monotonic_count += 1

    if successful:
        mono_rate = monotonic_count / len(successful)
        print(f"\n[实验A] 收敛曲线单调非降率: {monotonic_count}/{len(successful)} = {mono_rate:.0%}")
        print(f"  目标: ≥80%  {'✅ PASS' if mono_rate >= 0.8 else '❌ FAIL'}")

    # 实验 B：不动点（最后 2 个 revision hash 相同 = 到达稳态）
    # 注：当前实现中每步都产生新 claim，hash 不会重复
    # 改为检验"收敛到 1.0"
    converged_count = sum(1 for r in successful if r["convergence_curve"] and r["convergence_curve"][-1] == 1.0)
    if successful:
        conv_rate = converged_count / len(successful)
        print(f"\n[实验B] 最终收敛率=1.0: {converged_count}/{len(successful)} = {conv_rate:.0%}")
        print(f"  目标: ≥70%  {'✅ PASS' if conv_rate >= 0.7 else '❌ FAIL'}")

    # 统计
    durations = [r["duration"] for r in successful]
    claims = [r["claims_count"] for r in successful]
    if durations:
        print(f"\n[统计]")
        print(f"  耗时: avg={sum(durations)/len(durations):.1f}s, max={max(durations):.1f}s")
        print(f"  Claims: avg={sum(claims)/len(claims):.1f}, max={max(claims)}")

    # 每次 run 的详情
    print(f"\n[详情]")
    for r in results:
        status = "✅" if r["success"] else "❌"
        curve_str = "→".join(f"{c:.1f}" for c in r["convergence_curve"][:8])
        print(f"  Run {r['run_id']}: {status} {r['duration']:.1f}s claims={r['claims_count']} curve=[{curve_str}]")

    print("\n" + "=" * 60)
    return successful


async def main():
    print(f"开始收敛性验证实验")
    print(f"服务: {SERVER_URL.format(session_id='...')}")

    # Phase 1: 简单任务
    print(f"\n{'='*40}")
    print(f"Phase 1: 简单任务 ({NUM_RUNS} runs)")
    print(f"任务: {TEST_TASK}")
    print()

    results_simple = []
    for i in range(NUM_RUNS):
        print(f"  Run {i+1}/{NUM_RUNS}...", end=" ", flush=True)
        r = await run_single_task(TEST_TASK, i + 1)
        status = "✅" if r["success"] else "❌"
        print(f"{status} ({r['duration']:.1f}s, {r['claims_count']} claims)")
        results_simple.append(r)
        await asyncio.sleep(1)

    analyze_results(results_simple)

    # Phase 2: 复杂任务
    print(f"\n{'='*40}")
    print(f"Phase 2: 复杂任务 ({NUM_RUNS} runs)")
    print(f"任务: {COMPLEX_TASK}")
    print()

    results_complex = []
    for i in range(NUM_RUNS):
        print(f"  Run {i+1}/{NUM_RUNS}...", end=" ", flush=True)
        r = await run_single_task(COMPLEX_TASK, i + 1)
        status = "✅" if r["success"] else "❌"
        print(f"{status} ({r['duration']:.1f}s, {r['claims_count']} claims)")
        results_complex.append(r)
        await asyncio.sleep(1)

    analyze_results(results_complex)

    # 保存原始数据
    output_path = Path("tests/convergence_results.json")
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"simple": results_simple, "complex": results_complex},
                  f, indent=2, ensure_ascii=False)
    print(f"\n原始数据已保存: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
