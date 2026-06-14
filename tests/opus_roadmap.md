# Educe 架构路线图

# Educe 进化路线图：从代谢到生殖

在给路线图之前，我要先做一个**判断**，因为这决定了整张图的骨架。

你的愿景里最锋利、也最难的一刀是：**"代谢回路"——把试错蒸馏成结构改变**。其他三条（三层下沉、收敛优先、护城河）都是这一条的衍生物或前提。

- 三层下沉 = 代谢的**方向**（沉淀往哪沉）
- 收敛优先 = 代谢的**前提**（弱模型才能稳定产生可观察的因果）
- 护城河 = 代谢的**结果**（沉淀久了就长出身体）

所以路线图的真正主线是：**让"后果"能够回流并改变 seed 自身**。你现在所有的现成件——激发引擎、行为循环、Connector、知识系统——都是"代谢"的**器官前体**，但它们之间还没接成回路。**血还没流起来。**

下面用发育阶段命名，但我把它重新校准为更准确的隐喻。

---

## 阶段总览

| 阶段 | 生物隐喻 | 涌现的能力跃迁 | 时间 |
|---|---|---|---|
| **0** | 受精卵着床 | seed 能**感知自己行为的后果**（闭环可观测） | 2-3 周 |
| **1** | 卵裂 + 代谢启动 | seed 能**因后果改变下次行为**（短回路代谢） | 4-6 周 |
| **2** | 分化 | 重复路径**自动下沉为技能**（意图层→技能层） | 6-8 周 |
| **3** | 神经反射弧 | 高频技能**内化为反射**（技能层→反射层，跳过推理） | 6-8 周 |
| **4** | 器官形成 | seed 与特定环境**长出不可迁移的结构**（护城河） | 8-12 周 |
| **5** | 出生 | seed 能**衍生子 seed**（自我复制 + 变异遗传） | 持续 |

**关键洞察：阶段 0-1 才是真正的"心跳"。** 没有可观测的后果回流，后面所有"进化"都是开环的随机游走（你现在的 +22% 大概率就是开环优化的天花板信号）。

---

## 阶段 0：着床 —— 让后果可观测

> **能力跃迁：从"seed 做了什么"到"seed 知道自己做的事产生了什么后果"**

这是整个代谢回路的传感器层。没有它，"固化或淘汰"就没有依据。

### 交付物
1. **因果账本（Consequence Ledger）** —— 每个决策点记录三元组：
   ```
   (context_snapshot, action_taken, outcome)
   ```
   其中 outcome 分**即时后果**（环境返回值、报错、用户确认/拒绝）和**延迟后果**（占位，阶段 1 填充）。

2. **Outcome Hook** —— 在行为循环的每个 action 执行后强制写账本。

3. **后果可视化** —— 前端 ArtifactCard 增加"后果回放"视图：这个决策导致了什么。

### 复用 / 重构 / 新建
| 项 | 处理 |
|---|---|
| 行为循环（决策树 prompt） | **复用**，但在 action 节点插入 hook |
| 知识系统（分层记忆） | **复用**作为账本的存储底座，但要新增 `outcome` 维度索引 |
| ConnectorRegistry/MCP | **复用**，capability 调用处包裹一层 outcome 捕获 |
| WebSocket/前端 | **复用**，加一个事件类型 `consequence` |
| 因果账本本身 | **全新**（但很薄，是一张结构化日志表 + schema） |

### 验证标准
- 在 35B 模型上跑 100 个真实任务，**95%+ 的决策点能产出结构化的 (context, action, outcome) 三元组**（不是自然语言日志，是可查询的结构）。
- 能回答一个查询：**"过去 7 天里，哪类 action 的 outcome 失败率最高？"** —— 如果能，说明代谢有了味觉。

### 为什么这是第一步而不是别的
因为它**独立交付价值**：哪怕后面全停了，你也得到了一个"行为-后果可观测"的系统，这本身就是 debug 和信任的巨大提升。而且它**不动任何现有逻辑**，纯增量。

---

## 阶段 0 的具体可执行动作（下一步，可直接写代码）

### Step 1：定义因果账本 schema

