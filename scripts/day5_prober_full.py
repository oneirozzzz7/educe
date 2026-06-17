"""
Day 5 Prober 完整验证 — 可修复的 OPEN claim

场景：创建一个用了 colorama 的脚本但不先安装 → 运行失败 → OPEN claim
Round 2: 问模型"有什么问题"，Prober 注入 OPEN claim，模型应该安装 colorama 并重试

与上一版区别：这次的 OPEN claim 是模型能实际修复的。
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


def get_reply_text(events: list[dict]) -> str:
    """从 chunk 事件中提取模型回复文本"""
    chunks = []
    for e in events:
        if e.get("type") == "chunk":
            content = e.get("content", "")
            if not content.startswith("```"):
                chunks.append(content)
    return "".join(chunks)


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
    print("Day 5 Prober 完整验证 — 可修复 OPEN claim + 模型自发修复")
    print("=" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # ═══ Round 1: 写一个用了 pyyaml 但没安装的脚本 ═══
        # 先卸载 pyyaml 确保失败
        print("━━━ 准备: 确保 pyyaml 未安装 ━━━")
        import subprocess
        subprocess.run(["pip", "uninstall", "pyyaml", "-y"],
                       capture_output=True, timeout=10)

        print("\n━━━ Round 1: 创建用了 yaml 的脚本 + 运行（预期失败）━━━")
        events = await send_and_wait(ws, (
            "创建 yaml_demo/ 目录，写 config_parser.py：\n"
            "```python\n"
            "import yaml\n"
            "data = {'name': 'educe', 'version': '1.0'}\n"
            "result = yaml.dump(data)\n"
            "print(result)\n"
            "```\n"
            "然后运行 cd yaml_demo && python config_parser.py"
        ), timeout=60)
        state1 = read_convergence(session_id)
        print(f"  Curve: {state1['curve']}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")

        open_count = sum(1 for c in state1["claims"] if c["status"] == "open")
        print(f"\n  OPEN claims: {open_count}")

        if open_count == 0:
            print("  ⚠️ pyyaml 可能已安装，尝试不同方案")
            # 如果 yaml 已安装，用另一个肯定没装的包
            events = await send_and_wait(ws, (
                "在 yaml_demo/ 下创建 test2.py：\n"
                "import rich_yaml_formatter_xyz\n"
                "print('ok')\n"
                "然后运行 cd yaml_demo && python test2.py"
            ), timeout=30)
            state1 = read_convergence(session_id)
            open_count = sum(1 for c in state1["claims"] if c["status"] == "open")
            print(f"  重试后 OPEN claims: {open_count}")
            for c in state1["claims"]:
                if c["status"] == "open":
                    print(f"    ⚠️ [{c['status']}] {c['text']}")

        # ═══ Round 2: 新消息 — 模型应该看到 OPEN claim 并尝试修复 ═══
        print("\n━━━ Round 2: 让模型修复问题 ━━━")
        print("  (Prober 应该注入 OPEN claims 到 system prompt)")
        events = await send_and_wait(ws, (
            "刚才的脚本运行失败了，请帮我修复这个问题然后重新运行验证。"
        ), timeout=60)

        reply = get_reply_text(events)
        print(f"  模型回复: {reply[:200]}")

        state2 = read_convergence(session_id)
        print(f"  Curve: {state2['curve']}")
        new_claims = state2["claims"][len(state1["claims"]):]
        for c in new_claims:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")

    # ═══ 分析 ═══
    print("\n" + "=" * 70)
    print("分析")
    print("=" * 70)

    final = read_convergence(session_id)
    curve = final["curve"]
    if curve:
        print(f"  完整曲线: {' → '.join(f'{c:.2f}' for c in curve)}")

    verified_r2 = sum(1 for c in new_claims if c["status"] == "verified")
    print(f"\n  Round 2 新增 verified: {verified_r2}")

    # 判据: Round 2 是否产生了新的 VERIFIED claims（证明模型在修复）
    has_drop = any(curve[i] > curve[i+1] for i in range(len(curve)-1)) if len(curve) > 1 else False
    print(f"  曲线有下降: {'✅' if has_drop else '⚠️'}")
    print(f"  模型产生了修复动作: {'✅' if verified_r2 > 0 else '❌'}")

    # 检查模型回复是否提到了修复
    mentions_fix = any(kw in reply.lower() for kw in
                       ["install", "pip", "安装", "修复", "fix", "依赖"])
    print(f"  回复提到修复: {'✅' if mentions_fix else '⚠️'}")

    if verified_r2 > 0 and has_drop:
        print(f"\n  ✅ 完整恢复弧线验证通过")
        print(f"  Prober 注入 → 模型感知 → 自发修复 → 新 verified claims")
    elif verified_r2 > 0:
        print(f"\n  ✅ 模型成功修复（无曲线下降可能是 Round 1 就在修复中）")
    else:
        print(f"\n  ⚠️ 需要进一步分析")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
