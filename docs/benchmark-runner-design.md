# Benchmark Runner v2 — Opus 4.8 讨论结论 + 实施状态

> 2026-06-17，与 Opus 4.8 讨论后确认方案

## 架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Runner 方式 | 直接 import orchestrator | 共用生产路径，nudge/timeout 逻辑在 orchestrator 内部 |
| 执行方式 | 串行 | 30 case × 2 model = 60 次，避免限流/日志竞争 |
| 环境隔离 | 每 case 独立 workspace 目录 | 防文件冲突/假性成功 |
| Judge 策略 | L1 全自动 / L2 部分 / L3 judge | 成本控制 + 程序化分为 0 时跳过 judge |
| 评分 | 0~1 连续分，非 bool | 部分完成不该是 0 |

## 目录结构

```
.educe/benchmark_runs/
  {run_id}/
    {model}/
      summary.json           # 汇总
      {case_id}/
        workspace/           # 模型操作的隔离目录
        logs/sessions/...    # 日志三层（复用 SessionLogger）
        result.json          # 验收结果 + 事件 + 指标
```

## 日志→指标提取（已实现）

```python
extract_metrics(events) → {
    total_rounds, llm_time_s, tool_call_count,
    action_dist, nudge_count, safety_net_count,
    error_count, continuation_count,
    rounds_to_first_meaningful, redundant_read_ratio
}
```

## 当前状态

- [x] BenchmarkRunner 核心框架（benchmark_runner.py）
- [x] extract_metrics 从 events.jsonl 提取指标
- [x] Quick test 验证（3 case, Kimi-K2: 3/3 completed, 2/3 acceptance）
- [x] E2E 前端验证通过
- [ ] 完整 30 case 定义（含验收函数）
- [ ] Judge 评分模块（调 Claude API）
- [ ] 双模型对比（Kimi-K2 vs Qwen3.6）
- [ ] 结果分析报告

## Opus 提醒的坑

1. **单次运行 = 噪声样本** — 关键 case 需多次运行看方差
2. **judge 稳定性** — 结构化输出 + anchor rubric + 盲评 + 方差检查
3. **judge 分两类** — 评产出只给最终文件，评决策必须给 trace
4. **环境泄漏** — 确认无 module-level 单例跨 case 污染
5. **中间态建模** — status 区分 completed/partial/timeout/error
6. **客观指标校验 judge** — 如果 judge 打 5 分但 redundant=8 nudge=4，说明 rubric 有问题
