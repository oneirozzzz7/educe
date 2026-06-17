"""
educe 运行时路径定义 — 单一来源，全局引用此文件

所有运行时目录通过这里的函数获取，避免硬编码路径散落各处。
"""
from pathlib import Path

RUNTIME_DIR_NAME = ".educe"
CONFIG_FILE_NAME = "educe.yaml"


def runtime_dir(base: Path | None = None) -> Path:
    """运行时根目录（项目级 .educe/）"""
    root = base or Path.cwd()
    return root / RUNTIME_DIR_NAME


def output_dir(session_id: str, base: Path | None = None) -> Path:
    """session 构建产出目录"""
    return runtime_dir(base) / "output" / session_id[:16]


def convergence_dir(base: Path | None = None) -> Path:
    return runtime_dir(base) / "convergence"


def convergence_path(session_id: str, base: Path | None = None) -> Path:
    return convergence_dir(base) / f"{session_id[:16]}.jsonl"


def logs_dir(base: Path | None = None) -> Path:
    return runtime_dir(base) / "logs"


def config_path(base: Path | None = None) -> Path:
    return runtime_dir(base) / CONFIG_FILE_NAME
