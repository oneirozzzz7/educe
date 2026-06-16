"""
极限 E2E v2 — 运行时 bug（非代码可见的 typo）

关键区别：前一版 typo (dat vs data) 模型一眼就修了。
这次用一个运行时才暴露的问题：端口冲突 + 依赖缺失。

场景：
1. 先占用端口 8899（创建一个 dummy 进程）
2. 要求模型在 8899 端口启动服务 → 必然启动失败
3. 模型需要从 log 中发现 "Address already in use"
4. 修复：kill 旧进程或换端口
5. 最终 curl 验证

这个失败无法从代码中"看到"，必须运行后才暴露。
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".deepforge/convergence")


async def send_and_wait(ws, message: str, timeout: float = 90) -> list[dict]:
    await ws.send(json.dumps({"message": message}))
    events = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=8)
            data = json.loads(msg)
            events.append(data)

            if data.get("type") == "status" and data.get("content") == "idle":
                break

            if data.get("type") == "action_confirm_request":
                await ws.send(json.dumps({
                    "type": "action_confirm_response",
                    "decision": "confirm",
                    "note": "",
                }))
                inner_deadline = time.time() + 30
                while time.time() < inner_deadline:
                    try:
                        msg2 = await asyncio.wait_for(ws.recv(), timeout=5)
                        data2 = json.loads(msg2)
                        events.append(data2)
                        if data2.get("type") == "status" and data2.get("content") == "idle":
                            break
                    except asyncio.TimeoutError:
                        continue
                break

        except asyncio.TimeoutError:
            continue

    return events


def read_convergence(session_id: str) -> dict:
    log_path = CONVERGENCE_DIR / f"{session_id[:16]}.jsonl"
    if not log_path.exists():
        return {"curve": [], "claims": [], "revisions": 0}

    with open(log_path) as f:
        revisions = [json.loads(l) for l in f if l.strip()]

    claims = []
    if revisions:
        last = revisions[-1]
        for cid, c in last["claims"].items():
            claims.append({"status": c["status"], "text": c["text"][:100]})

    return {
        "curve": [r["convergence"] for r in revisions],
        "claims": claims,
        "revisions": len(revisions),
    }


async def main():
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)

    print("=" * 70)
    print("极限 E2E v2 — 运行时 bug（端口冲突）")
    print("=" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    # 先占用端口 8899（模拟端口冲突）
    import subprocess
    blocker = subprocess.Popen(
        ["python", "-c", "import http.server; http.server.HTTPServer(('', 8899), http.server.SimpleHTTPRequestHandler).serve_forever()"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    await asyncio.sleep(1)
    print(f"  已占用端口 8899 (PID={blocker.pid})")
    print()

    try:
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            await asyncio.sleep(1)

            # ═══ Round 1: 创建项目 + 尝试启动（会失败） ═══
            print("━━━ Round 1: 创建项目 + 启动（端口被占用，预期失败）━━━")
            t0 = time.time()
            events = await send_and_wait(ws, (
                "创建 port_demo/ 目录，写一个 server.py：\n"
                "用 http.server 在端口 8899 启动 HTTP 服务（返回 'hello'）。\n"
                "后台启动它（nohup python server.py > server.log 2>&1 &），"
                "等 2 秒后 curl http://localhost:8899/ 测试。\n"
                "如果失败请查看 server.log 诊断原因并修复。"
            ), timeout=120)
            elapsed = time.time() - t0
            state1 = read_convergence(session_id)
            print(f"  耗时: {elapsed:.1f}s")
            print(f"  Curve: {state1['curve']}")
            for c in state1["claims"]:
                icon = "✅" if c["status"] == "verified" else "⚠️"
                print(f"    {icon} [{c['status']}] {c['text']}")
            print()

            open_r1 = sum(1 for c in state1["claims"] if c["status"] == "open")
            verified_r1 = sum(1 for c in state1["claims"] if c["status"] == "verified")
            print(f"  Round 1: {verified_r1} verified, {open_r1} open")

            # ═══ Round 2: 如果模型没自动修复，引导它修 ═══
            if open_r1 > 0:
                print("\n━━━ Round 2: 模型遇到了失败，引导修复 ━━━")
                # 释放端口（模拟用户 kill 了占用进程）
                blocker.terminate()
                blocker.wait()
                await asyncio.sleep(0.5)
                print("  [测试框架] 已释放端口 8899")

                events = await send_and_wait(ws, (
                    "端口 8899 现在已经释放了。重新启动 port_demo/server.py "
                    "（后台运行），然后 curl localhost:8899 验证。"
                ), timeout=60)
            else:
                print("\n━━━ Round 2: 模型在 Round 1 自行修复了（换了端口或 kill 了旧进程）━━━")
                # 释放端口
                blocker.terminate()
                blocker.wait()

                events = await send_and_wait(ws, (
                    "再 curl 一次验证服务正常运行"
                ), timeout=30)

            state2 = read_convergence(session_id)
            print(f"  Curve: {state2['curve']}")
            new_claims = state2["claims"][len(state1["claims"]):]
            for c in new_claims:
                icon = "✅" if c["status"] == "verified" else "⚠️"
                print(f"    {icon} [{c['status']}] {c['text']}")
            print()

    finally:
        # 确保清理 blocker
        try:
            blocker.terminate()
            blocker.wait(timeout=2)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # 最终报告
    # ═══════════════════════════════════════════════════════════════════
    print("=" * 70)
    print("最终分析")
    print("=" * 70)

    final = read_convergence(session_id)
    curve = final["curve"]
    print(f"\n完整收敛曲线 ({len(curve)} revisions):")
    if curve:
        print(f"  {' → '.join(f'{c:.2f}' for c in curve)}")

    verified_count = sum(1 for c in final["claims"] if c["status"] == "verified")
    open_count = sum(1 for c in final["claims"] if c["status"] == "open")
    total = len(final["claims"])

    print(f"\n最终知识状态:")
    print(f"  Verified: {verified_count}/{total}")
    print(f"  Open: {open_count}/{total}")

    # 判据
    print(f"\n━━━ 判据 ━━━")

    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    print(f"  曲线有下降（运行时 bug 被捕获）: {'✅' if has_drop else '⚠️'}")

    has_open = open_count > 0
    print(f"  存在 OPEN claims（失败被追踪）: {'✅' if has_open else '⚠️'}")

    knowledge_growth = state2["revisions"] > state1["revisions"]
    print(f"  多轮知识增长: {'✅' if knowledge_growth else '❌'}")

    model_adapted = verified_count >= 3
    print(f"  模型最终完成任务: {'✅' if model_adapted else '❌'} ({verified_count} verified)")

    # 总结
    if has_drop:
        print(f"\n  ✅ 极限场景通过 — 运行时 bug 被正确追踪，曲线有下降")
    elif has_open:
        print(f"\n  ✅ 极限场景通过（变体）— 失败被追踪为 OPEN")
    elif model_adapted:
        print(f"\n  ⚠️ 模型太强 — 自行发现端口冲突并解决（无需引导）")
        print(f"     这证明 Qwen3.6 有真实的环境感知能力")
    else:
        print(f"\n  ❌ 未通过")

    # 关键洞察
    print(f"\n━━━ 关键洞察 ━━━")
    if not has_drop and model_adapted:
        print(f"  弱模型的'运行时诊断能力'超出预期：")
        print(f"  - 它能从 curl/log 错误信息中推断问题（端口冲突）")
        print(f"  - 自动尝试修复策略（换端口 / kill 旧进程）")
        print(f"  - 这是框架反馈循环（shell output → 模型推理）的核心价值")
    if has_drop:
        print(f"  收敛曲线如实反映了'知识暂时失效→重建'的过程")
        print(f"  Prober 的价值：自动重新验证 OPEN claims（而不是需要用户引导）")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