```python
# educe/metabolism/ledger.py

from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class OutcomeType(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    USER_REJECTED = "user_rejected"
    USER_CONFIRMED = "user_confirmed"
    PENDING = "pending"        # 延迟后果占位，阶段1回填

class ConsequenceRecord(BaseModel):
    record_id: str
    seed_id: str
    decision_point: str          # 决策树里哪个节点
    context_snapshot: dict       # 决策时的关键上下文（裁剪过，非全量）
    action_taken: dict           # capability名 + 参数
    outcome_type: OutcomeType
    outcome_detail: dict         # 返回值/报错/用户反馈
    immediate_reward: Optional[float] = None   # -1.0 ~ 1.0，先用规则打
    delayed_outcome_ref: Optional[str] = None  # 阶段1用
    created_at: datetime
```

### Step 2：在 capability 执行处包一层（不改 connector 本身）

```python
# educe/metabolism/outcome_hook.py

import uuid, time
from educe.metabolism.ledger import ConsequenceRecord, OutcomeType

class OutcomeCapturer:
    def __init__(self, ledger_store, reward_fn):
        self.ledger = ledger_store
        self.reward_fn = reward_fn

    async def wrap(self, seed_id, decision_point, context, action_fn, action_meta):
        ctx_snap = self._snapshot(context)   # 裁剪：只留决策相关字段
        record_id = str(uuid.uuid4())
        t0 = time.time()
        try:
            result = await action_fn()
            otype = OutcomeType.SUCCESS
            detail = {"result": self._truncate(result), "latency": time.time()-t0}
        except Exception as e:
            otype = OutcomeType.FAILURE
            detail = {"error": str(e), "type": type(e).__name__}
            result = None

        record = ConsequenceRecord(
            record_id=record_id,
            seed_id=seed_id,
            decision_point=decision_point,
            context_snapshot=ctx_snap,
            action_taken=action_meta,
            outcome_type=otype,
            outcome_detail=detail,
            immediate_reward=self.reward_fn(otype, detail),
            created_at=time.time(),
        )
        await self.ledger.append(record)
        await self._emit_ws(record)   # 推前端
        if otype == OutcomeType.FAILURE:
            raise  # 不吞异常，只是顺路记录
        return result
```

### Step 3：最朴素的即时奖励函数（先规则，别上模型）

```python
# educe/metabolism/reward.py

def immediate_reward(otype, detail) -> float:
    if otype == OutcomeType.SUCCESS:
        latency = detail.get("latency", 0)
        return 1.0 if latency < 2.0 else 0.7   # 快慢有差别
    if otype == OutcomeType.USER_CONFIRMED:
        return 1.0
    if otype == OutcomeType.USER_REJECTED:
        return -1.0
    if otype == OutcomeType.FAILURE:
        return -0.8
    return 0.0
```

### Step 4：行为循环接入点（最小侵入）

```python
# 在你现有的 behavior loop 里，原来直接调 capability 的地方：

# 旧：
# result = await connector.invoke(cap_name, params)

# 新：
result = await outcome_capturer.wrap(
    seed_id=seed.id,
    decision_point=current_node.name,
    context=working_context,
    action_fn=lambda: connector.invoke(cap_name, params),
    action_meta={"capability": cap_name, "params": params},
)
```

### Step 5：前端加事件类型
WebSocket 推 `{"type": "consequence", "data": record}`，ArtifactCard 下方加一行后果状态徽章（✅/❌/⏳）。

**这一步做完，你就有了第一个可观测的代谢闭环传感器。** 大概 2 周内可验证。

---

## 阶段 1：代谢启动 —— 让后果改变下次行为

> **能力跃迁：从"记录后果"到"因为上次失败，这次换个走法"**

这是**心跳第一次自己跳**。

### 核心机制
1. **延迟后果回填**：阶段 0 留的 `PENDING` 现在要被回填——一个 action 的真正后果可能在 5 分钟后才显现（用户改了你生成的东西、下游报错）。需要一个 **outcome reconciler**，把延迟信号关联回 record。
2. **决策前检索因果**：决策时，先查"在相似 context 下，这个 action 历史 outcome 如何"，把这个证据注入 prompt。这是**用记忆指导当下**——代谢的最小闭环。
3. **激发引擎改造**：你现有的变异/A-B/淘汰，**评分函数从开环（人工/猜测）换成账本驱动的真实后果累积奖励**。这是最重要的重构。

