#!/usr/bin/env python3
"""The Descent Curve — one command to prove that Educe learns.

Usage:
    EDUCE_BASE_URL=http://api.example.com/v1 \
    EDUCE_API_KEY=pk-xxx \
    EDUCE_MODEL=Qwen3-235B-A22B \
    python reproduce_descent.py

Output:
    .educe/descent/descent_curve.png
    .educe/descent/statistics.json
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from educe.core.longitudinal_runner import LongitudinalRunner, TaskFamily, RunResult

# ═══ Configuration ═══

API_KEY = os.environ.get("EDUCE_API_KEY", "")
BASE_URL = os.environ.get("EDUCE_BASE_URL", "")
MODEL = os.environ.get("EDUCE_MODEL", "Qwen3-235B-A22B")
N_RUNS = int(os.environ.get("EDUCE_DESCENT_RUNS", "15"))

if not API_KEY or not BASE_URL:
    print("Error: set EDUCE_BASE_URL and EDUCE_API_KEY environment variables.")
    sys.exit(1)


# ═══ Acceptance Checks ═══

def check_mortgage(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """FIN: 月供 ≈ 13464~13490"""
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    normalized = re.sub(r'[\s,.\-]', '', reply_text)
    for target in range(13460, 13490):
        if str(target) in normalized:
            return True, 1.0, f"月供 {target} 正确"
    if "1347" in normalized:
        return True, 0.8, "月供约 13470 范围内"
    return False, 0.0, "未找到正确月供金额"


def check_env_setup(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """TECH: 检查 Python 环境信息（需要多步 shell）— 严格版"""
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    score = 0.0
    # 必须有具体版本号
    if re.search(r'3\.\d+\.\d+', reply_text):
        score += 0.25
    # 必须有具体包数量（数字）
    if re.search(r'\d+\s*(个|packages|个包|installed)', reply_text):
        score += 0.25
    # 必须有具体路径（含 / 或 \\）
    if re.search(r'(/[^\s]+python|/[^\s]+site-packages)', reply_text):
        score += 0.25
    # 必须有 site-packages 具体位置
    if re.search(r'site-packages', reply_text):
        score += 0.25
    return score >= 0.75, min(score, 1.0), f"score={score:.1f}"


def check_sysinfo(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """Shell 多步型：需要运行多个命令收集系统信息"""
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    score = 0.0
    # 需要有内存信息
    if re.search(r'\d+\s*(GB|MB|G|M|bytes)', reply_text):
        score += 0.4
    # 需要有磁盘信息
    if re.search(r'\d+%|disk|磁盘|容量', reply_text, re.IGNORECASE):
        score += 0.3
    # 需要有 CPU 信息
    if re.search(r'cpu|核|core|processor', reply_text, re.IGNORECASE):
        score += 0.3
    return score >= 0.6, min(score, 1.0), f"score={score:.1f}"



def check_git_report(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """Git 多步型：需要多个 git 命令收集仓库信息"""
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    score = 0.0
    if re.search(r'\d+\s*(commit|提交)', reply_text, re.IGNORECASE):
        score += 0.25
    if re.search(r'(branch|分支|main|master)', reply_text, re.IGNORECASE):
        score += 0.25
    if re.search(r'(author|contributor|贡献|作者)', reply_text, re.IGNORECASE):
        score += 0.25
    if re.search(r'(\d+\s*(file|文件)|\.py|\.ts)', reply_text, re.IGNORECASE):
        score += 0.25
    return score >= 0.75, min(score, 1.0), f"score={score:.1f}"


def check_network_report(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """网络诊断：需要多步 ping/curl/ifconfig"""
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    score = 0.0
    if re.search(r'(\d+\.\d+\.\d+\.\d+|localhost|127\.0)', reply_text):
        score += 0.3
    if re.search(r'(ping|延迟|latency|ms|time=)', reply_text, re.IGNORECASE):
        score += 0.3
    if re.search(r'(port|端口|listen|ESTABLISHED)', reply_text, re.IGNORECASE):
        score += 0.2
    if re.search(r'(interface|en0|eth|lo0|网卡)', reply_text, re.IGNORECASE):
        score += 0.2
    return score >= 0.6, min(score, 1.0), f"score={score:.1f}"


def check_project_scaffold(result: RunResult, workspace: Path) -> tuple[bool, float, str]:
    """项目脚手架：需要创建多文件+运行验证"""
    score = 0.0
    if (workspace / "main.py").exists() or (workspace / "app.py").exists():
        score += 0.3
    if (workspace / "requirements.txt").exists() or (workspace / "pyproject.toml").exists():
        score += 0.2
    if (workspace / "README.md").exists():
        score += 0.2
    py_files = list(workspace.glob("*.py"))
    if len(py_files) >= 2:
        score += 0.15
    reply_file = workspace.parent / "reply.txt"
    reply_text = reply_file.read_text(encoding="utf-8") if reply_file.exists() else ""
    if re.search(r'(创建|created|wrote|写入)', reply_text, re.IGNORECASE):
        score += 0.15
    return score >= 0.7, min(score, 1.0), f"score={score:.1f}"


# ═══ Task Families ═══

TASK_FAMILIES = [
    # --- Experiment group (multi-step, has descent space) ---
    TaskFamily(
        family_id="sysinfo_report",
        instruction="查下这台机器的 CPU 型号、内存总量、磁盘剩余空间，整理成一份简报",
        acceptance_check=check_sysinfo,
    ),
    TaskFamily(
        family_id="git_repo_report",
        instruction="分析当前 git 仓库：总提交数、分支数、主要贡献者、最近一次提交内容、项目文件构成（.py/.ts/.md各多少），整理成简报",
        acceptance_check=check_git_report,
    ),
    TaskFamily(
        family_id="network_diagnostic",
        instruction="做一次网络诊断：本机 IP 地址、能否 ping 通 baidu.com（延迟多少）、当前监听的端口有哪些、网卡信息，整理成报告",
        acceptance_check=check_network_report,
    ),
    # --- Control group (already optimal, expect flat) ---
    TaskFamily(
        family_id="env_python_info",
        instruction="查下当前 Python 环境：版本号、pip 已安装的包数量、python 可执行文件路径、site-packages 位置，整理汇报",
        acceptance_check=check_env_setup,
    ),
    TaskFamily(
        family_id="fin_mortgage",
        instruction="帮我算下这笔房贷：300万，30年，利率3.5%，等额本息，月供多少",
        acceptance_check=check_mortgage,
    ),
]


# ═══ Main ═══

async def run_experiment():
    all_results = {}

    for family in TASK_FAMILIES:
        print(f"\n{'━'*60}")
        print(f"  Task Family: {family.family_id}")
        print(f"{'━'*60}")

        runner = LongitudinalRunner(
            task_family=family,
            n_runs=N_RUNS,
            model_name=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
        )
        results = await runner.run_all()
        all_results[family.family_id] = results

    return all_results


def analyze_and_plot(all_results: dict[str, list[RunResult]]):
    """Analyze results and generate charts."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from scipy.stats import spearmanr
    except ImportError:
        print("\nInstall matplotlib and scipy for plotting: pip install matplotlib scipy")
        print("Skipping plot generation, saving raw statistics only.")
        _save_statistics(all_results, None)
        return

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    fig.suptitle("The Descent Curve — Educe Learning Verification", fontsize=14)

    stats = {}
    colors = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#64748b']

    for idx, (family_id, runs) in enumerate(all_results.items()):
        run_indices = list(range(len(runs)))
        tokens = [r.total_tokens for r in runs]
        scores = [r.score for r in runs]

        # Normalize tokens (relative to first run)
        baseline = tokens[0] if tokens[0] > 0 else 1
        normalized = [t / baseline for t in tokens]

        # Plot cost curve
        axes[0].plot(run_indices, normalized, marker='o', label=family_id,
                     color=colors[idx], linewidth=2, markersize=4)

        # Plot correctness
        axes[1].plot(run_indices, scores, marker='s', label=family_id,
                     color=colors[idx], linewidth=2, markersize=4)

        # Statistics
        rho, pval = spearmanr(run_indices, tokens) if len(tokens) > 3 else (0, 1)
        first_3_mean = sum(tokens[:3]) / max(len(tokens[:3]), 1)
        last_3_mean = sum(tokens[-3:]) / max(len(tokens[-3:]), 1)
        convergence = last_3_mean / first_3_mean if first_3_mean > 0 else 1.0
        fidelity = min(scores[-5:]) if len(scores) >= 5 else min(scores) if scores else 0

        stats[family_id] = {
            "spearman_rho": round(rho, 4),
            "spearman_p": round(pval, 4),
            "convergence_ratio": round(convergence, 4),
            "fidelity_floor": round(fidelity, 4),
            "first_3_tokens_mean": round(first_3_mean),
            "last_3_tokens_mean": round(last_3_mean),
            "total_runs": len(runs),
            "correct_count": sum(1 for r in runs if r.correct),
        }

    axes[0].set_ylabel("Normalized Cost (tokens / baseline)")
    axes[0].set_title("Cost should decrease with experience")
    axes[0].legend()
    axes[0].axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    axes[0].set_ylim(bottom=0)

    axes[1].set_xlabel("Run Number")
    axes[1].set_ylabel("Correctness Score")
    axes[1].set_title("Correctness should stay high")
    axes[1].legend()
    axes[1].set_ylim(-0.1, 1.1)

    plt.tight_layout()

    output_dir = Path(".educe/descent")
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = output_dir / "descent_curve.png"
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    print(f"\n  Chart saved: {chart_path}")

    _save_statistics(all_results, stats)


