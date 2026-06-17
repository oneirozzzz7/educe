"""
测试builder在集成环境下的需求分析
验证 _analyze_requirements 在 handle() 中的行为
"""
import asyncio
import sys
sys.path.insert(0, ".")

from educe.core.config import EduceConfig
from educe.core.message import Message, MessageType, WorkContext
from educe.agents.builder import BuilderAgent


async def test_builder_analysis():
    config = EduceConfig.load()

    from educe.models.router import ModelClient
    model_config = config.get_model_config("builder")
    client = ModelClient(api_key=model_config.api_key, base_url=model_config.base_url)

    builder = BuilderAgent(config=config, model_client=client)

    test_cases = [
        ("做一个计算器", "DIRECT"),
        ("做一个番茄钟", "DIRECT"),
        ("做一个坦克大战游戏", "DECISION"),
        ("做一个简单的待办清单", "DIRECT"),
        ("做一个博客系统", "DECISION"),
        ("帮我做一个超级玛丽游戏", "DECISION"),
    ]

    results = []
    for req, expected in test_cases:
        context = WorkContext(user_request=req)
        msg = Message(
            type=MessageType.USER_INPUT,
            sender="user",
            receiver="builder",
            content=req
        )

        got_decision = False
        got_output = False

        # 只运行到第一个yield就够了
        try:
            async for out_msg in builder.handle(msg, context):
                content = out_msg.content if hasattr(out_msg, 'content') else str(out_msg)
                if "__DECISION_REQUEST__" in content:
                    got_decision = True
                    break
                elif "__BUILD_PROGRESS__" in content or "__PIPELINE" in content:
                    got_output = True
                    break
                else:
                    # 模型开始生成代码了 — 直接构建
                    got_output = True
                    break
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append(("ERROR", expected))
            continue

        actual = "DECISION" if got_decision else "DIRECT"
        status = "✅" if actual == expected else "❌"
        results.append((actual, expected))
        print(f"  {status} {req} -> {actual} (expected {expected})")

    passed = sum(1 for a, e in results if a == e)
    print(f"\n结果: {passed}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(test_builder_analysis())
