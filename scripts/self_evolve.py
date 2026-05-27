#!/usr/bin/env python3
"""
DeepForge 自进化引擎
持续运行，自动发现问题、改进框架、验证效果

用法:
    python scripts/self_evolve.py              # 运行直到手动停止
    python scripts/self_evolve.py --hours 12   # 运行12小时
"""

import asyncio
import json
import os
import re
import sys
import time
import random
import traceback
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from deepforge.core.config import DeepForgeConfig, ModelConfig
from deepforge.core.orchestrator import Orchestrator
from deepforge.core.message import Message, MessageType, WorkContext
from deepforge.models.router import ModelClient
from deepforge.agents import ALL_AGENTS
from deepforge.agents.engineer import EngineerAgent
from deepforge.agents.supervisor import SupervisorAgent
from deepforge.memory.store import MemoryStore, MemoryEntry
from deepforge.skills.registry import SkillRegistry

# ═══ 进化任务池 ═══

CODE_QUALITY_TASKS = [
    "做一个密码生成器网页，支持设置长度和字符类型",
    "做一个颜色选择器工具，支持RGB和HEX转换",
    "做一个倒计时网页，可以设置目标日期",
    "做一个BMI计算器",
    "做一个二维码生成器网页",
    "做一个简单的画板工具，支持画笔和橡皮擦",
    "做一个单位换算工具，支持长度重量温度",
    "做一个随机名言生成器网页",
    "做一个简单的音乐节拍器",
    "做一个打字速度测试工具",
    "做一个IP地址查询工具的前端界面",
    "做一个简单的日历组件",
    "做一个CSS渐变生成器",
    "做一个简单的投票页面",
    "做一个Emoji搜索工具",
]

PIPELINE_STRESS_TASKS = [
    "做一个能离线使用的记事本网页，支持自动保存到localStorage",
    "做一个Chrome扩展，显示当前页面的字数统计",
    "做一个数据可视化看板，用Canvas画柱状图和饼图",
    "做一个正则表达式测试工具，实时匹配高亮",
    "做一个Markdown转HTML工具，带实时预览",
]

SKILL_GENERATION_TASKS = [
    ("regex_tester", "正则表达式测试工具", ["regex", "正则", "测试"]),
    ("color_tool", "颜色选择和转换工具", ["color", "颜色", "RGB", "HEX"]),
    ("password_gen", "密码生成器", ["password", "密码", "生成"]),
    ("unit_converter", "单位换算工具", ["unit", "单位", "换算", "转换"]),
    ("qr_generator", "二维码生成器", ["qr", "二维码", "生成"]),
]

LOG_DIR = Path(".deepforge/evolution")
LOG_DIR.mkdir(parents=True, exist_ok=True)


