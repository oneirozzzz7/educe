# 过程透明度设计方案 — Round 12-13 Opus 讨论成果

*2026-06-20 · 接口冻结前的完整设计*

---

## 核心原则

> **透明 = 可见证，不是可查看。过程自己摊在眼前，不需要用户点击。**

### 三层模型

| 层 | 含义 | 默认状态 |
|---|---|---|
| **Glance** | 做了什么 + 结果 + 异常 | **默认展开** |
| **Inspect** | 完整 I/O | 一键展开 |
| **Audit** | 全 trace + 决策点 | status 面板 |

### 不硬编码原则

- 所有阈值（流式切换、截断行数、节流间隔、超时）从配置加载
- 流式机制是通用的（所有 tool 统一走 tool_start/chunk/end）
- 不按工具类型做 if-else 分支

---

## 一、WebSocket 流式协议

```typescript
// 工具开始
{ type: "tool_start", id: "t1", tool: "write_file",
  meta: { path: "test.py", mode: "create"|"modify" } }

// 流式内容块
{ type: "tool_chunk", id: "t1", stream: "content"|"stdout"|"stderr"|"diff",
  data: "import sys\n" }

// 工具结束
{ type: "tool_end", id: "t1",
  result: { exit_code: 0, duration_ms: 2300, lines: 3 } }

// 可选：工具取消（用户中断）
{ type: "tool_cancel", id: "t1", reason: "user" }
```

---

## 二、write_file 过程可见

### 新建文件：内容流式出现
```
┌─────────────────────────────────────┐
│ ✎ 写入 test.py                       │   ← 进行中
│ ─────────────────────────────────── │
│  1  import sys                       │   ← 内容逐行出现
│  2  def main():                      │
│  3      print("hello")        ▎      │
└─────────────────────────────────────┘

写完后：
┌─────────────────────────────────────┐
│ ✓ 写入 test.py · 3 行                 │
│ ─────────────────────────────────── │
│  1  import sys                       │   ← 保持可见（可折叠）
│  2  def main():                      │
│  3      print("hello")               │
└─────────────────────────────────────┘
```

### 修改已有文件：diff 视图
```
┌─────────────────────────────────────┐
│ ✓ 修改 config.py · +2 -1             │
│ ─────────────────────────────────── │
│   2    DEBUG = False                 │
│ - 3    PORT = 8000                   │   ← 红
│ + 3    PORT = 9000                   │   ← 绿
│ + 4    TIMEOUT = 30                  │
└─────────────────────────────────────┘
```

### 后端逻辑
```python
async def write_file(path, content, emit):
    mode = "modify" if os.path.exists(path) else "create"
    await emit("tool_start", meta={"path": path, "mode": mode})

    if mode == "modify":
        diff = compute_diff(read_old(path), content)
        await emit("tool_chunk", stream="diff", data=diff)
    else:
        for line in content.splitlines(keepends=True):
            await emit("tool_chunk", stream="content", data=line)

    write_to_disk(path, content)
    await emit("tool_end", result={"lines": content.count("\n")+1})
```

**关键：先推内容给前端，再写盘。顺序就是信任。**

---

## 三、shell 流式输出

### 自适应切换（不硬编码阈值，从配置读）
```
命令开始 → 显示 "⟳ 运行中: cmd"
         → 如果 THRESHOLD_MS 内完成 → 直接显示完整输出
         → 如果超过 THRESHOLD_MS → 切换到流式，逐行追加
```

`THRESHOLD_MS` 从 `educe/config/` 声明式配置加载，默认值可调。

### 流式形态
```
┌─────────────────────────────────────┐
│ ⟳ pytest tests/                      │   ← 运行中
│ ─────────────────────────────────── │
│ collected 12 items                   │
│ test_foo.py ......                   │   ← 实时追加
│ test_bar.py ..▎                      │
└─────────────────────────────────────┘

完成后：
┌─────────────────────────────────────┐
│ ✓ pytest · exit 0 · 2.3s             │   ← 退出码+耗时
│ ─────────────────────────────────── │
│ ... (最后 N 行可见，可展开全部)        │
│ ============ 12 passed in 2.3s ===== │
└─────────────────────────────────────┘
```

### 后端改动（subprocess.run → Popen 异步流式）
```python
async def run_shell(cmd, emit):
    await emit("tool_start", meta={"cmd": cmd})
    start = time.time()

    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=PIPE, stderr=PIPE)

    async def pump(stream, name):
        async for line in stream:
            await emit("tool_chunk", stream=name,
                       data=line.decode(errors="replace"))

    await asyncio.gather(pump(proc.stdout, "stdout"), pump(proc.stderr, "stderr"))
    code = await proc.wait()

    await emit("tool_end", result={
        "exit_code": code,
        "duration_ms": int((time.time()-start)*1000)
    })
```

---

## 四、边界处理（从配置读，不硬编码）

| 参数 | 默认值 | 配置键 | 作用 |
|------|--------|--------|------|
| 流式切换阈值 | 300ms | `tool_stream.threshold_ms` | 超过才流式 |
| 前端最大渲染行 | 200 | `tool_stream.max_render_lines` | 超过折叠 |
| 高频输出节流 | 50ms | `tool_stream.flush_interval_ms` | 批量推送 |
| 命令超时 | 300s | `tool_stream.timeout_s` | 超时 kill |
| `\r` 回车处理 | true | `tool_stream.handle_cr` | 覆盖当前行 |

---

## 五、前端 StreamView 组件

```tsx
function ToolCard({ id }) {
  const tool = useToolStream(id);
  const showLive = tool.status === "running" && tool.elapsed > threshold;

  return (
    <Card>
      <Header>
        {tool.status === "running" ? "⟳" : tool.exitCode === 0 ? "✓" : "✗"}
        {tool.title}
        {tool.status === "done" && <Meta>exit {tool.exitCode} · {tool.duration}</Meta>}
      </Header>
      <Body>
        <StreamView lines={tool.lines} maxRender={config.maxLines} autoScroll />
      </Body>
    </Card>
  );
}
```

---

## 六、可中断设计（预留接口）

协议已包含 `tool_cancel`。前端在 `tool_start` 后显示一个 [停止] 按钮：
```
⟳ 运行中: npm install                          [停止]
```

点击发送 `{ type: "tool_cancel", id: "t1", reason: "user" }`，后端 kill 进程。

---

## 七、与 Round 12 的关系

| Round 12 | Round 13 |
|----------|----------|
| "✓ 写入 test.py" + ⌄ 展开 | 内容**默认可见**，不需要点 |
| 输出摘要一行 | **完整输出**默认展开（或流式） |
| 需要点击才看到命令 | 命令**始终可见** |
| 没有退出码/耗时 | exit code + duration 常驻 |

---

## 八、实施顺序

1. **后端 shell 改流式**（Popen + pump + tool_start/chunk/end）
2. **后端 write_file 改流式**（先推内容再写盘）
3. **前端 ToolCard + StreamView 组件**（订阅 tool 事件流）
4. **配置外置**（阈值/截断/节流参数到 YAML）
5. **可中断**（cancel 按钮 + 后端 kill）

---

*下次 session 直接从第 1 步开始实现。*
