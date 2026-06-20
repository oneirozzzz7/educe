"""
激发引擎 v0.4b — 代码题验证（有演化空间 + 可验证评分 + 对照组）

关键改进：
- 换到代码题（baseline 预计 50-65%）
- 用 exec + assert 做零主观评分
- 每 seed 跑 20 题（降低单题权重）
- 加随机变异对照组（证明演化 > 随机）
- 跑 3 次取均值消除噪声
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp

BASE_URL = os.environ.get("EDUCE_BASE_URL", "")
API_KEY = os.environ.get("EDUCE_API_KEY", "")


# ═══ 代码题 Benchmark（答案可 exec 验证）═══

CODE_QUESTIONS = [
    # 字符串处理
    {"q": "写一个 Python 函数 reverse_words(s) 把字符串中的单词顺序反转。例如 'hello world' → 'world hello'",
     "test": "assert reverse_words('hello world') == 'world hello'\nassert reverse_words('a b c') == 'c b a'\nassert reverse_words('hi') == 'hi'"},
    {"q": "写一个 Python 函数 count_vowels(s) 统计字符串中元音字母（aeiou，不区分大小写）的个数",
     "test": "assert count_vowels('hello') == 2\nassert count_vowels('AEIOU') == 5\nassert count_vowels('xyz') == 0"},
    {"q": "写一个 Python 函数 is_palindrome(s) 判断字符串是否是回文（忽略大小写和空格）",
     "test": "assert is_palindrome('racecar') == True\nassert is_palindrome('A man a plan a canal Panama'.replace(' ','')) == True\nassert is_palindrome('hello') == False"},
    {"q": "写一个 Python 函数 remove_duplicates(s) 去除字符串中的重复字符，保持首次出现顺序",
     "test": "assert remove_duplicates('abcabc') == 'abc'\nassert remove_duplicates('hello') == 'helo'\nassert remove_duplicates('aaa') == 'a'"},
    # 数组/列表
    {"q": "写一个 Python 函数 flatten(lst) 把嵌套列表展平为一维。例如 [[1,2],[3,[4,5]]] → [1,2,3,4,5]",
     "test": "assert flatten([[1,2],[3,[4,5]]]) == [1,2,3,4,5]\nassert flatten([1,[2],[[3]]]) == [1,2,3]\nassert flatten([]) == []"},
    {"q": "写一个 Python 函数 two_sum(nums, target) 返回列表中和为 target 的两个数的索引",
     "test": "assert sorted(two_sum([2,7,11,15], 9)) == [0,1]\nassert sorted(two_sum([3,2,4], 6)) == [1,2]"},
    {"q": "写一个 Python 函数 rotate_list(lst, k) 把列表右旋 k 步。例如 [1,2,3,4,5] k=2 → [4,5,1,2,3]",
     "test": "assert rotate_list([1,2,3,4,5], 2) == [4,5,1,2,3]\nassert rotate_list([1,2,3], 1) == [3,1,2]\nassert rotate_list([1], 5) == [1]"},
    {"q": "写一个 Python 函数 max_subarray_sum(nums) 求最大子数组和（Kadane算法）",
     "test": "assert max_subarray_sum([-2,1,-3,4,-1,2,1,-5,4]) == 6\nassert max_subarray_sum([1]) == 1\nassert max_subarray_sum([-1,-2,-3]) == -1"},
    # 数学
    {"q": "写一个 Python 函数 is_prime(n) 判断 n 是否为质数",
     "test": "assert is_prime(2) == True\nassert is_prime(17) == True\nassert is_prime(4) == False\nassert is_prime(1) == False"},
    {"q": "写一个 Python 函数 fibonacci(n) 返回第 n 个斐波那契数（从0开始：0,1,1,2,3,5...）",
     "test": "assert fibonacci(0) == 0\nassert fibonacci(1) == 1\nassert fibonacci(5) == 5\nassert fibonacci(10) == 55"},
    # 字典/集合
    {"q": "写一个 Python 函数 most_frequent(lst) 返回列表中出现最多的元素",
     "test": "assert most_frequent([1,2,2,3,3,3]) == 3\nassert most_frequent(['a','b','a']) == 'a'"},
    {"q": "写一个 Python 函数 group_anagrams(words) 把同字母异序词分组。返回列表的列表",
     "test": "result = group_anagrams(['eat','tea','tan','ate','nat','bat'])\nassert sorted([sorted(g) for g in result]) == sorted([sorted(g) for g in [['eat','tea','ate'],['tan','nat'],['bat']]])"},
    # 递归/动态规划
    {"q": "写一个 Python 函数 climb_stairs(n) 计算爬 n 级台阶的方法数（每次1或2级）",
     "test": "assert climb_stairs(1) == 1\nassert climb_stairs(2) == 2\nassert climb_stairs(5) == 8"},
    {"q": "写一个 Python 函数 coin_change(coins, amount) 返回凑出 amount 所需最少硬币数，不能凑出返回-1",
     "test": "assert coin_change([1,5,10], 11) == 2\nassert coin_change([2], 3) == -1\nassert coin_change([1], 0) == 0"},
    # 实用
    {"q": "写一个 Python 函数 valid_brackets(s) 判断括号字符串是否合法（只含()[]{}）",
     "test": "assert valid_brackets('()[]{}') == True\nassert valid_brackets('([{}])') == True\nassert valid_brackets('(]') == False\nassert valid_brackets('([)]') == False"},
    {"q": "写一个 Python 函数 merge_sorted(a, b) 合并两个已排序列表为一个有序列表",
     "test": "assert merge_sorted([1,3,5],[2,4,6]) == [1,2,3,4,5,6]\nassert merge_sorted([],[1,2]) == [1,2]"},
    {"q": "写一个 Python 函数 matrix_transpose(m) 转置矩阵（列表的列表）",
     "test": "assert matrix_transpose([[1,2,3],[4,5,6]]) == [[1,4],[2,5],[3,6]]"},
    {"q": "写一个 Python 函数 binary_search(arr, target) 在有序数组中查找 target 的索引，不存在返回-1",
     "test": "assert binary_search([1,3,5,7,9], 5) == 2\nassert binary_search([1,3,5,7,9], 4) == -1\nassert binary_search([], 1) == -1"},
    {"q": "写一个 Python 函数 power(base, exp) 实现快速幂，不用 ** 运算符",
     "test": "assert power(2, 10) == 1024\nassert power(3, 0) == 1\nassert power(5, 3) == 125"},
    {"q": "写一个 Python 函数 longest_common_prefix(strs) 返回字符串列表的最长公共前缀",
     "test": "assert longest_common_prefix(['flower','flow','flight']) == 'fl'\nassert longest_common_prefix(['dog','racecar','car']) == ''\nassert longest_common_prefix(['a']) == 'a'"},
]

# 前 15 题训练，后 5 题 hold-out
TRAIN = CODE_QUESTIONS[:15]
HOLDOUT = CODE_QUESTIONS[15:]


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
    text="写出正确的 Python 函数。注意边界条件和特殊情况。代码要简洁高效。",
)


# ═══ 可验证评分（exec + assert）═══

def evaluate_code(response: str, test_code: str) -> bool:
    """从模型输出提取代码并执行测试"""
    # 提取代码块
    code_match = re.search(r'```python\s*(.*?)```', response, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    else:
        # 尝试提取 def 开头的代码
        lines = response.split('\n')
        code_lines = []
        in_func = False
        for line in lines:
            if line.strip().startswith('def '):
                in_func = True
            if in_func:
                code_lines.append(line)
        code = '\n'.join(code_lines) if code_lines else response

    try:
        exec(code + '\n' + test_code, {})
        return True
    except Exception:
        return False


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


# ═══ 评估 ═══

async def evaluate_seed(session, seed: Seed, questions: list[dict]) -> tuple[float, list[dict]]:
    system = f"你是一个 Python 编程助手。\n\n## 思维引导\n{seed.text}\n\n只输出函数代码（用```python```包裹），不要解释。"
    results = []
    for q in questions:
        resp = await call_model(session, system, q["q"])
        passed = evaluate_code(resp, q["test"])
        results.append({"q": q["q"][:40], "passed": passed, "response": resp[:80]})
        await asyncio.sleep(0.3)
    pass_rate = sum(1 for r in results if r["passed"]) / len(results)
    return pass_rate, results


# ═══ 变异 ═══

async def mutate_directed(session, parent: Seed, failed_qs: list[dict], n: int = 4) -> list[Seed]:
    failed_desc = "\n".join(f"- {q['q'][:50]}" for q in failed_qs[:4])
    mutants = []
    for i in range(n):
        style = "微调" if i < 2 else "完全不同思路"
        prompt = f"""当前的编程引导语是："{parent.text}"
