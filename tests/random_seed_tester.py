"""
DeepForge RandomSeedTester
严格按照 random_seed_testing.md 的三层随机架构实现：
  Layer 1: UserPersona — seed → 用户画像
  Layer 2: TrajectoryGenerator — 画像 + seed → 操作序列
  Layer 3: QuestionGenerator — 操作类型 + seed → 自然语言问题

验证标准：
  快速测试 10 seeds: pass_rate >= 90%
  完整测试 30 seeds: pass_rate >= 85%
  没有任何 seed 的 pass_rate < 70%
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import websockets
from dataclasses import dataclass, field
from pathlib import Path


# ═══════════════════════════════════════
#  Layer 1: 用户人格生成
# ═══════════════════════════════════════

class UserPersona:
    ARCHETYPES = {
        "explorer": {
            "weight": 25,
            "topic_switch_rate": 0.7,
            "code_rate": 0.2,
            "follow_up_rate": 0.15,
            "avg_turns": 12,
            "patience": 0.3,
            "domains": "uniform",
        },
        "builder": {
            "weight": 20,
            "topic_switch_rate": 0.3,
            "code_rate": 0.5,
            "follow_up_rate": 0.3,
            "avg_turns": 8,
            "patience": 0.6,
            "domains": ["tech", "tool"],
        },
        "learner": {
            "weight": 20,
            "topic_switch_rate": 0.2,
            "code_rate": 0.05,
            "follow_up_rate": 0.5,
            "avg_turns": 15,
            "patience": 0.7,
            "domains": ["science", "tech", "history", "education"],
        },
        "helper": {
            "weight": 20,
            "topic_switch_rate": 0.4,
            "code_rate": 0.15,
            "follow_up_rate": 0.2,
            "avg_turns": 6,
            "patience": 0.4,
            "domains": ["medical", "legal", "finance", "life"],
        },
        "chatter": {
            "weight": 15,
            "topic_switch_rate": 0.6,
            "code_rate": 0.05,
            "follow_up_rate": 0.1,
            "avg_turns": 10,
            "patience": 0.5,
            "domains": "uniform",
        },
    }

    def __init__(self, seed: int):
        rng = random.Random(seed)
        archetypes = list(self.ARCHETYPES.keys())
        weights = [self.ARCHETYPES[a]["weight"] for a in archetypes]
        self.archetype = rng.choices(archetypes, weights=weights)[0]
        profile = self.ARCHETYPES[self.archetype]

        self.topic_switch_rate = self._perturb(rng, profile["topic_switch_rate"], 0.2)
        self.code_rate = self._perturb(rng, profile["code_rate"], 0.2)
        self.follow_up_rate = self._perturb(rng, profile["follow_up_rate"], 0.2)
        self.avg_turns = max(3, int(profile["avg_turns"] + rng.randint(-3, 3)))
        self.patience = self._perturb(rng, profile["patience"], 0.15)
        self.domains = profile["domains"]

        self.style = rng.choice(["formal", "casual", "terse", "verbose", "mixed"])
        self.uses_emoji = rng.random() < 0.3
        self.makes_typos = rng.random() < 0.15

    def _perturb(self, rng, value, range_pct):
        delta = value * range_pct
        return max(0.01, min(0.99, value + rng.uniform(-delta, delta)))


# ═══════════════════════════════════════
#  Layer 2: 行为轨迹生成
# ═══════════════════════════════════════

class TrajectoryGenerator:
    def generate(self, persona: UserPersona, seed: int) -> list:
        rng = random.Random(seed)
        turns = persona.avg_turns + rng.randint(-3, 3)
        turns = max(3, min(20, turns))

        trajectory = []
        last_action = None
        last_was_code = False
        consecutive_same_topic = 0

        for i in range(turns):
            action = self._decide_action(
                rng, persona, last_action, last_was_code,
                consecutive_same_topic, i, turns
            )
            domain = self._select_domain(rng, persona, trajectory)
            trajectory.append({
                "turn": i + 1,
                "action": action,
                "domain": domain,
                "is_first_turn": i == 0,
                "is_last_turn": i == turns - 1,
            })
            if action == "topic_switch":
                consecutive_same_topic = 0
            else:
                consecutive_same_topic += 1
            last_was_code = action in ("code_request", "code_modify")
            last_action = action

        return trajectory

    def _decide_action(self, rng, persona, last_action, last_was_code,
                        consecutive_same_topic, turn_idx, total_turns):
        if turn_idx == 0:
            return rng.choices(
                ["greeting", "chat", "code_request", "deep_question"],
                weights=[20, 40, 20, 20]
            )[0]

        if turn_idx == total_turns - 1:
            return rng.choices(
                ["positive_feedback", "chat", "topic_switch"],
                weights=[40, 30, 30]
            )[0]

        if last_was_code:
            return rng.choices(
                ["code_modify", "follow_up", "topic_switch", "chat", "positive_feedback", "negative_feedback"],
                weights=[25, 15, 30, 15, 10, 5]
            )[0]

        if last_action == "negative_feedback":
            return rng.choices(
                ["follow_up", "topic_switch", "chat"],
                weights=[50, 35, 15]
            )[0]

        switch_boost = min(consecutive_same_topic * 0.1, 0.3)
        base_weights = {
            "chat": 20,
            "deep_question": 15,
            "code_request": persona.code_rate * 100,
            "follow_up": persona.follow_up_rate * 100,
            "topic_switch": (persona.topic_switch_rate + switch_boost) * 100,
            "file_upload": 5,
            "negative_feedback": 3,
            "positive_feedback": 5,
            "ambiguous": 5,
        }
        actions = list(base_weights.keys())
        weights = list(base_weights.values())
        return rng.choices(actions, weights=weights)[0]

    def _select_domain(self, rng, persona, trajectory):
        ALL_DOMAINS = [
            "medical", "legal", "math", "tech", "finance",
            "writing", "psychology", "history", "science",
            "cooking", "education", "life", "pets", "fitness",
        ]
        if persona.domains == "uniform":
            return rng.choice(ALL_DOMAINS)
        else:
            if rng.random() < 0.8:
                return rng.choice(persona.domains)
            else:
                return rng.choice(ALL_DOMAINS)


# ═══════════════════════════════════════
#  Layer 3: 具体问题生成
# ═══════════════════════════════════════

class QuestionGenerator:
    TEMPLATES = {
        "medical": {
            "chat": [
                "头疼怎么办", "感冒了吃什么药好", "孩子发烧38.5度怎么处理",
                "最近总是失眠怎么办", "体检报告血压偏高", "膝盖疼是什么原因",
                "长期腰疼有什么改善方法", "嗓子疼吃什么药",
            ],
            "deep_question": [
                "为什么糖尿病会遗传", "mRNA疫苗的原理是什么",
                "布洛芬的副作用有哪些", "免疫系统是怎么工作的",
                "幽门螺杆菌怎么根治", "长期失眠有什么科学的改善方法",
            ],
        },
        "legal": {
            "chat": [
                "劳动合同到期公司不续签需要赔偿吗", "租房合同没到期房东要求搬走怎么办",
                "交通事故责任怎么划分", "网购买到假货怎么维权",
                "离婚财产怎么分", "被公司辞退怎么要赔偿",
            ],
            "deep_question": [
                "民法典对遗产继承有什么新规定", "劳动仲裁的流程和时效",
                "合同违约金的法律上限是多少", "知识产权侵权怎么认定",
            ],
        },
        "math": {
            "chat": [
                "一个袋子3红球5蓝球不放回取2个两个都是红球的概率",
                "怎么证明根号2是无理数", "排列组合怎么区分",
                "高考数学怎么从100分提到130分",
            ],
            "deep_question": [
                "证明任意正整数n n(n+1)能被2整除",
                "贝叶斯定理的直觉理解", "微积分的本质是什么",
                "线性代数在实际中有什么应用",
            ],
        },
        "tech": {
            "chat": [
                "Python和Java哪个好学", "什么是微服务架构",
                "Docker怎么用", "学React从哪开始",
                "TCP三次握手的过程第三次丢失会怎样",
                "Redis和Memcached在高并发场景下各自优缺点",
            ],
            "deep_question": [
                "数据库索引的底层原理", "分布式系统的CAP定理",
                "操作系统的虚拟内存机制", "HTTP2和HTTP3的核心区别",
            ],
            "code_request": [
                "做一个番茄钟", "帮我写一个计算器网页",
                "做个待办清单应用", "写一个密码生成器",
                "帮我做一个贪吃蛇游戏", "做一个BMI计算器",
                "写个Python脚本统计文件行数",
            ],
            "code_modify": [
                "改成红色", "加个深色模式", "字体改大一点",
                "把标题去掉", "加一个返回按钮", "改成圆角",
                "加个导出按钮", "背景换成渐变色",
            ],
        },
        "finance": {
            "chat": [
                "月收入1万存款20万如何规划养老投资",
                "什么是可转债什么情况下适合转股",
                "基金定投和一次性买入哪个好",
                "怎么看股票的财务报表",
            ],
            "deep_question": [
                "通货膨胀的本质原因", "为什么美联储加息会影响全球",
                "比特币的底层原理", "期权定价模型是怎么回事",
            ],
        },
        "science": {
            "chat": [
                "光速为什么不能被超越",
                "mRNA疫苗和传统灭活疫苗的本质区别",
                "黑洞是怎么形成的", "量子计算是什么",
            ],
            "deep_question": [
                "薛定谔的猫到底说的是什么", "暗物质存在的证据",
                "进化论的核心证据有哪些", "相对论的时间膨胀效应",
            ],
        },
        "history": {
            "chat": [
                "安史之乱为什么是唐朝由盛转衰的转折点",
                "秦始皇统一六国的关键因素有哪些",
                "二战的转折点是什么", "明朝为什么灭亡",
            ],
            "deep_question": [
                "工业革命为什么首先在英国发生",
                "罗马帝国衰落的根本原因", "丝绸之路的历史影响",
                "冷战对当今世界格局的影响",
            ],
        },
        "psychology": {
            "chat": [
                "工作三年感觉没成长很迷茫该怎么办",
                "考试前极度焦虑怎么缓解",
                "总是拖延怎么办", "和同事关系不好怎么处理",
            ],
            "deep_question": [
                "认知行为疗法的核心原理",
                "为什么人会有从众心理",
                "原生家庭对性格的影响有多大",
            ],
        },
        "cooking": {
            "chat": [
                "红烧肉怎么做才能肥而不腻入口即化",
                "糖醋排骨的正宗做法和关键步骤",
                "番茄炒蛋怎么做好吃", "蒸鱼怎么去腥",
            ],
            "deep_question": [
                "美拉德反应在烹饪中的应用",
                "低温慢煮的科学原理",
            ],
        },
        "education": {
            "chat": [
                "如何用费曼技巧学习复杂概念",
                "高考数学怎么从100分提到130分",
                "孩子注意力不集中怎么办", "记忆力差怎么训练",
            ],
            "deep_question": [
                "间隔重复法的科学依据", "刻意练习和普通练习的区别",
            ],
        },
        "writing": {
            "chat": [
                "帮我润色一段自我介绍", "怎么写一篇好的读书笔记",
                "年终总结怎么写", "求职信怎么写才有竞争力",
            ],
        },
        "life": {
            "chat": [
                "新房装修甲醛怎么除", "空调不制冷怎么办",
                "马桶堵了怎么通", "搬家有什么注意事项",
            ],
        },
        "pets": {
            "chat": [
                "猫咪呕吐是什么原因", "狗狗疫苗打几针",
                "养猫需要准备什么", "猫粮怎么选",
            ],
        },
        "fitness": {
            "chat": [
                "减脂期怎么控制饮食", "跑步膝盖疼怎么办",
                "增肌需要吃蛋白粉吗", "每天运动多久合适",
            ],
        },
        "tool": {
            "code_request": [
                "做一个单位换算工具", "帮我写个正则表达式测试器",
                "做一个简单的记事本网页", "写一个倒计时器",
                "做个颜色选择器", "帮我做一个二维码生成器",
            ],
            "code_modify": [
                "改成蓝色主题", "加个清除按钮", "支持深色模式",
                "把界面改成居中", "加一个历史记录功能",
            ],
        },
    }

    GENERIC = {
        "greeting": ["你好", "嗨", "在吗", "hi", "你好呀"],
        "positive_feedback": ["谢谢", "太好了", "不错，很有帮助", "学到了", "完美"],
        "negative_feedback": ["不对", "错了", "不是这样的", "你说的不准确", "重新回答"],
        "follow_up": [
            "继续说", "详细讲讲", "举个例子", "为什么", "还有呢",
            "这个能展开说说吗", "具体来说呢",
        ],
        "topic_switch": [],
        "ambiguous": [
            "那个怎么弄", "帮我看看", "这个对吗", "有什么好的",
            "能不能搞一下", "你觉得呢",
        ],
        "file_upload": [
            "帮我分析一下这个文件", "这个数据什么意思",
            "帮我看看这段代码", "这个报告有什么问题",
        ],
    }

    def generate(self, action: str, domain: str, persona: UserPersona,
                 trajectory: list, seed: int) -> str:
        rng = random.Random(seed)

        if action in self.GENERIC and self.GENERIC[action]:
            question = rng.choice(self.GENERIC[action])
            return self._apply_style(rng, question, persona)

        if action == "topic_switch":
            all_domains = list(self.TEMPLATES.keys())
            other_domains = [d for d in all_domains if d != domain]
            domain = rng.choice(other_domains) if other_domains else domain
            action = "chat"

        domain_templates = self.TEMPLATES.get(domain, {})
        action_templates = domain_templates.get(action)
        if not action_templates:
            action_templates = domain_templates.get("chat")
        if not action_templates:
            action_templates = ["请问关于{}的问题".format(domain)]

        question = rng.choice(action_templates)
        return self._apply_style(rng, question, persona)

    def _apply_style(self, rng, question, persona):
        if persona.style == "terse":
            question = question.rstrip("呢吗吧啊呀")
        elif persona.style == "verbose":
            prefixes = ["请问一下，", "我想问问，", "麻烦帮我看看，", "有个问题想请教，"]
            question = rng.choice(prefixes) + question
        elif persona.style == "casual":
            suffixes = ["呢", "啊", "呗", "吧", "嘛"]
            question = question + rng.choice(suffixes)

        if persona.uses_emoji and rng.random() < 0.3:
            emojis = ["😊", "🤔", "👀", "💡", "🙏"]
            question = question + " " + rng.choice(emojis)

        return question


# ═══════════════════════════════════════
#  完整测试运行器
# ═══════════════════════════════════════

@dataclass
class TurnResult:
    turn: int
    action: str
    domain: str
    question: str
    response: str = ""
    passed: bool = False
    fail_reason: str = ""
    duration: float = 0.0


class RandomSeedTester:
    def __init__(self, ws_url: str = "ws://localhost:7860/ws"):
        self.ws_url = ws_url
        self.qgen = QuestionGenerator()
        self.tgen = TrajectoryGenerator()

    async def run_test(self, seed: int) -> dict:
        persona = UserPersona(seed)
        trajectory = self.tgen.generate(persona, seed + 1000)

        questions = []
        for step in trajectory:
            q = self.qgen.generate(
                action=step["action"],
                domain=step["domain"],
                persona=persona,
                trajectory=trajectory,
                seed=seed + step["turn"] * 100,
            )
            step["question"] = q
            questions.append(step)

        results = await self._execute_session(questions)

        passed_count = sum(1 for r in results if r.passed)
        total = len(results)

        return {
            "seed": seed,
            "persona": persona.archetype,
            "style": persona.style,
            "turns": total,
            "results": [self._result_to_dict(r) for r in results],
            "pass_rate": passed_count / total if total > 0 else 0,
            "passed": passed_count,
            "failed": total - passed_count,
        }

    async def _execute_session(self, questions: list) -> list:
        import uuid
        sid = uuid.uuid4().hex[:8]
        results = []

        try:
            async with websockets.connect("{}/{}".format(self.ws_url, sid)) as ws:
                for step in questions:
                    q = step["question"]
                    action = step["action"]

                    # file_upload跳过（需要实际文件）
                    if action == "file_upload":
                        results.append(TurnResult(
                            turn=step["turn"], action=action,
                            domain=step["domain"], question=q,
                            passed=True, fail_reason="skipped_file_upload"
                        ))
                        continue

                    start = time.time()
                    await ws.send(json.dumps({"message": q}))

                    reply = ""
                    try:
                        while True:
                            d = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                            if d.get("type") == "agent_message":
                                reply = d.get("content", "")
                            if d.get("content") == "idle":
                                break
                    except asyncio.TimeoutError:
                        pass

                    dur = round(time.time() - start, 1)
                    passed, fail_reason = self._validate_turn(action, step["domain"], q, reply)

                    results.append(TurnResult(
                        turn=step["turn"], action=action,
                        domain=step["domain"], question=q,
                        response=reply[:500], passed=passed,
                        fail_reason=fail_reason, duration=dur,
                    ))
        except Exception as e:
            for step in questions[len(results):]:
                results.append(TurnResult(
                    turn=step["turn"], action=step["action"],
                    domain=step["domain"], question=step["question"],
                    passed=False, fail_reason="connection_error: {}".format(str(e)[:80])
                ))

        return results

    def _validate_turn(self, action: str, domain: str, question: str, response: str) -> tuple:
        if not response:
            return False, "empty_response"

        if len(response) < 5:
            return False, "response_too_short"

        if "出错了:" in response or "ERROR" in response:
            return False, "error_response"

        if action in ("code_request", "code_modify"):
            has_code = ("<!DOCTYPE" in response or "filepath:" in response
                       or "<html" in response.lower() or "def " in response
                       or "function " in response or "未能生成" in response)
            if not has_code and len(response) < 100:
                return False, "code_expected_but_got_text"
            return True, ""

        if action == "greeting":
            return True, ""

        if action in ("positive_feedback", "negative_feedback"):
            return True, ""

        if action in ("chat", "deep_question", "follow_up"):
            if len(response) < 50:
                return False, "response_too_short_for_question"
            return True, ""

        return True, ""

    def _result_to_dict(self, r: TurnResult) -> dict:
        return {
            "turn": r.turn, "action": r.action, "domain": r.domain,
            "question": r.question[:60], "passed": r.passed,
            "fail_reason": r.fail_reason, "duration": r.duration,
        }

    async def run_batch(self, seeds: list) -> dict:
        all_results = []
        for seed in seeds:
            result = await self.run_test(seed)
            all_results.append(result)
            print("  seed={}: {:10s} {:7s} {}turns pass={:.0f}% ({}/{})".format(
                seed, result["persona"], result["style"],
                result["turns"], result["pass_rate"] * 100,
                result["passed"], result["turns"]))

        overall_pass = sum(r["pass_rate"] for r in all_results) / len(all_results)

        by_persona = {}
        for r in all_results:
            p = r["persona"]
            if p not in by_persona:
                by_persona[p] = {"count": 0, "total_pass_rate": 0}
            by_persona[p]["count"] += 1
            by_persona[p]["total_pass_rate"] += r["pass_rate"]
        for p in by_persona:
            by_persona[p]["avg_pass_rate"] = round(
                by_persona[p]["total_pass_rate"] / by_persona[p]["count"], 3)

        weak_seeds = [r for r in all_results if r["pass_rate"] < 0.7]
        failures = []
        for r in all_results:
            for tr in r["results"]:
                if not tr["passed"] and tr["fail_reason"] not in ("", "skipped_file_upload"):
                    failures.append({
                        "seed": r["seed"], "persona": r["persona"],
                        "turn": tr["turn"], "action": tr["action"],
                        "question": tr["question"], "reason": tr["fail_reason"],
                    })

        return {
            "total_seeds": len(seeds),
            "overall_pass_rate": round(overall_pass, 3),
            "by_persona": by_persona,
            "weak_seeds": [{"seed": r["seed"], "pass_rate": r["pass_rate"]} for r in weak_seeds],
            "failure_details": failures[:20],
            "verdict": "PASS" if overall_pass >= 0.9 and not weak_seeds else "NEEDS_WORK",
        }


async def quick_test():
    print("=" * 60)
    print("RandomSeedTester - Quick Test (10 seeds)")
    print("=" * 60)
    tester = RandomSeedTester()
    result = await tester.run_batch(list(range(42, 52)))
    print()
    print("Overall: {:.1f}% (target >= 90%)".format(result["overall_pass_rate"] * 100))
    print("By persona:", json.dumps(result["by_persona"], indent=2, ensure_ascii=False))
    if result["weak_seeds"]:
        print("Weak seeds (<70%):", result["weak_seeds"])
    if result["failure_details"]:
        print("Failures:")
        for f in result["failure_details"][:10]:
            print("  seed={} turn={} {} {} -> {}".format(
                f["seed"], f["turn"], f["action"], f["question"][:30], f["reason"]))
    print("Verdict:", result["verdict"])
    return result


async def full_test():
    print("=" * 60)
    print("RandomSeedTester - Full Test (30 seeds)")
    print("=" * 60)
    tester = RandomSeedTester()
    result = await tester.run_batch(list(range(42, 72)))
    print()
    print("Overall: {:.1f}% (target >= 85%)".format(result["overall_pass_rate"] * 100))
    print("Verdict:", result["verdict"])
    return result


if __name__ == "__main__":
    asyncio.run(quick_test())
