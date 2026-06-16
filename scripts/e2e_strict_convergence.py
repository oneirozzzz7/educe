"""
e2e_strict_convergence.py — 严格端到端收敛验证

验证目标：一个完整的多轮交互项目，模型需要：
1. 创建多文件项目
2. 启动服务并端到端验证
3. 追加新功能（修改已有代码）
4. 遇到真实 bug 并修复
5. 最终全部功能通过

收敛曲线应该呈现：上升 → 遇到失败下降 → 修复后恢复

通过 WebSocket（前端唯一通信接口）进行，等价于浏览器操作。
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".deepforge/convergence")


async def send_and_wait(ws, message: str, timeout: float = 60) -> list[dict]:
    """发送消息并等待到 idle，收集所有响应事件"""
    await ws.send(json.dumps({"message": message}))
    events = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            events.append(data)

            if data.get("type") == "status" and data.get("content") == "idle":
                break

            # 自动确认
            if data.get("type") == "action_confirm_request":
                await ws.send(json.dumps({
                    "type": "action_confirm_response",
                    "decision": "confirm",
                    "note": "",
                }))
                # 等确认执行完成
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
    """读取收敛日志"""
    log_path = CONVERGENCE_DIR / f"{session_id[:16]}.jsonl"
    if not log_path.exists():
        return {"curve": [], "claims": [], "revisions": 0}

    with open(log_path) as f:
        revisions = [json.loads(l) for l in f if l.strip()]

    claims = []
    if revisions:
        last = revisions[-1]
        for cid, c in last["claims"].items():
            claims.append({"status": c["status"], "text": c["text"][:80]})

    return {
        "curve": [r["convergence"] for r in revisions],
        "claims": claims,
        "revisions": len(revisions),
    }


async def main():
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)

    print("=" * 70)
    print("严格端到端收敛验证 — 多轮 FastAPI 项目")
    print("=" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        # 等待连接稳定
        await asyncio.sleep(1)

        # ═══ Round 1: 创建基础 API ═══
        print("━━━ Round 1: 创建 FastAPI + SQLite 基础 API ━━━")
        t0 = time.time()
        events = await send_and_wait(ws, (
            "创建 Python 项目 api-server/：models.py（SQLite 数据库操作，"
            "tasks 表有 id/name/status/created_at）+ app.py（FastAPI 路由："
            "POST /tasks 创建任务返回 JSON，GET /tasks/{id} 查询任务）。"
            "创建后 cd api-server && python -c 'from models import *; print(\"import ok\")' 验证。"
        ))
        elapsed = time.time() - t0
        state1 = read_convergence(session_id)
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  Revisions: {state1['revisions']}")
        print(f"  Curve: {state1['curve']}")
        print(f"  Claims: {len(state1['claims'])}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

        # ═══ Round 2: 启动服务 + 端到端 curl 测试 ═══
        print("━━━ Round 2: 启动服务 + curl 端到端测试 ━━━")
        t0 = time.time()
        events = await send_and_wait(ws, (
            "现在启动 api-server：cd api-server && pip install fastapi uvicorn -q && "
            "nohup python -m uvicorn app:app --port 8000 > server.log 2>&1，"
            "然后 sleep 2 && curl -s http://localhost:8000/tasks -X POST "
            "-H 'Content-Type: application/json' -d '{\"name\": \"test1\"}'。"
            "如果失败就检查 server.log 并修复。"
        ))
        elapsed = time.time() - t0
        state2 = read_convergence(session_id)
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  Curve: {state2['curve']}")
        new_claims = state2["claims"][len(state1["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

        # ═══ Round 3: 追加功能（修改代码） ═══
        print("━━━ Round 3: 追加 DELETE /tasks/{id} 功能 ━━━")
        t0 = time.time()
        events = await send_and_wait(ws, (
            "给 api-server 加一个 DELETE /tasks/{id} 接口，删除指定任务。"
            "修改 models.py 加 delete_task 函数，修改 app.py 加路由。"
            "然后重启服务并用 curl 测试删除。"
        ))
        elapsed = time.time() - t0
        state3 = read_convergence(session_id)
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  Curve: {state3['curve']}")
        new_claims = state3["claims"][len(state2["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

    # ═══ 最终报告 ═══
    print("=" * 70)
    print("最终收敛分析")
    print("=" * 70)

    final = read_convergence(session_id)
    curve = final["curve"]
    print(f"\n完整收敛曲线 ({len(curve)} revisions):")
    print(f"  {' → '.join(f'{c:.2f}' for c in curve)}")

    # 分析指标
    verified_count = sum(1 for c in final["claims"] if c["status"] == "verified")
    open_count = sum(1 for c in final["claims"] if c["status"] == "open")
    total = len(final["claims"])

    print(f"\n最终知识状态:")
    print(f"  Verified: {verified_count}/{total}")
    print(f"  Open: {open_count}/{total}")
    print(f"  最终收敛度: {curve[-1]:.2f}" if curve else "  无数据")

    # 严格判据
    print(f"\n━━━ 严格验证判据 ━━━")

    # 判据1: 至少有 6 个 claims（多步骤任务）
    p1 = total >= 6
    print(f"  [{'✅' if p1 else '❌'}] 复杂度: {total} claims (要求≥6)")

    # 判据2: 存在 OPEN claims（有真实失败被追踪）
    p2 = open_count > 0
    print(f"  [{'✅' if p2 else '⚠️'}] 失败追踪: {open_count} open claims")

    # 判据3: 曲线有下降（遇到了真实困难）
    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    print(f"  [{'✅' if has_drop else '⚠️'}] 曲线有下降（遇到真实困难）: {has_drop}")

    # 判据4: 3轮交互全部有响应（模型没卡死）
    p4 = state3["revisions"] > state2["revisions"] > state1["revisions"]
    print(f"  [{'✅' if p4 else '❌'}] 三轮均有新知识产出: rev {state1['revisions']}→{state2['revisions']}→{state3['revisions']}")

    # 判据5: 多文件操作（write_file 至少 2 次）
    write_claims = sum(1 for c in final["claims"] if "file created" in c["text"])
    p5 = write_claims >= 2
    print(f"  [{'✅' if p5 else '❌'}] 多文件操作: {write_claims} files created")

    # 总结
    passed = sum([p1, p4, p5])
    total_criteria = 5
    print(f"\n  总评: {passed}/{total_criteria} 硬性判据通过")
    if p2:
        print(f"  + 有失败追踪（收敛系统真正工作的证据）")
    if has_drop:
        print(f"  + 收敛曲线有恢复弧线（证明不是全成功的假象）")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
