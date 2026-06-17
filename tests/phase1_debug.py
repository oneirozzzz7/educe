import asyncio, json, websockets, uuid, sys, time
sys.path.insert(0, ".")

async def main():
    # Phase 1 路由问题分析
    # 路由验证失败了：番茄钟被判为text，量子计算被判为code
    # 原因：_decide的judge prompt现在带了conversation history
    # 但history里包含了前一轮的回答，模型可能被history干扰

    # 先单独测试judge prompt在无history时的表现
    from educe.core.config import EduceConfig
    from educe.models.router import ModelClient

    config = EduceConfig.load()
    client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)

    tests = [
        ("做一个番茄钟", True, "NEED_CODE"),
        ("什么是人工智能", False, "NO_CODE"),
        ("量子计算是什么", False, "NO_CODE"),
        ("帮我做一个计算器网页", True, "NEED_CODE"),
        ("红烧肉怎么做", False, "NO_CODE"),
        ("改成红色", True, "NEED_CODE"),  # 有代码上下文时
    ]

    judge_system = (
        "判断用户是否需要你编写代码/网页/工具/游戏/脚本。\n"
        "- 需要编程（做网页/工具/游戏/脚本，或修改之前生成的代码）-> 只回复：NEED_CODE\n"
        "- 不需要（聊天/提问/分析/翻译/写文章等）-> 只回复：NO_CODE\n"
    )

    print("Judge prompt 单独测试（无history）:")
    ok = 0
    for q, _, expected in tests:
        if q == "改成红色":
            system = judge_system + "\n注意：之前的对话中生成过代码。如果用户要求修改/调整/优化/加功能/改颜色等，回复NEED_CODE。"
        else:
            system = judge_system

        try:
            r = await client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": q},
                ],
                model=config.default_model.model,
                max_tokens=20,
                temperature=0.0,
            )
            got = "NEED_CODE" if "NEED_CODE" in r else "NO_CODE"
        except Exception as e:
            got = f"ERROR"

        correct = got == expected
        if correct:
            ok += 1
        print(f"  {'PASS' if correct else 'FAIL'}: {q:20s} expected={expected} got={got}")

    print(f"  准确率: {ok}/{len(tests)}")

asyncio.run(main())
