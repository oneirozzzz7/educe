"""
极限 E2E — 失败→诊断→修复→恢复弧线

场景设计：
给模型一个"几乎正确但必须调试才能跑通"的多步任务。
不直接告诉它"有 bug"，而是让它在运行时发现错误，自己修复。

测试场景：创建一个 Python HTTP API，代码中有一个隐蔽的 bug
（比如变量名拼写错误），模型需要：
1. 创建文件
2. 启动 → 发现启动失败
3. 检查错误日志 → 定位问题
4. 修复 → 重启 → 验证通过

收敛曲线预期：1.0 → 1.0 → 下降(启动失败) → 回升(修复后)

但是！当前系统无法"恢复" OPEN claim（Day 4 发现），
所以实际预期是：上升 → 下降 → 微回升（新 claim 稀释）。
这正是 Prober 必要性的又一证据。
"""
import asyncio
import json
import time
import uuid
from pathlib import Path

import websockets

SERVER_URL = "ws://localhost:7860/ws/{session_id}"
CONVERGENCE_DIR = Path(".educe/convergence")


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
    print("极限 E2E — 失败→诊断→修复→恢复弧线")
    print("=" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # ═══ Round 1: 给一个有隐蔽 bug 的完整项目需求 ═══
        # 策略：要求创建一个 HTTP 服务并验证，但代码中有 typo
        # 让模型自己发现（运行失败时看错误信息）并修复
        print("━━━ Round 1: 创建项目 + 启动（预期遇到问题）━━━")
        print("  需求：创建一个 JSON API 项目，启动后 curl 测试")
        t0 = time.time()
        events = await send_and_wait(ws, (
            "创建 bugfix_demo/ 目录，创建 api.py 文件，内容：\n"
            "```python\n"
            "import json\n"
            "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
            "\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200)\n"
            "        self.send_header('Content-Type', 'application/json')\n"
            "        self.end_headers()\n"
            "        data = {'status': 'ok', 'items': [1, 2, 3]}\n"
            "        self.wfile.write(json.dumps(dat).encode())  # bug: dat instead of data\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    server = HTTPServer(('', 8877), Handler)\n"
            "    print('Server starting on port 8877')\n"
            "    server.serve_forever()\n"
            "```\n\n"
            "然后在后台启动这个服务（nohup python api.py > api.log 2>&1 &），"
            "等 2 秒后 curl http://localhost:8877/ 测试。"
            "如果 curl 失败或返回错误，检查 api.log 找出原因并修复。"
        ), timeout=120)
        elapsed = time.time() - t0
        state1 = read_convergence(session_id)
        print(f"  耗时: {elapsed:.1f}s")
        print(f"  Curve: {state1['curve']}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

        # 分析 Round 1 结果
        open_r1 = sum(1 for c in state1["claims"] if c["status"] == "open")
        verified_r1 = sum(1 for c in state1["claims"] if c["status"] == "verified")
        print(f"  Round 1 结果: {verified_r1} verified, {open_r1} open")

        # ═══ Round 2: 如果模型在 Round 1 就自己修了，给更多验证 ═══
        # 如果没修，引导它去看 log
        if open_r1 == 0 and verified_r1 > 0:
            print("\n  💡 模型在 Round 1 就自己发现并修复了 bug！")
            print("  追加验证：测试更多 endpoint")
            print("\n━━━ Round 2: 追加功能验证（POST 请求）━━━")
            events = await send_and_wait(ws, (
                "给 bugfix_demo/api.py 追加 POST 处理：接收 JSON body，"
                "返回 {'received': body, 'count': len(body)}。"
                "重启服务后用 curl -X POST -d '{\"a\":1}' 测试。"
            ), timeout=90)
        else:
            print("\n━━━ Round 2: 引导诊断修复 ━━━")
            events = await send_and_wait(ws, (
                "刚才 curl 可能失败了。检查 bugfix_demo/api.log 的错误信息，"
                "找到 bug 并修复 api.py，然后重启服务再测试。"
            ), timeout=90)

        state2 = read_convergence(session_id)
        print(f"  Curve: {state2['curve']}")
        new_claims = state2["claims"][len(state1["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

        # ═══ Round 3: 最终验证 ═══
        print("━━━ Round 3: 最终 curl 验证 ━━━")
        events = await send_and_wait(ws, (
            "curl http://localhost:8877/ 验证返回 JSON 中包含 'status' 字段"
        ), timeout=30)
        state3 = read_convergence(session_id)
        print(f"  Curve: {state3['curve']}")
        new_claims = state3["claims"][len(state2["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")
        print()

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
    else:
        print("  无数据")

    # 分析
    verified_count = sum(1 for c in final["claims"] if c["status"] == "verified")
    open_count = sum(1 for c in final["claims"] if c["status"] == "open")
    total = len(final["claims"])

    print(f"\n最终知识状态:")
    print(f"  Verified: {verified_count}/{total}")
    print(f"  Open: {open_count}/{total}")
    print(f"  最终收敛度: {curve[-1]:.2f}" if curve else "  无数据")

    # 判据
    print(f"\n━━━ 极限 E2E 判据 ━━━")

    # 判据1: 至少 4 个 claims
    p1 = total >= 4
    print(f"  [{'✅' if p1 else '❌'}] 复杂度: {total} claims (要求≥4)")

    # 判据2: 曲线有下降（遇到 bug）
    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    print(f"  [{'✅' if has_drop else '⚠️'}] 曲线有下降: {has_drop}")

    # 判据3: 最终收敛度 > 下降点（有恢复趋势）
    if has_drop:
        drop_val = min(curve)
        recovery = curve[-1] > drop_val
        print(f"  [{'✅' if recovery else '⚠️'}] 恢复趋势: 最低{drop_val:.2f} → 最终{curve[-1]:.2f}")
    else:
        recovery = False
        print(f"  [⚠️] 恢复趋势: N/A（无下降）")

    # 判据4: 模型执行了修复动作（有 write_file 或 shell 成功在失败之后）
    claims_ordered = final["claims"]
    found_fail = False
    found_fix_after_fail = False
    for c in claims_ordered:
        if c["status"] == "open":
            found_fail = True
        elif found_fail and c["status"] == "verified":
            found_fix_after_fail = True
            break
    # 如果没有失败但全部验证通过 = 模型太强，一步到位修了
    model_self_fixed = (open_count == 0 and verified_count >= 4)
    print(f"  [{'✅' if found_fix_after_fail or model_self_fixed else '⚠️'}] "
          f"修复行为: {'模型自修复' if found_fix_after_fail else '一步到位' if model_self_fixed else '未观察到修复'}")

    # 判据5: 多轮交互有知识增长
    p5 = state3["revisions"] > state1["revisions"]
    print(f"  [{'✅' if p5 else '❌'}] 知识增长: rev {state1['revisions']}→{state3['revisions']}")

    # 总结
    passed = sum([p1, p5, has_drop or model_self_fixed])
    print(f"\n  总评: {passed}/3 核心判据通过")

    if model_self_fixed and not has_drop:
        print(f"  📝 注意: 模型在单轮内自行修复了 bug（曲线无下降）")
        print(f"     这说明弱模型能力超出预期——它看到代码中的 typo 后直接修了")
        print(f"     证据：Round 1 就产生了多个 verified claims")

    if has_drop and not recovery:
        print(f"  📝 注意: 曲线下降后未恢复——这是 Day 4 发现的 Prober 缺口")
        print(f"     OPEN claim 不会被新的成功操作自动关闭")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
