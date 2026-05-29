import asyncio
import json
import websockets
import uuid
import sys
import time
sys.path.insert(0, ".")

ROUTE_TESTS = [
    ("什么是人工智能", "text"),
    ("做一个番茄钟", "code"),
    ("量子计算是什么", "text"),
    ("帮我写一个计算器网页", "code"),
    ("红烧肉怎么做", "text"),
    ("帮我做一个贪吃蛇游戏", "code"),
    ("介绍一下机器学习", "text"),
    ("写个Python脚本统计文件行数", "code"),
]


async def test_route():
    print("=" * 50)
    print("Phase 1: 路由准确率测试")
    print("=" * 50)
    ok = 0
    total = len(ROUTE_TESTS)
    for q, expected in ROUTE_TESTS:
        sid = uuid.uuid4().hex[:8]
        try:
            async with websockets.connect("ws://localhost:7860/ws/" + sid) as ws:
                await ws.send(json.dumps({"message": q}))
                reply = ""
                try:
                    while True:
                        d = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
                        if d.get("type") == "agent_message":
                            reply = d.get("content", "")
                        if d.get("content") == "idle":
                            break
                except asyncio.TimeoutError:
                    pass

                is_code = ("<!DOCTYPE" in reply or "filepath:" in reply
                          or "<html" in reply.lower()
                          or "未能生成" in reply)
                actual = "code" if is_code else "text"
                correct = actual == expected
                if correct:
                    ok += 1
                tag = "PASS" if correct else "FAIL"
                print("  {} | {} | expected={} got={} | reply={}...".format(
                    tag, q[:20], expected, actual, reply[:60].replace("\n", " ")))
        except Exception as e:
            print("  ERROR | {} | {}".format(q[:20], str(e)[:60]))
    print("  Route accuracy: {}/{} ({:.0f}%)".format(ok, total, ok / total * 100))
    return ok, total


async def test_benchmark():
    print()
    print("=" * 50)
    print("Phase 1: 20-question benchmark")
    print("=" * 50)
    from tests.ab_experiment import TEST_QUESTIONS, score_response
    sid = uuid.uuid4().hex[:8]
    scores = []
    async with websockets.connect("ws://localhost:7860/ws/" + sid) as ws:
        for i, (q, domain, kw, bad) in enumerate(TEST_QUESTIONS):
            await ws.send(json.dumps({"message": q}))
            reply = ""
            try:
                while True:
                    d = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
                    if d.get("type") == "agent_message":
                        reply = d.get("content", "")
                    if d.get("content") == "idle":
                        break
            except asyncio.TimeoutError:
                pass
            s = score_response(q, domain, reply, kw, bad)
            total = round(sum(s.values()) / 4, 1)
            scores.append(total)
            print("  Q{:02d} | {:.1f} | {} | {}...".format(
                i + 1, total, domain, q[:30]))

    avg = round(sum(scores) / len(scores), 2) if scores else 0
    target = 7.70
    tag = "PASS" if avg >= target else "NEEDS WORK"
    print()
    print("  Average: {} (target: {}) -> {}".format(avg, target, tag))
    return avg


async def main():
    print("DeepForge Phase 1 Verification")
    print("Started at:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print()

    route_ok, route_total = await test_route()
    avg_score = await test_benchmark()

    print()
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    print("  Route: {}/{} ({:.0f}%)".format(route_ok, route_total, route_ok / route_total * 100))
    print("  Benchmark: {:.2f} (target 7.70)".format(avg_score))
    if route_ok >= 7 and avg_score >= 7.70:
        print("  OVERALL: PASS")
    else:
        print("  OVERALL: NEEDS IMPROVEMENT")


if __name__ == "__main__":
    asyncio.run(main())
