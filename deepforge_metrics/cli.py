"""
CLI入口：click实现
"""
import json
from pathlib import Path

import click

from .engine import evaluate as do_eval, write_metrics
from .gate import run_gate as do_gate


@click.group()
def main():
    """DeepForge归因实验评估工具"""
    pass


@main.command()
@click.argument("gold", type=click.Path(exists=True, path_type=Path))
@click.argument("pred", type=click.Path(exists=True, path_type=Path))
@click.option("--config", "-c", type=click.Path(exists=True, path_type=Path), default=Path("eval/metrics_config.yaml"))
@click.option("--out", "-o", type=click.Path(path_type=Path), default=Path("eval/metrics.json"))
def eval(gold: Path, pred: Path, config: Path, out: Path):
    """计算指标并写metrics.json"""
    results = do_eval(gold, pred, config)
    write_metrics(results, out)
    click.echo(f"✅ 已写入 {out}")


@main.command()
@click.option("--metrics", "-m", type=click.Path(exists=True, path_type=Path), default=Path("eval/metrics.json"))
def gate(metrics: Path):
    """Gate判定"""
    do_gate(metrics)


@main.command()
@click.argument("metrics_json", type=click.Path(exists=True, path_type=Path))
@click.option("--out", "-o", type=click.Path(path_type=Path), default=Path("eval/report.csv"))
def export_csv(metrics_json: Path, out: Path):
    """导出CSV（含每条样本明细）"""
    import pandas as pd

    with metrics_json.open() as f:
        data = json.load(f)

    # 这里简化：实际可合并原始df
    df = pd.json_normalize(data["results"])
    df.to_csv(out, index=False)
    click.echo(f"✅ 已导出 {out}")


if __name__ == "__main__":
    main()