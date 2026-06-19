# Educe 系统升级方案 — P0+P1 完整规格

*11 轮 Opus 4.8 讨论确认 · 2026-06-20*

---

## 一、系统定位

> "别的 AI 让你适应它。Educe 让你看着它适应你——而且你随时能改。"

---

## 二、核心架构：EvolutionEvent 总线

### 切入点
把 `_slog`（死日志）升级为活总线。一处改动打通全部6个前端-进化层断裂。

### 事件三层投影
```
emit(EvolutionEvent)
  ├→ LoggerProjection（同步先行，真相源，JSONL）
  ├→ FrontendProjection（WebSocket push，可失败）
  └→ LearnerProjection（更新 confidence 状态机）
```

### 进总线的事件（5个，三门槛全过）
- nudge_triggered → OBSERVE
- safety_net → OBSERVE/DEGRADE
- reflex_shadow → OBSERVE
- reflex_hit → SHIFT/CRYSTALLIZE
- skill_matched → SHIFT

### 不进总线（纯日志，15个）
session_start, clarify_resume, turn_start, llm_response, actions_parsed,
continuation, tool_result, clarify_pause, turn_end, organ_execute,
build_start, build_end 等。

---

## 三、EvolutionEvent JSON Schema (v1)

```json
{
  "schema_version": 1,
  "kind": "shift",
  "organ": { "family": "reflex", "id": "skill_cs_35637a" },
  "cause": "你连续 4 次查函数定义时都跳过了引用列表",
  "delta": { "action": "skip_references", "confidence_before": 0.55, "confidence_after": 0.70 },
  "phrase": "我注意到你不需要引用列表，下次直接跳过",
  "confidence": 0.70,
  "progress": null,
  "ts": 1781800596.123,
  "event_id": "evt_a1b2c3"
}
```

### Kind 枚举
OBSERVE → PROPOSE → SHIFT → CRYSTALLIZE | DEGRADE | REVERT

### Confidence 参数
- OBSERVE_GAIN = 0.15
- CONFIRM_JUMP = 0.40
- REVERT_DROP = 0.50（非对称）
- DECAY/DAY = 0.05
- HOT_THRESHOLD = 0.70 → PROPOSE
- CRYST_THRESHOLD = 0.90 + 至少1次CONFIRM → CRYSTALLIZE

---

## 四、校准回流格式

```json
{
  "type": "calibrate",
  "event_id": "evt_a1b2c3",
  "action": "confirm|revert|dismiss|snooze",
  "note": "可选补充说明",
  "counter_signal": false,
  "client_ts": 1781800620.456
}
```

---

## 五、前端 TypeScript 接口

```typescript
type EvolutionKind = "observe"|"propose"|"shift"|"crystallize"|"degrade"|"revert";

interface EvolutionEvent {
  schema_version: number;
  kind: EvolutionKind;
  organ: { family: string; id: string|null };
  cause: string;
  delta: Record<string, any>;  // 按 kind 分型
  phrase: string|null;
  confidence: number;
  progress: { current: number; threshold: number } | null;
  ts: number;
  event_id: string;
}

interface EvolutionState {
  connected: boolean;
  observations: EvolutionEvent[];
  proposals: EvolutionEvent[];
  recentShifts: EvolutionEvent[];
  skills: SkillSummary[];
  pendingCalibrations: Record<string, CalibrateMessage>;
}
```

### 兼容策略
前端遇到不认识的 schema_version → 降级显示 cause 字段（人话永远可读）。

---

## 六、PROPOSE 卡片设计

### reflex layout
```
⚡ 反射候选：查函数定义
  搜索定义 → 直接跳到行号（跳过引用列表）
  基于你最近 4 次的操作
  [接受]  [看看它学到了什么]  [不用(dismiss)]  [看情况(snooze)]
```

### verbosity layout
```
? 我觉得你偏好简短回答 (70%)
  基于最近 3 次你都跳过了解释部分
  [对，就这样]  [看情况]  [不，我要详细的(counter_signal)]
```

---

## 七、后端实现要点

### _slog 兼容层
```python
def _slog(self, type, name, **kwargs):
    self._log_only(type, name, kwargs)  # 无条件先写日志
    builder = EVOLUTION_EVENTS.get((type, name))
    if builder:
        event = builder.build(kwargs)
        if event and event.passes_three_gates():
            await self.bus.emit(event)
```

### 异步模式检测
- 热路径（同步）：append (action_type, context_hash) 到 ring buffer，O(1)
- 冷路径（异步）：worker 消费 buffer，做模式计数，决定 emit OBSERVE

### PROPOSE 推送时机
- 交互回合完整结束后，冷路径检查
- 同一时刻屏幕上最多一张 PROPOSE 卡片

---

## 八、视觉设计

### 反射气泡
- 瞬现（天然，不加动画）
- 左边缘 2px 青色条 (#22d3ee)
- 底部右角 ⚡ {skill_name} · {elapsed}s（图标青色，文字 text-2）
- Click 展开卡片 + [查看/编辑] [这次不对]

### 信息架构
- Layer 0：静默记录（OBSERVE 不弹 UI）
- Layer 1：状态跃迁推送（PROPOSE 卡片 / SHIFT toast）
- Layer 2：随时可查（educe status 面板）

---

## 九、哇时刻旅程

| 交互 | 前端展示 | confidence | 内部事件 |
|------|----------|-----------|----------|
| #1 | 👁 淡标记 "开始观察" | 0.15 | OBSERVE |
| #2-3 | "观察中 45%" | 0.30-0.55 | OBSERVE |
| #4 | "70%，提议" → PROPOSE 卡片弹出 | 0.70 | PROPOSE |
| 用户点[接受] | — | 0.70+0.40=跨0.90 | CRYSTALLIZE |
| #5 | ⚡ 反射触发 + 青色条 | ≥0.90 | reflex_hit |

---

## 十、分阶段路径

| 阶段 | 交付 | 验收 |
|------|------|------|
| P0 | EvolutionEvent 总线 + 注册表 + 三层投影骨架 | 旧功能零回归 |
| P1 | 器官A(verbosity双向) + 反射气泡 + PROPOSE + 校准回流 | 哇时刻跑通 |
| P2 | 器官C + status/log/diff/skills 四件套 | 完整协作系统 |
| P3 | 前端拆分 + 校准探针信号采集 | 可维护 + 双向闭环 |

---

## 十一、E2E 测试计划

### Happy path
5 次同类操作 → OBSERVE → PROPOSE → confirm → CRYSTALLIZE → 反射触发

### 边界用例
1. 5 次不同操作 → 不弹 PROPOSE（防假阳性）
2. snooze 后再做 → 会再弹（不永久消失）
3. dismiss 后再做 → 不再弹（永久压制）
4. WS 断线重连 → state 恢复
5. 乐观更新超时 → 重试/回滚
6. counter_signal → 反方向加权
7. 并发模式 → 只弹一张最高的
8. 连续违背固化反射 → DEGRADE 触发
