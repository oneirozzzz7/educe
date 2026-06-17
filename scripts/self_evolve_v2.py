"""
DeepForge 自进化引擎 v2
五层闭环：检测 → 诊断 → 修复 → 验证 → 沉淀

检测层(弱模型)：跑多维度测试
诊断层：分析失败根因
修复层：生成修复方案（只追加不修改）
验证层：A/B对比确认修复有效
沉淀层：高价值经验编译进L1
"""
from __future__ import annotations

import asyncio
import json
import time
import random
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any

from educe.core.config import EduceConfig, ModelConfig
from educe.core.orchestrator import Orchestrator
from educe.models.router import ModelClient
from educe.agents import ALL_AGENTS
from educe.memory.store import MemoryStore
from educe.skills.registry import SkillRegistry
from educe.core.knowledge import LayeredCache

LOG_DIR = Path(".educe/evolution")
LOG_DIR.mkdir(parents=True, exist_ok=True)

TASKS = [
    "做一个番茄钟网页",
    "做一个JSON格式化工具",
    "做一个密码生成器",
    "做一个BMI计算器",
    "做一个倒计时网页",
    "做一个颜色选择器",
    "做一个贪吃蛇游戏",
    "做一个石头剪刀布游戏",
    "做一个简单的画板工具",
    "做一个Markdown编辑器",
    "做一个CSS渐变生成器",
    "做一个单位换算工具",
    "做一个简单的投票页面",
    "做一个打字速度测试工具",
]


