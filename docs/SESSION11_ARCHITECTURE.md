# Educe Session 11 架构变化记录

> 2026-06-24~25，本轮完成了 Action Loop 的核心重构。

---

## 本轮新增/重构模块

| 模块 | 文件 | 职责 | 状态 |
|------|------|------|------|
| **Action Loop V2** | `educe/core/action_loop_v2.py` | Plan-aware 循环 + Challenge + 无 max_rounds | ✅ 已切换 |
| **Plan 解析器** | `educe/core/plan_parser.py` | 从 LLM output 提取 `<plan>` 块 + 压缩 | ✅ |
| **Loop Context** | `educe/core/loop_context.py` | 三层滑动窗口（hot/warm/frozen）+ pinned slot | ✅ |
| **Session State** | `educe/core/session_env.py` | 环境事实层（永不压缩，每轮注入 `<env>`） | ✅ |
| **ContextAssembler** | `educe/core/context_assembler.py` | 按意图召回相关资产 | ✅ |
| **Irreversibility** | `educe/core/irreversibility.py` | 物理不可逆判定（唯一硬逻辑） | ✅ |
| **测试系统** | `tests/conftest.py` + `tests/contract/` + `tests/smoke/` | L2 契约 + L3 冒烟 | ✅ |
| **Skills (按需加载)** | `educe/config/skills/plan_protocol.md` | Plan 协议教学（challenge 时注入） | ✅ |

---

## Action Loop V2 架构

```
用户输入
    │
    ▼
┌─────────────────────────────┐
│ @path 检测 → SessionState    │  ← 环境事实固定
│ inject_env(<env>)            │  ← 每轮注入，永不压缩
│ Pinned Plan                  │  ← 模型自己的状态
│ Situation                    │  ← 框架计算的客观事实
│ Challenge (按需)             │  ← 检测异常时强制回应
└─────────────────┬───────────┘
                  ▼
            LLM 调用
                  │
    ┌─────────────┼─────────────┐
    │             │             │
 status=done   有 action      纯文字
    │             │             │
    ▼             ▼             ▼
  终止        执行 action     推送回复
              │                终止
              ▼
         结果追加 messages
         cwd 跟踪
         Challenge 检测
              │
              ▼
         下一轮...
```

**终止条件**：
1. `status: done`（模型自决）
2. 纯文字回复（无 action）
3. wall_clock 120s 超时

---

## Session State 层

```
SessionState（永不压缩，跨轮保持）
├── project_root: /Users/JD/others/json解析  [source: AT_REFERENCE]
├── cwd: /Users/JD/others/json解析/devkit
├── pinned_paths: [{path, source, turn_id}]
└── confirmed_facts: {key → Fact(value, source, verified)}

注入格式（<env> 块）:
<env>
root: /Users/JD/others/json解析
cwd: /Users/JD/others/json解析/devkit
pinned: /Users/JD/others/json解析/
facts:
  项目类型=零售发票工具+DevKit (verified)
</env>
```

**来源优先级**：USER_EXPLICIT(3) > TOOL_VERIFIED(2) > AT_REFERENCE(1) > INFERRED(0)

---

## Challenge 机制

| 触发条件 | 阈值 | 效果 |
|---------|------|------|
| 重复操作（同一 target） | 3 次 | 要求换策略或停止 |
| Plan 缺失 | 第 3 轮起 | 注入 plan_protocol skill |
| 长时间无回复 | 10+ 轮 | 要求评估是否该停 |
| 冷却 | 至少隔 2 轮 | 避免噪音 |

---

## 三层压缩窗口

| 层 | 保留轮次 | 格式 | 压缩触发 |
|----|---------|------|---------|
| Hot | 最近 5 轮 | 完整原文 | — |
| Warm | 5~20 轮 | 单行机械摘要 | 自动滑动 |
| Frozen | 20+ 轮 | 块摘要(500字) | token > 20K |

---

## 测试体系

```bash
# 每次 commit 前（<20s，¥0）
pytest tests/contract/ -v

# push 前（需要真 LLM API）
pytest tests/smoke/ -v
```

契约测试守护：chunk 时序 / 多轮回复 / shell 输出 / artifact / confirm 阻塞

---

## 本轮删除/废弃

| 删除的 | 原因 |
|--------|------|
| `safe_categories` / `_is_dangerous_shell` | 框架不判断安全性 |
| `Evidence-Gated Nudge` / `should_nudge` / `should_restrict` | 框架不强制收敛 |
| `needs_confirm = {"build", "plan"}` | 框架不替模型决策 |
| `build_context()` 作为主 system prompt | 改用 `build_system_prompt()` |
| WelcomeCard 文件列表 | 环境信息不展示给用户 |

---

## 已知遗留问题

| 问题 | 严重度 | 状态 |
|------|--------|------|
| Challenge 与 session_env 深度协同（工具失败对照 root） | P1 | TODO |
| 压缩窗口在极长会话中的 LLM 摘要（方案 B） | P2 | TODO |
| Plan 协议模型遵循率（Qwen3-235B ~60%） | P2 | Challenge 兜底 |
| 相对路径 @ 引用支持 | P3 | 目前只支持绝对路径 |
| session_env 持久化接入 session 存储 | P2 | TODO |
