"""
端到端WebSocket测试——协作式构建流程
模拟真实的 WebSocket 交互：
1. 发送"做一个坦克大战游戏"
2. 收到 decision_request
3. 发送 decision_response
4. 收到构建结果
"""
import asyncio
import json
import sys
sys.path.insert(0, ".")

import websockets


async def test_e2e_collaborative():
    uri = "ws://localhost:7860/ws/test-collab-001"

    async with websockets.connect(uri, ping_interval=30) as ws:
        print("=== 连接成功 ===")

        # Step 1: 发送复杂任务
        await ws.send(json.dumps({
            "type": "message",
            "message": "做一个坦克大战游戏",
        }))
        print(">>> 已发送: 做一个坦克大战游戏")

        # Step 2: 等待消息，期望收到 decision_request
        got_decision = False
        decisions = []
        timeout = 60

        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "status":
                    print(f"  [status] {msg.get('content', '')}")
                elif msg_type == "decision_request":
                    got_decision = True
                    decisions = msg.get("decisions", [])
                    print(f"  ✅ [decision_request] 收到 {len(decisions)} 个决策点:")
                    for i, d in enumerate(decisions):
                        print(f"     {i+1}. {d.get('question', '')}")
                        for j, opt in enumerate(d.get('options', [])):
                            print(f"        - {opt}")
                    break
                elif msg_type == "chunk":
                    print(f"  [chunk] {msg.get('text', '')[:50]}...")
                elif msg_type == "agent_message":
                    print(f"  [agent] {msg.get('sender', '')}: {msg.get('content', '')[:80]}...")
                elif msg_type == "build_progress":
                    print(f"  [build] {msg.get('step', '')}")
                elif msg_type == "expert":
                    print(f"  [expert] {msg.get('content', '')}")
                elif msg_type == "error":
                    print(f"  ❌ [error] {msg.get('content', '')}")
                    break
                else:
                    print(f"  [{msg_type}] {json.dumps(msg, ensure_ascii=False)[:100]}")
        except asyncio.TimeoutError:
            print(f"  ⏰ 超时 ({timeout}s)")

        if not got_decision:
            print("\n❌ 未收到 decision_request")
            return False

        # Step 3: 发送 decision_response（选第一个选项）
        choices = []
        for d in decisions:
            choices.append({
                "question": d["question"],
                "choice": d["options"][0] if d.get("options") else "默认"
            })

        await ws.send(json.dumps({
            "type": "decision_response",
            "decisions": choices
        }))
        print(f"\n>>> 已发送 decision_response: 选择了每个问题的第一个选项")

        # Step 4: 等待构建结果
        got_result = False
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "status":
                    status = msg.get("content", "")
                    print(f"  [status] {status}")
                    if status == "idle":
                        got_result = True
                        break
                elif msg_type == "build_progress":
                    print(f"  [build] {msg.get('step', '')}")
                elif msg_type == "chunk":
                    text = msg.get("text", "")
                    if len(text) > 50:
                        text = text[:50] + "..."
                    print(f"  [chunk] {text}")
                elif msg_type == "agent_message":
                    content = msg.get("content", "")
                    print(f"  [agent] {msg.get('sender','')}: {content[:80]}...")
                elif msg_type == "error":
                    print(f"  ❌ [error] {msg.get('content', '')}")
                    break
                else:
                    print(f"  [{msg_type}] ...")
        except asyncio.TimeoutError:
            print(f"  ⏰ 构建超时")

        if got_result:
            print("\n✅ 协作式构建端到端流程完成")
        else:
            print("\n⚠️ 构建可能未正常完成")

        return got_decision and got_result


if __name__ == "__main__":
    result = asyncio.run(test_e2e_collaborative())
    sys.exit(0 if result else 1)