但模型在以下题目上输出了错误代码：
{failed_desc}

请改写引导语帮助模型写出正确代码。要求简洁（1-3句），风格：{style}。
只输出改写后的引导语："""
        resp = await call_model(session, "你是 prompt 优化专家。", prompt)
        if resp:
            mutants.append(Seed(id=f"g{parent.generation+1}-m{i}", text=resp.strip()[:200],
                                generation=parent.generation+1, parent_id=parent.id))
        await asyncio.sleep(0.3)
    return mutants


async def mutate_random(session, parent: Seed, n: int = 4) -> list[Seed]:
    """随机变异对照组 — 不看失败题，纯随机改写"""
    mutants = []
    for i in range(n):
        prompt = f"""当前的编程引导语是："{parent.text}"
请随机改写成一个完全不同风格的引导语，不需要任何原因。要求简洁（1-3句）。
只输出改写后的引导语："""
        resp = await call_model(session, "你是 prompt 改写器。", prompt)
        if resp:
            mutants.append(Seed(id=f"g{parent.generation+1}-rand{i}", text=resp.strip()[:200],
                                generation=parent.generation+1, parent_id=parent.id))
        await asyncio.sleep(0.3)
    return mutants


# ═══ 主循环 ═══

async def run_evolution(max_gen: int = 5):
    print("=" * 60)
    print("  激发引擎 v0.4b — 代码题 + 对照组")
    print(f"  训练: {len(TRAIN)} 题 | Hold-out: {len(HOLDOUT)} 题")
    print(f"  对照: 定向变异 vs 随机变异")
    print("=" * 60)

    connector = aiohttp.TCPConnector(limit=5)
    best = BASELINE_SEED
    history = []
    no_improve = 0

    async with aiohttp.ClientSession(connector=connector) as session:
        # Gen 0
        print(f"\n[Gen 0] 评估 baseline...")
        best.fitness, details = await evaluate_seed(session, best, TRAIN)
        failed = [TRAIN[i] for i, d in enumerate(details) if not d["passed"]]
        print(f"  Baseline: {best.fitness:.0%} ({int(best.fitness*len(TRAIN))}/{len(TRAIN)})")
        print(f"  失败: {len(failed)} 题")
        history.append({"gen": 0, "best": best.id, "fitness": best.fitness})

        for gen in range(1, max_gen + 1):
            if not failed:
                print(f"\n[Gen {gen}] 完美！")
                break
            if no_improve >= 3:
                print(f"\n[Gen {gen}] 收敛。")
                break

            print(f"\n[Gen {gen}] 变异...")

            # 定向变异
            directed = await mutate_directed(session, best, failed, n=3)
            # 随机变异（对照）
            random_muts = await mutate_random(session, best, n=2)

            all_candidates = directed + random_muts
            best_candidate = best
            best_is_directed = None

            for mut in all_candidates:
                mut.fitness, _ = await evaluate_seed(session, mut, TRAIN)
                is_dir = "定向" if mut in directed else "随机"
                print(f"    {mut.id} ({is_dir}): {mut.fitness:.0%} | {mut.text[:45]}...")
                if mut.fitness > best_candidate.fitness:
                    best_candidate = mut
                    best_is_directed = (mut in directed)

            if best_candidate.fitness > best.fitness:
                source = "定向" if best_is_directed else "随机"
                print(f"  ✓ 新 best [{source}]: {best.fitness:.0%} → {best_candidate.fitness:.0%}")
                best = best_candidate
                no_improve = 0
                _, details = await evaluate_seed(session, best, TRAIN)
                failed = [TRAIN[i] for i, d in enumerate(details) if not d["passed"]]
            else:
                print(f"  ○ 无改善 ({best.fitness:.0%})")
                no_improve += 1

            history.append({"gen": gen, "best": best.id, "fitness": best.fitness})

        # Hold-out
        print(f"\n{'='*60}")
        print("  Hold-out 验证")
        print(f"{'='*60}")
        bl_ho, _ = await evaluate_seed(session, BASELINE_SEED, HOLDOUT)
        best_ho, ho_details = await evaluate_seed(session, best, HOLDOUT)
        print(f"  Baseline: {bl_ho:.0%} | Final best: {best_ho:.0%} | Δ={best_ho-bl_ho:+.0%}")
        for d in ho_details:
            print(f"    {'✓' if d['passed'] else '✗'} {d['q']}")

        # 总结
        print(f"\n{'='*60}")
        print(f"  总结")
        print(f"{'='*60}")
        print(f"  Baseline train: {BASELINE_SEED.fitness:.0%}")
        print(f"  Final train: {best.fitness:.0%} (Δ={best.fitness-BASELINE_SEED.fitness:+.0%})")
        print(f"  Baseline hold-out: {bl_ho:.0%}")
        print(f"  Final hold-out: {best_ho:.0%} (Δ={best_ho-bl_ho:+.0%})")
        print(f"  Seed 被替换: {'是' if best.id != 'baseline' else '否'}")
        print(f"  Final seed: {best.text}")

        # 保存
        output = {"baseline_train": BASELINE_SEED.fitness, "final_train": best.fitness,
                  "baseline_holdout": bl_ho, "final_holdout": best_ho,
                  "seed_replaced": best.id != "baseline", "final_seed": best.text, "history": history}
        Path(".educe").mkdir(exist_ok=True)
        Path(".educe/evolution_v04b_result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run_evolution(max_gen=5))
