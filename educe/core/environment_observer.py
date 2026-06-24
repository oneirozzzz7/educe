"""Environment Observer — 独立观测工具执行的环境副作用

不信任工具的返回值。框架自己去 stat/hash 文件，记录事实。
"""

import hashlib
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FsObservation:
    path: str
    existed_before: bool
    exists_after: bool
    size_before: Optional[int] = None
    size_after: Optional[int] = None
    hash_after: Optional[str] = None
    mtime_after: Optional[float] = None
    delta: str = "unchanged"  # created | modified | deleted | unchanged | noop


@dataclass
class Artifact:
    artifact_id: str
    path: str
    filename: str
    mime: str
    size: int
    hash: str
    created_by: str  # tool_call identifier
    preview_kind: str  # text | code | image | binary
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "filename": self.filename,
            "mime": self.mime,
            "size": self.size,
            "preview_kind": self.preview_kind,
            "download_url": f"/api/artifacts/{self.artifact_id}",
        }


class EnvironmentObserver:
    """观测工具执行前后的环境变化。"""

    def __init__(self, workdir: Optional[Path] = None):
        self.workdir = workdir or Path.cwd()
        self._artifacts: dict[str, Artifact] = {}
        self._observations: list[FsObservation] = []
        self._counter = 0

    def snapshot_path(self, path: Path) -> dict:
        """对单个路径做快照。"""
        if path.exists():
            stat = path.stat()
            return {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime}
        return {"exists": False, "size": None, "mtime": None}

    def observe_write(self, target_path: str, before: dict, tool_result: dict) -> FsObservation:
        """观测 write_file 执行后的环境变化。"""
        path = Path(target_path).expanduser()
        if not path.is_absolute():
            path = self.workdir / path

        after = self.snapshot_path(path)

        obs = FsObservation(
            path=str(path),
            existed_before=before["exists"],
            exists_after=after["exists"],
            size_before=before["size"],
            size_after=after["size"],
            mtime_after=after.get("mtime"),
        )

        if not before["exists"] and after["exists"]:
            obs.delta = "created"
        elif before["exists"] and after["exists"] and before["size"] != after["size"]:
            obs.delta = "modified"
        elif before["exists"] and not after["exists"]:
            obs.delta = "deleted"
        elif not after["exists"]:
            obs.delta = "noop"

        if after["exists"]:
            try:
                content = path.read_bytes()[:8192]
                obs.hash_after = hashlib.md5(content).hexdigest()[:12]
            except Exception:
                pass

        self._observations.append(obs)

        # 如果文件确实被创建/修改，登记为 artifact
        if obs.delta in ("created", "modified") and after["exists"]:
            self._register_artifact(path, "write_file")

        return obs

    def observe_shell(self, cmd: str, stdout: str, exit_code: int) -> dict:
        """观测 shell 执行后的结果 + 工作目录变化。"""
        result = {
            "cmd": cmd[:200],
            "exit_code": exit_code,
            "stdout_len": len(stdout),
            "stdout_preview": stdout[:500] if stdout else "",
            "fs_changes": [],
        }
        return result

    def snapshot_workdir(self) -> dict[str, float]:
        """对工作目录做浅层快照（文件名→mtime），用于前后比对。"""
        snap = {}
        try:
            for entry in self.workdir.iterdir():
                if entry.name.startswith("."):
                    continue
                if entry.is_file():
                    snap[str(entry)] = entry.stat().st_mtime
        except Exception:
            pass
        return snap

    def diff_workdir(self, before: dict[str, float], after: dict[str, float]) -> list[FsObservation]:
        """比对工作目录快照，返回变化的文件列表。"""
        changes = []
        for path, mtime in after.items():
            if path not in before:
                obs = FsObservation(
                    path=path, existed_before=False, exists_after=True,
                    size_after=Path(path).stat().st_size if Path(path).exists() else 0,
                    delta="created")
                changes.append(obs)
                self._observations.append(obs)
                self._register_artifact(Path(path), "shell")
            elif mtime != before[path]:
                obs = FsObservation(
                    path=path, existed_before=True, exists_after=True,
                    size_before=None, size_after=Path(path).stat().st_size if Path(path).exists() else 0,
                    delta="modified")
                changes.append(obs)
                self._observations.append(obs)
                self._register_artifact(Path(path), "shell")

        for path in before:
            if path not in after:
                obs = FsObservation(
                    path=path, existed_before=True, exists_after=False, delta="deleted")
                changes.append(obs)
                self._observations.append(obs)

        return changes

    def _register_artifact(self, path: Path, created_by: str) -> Artifact:
        """登记一个文件产物。"""
        import mimetypes
        self._counter += 1
        artifact_id = f"art_{self._counter:04d}"

        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size

        ext = path.suffix.lower()
        if ext in (".py", ".js", ".ts", ".sh", ".yaml", ".yml", ".json", ".toml", ".css", ".html"):
            preview_kind = "code"
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            preview_kind = "image"
        elif ext in (".txt", ".md", ".csv", ".log"):
            preview_kind = "text"
        else:
            preview_kind = "binary"

        content_hash = ""
        try:
            content_hash = hashlib.md5(path.read_bytes()[:8192]).hexdigest()[:12]
        except Exception:
            pass

        artifact = Artifact(
            artifact_id=artifact_id,
            path=str(path),
            filename=path.name,
            mime=mime,
            size=size,
            hash=content_hash,
            created_by=created_by,
            preview_kind=preview_kind,
        )
        self._artifacts[artifact_id] = artifact
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        return self._artifacts.get(artifact_id)

    @property
    def artifacts(self) -> list[Artifact]:
        return list(self._artifacts.values())

    @property
    def observations(self) -> list[FsObservation]:
        return self._observations

    def recent_artifacts(self, n: int = 5) -> list[dict]:
        """最近 N 个 artifact 的字典表示（给前端推送用）。"""
        return [a.to_dict() for a in list(self._artifacts.values())[-n:]]

    def build_observation_facts(self) -> str:
        """给 runtime_facts 注入用：当前工作目录产物列表。"""
        if not self._artifacts:
            return ""
        lines = ["files_produced_this_session:"]
        for a in self._artifacts.values():
            lines.append(f"  - {a.filename} ({a.preview_kind}, {a.size}B, by {a.created_by})")
        return "\n".join(lines)
