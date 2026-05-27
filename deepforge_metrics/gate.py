"""
Gate判定：任一Gate指标未通过→exit(1)
"""
import json
import sys
from pathlib import Path

from .engine import MetricResult


def run_gate(metrics_json: Path) -> None:
    if not metrics_json.exists():
        print(f"[Gate] 文件不存在: {metrics_json}", file=sys.stderr)
        sys.exit(2)

    with metrics_json.open(encoding="utf-8") as f:
        data = json.load(f)

    results = [MetricResult(**r) for r in data["results"]]
    fails = [r for r in results if r.gate and not r.pass_gate]

    if fails:
        print("[Gate] 以下指标未达标:", file=sys.stderr)
        for r in fails:
            print(f"  - {r.name}: {r.value:.3f} (target={r.target})", file=sys.stderr)
        sys.exit(1)
    print("[Gate] 全部通过")
    sys.exit(0)


if __name__ == "__main__":
    # 默认读eval/metrics.json
    default_file = Path(__file__).parent.parent / "eval" / "metrics.json"
    run_gate(default_file)