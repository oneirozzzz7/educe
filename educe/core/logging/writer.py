"""JsonlWriter — append-only writer with handle caching and flush-on-write."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlWriter:
    def __init__(self, path: Path):
        self._path = path
        self._handle = None

    def _ensure_open(self):
        if self._handle is None or self._handle.closed:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(self._path, "a", encoding="utf-8")

    def append(self, record: dict[str, Any]) -> None:
        self._ensure_open()
        self._handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if self._handle and not self._handle.closed:
            self._handle.flush()
            self._handle.close()
            self._handle = None

    def __del__(self):
        self.close()
