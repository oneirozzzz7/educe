"""
Demo: BehaviorLearner 端到端闭环演示

用真实弱模型(Qwen3.6-35B-A3B)跑完整流程：
  Round 1: Agent 犯错（不知道项目约定）
  Round 2: 用户纠正 → 学到规则（staged）
  Round 3: 模拟多次命中+成功 → 晋升 active
  Round 4: 同类问题再来 → 规则注入 prompt → 模型直接做对

让人肉眼看到"犯错 → 学到 → 下次做对"的完整闭环。
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from deepforge.core.behavior import BehaviorManifest, BehaviorUnit, UnitStatus
from deepforge.core.behavior_learner import BehaviorLearner
from deepforge.models.router import ModelClient

# 从环境变量或 deepforge 配置读取
API_KEY = os.environ.get("EDUCE_MODEL_KEY", "")
BASE_URL = os.environ.get("EDUCE_MODEL_URL", "")
MODEL = os.environ.get("EDUCE_MODEL_NAME", "qwen36")

if not API_KEY or not BASE_URL:
    # fallback: 尝试从 .deepforge 配置读取
    try:
        cfg_path = Path(".deepforge/config.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            API_KEY = cfg.get("default_model", {}).get("api_key", "")
            BASE_URL = cfg.get("default_model", {}).get("base_url", "")
            MODEL = cfg.get("default_model", {}).get("model", MODEL)
    except Exception:
        pass

if not API_KEY or not BASE_URL:
    print("请设置环境变量 EDUCE_MODEL_KEY 和 EDUCE_MODEL_URL，或配置 .deepforge/config.json")
    exit(1)

BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(text: str):
    print(f"\n{'═'*60}")
    print(f"{BOLD}{text}{RESET}")
    print(f"{'═'*60}")


def user_says(text: str):
    print(f"\n{BLUE}👤 用户: {text}{RESET}")


def agent_says(text: str):
    lines = text.strip().split('\n')
    preview = '\n'.join(lines[:8])
    if len(lines) > 8:
        preview += f"\n{DIM}... ({len(lines)-8} more lines){RESET}"
    print(f"{GREEN}🤖 Agent: {preview}{RESET}")


def system_log(text: str):
    print(f"{DIM}   ⚙ {text}{RESET}")


async def main():
    client = ModelClient(api_key=API_KEY, base_url=BASE_URL)
    tmp = Path(tempfile.mkdtemp()) / "manifest.json"
    manifest = BehaviorManifest(agent_id="demo", base_seed="你是一个编程助手。")
    learner = BehaviorLearner(manifest=manifest, persist_path=tmp)

    # ═══════════════════════════════════════════════════════════
    header("Round 1: Agent 犯错（不知道项目规范）")
    # ═══════════════════════════════════════════════════════════

    question1 = "帮我写一个 JavaScript 函数，把数组去重"

    system_prompt_r1 = manifest.render_for_prompt(question1)
    system_log(f"System prompt 行为规则部分: {repr(system_prompt_r1[:100]) if system_prompt_r1 else '(空，无规则)'}")

    response1 = await client.chat(
        messages=[
            {"role": "system", "content": system_prompt_r1 or "你是一个编程助手。"},
            {"role": "user", "content": question1},
        ],
        model=MODEL, max_tokens=500, temperature=0.3,
    )

    user_says(question1)
    agent_says(response1)

    # 检查是否用了 var（弱模型大概率会用）
    used_var = "var " in response1
    used_arrow = "=>" in response1
    system_log(f"用了 var: {used_var} | 用了箭头函数: {used_arrow}")

    # ═══════════════════════════════════════════════════════════
    header("Round 2: 用户纠正 → BehaviorLearner 提取规则")
    # ═══════════════════════════════════════════════════════════

    correction = "不要用 var 和 function 关键字，我们项目统一用 const/let + 箭头函数，这是团队规范"
    user_says(correction)

    unit = await learner.learn_from_correction(
        prev_response=response1,
        user_correction=correction,
        client=client,
        model=MODEL,
    )

    if unit:
        print(f"\n{YELLOW}📝 学到新规则 (staged):{RESET}")
        print(f"   Trigger:   {unit.trigger}")
        print(f"   Directive: {unit.directive}")
        print(f"   Weight:    {unit.weight:.3f}")
        print(f"   Status:    {unit.status.value}")
    else:
        print(f"{RED}❌ 未能从纠正中提取规则{RESET}")
        return

    # ═══════════════════════════════════════════════════════════
    header("Round 3: 模拟验证 → 晋升为 active")
    # ═══════════════════════════════════════════════════════════

    system_log("模拟3次命中+成功（实际产品中由用户交互自然产生）...")
    for i in range(4):
        learner.reinforce(unit.id)
        system_log(f"  reinforce #{i+1}: weight={unit.weight:.3f}, status={unit.status.value}")

    assert unit.status == UnitStatus.ACTIVE, f"Expected ACTIVE, got {unit.status.value}"
    print(f"\n{GREEN}✅ 规则已晋升为 ACTIVE!{RESET}")
    print(f"   Stats: hits={unit.hit_count}, success_rate={unit.success_rate:.0%}, weight={unit.weight:.3f}")

    # ═══════════════════════════════════════════════════════════
    header("Round 4: 同类问题再来 → 规则注入 → 模型直接做对")
    # ═══════════════════════════════════════════════════════════

    question2 = "帮我写一个 JavaScript 函数，合并两个对象（深合并）"
    user_says(question2)

    # 渲染带规则的 prompt
    system_prompt_r4 = manifest.render_for_prompt(question2)
    print(f"\n{YELLOW}📋 注入的 system prompt:{RESET}")
    for line in system_prompt_r4.split('\n'):
        print(f"   {line}")

    response2 = await client.chat(
        messages=[
            {"role": "system", "content": system_prompt_r4},
            {"role": "user", "content": question2},
        ],
        model=MODEL, max_tokens=500, temperature=0.3,
    )

    agent_says(response2)

    # 验证改善
    used_var_r4 = "var " in response2
    used_const_r4 = "const " in response2 or "let " in response2
    used_arrow_r4 = "=>" in response2

    # ═══════════════════════════════════════════════════════════
    header("对比总结")
    # ═══════════════════════════════════════════════════════════

    print(f"""
