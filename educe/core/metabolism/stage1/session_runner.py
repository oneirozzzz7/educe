"""
模拟用户 Session Runner — 让弱模型真实踩坑，积累因果数据

设计原则（Opus 4.8 建议）：
- 任务骨架固定（保证科学性）
- 自然语言表达由弱模型随机（保证多样性）
- 每个 pitfall 跑多次，不同 persona
- 记录完整的 (context, action, outcome) 三元组
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import yaml
import aiohttp
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from educe.core.metabolism.ledger import LedgerStore, ConsequenceRecord, OutcomeType
from educe.core.metabolism.reward import immediate_reward

log = logging.getLogger("educe.stage1")

import os

BASE_URL = os.environ.get("DEEPFORGE_BASE_URL", "")
API_KEY = os.environ.get("DEEPFORGE_API_KEY", "")

SYSTEM_PROMPT_BASE = """你是 Educe，一个运行在框架中的智能助手。你的文字回复展示给用户，只有 <action> 标签才会被执行。

## 决策流程
第零步：纯知识问答 → 直接回答
第一步：了解项目/文件 → <action type="read_dir">路径</action> 或 <action type="read_file">文件</action>
第二步：一步做完 → <action type="shell">命令</action>；多步 → <action type="build">需求</action>

安全级别：read_dir/read_file 直接执行；shell/build 需确认。
"""


@dataclass
class Persona:
    name: str
    instruction_style: str  # 如何把 intent 变成自然语言


PERSONAS = [
    Persona("新手", "用最简短、含糊的话说，不给具体路径或命令"),
    Persona("直接型", "明确说想做什么，但不关心具体实现细节"),
    Persona("探索型", "先问项目情况，再决定要做什么"),
    Persona("急性子", "直接给出想要的最终结果，跳过中间步骤"),
    Persona("谨慎型", "先确认当前状态，再一步步操作"),
]


async def call_model(session: aiohttp.ClientSession, system: str, user_msg: str) -> Optional[str]:
    """调用弱模型"""
    payload = {
        "model": "qwen36",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 300,
        "temperature": 0.5,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


async def generate_user_instruction(session: aiohttp.ClientSession, persona: Persona, intent: str) -> str:
    """用弱模型把 intent 改写成符合 persona 风格的自然语言"""
    prompt = f"""请把以下意图改写成一句用户指令，风格要求：{persona.instruction_style}
