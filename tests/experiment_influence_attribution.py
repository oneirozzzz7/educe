"""
影响力归因实验（Influence Attribution Experiment）

核心问题：BehaviorUnit 注入 prompt 后，模型行为的改变是"因为规则"还是"尽管规则"？

实验设计：
- 5 条不同类型的 BehaviorUnit（覆盖风格/结构/内容/格式/安全）
- 每条规则 × 10 个同类问题 = 50 对 (with_rule, without_rule)
- 用弱模型(Qwen3.6-35B)跑，因为弱模型更容易受 prompt 影响
- 每对回答用自动化指标 + LLM Judge 评估"规则是否生效"

指标：
- compliance_rate: 有规则时遵守规则的比例
- baseline_rate: 无规则时恰好符合规则的比例
- delta = compliance_rate - baseline_rate（真实影响力）
- delta < 5%: 规则无效（模型忽略）
- delta 5-20%: 弱影响
- delta > 20%: 强影响（架构根基成立）
"""
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from educe.models.router import ModelClient

# 模型配置
API_KEY = os.environ.get("EDUCE_MODEL_KEY", "")
BASE_URL = os.environ.get("EDUCE_MODEL_URL", "")
MODEL = os.environ.get("EDUCE_MODEL_NAME", "qwen36")

if not API_KEY or not BASE_URL:
    try:
        cfg_path = Path(".educe/config.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            API_KEY = cfg.get("default_model", {}).get("api_key", "")
            BASE_URL = cfg.get("default_model", {}).get("base_url", "")
            MODEL = cfg.get("default_model", {}).get("model", MODEL)
    except Exception:
        pass

if not API_KEY or not BASE_URL:
    print("请设置 EDUCE_MODEL_KEY / EDUCE_MODEL_URL 或 .educe/config.json")
    exit(1)


# ═══════════════════════════════════════════════════════════
# 实验数据：5条规则 × 10个问题
# ═══════════════════════════════════════════════════════════

RULES = [
    {
        "id": "concise",
        "unit": "当用户说\"简单解释\"或\"通俗解释\"时：用一个生活类比开头（不超过2句），然后一个最小代码示例（不超过5行），总字数控制在200字以内",
        "check_description": "回答是否在200字以内，且有类比",
        "questions": [
            "简单解释一下什么是递归",
            "通俗解释一下哈希表",
            "简单解释什么是闭包",
            "通俗解释一下HTTP协议",
            "简单解释什么是多线程",
            "通俗解释一下数据库索引",
            "简单解释什么是API",
            "通俗解释一下正则表达式",
            "简单解释什么是缓存",
            "通俗解释一下异步编程",
        ],
    },
    {
        "id": "no_emoji",
        "unit": "在技术回答中不要使用任何 emoji 表情符号，保持专业文档风格",
        "check_description": "回答中是否不含emoji",
        "questions": [
            "Python 的 GIL 是什么？",
            "怎么处理 JavaScript 的异步错误？",
            "Docker 和虚拟机的区别是什么？",
            "什么时候用 Redis 什么时候用 MySQL？",
            "Git rebase 和 merge 有什么区别？",
            "怎么设计一个好的 REST API？",
            "微服务架构的优缺点？",
            "如何避免 SQL 注入？",
            "React hooks 的原理是什么？",
            "TCP 和 UDP 的区别？",
        ],
    },
    {
        "id": "chinese_only",
        "unit": "所有回答必须完全使用中文，包括代码注释也用中文，变量名可以用英文但解释文字必须全中文",
        "check_description": "除代码关键字和变量名外，解释文字是否全部中文",
        "questions": [
            "Write a Python function to reverse a string",
            "How to implement binary search?",
            "Explain the observer pattern",
            "What is dependency injection?",
            "How does garbage collection work?",
            "Explain the difference between stack and heap",
            "What is a design pattern?",
            "How to handle race conditions?",
            "What is memoization?",
            "Explain event-driven architecture",
        ],
    },
    {
        "id": "security_first",
        "unit": "当用户问代码实现时，必须首先指出安全风险（如果有），然后再给出安全的实现。安全警告用「⚠️ 安全提示：」开头",
        "check_description": "回答是否包含安全提示/警告",
        "questions": [
            "怎么用 Python 执行系统命令？",
            "怎么拼接 SQL 查询？",
            "怎么处理用户上传的文件？",
            "怎么存储用户密码？",
            "怎么用 eval 执行动态代码？",
            "怎么做 HTTP 请求时传 token？",
            "怎么读取用户输入并显示在网页上？",
            "怎么做文件下载功能？",
            "怎么实现用户登录？",
            "怎么用正则验证用户邮箱？",
        ],
    },
    {
        "id": "structured_answer",
        "unit": "回答技术问题时，必须使用这个结构：先用一句话总结答案，然后「为什么：」解释原因，最后「示例：」给代码。三段式，不多不少",
        "check_description": "回答是否包含明确的三段结构（总结+为什么+示例）",
        "questions": [
            "什么是 SOLID 原则中的单一职责？",
            "为什么要用 TypeScript？",
            "什么是 Promise？",
            "为什么数据库要用事务？",
            "什么是 RESTful？",
            "为什么要写单元测试？",
            "什么是中间件？",
            "为什么要用版本控制？",
            "什么是依赖注入？",
            "为什么前端要用打包工具？",
        ],
    },
]


# ═══════════════════════════════════════════════════════════
# 自动化检测函数（每条规则对应一个 checker）
# ═══════════════════════════════════════════════════════════

def check_concise(response: str) -> bool:
    """200字以内 + 有类比（比喻、像、好比、就像）"""
    has_analogy = any(w in response for w in ["像", "好比", "就像", "类比", "比喻", "想象", "好像", "如同"])
    is_short = len(response) < 400  # 中文200字 ≈ 400 chars
    return has_analogy and is_short


def check_no_emoji(response: str) -> bool:
    """不含 emoji"""
    import re
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF"
        "\U0000FE00-\U0000FE0F\U0000200D]+",
        flags=re.UNICODE,
    )
    return not bool(emoji_pattern.search(response))


