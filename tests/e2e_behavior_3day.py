"""
E2E 3-Day Behavior Learning Simulation

模拟"张工"（资深后端工程师）连续使用 3 天：
- Day 1: 冷启动，2次显式纠正（简洁+可运行代码）
- Day 2: 规则生效，验证注入后输出改善，积累 marginal_value
- Day 3: 稳态，坏规则被淘汰，系统收敛

Pass criteria: 9 项指标中通过 >= 7 项
"""
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from deepforge.core.behavior import BehaviorManifest, BehaviorUnit, UnitStatus
from deepforge.core.behavior_learner import BehaviorLearner
from deepforge.models.router import ModelClient

API_KEY = os.environ.get("EDUCE_MODEL_KEY", "")
BASE_URL = os.environ.get("EDUCE_MODEL_URL", "")
MODEL = os.environ.get("EDUCE_MODEL_NAME", "qwen36")

if not API_KEY or not BASE_URL:
    try:
        cfg = json.loads(Path(".deepforge/config.json").read_text())
        API_KEY = cfg.get("default_model", {}).get("api_key", "")
        BASE_URL = cfg.get("default_model", {}).get("base_url", "")
        MODEL = cfg.get("default_model", {}).get("model", MODEL)
    except Exception:
        pass

BASE_SYSTEM = "你是一个技术助手，帮助用户解答编程问题和写代码。"

# ═══════════════════════════════════════
# Compliance Checkers
# ═══════════════════════════════════════

def check_concise(response: str) -> bool:
    sentences = re.split(r'[。！？\n]', response)
    sentences = [s for s in sentences if len(s.strip()) > 5]
    return len(response) < 500 or len(sentences) <= 8

def check_runnable_code(response: str) -> bool:
    code_blocks = re.findall(r'```(?:go|python)?\s*\n(.*?)```', response, re.DOTALL)
    if not code_blocks:
        return False
    for block in code_blocks:
        if 'import' in block or 'package' in block or 'from ' in block:
            return True
    return False

def check_english_terms(response: str) -> bool:
    bad_translations = ["协程", "通道", "互斥锁", "读写锁", "垃圾回收器", "调度器"]
    count = sum(1 for t in bad_translations if t in response)
    return count < 2

def check_not_too_concise(response: str) -> bool:
    return len(response) > 400

def detect_signal(query: str, prev_response: str) -> str:
    q = query.lower()
    positive = ["谢谢", "太好了", "正是", "很有帮助", "不错", "完美"]
    negative = ["不对", "错了", "太啰嗦", "废话", "不要", "不能", "缺少", "漏了"]
    if any(w in query for w in negative):
        return "error"
    if any(w in query for w in positive):
        return "grateful"
    return "neutral"


# ═══════════════════════════════════════
# Interaction Scripts
# ═══════════════════════════════════════

DAY1 = [
    {"query": "Go语言的channel和mutex有什么区别？"},
    {"query": "Docker的multi-stage build怎么用？"},
    {"query": "Redis的pub/sub和stream有什么区别？"},
    {"query": "不对，你说得太啰嗦了，我只要结论，3-5句话搞定", "is_correction": True},
    {"query": "K8s的liveness和readiness probe区别？"},
    {"query": "又太长了，简洁点行不行", "is_correction": True},
    {"query": "写个Go的并发worker pool"},
    {"query": "错了，你给的代码不能直接运行，缺少import和main函数", "is_correction": True},
    {"query": "解释一下goroutine的调度模型"},
    {"query": "继续讲GMP模型"},
]

DAY2 = [
    {"query": "gRPC和REST的区别？", "check": "concise"},
    {"query": "谢谢，讲得清楚"},
    {"query": "写个用context做timeout控制的Go例子", "check": "runnable"},
    {"query": "太好了，可以直接用"},
    {"query": "解释mutex和RWMutex的差别", "check": "concise"},
    {"query": "推荐几本产品经理入门书"},
    {"query": "Go的interface和Java的interface有啥不同？", "check": "concise"},
    {"query": "写一个带graceful shutdown的HTTP server", "check": "runnable"},
    {"query": "channel的底层数据结构是什么？", "check": "concise"},
    {"query": "能详细展开讲一下Go的GC三色标记法吗？每个阶段都解释一下", "check": "not_too_concise"},
    {"query": "sync.Pool的使用场景？"},
    {"query": "写个用errgroup处理并发错误的例子", "check": "runnable"},
    {"query": "太好了，这个可以直接用"},
    {"query": "什么是work stealing scheduler？"},
    {"query": "协程和线程的区别？"},
]

