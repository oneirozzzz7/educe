"""
非显然规则发现实验（Implicit Preference Discovery）

核心问题：BehaviorLearner 能否发现用户没显式说出来的环境偏好？

实验设计：
- 模拟一个有"隐性偏好"的用户（通过 pattern 体现而非直接纠正）
- 用户反复对某类回答表示不满（penalize）/ 满意（reinforce）
- 但从不直接说"请这样做"
- 观察：系统能否从 reinforce/penalize 的模式中归纳出规则？

这验证的是 Phase 1 代谢的核心假设：
后果信号（满意/不满意）→ 自动提取行为规则 → 无需显式纠正

如果成功：护城河是"连续适应中自动发现的隐性偏好"
如果失败：需要用户显式纠正 → 价值降级为"高效记忆系统"
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.behavior import BehaviorManifest, BehaviorUnit, UnitStatus
from educe.core.behavior_learner import BehaviorLearner
from educe.models.router import ModelClient

API_KEY = os.environ.get("EDUCE_MODEL_KEY", "")
BASE_URL = os.environ.get("EDUCE_MODEL_URL", "")
MODEL = os.environ.get("EDUCE_MODEL_NAME", "qwen36")

if not API_KEY or not BASE_URL:
    try:
        cfg = json.loads(Path(".educe/config.json").read_text())
        API_KEY = cfg.get("default_model", {}).get("api_key", "")
        BASE_URL = cfg.get("default_model", {}).get("base_url", "")
        MODEL = cfg.get("default_model", {}).get("model", MODEL)
    except Exception:
        pass


IMPLICIT_PREFERENCE_PROMPT = """\
你是一个隐性偏好分析器。

以下是用户对 AI 回答的满意/不满意记录：
{history}

请分析用户的隐性偏好模式——他们满意什么样的回答，不满意什么样的？
提取一条最核心的行为规则（用户可能自己都没意识到的偏好）。

输出JSON：
{{
  "trigger": "什么情况下应该应用这条规则",
  "directive": "应该怎么做",
  "confidence": 0.0-1.0,
  "reasoning": "为什么你认为这是用户的隐性偏好"
}}

