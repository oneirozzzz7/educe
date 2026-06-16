"""
eval_convergence_failures.py — 测试收敛曲线在有失败时的行为

关键验证：当 action 失败时，IterationState 能正确记录 OPEN claims，
收敛曲线不是一路 1.0 而是有起伏。
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".deepforge/convergence")

# 会产生失败的任务（import 一个不存在的模块）
FAILING_TASK = "创建 app.py 导入 nonexistent_module，然后运行 python app.py"

NUM_RUNS = 3


async def run_single_task(task: str, run_id: int) -> dict:
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)
    log_path = CONVERGENCE_DIR / f"{session_id[:16]}.jsonl"

    result = {
        "run_id": run_id,
        "session_id": session_id,
        "success": False,
        "convergence_curve": [],
        "claims_detail": [],
        "duration": 0,
    }

    t0 = time.time()
    try:
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            await ws.send(json.dumps({"message": task}))

            deadline = time.time() + 45
            got_idle = False
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    if data.get("type") == "status" and data.get("content") == "idle":
                        got_idle = True
                        break
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

    await asyncio.sleep(0.5)
    if log_path.exists():
        with open(log_path) as f:
            revisions = [json.loads(line) for line in f if line.strip()]
        result["convergence_curve"] = [r["convergence"] for r in revisions]
        if revisions:
            last = revisions[-1]
            for cid, claim in last["claims"].items():
                result["claims_detail"].append(f"[{claim['status']}] {claim['text'][:60]}")

    return result


async def main():
    print(f"收敛性失败场景验证 ({NUM_RUNS} runs)")
    print(f"任务: {FAILING_TASK}")
    print()

    results = []
    for i in range(NUM_RUNS):
        print(f"  Run {i+1}/{NUM_RUNS}...", end=" ", flush=True)
        r = await run_single_task(FAILING_TASK, i + 1)
        status = "✅" if r["success"] else "❌"
        print(f"{status} ({r['duration']:.1f}s)")
        results.append(r)
        await asyncio.sleep(1)

    print(f"\n{'='*60}")
    print("结果分析")
    print(f"{'='*60}")

    has_open = 0
    has_non_monotone = 0
    for r in results:
        curve = r["convergence_curve"]
        has_open_claims = any("open" in c for c in r["claims_detail"])
        if has_open_claims:
            has_open += 1

        curve_str = "→".join(f"{c:.2f}" for c in curve)
        print(f"\n  Run {r['run_id']}: curve=[{curve_str}]")
        for claim in r["claims_detail"]:
            print(f"    {claim}")

    print(f"\n[关键指标]")
    print(f"  有 OPEN claims 的 runs: {has_open}/{len(results)}")
    print(f"  收敛曲线 < 1.0 出现: {'✅ 是' if has_open > 0 else '⚠️ 全是1.0'}")

    # 保存
    with open("tests/convergence_failures.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