### 复用 / 重构 / 新建
| 项 | 处理 |
|---|---|
| 激发引擎 v0.4 | **重构核心**：fitness function 改为 `Σ(account ledger rewards)`，变异方向由失败模式聚类引导，不再纯随机 |
| 知识系统召回 | **复用 + 扩展**：召回时增加"按 context 相似度查历史 outcome" |
| 因果账本 | **复用**，激活 delayed_outcome 字段 |
| Outcome Reconciler | **全新**：异步进程，关联延迟信号 |

### 验证标准（最关键的一关）
- 同一类任务跑两批：A 组关闭因果注入，B 组开启。**B 组在 35B 上的失败率相对下降 ≥ 20%**，且这个下降**来自账本而非更大的 prompt**（消融实验：只加无关上下文不应有同等效果）。
- **闭环优于开环的证明**：把激发引擎的 fitness 从账本驱动换回开环，演化收益应显著退化。如果不退化，说明你的"代谢"是假的。

> ⚠️ 这一关如果过不了，**不要往下走**。它会告诉你：你的后果信号要么太稀疏、要么太噪声、要么 context_snapshot 裁剪错了关键变量。这恰恰是路线图最有价值的地方——它强迫你在地基上验证愿景是否成立。

---

## 阶段 2：分化 —— 重复路径下沉为技能

> **能力跃迁：从"每次都推理"到"这条路我走熟了，打包成一个动作"**

这是三层下沉的**意图层 → 技能层**。

### 核心机制
- **路径挖掘**：在账本里挖**高频 + 高奖励 + 低方差**的 decision-point 序列。
- **技能固化**：把这样的序列**编译成一个新的 composite capability**，注册进 ConnectorRegistry——下次意图层可以直接调用它，不用展开推理。
- **收敛优先在这里体现**：技能固化后，弱模型在意图层面对的分支变少了，环境切面变小了。

### 复用 / 重构 / 新建
| 项 | 处理 |
|---|---|
| ConnectorRegistry | **复用 + 扩展**：支持"动态注册由账本编译出的 composite capability" |
| 激发引擎 | **复用**：技能本身成为新的演化单元 |
| 路径挖掘器 | **全新**：序列模式挖掘（可以朴素，频繁子序列 + 奖励过滤） |

### 验证标准
- 系统能**自动**（无人工）从账本中提出 ≥ 5 个 composite skill，且这些 skill 被调用时**平均决策步数下降 ≥ 40%**，奖励不下降。
- 35B 模型在有这些 skill 后，**同任务 token 消耗下降**（因为不展开推理了）——这是"收敛"的硬指标。

---

## 阶段 3：反射弧 —— 技能内化为反射

> **能力跃迁：从"调用技能要先想要不要调"到"看到这个 pattern 直接做，跳过 LLM"**

技能层 → 反射层。这是性能和护城河的双重跃迁。

### 核心机制
- 对**超高频 + 超稳定**的技能，训练一个**轻量分类器/规则**（甚至不是 LLM），直接 context → action，**绕过决策树 prompt**。
- LLM 退居"反射失败时的兜底"和"新情况的探索者"。

### 验证标准
- 高频路径**有 ≥ 30% 的决策不再经过 LLM**，整体延迟下降，准确率不降。
- 这是你第一次能说"系统的一部分已经不依赖模型了"——**身体开始独立于大脑**。

---

## 阶段 4：器官形成 —— 长出不可迁移的结构（护城河）

> **能力跃迁：从"通用 agent"到"这个 seed 离开了这个环境就废了，但在这个环境里无可替代"**

前三阶段沉淀的技能/反射/因果账本，是**针对特定环境**长出来的。这一阶段是把它们**显式结构化为"器官"**——环境特定的、共演化的结构。护城河在此显性化。

（此阶段架构细节依赖 0-3 的实际产物，先不过度设计。）

---

## 阶段 5：出生 —— seed 衍生子 seed

> **能力跃迁：成熟 seed 能 fork 出携带"遗传"（