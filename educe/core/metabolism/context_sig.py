"""
context_sig — 决策上下文的有损投影函数

阶段2路径挖掘器的核心组件。将高维决策 context 降维为可哈希桶签名，
使得"语义相似的情境"落入同一桶。

设计原则（Opus 4.8 讨论确认）：
- 分层投影：task_type 做域分区键（scope），不进 sig
- sig 仅 3 维：(action_verb, outcome, resource_delta)
- shell 子分类：head+keyword 规则投影到 ~15 个语义动词
- prev_action 不单独进 sig（n-gram 滑窗已编码前驱信息）
- step_position 后置处理（挖出 pattern 后做位置画像）
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepSig:
    """单步决策签名 — 路径挖掘器的 token"""
    verb: str       # "shell.git" | "write_file" | ...  (~25 取值)
    outcome: str    # "ok" | "err"                       (2 取值)
    rdelta: str     # "+file" | "-file" | "read" | "none" (4 取值)

    def __str__(self) -> str:
        return f"{self.verb}[{self.outcome},{self.rdelta}]"

    def to_tuple(self) -> tuple[str, str, str]:
        return (self.verb, self.outcome, self.rdelta)


# ═══════════════════════════════════════
#  Shell 子分类规则
# ═══════════════════════════════════════

_SHELL_RULES: list[tuple[str, Any]] = [
    ("git",     lambda h, full: h == "git"),
    ("test",    lambda h, full: (h in {"pytest", "jest", "go"} and "test" in full)
                                or (h in {"npm", "yarn", "pnpm"} and "test" in full)
                                or (h == "cargo" and "test" in full)),
    ("build",   lambda h, full: h in {"make", "cargo", "go", "tsc", "webpack", "vite"}
                                or (h in {"npm", "yarn", "pnpm"} and "build" in full)),
    ("serve",   lambda h, full: "uvicorn" in full or "nohup" in full or "gunicorn" in full
                                or "flask run" in full or "npm start" in full
                                or "npm run dev" in full),
    ("heredoc", lambda h, full: "EOF" in full
                                or ("cat" in full and ">" in full and "<<" in full)),
    ("pkg",     lambda h, full: h in {"pip", "pip3", "npm", "yarn", "pnpm", "apt", "brew", "cargo"}
                                and any(k in full for k in ("install", "add", "uninstall"))),
    ("search",  lambda h, full: h in {"grep", "rg", "ag", "find", "fd", "ack"}),
    ("read",    lambda h, full: h in {"cat", "less", "head", "tail", "bat", "sed", "awk"}
                                and ">" not in full),
    ("nav",     lambda h, full: h in {"ls", "cd", "pwd", "tree", "stat", "du", "wc"}),
    ("mutate",  lambda h, full: h in {"mv", "cp", "rm", "mkdir", "touch", "chmod", "ln"}),
    ("write",   lambda h, full: (h in {"echo", "sed", "tee"} and (">" in full or "-i" in full))
                                or (h == "cat" and ">" in full)
                                or (h == "echo")),
    ("net",     lambda h, full: h in {"curl", "wget", "ssh", "scp", "docker", "kubectl"}),
    ("proc",    lambda h, full: h in {"ps", "kill", "top", "systemctl", "service", "pkill", "lsof"}),
    ("python",  lambda h, full: h in {"python", "python3"}),
    ("node",    lambda h, full: h in {"node", "npx", "tsx"}),
    ("open",    lambda h, full: h in {"open", "xdg-open"}),
    ("source",  lambda h, full: h in {"source", "."} or "activate" in full),
]


def shell_subclass(params: str) -> str:
    """将 shell 命令参数投影到语义子类（~15 个桶）"""
    full = params.strip()
    try:
        tokens = shlex.split(full)
    except ValueError:
        tokens = full.split()
    if not tokens:
        return "shell.other"

    # 跳过环境变量前缀 FOO=bar
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        i += 1
    head = (tokens[i] if i < len(tokens) else tokens[0]).rsplit("/", 1)[-1]

    # 跳过 sudo
    if head == "sudo" and i + 1 < len(tokens):
        head = tokens[i + 1].rsplit("/", 1)[-1]

    # 处理 cd dir && real_cmd
    if head == "cd" and "&&" in full:
        parts = full.split("&&", 1)[1].strip().split()
        if parts:
            head = parts[0].rsplit("/", 1)[-1]

    for name, fn in _SHELL_RULES:
        try:
            if fn(head, full):
                return f"shell.{name}"
        except Exception:
            continue
    return "shell.other"


# ═══════════════════════════════════════
#  Action Verb 投影
# ═══════════════════════════════════════

def action_verb(record: dict) -> str:
    """从 ConsequenceRecord dict 提取 action verb"""
    cap = record.get("decision_point", "") or record.get("action_taken", {}).get("capability", "")
    if cap == "shell":
        return shell_subclass(record.get("action_taken", {}).get("params", ""))
    return cap


# ═══════════════════════════════════════
#  Resource Delta 投影
# ═══════════════════════════════════════

_RE_DESTRUCTIVE = re.compile(r"\brm\b")
_RE_CREATIVE = re.compile(r"[>]{1,2}|tee|touch|mkdir|cp\b|mv\b")
_RE_READING = re.compile(r"\b(cat|less|head|tail|grep|find|ls|awk|sed)\b")


def resource_delta(record: dict) -> str:
    """推断这一步对资源状态的改变"""
    cap = record.get("decision_point", "") or record.get("action_taken", {}).get("capability", "")
    params = record.get("action_taken", {}).get("params", "")

    if cap in ("write_file", "edit_file"):
        return "+file"
    if cap in ("read_lines", "read_file", "read_dir", "search_in_file"):
        return "read"
    if cap == "shell":
        if _RE_DESTRUCTIVE.search(params):
            return "-file"
        if _RE_CREATIVE.search(params):
            return "+file"
        if _RE_READING.search(params):
            return "read"
    return "none"


# ═══════════════════════════════════════
#  完整 StepSig 投影
# ═══════════════════════════════════════

def project_sig(record: dict, level: int = 2) -> StepSig:
    """
    将 ConsequenceRecord 投影为 StepSig。

    level=2: 全维 (verb, outcome, rdelta) — 默认
    level=1: 中维 (verb, outcome, "none") — 稀疏域降级用
    level=0: 粗维 (verb, "ok", "none")   — 极端稀疏
    """
    verb = action_verb(record)
    outcome = "ok" if record.get("outcome_type") in ("success", "user_confirmed") else "err"
    rdelta = resource_delta(record) if level >= 2 else "none"
    if level < 1:
        outcome = "ok"
    return StepSig(verb=verb, outcome=outcome, rdelta=rdelta)


# ═══════════════════════════════════════
#  Task Type 域分区（scope key）
# ═══════════════════════════════════════

_TASK_TYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("CODE", ["代码", "实现", "写一个", "函数", "类", "模块", "重构", "implement", "code", "function", "class"]),
    ("SHELL", ["运行", "执行", "命令", "shell", "terminal", "run", "execute"]),
    ("BUILD", ["构建", "部署", "build", "deploy", "docker", "compile"]),
    ("TEST", ["测试", "test", "验证", "check"]),
    ("FILE", ["文件", "读", "写", "创建", "修改", "file", "read", "write", "create", "edit"]),
    ("SEARCH", ["搜索", "查找", "search", "find", "grep", "看看"]),
    ("PKG", ["安装", "依赖", "install", "pip", "npm", "package"]),
]


def task_type(user_input: str) -> str:
    """从 user_input 推断任务域（scope key）"""
    lower = user_input.lower()
    for ttype, keywords in _TASK_TYPE_PATTERNS:
        if any(kw in lower for kw in keywords):
            return ttype
    return "GENERAL"
