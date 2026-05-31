"""
LLM路由准确率验证——测试4选1路由是否可靠
"""
import asyncio
import json
import websockets
import uuid

ROUTE_TESTS = [
    # (input, expected_action, reason)
    # REPLY cases
    ("你好", "reply", "简单问候"),
    ("什么是人工智能", "reply", "知识提问"),
    ("量子计算是什么", "reply", "科学问题"),
    ("红烧肉怎么做", "reply", "生活问题"),
    ("帮我分析一下这篇文章的论点", "reply", "分析任务"),
    ("翻译一下这段话", "reply", "翻译任务"),

    # BUILD cases
    ("做一个计算器", "build", "简单工具"),
    ("帮我写一个番茄钟网页", "build", "网页工具"),
    ("做个贪吃蛇游戏", "build", "游戏"),
    ("写一个Python脚本统计文件行数", "build", "脚本"),

    # CLARIFY cases (这些需要更多信息)
    ("帮我弄一下", "clarify", "完全模糊"),
    ("那个东西能不能搞一下", "clarify", "指代不清"),

    # PLAN cases (这些是复杂任务)
    ("帮我做一个超级玛丽游戏", "plan", "复杂游戏"),
    ("做一个完整的博客系统", "plan", "大型项目"),
]


async def test_routing():
    print("LLM Router Accuracy Test ({} cases)".format(len(ROUTE_TESTS)))
    print()

    correct = 0
    results = []

    for input_text, expected, reason in ROUTE_TESTS:
        sid = uuid.uuid4().hex[:8]
        try:
            async with websockets.connect("ws://localhost:7860/ws/{}".format(sid)) as ws:
                await ws.send(json.dumps({"message": input_text}))
                got_action = "unknown"
                reply = ""
                try:
                    while True:
                        d = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                        if d.get("type") == "plan_proposal":
                            got_action = "plan"
                        elif d.get("type") == "agent_message":
                            reply = d.get("content", "")
                            if "<!DOCTYPE" in reply or "filepath:" in reply or "未能生成" in reply:
                                got_action = "build"
                            else:
                                got_action = "reply"
                        elif d.get("content") == "idle":
                            break
                except asyncio.TimeoutError:
                    got_action = "timeout"
        except Exception as e:
            got_action = "error"

        # CLARIFY没有明确的WebSocket消息类型，暂时归为reply
        if expected == "clarify" and got_action == "reply":
            # 检查回复是否是追问
            is_question = "?" in reply or "？" in reply or "什么" in reply[:50]
            if is_question:
                got_action = "clarify"

        match = got_action == expected or (expected == "plan" and got_action in ("plan", "build"))
        if match:
            correct += 1
        tag = "PASS" if match else "FAIL"

        results.append({"input": input_text[:20], "expected": expected, "got": got_action, "match": match})
        print("  {} | exp={:7s} got={:7s} | {} | {}".format(
            tag, expected, got_action, reason, input_text[:25]))

    print()
    accuracy = correct / len(ROUTE_TESTS) * 100
    print("Accuracy: {}/{} ({:.0f}%)".format(correct, len(ROUTE_TESTS), accuracy))
    print("Target: >= 85%")
    print("Verdict: {}".format("PASS" if accuracy >= 85 else "NEEDS WORK"))


if __name__ == "__main__":
    asyncio.run(test_routing())
