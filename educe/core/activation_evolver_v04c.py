"""
激发引擎 v0.4c — 多步推理演化（有空间的正确领域）

关键条件满足：
- Baseline 60-80%（有演化空间）
- 可验证评分（答案唯一，字符串比对）
- 20 题训练 + 5 题 hold-out
- 定向变异 vs 随机变异对照
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp

BASE_URL = os.environ.get("EDUCE_BASE_URL", "")
API_KEY = os.environ.get("EDUCE_API_KEY", "")


# ═══ 多步推理题库（模型 baseline ~70-80%）═══

TRAIN_QUESTIONS = [
    # 约束满足
    {"q": "一个密码由4位数字组成。第一位是第四位的2倍，第二位比第三位大3，四位数字之和为14，第三位是1。密码是多少？", "a": "4412"},
    {"q": "甲乙丙丁四人年龄不同。甲比乙大，丙比丁小，乙比丁大，谁最大谁最小？格式：最大X最小Y", "a": "最大甲最小丙"},
    {"q": "有红黄蓝三个球和三个同色的盒子。红球不在红盒，黄球不在蓝盒。每个球恰好在一个不同色的盒子里。红球在哪个盒子？", "a": "蓝"},
    {"q": "A+B=8, B+C=11, A+C=9。求A、B、C各是多少？格式：A=X,B=X,C=X", "a": "A=3,B=5,C=6"},
    {"q": "5个人排队，已知：张在李前面，王在赵后面，李在王前面，刘在最后。张排第几？", "a": "1"},
    # 递推/计算
    {"q": "有5个盒子编号1-5。规则：每个盒子的球数等于前两个盒子之和。1号有1个，2号有1个。5号有几个？", "a": "8"},
    {"q": "一根100cm的绳子，第一次剪掉一半，第二次剪掉剩下的三分之一，第三次剪掉剩下的四分之一。最终剩多少cm？", "a": "25"},
    {"q": "小明存了100元，每月底存入上月余额的10%作为利息。3个月后他有多少元？（四舍五入到整数）", "a": "133"},
    {"q": "一个细菌每小时分裂一次（变成2个）。如果一开始有1个细菌，瓶子12小时装满。如果一开始放2个细菌，几小时装满？", "a": "11"},
    {"q": "甲做一件工作需6天，乙需9天。甲先做2天后乙加入，两人再合做几天完成？", "a": "2.4"},
    # 逻辑推理
    {"q": "A说'我们中恰好有一个人说真话'。B说'我们中恰好有两个人说真话'。C说'我们中没有人说真话'。谁说真话？", "a": "A"},
    {"q": "甲说乙及格了，乙说丙及格了，丙说自己没及格。三人中只有一人说谎。谁说谎？", "a": "乙"},
    {"q": "桌上有3张牌：A在B左边，B在C左边。翻开A是红桃，翻开C是黑桃。不看B，B一定是红色还是黑色还是不确定？", "a": "不确定"},
    {"q": "一个岛上有100个人，其中蓝眼37人红眼63人。他们不知道自己眼睛颜色。如果一个外来人说'岛上有蓝眼睛的人'，第几天蓝眼人会离开？", "a": "37"},
    # 应用题
    {"q": "甲乙两车从AB两城相向而行，甲速60km/h，乙速40km/h。AB相距200km。几小时后两车相距100km？（第一次）", "a": "1"},
    {"q": "一个商品先涨价20%再打8折，最终价格相比原价是涨了还是降了？涨/降多少百分比？格式：降X%", "a": "降4%"},
    {"q": "10个人站一排，甲乙必须相邻，丙丁必须不相邻。有多少种排法？（只给数字）", "a": "564480"},
    {"q": "一水池有A、B两管。A管注水：第1小时1吨，第2小时2吨，第3小时3吨...B管每小时放水0.5吨。池容量10吨。几小时注满？", "a": "4"},
    {"q": "一列火车过一座桥用30秒，过一个站台用25秒。桥长500米，站台长300米。火车长度和速度各是多少？格式：长Xm速Xm/s", "a": "长100m速20m/s"},
    {"q": "扑克牌中随机抽2张，至少有1张红色（红桃/方块）的概率是多少？（用分数表示）", "a": "15/17"},
]

HOLDOUT_QUESTIONS = [
    {"q": "ABC三个数，A+B+C=100，A是B的2倍，C比A多10。求A、B、C。格式：A=X,B=X,C=X", "a": "A=36,B=18,C=46"},
    {"q": "一个钟在12小时内时针和分针重合几次？", "a": "11"},
    {"q": "一筐鸡蛋，2个2个拿余1，3个3个拿余2，5个5个拿余4。最少有几个？", "a": "29"},
    {"q": "甲乙丙三人分别是医生、教师、律师（不一定对应）。甲说：我不是医生。乙说：我是教师。只有一人说了假话。甲是什么职业？", "a": "律师"},
    {"q": "一个正方形边长10cm，在每个角切掉边长2cm的小正方形后折成无盖盒子，体积是多少cm³？", "a": "72"},
]


# ═══ Seed ═══

@dataclass
class Seed:
    id: str
    text: str
    generation: int = 0
    fitness: float = 0.0
    parent_id: Optional[str] = None

BASELINE_SEED = Seed(
    id="baseline",
    text="请仔细分析每个条件，一步步推理。注意陷阱和边界情况。最后给出明确答案。",
)


# ═══ 模型调用 ═══

async def call_model(session: aiohttp.ClientSession, system: str, user_msg: str) -> str:
    payload = {
        "model": "qwen36",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        "max_tokens": 800, "temperature": 0.3,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        async with session.post(f"{BASE_URL}/chat/completions", json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200: return ""
            data = await resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception:
        return ""


# ═══ 评分 ═══

def check_answer(response: str, correct: str) -> bool:
    """检查模型回复中是否包含正确答案"""
    if not response:
        return False
    # 标准化比较
    resp_clean = response.replace(" ", "").replace("，", ",").replace("：", ":")
    ans_clean = correct.replace(" ", "")
    if ans_clean in resp_clean:
        return True
    # 对数字答案，提取最后出现的数字
    if re.match(r'^[\d.]+$', correct):
        numbers = re.findall(r'[\d.]+', response)
        if numbers and numbers[-1] == correct:
            return True
    return False


# ═══ 评估 ═══

async def evaluate_seed(session, seed: Seed, questions: list) -> tuple[float, list]:
    system = f"你是一个擅长逻辑推理和数学计算的助手。\n\n## 思维引导\n{seed.text}\n\n请一步步推理，最后在独立一行给出最终答案。"
    results = []
    for q in questions:
        resp = await call_model(session, system, q["q"])
        correct = check_answer(resp, q["a"])
        results.append({"q": q["q"][:40], "a": q["a"], "correct": correct, "resp": resp[:100]})
        await asyncio.sleep(0.3)
    rate = sum(1 for r in results if r["correct"]) / len(results) if results else 0
    return rate, results


# ═══ 变异 ═══

async def mutate_directed(session, parent: Seed, failed_qs: list, n: int = 3) -> list[Seed]:
    failed_desc = "\n".join(f"- {q['q'][:60]}（答案应是{q['a']}）" for q in failed_qs[:4])
    mutants = []
    for i in range(n):
        style = ["增加验算步骤", "强调逐步代入检验", "换一个思维角度"][i % 3]
        prompt = f"""当前引导语："{parent.text}"
