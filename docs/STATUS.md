# Educe 项目状态文档（2026-06-04）

## 今日完成的工作

### Session 2 — Thinking 提取 + 代码实时更新 + 架构研究
1. **ModelClient.chat_with_reasoning()** — 新增 `_chat_raw()` 和 `chat_with_reasoning()` 方法，提取 `<think>` 标签和 `model_extra.reasoning`，现有 `chat()` 保持向后兼容
2. **builder.py reasoning 推送** — 复杂任务路径中使用 `chat_with_reasoning()`，推送 `step_reasoning` 事件到前端
3. **StepBuilder 实时代码推送** — 每步产出代码后推送 `step_code_content` 事件（含完整累积代码），前端 Code 面板即时更新
4. **前端事件处理** — `page.tsx` 处理 `step_reasoning`（可折叠 details 块）和 `step_code_content`（实时更新 streamingCode）
5. **Claude Code 架构深度研究** — 全 18 章深度分析，提炼 Slot Reservation / 4 层压缩 / 工具并发 / Fork Cache / Memory 系统等可迁移模式

### Session 1 — Bug 修复 + 能力升级
1. Preview 隔离：按 session_id 独立输出目录
2. CompleteBar 0.0KB/0s：历史任务从 HTML 计算大小，从时间戳计算耗时
3. 追问无回复：agent_message 在 phase=active 时被静默丢弃
4. Plan 卡片不显示：idle 紧跟 plan_proposal 导致 UI 被重置
5. Decision 卡片被输入框遮挡：底部 padding 不足
6. Session 保存空内容：路径拼接 bug 导致文件读不到
7. _extract_files 正则截断：代码中的反引号导致提前截断（核心 bug）
8. API key 优先级：KIMI_API_KEY 覆盖了 DEEPFORGE_API_KEY

### 能力升级
1. **自适应深度**：复杂度评估驱动 max_turns/exec_timeout
2. **StepBuilder 分步构建**：复杂任务拆步+每步验证
3. **协作式规划**：复杂任务展示 plan_proposal 让用户选方案
4. **Qwen 模型接入**：支持 thinking mode，自适应开关
5. **格式兼容**：_extract_files 支持 filepath:/html/raw 三种格式
6. **CDN 支持**：允许模型使用外部库（marked.js, Chart.js 等）
7. **API 重试**：3次重试 + 120s 超时
8. **步骤时间线**：结构化事件流，前端可视化构建过程（刚完成 P0）

### 对比实验结果（5个任务 × DeepSeek-V4-Flash）
```
dashboard    7/7  (修正后预估)
markdown     7/7  ★ 从5/7修到满分
todo         7/7  ★
breakout     7/7  ★
apitester    6/7  (JSON格式化关键词匹配问题)
总计: 34/35 (97%)
```

## 当前运行状态

### 服务
- 后端：`python main.py web --port 7860`（需手动启动）
- 前端：`cd web && npx next dev --port 3003`（需手动启动）
- 模型：`.env` 当前配置为 DeepSeek-V4-Flash（Qwen 内网不稳定时的备选）

### .env 配置
```
当前: DeepSeek-V4-Flash（公网稳定）
备选: Qwen3.5-397B-A17B（内网，速度快但不稳定）
配置方式: 修改项目根目录 .env 文件中的 DEEPFORGE_API_KEY/MODEL/BASE_URL
```

## 待办事项

### P0（已完成 ✅）
- [x] **Transcript P1：提取 thinking 内容** — ModelClient.chat_with_reasoning() 返回 reasoning，builder.py 推送 step_reasoning 事件到前端（可折叠 details 块）
- [x] **Transcript P1：代码面板实时更新** — StepBuilder 每步完成后推送 step_code_content 事件，Code 面板即时更新

### P0（下次优先）
- [ ] **Slot Reservation** — ModelClient 默认 max_tokens=4K（DeepSeek 实际 p99 输出远低于默认值），截断时升 16K。参考 Claude Code Ch17：8K→64K 策略节省 12-28% 上下文
- [ ] **StepBuilder 上下文压缩** — 每步完成后压缩前序步骤的 tool results（Layer 2 microcompact 思路），防止多步构建后上下文溢出

### P1
- [ ] **Phase 5：多类型输出支持** — artifact 面板支持 Python/Markdown/多文件，添加 zip 下载
- [ ] **Transcript P2：步骤间 diff 高亮** — 新增行绿色背景
- [ ] **Transcript P2：历史快照** — 保存每步代码快照，支持回退
- [ ] **AgenticLoop 结构化终止** — run() 返回结构化终止原因 `{ reason, files, turns, errors }`，而非只返回 files dict。参考 Claude Code Ch5 的 10 种 Terminal 状态
- [ ] **工具安全分类** — 按输入内容分类只读/写操作（`is_read_only(command)`），只读操作可并发执行。参考 Claude Code Ch7 partition 算法

### P2
- [ ] **Phase 7：研究报告分段生成** — 文字类复杂任务的分段生成（拆章节→逐段→综合）
- [ ] **前端稳定性** — Next.js dev server 反复崩溃，需要 production build 或守护进程
- [ ] **投机执行** — 在模型流式输出时提前启动已解析的只读工具。参考 Claude Code Ch7 StreamingToolExecutor
- [ ] **Memory 系统** — 文件式记忆（4 种类型：user/feedback/project/reference）+ LLM side-query 检索。参考 Claude Code Ch11

## 关键设计原则（记忆）
1. **过程>结果** — Outcome 只是及格线，Transcript 才是分水岭
2. **不硬编码** — 复杂度/步骤数/输出格式都由模型自己判断
3. **框架引导，不替代** — 让模型在正确结构里发挥，不注入知识
4. **协作式** — 复杂任务用户参与决策（plan/decision）

## 最新 Git 状态
- 分支：main
- 最新 commit：`1762055` docs: project status and TODO for session handoff
- 待提交：thinking 提取 + 代码实时更新（4 文件改动）
- 远程：github.com/oneirozzzz7/deepforge
