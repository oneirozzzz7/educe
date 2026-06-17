"""
Marginal Value 数据采集管道

并行运行20个场景，每个跑40轮交互，产出 JSONL 事件数据。
用于验证 marginal_value 机制的正确性和积累真实分布数据。

用法: EDUCE_MODEL_KEY=... EDUCE_MODEL_URL=... python tests/pipeline_marginal_value.py
"""
import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import sys
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

CONCURRENCY = 4
OUTPUT_DIR = Path(".educe/experiments/marginal_data")


# ═══════════════════════════════════════
# Checkers
# ═══════════════════════════════════════

def check_short(resp: str) -> bool:
    return len(resp) < 600  # 中文200字 ≈ 600 chars

def check_no_emoji(resp: str) -> bool:
    return not bool(re.search(r'[\U0001F600-\U0001FAFF\U00002600-\U000027BF]', resp))

def check_chinese_majority(resp: str) -> bool:
    text = re.sub(r'```[\s\S]*?```', '', resp)
    cn = len(re.findall(r'[一-鿿]', text))
    en = len(re.findall(r'[a-zA-Z]', text))
    return cn / (cn + en + 1) > 0.4

def check_has_security(resp: str) -> bool:
    return any(w in resp for w in ["安全", "风险", "注意", "警告", "漏洞", "⚠"])

def check_numbered_list(resp: str) -> bool:
    return bool(re.search(r'^\d+\.', resp, re.MULTILINE))

def check_no_markdown_header(resp: str) -> bool:
    return not bool(re.search(r'^#+\s', resp, re.MULTILINE))

def check_has_analogy(resp: str) -> bool:
    return any(w in resp for w in ["像", "好比", "就像", "如同", "好像", "想象"])

def check_starts_with_summary(resp: str) -> bool:
    first_line = resp.strip().split('\n')[0]
    return len(first_line) < 80

def check_has_type_hint(resp: str) -> bool:
    return bool(re.search(r'(:\s*(int|str|float|bool|list|dict|Optional|Any)|\)\s*->)', resp))

def check_no_var(resp: str) -> bool:
    return "var " not in resp


# ═══════════════════════════════════════
# Scenarios
# ═══════════════════════════════════════

