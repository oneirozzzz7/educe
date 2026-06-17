# Educe 日志系统改造 — 实施计划

> 下次 session 直接按本文档执行。与 Opus 4.8 讨论确认。

## 架构

```
.educe/logs/
  index.jsonl                     # L0: 每行一个 SessionSummary
  sessions/
    2026-06-17/
      <session_id>/
        events.jsonl              # L1: 按 seq 排序的 Event
        trace.jsonl               # L2: 大 payload（UUID 引用）
        meta.json                 # session 元数据
```

## 新建文件

```
educe/core/logging/
  __init__.py          # 导出 SessionLogger, get_logger
  schema.py            # dataclass: Event, Trace, SessionSummary, SessionMeta  (~120行)
  session_logger.py    # SessionLogger 核心实现                                (~180行)
  writer.py            # JsonlWriter（句柄缓存 + flush）                        (~60行)
  compat.py            # log_activity shim（保持旧 import 路径可用）             (~40行)
```

## 改动文件

| 文件 | 改动内容 | 规模 |
|------|---------|------|
| `educe/core/activity_log.py` | 内容替换为 `from .logging.compat import log_activity` | ~5行 |
| `educe/core/orchestrator.py` | 注入 SessionLogger + 替换20处 log_activity + 新增12个埋点 | ~120行 |
| `educe/cli/app.py` 或启动入口 | 创建 SessionLogger，写 meta 起始，结束时 close | ~15行 |
| `educe/web/server.py` | WebSocket session 创建时初始化 logger | ~10行 |

## Schema（核心 dataclass）

```python
@dataclass
class Event:
    event_id: str           # 16位 UUID
    ts: float               # unix timestamp
    type: str               # "framework"|"llm_call"|"tool_call"|"user"|"error"
    name: str               # "session_start","llm_response","shell","nudge_triggered"
    status: str             # "ok"|"error"|"partial"
    duration_ms: float|None
    summary: str            # 人类可读单行（不截断关键信息）
    data: dict              # 小字段（action_type, exit_code, model 等）
    trace_id: str|None      # → trace.jsonl 中的 UUID，None=无大payload

@dataclass
class Trace:
    trace_id: str
    ts: float
    kind: str               # "system_prompt"|"llm_output"|"tool_result"|"messages"
    payload: Any            # 完整内容

@dataclass
class SessionSummary:       # index.jsonl 每行
    session_id: str
    date: str
    start_ts: float
    end_ts: float|None
    status: str             # "running"|"completed"|"error"|"aborted"
    task: str               # 首条用户指令（截断200字）
    n_events: int
    n_errors: int
    model: str

@dataclass
class SessionMeta:          # meta.json
    session_id: str
    start_ts: float
    educe_version: str
    model: str
    config: dict            # 关键运行参数快照
    git_sha: str
    cwd: str
    status: str
```

## Orchestrator 新增埋点清单（12个）

| 位置 | event name | type | trace |
|------|-----------|------|-------|
| run() 入口 | session_start | framework | — |
| 每轮迭代开始 | turn_start | framework | trace: messages + system_prompt |
| LLM 调用返回 | llm_response | llm_call | trace: raw_output（含 native tokens）|
| action 解析后 | actions_parsed | framework | data: types, count |
| 工具执行完 | tool_result | tool_call | trace: full_output (if >500 chars) |
| nudge 触发 | nudge_triggered | framework | data: nudge_count, redundancy_score |
| continuation 触发 | continuation | framework | data: signal_text |
| safety_net 触发 | safety_net | framework | data: round, nudge_count |
| clarify 暂停 | clarify_pause | framework | data: question |
| 用户回复 clarify | clarify_resume | user | data: answer |
| 循环结束 | turn_end | framework | data: reason(max_rounds/no_action/clarify) |
| session 结束 | session_end | framework | data: outcome, total_turns |

## 引用机制

写 trace 时生成 `trace_id = uuid4().hex[:16]`，append 到 trace.jsonl。
Event 持有 `trace_id` 字段。
读取时扫描 trace.jsonl 建 `{trace_id: line}` 索引。

## 性能策略

- 同步 append + `open("a")` 句柄缓存（不关闭直到 session end）
- 每次 write 后 flush（崩溃安全，不丢事件）
- L2 trace 为可配置（env `EDUCE_TRACE=0` 关闭）
- 当前量级（单 session 数百事件 + 几十 KB trace）同步完全够

## 兼容策略

1. `activity_log.py` 改为 shim：`from .logging.compat import log_activity`
2. 旧 `.educe/logs/activity_*.jsonl` 保留只读，不删不迁移
3. shim 的 `log_activity` 转调新 SessionLogger（无 active logger 时 noop）
4. 过渡期后（2个版本）删除 shim

## 执行顺序

1. 新建 `educe/core/logging/` 包（schema + writer + session_logger）
2. 新建 compat.py shim
3. 替换 `activity_log.py` 为 shim import
4. orchestrator.py 注入 logger + 替换 20 处调用
5. 新增 12 个埋点
6. server.py / cli.py 初始化 logger
7. 端到端验证：跑一个 session → 检查 logs/ 目录结构和内容
