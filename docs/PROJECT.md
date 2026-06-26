# Educe 项目文档

> **开源进化引擎框架** — 让任何 LLM 从 chat-only 进化为自主执行体

---

## 目录

1. [项目愿景与核心命题](#1-项目愿景与核心命题)
2. [架构设计与核心组件](#2-架构设计与核心组件)
3. [当前能力清单](#3-当前能力清单)
4. [验证成果](#4-验证成果)
5. [已知限制与待办](#5-已知限制与待办)
6. [下一步路线图](#6-下一步路线图)
7. [开发规范](#7-开发规范)

---

## 1. 项目愿景与核心命题

### 1.1 定位

Educe 是一个**开源进化引擎框架**。核心理念：让任何 LLM 从纯对话（chat-only）进化为能够自主执行任务的执行体。

Educe **不是**什么：
- 不是"治理层"（不在模型之上做规则判断）
- 不是商业产品

Educe **是**什么：
- 让 **Seed**（智能体种子）栖息在环境里、通过试错蒸馏出**世界模型**的进化引擎

**护城河**：Seed 与环境共演化出的"身体图式"（body schema）—— 即私有上下文的**采集 + 淘汰飞轮**。这种私有积累与模型能力正交，不会随模型升级被抹平。

### 1.2 核心命题

> **智能体的行为成本应该随经验单调下降。**

| | 成本曲线 | 原因 |
|---|---|---|
| Claude Code | 水平线 | 每次从零开始，无跨会话积累 |
| **Educe** | **单调下降** | 知识复利 + 行为编译 |

这条曲线（**The Descent Curve**）是整个项目的核心证据，也是当前最高优先级的验证目标。

### 1.3 五条公理

进化引擎建立在五条不可妥协的公理之上：

1. **代谢**（淘汰 / 冲突仲裁）— 系统命脉。没有淘汰就没有进化。
2. **确定性增加** — 进化 = 校准良好的确定性增加。
3. **环境嵌入** — 项目即环境，Seed 栖息其中。
4. **渐进固化** — 从慎思（deliberate）到反射（reflex）的运行时编译。
5. **机制与认知分离** — 框架 = 资产容器 + 零判断；模型 = 所有决策。

### 1.4 三方角色

公理 5（机制与认知分离）落地为严格的三方职责划分：

| 角色 | 职责 |
|---|---|
| **框架** | AssetStore + ContextAssembler + Ledger（**零判断**，只搬运资产，不做决策） |
| **模型** | **所有决策**（包括"要不要问用户"这种元决策） |
| **用户** | 声明边界 + 确认不可逆操作 + 提供反馈 |

---

## 2. 架构设计与核心组件

### 2.1 核心循环（V3 — 当前唯一 loop）

```
用户消息 → orchestrator._action_loop()
  → action_loop_v3()
    → ConversationTruth（单一数据源：records / tier / project / compact）
    → Plan（pinned slot，模型维护，status: working | done）
    → Challenge（Situation 驱动，模型必须回应）
    → action 执行 → 结果回注 truth
    → _strip_plan()（剥离 <plan> / <challenge> / XML）
    → parse_actions()（清理 reply_text）
  → WS 推送前端
```

### 2.2 三大核心抽象

#### ConversationTruth（单一数据源）
- 消灭"两套数据源"问题，所有状态统一存放。
- 文件：`educe/core/conversation_truth.py`

#### Plan（模型维护的计划槽）
- pinned slot，由模型维护，状态机 `working | done`。
- 模型自知进度、自决停止，替代传统的 `max_rounds` 硬限制。

#### Challenge（态势驱动的质询）
- 由 Situation 态势感知触发（如重复操作、action error）。
- 模型必须回应 Challenge，形成自我校准。

### 2.3 关键子系统

| 子系统 | 职责 |
|---|---|
| **Action Normalizer** | 归一化：`use_tool` / native tool call / markdown code block / 自然 XML / python promotion |
| **Situation** | 态势感知：`turns_without_edit` / `file_edit` 追踪 |
| **不可逆判定** | 物理识别危险操作（`rm -rf` / `kill` / `DROP` / `git push --force`） |
| **L1 澄清刹车** | 高危操作检测，触发澄清 |
| **ProjectMemoryStore** | 复利记忆：`fact / scar / convention` + 频率沉淀 + 遗忘衰减 |
| **CredentialStore** | 凭据管理 + subprocess env 注入 |
| **VerbosityOrgan** | 信号检测 + confidence 状态机 + 校准回流 |
| **CompositeSkill** | L0–L4 多级技能 + 编译 + 运行时注入（21 个技能） |
| **ReflexRouter** | L3 直接执行 + Guard 编译器 |
| **Ledger** | 结构化日志（13 事件类型 + session 生命周期） |

### 2.4 三维进化模型

- **懂（知识）** → ProjectMemoryStore 的 fact 积累
- **熟（行为）** → CompositeSkill / ReflexRouter 的行为编译
- **醒（边界 / scar）** → scar 记忆 + 不可逆判定 + 澄清刹车

> 护城河不在"行为编译"（会被模型进步抹平），而在"知识复利"（与模型能力正交）。

### 2.5 前端架构

- **技术栈**：Next.js + Tailwind CSS
- **布局**：单列 + 内联展开
- **核心组件**：Action 折叠卡片、ToolStreamCard、进化态势条、Activity Timeline

### 2.6 代码规模

| 文件 / 模块 | 规模 |
|---|---|
| `educe/core/orchestrator.py` | 1687 行 |
| `educe/core/action_loop_v3.py` | ~340 行 |
| `educe/core/conversation_truth.py` | ~270 行 |
| 契约测试 | 6 case |
| 冒烟测试 | 3 case |
| Python 后端核心代码 | 约 8000 行 |

---

## 3. 当前能力清单

### 执行能力
- Shell 执行（连续多轮 + 后台进程 + cd 自动更新）
- 文件操作（read_dir / read_file / write_file / edit_file / search_in_file / read_lines）
- Action 归一化（5 种表达形式）
- 不可逆判定 + 用户确认

### 进化能力
- 复利记忆（fact / scar / convention + 频率沉淀 + 遗忘衰减）
- CompositeSkill（L0–L4 多级 + 编译 + 运行时注入，21 个技能）
- ReflexRouter（L3 直接执行 + Guard 编译器）
- VerbosityOrgan（confidence 状态机 + 校准回流）

### 交互与上下文
- Plan/Challenge 架构（模型自知 + 自决停止）
- ConversationTruth 单一数据源
- Situation 态势感知
- 文件引用（@ 选择器 + 附件注入）
- 凭据管理

### 可观测性
- 结构化日志（13 事件类型）
- 过程透明度（流式输出 + ToolStreamCard）
- Benchmark Runner v2（30 case + Judge 评分）

---

## 4. 验证成果

| 验证项 | 结果 |
|---|---|
| Kimi-K2 acceptance | **0.722（+52%）** |
| Qwen3.6 acceptance | 0.553（TECH 域 **0.90**） |
| Nudge 精度 | Precision = **1.00**，Recall = **0.89** |
| Shadow A/B | **41% 延迟减少**，CODE 域接管精确率 **100%** |
| 对抗测试 | 27 项 **0 崩溃** |
| E2E 测试 | 24 场景全通过 |
| 日志反哺闭环 | 161 fixtures，95% 修复率 |

> **尚未验证**：The Descent Curve（成本随经验单调下降）仍缺曲线证据。

---

## 5. 已知限制与待办

### 核心缺口
- **The Descent Curve 尚未证明** — 核心命题缺乏直接证据

### 遗留功能
- ConversationTruth WARM 预算精度
- confirm 后状态恢复
- session_env 持久化接入

### Known Limitations
- 裸文本中闭合 action 标签对会被误匹配为 action（极低概率，代码块内已安全）

---

## 6. 下一步路线图

### P0 — The Descent Curve（最高优先级）
- 证明核心命题：行为成本随经验单调下降
- 实验：3 任务族 × 15 次，记录 (llm_calls, tokens, wall_clock, correct)
- 产出：`reproduce_descent.py`（任何人 clone 后一条命令产出曲线）
- **在拿到曲线前，所有新功能建造都视为沉没成本**

### P1 — 遗留功能修复
- WARM 预算 / confirm 状态 / session_env 持久化

### P2 — 前端 UI 美化

### P3 — 开源发布准备
- reproduce_descent.py + 文档 + 许可证 + 贡献指南

---

## 7. 开发规范

### 第一原则：尊重公理
框架做搬运，模型做判断。写 `if` 业务逻辑前先问：这个判断应该交给模型吗？

### 单一数据源原则
所有会话状态经过 ConversationTruth。禁止引入第二套并行数据源。

### 单一 Loop 原则
`action_loop_v3()` 是唯一执行循环。不复活废弃 loop，不引入并行循环。

### 进化优先于功能
拿到 Descent Curve 之前冻结新功能开发。

### 测试要求
- 核心变更需通过契约测试（6 case）+ 冒烟测试（3 case）
- E2E 验证：Playwright MCP 交互 → 截图 → 日志 → Opus 4.8 审查 → PASS 后提交

### 代码组织
- 后端核心：`educe/core/`
- 前端：`web/`（Next.js + Tailwind）
- 测试：`tests/contract/` + `tests/smoke/`
- 文档：`docs/`

---

*文档基于 Session 12（2026-06-26）后的项目状态。由 Opus 4.8 审查通过。*