只输出JSON"""


async def run_experiment():
    if not API_KEY or not BASE_URL:
        print("Set EDUCE_MODEL_KEY and EDUCE_MODEL_URL")
        return

    client = ModelClient(api_key=API_KEY, base_url=BASE_URL)

    print("═" * 60)
    print("非显然规则发现实验（Implicit Preference Discovery）")
    print("═" * 60)

    # ═══════════════════════════════════════════════════════════
    # 场景 1：用户偏好"先给结论再解释"（从不直接说出来）
    # ═══════════════════════════════════════════════════════════

    print("\n场景 1: 隐性偏好 = '先给结论再解释'")
    print("─" * 50)

    questions = [
        "什么是微服务？", "React 和 Vue 哪个好？", "要不要用 TypeScript？",
        "什么时候用 Redis？", "单元测试有必要吗？", "GraphQL 比 REST 好吗？",
        "要不要上 Docker？", "什么是 DDD？",
    ]

    # 模拟：用户对"先给结论"的回答满意，对"先讲背景"的不满意
    history_entries = []
    for i, q in enumerate(questions):
        resp = await client.chat(
            messages=[{"role": "system", "content": "你是编程助手。"},
                      {"role": "user", "content": q}],
            model=MODEL, max_tokens=400, temperature=0.5,
        )

        # 判断回答是否"先给结论"
        first_line = resp.strip().split('\n')[0]
        starts_with_conclusion = (
            len(first_line) < 60
            and not first_line.startswith('#')
            and not first_line.startswith('*')
            and ('是' in first_line or '不' in first_line or '可以' in first_line or '建议' in first_line)
        )

        # 模拟用户信号
        if starts_with_conclusion:
            signal = "satisfied"
            history_entries.append(f"✓ 满意 | 问: {q} | 回答开头: {first_line[:50]}")
        else:
            signal = "unsatisfied"
            history_entries.append(f"✗ 不满 | 问: {q} | 回答开头: {first_line[:50]}")

        print(f"  [{signal:>12}] {q} → '{first_line[:40]}...'")

    # 用 LLM 从满意/不满意模式中提取隐性偏好
    print(f"\n  分析 {len(history_entries)} 条反馈记录...")
    history_text = "\n".join(history_entries)

    raw = await client.chat(
        messages=[{"role": "user", "content": IMPLICIT_PREFERENCE_PROMPT.format(history=history_text)}],
        model=MODEL, max_tokens=300, temperature=0.0,
    )

    try:
        parsed = json.loads(raw.strip().strip("```json").strip("```"))
    except Exception:
        parsed = {"trigger": "", "directive": "", "confidence": 0, "reasoning": raw[:200]}

    print(f"\n  🔍 发现的隐性偏好:")
    print(f"     Trigger: {parsed.get('trigger', 'N/A')}")
    print(f"     Directive: {parsed.get('directive', 'N/A')}")
    print(f"     Confidence: {parsed.get('confidence', 'N/A')}")
    print(f"     Reasoning: {parsed.get('reasoning', 'N/A')[:100]}")

    # 验证：用发现的规则跑同类问题，看是否改善
    discovered_rule = parsed.get("directive", "")
    if discovered_rule:
        print(f"\n  验证：用发现的规则跑新问题...")
        test_q = "Kubernetes 有必要学吗？"

        # 无规则
        r_without = await client.chat(
            messages=[{"role": "system", "content": "你是编程助手。"},
                      {"role": "user", "content": test_q}],
            model=MODEL, max_tokens=300, temperature=0.3,
        )
        # 有规则
        r_with = await client.chat(
            messages=[{"role": "system", "content": f"你是编程助手。\n\n## 经验教训（供参考）\n- {discovered_rule}"},
                      {"role": "user", "content": test_q}],
            model=MODEL, max_tokens=300, temperature=0.3,
        )

        print(f"     无规则第一行: '{r_without.strip().split(chr(10))[0][:60]}'")
        print(f"     有规则第一行: '{r_with.strip().split(chr(10))[0][:60]}'")

    # ═══════════════════════════════════════════════════════════
    # 场景 2：用户偏好"不要用比喻，直接给技术定义"
    # ═══════════════════════════════════════════════════════════

    print("\n\n场景 2: 隐性偏好 = '不要比喻，直接技术定义'")
    print("─" * 50)

    tech_questions = [
        "什么是闭包？", "什么是协程？", "什么是事务隔离？", "什么是 CAP 定理？",
        "什么是一致性哈希？", "什么是 B+ 树？", "什么是 Raft 算法？", "什么是 WebSocket？",
    ]

    history_entries_2 = []
    for q in tech_questions:
        resp = await client.chat(
            messages=[{"role": "system", "content": "你是编程助手。"},
                      {"role": "user", "content": q}],
            model=MODEL, max_tokens=400, temperature=0.5,
        )

        has_analogy = any(w in resp[:200] for w in ["像", "好比", "就像", "想象", "如同", "比喻"])

        if has_analogy:
            signal = "unsatisfied"
            history_entries_2.append(f"✗ 不满 | 问: {q} | 包含比喻: 是")
        else:
            signal = "satisfied"
            history_entries_2.append(f"✓ 满意 | 问: {q} | 包含比喻: 否")

        print(f"  [{signal:>12}] {q} → 有比喻: {has_analogy}")

    # 提取
    history_text_2 = "\n".join(history_entries_2)
    raw2 = await client.chat(
        messages=[{"role": "user", "content": IMPLICIT_PREFERENCE_PROMPT.format(history=history_text_2)}],
        model=MODEL, max_tokens=300, temperature=0.0,
    )

    try:
        parsed2 = json.loads(raw2.strip().strip("```json").strip("```"))
    except Exception:
        parsed2 = {"trigger": "", "directive": "", "confidence": 0, "reasoning": raw2[:200]}

    print(f"\n  🔍 发现的隐性偏好:")
    print(f"     Trigger: {parsed2.get('trigger', 'N/A')}")
    print(f"     Directive: {parsed2.get('directive', 'N/A')}")
    print(f"     Confidence: {parsed2.get('confidence', 'N/A')}")
    print(f"     Reasoning: {parsed2.get('reasoning', 'N/A')[:100]}")

    # ═══════════════════════════════════════════════════════════
    # 总结
    # ═══════════════════════════════════════════════════════════
    print("\n" + "═" * 60)
    print("实验总结")
    print("═" * 60)
    print(f"""
场景1 (先结论后解释):
  发现: {parsed.get('directive', 'N/A')[:60]}
  置信度: {parsed.get('confidence', '?')}

场景2 (不要比喻):
  发现: {parsed2.get('directive', 'N/A')[:60]}
  置信度: {parsed2.get('confidence', '?')}

关键问题：发现的规则是否真正反映了我们设定的隐性偏好？
- 场景1 预期发现: "先给结论/判断，再展开解释"
- 场景2 预期发现: "不要用比喻，直接给技术定义"
""")


if __name__ == "__main__":
    asyncio.run(run_experiment())