class EvolutionEngine:
    def __init__(self, config: DeepForgeConfig):
        self.config = config
        self.client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)
        self.memory = MemoryStore(".deepforge/memory")
        self.skills = SkillRegistry(".deepforge/skills", ".deepforge/community_skills")
        self.stats = {
            "rounds": 0,
            "tests_run": 0,
            "tests_passed": 0,
            "improvements": 0,
            "skills_created": 0,
            "errors_fixed": 0,
            "started_at": time.time(),
        }
        self.log_file = LOG_DIR / f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    def _log(self, event: str, data: dict):
        entry = {"time": datetime.now().isoformat(), "event": event, **data}
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"  [{event}] {json.dumps(data, ensure_ascii=False)[:120]}")

    def _create_orchestrator(self) -> Orchestrator:
        orchestrator = Orchestrator(self.config, max_iterations=2)
        for agent_cls in ALL_AGENTS:
            agent = agent_cls(config=self.config, model_client=self.client)
            if hasattr(agent, 'memory_store'):
                agent.memory_store = self.memory
            if hasattr(agent, 'skill_registry'):
                agent.skill_registry = self.skills
            orchestrator.register(agent)
        return orchestrator

    async def test_code_quality(self, task: str) -> dict:
        """测试工程师Agent能否产出可用代码"""
        agent = EngineerAgent(config=self.config, model_client=self.client)
        context = WorkContext(user_request=task)
        msg = Message(type=MessageType.TASK, sender="architect", receiver="engineer", content=task)
        context.add_message(msg)

        try:
            async for _ in agent.handle(msg, context):
                pass
        except Exception as e:
            return {"passed": False, "error": str(e), "task": task}

        files = context.artifacts.get("code_files", [])
        eng_output = context.artifacts.get("engineer_output", "")

        if not files and not eng_output:
            return {"passed": False, "error": "no output", "task": task}

        html_content = ""
        for f in files:
            p = Path(f)
            if p.exists() and p.suffix == ".html":
                html_content = p.read_text(encoding="utf-8", errors="replace")
                p.unlink(missing_ok=True)
                break

        if not html_content:
            match = re.search(r'(<!DOCTYPE[\s\S]*?</html>)', eng_output, re.IGNORECASE)
            if match:
                html_content = match.group(1)

        if not html_content:
            return {"passed": False, "error": "no html extracted", "task": task, "output_len": len(eng_output)}

        checks = {
            "has_doctype": "<!DOCTYPE" in html_content or "<!doctype" in html_content,
            "has_closing": "</html>" in html_content,
            "has_style": "<style" in html_content,
            "has_script": "<script" in html_content,
            "no_truncation": not html_content.rstrip().endswith("..."),
            "size_ok": 200 < len(html_content) < 50000,
        }

        passed = sum(checks.values()) >= 5
        return {
            "passed": passed,
            "task": task,
            "file_size": len(html_content),
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
        }

    async def test_pipeline(self, task: str) -> dict:
        """测试完整pipeline能否跑通"""
        orchestrator = self._create_orchestrator()
        start = time.time()

        try:
            context = await asyncio.wait_for(
                orchestrator.run_pipeline(task),
                timeout=300,
            )
            duration = time.time() - start
            artifacts = list(context.artifacts.keys())
            msg_count = len(context.conversation_history)
            has_output = bool(context.artifacts.get("engineer_output"))

            return {
                "passed": has_output,
                "task": task,
                "duration": round(duration, 1),
                "artifacts": artifacts,
                "messages": msg_count,
            }
        except asyncio.TimeoutError:
            return {"passed": False, "error": "timeout (300s)", "task": task}
        except Exception as e:
            return {"passed": False, "error": str(e)[:200], "task": task}

    async def evolve_round(self, round_num: int):
        """一轮进化：测试→分析→改进"""
        phase = round_num % 3

        if phase == 0:
            # 代码质量测试
            task = random.choice(CODE_QUALITY_TASKS)
            print(f"\n🔧 代码质量测试: {task}")
            result = await self.test_code_quality(task)
            self.stats["tests_run"] += 1

            if result["passed"]:
                self.stats["tests_passed"] += 1
                self._log("code_test_pass", result)
            else:
                self._log("code_test_fail", result)
                self._record_failure("code_quality", task, result.get("error", "unknown"))

        elif phase == 1:
            # Pipeline稳定性测试
            task = random.choice(PIPELINE_STRESS_TASKS)
            print(f"\n🔄 Pipeline压力测试: {task}")
            result = await self.test_pipeline(task)
            self.stats["tests_run"] += 1

            if result["passed"]:
                self.stats["tests_passed"] += 1
                self._log("pipeline_test_pass", result)
            else:
                self._log("pipeline_test_fail", result)
                self._record_failure("pipeline", task, result.get("error", "unknown"))

        else:
            # Skill模板生成
            if SKILL_GENERATION_TASKS:
                name, desc, tags = random.choice(SKILL_GENERATION_TASKS)
                print(f"\n📦 Skill生成: {name}")
                existing = self.skills.get(name)
                if not existing:
                    from deepforge.skills.registry import Skill
                    skill = Skill(
                        name=name,
                        description=desc,
                        tags=tags,
                        pipeline=["project_manager", "engineer", "reviewer"],
                        prompt_template=f"做一个{desc}" + "，要求：单HTML文件，暗色主题，功能完整",
                        source="evolution",
                    )
                    task = skill.prompt_template
                    result = await self.test_code_quality(task)
                    self.stats["tests_run"] += 1

                    if result["passed"]:
                        self.stats["tests_passed"] += 1
                        self.skills.save_skill(skill)
                        self.stats["skills_created"] += 1
                        self._log("skill_created", {"name": name, "desc": desc})
                    else:
                        self._log("skill_failed", {"name": name, "error": result.get("error", "")})
                else:
                    self._log("skill_exists", {"name": name})

    def _record_failure(self, category: str, task: str, error: str):
        """记录失败到记忆系统，供后续分析"""
        import uuid
        entry = MemoryEntry(
            id=uuid.uuid4().hex[:12],
            category="evolution_failure",
            title=f"[{category}] {task[:50]}",
            content=f"任务: {task}\n错误: {error}\n时间: {datetime.now().isoformat()}",
            tags=[category, "failure", "evolution"],
            source="evolution",
        )
        self.memory.add(entry)

    async def supervisor_review(self):
        """监工Agent审视当前状态并做出决策"""
        supervisor = SupervisorAgent(config=self.config, model_client=self.client)
        context = WorkContext(user_request="监工审查")

        rate = self.stats["tests_passed"] / max(self.stats["tests_run"], 1) * 100
        failures = self.memory.search("failure", category="evolution_failure", limit=5)
        failure_list = [f.title for f in failures]

        context.metadata["evolution_stats"] = {
            "rounds": self.stats["rounds"],
            "tests": self.stats["tests_run"],
            "pass_rate": f"{rate:.0f}%",
            "skills_created": self.stats["skills_created"],
            "hours": round((time.time() - self.stats["started_at"]) / 3600, 1),
        }
        context.metadata["recent_failures"] = failure_list

        msg = Message(
            type=MessageType.TASK,
            sender="system",
            receiver="supervisor",
            content=f"进化引擎已运行{self.stats['rounds']}轮，通过率{rate:.0f}%，请审视并决策下一步。",
        )
        context.add_message(msg)

        print(f"\n👷 监工审查中...")
        async for response in supervisor.handle(msg, context):
            decision = response.content
            self._log("supervisor_decision", {"decision": decision[:300]})
            print(f"  📋 监工决策: {decision[:200]}")
            self.stats["improvements"] += 1

    def print_stats(self):
        elapsed = time.time() - self.stats["started_at"]
        hours = elapsed / 3600
        rate = self.stats["tests_passed"] / max(self.stats["tests_run"], 1) * 100

        print(f"\n{'='*50}")
        print(f"📊 进化统计 (运行 {hours:.1f} 小时)")
        print(f"{'='*50}")
        print(f"  轮次: {self.stats['rounds']}")
        print(f"  测试: {self.stats['tests_run']} 次")
        print(f"  通过: {self.stats['tests_passed']} ({rate:.0f}%)")
        print(f"  Skill: {self.stats['skills_created']} 个新建")
        print(f"  日志: {self.log_file}")
        print(f"{'='*50}\n")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="DeepForge 自进化引擎")
    parser.add_argument("--hours", type=float, default=0, help="运行时长(小时)，0=无限")
    parser.add_argument("--interval", type=int, default=30, help="每轮间隔(秒)")
    args = parser.parse_args()

    # 加载配置
    from deepforge.core.setup_wizard import load_env_file
    load_env_file()

    config = DeepForgeConfig.load()
    if not config.default_model.api_key:
        print("❌ 请先配置API Key")
        sys.exit(1)

    engine = EvolutionEngine(config)
    end_time = time.time() + args.hours * 3600 if args.hours > 0 else float("inf")

    print("╔══════════════════════════════════════════╗")
    print("║  DeepForge 自进化引擎 v1.0               ║")
    print(f"║  模型: {config.default_model.model:<33}║")
    print(f"║  时长: {'无限' if args.hours == 0 else str(args.hours)+'小时':<33}║")
    print(f"║  间隔: {args.interval}秒{' '*29}║")
    print("║  按 Ctrl+C 停止                          ║")
    print("╚══════════════════════════════════════════╝")

    try:
        while time.time() < end_time:
            engine.stats["rounds"] += 1
            round_num = engine.stats["rounds"]
            print(f"\n{'─'*50}")
            print(f"🧬 进化轮次 #{round_num} ({datetime.now().strftime('%H:%M:%S')})")

            try:
                await engine.evolve_round(round_num)
            except Exception as e:
                print(f"  ❌ 轮次异常: {e}")
                engine._log("round_error", {"round": round_num, "error": str(e)[:200]})

            if round_num % 5 == 0:
                engine.print_stats()

            if round_num % 10 == 0:
                try:
                    await engine.supervisor_review()
                except Exception as e:
                    print(f"  ⚠ 监工异常: {e}")

            if time.time() < end_time:
                await asyncio.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n⏹ 进化已停止")

    engine.print_stats()
    print(f"进化日志: {engine.log_file}")


if __name__ == "__main__":
    asyncio.run(main())
