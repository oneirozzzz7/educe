"""
评估引擎：基于pandas计算指标
"""
import json
import sys
from pathlib import Path
from typing import List

import pandas as pd

from pydantic import BaseModel

from .config import Config, Metric, load_config


class MetricResult(BaseModel):
    name: str
    value: float
    pass_gate: bool
    gate: bool
    target: float
    higher_is_better: bool
    description: str = ""


def _compute_single_metric(df: pd.DataFrame, metric: Metric) -> MetricResult:
    """计算单个指标"""
    try:
        value = float(eval(metric.formula, {"df": df, "pd": pd}))
    except Exception as exc:
        raise RuntimeError(f"Error evaluating {metric.name}: {exc}") from exc

    if metric.higher_is_better:
        pass_gate = value >= metric.target
    else:
        pass_gate = value <= metric.target

    return MetricResult(
        name=metric.name,
        value=value,
        pass_gate=pass_gate,
        gate=metric.gate,
        target=metric.target,
        higher_is_better=metric.higher_is_better,
        description=metric.description,
    )


def evaluate(gold_path: Path, pred_path: Path, config_path: Path) -> List[MetricResult]:
    """主评估入口"""
    cfg: Config = load_config(config_path)
    gold_df = pd.read_json(gold_path, lines=True)
    pred_df = pd.read_json(pred_path, lines=True)

    if len(gold_df) != len(pred_df):
        raise ValueError("gold与pred样本数不一致")
    if set(gold_df.columns) < {"session_id", "gold_label"} or set(pred_df.columns) < {"session_id", "pred_label"}:
        raise ValueError("缺少必要字段")

    # 按session_id对齐
    merged = pd.merge(
        gold_df.rename(columns={"label": "gold_label"}),
        pred_df.rename(columns={"label": "pred_label"}),
        on="session_id",
        how="inner",
    )
    if len(merged) != len(gold_df):
        raise ValueError("session_id对齐失败，请检查数据")

    results: List[MetricResult] = []
    for m in cfg.metrics:
        results.append(_compute_single_metric(merged, m))
    return results


def write_metrics(results: List[MetricResult], out_path: Path) -> None:
    """写metrics.json"""
    payload = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "results": [r.dict() for r in results],
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # 本地快速自测
    root = Path(__file__).parent.parent
    gold = root / "eval" / "gold.jsonl"
    pred = root / "eval" / "pred.jsonl"
    cfg = root / "eval" / "metrics_config.yaml"
    out = root / "eval" / "metrics.json"

    if not gold.exists() or not pred.exists():
        print("缺少测试数据，跳过")
        sys.exit(0)

    res = evaluate(gold, pred, cfg)
    write_metrics(res, out)
    print("metrics.json已生成", out)