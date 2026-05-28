"""
DeepForge 进化核心——纯函数式，不依赖Orchestrator
用户每次任务完成后在后台静默运行
"""
from __future__ import annotations

import re
import json
import time
from pathlib import Path
from datetime import datetime

from deepforge.core.knowledge import LayeredCache

LOG_DIR = Path(".deepforge/evolution")


def evolve_from_output(engineer_output: str, user_request: str,
                       knowledge: LayeredCache) -> dict:
    """从一次任务的产出物中提取经验，写入知识库

    Args:
        engineer_output: Builder产出的代码内容
        user_request: 用户原始请求
        knowledge: 知识库实例（本地的）

    Returns:
        进化结果摘要
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    result = _detect(engineer_output)
    result["task"] = user_request[:80]

    diagnosis = _diagnose(result)

    fix_result = None
    if diagnosis["category"] != "all_good":
        fix_result = _fix(diagnosis, knowledge)

    if diagnosis["category"] == "all_good" or result.get("passed"):
        _deposit_success(user_request, result, knowledge)

    if knowledge.stats()["total"] > 1000:
        knowledge.prune(max_entries=800)
        knowledge.merge_duplicates()

    _log_event("evolve", {
        "task": user_request[:60],
        "passed": result.get("passed", False),
        "score": f"{result.get('checks_passed', 0)}/{result.get('checks_total', 0)}",
        "diagnosis": diagnosis["category"],
        "fix": fix_result.get("action") if fix_result else None,
    })

    return {
        "passed": result.get("passed", False),
        "diagnosis": diagnosis["category"],
        "fix": fix_result,
    }


def _detect(engineer_output: str) -> dict:
    """多维度检测产出物质量"""
    if not engineer_output or len(engineer_output) < 50:
        return {"passed": False, "checks": {"has_file": False}, "checks_passed": 0, "checks_total": 1}

    has_output = bool(re.search(r'<!DOCTYPE|```filepath:', engineer_output, re.I))
    checks = {}

    if has_output:
        checks["has_file"] = True
        checks["has_doctype"] = bool(re.search(r'<!DOCTYPE', engineer_output, re.I))
        checks["has_closing"] = "</html>" in engineer_output
        checks["has_css_vars"] = len(re.findall(r'--[\w-]+:', engineer_output)) >= 3
        checks["has_animation"] = "@keyframes" in engineer_output
        checks["has_responsive"] = "@media" in engineer_output
        checks["has_error_handling"] = "try" in engineer_output or "catch" in engineer_output
        checks["size_ok"] = 5000 < len(engineer_output) < 50000
    else:
        checks["has_file"] = False

    passed = checks.get("has_file", False) and checks.get("has_closing", False)

    return {
        "passed": passed,
        "output_size": len(engineer_output),
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
    }


def _diagnose(result: dict) -> dict:
    """规则引擎诊断"""
    if result.get("passed"):
        checks = result.get("checks", {})
        gaps = [k for k, v in checks.items() if not v]
        if gaps:
            return {"category": "quality_gap", "gaps": gaps, "severity": "low"}
        return {"category": "all_good", "severity": "none"}

    checks = result.get("checks", {})

    if not checks.get("has_file", False):
        return {"category": "no_output", "severity": "critical"}

    if not checks.get("has_closing", False):
        return {"category": "truncated", "severity": "high"}

    return {"category": "unknown", "severity": "medium"}


def _fix(diagnosis: dict, knowledge: LayeredCache) -> dict | None:
    """往知识库追加经验——只追加不修改"""
    category = diagnosis.get("category")

    if category == "quality_gap":
        gaps = diagnosis.get("gaps", [])
        added = 0
        gap_knowledge = {
            "has_css_vars": ("CSS必须使用:root变量系统(--primary, --bg, --text等)", {"css", "变量", "root", "颜色"}),
            "has_animation": ("CSS必须包含@keyframes动画(loading/pulse/fadeIn等至少1个)", {"css", "动画", "animation", "keyframes"}),
            "has_responsive": ("必须有@media响应式查询适配移动端", {"响应式", "media", "移动端", "responsive"}),
            "has_error_handling": ("JS必须有try/catch错误处理", {"错误", "error", "try", "catch"}),
        }
        for gap in gaps:
            if gap in gap_knowledge:
                content, triggers = gap_knowledge[gap]
                knowledge.add(content, triggers, "pattern")
                added += 1
        return {"action": "knowledge_added", "count": added}

    elif category == "no_output":
        knowledge.add(
            "Builder必须输出```filepath:文件名格式的完整代码，禁止输出描述文字",
            {"builder", "输出", "格式", "代码", "文件"}, "lesson",
        )
        return {"action": "lesson_added", "topic": "output_format"}

    elif category == "truncated":
        knowledge.add(
            "HTML文件必须有</html>闭合标签，如果被截断需要续写补全",
            {"html", "截断", "闭合", "truncated"}, "lesson",
        )
        return {"action": "lesson_added", "topic": "truncation"}

    return None


def _deposit_success(user_request: str, result: dict, knowledge: LayeredCache):
    """成功经验编译进L1"""
    score = result.get("checks_passed", 0)
    total = result.get("checks_total", 0)
    tokens = knowledge._tokenize(user_request)
    knowledge.add(f"[成功] {user_request[:60]} → {score}/{total}分", tokens, "success")
    knowledge._compile_l1()


def _log_event(event: str, data: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"evo_{datetime.now().strftime('%Y%m%d')}.jsonl"
    entry = {"time": datetime.now().isoformat(), "event": event, **data}
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
