"""
路由测试池——50+个case覆盖4种动作，每次随机抽30个
分布：REPLY 40% / BUILD 30% / CLARIFY 15% / PLAN 15%
"""
import random
import asyncio
import json
import websockets
import uuid

ROUTE_TEST_POOL = [
    # ═══ REPLY cases (20个) ═══
    # easy
    {"input": "你好", "expected": ["reply"], "difficulty": "easy"},
    {"input": "介绍刘备", "expected": ["reply"], "difficulty": "easy"},
    {"input": "今天天气怎么样", "expected": ["reply"], "difficulty": "easy"},
    {"input": "1+1等于几", "expected": ["reply"], "difficulty": "easy"},
    {"input": "谢谢你的帮助", "expected": ["reply"], "difficulty": "easy"},
    # medium
    {"input": "什么是量子纠缠", "expected": ["reply"], "difficulty": "medium"},
    {"input": "比较React和Vue的优劣", "expected": ["reply"], "difficulty": "medium"},
    {"input": "帮我分析一下中国房价走势", "expected": ["reply"], "difficulty": "medium"},
    {"input": "怎么提高英语口语", "expected": ["reply"], "difficulty": "medium"},
    {"input": "写一首关于秋天的诗", "expected": ["reply"], "difficulty": "medium"},
    {"input": "糖尿病患者饮食注意什么", "expected": ["reply"], "difficulty": "medium"},
    {"input": "解释一下区块链的原理", "expected": ["reply"], "difficulty": "medium"},
    # hard (容易被误判为BUILD的REPLY)
    {"input": "分析一下这段代码的问题", "expected": ["reply"], "difficulty": "hard"},
    {"input": "Python的装饰器怎么理解", "expected": ["reply"], "difficulty": "hard"},
    {"input": "帮我想一个APP的名字", "expected": ["reply"], "difficulty": "hard"},
    {"input": "数据库设计有什么原则", "expected": ["reply"], "difficulty": "hard"},
    {"input": "怎么设计一个好的API", "expected": ["reply"], "difficulty": "hard"},
    {"input": "红烧肉的做法步骤", "expected": ["reply"], "difficulty": "medium"},
    {"input": "三国演义的主要人物关系", "expected": ["reply"], "difficulty": "medium"},
    {"input": "deepseek模型能力怎么样", "expected": ["reply"], "difficulty": "medium"},

    # ═══ BUILD cases (15个) ═══
    # easy
    {"input": "做一个计算器", "expected": ["build"], "difficulty": "easy"},
    {"input": "做一个番茄钟", "expected": ["build"], "difficulty": "easy"},
    {"input": "写个Hello World网页", "expected": ["build"], "difficulty": "easy"},
    {"input": "做一个BMI计算器", "expected": ["build"], "difficulty": "easy"},
    {"input": "帮我写一个倒计时器", "expected": ["build"], "difficulty": "easy"},
    # medium
    {"input": "做一个密码生成器", "expected": ["build"], "difficulty": "medium"},
    {"input": "写个Python脚本统计文件行数", "expected": ["build"], "difficulty": "medium"},
    {"input": "做一个单位换算工具", "expected": ["build"], "difficulty": "medium"},
    {"input": "帮我做一个颜色选择器", "expected": ["build"], "difficulty": "medium"},
    # hard (边界case: BUILD或PLAN都合理)
    {"input": "做个贪吃蛇游戏", "expected": ["build", "plan"], "difficulty": "hard"},
    {"input": "帮我做一个记账本应用", "expected": ["build", "plan"], "difficulty": "hard"},
    {"input": "做一个简单的聊天界面", "expected": ["build", "plan"], "difficulty": "hard"},
    {"input": "写一个爬虫抓取新闻标题", "expected": ["build"], "difficulty": "medium"},
    {"input": "做一个Markdown编辑器", "expected": ["build", "plan"], "difficulty": "hard"},
    {"input": "帮我写一个正则表达式测试工具", "expected": ["build"], "difficulty": "medium"},

    # ═══ CLARIFY cases (8个) ═══
    {"input": "帮我弄一下", "expected": ["clarify"], "difficulty": "easy"},
    {"input": "那个东西能不能搞一下", "expected": ["clarify"], "difficulty": "easy"},
    {"input": "帮我看看", "expected": ["clarify"], "difficulty": "easy"},
    {"input": "能不能帮个忙", "expected": ["clarify"], "difficulty": "medium"},
    {"input": "搞个好的", "expected": ["clarify"], "difficulty": "medium"},
    {"input": "这个怎么办", "expected": ["clarify"], "difficulty": "medium"},
    {"input": "优化一下", "expected": ["clarify", "reply"], "difficulty": "hard"},
    {"input": "改改", "expected": ["clarify", "build"], "difficulty": "hard"},

    # ═══ PLAN cases (8个) ═══
    {"input": "帮我做一个超级玛丽游戏", "expected": ["plan"], "difficulty": "easy"},
    {"input": "做一个完整的博客系统", "expected": ["plan"], "difficulty": "easy"},
    {"input": "帮我开发一个电商后台", "expected": ["plan"], "difficulty": "easy"},
    {"input": "做一个多人在线协作白板", "expected": ["plan"], "difficulty": "medium"},
    {"input": "帮我做一个项目管理工具", "expected": ["plan"], "difficulty": "medium"},
    {"input": "开发一个带AI功能的笔记应用", "expected": ["plan"], "difficulty": "medium"},
    {"input": "做一个类似抖音的短视频应用", "expected": ["plan"], "difficulty": "easy"},
    {"input": "帮我做一个在线考试系统", "expected": ["plan"], "difficulty": "medium"},
]


