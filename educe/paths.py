"""
educe 运行时路径定义 — 单一来源，全局引用此文件

所有运行时目录通过这里的函数获取，避免硬编码路径散落各处。
启动时自动检测旧 .deepforge/ 目录并迁移。
"""
import logging
import shutil
from pathlib import Path

RUNTIME_DIR_NAME = ".educe"
OLD_DIR_NAME = ".deepforge"
CONFIG_FILE_NAME = "educe.yaml"
OLD_CONFIG_NAME = "deepforge.yaml"

log = logging.getLogger("educe.paths")

_migrated = False


def _migrate_if_needed(base: Path) -> None:
    """一次性迁移：.deepforge/ → .educe/（启动时自动执行）"""
    global _migrated
    if _migrated:
        return
    _migrated = True

    old_dir = base / OLD_DIR_NAME
    new_dir = base / RUNTIME_DIR_NAME

    if not old_dir.exists():
        return

    if new_dir.exists() and any(new_dir.iterdir()):
        # 新目录已有内容，合并旧目录中新目录没有的子目录
        for item in old_dir.iterdir():
            if item.name.startswith("."):
                continue
            target = new_dir / item.name
            if not target.exists():
                try:
                    shutil.move(str(item), str(target))
                    log.info("Migrated %s → %s", item.name, target)
                except Exception as e:
                    log.warning("Migration failed for %s: %s", item.name, e)
    else:
        # 新目录不存在或为空，整体迁移
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        if new_dir.exists():
            shutil.rmtree(str(new_dir))
        try:
            shutil.move(str(old_dir), str(new_dir))
            log.info("Migrated .deepforge/ → .educe/ (full move)")
        except Exception as e:
            log.warning("Full migration failed: %s", e)
            return

    # 重命名旧配置文件
    old_config = new_dir / OLD_CONFIG_NAME
    new_config = new_dir / CONFIG_FILE_NAME
    if old_config.exists() and not new_config.exists():
        old_config.rename(new_config)
        log.info("Renamed %s → %s", OLD_CONFIG_NAME, CONFIG_FILE_NAME)

    # 留软链接兼容旧路径引用
    if not old_dir.exists():
        try:
            old_dir.symlink_to(new_dir)
            log.info("Created symlink .deepforge → .educe")
        except OSError:
            pass


def runtime_dir(base: Path | None = None) -> Path:
    """运行时根目录（项目级 .educe/）"""
    root = base or Path.cwd()
    _migrate_if_needed(root)
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
