# Educe 项目状态文档（2026-06-04）

## 今日完成的工作

### Bug 修复
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

### P0（下次优先）
- [ ] **Transcript P1：提取 thinking 内容** — ModelClient.chat 返回 reasoning，StepBuilder 作为 step_reasoning 事件推送到前端
- [ ] **Transcript P1：代码面板实时更新** — 每步完成后 Code 面板显示当前代码，不再等到最后

### P1
- [ ] **Phase 5：多类型输出支持** — artifact 面板支持 Python/Markdown/多文件，添加 zip 下载
- [ ] **Transcript P2：步骤间 diff 高亮** — 新增行绿色背景
- [ ] **Transcript P2：历史快照** — 保存每步代码快照，支持回退

### P2
- [ ] **Phase 7：研究报告分段生成** — 文字类复杂任务的分段生成（拆章节→逐段→综合）
- [ ] **前端稳定性** — Next.js dev server 反复崩溃，需要 production build 或守护进程

## 关键设计原则（记忆）
1. **过程>结果** — Outcome 只是及格线，Transcript 才是分水岭
2. **不硬编码** — 复杂度/步骤数/输出格式都由模型自己判断
3. **框架引导，不替代** — 让模型在正确结构里发挥，不注入知识
4. **协作式** — 复杂任务用户参与决策（plan/decision）

## 最新 Git 状态
- 分支：main
- 最新 commit：`d34c03a` feat: structured step timeline
- 远程：已 push 到 github.com/oneirozzzz7/deepforge