SCENARIOS = [
    # STRONG (model won't do without rule)
    {"id": "s01", "category": "strong",
     "correction": "所有回答必须控制在100字以内",
     "checker": check_short,
     "questions": [f"解释{t}" for t in ["微服务","Docker","REST API","ORM","CI/CD",
                   "GraphQL","WebSocket","OAuth","JWT","Redis",
                   "消息队列","服务网格","K8s","gRPC","Serverless"]]},
    {"id": "s02", "category": "strong",
     "correction": "不要用markdown标题（#），用粗体代替",
     "checker": check_no_markdown_header,
     "questions": [f"介绍{t}" for t in ["React","Vue","Angular","Svelte","Next.js",
                   "Nuxt","Remix","Astro","SolidJS","Qwik",
                   "Webpack","Vite","Rollup","esbuild","Turbopack"]]},
    {"id": "s03", "category": "strong",
     "correction": "每个回答必须用生活类比开头",
     "checker": check_has_analogy,
     "questions": [f"简单解释{t}" for t in ["递归","闭包","多线程","哈希表","二叉树",
                   "缓存","索引","事务","锁","队列",
                   "栈","图","堆","链表","集合"]]},
    {"id": "s04", "category": "strong",
     "correction": "代码中不允许使用var关键字，只能用const或let",
     "checker": check_no_var,
     "questions": [f"用JavaScript写{t}" for t in ["数组去重","深拷贝","防抖函数","节流函数","柯里化",
                   "发布订阅","Promise.all","深合并","扁平化数组","链式调用",
                   "单例模式","观察者","迭代器","生成器","代理模式"]]},
    {"id": "s05", "category": "strong",
     "correction": "问题用英文问，但你必须用中文回答，代码注释也用中文",
     "checker": check_chinese_majority,
     "questions": ["How to implement binary search?","Explain the observer pattern",
                   "What is dependency injection?","How does garbage collection work?",
                   "Explain stack vs heap","What is memoization?",
                   "How to handle race conditions?","What is event loop?",
                   "Explain CAP theorem","What is sharding?",
                   "How does DNS work?","What is load balancing?",
                   "Explain ACID properties","What is eventual consistency?",
                   "How does TLS work?"]},

    # MODERATE (model sometimes does)
    {"id": "s06", "category": "moderate",
     "correction": "回答技术问题时第一行必须是一句话总结（不超过20字）",
     "checker": check_starts_with_summary,
     "questions": [f"什么是{t}" for t in ["SOLID原则","设计模式","依赖注入","控制反转","面向对象",
                   "函数式编程","响应式编程","领域驱动","微前端","Monorepo",
                   "TDD","BDD","DDD","CQRS","Event Sourcing"]]},
    {"id": "s07", "category": "moderate",
     "correction": "Python代码必须有type hint",
     "checker": check_has_type_hint,
     "questions": [f"用Python写{t}" for t in ["快速排序","二分查找","BFS","DFS","动态规划",
                   "LRU缓存","单例模式","工厂模式","装饰器","生成器",
                   "协程示例","文件读写","HTTP请求","JSON解析","日志系统"]]},
    {"id": "s08", "category": "moderate",
     "correction": "回答中不要使用emoji表情",
     "checker": check_no_emoji,
     "questions": [f"怎么{t}" for t in ["配置Nginx","部署Docker","用Git rebase","写Dockerfile","配置CI",
                   "用Redis做缓存","配置Webpack","写单元测试","做性能优化","处理并发",
                   "做数据迁移","配置SSL","用消息队列","做服务发现","配置负载均衡"]]},

    # WEAK (model already does this mostly)
    {"id": "s09", "category": "weak",
     "correction": "回答代码问题时要给代码示例",
     "checker": lambda r: "```" in r,
     "questions": [f"怎么用Python {t}" for t in ["读文件","发HTTP请求","连数据库","解析JSON","写日志",
                   "多线程","异步IO","正则匹配","操作Excel","发邮件",
                   "压缩文件","加密数据","连Redis","用SQLAlchemy","写爬虫"]]},
    {"id": "s10", "category": "weak",
     "correction": "SQL相关回答要提醒注入风险",
     "checker": check_has_security,
     "questions": [f"怎么用SQL {t}" for t in ["拼接查询","动态WHERE","LIKE搜索","用户登录验证","批量插入",
                   "导出数据","权限检查","日志查询","统计报表","删除用户",
                   "更新密码","搜索功能","分页查询","模糊匹配","关联查询"]]},
    {"id": "s11", "category": "weak",
     "correction": "回答要用有序列表组织",
     "checker": check_numbered_list,
     "questions": [f"{t}的步骤是什么" for t in ["部署应用","代码review","性能优化","安全审计","数据迁移",
                   "故障排查","容量规划","灾难恢复","版本发布","回滚操作",
                   "监控告警","日志分析","压力测试","API设计","数据库设计"]]},
]


# ═══════════════════════════════════════
# Pipeline Core
# ═══════════════════════════════════════

