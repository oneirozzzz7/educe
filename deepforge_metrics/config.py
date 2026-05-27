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