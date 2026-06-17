"""快速验证 benchmark runner — 3 个 L1 case (Kimi-K2)"""
import asyncio
import sys
sys.path.insert(0, ".")

from pathlib import Path
from educe.core.benchmark_runner import BenchmarkRunner, BenchmarkCase, CaseResult


# === 验收检查函数 ===

def check_calculation(result: CaseResult, workspace: Path) -> tuple[bool, float, str]:
    """验证计算结果包含 56088"""
    import re
    for evt in result.events:
        if evt.get("name") == "model_output":
            preview = evt.get("data", {}).get("reply_preview", "")
            # Normalize all whitespace/separator chars for matching
            normalized = re.sub(r'[\s  ,.]', '', preview)
            if "56088" in normalized:
                return True, 1.0, f"正确答案 56088 (raw: {preview[:40]})"
    for evt in result.events:
        summary = re.sub(r'[\s  ,.]', '', evt.get("summary", ""))
        if "56088" in summary:
            return True, 1.0, "正确答案 56088 (in summary)"
    return False, 0.0, "未找到正确答案 56088"


def check_system_info(result: CaseResult, workspace: Path) -> tuple[bool, float, str]:
    """验证执行了目录读取或系统命令"""
    for evt in result.events:
        if evt.get("type") == "tool_call":
            action_type = evt.get("data", {}).get("action_type", "")
            if action_type in ("shell", "read_dir", "read_file"):
                return True, 1.0, f"执行了 {action_type}"
    return False, 0.0, "未执行任何读取/命令操作"


def check_file_created(result: CaseResult, workspace: Path) -> tuple[bool, float, str]:
    """验证 workspace 中创建了文件"""
    files = list(workspace.rglob("*"))
    created = [f for f in files if f.is_file()]
    if created:
        return True, 1.0, f"创建了 {len(created)} 个文件: {[f.name for f in created[:3]]}"
    return False, 0.0, "未创建任何文件"


# === Case 定义 ===

QUICK_CASES = [
    BenchmarkCase(
        case_id="QUICK-01",
        level="L1",
        domain="CALC",
        instruction="帮我算下 123 * 456 等于多少",
        acceptance_checks=[check_calculation],
    ),
    BenchmarkCase(
        case_id="QUICK-02",
        level="L1",
        domain="TECH",
        instruction="查下当前目录有哪些文件",
        acceptance_checks=[check_system_info],
    ),
    BenchmarkCase(
        case_id="QUICK-03",
        level="L1",
        domain="LIFE",
        instruction="帮我写一个简单的 Python hello world 脚本，保存到 hello.py",
        acceptance_checks=[check_file_created],
    ),
]


async def main():
    import os
    runner = BenchmarkRunner(
        cases=QUICK_CASES,
        model_name=os.environ.get("BENCH_MODEL", "Kimi-K2"),
        api_key=os.environ.get("BENCH_API_KEY", os.environ.get("DEEPFORGE_API_KEY", "")),
        base_url=os.environ.get("BENCH_BASE_URL", "http://api.example.com/v1"),
        timeout_s=90.0,
    )
    results = await runner.run_all()

    # Print acceptance results
    print("\n=== Acceptance ===")
    for r in results:
        acc = r.acceptance.get("score", "N/A")
        print(f"  {r.case_id}: status={r.status}, acceptance={acc}, rounds={r.metrics.get('total_rounds', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