class EvolutionEngineV2:
    def __init__(self, config: EduceConfig, client: ModelClient):
        self.config = config
        self.client = client
        self.knowledge = LayeredCache()
        self.memory = MemoryStore(".educe/memory")
        self.log_file = LOG_DIR / f"evo2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self.stats = {
            "rounds": 0, "tests": 0, "passes": 0, "fails": 0,
            "diagnoses": 0, "fixes": 0, "verified": 0, "deposited": 0,
            "started_at": time.time(),
        }

    def _log(self, event: str, data: dict):
        entry = {"time": datetime.now().isoformat(), "event": event, **data}
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ═══════════════════════════════════════
    #  Layer 1: 检测（弱模型跑测试）
    # ═══════════════════════════════════════

    async def detect(self, task: str) -> dict:
        """用弱模型跑任务，返回多维度检测结果"""
        orch = self._create_orchestrator()
        start = time.time()

        try:
            ctx = await asyncio.wait_for(orch.run(task), timeout=180)
            dur = time.time() - start
            files = ctx.artifacts.get("code_files", [])
            eng = ctx.artifacts.get("engineer_output", "")

            has_output = bool(files) or bool(re.search(r'<!DOCTYPE', eng, re.I))

            # 多维度检查
            checks = {}
            if has_output:
                checks["has_file"] = True
                checks["has_doctype"] = "<!DOCTYPE" in eng or "<!doctype" in eng
                checks["has_closing"] = "</html>" in eng
                checks["has_css_vars"] = len(re.findall(r'--[\w-]+:', eng)) >= 3
                checks["has_animation"] = "@keyframes" in eng
                checks["has_responsive"] = "@media" in eng
                checks["has_error_handling"] = "try" in eng or "catch" in eng
                checks["size_ok"] = 5000 < len(eng) < 50000
            else:
                checks["has_file"] = False

            passed = checks.get("has_file", False) and checks.get("has_closing", False)

            result = {
                "task": task, "passed": passed, "duration": round(dur, 1),
                "output_size": len(eng), "checks": checks,
                "checks_passed": sum(1 for v in checks.values() if v),
                "checks_total": len(checks),
            }

            self.stats["tests"] += 1
            if passed:
                self.stats["passes"] += 1
            else:
                self.stats["fails"] += 1

            self._log("detect_pass" if passed else "detect_fail", result)
            return result

        except asyncio.TimeoutError:
            self.stats["tests"] += 1
            self.stats["fails"] += 1
            result = {"task": task, "passed": False, "error": "timeout", "duration": 180}
            self._log("detect_timeout", result)
            return result
        except Exception as e:
            self.stats["tests"] += 1
            self.stats["fails"] += 1
            result = {"task": task, "passed": False, "error": str(e)[:100]}
            self._log("detect_error", result)
            return result

    # ═══════════════════════════════════════
    #  Layer 2: 诊断（分析失败根因）
    # ═══════════════════════════════════════

    def diagnose(self, result: dict) -> dict:
        """分析失败根因——不调LLM，用规则诊断"""
        if result.get("passed"):
            # 通过了也诊断质量不足项
            checks = result.get("checks", {})
            gaps = [k for k, v in checks.items() if not v]
            if gaps:
                return {"category": "quality_gap", "gaps": gaps, "severity": "low"}
            return {"category": "all_good", "severity": "none"}

        error = result.get("error", "")
        checks = result.get("checks", {})

        if error == "timeout":
            return {"category": "timeout", "severity": "high",
                    "cause": "Builder或模型调用超时", "fix": "减少prompt长度或增加超时"}

        if not checks.get("has_file", False):
            return {"category": "no_output", "severity": "critical",
                    "cause": "Builder未产出代码文件", "fix": "强化prompt要求直接输出代码"}

        if not checks.get("has_closing", False):
            return {"category": "truncated", "severity": "high",
                    "cause": "代码被截断(缺少</html>)", "fix": "启用截断续写机制"}

        return {"category": "unknown", "severity": "medium",
                "cause": f"未知失败: {error}", "fix": "需要人工分析"}

    # ═══════════════════════════════════════
    #  Layer 3: 修复（生成修复方案）
    # ═══════════════════════════════════════

    def fix(self, diagnosis: dict) -> dict | None:
        """生成修复方案——只追加知识，不修改代码结构"""
        category = diagnosis.get("category")
        self.stats["fixes"] += 1

        if category == "quality_gap":
            gaps = diagnosis.get("gaps", [])
            for gap in gaps:
                knowledge = self._gap_to_knowledge(gap)
                if knowledge:
                    self.knowledge.add(knowledge["content"], knowledge["triggers"], "pattern")
            return {"action": "knowledge_added", "count": len(gaps)}

        elif category == "no_output":
            self.knowledge.add(
                "Builder必须输出```filepath:文件名格式的完整代码，禁止输出描述文字",
                {"builder", "输出", "格式", "代码", "文件"},
                "lesson",
            )
            return {"action": "lesson_added", "topic": "output_format"}

        elif category == "truncated":
            self.knowledge.add(
                "HTML文件必须有</html>闭合标签，如果被截断需要续写补全",
                {"html", "截断", "闭合", "truncated"},
                "lesson",
            )
            return {"action": "lesson_added", "topic": "truncation"}

        elif category == "timeout":
            self.knowledge.add(
                "复杂任务prompt要精简，减少上下文长度以降低超时风险",
                {"超时", "timeout", "prompt", "精简"},
                "lesson",
            )
            return {"action": "lesson_added", "topic": "timeout"}

        return None

    def _gap_to_knowledge(self, gap: str) -> dict | None:
        mapping = {
            "has_css_vars": {
                "content": "CSS必须使用:root变量系统(--primary, --bg, --text等)",
                "triggers": {"css", "变量", "root", "颜色"},
            },
            "has_animation": {
                "content": "CSS必须包含@keyframes动画(loading/pulse/fadeIn等至少1个)",
                "triggers": {"css", "动画", "animation", "keyframes"},
            },
            "has_responsive": {
                "content": "必须有@media响应式查询适配移动端",
                "triggers": {"响应式", "media", "移动端", "responsive"},
            },
            "has_error_handling": {
                "content": "JS必须有try/catch错误处理",
                "triggers": {"错误", "error", "try", "catch"},
            },
        }
        return mapping.get(gap)

    # ═══════════════════════════════════════
    #  Layer 4: 验证（A/B对比）
    # ═══════════════════════════════════════

    async def verify(self, task: str, before_result: dict) -> dict:
        """修复后重跑同一任务，对比是否改善"""
        after_result = await self.detect(task)
        self.stats["verified"] += 1

        before_score = before_result.get("checks_passed", 0)
        after_score = after_result.get("checks_passed", 0)

        improved = after_score > before_score
        regressed = after_score < before_score

        verdict = {
            "task": task,
            "before": before_score,
            "after": after_score,
            "improved": improved,
            "regressed": regressed,
        }

        self._log("verify", verdict)

        if regressed:
            # 回滚——但我们只追加了知识没改代码，所以不需要回滚
            self._log("regression_detected", verdict)

        return verdict

    # ═══════════════════════════════════════
    #  Layer 5: 沉淀（编译进L1）
    # ═══════════════════════════════════════

    def deposit(self, verify_result: dict):
        """成功的修复经验编译进L1"""
        if verify_result.get("improved"):
            # 让知识库重新编译L1
            self.knowledge._compile_l1()
            self.stats["deposited"] += 1
            self._log("deposited", {"l1_count": len(self.knowledge._compiled_l1)})

    # ═══════════════════════════════════════
    #  记忆管理（防膨胀）
    # ═══════════════════════════════════════

    def cleanup_memory(self, max_entries: int = 1000):
        """定期清理——保留高价值，淘汰低价值"""
        entries = list(self.knowledge._entries.values())
        if len(entries) <= max_entries:
            return

        # 按价值排序：使用次数×成功率
        entries.sort(key=lambda e: e.usage_count * e.success_rate, reverse=True)

        # 保留top max_entries
        keep_ids = {e.id for e in entries[:max_entries]}
        to_remove = [e.id for e in entries if e.id not in keep_ids]

        for eid in to_remove:
            del self.knowledge._entries[eid]

        self.knowledge._rebuild_index()
        self.knowledge._save()
        self._log("cleanup", {"removed": len(to_remove), "remaining": len(self.knowledge._entries)})

    # ═══════════════════════════════════════
    #  主循环
    # ═══════════════════════════════════════

    async def run_cycle(self):
        """一轮完整五层闭环"""
        self.stats["rounds"] += 1
        task = random.choice(TASKS)

        print(f"\n{'─'*50}")
        print(f"🧬 进化轮次 #{self.stats['rounds']} | {task}")

        # Layer 1: 检测
        result = await self.detect(task)
        passed = result.get("passed", False)
        score = result.get("checks_passed", 0)
        total = result.get("checks_total", 0)
        print(f"  L1检测: {'✅' if passed else '❌'} {score}/{total} ({result.get('duration',0)}s)")

        # Layer 2: 诊断
        diagnosis = self.diagnose(result)
        self.stats["diagnoses"] += 1
        print(f"  L2诊断: {diagnosis['category']} ({diagnosis.get('severity','?')})")

        if diagnosis["category"] == "all_good":
            # Layer 5: 直接沉淀成功经验
            self.knowledge.add(
                f"[成功] {task} → {score}/{total}分",
                self.knowledge._tokenize(task),
                "success",
            )
            self.stats["deposited"] += 1
            print(f"  L5沉淀: 成功经验记录")
            return

        # Layer 3: 修复
        fix_result = self.fix(diagnosis)
        if fix_result:
            print(f"  L3修复: {fix_result.get('action')} ({fix_result.get('topic', fix_result.get('count',''))})")

            # Layer 4: 验证（有50%概率做验证，避免每轮都重跑）
            if random.random() < 0.5 and not result.get("error"):
                verify = await self.verify(task, result)
                print(f"  L4验证: before={verify['before']} after={verify['after']} {'📈' if verify['improved'] else '➡️'}")

                # Layer 5: 沉淀
                self.deposit(verify)
                if verify.get("improved"):
                    print(f"  L5沉淀: 改进已编译进L1")

        # 定期清理记忆
        if self.stats["rounds"] % 20 == 0:
            self.cleanup_memory()
            print(f"  🧹 记忆清理完成")

    def print_stats(self):
        elapsed = (time.time() - self.stats["started_at"]) / 3600
        rate = self.stats["passes"] / max(self.stats["tests"], 1) * 100
        print(f"\n{'═'*50}")
        print(f"📊 进化统计 (运行 {elapsed:.1f}h)")
        print(f"  检测: {self.stats['tests']} 次, 通过率: {rate:.0f}%")
        print(f"  诊断: {self.stats['diagnoses']} | 修复: {self.stats['fixes']} | 验证: {self.stats['verified']}")
        print(f"  沉淀: {self.stats['deposited']} | 知识库: {len(self.knowledge._entries)} 条")
        print(f"  L1编译: {len(self.knowledge._compiled_l1)} 条热知识")
        print(f"{'═'*50}")

    def generate_report(self) -> dict:
        """生成进化报告——可被API调用"""
        elapsed = (time.time() - self.stats["started_at"]) / 3600
        rate = self.stats["passes"] / max(self.stats["tests"], 1) * 100
        k_stats = self.knowledge.stats()

        return {
            "elapsed_hours": round(elapsed, 2),
            "rounds": self.stats["rounds"],
            "tests": self.stats["tests"],
            "pass_rate": round(rate, 1),
            "diagnoses": self.stats["diagnoses"],
            "fixes": self.stats["fixes"],
            "verified": self.stats["verified"],
            "deposited": self.stats["deposited"],
            "knowledge": k_stats,
            "log_file": str(self.log_file),
        }

    def _create_orchestrator(self) -> Orchestrator:
        orch = Orchestrator(self.config, max_iterations=2)
        ms = MemoryStore(".educe/memory")
        sr = SkillRegistry(".educe/skills", ".educe/community_skills")
        for ac in ALL_AGENTS:
            a = ac(config=self.config, model_client=self.client)
            if hasattr(a, "memory_store"):
                a.memory_store = ms
            if hasattr(a, "skill_registry"):
                a.skill_registry = sr
            orch.register(a)
        return orch