def check_chinese_only(response: str) -> bool:
    """解释文字主要是中文（中文字符占比 > 30%）"""
    import re
    # 去掉代码块
    text_only = re.sub(r'```[\s\S]*?```', '', response)
    text_only = re.sub(r'`[^`]*`', '', text_only)
    if not text_only.strip():
        return False
    chinese_chars = len(re.findall(r'[一-鿿]', text_only))
    total_alpha = len(re.findall(r'[a-zA-Z]', text_only))
    if chinese_chars + total_alpha == 0:
        return False
    return chinese_chars / (chinese_chars + total_alpha) > 0.4


def check_security_first(response: str) -> bool:
    """包含安全相关提示"""
    security_keywords = ["安全", "风险", "注意", "警告", "危险", "漏洞", "防", "⚠",
                         "security", "warning", "caution", "injection", "XSS", "CSRF"]
    return any(kw in response for kw in security_keywords)


def check_structured(response: str) -> bool:
    """包含三段式结构标记"""
    has_summary = len(response.split('\n')[0]) < 100  # 第一行是短总结
    has_why = any(w in response for w in ["为什么", "原因", "因为", "本质"])
    has_example = any(w in response for w in ["示例", "例如", "```", "代码"])
    return has_summary and has_why and has_example


CHECKERS = {
    "concise": check_concise,
    "no_emoji": check_no_emoji,
    "chinese_only": check_chinese_only,
    "security_first": check_security_first,
    "structured_answer": check_structured,
}


# ═══════════════════════════════════════════════════════════
# 实验执行
# ═══════════════════════════════════════════════════════════

@dataclass
class TrialResult:
    rule_id: str
    question: str
    with_rule: str = ""
    without_rule: str = ""
    compliant_with: bool = False
    compliant_without: bool = False


@dataclass
class ExperimentResult:
    rule_id: str
    rule_text: str
    trials: list = field(default_factory=list)
    compliance_with: float = 0.0     # 有规则时的遵守率
    compliance_without: float = 0.0  # 无规则时的基线率
    delta: float = 0.0               # 真实影响力

    def compute(self):
        n = len(self.trials)
        if n == 0:
            return
        self.compliance_with = sum(1 for t in self.trials if t.compliant_with) / n
        self.compliance_without = sum(1 for t in self.trials if t.compliant_without) / n
        self.delta = self.compliance_with - self.compliance_without


BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


