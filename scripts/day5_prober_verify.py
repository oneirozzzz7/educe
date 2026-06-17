"""
Day 5 — Prober 验证测试

验证 IterationState OPEN claims 注入到 system prompt 后，
模型是否能"感知"失败并主动修复。

场景：
1. Round 1: 运行一个必定失败的命令（产生 OPEN claim）
2. Round 2: 给一个相关但不同的需求 — 模型应该能看到 OPEN claim 并关联修复
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


def get_model_responses(events: list[dict]) -> str:
    """从 events 中提取模型回复文本"""
    texts = []
    for e in events:
        if e.get("type") == "assistant_message":
            texts.append(e.get("content", ""))
        elif e.get("type") == "text_chunk":
            texts.append(e.get("content", ""))
    return " ".join(texts)


async def main():
    session_id = str(uuid.uuid4())
    ws_url = SERVER_URL.format(session_id=session_id)

    print("=" * 70)
    print("Day 5 — Prober 验证: OPEN claims 感知 + 自发修复")
    print("=" * 70)
    print(f"Session: {session_id[:16]}")
    print()

    async with websockets.connect(ws_url, ping_interval=None) as ws:
        await asyncio.sleep(1)

        # ═══ Round 1: 创建项目 + 故意让一个命令失败 ═══
        print("━━━ Round 1: 创建项目 + 注入失败 ━━━")
        events = await send_and_wait(ws, (
            "创建 prober_test/ 目录，写 app.py 内容为 print('hello')，"
            "然后运行 cd prober_test && python app.py 验证。"
            "之后运行 cd prober_test && python missing_file.py（这个会失败没关系）。"
        ), timeout=60)
        state1 = read_convergence(session_id)
        print(f"  Curve: {state1['curve']}")
        for c in state1["claims"]:
            icon = "✅" if c["status"] == "verified" else "⚠️"
            print(f"    {icon} [{c['status']}] {c['text']}")

        open_count = sum(1 for c in state1["claims"] if c["status"] == "open")
        print(f"\n  OPEN claims: {open_count}")
        assert open_count > 0, "预期应该有 OPEN claim（missing_file.py 失败）"
        print("  ✅ 成功产生 OPEN claim")

        # ═══ Round 2: 发送新消息，验证模型"看到"了 OPEN claims ═══
        # 关键：模型的 system prompt 中现在应该包含 "待处理问题" 部分
        print("\n━━━ Round 2: 新消息 — 验证模型能否感知 OPEN claims ━━━")
        events = await send_and_wait(ws, (
            "检查一下 prober_test/ 目录现在的状态，有什么问题需要修复吗？"
        ), timeout=60)

        response_text = get_model_responses(events)
        print(f"  模型回复（前200字）: {response_text[:200]}")

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

    # 判据1: 模型回复中提到了 missing_file 相关内容
    mentions_issue = any(kw in response_text.lower() for kw in
                        ["missing", "不存在", "失败", "错误", "问题", "修复", "fix"])
    print(f"\n  判据1 — 模型感知到问题: {'✅' if mentions_issue else '❌'}")
    if mentions_issue:
        print(f"    模型回复中包含了问题相关关键词")

    # 判据2: 收敛曲线有变化（Round 2 产生了新 claims）
    growth = state2["revisions"] > state1["revisions"]
    print(f"  判据2 — 知识增长: {'✅' if growth else '⚠️'}")

    # 总结
    if mentions_issue:
        print(f"\n  ✅ Prober 验证通过 — 模型能感知 OPEN claims 并做出响应")
        print(f"  Prober 方案 C（注入 prompt）有效！")
    else:
        print(f"\n  ⚠️ 需要进一步验证 — 模型可能没注意到 OPEN claims")
        print(f"  可能原因：1) 注入位置不够显眼 2) 模型忽略了补充信息")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