模型在这些题上答错了：
{failed_desc}

请改写引导语，策略：{style}。1-3句话，只输出改写结果："""
        resp = await call_model(session, "你是 prompt 优化专家。", prompt)
        if resp:
            mutants.append(Seed(id=f"g{parent.generation+1}-d{i}", text=resp.strip().strip('"')[:200],
                                generation=parent.generation+1, parent_id=parent.id))
        await asyncio.sleep(0.3)
    return mutants


async def mutate_random(session, parent: Seed, n: int = 2) -> list[Seed]:
    mutants = []
    for i in range(n):
        prompt = f"""当前引导语："{parent.text}"
请随机改写成完全不同风格的推理引导语。1-3句话，只输出结果："""
        resp = await call_model(session, "你是改写助手。", prompt)
        if resp:
            mutants.append(Seed(id=f"g{parent.generation+1}-r{i}", text=resp.strip().strip('"')[:200],
                                generation=parent.generation+1, parent_id=parent.id))
        await asyncio.sleep(0.3)
    return mutants


# ═══ 主循环 ═══

async def run_evolution(max_gen: int = 5):
    if not BASE_URL or not API_KEY:
        print("ERROR: Set EDUCE_BASE_URL and EDUCE_API_KEY env vars")
        return

    print("=" * 60)
    print("  激发引擎 v0.4c — 多步推理演化")
    print(f"  训练: {len(TRAIN_QUESTIONS)} | Hold-out: {len(HOLDOUT_QUESTIONS)}")
    print(f"  变异: 3定向 + 2随机/代 | 最大: {max_gen}代")
    print("=" * 60)

    connector = aiohttp.TCPConnector(limit=5)
    best = BASELINE_SEED
    history = []
    no_improve = 0

    async with aiohttp.ClientSession(connector=connector) as session:
        # Gen 0
        print(f"\n[Gen 0] 评估 baseline...")
        best.fitness, details = await evaluate_seed(session, best, TRAIN_QUESTIONS)
        failed = [TRAIN_QUESTIONS[i] for i, d in enumerate(details) if not d["correct"]]
        passed_list = [d["q"] for d in details if d["correct"]]
        print(f"  Pass rate: {best.fitness:.0%} ({int(best.fitness*len(TRAIN_QUESTIONS))}/{len(TRAIN_QUESTIONS)})")
        print(f"  Failed ({len(failed)}):")
        for d in details:
            if not d["correct"]:
                print(f"    ✗ {d['q']} (expected: {d['a']})")
        history.append({"gen": 0, "best": best.id, "fitness": best.fitness, "seed": best.text[:60]})

        # Evolution loop
        for gen in range(1, max_gen + 1):
            if not failed:
                print(f"\n[Gen {gen}] 全部通过！")
                break
            if no_improve >= 3:
                print(f"\n[Gen {gen}] 连续3代无改善，收敛。")
                break

            print(f"\n[Gen {gen}] 变异 (failed={len(failed)})...")
            directed = await mutate_directed(session, best, failed, n=3)
            random_muts = await mutate_random(session, best, n=2)
            candidates = directed + random_muts

            best_candidate = best
            best_source = ""
            for mut in candidates:
                mut.fitness, _ = await evaluate_seed(session, mut, TRAIN_QUESTIONS)
                src = "定向" if mut in directed else "随机"
                marker = "★" if mut.fitness > best.fitness else " "
                print(f"  {marker} {mut.id} ({src}): {mut.fitness:.0%} | {mut.text[:50]}...")
                if mut.fitness > best_candidate.fitness:
                    best_candidate = mut
                    best_source = src

            if best_candidate.fitness > best.fitness:
                print(f"\n  ✓ 替换! [{best_source}] {best.fitness:.0%} → {best_candidate.fitness:.0%}")
                best = best_candidate
                no_improve = 0
                _, details = await evaluate_seed(session, best, TRAIN_QUESTIONS)
                failed = [TRAIN_QUESTIONS[i] for i, d in enumerate(details) if not d["correct"]]
            else:
                print(f"\n  ○ 无改善 ({best.fitness:.0%})")
                no_improve += 1

            history.append({"gen": gen, "best": best.id, "fitness": best.fitness, "seed": best.text[:60]})

        # Hold-out
        print(f"\n{'='*60}")
        print("  Hold-out 验证")
        print(f"{'='*60}")
        bl_ho, _ = await evaluate_seed(session, BASELINE_SEED, HOLDOUT_QUESTIONS)
        best_ho, ho_details = await evaluate_seed(session, best, HOLDOUT_QUESTIONS)
        print(f"  Baseline: {bl_ho:.0%} | Best: {best_ho:.0%} | Δ={best_ho-bl_ho:+.0%}")
        for d in ho_details:
            print(f"    {'✓' if d['correct'] else '✗'} {d['q']} (ans={d['a']})")

        # Summary
        print(f"\n{'='*60}")
        print(f"  演化总结")
        print(f"{'='*60}")
        replaced = best.id != "baseline"
        print(f"  Seed 被替换: {'✅ 是' if replaced else '❌ 否'}")
        print(f"  Train: {BASELINE_SEED.fitness:.0%} → {best.fitness:.0%} (Δ={best.fitness-BASELINE_SEED.fitness:+.0%})")
        print(f"  Hold-out: {bl_ho:.0%} → {best_ho:.0%} (Δ={best_ho-bl_ho:+.0%})")
        print(f"  Final seed: {best.text}")
        for h in history:
            print(f"    Gen {h['gen']}: {h['fitness']:.0%} | {h['seed']}")

        # Save
        Path(".educe").mkdir(exist_ok=True)
        Path(".educe/evolution_v04c_result.json").write_text(json.dumps({
            "replaced": replaced, "baseline_train": BASELINE_SEED.fitness,
            "final_train": best.fitness, "baseline_holdout": bl_ho,
            "final_holdout": best_ho, "final_seed": best.text, "history": history,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run_evolution(max_gen=5))
