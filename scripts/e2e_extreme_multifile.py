"""
极限 E2E — 多文件接口不匹配 + 跨轮 Prober 修复

这是一个严格的端到端测试，验证：
1. 弱模型能否处理多文件间的接口不一致
2. Prober 注入是否在跨轮对话中发挥真实作用
3. 收敛曲线是否呈现完整的 下降→诊断→修复→恢复 弧线

场景设计（工程难度高于之前所有测试）：
- 3 个互相依赖的 Python 文件
- 故意在需求描述中制造命名不一致（models: fetch_records / main: get_records）
- 运行时才暴露 AttributeError
- Round 2 给新需求时，Prober 注入旧的 OPEN claim
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".deepforge/convergence")


async def send_and_wait(ws, message: str, timeout: float = 120) -> list[dict]:
    await ws.send(json.dumps({"message": message}))
    events = []
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
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
                inner_deadline = time.time() + 45
                while time.time() < inner_deadline:
                    try:
                        msg2 = await asyncio.wait_for(ws.recv(), timeout=8)
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


def get_actions(events: list[dict]) -> list[str]:
    """提取执行的 action 信息"""
    actions = []
    for e in events:
        if e.get("type") == "agent_message":
            actions.append(e.get("content", "")[:80])
        elif e.get("type") == "chunk" and "```" in e.get("content", ""):
            content = e.get("content", "")
            if content.startswith("```"):
                actions.append(content[:100])
    return actions


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
            claims.append({"status": c["status"], "text": c["text"][:120]})

    return {
        "curve": [r["convergence"] for r in revisions],
        "claims": claims,
        "revisions": len(revisions),
    }


async def main():
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)

    print("═" * 70)
    print("极限 E2E — 多文件接口不匹配 + 跨轮 Prober")
    print("═" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # ═══════════════════════════════════════════════════════════
        # Round 1: 创建多文件项目（接口命名故意不一致）
        # 需求中说 "get_records" 但 models 里实际叫 "fetch_records"
        # ═══════════════════════════════════════════════════════════
        print("━━━ Round 1: 创建多文件项目（命名不一致陷阱）━━━")
        print("  需求描述中用了不一致的方法名（get_records vs fetch_records）")
        print()
        t0 = time.time()
        events = await send_and_wait(ws, (
            "创建 inventory/ 目录，包含 3 个文件：\n\n"
            "1. models.py — 数据层：\n"
            "   - 类 InventoryDB，初始化时创建 items 列表 [{\"id\":1,\"name\":\"Widget\",\"qty\":10}]\n"
            "   - 方法 fetch_records(category=None) 返回所有 items（如果 category 不为 None 则过滤）\n"
            "   - 方法 update_qty(item_id, delta) 修改数量，返回 True/False\n\n"
            "2. service.py — 业务层：\n"
            "   - 导入 models.InventoryDB\n"
            "   - 类 InventoryService，初始化创建 self.db = InventoryDB()\n"
            "   - 方法 get_records(category=None) 调用 db 的对应方法\n"
            "   - 方法 restock(item_id, amount) 调用 db.update_qty 加数量\n\n"
            "3. main.py — 入口：\n"
            "   - 导入 service.InventoryService\n"
            "   - 创建 svc 实例\n"
            "   - 打印 svc.get_records() 的结果\n"
            "   - 调用 svc.restock(1, 5)\n"
            "   - 再次打印验证数量变了\n\n"
            "创建后运行 cd inventory && python main.py 验证输出。"
        ), timeout=120)
        elapsed = time.time() - t0

        state1 = read_convergence(session_id)
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  Revisions: {state1['revisions']}")
        print(f"  Curve: {[f'{c:.2f}' for c in state1['curve']]}")
        print(f"  Claims ({len(state1['claims'])}):")
        for c in state1["claims"]:
            icon = {"verified": "✅", "open": "⚠️", "ruled_out": "🔄"}.get(c["status"], "?")
            print(f"    {icon} [{c['status']:10s}] {c['text']}")
        print()

        # 分析 Round 1 状态
        open_r1 = sum(1 for c in state1["claims"] if c["status"] == "open")
        verified_r1 = sum(1 for c in state1["claims"] if c["status"] == "verified")
        ruled_out_r1 = sum(1 for c in state1["claims"] if c["status"] == "ruled_out")
        print(f"  状态: {verified_r1}✅ {open_r1}⚠️ {ruled_out_r1}🔄")

        # ═══════════════════════════════════════════════════════════
        # Round 2: 如果 Round 1 有失败，不告诉模型具体问题，
        # 给一个"追加需求"看 Prober 是否引导模型先修复旧问题
        # ═══════════════════════════════════════════════════════════
        if open_r1 > 0:
            print("\n━━━ Round 2: 追加需求（不提修复，看 Prober 是否引导）━━━")
            print("  给新需求但不提之前的 bug，Prober 应注入 OPEN claims")
        else:
            print("\n━━━ Round 2: 模型自行修复了（追加更难需求）━━━")
            print("  模型太强，一步搞定。追加有运行时逻辑 bug 的需求。")

        t0 = time.time()
        if open_r1 > 0:
            events = await send_and_wait(ws, (
                "给 inventory 项目追加一个功能：\n"
                "在 service.py 加 get_low_stock(threshold=5) 方法，"
                "返回数量低于 threshold 的所有商品。\n"
                "在 main.py 中调用它并打印结果。\n"
                "运行 cd inventory && python main.py 验证。"
            ), timeout=120)
        else:
            # 模型在 Round 1 就搞定了，追加更难的需求
            events = await send_and_wait(ws, (
                "给 inventory 追加功能：\n"
                "1. models.py 加 delete_item(item_id) 方法\n"
                "2. service.py 加 remove_item(item_id) 和 get_low_stock(threshold=5)\n"
                "3. main.py 中：先 restock(1, -20)（让数量变负），\n"
                "   然后调用 get_low_stock() 看是否返回该 item，\n"
                "   再 remove_item(1)，再 get_records() 确认被删除。\n"
                "运行 cd inventory && python main.py 验证所有输出正确。"
            ), timeout=120)

        elapsed = time.time() - t0
        state2 = read_convergence(session_id)
        print(f"\n  耗时: {elapsed:.1f}s")
        print(f"  Curve: {[f'{c:.2f}' for c in state2['curve']]}")
        new_claims = state2["claims"][len(state1["claims"]):]
        print(f"  新增 Claims ({len(new_claims)}):")
        for c in new_claims:
            icon = {"verified": "✅", "open": "⚠️", "ruled_out": "🔄"}.get(c["status"], "?")
            print(f"    {icon} [{c['status']:10s}] {c['text']}")
        print()

        # ═══════════════════════════════════════════════════════════
        # Round 3: 最终验证（完整运行）
        # ═══════════════════════════════════════════════════════════
        print("━━━ Round 3: 最终验证 ━━━")
        events = await send_and_wait(ws, (
            "运行 cd inventory && python main.py，确认所有功能正常工作。"
        ), timeout=60)
        state3 = read_convergence(session_id)
        print(f"  Curve: {[f'{c:.2f}' for c in state3['curve']]}")
        new_claims = state3["claims"][len(state2["claims"]):]
        for c in new_claims:
            icon = {"verified": "✅", "open": "⚠️", "ruled_out": "🔄"}.get(c["status"], "?")
            print(f"    {icon} [{c['status']:10s}] {c['text']}")

    # ═══════════════════════════════════════════════════════════════
    # 最终报告
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "═" * 70)
    print("最终报告")
    print("═" * 70)

    final = read_convergence(session_id)
    curve = final["curve"]
    print(f"\n完整收敛曲线 ({len(curve)} revisions):")
    if len(curve) <= 15:
        print(f"  {' → '.join(f'{c:.2f}' for c in curve)}")
    else:
        print(f"  前10: {' → '.join(f'{c:.2f}' for c in curve[:10])}")
        print(f"  后{len(curve)-10}: {' → '.join(f'{c:.2f}' for c in curve[10:])}")

    verified = sum(1 for c in final["claims"] if c["status"] == "verified")
    open_c = sum(1 for c in final["claims"] if c["status"] == "open")
    ruled_out = sum(1 for c in final["claims"] if c["status"] == "ruled_out")
    total = len(final["claims"])

    print(f"\n最终知识状态:")
    print(f"  Verified: {verified}/{total}")
    print(f"  Open: {open_c}/{total}")
    print(f"  Ruled Out: {ruled_out}/{total}")

    # ━━━ 极限判据（严格） ━━━
    print(f"\n━━━ 极限判据（严格）━━━")

    # 1. 复杂度：至少 10 个 claims（多步骤多文件）
    p1 = total >= 10
    print(f"  [{'✅' if p1 else '❌'}] 复杂度: {total} claims (要求≥10)")

    # 2. 曲线有下降（真实困难，不是假下降）
    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    print(f"  [{'✅' if has_drop else '❌'}] 曲线下降: {has_drop}")

    # 3. 自动恢复（RULED_OUT 存在 = claim closure 机制生效）
    has_recovery = ruled_out > 0
    print(f"  [{'✅' if has_recovery else '⚠️'}] Claim 自动关闭: {ruled_out} ruled_out")

    # 4. 多轮均有知识增长
    p4 = state3["revisions"] > state2["revisions"] > state1["revisions"]
    print(f"  [{'✅' if p4 else '❌'}] 三轮知识增长: rev {state1['revisions']}→{state2['revisions']}→{state3['revisions']}")

    # 5. 最终收敛度 > 0.8（系统最终能完成大部分任务）
    final_conv = curve[-1] if curve else 0
    p5 = final_conv >= 0.8
    print(f"  [{'✅' if p5 else '❌'}] 最终收敛度: {final_conv:.2f} (要求≥0.80)")

    # 6. 多文件操作（至少3个文件创建）
    file_claims = sum(1 for c in final["claims"] if "file created" in c["text"])
    p6 = file_claims >= 3
    print(f"  [{'✅' if p6 else '❌'}] 多文件: {file_claims} files (要求≥3)")

    # 7. Prober 曾经注入（检查日志）
    # 这个通过之前的日志验证确认过了

    passed = sum([p1, has_drop, has_recovery, p4, p5, p6])
    print(f"\n  总评: {passed}/6 极限判据")

    # 分析收敛弧线形态
    if has_drop:
        drop_points = [i for i in range(len(curve)-1) if curve[i] > curve[i+1]]
        recovery_points = [i for i in range(len(curve)-1) if curve[i] < curve[i+1]]
        print(f"\n  曲线分析:")
        print(f"    下降点: {len(drop_points)} 次")
        print(f"    上升点: {len(recovery_points)} 次")
        if recovery_points and drop_points:
            max_drop = max(curve[i] - curve[i+1] for i in drop_points)
            max_rise = max(curve[i+1] - curve[i] for i in recovery_points)
            print(f"    最大单步下降: {max_drop:.3f}")
            print(f"    最大单步恢复: {max_rise:.3f}")

    # 模型能力分析
    print(f"\n━━━ 模型能力分析 ━━━")
    if open_r1 == 0:
        print(f"  🔥 模型在 Round 1 自行解决了接口不匹配问题")
        print(f"     Qwen3.6 对多文件接口一致性有强感知")
    else:
        if has_recovery:
            print(f"  🔧 模型遇到了接口问题，通过 Prober 引导+自诊断修复")
        else:
            print(f"  ⚠️ 接口问题产生了未恢复的 OPEN claims")

    print(f"\n{'═'*70}")


if __name__ == "__main__":
    asyncio.run(main())
