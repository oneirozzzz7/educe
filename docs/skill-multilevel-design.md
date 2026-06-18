# Opus 4.8 讨论：CompositeSkill 多级形态设计

> 2026-06-18，用户质疑"skill 就只能是一段文本描述？"引发的深度讨论

## 核心结论

Skill 不是静态的文本描述。它是一个从 Hint 到 Pure-Reflex 的**连续谱系**：

| Level | 名称 | LLM 角色 | 适用 |
|-------|------|---------|------|
| L0 | Hint | 完全自主决策 | 路径出现 2-3 次 |
| L1 | Template | 填空+确认 | 结构稳定，参数依赖任务 |
| L2 | Plan-Graph | 一次性审批 DAG | 多步强依赖，顺序固化 |
| L3 | Guarded-Reflex | 仅守卫失败时唤醒 | 高频确定性低风险 |
| L4 | Pure-Reflex | 完全旁路 | 极高频幂等零风险 |

**同一个 skill 在生命周期中可升降级。** 不是 5 种不同的 skill。

## 关键设计决策

### 升级证据（保守）
- L0->L1: invocations >= 5 + 路径结构稳定
- L1->L2: acceptance >= 80% + patch_rate <= 20% + invocations >= 10
- L2->L3: acceptance >= 95% + success >= 95% + 能编译守卫 + 治理批准
- L3->L4: guard_pass >= 99% + 只允许 readonly/idempotent

### 降级（激进）
- 单次失败即降一级
- guard_pass_rate 跌破 0.9 → 降到 L1
- 守卫漏洞（通过但造成损害）→ 降到 L0 + 冻结

### 安全红线
> 反射弧的前提是"判断逻辑已完全外化为 guard"。如果正确性仍依赖 LLM 语境理解，永远不升 L3。

- destructive safety_class → 封顶 L1
- reversible → 封顶 L3（须有 rollback_plan）
- readonly/idempotent → 可达 L4

### 执行循环介入点
```
user_input
  -> [介入点D] ReflexRouter（L3/L4 在此拦截）
  -> [介入点A] system_prompt 注入（L0 Hint）
  -> LLM
  -> parse_actions
  -> [介入点B] action 预填充（L1 Template）
  -> [介入点C] 整段接管（L2 Plan-Graph, LLM 审批）
  -> execute
```

## 阶段 3 走向建议

1. 先建 L2（Plan-Graph + LLM 一次性审批）— 性价比最高
2. ReflexRouter 作为独立组件先落地（即使初期只透传）
3. 守卫编译器是阶段3真正技术难点 — 单独立项
4. 统计账本和因果账本打通：outcome_success 必须来自真实下游反馈

## 当前实现状态

- [x] 数据结构：CompositeSkill 支持 L0-L4 + stats + guards + safety_class
- [x] 升降级逻辑：check_upgrade() + record_outcome()
- [x] 向后兼容旧 registry
- [x] E2E 验证通过
- [ ] L2 Plan-Graph 渲染 + LLM 审批流程
- [ ] ReflexRouter 组件
- [ ] Guard 编译器
