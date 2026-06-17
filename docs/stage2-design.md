# Educe 阶段 2 设计 — 路径下沉为技能

> 2026-06-17，与 Opus 4.8 讨论。基于正确定位（进化引擎）。

## 核心概念

阶段 2 = 公理 2（三层下沉）的首次物理实现：
- 重复稳定的多步决策序列 → 编译为 CompositeSkill → 下沉到技能层
- 从"每步都慢推理"到"一口气做完"

## 1. 路径挖掘器

### 数据结构

```python
@dataclass
class DecisionPoint:
    session_id: str
    seq: int                    # session 内序号
    context_sig: str           # context 的结构化签名（降维投影）
    action: str
    outcome_reward: float
    outcome_variance: float
    token_cost: int

@dataclass
class PathCandidate:
    steps: tuple[str, ...]              # (action_A, action_B, action_C)
    context_precondition: str          # 触发该路径的入口 context 签名
    support: int                       # 出现次数
    mean_reward: float
    reward_variance: float
    mean_token_cost: int
    decision_steps_saved: int          # = len(steps) - 1
```

### 算法（最小可行：n-gram 滑窗）

1. 按 session 分组，按 seq 排序
2. 滑窗提取 2..4 长度的 action 子序列
3. 三重过滤：高频（support≥3）+ 高奖励 + 低方差（收敛优先公理）
4. 去重：长路径吸收子路径

### context_sig 是命门

原始 context 高维，直接比对永远不重复。需要有损投影：
`{任务类型, 关键资源状态, 上一步outcome类别}` → 可哈希桶

## 2. CompositeSkill 结构

```python
@dataclass
class CompositeSkill:
    skill_id: str
    trigger: ContextMatcher          # 何时激活
    steps: list[AtomicCapability]    # 原子能力序列
    binding: list[DataFlow]          # 步骤间参数传递
    provenance: PathCandidate        # 来源证据
    confidence: float
    fallback: str                    # 失败时回退意图层
```

### 与 BehaviorManifest 的关系

| | BehaviorManifest（阶段1） | CompositeSkill（阶段2） |
|---|---|---|
| 单位 | 单条规则 if-then | 多步序列编译产物 |
| 作用层 | 意图层的决策偏置 | 技能层的执行替换 |
| 决策成本 | 仍需逐步决策 | 一次激活，N步免决策 |

**正确关系：CompositeSkill 由多条 BehaviorManifest 规则"凝结"而成。**

## 3. 验证方法

A/B 对照（可用现有 benchmark）：
```
baseline:  关闭 CompositeSkill 跑 30 case → 记录 (decision_steps, tokens)
treatment: 开启 CompositeSkill 跑 30 case → 记录 (decision_steps, tokens)

通过条件：
  decision_steps_treatment / decision_steps_baseline ≤ 0.6
  AND token_treatment < token_baseline
  AND task_success_rate 不下降
```

## 4. 阶段 1→2 的 Gap

### 🔴 阻断性（必须先解决）

1. **序列归属**：账本必须有 session_id + step 时序（→ 检查已有日志系统是否满足）
2. **context 签名/投影函数**：降维投影不存在 → 挖掘器无法工作

### 🟡 削弱效果

3. **延迟后果回填**：长路径 reward 估计有偏
4. **因果检索**：给定 context 检索可用技能 = 阶段1欠的账
5. **账本规模小**：可用 benchmark 30 case + 161 fixtures 合成数据先灌

## 5. 质变

- **用户直接感知**：更快（-40%步数）、更便宜（token下降）
- **行为感知**：系统对熟悉任务"不再啰嗦"，一口气做完 → 从工具到伙伴
- **风险**：技能固化 = 自作主张整段执行，必须可被治理层一票否决

## 行动清单

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | 确认序列归属 | 检查日志/账本是否有 session_id + seq |
| P0 | 设计 context_sig 投影函数 | 决定降维到哪些维度 |
| P1 | 实现路径挖掘器 MVP | n-gram 滑窗 + 三重过滤 |
| P1 | 实现 CompositeSkill 结构 | trigger + steps + binding + fallback |
| P2 | 因果检索（还阶段1旧账） | 给定 context 检索可用技能 |
| P2 | A/B 验证 | 用 benchmark 30 case 做对照 |