DAY3 = [
    {"query": "怎么设计一个分布式锁？", "check": "concise"},
    {"query": "不对，为什么开头讲笑话？直接回答问题", "is_correction": True},
    {"query": "etcd和ZooKeeper选哪个？", "check": "concise"},
    {"query": "写个分布式锁的Go实现", "check": "runnable"},
    {"query": "谢谢，正是我要的"},
    {"query": "CAP theorem是什么？", "check": "concise"},
    {"query": "ACID和BASE的区别？"},
    {"query": "Raft算法的leader election怎么工作？"},
    {"query": "总结一下Go做微服务的最佳实践", "check": "concise"},
    {"query": "谢谢，很有帮助"},
]


# ═══════════════════════════════════════
# Test Engine
# ═══════════════════════════════════════

@dataclass
class TurnResult:
    day: int
    turn: int
    query: str
    signal: str
    response_len: int
    check_name: str = ""
    check_passed: bool = True
    rules_staged: int = 0
    rules_active: int = 0
    rules_archived: int = 0
    learned_this_turn: str = ""


async def run_day(day_num: int, interactions: list, learner: BehaviorLearner,
                  manifest: BehaviorManifest, client: ModelClient, prev_response: str = "") -> list[TurnResult]:
    results = []
    prev_injected_ids: list[str] = []

    for i, turn in enumerate(interactions):
        query = turn["query"]
        signal = detect_signal(query, prev_response)

        # 反馈回填（对上一轮注入的 units）
        if prev_response and prev_injected_ids:
            if signal in ("grateful", "engaged"):
                learner.reinforce(prev_injected_ids[0])
            elif signal in ("error", "unsatisfied"):
                learner.penalize(prev_injected_ids[0])

        # 学习（纠正轮）
        learned = ""
        if turn.get("is_correction") and prev_response:
            unit = await learner.learn_from_correction(prev_response, query, client, MODEL)
            if unit:
                learned = unit.directive[:60]

        # 构建 prompt（全量注入 active + staged）
        system = BASE_SYSTEM
        behavior_text = manifest.render_for_prompt("")
        if behavior_text and behavior_text != manifest.base_seed:
            system += f"\n{behavior_text}"

        # 决定哪些被注入、哪些被 withhold
        candidates = manifest.active_units() + manifest.staged_units()
        injected_ids = []
        withheld_ids = []
        for u in candidates:
            if learner.should_withhold(u.id):
                withheld_ids.append(u.id)
            else:
                injected_ids.append(u.id)

        # 记录 baseline for withheld
        for uid in withheld_ids:
            is_ok = signal in ("grateful", "engaged", "neutral")
            learner.record_baseline(uid, compliant=is_ok)

        # 生成回复
        response = await client.chat(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": query}],
            model=MODEL, max_tokens=600, temperature=0.3,
        )

        # Output-Metric Attribution: 记录输出特征到 units
        from deepforge.core.response_features import compute_response_features
        features = compute_response_features(response)
        for uid in injected_ids:
            unit = manifest.get_unit(uid)
            if unit and unit.effect_dimension and unit.effect_dimension in features:
                unit.record_metric_sample(features[unit.effect_dimension], injected=True)
        for uid in withheld_ids:
            unit = manifest.get_unit(uid)
            if unit and unit.effect_dimension and unit.effect_dimension in features:
                unit.record_metric_sample(features[unit.effect_dimension], injected=False)

        # Check compliance
        check_name = turn.get("check", "")
        check_passed = True
        if check_name == "concise":
            check_passed = check_concise(response)
        elif check_name == "runnable":
            check_passed = check_runnable_code(response)
        elif check_name == "english_terms":
            check_passed = check_english_terms(response)
        elif check_name == "not_too_concise":
            check_passed = check_not_too_concise(response)

        # 动态信号：check 有结果时，直接 reinforce/penalize 被注入的 units
        if check_name and injected_ids:
            if check_passed:
                learner.reinforce(injected_ids[0])
            else:
                learner.penalize(injected_ids[0])

        # lifecycle
        learner.lifecycle_check()

        stats = manifest.stats()
        results.append(TurnResult(
            day=day_num, turn=i+1, query=query[:40],
            signal=signal, response_len=len(response),
            check_name=check_name, check_passed=check_passed,
            rules_staged=stats["staged"], rules_active=stats["active"],
            rules_archived=stats["archived"], learned_this_turn=learned,
        ))

        prev_response = response
        prev_injected_ids = injected_ids

    return results


