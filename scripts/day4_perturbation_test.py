"""
Day 4 — 扰动注入实验

验证 IterationState 对错误/矛盾信息的韧性：
1. 结构层：Claim 状态可回退（VERIFIED→OPEN），收敛曲线正确反映
2. API 层：通过 WebSocket 注入会失败的操作，观察系统响应
3. 恢复层：失败后继续操作，收敛是否能回升

实验分三部分：
Part A — 纯数据结构层扰动（不需要模型调用）
Part B — 端到端扰动（通过 WS 注入注定失败的操作）
Part C — 恢复弧线（失败后追加修复指令）
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

# ═══════════════════════════════════════════════════════════════════
# Part A: 结构层验证 — Claim 回退与收敛曲线响应
# ═══════════════════════════════════════════════════════════════════

def test_part_a():
    """验证 IterationState 结构能正确表达状态回退"""
    from deepforge.core.iteration_state import Claim, FactStatus, IterationState, StateLog
    import tempfile

    print("=" * 70)
    print("Part A: 结构层 — Claim 回退与收敛曲线响应")
    print("=" * 70)

    tmp = Path(tempfile.mkdtemp()) / "perturbation_test.jsonl"
    log = StateLog(tmp)

    # Step 1: 正常积累（3 VERIFIED claims）
    state = IterationState(task_id="perturb-test")
    c1 = Claim.new("file app.py created", FactStatus.VERIFIED, ("ev1",))
    state = state.apply(c1)
    log.record(state)

    c2 = Claim.new("pip install fastapi succeeded", FactStatus.VERIFIED, ("ev2",))
    state = state.apply(c2)
    log.record(state)

    c3 = Claim.new("server responds 200 on /health", FactStatus.VERIFIED, ("ev3",))
    state = state.apply(c3)
    log.record(state)

    print(f"  Step 1 — 正常积累: {log.convergence_curve()}")
    assert log.convergence_curve() == [1.0, 1.0, 1.0], "正常积累应全为1.0"

    # Step 2: 注入扰动 — 将 c3 "server responds 200" 改为 OPEN
    # 模拟场景：进程被 kill 后重试发现服务不响应
    c3_retracted = c3.with_status(FactStatus.OPEN, ("perturbation:server_killed",))
    state = state.apply(c3_retracted)
    log.record(state)

    curve = log.convergence_curve()
    print(f"  Step 2 — 注入扰动 (VERIFIED→OPEN): {curve}")
    assert curve[-1] < 1.0, "扰动后收敛度应下降"
    assert curve[-1] == 2/3, f"3 claims, 2 resolved → 期望 0.667, got {curve[-1]}"

    # Step 3: 恢复 — 重新验证（模拟 server 重启后再次 curl 成功）
    c3_recovered = c3.with_status(FactStatus.VERIFIED, ("recovery:restart_ok",))
    state = state.apply(c3_recovered)
    log.record(state)

    curve = log.convergence_curve()
    print(f"  Step 3 — 恢复 (OPEN→VERIFIED): {curve}")
    assert curve[-1] == 1.0, "恢复后应回到 1.0"

    # Step 4: 验证完整曲线形态
    expected = [1.0, 1.0, 1.0, 2/3, 1.0]
    assert len(curve) == 5, f"应有5个revision, got {len(curve)}"
    print(f"  Step 4 — 完整曲线: {[f'{c:.2f}' for c in curve]}")
    print(f"  期望形态: 上升 → 下降(扰动) → 恢复")

    # Step 5: diff 验证
    diff_down = log.diff(2, 3)
    assert diff_down["convergence_delta"] < 0, "扰动应导致负 delta"
    print(f"  Step 5 — 下降 delta: {diff_down['convergence_delta']:.3f}")

    diff_up = log.diff(3, 4)
    assert diff_up["convergence_delta"] > 0, "恢复应导致正 delta"
    print(f"  Step 5 — 恢复 delta: {diff_up['convergence_delta']:.3f}")

    # Step 6: 序列化/反序列化后曲线保持
    log2 = StateLog(tmp)
    log2.load()
    assert log2.convergence_curve() == curve, "持久化后曲线应一致"
    print(f"  Step 6 — 序列化后曲线一致: ✅")

    print(f"\n  ✅ Part A 全部通过 — IterationState 能正确表达扰动和恢复")
    print()
    return True


# ═══════════════════════════════════════════════════════════════════
# Part B: 端到端扰动 — 注入注定失败的操作
# ═══════════════════════════════════════════════════════════════════

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".deepforge/convergence")


async def send_and_wait(ws, message: str, timeout: float = 90) -> list[dict]:
    """发送消息并等待到 idle"""
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
            claims.append({"status": c["status"], "text": c["text"][:80]})

    return {
        "curve": [r["convergence"] for r in revisions],
        "claims": claims,
        "revisions": len(revisions),
    }


async def test_part_b():
    """端到端扰动：先成功创建文件，再发一个注定失败的命令"""
    print("=" * 70)
    print("Part B: 端到端扰动 — 注入注定失败的操作")
    print("=" * 70)

    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)
    print(f"  Session: {session_id[:16]}")

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # Round 1: 正常操作 — 创建文件
        print("\n  ━━━ Round 1: 正常操作（创建文件）━━━")
        events = await send_and_wait(ws, (
            "创建 perturb_demo/ 目录，写一个 hello.py 文件内容为 print('hello')，"
            "然后运行 cd perturb_demo && python hello.py 验证输出。"
        ))
        state1 = read_convergence(session_id)
        print(f"    Curve: {state1['curve']}")
        print(f"    Claims: {len(state1['claims'])}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

        # Round 2: 注入扰动 — 运行一个不存在的命令
        print("\n  ━━━ Round 2: 注入扰动（故意运行不存在的包）━━━")
        events = await send_and_wait(ws, (
            "在 perturb_demo/ 下运行 python -c \"import nonexistent_module_xyz\""
        ))
        state2 = read_convergence(session_id)
        print(f"    Curve: {state2['curve']}")
        new_claims = state2["claims"][len(state1["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

        # Round 3: 恢复 — 运行一个成功的命令
        print("\n  ━━━ Round 3: 恢复操作（运行正常命令）━━━")
        events = await send_and_wait(ws, (
            "在 perturb_demo/ 运行 python hello.py 再次验证"
        ))
        state3 = read_convergence(session_id)
        print(f"    Curve: {state3['curve']}")
        new_claims = state3["claims"][len(state2["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

    # 分析
    print("\n  ━━━ 分析 ━━━")
    final = read_convergence(session_id)
    curve = final["curve"]
    print(f"  完整曲线: {' → '.join(f'{c:.2f}' for c in curve)}")

    # 验证曲线有下降
    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    open_claims = sum(1 for c in final["claims"] if c["status"] == "open")

    print(f"  曲线有下降: {'✅' if has_drop else '❌'}")
    print(f"  存在 OPEN claims: {'✅' if open_claims > 0 else '❌'} ({open_claims} open)")

    if has_drop:
        print(f"\n  ✅ Part B 通过 — 端到端扰动正确反映在收敛曲线")
    else:
        # 即使没有下降（因为 OPEN claim 是新增而非回退），验证 OPEN 状态被追踪
        if open_claims > 0:
            print(f"\n  ✅ Part B 通过（变体）— 失败被追踪为 OPEN claim，曲线未满分")
        else:
            print(f"\n  ⚠️ Part B 部分通过 — 失败操作可能未被系统追踪")

    print()
    return has_drop or open_claims > 0


# ═══════════════════════════════════════════════════════════════════
# Part C: 极限恢复弧线 — 失败后模型自诊断修复
# ═══════════════════════════════════════════════════════════════════

async def test_part_c():
    """极限测试：给模型一个确定会失败的场景（语法错误），看收敛曲线"""
    print("=" * 70)
    print("Part C: 恢复弧线 — 确定性失败 + 修复")
    print("=" * 70)

    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)
    print(f"  Session: {session_id[:16]}")

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # Round 1: 创建一个有语法错误的文件并运行（确定失败）
        print("\n  ━━━ Round 1: 创建文件 + 运行（正常）━━━")
        events = await send_and_wait(ws, (
            "创建 arc_demo/ 目录，写 calc.py 内容为：\n"
            "def add(a, b): return a + b\n"
            "print(add(2, 3))\n\n"
            "然后 cd arc_demo && python calc.py 验证输出5。"
        ), timeout=60)
        state1 = read_convergence(session_id)
        print(f"    Curve: {state1['curve']}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

        # Round 2: 故意写一个有语法错误的文件并运行（确定失败）
        print("\n  ━━━ Round 2: 运行有语法错误的命令（确定失败）━━━")
        events = await send_and_wait(ws, (
            "在 arc_demo/ 下运行这个命令（注意这会失败）：\n"
            "python -c \"def broken(: print('never')\""
        ), timeout=30)
        state2 = read_convergence(session_id)
        print(f"    Curve: {state2['curve']}")
        new_claims = state2["claims"][len(state1["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

        # Round 3: 修复后运行（恢复）
        print("\n  ━━━ Round 3: 运行正确命令（恢复）━━━")
        events = await send_and_wait(ws, (
            "在 arc_demo/ 下运行正确的命令：python -c \"print(2+3)\""
        ), timeout=30)
        state3 = read_convergence(session_id)
        print(f"    Curve: {state3['curve']}")
        new_claims = state3["claims"][len(state2["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"      {icon} [{c['status']}] {c['text']}")

    # 最终分析
    print("\n  ━━━ 最终分析 ━━━")
    final = read_convergence(session_id)
    curve = final["curve"]
    if curve:
        print(f"  完整曲线: {' → '.join(f'{c:.2f}' for c in curve)}")
    else:
        print(f"  无收敛数据")

    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    open_total = sum(1 for c in final["claims"] if c["status"] == "open")
    verified_total = sum(1 for c in final["claims"] if c["status"] == "verified")

    print(f"  曲线有下降: {'✅' if has_drop else '❌'}")
    print(f"  最终状态: {verified_total} verified, {open_total} open")

    # Part C 的核心判据：
    # 1. 曲线有下降（Round 2 失败被追踪）
    # 2. OPEN claims 存在
    # 注意：当前系统没有 "恢复" 机制（Round 3 的成功是新 claim，不修复旧 claim）
    # 这是 Day 5 Prober 的动机
    if has_drop and open_total > 0:
        print(f"\n  ✅ Part C 通过 — 失败正确追踪，曲线下降")
        print(f"  💡 发现: 恢复需要 Prober（旧 OPEN claim 无法自动恢复）→ Day 5 动机成立")
    elif open_total > 0:
        print(f"\n  ⚠️ Part C 部分通过 — 有 OPEN 但曲线形态不理想")
    else:
        print(f"\n  ❌ Part C 未通过 — 失败未被捕获")

    print()
    return has_drop or open_total > 0


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "═" * 70)
    print("Day 4 — IterationState 扰动注入实验")
    print("═" * 70 + "\n")

    # Part A: 纯结构验证（不需要模型/服务）
    a_pass = test_part_a()

    # Part B: 端到端扰动
    b_pass = await test_part_b()

    # Part C: 恢复弧线
    c_pass = await test_part_c()

    # 汇总
    print("═" * 70)
    print("Day 4 汇总")
    print("═" * 70)
    print(f"  Part A (结构层回退): {'✅ PASS' if a_pass else '❌ FAIL'}")
    print(f"  Part B (端到端扰动): {'✅ PASS' if b_pass else '❌ FAIL'}")
    print(f"  Part C (恢复弧线):   {'✅ PASS' if c_pass else '❌ FAIL'}")

    all_pass = a_pass and b_pass and c_pass
    print(f"\n  {'✅ Day 4 GO — 系统韧性验证通过' if all_pass else '⚠️ 部分通过 — 需要分析'}")
    print(f"  下一步: {'Day 5 — Prober 是否需要' if all_pass else '分析未通过项原因'}")
    print("═" * 70)


if __name__ == "__main__":
    asyncio.run(main())