async def main():
    import argparse, sys, os
    sys.path.insert(0, ".")
    sys.path.insert(0, "tests")

    parser = argparse.ArgumentParser(description="DeepForge 自进化引擎 v2")
    parser.add_argument("--hours", type=float, default=0, help="运行时长(小时)")
    parser.add_argument("--interval", type=int, default=60, help="每轮间隔(秒)")
    args = parser.parse_args()

    from local_config_loader import load_keys_from_llm_api
    load_keys_from_llm_api()

    config = EduceConfig.load()
    if not config.default_model.api_key:
        print("❌ 请先配置API Key")
        return

    client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)
    engine = EvolutionEngineV2(config, client)
    end_time = time.time() + args.hours * 3600 if args.hours > 0 else float("inf")

    print("╔══════════════════════════════════════╗")
    print("║  DeepForge 自进化引擎 v2             ║")
    print("║  五层闭环：检测→诊断→修复→验证→沉淀  ║")
    print(f"║  模型: {config.default_model.model:<29}║")
    print("╚══════════════════════════════════════╝")

    try:
        while time.time() < end_time:
            await engine.run_cycle()
            if engine.stats["rounds"] % 5 == 0:
                engine.print_stats()
            if time.time() < end_time:
                await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n⏹ 进化已停止")

    engine.print_stats()


if __name__ == "__main__":
    asyncio.run(main())