def sample_test_set(pool=None, n=30, seed=None):
    if pool is None:
        pool = ROUTE_TEST_POOL
    rng = random.Random(seed)
    sampled = rng.sample(pool, min(n, len(pool)))
    return sampled


async def run_route_test(test_set=None, seed=None):
    if test_set is None:
        test_set = sample_test_set(seed=seed)

    print("Route Accuracy Test ({} cases, seed={})".format(len(test_set), seed))
    print()

    correct = 0
    results = []

    for case in test_set:
        input_text = case["input"]
        expected = case["expected"]
        difficulty = case["difficulty"]
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
                            elif reply and ("?" in reply[:80] or "？" in reply[:80]) and len(reply) < 200:
                                got_action = "clarify"
                            else:
                                got_action = "reply"
                        elif d.get("content") == "idle":
                            break
                except asyncio.TimeoutError:
                    got_action = "timeout"
        except Exception:
            got_action = "error"

        match = got_action in expected
        if match:
            correct += 1
        tag = "PASS" if match else "FAIL"
        results.append({"input": input_text[:25], "expected": expected, "got": got_action, "match": match, "difficulty": difficulty})
        print("  {} {:5s} | exp={:20s} got={:7s} | {}".format(
            tag, difficulty, "/".join(expected), got_action, input_text[:30]))

    accuracy = correct / len(test_set) * 100
    print()
    print("Accuracy: {}/{} ({:.0f}%)".format(correct, len(test_set), accuracy))

    by_diff = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "correct": 0})
        by_diff[d]["total"] += 1
        if r["match"]:
            by_diff[d]["correct"] += 1
    print("By difficulty:")
    for d in ["easy", "medium", "hard"]:
        if d in by_diff:
            info = by_diff[d]
            print("  {}: {}/{} ({:.0f}%)".format(d, info["correct"], info["total"],
                info["correct"]/info["total"]*100))

    by_expected = {}
    for r in results:
        for e in r["expected"][:1]:
            by_expected.setdefault(e, {"total": 0, "correct": 0})
            by_expected[e]["total"] += 1
            if r["match"]:
                by_expected[e]["correct"] += 1
    print("By action type:")
    for a in ["reply", "build", "clarify", "plan"]:
        if a in by_expected:
            info = by_expected[a]
            print("  {}: {}/{} ({:.0f}%)".format(a, info["correct"], info["total"],
                info["correct"]/info["total"]*100))

    print()
    print("Target: >= 85%")
    print("Verdict: {}".format("PASS" if accuracy >= 85 else "NEEDS WORK"))
    return {"accuracy": accuracy, "results": results}


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    asyncio.run(run_route_test(seed=seed))