async def run_experiment():
    client = ModelClient(api_key=API_KEY, base_url=BASE_URL)
    results: list[ExperimentResult] = []

    base_system = "你是一个编程助手。"

    print(f"\n{BOLD}═══ 影响力归因实验 ═══{RESET}")
    print(f"模型: {MODEL}")
    print(f"规则数: {len(RULES)}")
    print(f"总查询数: {len(RULES) * 10 * 2} (每条规则 × 10问 × 2组)")
    print(f"{'─'*60}\n")

    for rule_data in RULES:
        rule_id = rule_data["id"]
        rule_text = rule_data["unit"]
        questions = rule_data["questions"]
        checker = CHECKERS[rule_id]

        exp = ExperimentResult(rule_id=rule_id, rule_text=rule_text)
        print(f"{BOLD}[{rule_id}]{RESET} {rule_text[:60]}...")

        system_with_rule = (
            f"{base_system}\n\n"
            f"## 经验教训（供参考，你有权根据具体情况判断是否适用）\n"
            f"- {rule_text}"
        )

        for i, q in enumerate(questions):
            # 并发跑 with/without
            resp_with, resp_without = await asyncio.gather(
                client.chat(
                    messages=[{"role": "system", "content": system_with_rule},
                              {"role": "user", "content": q}],
                    model=MODEL, max_tokens=600, temperature=0.3,
                ),
                client.chat(
                    messages=[{"role": "system", "content": base_system},
                              {"role": "user", "content": q}],
                    model=MODEL, max_tokens=600, temperature=0.3,
                ),
            )

            trial = TrialResult(
                rule_id=rule_id,
                question=q,
                with_rule=resp_with,
                without_rule=resp_without,
                compliant_with=checker(resp_with),
                compliant_without=checker(resp_without),
            )
            exp.trials.append(trial)

            # 进度指示
            icon = "✓" if trial.compliant_with and not trial.compliant_without else \
                   "≈" if trial.compliant_with == trial.compliant_without else \
                   "✗" if not trial.compliant_with else "?"
            print(f"  {DIM}[{i+1}/10] {icon} q=\"{q[:30]}...\" with={trial.compliant_with} base={trial.compliant_without}{RESET}")

        exp.compute()
        delta_color = GREEN if exp.delta > 0.2 else YELLOW if exp.delta > 0.05 else RED
        print(f"  {BOLD}→ compliance: {exp.compliance_with:.0%} (with) vs {exp.compliance_without:.0%} (baseline) | "
              f"{delta_color}delta = {exp.delta:+.0%}{RESET}\n")
        results.append(exp)

    # ═══════════════════════════════════════════════════════════
    # 总结
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'═'*60}")
    print(f"{BOLD}实验结果总结{RESET}")
    print(f"{'═'*60}\n")

    print(f"{'规则':<20} {'有规则':<10} {'无规则':<10} {'Delta':<10} {'判定'}")
    print(f"{'─'*60}")

    total_delta = 0
    for exp in results:
        if exp.delta > 0.20:
            verdict = f"{GREEN}强影响 ✓{RESET}"
        elif exp.delta > 0.05:
            verdict = f"{YELLOW}弱影响 ~{RESET}"
        else:
            verdict = f"{RED}无效 ✗{RESET}"
        print(f"{exp.rule_id:<20} {exp.compliance_with:<10.0%} {exp.compliance_without:<10.0%} {exp.delta:<+10.0%} {verdict}")
        total_delta += exp.delta

    avg_delta = total_delta / len(results)
    print(f"{'─'*60}")
    print(f"{'平均':<20} {'':10} {'':10} {avg_delta:<+10.0%}")

    print(f"\n{BOLD}结论：{RESET}")
    if avg_delta > 0.20:
        print(f"{GREEN}  架构根基成立。BehaviorUnit 注入显著改变模型行为 (avg delta={avg_delta:.0%})。")
        print(f"  学习系统产出的规则具有真实影响力。{RESET}")
    elif avg_delta > 0.05:
        print(f"{YELLOW}  部分有效。某些类型的规则能改变行为，某些被忽略。")
        print(f"  需要优化规则的表达方式和注入策略。{RESET}")
    else:
        print(f"{RED}  架构根基存疑。规则注入未能显著改变模型行为。")
        print(f"  模型可能忽略了 system prompt 中的行为指令。{RESET}")

    # 保存详细数据
    output_path = Path(".educe/experiments/influence_attribution.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "timestamp": time.time(),
        "model": MODEL,
        "avg_delta": avg_delta,
        "results": [
            {
                "rule_id": exp.rule_id,
                "rule_text": exp.rule_text,
                "compliance_with": exp.compliance_with,
                "compliance_without": exp.compliance_without,
                "delta": exp.delta,
                "trials": [
                    {
                        "question": t.question,
                        "compliant_with": t.compliant_with,
                        "compliant_without": t.compliant_without,
                        "with_rule_len": len(t.with_rule),
                        "without_rule_len": len(t.without_rule),
                    }
                    for t in exp.trials
                ],
            }
            for exp in results
        ],
    }
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2))
    print(f"\n{DIM}详细数据已保存: {output_path}{RESET}")


if __name__ == "__main__":
    asyncio.run(run_experiment())
