# 日志反哺治理层 — 设计方案

> 2026-06-17，与 Opus 4.8 讨论确认

## 核心原则

**只补漏不增益** — 反哺只用于修复失败/漏报，不强化已成功路径。防止自我强化偏差。

## 阶段 1：失败回放管线 + Normalizer 闭环（最高杠杆）

```
失败采集器：
  扫 L1 events.jsonl → 筛 tool_result.status == error
  关联 L2 trace.jsonl → 取 llm_output（原始）+ tool_result（错误信息）
  → 落地为 tests/fixtures/failures/{hash}.json

回放器：
  fixture → parse_actions → 断言（以前失败，现在通过了吗？）

Normalizer 改进后：
  对全部 fixtures 回放 → 红转绿数 / 新增红数
```

**架构前提**：parse_actions 必须能脱离 LLM、脱离真实 fs 被独立调用（已满足）。

## 阶段 2：治理机制反事实校准

混淆矩阵：
```
              实际结局好    实际结局坏
触发了干预      误报(扰民)     正确拦截
没触发干预      正确放行       漏报(危险)
```

从历史 session 的 nudge_triggered / safety_net 触发后续 outcome 做统计：
- 干预后结局变好 = 刹车踩对了
- 未干预但 outcome=failure = 漏报，需收紧阈值

## 防偏差机制

1. 反哺只处理失败样本，不碰成功样本
2. 失败 fixtures 永不退场（只增不减）
3. 盲区显式化：样本 < 阈值的指令类型标记"治理未验证区"
4. 每条 normalizer 规则关联来源 fixture hash（可回滚可问责）

## 风险

- 日志反馈到 prompt = 让仪表盘开车 → 拒绝
- 统计不足时学到的是噪声 → 阶段 1 用确定性规则不用统计
- 强化偏差 → "只补漏"原则 + 盲区可视化
