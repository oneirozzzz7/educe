"""Plan 解析器 + 压缩器

从 LLM output 中提取 <plan> 块，解析字段，管理压缩。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Plan:
    goal: str = ""
    findings: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    next: str = ""
    status: str = "working"

    def to_block(self) -> str:
        findings_str = "\n".join(f"  - {f}" for f in self.findings) if self.findings else "（无）"
        done_str = self._render_done()
        return (
            "<plan>\n"
            f"goal: {self.goal}\n"
            f"findings:\n{findings_str}\n"
            f"done: {done_str}\n"
            f"next: {self.next}\n"
            f"status: {self.status}\n"
            "</plan>"
        )

    def _render_done(self) -> str:
        if not self.done:
            return "（无）"
        # 如果有 summary 条目（压缩后的）
        parts = []
        for d in self.done:
            if isinstance(d, dict) and d.get("type") == "done_summary":
                parts.append(f"[已完成{d['count']}项: {', '.join(f'{k}×{v}' for k,v in d['by_action'].items())}]")
            else:
                parts.append(str(d))
        return "; ".join(parts)

    def compress(self):
        """就地压缩 done 和 findings。"""
        self.done = _compress_done(self.done)
        self.findings = _compress_findings(self.findings)


# ═══ 解析 ═══

_PLAN_RE = re.compile(r"<plan>(.*?)</plan>", re.DOTALL | re.IGNORECASE)
_FIELD_KEYS = ("goal", "findings", "done", "next", "status")


def parse_plan(raw: str) -> Optional[Plan]:
    """从 LLM output 提取最后一个 <plan> 块。无则返回 None。"""
    matches = _PLAN_RE.findall(raw)
    if not matches:
        return None

    body = matches[-1].strip()
    fields = _parse_fields(body)

    # 解析 findings（支持多行列表）
    findings_raw = fields.get("findings", "")
    findings = _parse_list(findings_raw)

    # 解析 done（支持多行列表或分号分隔）
    done_raw = fields.get("done", "")
    done = _parse_list(done_raw) if "\n" in done_raw else [x.strip() for x in done_raw.split(";") if x.strip()]

    return Plan(
        goal=fields.get("goal", "").strip(),
        findings=findings,
        done=done,
        next=fields.get("next", "").strip(),
        status=_normalize_status(fields.get("status", "working")),
    )


def _parse_fields(body: str) -> dict:
    """逐行扫描，支持 value 跨行。"""
    result: dict = {}
    current_key: Optional[str] = None
    lines: list[str] = []

    def flush():
        if current_key is not None:
            result[current_key] = "\n".join(lines).strip()

    for line in body.splitlines():
        m = re.match(r"\s*(\w+)\s*:\s*(.*)$", line)
        if m and m.group(1).lower() in _FIELD_KEYS:
            flush()
            current_key = m.group(1).lower()
            lines = [m.group(2)]
        else:
            if current_key is not None:
                lines.append(line)
    flush()
    return result


def _parse_list(text: str) -> list[str]:
    """解析 '- item' 格式的多行列表，或逗号/分号分隔。"""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("* "):
            items.append(line[2:].strip())
        elif line and line != "（无）":
            items.append(line)
    return items


def _normalize_status(s: str) -> str:
    s = s.strip().lower()
    if "done" in s or "完成" in s:
        return "done"
    return "working"


# ═══ 压缩 ═══

DONE_KEEP_RECENT = 10
FINDINGS_MAX = 30


def _compress_done(done: list) -> list:
    """done 超 10 条时，旧条目聚合为计数摘要。"""
    if len(done) <= DONE_KEEP_RECENT:
        return done

    recent = done[-DONE_KEEP_RECENT:]
    old = done[:-DONE_KEEP_RECENT]

    # 聚合：按 action 类型计数
    counts: Counter = Counter()
    for d in old:
        if isinstance(d, dict) and d.get("type") == "done_summary":
            for k, v in d.get("by_action", {}).items():
                counts[k] += v
        else:
            # 提取 action 名（取第一个词）
            action_name = str(d).split()[0] if d else "unknown"
            counts[action_name] += 1

    summary = {
        "type": "done_summary",
        "count": sum(counts.values()),
        "by_action": dict(counts),
    }
    return [summary] + recent


def _compress_findings(findings: list[str]) -> list[str]:
    """findings 超 30 条时去重保留最近的。"""
    if len(findings) <= FINDINGS_MAX:
        return findings

    # 简单去重：按内容前 40 字符做 key
    seen: dict[str, str] = {}
    for f in findings:
        key = f[:40].lower().strip()
        seen[key] = f  # 后来的覆盖前面的

    deduped = list(seen.values())
    if len(deduped) <= FINDINGS_MAX:
        return deduped

    # 仍超限：保留最后 30 条
    return deduped[-FINDINGS_MAX:]