def _save_statistics(all_results, stats):
    output_dir = Path(".educe/descent")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute basic stats even without scipy
    if stats is None:
        stats = {}
        for family_id, runs in all_results.items():
            tokens = [r.total_tokens for r in runs]
            scores = [r.score for r in runs]
            first_3 = sum(tokens[:3]) / max(len(tokens[:3]), 1)
            last_3 = sum(tokens[-3:]) / max(len(tokens[-3:]), 1)
            stats[family_id] = {
                "convergence_ratio": round(last_3 / first_3, 4) if first_3 > 0 else None,
                "total_runs": len(runs),
                "correct_count": sum(1 for r in runs if r.correct),
                "first_3_tokens_mean": round(first_3),
                "last_3_tokens_mean": round(last_3),
            }

    stats_path = output_dir / "statistics.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"  Statistics saved: {stats_path}")

    # Print summary
    print(f"\n{'='*60}")
    print("  THE DESCENT CURVE — RESULTS")
    print(f"{'='*60}")
    for fid, s in stats.items():
        rho = s.get("spearman_rho", "N/A")
        conv = s.get("convergence_ratio", "N/A")
        fid_floor = s.get("fidelity_floor", "N/A")
        correct = s.get("correct_count", 0)
        total = s.get("total_runs", 0)
        print(f"\n  {fid}:")
        print(f"    Spearman ρ = {rho} (want < -0.5)")
        print(f"    Convergence = {conv} (want < 0.5)")
        print(f"    Fidelity floor = {fid_floor} (want >= 0.7)")
        print(f"    Correctness = {correct}/{total}")

    # Overall verdict
    control_families = {"fin_mortgage", "env_python_info"}
    experiment_families = [k for k in stats if k not in control_families]
    pass_count = sum(1 for k in experiment_families
                     if isinstance(stats[k].get("spearman_rho"), (int, float))
                     and stats[k]["spearman_rho"] < -0.5)
    total_exp = len(experiment_families)
    print(f"\n  {'✅ PASS' if pass_count >= 2 else '❌ FAIL'}: "
          f"{pass_count}/{total_exp} experiment families show significant descent")
    for ctrl_name in control_families:
        if ctrl_name in stats:
            ctrl = stats[ctrl_name]
            ctrl_rho = ctrl.get("spearman_rho", 0)
            ctrl_ok = abs(ctrl_rho) < 0.5 if isinstance(ctrl_rho, (int, float)) else True
            print(f"  {'✅' if ctrl_ok else '⚠️'} Control ({ctrl_name}): ρ={ctrl_rho} "
                  f"(expect flat, |ρ|<0.5)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    results = asyncio.run(run_experiment())
    analyze_and_plot(results)