async def run_scenario(scenario: dict, client: ModelClient, output_dir: Path):
    sid = scenario["id"]
    checker = scenario["checker"]
    questions = scenario["questions"]
    correction = scenario["correction"]

    manifest = BehaviorManifest(agent_id=f"pipe_{sid}", base_seed="你是一个编程助手。")
    persist_path = output_dir / f"{sid}_manifest.json"
    learner = BehaviorLearner(manifest=manifest, persist_path=persist_path)

    events = []

    # Phase A: Baseline (5 questions, no rule)
    for q in questions[:5]:
        try:
            resp = await client.chat(
                messages=[{"role": "system", "content": "你是一个编程助手。"},
                          {"role": "user", "content": q}],
                model=MODEL, max_tokens=500, temperature=0.3,
            )
        except Exception as e:
            resp = f"[error: {e}]"

        events.append({
            "scenario_id": sid, "category": scenario["category"],
            "phase": "baseline", "unit_id": None,
            "question": q, "injected": False,
            "compliant": checker(resp), "response_len": len(resp),
            "ts": time.time(),
        })

    # Phase B: Learn rule
    unit = BehaviorUnit(
        id=f"u_{sid}", trigger=correction[:60], directive=correction,
        evidence=["pipeline:synthetic"], weight=0.4, status=UnitStatus.STAGED,
    )
    manifest.add_unit(unit, message=f"pipeline learn: {sid}")

    # Phase C: Mixed rounds (withhold some for baseline measurement)
    for i, q in enumerate(questions[5:]):
        withhold = learner.should_withhold(unit.id)

        if not withhold:
            # Inject rule
            system = manifest.render_for_prompt(q)
            if system == manifest.base_seed:
                # Unit is STAGED, manually inject
                system = f"你是一个编程助手。\n\n## 经验教训（供参考，你有权根据具体情况判断是否适用）\n- {correction}"
        else:
            system = "你是一个编程助手。"

        try:
            resp = await client.chat(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": q}],
                model=MODEL, max_tokens=500, temperature=0.3,
            )
        except Exception as e:
            resp = f"[error: {e}]"

        compliant = checker(resp)

        # Record events
        events.append({
            "scenario_id": sid, "category": scenario["category"],
            "phase": "mixed", "unit_id": unit.id,
            "question": q, "injected": not withhold,
            "compliant": compliant, "response_len": len(resp),
            "round": i, "unit_status": unit.status.value,
            "unit_weight": round(unit.weight, 3),
            "unit_marginal_value": round(unit.marginal_value, 3),
            "unit_baseline_tests": unit.baseline_tests,
            "ts": time.time(),
        })

        # Feedback
        if withhold:
            learner.record_baseline(unit.id, compliant)
        elif compliant:
            learner.reinforce(unit.id)
        else:
            learner.penalize(unit.id)

    # Write JSONL
    output_file = output_dir / f"{sid}_events.jsonl"
    with open(output_file, "w") as f:
        for evt in events:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    # Summary
    baseline_compliance = sum(1 for e in events if e["phase"] == "baseline" and e["compliant"]) / max(1, sum(1 for e in events if e["phase"] == "baseline"))
    injected_compliance = sum(1 for e in events if e["phase"] == "mixed" and e["injected"] and e["compliant"]) / max(1, sum(1 for e in events if e["phase"] == "mixed" and e["injected"]))
    withheld_compliance = sum(1 for e in events if e["phase"] == "mixed" and not e["injected"] and e["compliant"]) / max(1, sum(1 for e in events if e["phase"] == "mixed" and not e["injected"]))

    return {
        "scenario_id": sid,
        "category": scenario["category"],
        "baseline_compliance": round(baseline_compliance, 3),
        "injected_compliance": round(injected_compliance, 3),
        "withheld_compliance": round(withheld_compliance, 3),
        "delta": round(injected_compliance - withheld_compliance, 3),
        "marginal_value_final": round(unit.marginal_value, 3),
        "unit_status_final": unit.status.value,
        "events_count": len(events),
    }


async def main():
    if not API_KEY or not BASE_URL:
        print("Set EDUCE_MODEL_KEY and EDUCE_MODEL_URL")
        return

    client = ModelClient(api_key=API_KEY, base_url=BASE_URL)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Pipeline: {len(SCENARIOS)} scenarios, concurrency={CONCURRENCY}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Estimated: ~{len(SCENARIOS) * 15} API calls\n")

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def bounded(s):
        async with semaphore:
            print(f"  [{s['id']}] starting ({s['category']})...")
            result = await run_scenario(s, client, OUTPUT_DIR)
            delta_str = f"+{result['delta']:.0%}" if result['delta'] > 0 else f"{result['delta']:.0%}"
            print(f"  [{s['id']}] done: delta={delta_str}, mv={result['marginal_value_final']:.2f}")
            return result

    results = await asyncio.gather(*[bounded(s) for s in SCENARIOS])

    # Summary
    summary = {
        "timestamp": time.time(),
        "model": MODEL,
        "scenarios": len(SCENARIOS),
        "results": results,
        "by_category": {},
    }
    for cat in ["strong", "moderate", "weak"]:
        cat_results = [r for r in results if r["category"] == cat]
        if cat_results:
            summary["by_category"][cat] = {
                "avg_delta": round(sum(r["delta"] for r in cat_results) / len(cat_results), 3),
                "avg_marginal_value": round(sum(r["marginal_value_final"] for r in cat_results) / len(cat_results), 3),
                "count": len(cat_results),
            }

    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    print(f"\n{'='*50}")
    print("PIPELINE RESULTS")
    print(f"{'='*50}")
    print(f"{'Category':<12} {'Avg Delta':<12} {'Avg MV':<12} {'N'}")
    print(f"{'-'*50}")
    for cat, data in summary["by_category"].items():
        print(f"{cat:<12} {data['avg_delta']:+.0%}{'':<8} {data['avg_marginal_value']:.2f}{'':<8} {data['count']}")
    print(f"\nSaved: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
