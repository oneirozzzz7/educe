"""
多轮对话路径系统性测试
覆盖6种真实用户路径，验证上下文管理是否正确。
"""
import asyncio
import json
import websockets
import uuid


async def run_session(steps):
    """运行一个多轮session，返回每步的结果"""
    sid = uuid.uuid4().hex[:8]
    results = []
    async with websockets.connect("ws://localhost:7860/ws/{}".format(sid)) as ws:
        for step in steps:
            msg = step["input"]
            await ws.send(json.dumps({"message": msg}))
            reply = ""
            progress = []
            while True:
                d = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if d.get("type") == "agent_message":
                    reply = d.get("content", "")
                if d.get("type") == "build_progress":
                    progress.append(d.get("step", ""))
                if d.get("content") == "idle":
                    break
            is_code = "<!DOCTYPE" in reply or "filepath:" in reply or bool(progress)
            results.append({
                "input": msg,
                "reply_len": len(reply),
                "is_code": is_code,
                "reply_preview": reply[:200],
                "progress": progress,
            })
    return results


def check_pollution(result, forbidden_keywords, required_keywords=None):
    """检查回复是否被实质性污染（不是简单提及）"""
    reply = result["reply_preview"]
    # 实质性污染 = 前100字之后仍然在讨论前序话题
    main_body = reply[100:] if len(reply) > 100 else reply
    polluted = any(kw in main_body for kw in forbidden_keywords)
    relevant = True
    if required_keywords:
        relevant = any(kw in reply for kw in required_keywords)
    return {"polluted": polluted, "relevant": relevant}


async def test_all_paths():
    print("=" * 60)
    print("Multi-turn Context Management Test (6 paths)")
    print("=" * 60)
    print()

    passed = 0
    total = 6

    # Path 1: text → text (不同话题)
    print("Path 1: text → text (topic switch)")
    r = await run_session([
        {"input": "量子计算是什么"},
        {"input": "红烧肉怎么做"},
    ])
    check = check_pollution(r[1], ["量子", "计算机", "qubit"], ["肉", "五花", "红烧", "炒", "煮"])
    ok = not check["polluted"] and check["relevant"]
    print("  Step 2 reply: {}...".format(r[1]["reply_preview"][:80]))
    print("  Polluted: {}  Relevant: {}  {}".format(check["polluted"], check["relevant"], "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    # Path 2: text → code → text
    print("Path 2: text → code → text")
    r = await run_session([
        {"input": "什么是机器学习"},
        {"input": "做一个BMI计算器"},
        {"input": "糖醋排骨怎么做"},
    ])
    check = check_pollution(r[2], ["计算器", "BMI", "机器学习", "算法"], ["排骨", "糖醋", "醋", "炸"])
    ok = not check["polluted"] and check["relevant"]
    print("  Step 3 reply: {}...".format(r[2]["reply_preview"][:80]))
    print("  Polluted: {}  Relevant: {}  {}".format(check["polluted"], check["relevant"], "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    # Path 3: code → code (不同项目)
    print("Path 3: code → code (different projects)")
    r = await run_session([
        {"input": "做一个计算器"},
        {"input": "做一个番茄钟"},
    ])
    has_tomato = "番茄" in r[1]["reply_preview"] or "倒计时" in r[1]["reply_preview"] or "tomato" in r[1]["reply_preview"].lower()
    has_calc_in_2 = "计算器" in r[1]["reply_preview"][:100]
    ok = has_tomato and not has_calc_in_2
    print("  Step 2 reply: {}...".format(r[1]["reply_preview"][:80]))
    print("  About tomato: {}  Calculator leak: {}  {}".format(has_tomato, has_calc_in_2, "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    # Path 4: code → text
    print("Path 4: code → text")
    r = await run_session([
        {"input": "做一个密码生成器"},
        {"input": "TCP三次握手是什么"},
    ])
    check = check_pollution(r[1], ["密码生成", "password", "random"], ["TCP", "握手", "SYN", "ACK"])
    ok = not check["polluted"] and check["relevant"]
    print("  Step 2 reply: {}...".format(r[1]["reply_preview"][:80]))
    print("  Polluted: {}  Relevant: {}  {}".format(check["polluted"], check["relevant"], "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    # Path 5: 多轮同话题 → 切换
    print("Path 5: multi-turn same topic → switch")
    r = await run_session([
        {"input": "量子计算是什么"},
        {"input": "继续深入讲讲"},
        {"input": "红烧肉怎么做"},
    ])
    check = check_pollution(r[2], ["量子", "qubit", "叠加"], ["肉", "五花", "红烧"])
    ok = not check["polluted"] and check["relevant"]
    print("  Step 3 reply: {}...".format(r[2]["reply_preview"][:80]))
    print("  Polluted: {}  Relevant: {}  {}".format(check["polluted"], check["relevant"], "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    # Path 6: 追问（应该保留上下文）
    print("Path 6: follow-up (should keep context)")
    r = await run_session([
        {"input": "光速为什么不能被超越"},
        {"input": "你说的相对论能再详细解释一下吗"},
    ])
    has_relativity = "相对论" in r[1]["reply_preview"] or "爱因斯坦" in r[1]["reply_preview"] or "光速" in r[1]["reply_preview"]
    ok = has_relativity
    print("  Step 2 reply: {}...".format(r[1]["reply_preview"][:80]))
    print("  Keeps context: {}  {}".format(has_relativity, "PASS" if ok else "FAIL"))
    if ok: passed += 1
    print()

    print("=" * 60)
    print("Result: {}/{} paths passed".format(passed, total))
    print("=" * 60)
    return passed, total


if __name__ == "__main__":
    p, t = asyncio.run(test_all_paths())
