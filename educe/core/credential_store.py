"""
凭据管理 — 安全的 KV 存储 + subprocess env 注入

设计原则（用户+Opus 确认）：
- 不硬编码任何网站的认证方式
- 凭据通过环境变量注入 shell 子进程
- 模型通过 $VAR_NAME 引用，不直接接触值
- system prompt 只暴露 name + note，不暴露 value
- 存储加密留 P2（当前 MVP 用 JSON 文件）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from dataclasses import dataclass

log = logging.getLogger("educe.credential_store")


@dataclass
class Credential:
    name: str       # 环境变量名，如 GITHUB_TOKEN
    value: str      # 实际值（不进 prompt/日志）
    note: str = ""  # 备注（可进 prompt）

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "Credential":
        return cls(name=d["name"], value=d.get("value", ""), note=d.get("note", ""))

    def to_public(self) -> dict:
        """公开信息（不含 value）"""
        return {"name": self.name, "note": self.note}


class CredentialStore:
    """KV 凭据存储"""

    def __init__(self, path: Path | None = None):
        self._path = path or Path(".educe/credentials.json")
        self._creds: dict[str, Credential] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for d in data:
                    c = Credential.from_dict(d)
                    self._creds[c.name] = c
            except Exception as e:
                log.warning("Failed to load credentials: %s", e)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self._creds.values()]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, name: str, value: str, note: str = "") -> None:
        self._creds[name] = Credential(name=name, value=value, note=note)
        self._save()

    def remove(self, name: str) -> bool:
        if name in self._creds:
            del self._creds[name]
            self._save()
            return True
        return False

    def get_env_dict(self) -> dict[str, str]:
        """返回可注入 subprocess env 的字典"""
        return {c.name: c.value for c in self._creds.values()}

    def get_public_list(self) -> list[dict]:
        """返回公开信息列表（不含 value）"""
        return [c.to_public() for c in self._creds.values()]

    def get_prompt_hint(self) -> str:
        """生成 system prompt 注入片段"""
        if not self._creds:
            return ""
        lines = ["可用凭据（通过环境变量 $NAME 引用）："]
        for c in self._creds.values():
            desc = f"  - ${c.name}"
            if c.note:
                desc += f": {c.note}"
            lines.append(desc)
        return "\n".join(lines)
