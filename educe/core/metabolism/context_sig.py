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
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger("educe.core.metabolism.context_sig")


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
#  Shell 子分类 — 外置 YAML 配置（公理五：机制与认知分离）
#  引擎持有匹配机制，配置表只含声明性领域知识。
#  优先从 .educe/config/shell_taxonomy.yaml 加载，
#  加载失败时使用内置默认值（保证引擎始终可启动）。
# ═══════════════════════════════════════

_TAXONOMY_PATHS = [
    Path(".educe/config/shell_taxonomy.yaml"),
    Path(__file__).parent.parent.parent / "config" / "shell_taxonomy.yaml",
    Path.home() / ".educe/config/shell_taxonomy.yaml",
]

_DEFAULT_TAXONOMY: dict[str, dict] = {
    "git":     {"match": "head", "values": ["git"]},
    "test":    {"match": "head_and_contains", "values": ["pytest", "jest"],
                "contains": ["test"],
                "alt_heads": ["npm", "yarn", "pnpm", "cargo", "go"]},
    "build":   {"match": "head_or_contains", "values": ["make", "cargo", "go", "tsc", "webpack", "vite"],
                "alt_heads": ["npm", "yarn", "pnpm"], "contains": ["build"]},
    "serve":   {"match": "full_contains_any", "values": ["uvicorn", "nohup", "gunicorn",
                "flask run", "npm start", "npm run dev"]},
    "heredoc": {"match": "full_contains_any", "values": ["EOF"]},
    "pkg":     {"match": "head_and_contains", "values": ["pip", "pip3", "npm", "yarn", "pnpm", "apt", "brew", "cargo"],
                "contains": ["install", "add", "uninstall"]},
    "search":  {"match": "head", "values": ["grep", "rg", "ag", "find", "fd", "ack"]},
    "read":    {"match": "head_not_contains", "values": ["cat", "less", "head", "tail", "bat", "sed", "awk"],
                "not_contains": [">"]},
    "nav":     {"match": "head", "values": ["ls", "cd", "pwd", "tree", "stat", "du", "wc", "echo", "printf", "date", "whoami", "hostname"]},
    "mutate":  {"match": "head", "values": ["mv", "cp", "rm", "mkdir", "touch", "chmod", "ln"]},
    "write":   {"match": "head_and_contains", "values": ["echo", "sed", "tee"],
                "contains": [">", "-i"],
                "alt_heads": ["cat", "echo"]},
    "net":     {"match": "head", "values": ["curl", "wget", "ssh", "scp", "docker", "kubectl"]},
    "proc":    {"match": "head", "values": ["ps", "kill", "top", "systemctl", "service", "pkill", "lsof"]},
    "python":  {"match": "head", "values": ["python", "python3", "bash", "sh"]},
    "node":    {"match": "head", "values": ["node", "npx", "tsx"]},
    "open":    {"match": "head", "values": ["open", "xdg-open"]},
    "source":  {"match": "head_or_contains", "values": ["source", "."],
                "contains": ["activate"]},
}


def _load_taxonomy() -> dict[str, dict]:
    """加载 YAML 配置，失败时使用内置默认值"""
    for p in _TAXONOMY_PATHS:
        if p.exists():
            try:
                import yaml
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and len(data) > 5:
                    return data
            except Exception as e:
                log.debug("suppressed: %s", e)
    return _DEFAULT_TAXONOMY


SHELL_TAXONOMY: dict[str, dict] = _load_taxonomy()


