```eval/metrics_config.yaml
metrics:
  - name: attribution_accuracy
    formula: "(df['pred_label'] == df['gold_label']).mean()"
    target: 0.75
    gate: true
    higher_is_better: true
    description: "预测归因标签与人工gold完全一致的比例"

  - name: over_tag_rate
    formula: "( (df['gold_label'] == '无标签') & (df['pred_label'] != '无标签') ).mean()"
    target: 0.10
    gate: true
    higher_is_better: false
    description: "gold无标签但预测有标签的比例"

  - name: under_tag_rate
    formula: "( (df['gold_label'] != '无标签') & (df['pred_label'] == '无标签') ).mean()"
    target: 0.15
    gate: true
    higher_is_better: false
    description: "gold有标签但预测无标签的比例"

  - name: wildcard_rate
    formula: "(df['pred_label'] == '其他/未知').mean()"
    target: 0.20
    gate: false
    higher_is_better: false
    description: "预测为「其他/未知」的比例"

  - name: evidence_completeness
    formula: "(df['evidence'].apply(lambda x: len(x) > 0 and any(e.strip() for e in x) )).mean()"
    target: 0.90
    gate: false
    higher_is_better: true
    description: "预测给出可点击原文片段且能定位的比例"
```

```deepforge_metrics/config.py
"""
配置加载模块：将YAML指标定义转为Pydantic模型
"""
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field


class Metric(BaseModel):
    name: str
    formula: str
    target: float
    gate: bool = False
    higher_is_better: bool = True
    description: str = ""


class Config(BaseModel):
    metrics: List[Metric]


def load_config(path: Path) -> Config:
    """加载YAML配置并校验"""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(**raw)


if __name__ == "__main__":
    # 简单自测
    sample_yaml = Path(__file__).with_name("metrics_config.yaml")
    cfg = load_config(sample_yaml)
    print("Loaded metrics:", [m.name for m in cfg.metrics])
```

```deepforge_metrics/engine.py
"""
评估引擎：基于pandas计算指标
"""
import json
import sys
from pathlib import Path
from typing import List

import pandas as pd

from .config import Config, load_config


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
        higher_is_b_better=metric.higher_is_better,
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
```

```deepforge_metrics/gate.py
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
```

```deepforge_metrics/cli.py
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
```

```scripts/sample_selector.py
"""
从200通对话中随机选100通，写sample_ids.txt
"""
import random
import sys
from pathlib import Path


def select(input_file: Path, output_dir: Path, n: int = 100, seed: int = 42):
    """随机选择n条session_id"""
    random.seed(seed)
    with input_file.open(encoding="utf-8") as f:
        ids = [json.loads(line)["session_id"] for line in f if line.strip()]
    if len(ids) < n:
        raise ValueError(f"总样本数{len(ids)}不足{n}")
    chosen = random.sample(ids, n)
    out = output_dir / "sample_ids.txt"
    with out.open("w", encoding="utf-8") as f:
        for sid in chosen:
            f.write(sid + "\n")
    print(f"✅ 已选{len(chosen)}条，写入{out}")


if __name__ == "__main__":
    import json

    root = Path(__file__).parent.parent
    in_file = root / "eval" / "gold.jsonl"
    if not in_file.exists():
        print("请准备gold.jsonl")
        sys.exit(1)
    select(in_file, root / "eval")
```

```scripts/compare.py
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
@click.argument("pred_a", type=click.Path(exists=True, path_type=Path), help="实验组pred.jsonl")
@click.argument("pred_b", type=click.Path(exists=True, path_type=Path), help="对照组pred.jsonl")
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
```

---

## 依赖安装
```bash
# 建议Python≥3.8
python -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install pandas pydantic click scipy pyyaml
```

## 运行/启动命令
1. 计算指标  
```bash
python -m deepforge_metrics.cli eval eval/gold.jsonl eval/pred.jsonl
```

2. Gate判定  
```bash
python -m deepforge_metrics.cli gate
```

3. 导出CSV  
```bash
python -m deepforge_metrics.cli export-csv eval/metrics.json
```

4. 样本选择  
```bash
python scripts/sample_selector.py
```

5. 两组对比  
```bash
python scripts/compare.py eval/pred.jsonl eval/pred_baseline.jsonl
```

---

## 关键功能说明
- 所有指标公式写在YAML，零硬编码；新增指标只需5行以内。
- Gate失败时进程exit(1)，CI直接阻塞合并。
- compare.py支持McNemar（分类）与配对t（连续值），一键给出p值。

---
### 文件写入结果
[OK] 文件已写入: eval/metrics_config.yaml
[OK] 文件已写入: deepforge_metrics/config.py
[OK] 文件已写入: deepforge_metrics/engine.py
[OK] 文件已写入: deepforge_metrics/gate.py
[OK] 文件已写入: deepforge_metrics/cli.py
[OK] 文件已写入: scripts/sample_selector.py
[OK] 文件已写入: scripts/compare.py