意图：{intent}
只输出改写后的一句话，不要解释："""

    result = await call_model(session, "你是一个指令改写助手，只输出改写结果。", prompt)
    if result:
        return result.strip().strip('"').strip("'")
    return intent  # 降级为原始 intent


async def run_single_session(
    session: aiohttp.ClientSession,
    ledger: LedgerStore,
    pitfall: dict,
    persona: Persona,
    trial_id: int,
) -> dict:
    """运行一个模拟用户 session，返回统计"""
    session_id = f"sim-{pitfall['id']}-{persona.name}-{trial_id}"
    stats = {"session_id": session_id, "actions": 0, "successes": 0, "failures": 0, "hit_pitfall": False}

    # 生成自然语言指令（围绕 pitfall trigger）
    user_instruction = await generate_user_instruction(session, persona, pitfall["trigger"])

    # 模型响应
    response = await call_model(session, SYSTEM_PROMPT_BASE, user_instruction)
    if not response:
        return stats

    # 提取 action
    import re
    action_match = re.search(r'<action\s+([^>]*?)(?:/>|>([\s\S]*?)</action>)', response, re.IGNORECASE)

    if not action_match:
        # 模型没产出 action — 记录为 no_action
        record = ConsequenceRecord(
            record_id=str(uuid.uuid4())[:12],
            session_id=session_id,
            seed_id="default",
            round_idx=0,
            decision_point="no_action",
            context_snapshot={"user_input": user_instruction[:150], "pitfall_id": pitfall["id"]},
            action_taken={"capability": "none", "params": ""},
            outcome_type=OutcomeType.FAILURE,
            outcome_detail={"reason": "model_did_not_act", "response_preview": response[:100]},
            immediate_reward=-0.3,
        )
        await ledger.append(record)
        stats["actions"] += 1
        stats["failures"] += 1
        return stats

    # 解析 action
    attrs_str = action_match.group(1)
    body = (action_match.group(2) or "").strip()
    attr_pattern = re.compile(r'(\w+)\s*=\s*["\']?([^"\'\s>]+)["\']?')
    attrs = dict(attr_pattern.findall(attrs_str))
    action_type = attrs.get("type", "")

    # 判断是否踩了坑
    naive_action = pitfall.get("naive_action", "").lower()
    correct_action = pitfall.get("correct_action", "").lower()

    # 简单判定：模型的 action 是否接近 naive（踩坑）还是 correct（避坑）
    action_text = f"{action_type} {body}".lower()
    hit_naive = any(kw in action_text for kw in naive_action.split()[:3] if len(kw) > 2)
    hit_correct = any(kw in action_text for kw in correct_action.split()[:3] if len(kw) > 2)

    if hit_correct and not hit_naive:
        outcome_type = OutcomeType.SUCCESS
        stats["successes"] += 1
    else:
        outcome_type = OutcomeType.FAILURE
        stats["failures"] += 1
        if hit_naive:
            stats["hit_pitfall"] = True

    reward = immediate_reward(outcome_type, {"latency": 0.3})

    record = ConsequenceRecord(
        record_id=str(uuid.uuid4())[:12],
        session_id=session_id,
        seed_id="default",
        round_idx=0,
        decision_point=action_type,
        context_snapshot={
            "user_input": user_instruction[:150],
            "pitfall_id": pitfall["id"],
            "pitfall_trigger": pitfall["trigger"],
            "persona": persona.name,
        },
        action_taken={"capability": action_type, "params": body[:200]},
        outcome_type=outcome_type,
        outcome_detail={
            "hit_naive": hit_naive,
            "hit_correct": hit_correct,
            "response_preview": response[:150],
            "naive_action": pitfall["naive_action"][:80],
            "correct_action": pitfall["correct_action"][:80],
        },
        immediate_reward=reward,
    )
    await ledger.append(record)
    stats["actions"] += 1

    return stats


async def run_accumulation(pitfalls_path: Path, output_dir: Path, trials_per_persona: int = 3):
    """主流程：积累因果数据"""
    # 加载 pitfalls
    with open(pitfalls_path, "r") as f:
        data = yaml.safe_load(f)
    pitfalls = data["pitfalls"]

    ledger = LedgerStore(output_dir)
    connector = aiohttp.TCPConnector(limit=5)

    total_sessions = len(pitfalls) * len(PERSONAS) * trials_per_persona
    print(f"{'='*60}")
    print(f"  模拟用户积累实验")
    print(f"  {len(pitfalls)} pitfalls × {len(PERSONAS)} personas × {trials_per_persona} trials = {total_sessions} sessions")
    print(f"{'='*60}")

    all_stats = []
    completed = 0

    async with aiohttp.ClientSession(connector=connector) as http_session:
        for pitfall in pitfalls:
            pitfall_stats = {"id": pitfall["id"], "sessions": 0, "hit_pitfall": 0, "avoided": 0}

            for persona in PERSONAS:
                for trial in range(trials_per_persona):
                    stats = await run_single_session(http_session, ledger, pitfall, persona, trial)
                    all_stats.append(stats)
                    pitfall_stats["sessions"] += 1
                    if stats["hit_pitfall"]:
                        pitfall_stats["hit_pitfall"] += 1
                    elif stats["successes"] > 0:
                        pitfall_stats["avoided"] += 1
                    completed += 1
                    await asyncio.sleep(0.3)

            hit_rate = pitfall_stats["hit_pitfall"] / pitfall_stats["sessions"] * 100
            avoid_rate = pitfall_stats["avoided"] / pitfall_stats["sessions"] * 100
            print(f"  [{pitfall['id']}] {pitfall['trigger'][:30]:30} | 踩坑率={hit_rate:.0f}% 避坑率={avoid_rate:.0f}%")

    # 汇总
    total_records = await ledger.count()
    total_hits = sum(1 for s in all_stats if s["hit_pitfall"])
    total_avoids = sum(1 for s in all_stats if s["successes"] > 0)

    print(f"\n{'='*60}")
    print(f"  汇总")
    print(f"{'='*60}")
    print(f"  总 sessions: {completed}")
    print(f"  账本记录数: {total_records}")
    print(f"  踩坑 sessions: {total_hits} ({total_hits/completed*100:.0f}%)")
    print(f"  避坑 sessions: {total_avoids} ({total_avoids/completed*100:.0f}%)")
    print(f"  数据存储: {output_dir}")


if __name__ == "__main__":
    pitfalls_file = Path("educe/core/metabolism/stage1") / "pitfalls.yaml"
    asyncio.run(run_accumulation(
        pitfalls_path=pitfalls_file,
        output_dir=Path(".educe/metabolism_stage1"),
        trials_per_persona=3,
    ))
