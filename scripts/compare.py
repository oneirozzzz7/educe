"""
对比两组pred结果，做统计检验
"""
import json
import sys
from pathlib import Path

import click
import pandas as pd
from scipy.stats import mcnemar, ttest_rel


@click.command()
@click.argument("pred_a", type=click.Path(exists=True, path_type=Path))
@click.argument("pred_b", type=click.Path(exists=True, path_type=Path))
@click.option("--metric", type=click.Choice(["accuracy", "token"]), default="accuracy", help="检验指标")
def main(pred_a: Path, pred_b: Path, metric: str):
    """配对样本检验：accuracy用McNemar，token用配对t"""
    df_a = pd.read_json(pred_a, lines=True)
    df_b = pd.read_json(pred_b, lines=True)
    merged = pd.merge(df_a, df_b, on="session_id", suffixes=("_a", "_b"))
    if metric == "accuracy":
        # 构建列联表
        correct_a = (merged["pred_label_a"] == merged["gold_label"]).astype(int)
        correct_b = (merged["pred_label_b"] == merged["gold_label"]).astype(int)
        table = pd.crosstab(correct_a, correct_b)
        if table.shape != (2, 2):
            print("无法构建2x2表，跳过McNemar")
            sys.exit(1)
        stat, p = mcnemar(table, exact=False)
        print(f"McNemar检验: stat={stat:.3f}, p={p:.3f}")
    else:
        # token列需存在
        if "token" not in merged.columns:
            print("缺少token字段")
            sys.exit(1)
        stat, p = ttest_rel(merged["token_a"], merged["token_b"])
        print(f"配对t检验: t={stat:.3f}, p={p:.3f}")


if __name__ == "__main__":
    main()