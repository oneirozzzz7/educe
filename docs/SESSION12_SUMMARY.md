# Session 12 总结 (2026-06-26)

## 完成事项

### P0 Bug 修复（用户可见文本泄露）

| Bug | 根因 | 修复 |
|-----|------|------|
| reply_text 含自然 XML 路径 | `parse_actions()` 清理 reply_text 时遗漏 `_NATURAL_XML_PATTERN` | 新增 `.sub("", reply_text)` |
| Challenge 内容泄露 | `_strip_plan()` 未剥离 `<challenge>` 块 | 新增 `_CHALLENGE_RE` 正则 |
| `[上轮路径]`/`[上轮发现]` 回显 | 跨轮时作为 assistant 消息注入，模型下轮回显 | 删除注入（plan pinned slot 已携带） |

### 死代码清理（-1390 行）

| 删除内容 | 行数 | 理由 |
|---------|------|------|
| `educe/core/action_loop_v2.py` | 357 | V3 已完全替代 |
| `educe/core/loop_context.py` | ~100 | ConversationTruth 替代 |
| `orchestrator._action_loop_legacy` | 695 | 不被调用 |
| 重复 `return self.context` | 1 | 死代码 |
| **合计** | **~1390** | orchestrator 2384→1687行 |

### 前端修复

- Google Fonts CSS `@import`（同步阻塞）改为 `<link rel="stylesheet">`（异步加载）
- 解决 Playwright 截图时 font loading 超时问题

## Opus 4.8 审查结果

**判定：PASS**

关键确认：
1. XML 清理精准——`.html` 文件名、`renderDiffView(left, right)` 等代码引用未被误删
2. `_NATURAL_XML_PATTERN` 仅匹配 16 个已知 action type 的精确闭合标签对
3. 代码块内容完全不受影响（`xml` 在 `_CODE_ONLY_LANGS` 中）
4. 多轮上下文正常——删除 `[上轮]` 注入未破坏模型记忆（plan pinned slot 足够）

**Known limitation**：裸文本中闭合 action 标签对会被误匹配为 action。极低概率，已记录。

## 当前架构状态

```
用户消息 → orchestrator._action_loop()
  → action_loop_v3() [唯一 loop，无 legacy]
    → ConversationTruth [单一数据源]
    → Plan (pinned slot, 模型维护)
    → Challenge (Situation 驱动，模型必须回应)
    → _strip_plan() [<plan>/<challenge>/XML 全部剥离]
    → parse_actions() [reply_text 清理]
  → WS 推送给前端
```

核心文件：
- `educe/core/action_loop_v3.py` — 主循环
- `educe/core/conversation_truth.py` — 单一数据源
- `educe/core/action_executor.py` — action 解析 + reply_text 清理
- `educe/core/orchestrator.py` — 1687行（精简后）

## 待办（Session 13）

### 优先级 1：The Descent Curve
- 前置条件已满足（V3 稳定 + 测试全过 + 死代码清理完）
- 实验装置：3 任务族 × 15 次
- 记录：(llm_calls, tokens, wall_clock, L3_takeover, correct)
- 成功标准：单调性 + 收敛性 + 保真性

### 优先级 2：遗留功能
- ConversationTruth WARM 预算精度
- confirm 后状态恢复
- session_env 持久化接入
- 前端 UI 美化（Memory Conflict 卡片、WelcomeCard）

## 验证证据

- 截图：`e2e_session12_p0_verified.png`（Round 1）、`e2e_session12_round2_expanded.png`（Round 2 展开）
- 日志：`.educe/logs/sessions/2026-06-26/2b3dfe4f-64a8-43/events.jsonl`
- 契约测试：6/6 PASS
- Commits: `de44a1b` → `94d4d7c` → `e70601a`