async def main():
    if not API_KEY or not BASE_URL:
        print("Set EDUCE_MODEL_KEY and EDUCE_MODEL_URL")
        return

    client = ModelClient(api_key=API_KEY, base_url=BASE_URL)
    manifest = BehaviorManifest(agent_id="zhang_gong", base_seed=BASE_SYSTEM)
    persist_path = Path("/tmp/e2e_behavior_test_manifest.json")
    learner = BehaviorLearner(manifest=manifest, persist_path=persist_path)

    print("═" * 60)
    print("E2E 3-Day Behavior Learning Simulation")
    print("Persona: 张工 (senior backend engineer, Go specialist)")
    print("═" * 60)

    all_results = []

    # ═══ Day 1 ═══
    print(f"\n{'─'*60}\nDay 1: Cold start + corrections ({len(DAY1)} turns)\n{'─'*60}")
    day1_results = await run_day(1, DAY1, learner, manifest, client)
    all_results.extend(day1_results)
    for r in day1_results:
        icon = "📝" if r.learned_this_turn else ("✓" if r.check_passed else "✗")
        extra = f" → learned: {r.learned_this_turn}" if r.learned_this_turn else ""
        print(f"  [{r.turn:>2}] {icon} {r.query}... (sig={r.signal}, len={r.response_len}){extra}")
    print(f"  State: staged={manifest.stats()['staged']}, active={manifest.stats()['active']}")

    # 模拟时间推进 + 快进 hit_count（模拟一天的自然使用）
    for u in manifest.units:
        if u.status == UnitStatus.STAGED:
            u.hit_count = max(u.hit_count, 2)

    # ═══ Day 2 ═══
    print(f"\n{'─'*60}\nDay 2: Rules active + marginal_value ({len(DAY2)} turns)\n{'─'*60}")
    day2_results = await run_day(2, DAY2, learner, manifest, client, prev_response="")
    all_results.extend(day2_results)
    for r in day2_results:
        check_str = f" [{r.check_name}={'✓' if r.check_passed else '✗'}]" if r.check_name else ""
        print(f"  [{r.turn:>2}] {r.query}... (sig={r.signal}, len={r.response_len}){check_str}")
    print(f"  State: staged={manifest.stats()['staged']}, active={manifest.stats()['active']}")

    # 注入坏规则（Day 3 验证淘汰）
    bad_rule = BehaviorUnit(
        id="bad_joke", trigger="任何问题", directive="每次回答都以一个笑话开头",
        weight=0.35, status=UnitStatus.STAGED,
        hit_count=2, success_count=1, fail_count=1,
    )
    bad_rule.last_hit_at = time.time()
    manifest.add_unit(bad_rule, message="injected bad rule for test")

    # ═══ Day 3 ═══
    print(f"\n{'─'*60}\nDay 3: Convergence + bad rule archival ({len(DAY3)} turns)\n{'─'*60}")
    day3_results = await run_day(3, DAY3, learner, manifest, client, prev_response="")
    all_results.extend(day3_results)
    for r in day3_results:
        check_str = f" [{r.check_name}={'✓' if r.check_passed else '✗'}]" if r.check_name else ""
        print(f"  [{r.turn:>2}] {r.query}... (sig={r.signal}, len={r.response_len}){check_str}")
    print(f"  State: staged={manifest.stats()['staged']}, active={manifest.stats()['active']}, archived={manifest.stats()['archived']}")

    # ═══════════════════════════════════════
    # PASS/FAIL Evaluation
    # ═══════════════════════════════════════
    print(f"\n{'═'*60}\nEVALUATION\n{'═'*60}\n")

    scores = {}

    # 1. 学习效率：Day 1 纠正后立即产生规则
    learned_turns = [r for r in day1_results if r.learned_this_turn]
    scores["learning_efficiency"] = len(learned_turns) >= 2
    print(f"  1. Learning efficiency: {len(learned_turns)} rules learned from {sum(1 for t in DAY1 if t.get('is_correction'))} corrections → {'PASS' if scores['learning_efficiency'] else 'FAIL'}")

    # 2. 晋升速度：Day 2 结束时至少 1 条 active
    day2_active = day2_results[-1].rules_active if day2_results else 0
    scores["promotion_speed"] = day2_active >= 1
    print(f"  2. Promotion speed: {day2_active} active by end of Day 2 → {'PASS' if scores['promotion_speed'] else 'FAIL'}")

    # 3. 收敛性：Day 3 结束时 active <= 5
    final_active = manifest.stats()["active"]
    scores["convergence"] = final_active <= 5
    print(f"  3. Convergence: {final_active} active rules at end → {'PASS' if scores['convergence'] else 'FAIL'}")

    # 4. 坏规则淘汰
    bad = manifest.get_unit("bad_joke")
    scores["bad_rule_archived"] = bad is None or bad.status == UnitStatus.ARCHIVED
    print(f"  4. Bad rule archived: {bad.status.value if bad else 'deleted'} → {'PASS' if scores['bad_rule_archived'] else 'FAIL'}")

    # 5. Day 2 check 通过率 >= 60%
    day2_checks = [r for r in day2_results if r.check_name]
    day2_pass_rate = sum(1 for r in day2_checks if r.check_passed) / max(1, len(day2_checks))
    scores["injection_quality"] = day2_pass_rate >= 0.6
    print(f"  5. Injection quality: {day2_pass_rate:.0%} checks passed in Day 2 → {'PASS' if scores['injection_quality'] else 'FAIL'}")

    # 6. 无害性：Day 2 "详细展开" 轮不过度简洁
    not_concise_checks = [r for r in day2_results if r.check_name == "not_too_concise"]
    scores["no_harm"] = all(r.check_passed for r in not_concise_checks) if not_concise_checks else True
    print(f"  6. No harm (detailed Q not truncated): {'PASS' if scores['no_harm'] else 'FAIL'}")

    # 7. marginal_value 有效
    active_units = manifest.active_units()
    has_high_mv = any(u.marginal_value >= 0.2 for u in active_units) if active_units else False
    scores["marginal_value_valid"] = has_high_mv or len(active_units) == 0
    print(f"  7. Marginal value: {'has unit with mv>=0.2' if has_high_mv else 'no high mv'} → {'PASS' if scores['marginal_value_valid'] else 'FAIL'}")

    # 8. baseline 积累
    baseline_ok = any(u.baseline_tests >= 2 for u in manifest.units if u.status != UnitStatus.ARCHIVED)
    scores["baseline_accumulation"] = baseline_ok
    print(f"  8. Baseline accumulation: {'has unit with bt>=2' if baseline_ok else 'insufficient'} → {'PASS' if scores['baseline_accumulation'] else 'FAIL'}")

    # 9. 误学习率 < 50%
    total_learned = manifest.stats()["total_units"]
    archived_count = manifest.stats()["archived"]
    false_positive_rate = archived_count / max(1, total_learned)
    scores["false_positive_rate"] = false_positive_rate < 0.5
    print(f"  9. False positive rate: {false_positive_rate:.0%} archived/total → {'PASS' if scores['false_positive_rate'] else 'FAIL'}")

    # Final verdict
    passed = sum(1 for v in scores.values() if v)
    total = len(scores)
    print(f"\n{'═'*60}")
    verdict = "PASS" if passed >= 7 else "FAIL"
    color = "\033[92m" if verdict == "PASS" else "\033[91m"
    print(f"  {color}RESULT: {verdict} ({passed}/{total} criteria met)\033[0m")
    print(f"{'═'*60}")

    # Manifest final state
    print(f"\nFinal manifest state:")
    for u in manifest.units:
        print(f"  [{u.status.value:>8}] {u.id[:12]:<12} w={u.weight:.2f} mv={u.marginal_value:.2f} hits={u.hit_count} bt={u.baseline_tests}")


if __name__ == "__main__":
    asyncio.run(main())