class _ShellClassifier:
    """引擎机制（L1）：统一的分类匹配逻辑，不认识任何具体命令值。"""

    def __init__(self):
        self._other_counter: dict[str, int] = {}

    def classify(self, head: str, full: str) -> str:
        for cat, rule in SHELL_TAXONOMY.items():
            if self._matches(head, full, rule):
                return f"shell.{cat}"
        self._other_counter[head] = self._other_counter.get(head, 0) + 1
        return "shell.other"

    def _matches(self, head: str, full: str, rule: dict) -> bool:
        match_type = rule["match"]
        values = rule.get("values", [])

        if match_type == "head":
            return head in values

        elif match_type == "head_and_contains":
            contains = rule.get("contains", [])
            alt_heads = rule.get("alt_heads", [])
            if head in values and any(c in full for c in contains):
                return True
            if head in alt_heads and any(c in full for c in contains):
                return True
            return False

        elif match_type == "head_or_contains":
            contains = rule.get("contains", [])
            return head in values or any(c in full for c in contains)

        elif match_type == "head_not_contains":
            not_contains = rule.get("not_contains", [])
            return head in values and not any(c in full for c in not_contains)

        elif match_type == "full_contains_any":
            return any(v in full for v in values)

        return False

    def suggest_new_categories(self, min_count: int = 5) -> list[dict]:
        """
        环境适应：从 other 积累中建议新分类。

        当某个命令头在 other 中出现超过 min_count 次，
        说明当前环境频繁使用了 taxonomy 未覆盖的命令。
        返回建议的新 YAML 条目（不自动写入，需人工/LLM 审批）。
        """
        suggestions = []
        for head, count in sorted(self._other_counter.items(), key=lambda x: -x[1]):
            if count >= min_count:
                suggestions.append({
                    "head": head,
                    "count": count,
                    "suggested_category": self._guess_category(head),
                    "yaml_entry": {
                        "match": "head",
                        "values": [head],
                    },
                })
        return suggestions

    @staticmethod
    def _guess_category(head: str) -> str:
        """启发式猜测命令的语义类别（仅作为建议，不直接使用）"""
        sysinfo_cmds = {"df", "free", "top", "uptime", "uname", "hostname",
                        "sysctl", "vm_stat", "system_profiler", "diskutil",
                        "lscpu", "lsblk", "mount", "ifconfig", "ip"}
        if head in sysinfo_cmds:
            return "sysinfo"
        util_cmds = {"which", "whereis", "type", "file", "readlink",
                     "basename", "dirname", "realpath", "date", "cal"}
        if head in util_cmds:
            return "util"
        wait_cmds = {"sleep", "wait"}
        if head in wait_cmds:
            return "wait"
        return "unknown"


_classifier = _ShellClassifier()


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

    return _classifier.classify(head, full)


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
#  Resource Delta 投影 — 声明式配置（公理五）
#  引擎持有匹配机制，具体分类规则来自 YAML 声明。
# ═══════════════════════════════════════

_RESOURCE_DELTA_PATHS = [
    Path(".educe/config/resource_delta.yaml"),
    Path(__file__).parent.parent.parent / "config" / "resource_delta.yaml",
    Path.home() / ".educe/config/resource_delta.yaml",
]

_DEFAULT_RESOURCE_DELTA: dict[str, dict] = {
    "destructive": {"delta": "-file", "match": "word_boundary", "values": ["rm", "rmdir", "shred", "unlink"]},
    "creative": {"delta": "+file", "match": "contains_any", "values": [">>", ">", "tee", "touch", "mkdir", "cp", "mv"]},
    "reading": {"delta": "read", "match": "word_boundary", "values": ["cat", "less", "head", "tail", "grep", "find", "ls", "awk", "sed", "bat", "rg", "ag", "fd"]},
}


def _load_resource_delta() -> dict[str, dict]:
    """加载资源分类配置，失败时使用内置默认值"""
    for p in _RESOURCE_DELTA_PATHS:
        if p.exists():
            try:
                import yaml
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and len(data) >= 2:
                    return data
            except Exception as e:
                log.debug("suppressed: %s", e)
    return _DEFAULT_RESOURCE_DELTA


RESOURCE_DELTA_RULES: dict[str, dict] = _load_resource_delta()


class _ResourceDeltaClassifier:
    """引擎机制：统一的资源变化判断逻辑，不认识任何具体命令。"""

    def classify(self, params: str) -> str:
        for _cat, rule in RESOURCE_DELTA_RULES.items():
            if self._matches(params, rule):
                return rule.get("delta", "none")
        return "none"

    def _matches(self, params: str, rule: dict) -> bool:
        match_type = rule.get("match", "word_boundary")
        values = rule.get("values", [])

        if match_type == "word_boundary":
            for v in values:
                if re.search(r"\b" + re.escape(v) + r"\b", params):
                    return True
            return False

        elif match_type == "contains_any":
            return any(v in params for v in values)

        return False


_rdelta_classifier = _ResourceDeltaClassifier()


def resource_delta(record: dict) -> str:
    """推断这一步对资源状态的改变"""
    cap = record.get("decision_point", "") or record.get("action_taken", {}).get("capability", "")
    params = record.get("action_taken", {}).get("params", "")

    if cap in ("write_file", "edit_file"):
        return "+file"
    if cap in ("read_lines", "read_file", "read_dir", "search_in_file"):
        return "read"
    if cap == "shell":
        return _rdelta_classifier.classify(params)
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