┌─────────────────┬──────────────────┬──────────────────┐
│                 │ Round 1 (无规则) │ Round 4 (有规则) │
├─────────────────┼──────────────────┼──────────────────┤
│ 用了 var        │ {'✗ Yes' if used_var else '✓ No':^16} │ {'✗ Yes' if used_var_r4 else '✓ No':^16} │
│ 用了 const/let  │ {'✓ Yes' if ('const' in response1 or 'let' in response1) else '✗ No':^16} │ {'✓ Yes' if used_const_r4 else '✗ No':^16} │
│ 用了箭头函数    │ {'✓ Yes' if used_arrow else '✗ No':^16} │ {'✓ Yes' if used_arrow_r4 else '✗ No':^16} │
└─────────────────┴──────────────────┴──────────────────┘
""")

    # 判断改善
    improved = (not used_var_r4 and used_const_r4) or (used_arrow_r4 and not used_arrow)
    if improved:
        print(f"{GREEN}{BOLD}🎉 行为改善确认！Agent 从纠正中学到了规则并在新任务中应用。{RESET}")
    elif not used_var_r4:
        print(f"{GREEN}✓ Round 4 没用 var（可能模型本身就避免了，也可能规则生效）{RESET}")
    else:
        print(f"{YELLOW}⚠ Round 4 仍然用了 var — 规则注入未完全生效（弱模型可能忽略了 system prompt 指令）{RESET}")

    # ═══════════════════════════════════════════════════════════
    header("Manifest 最终状态")
    # ═══════════════════════════════════════════════════════════

    print(f"  {manifest.stats()}")
    print(f"  Commits: {len(manifest.commits)}")
    for c in manifest.commits[-3:]:
        print(f"    [{c.commit_id}] {c.message}")

    # 持久化验证
    learner._persist()
    loaded = BehaviorManifest.load(tmp)
    print(f"\n  持久化验证: loaded {loaded.stats()['total_units']} units, {loaded.stats()['active']} active ✓")


if __name__ == "__main__":
    asyncio.run(main())
