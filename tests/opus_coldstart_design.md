# 冷启动方案设计

# Educe 代谢系统阶段1：模拟用户 + 冷启动 + 数据积累完整方案

先说一个核心判断，再展开。

---

## 0. 先纠正一个隐藏的认知陷阱

你的合伙人那句话有个危险的暗示："框架应该比用户更超前，提前积累数据"。

**但模拟用户跑出来的数据，对真实用户的有效性是无法保证的——除非你的模拟用户产生的是"环境特异"而非"用户特异"的经验。**

这是整个方案的设计原则：

| 经验类型 | 例子 | 能否靠模拟用户冷启动 | 原因 |
|---------|------|------------------|------|
| **环境特异型** | "这个项目跑 test 前要先 `make prepare`" | ✅ 能 | 环境是客观的，模拟用户和真实用户面对同一个项目 |
| **路径依赖型** | "改了 config 后必须重启 server 才生效" | ✅ 能 | 因果链是客观的 |
| **跨任务可迁移** | "Python 项目 import 失败先查 venv 激活" | ✅ 能 | 通用工程知识 |
| **用户习惯型** | "这个用户总是省略文件路径" | ❌ 不能 | 模拟的习惯 ≠ 真实用户习惯，**过拟合风险** |

**结论：冷启动种子只应该固化前三类（环境/因果/迁移），用户习惯型必须靠真实交互在线学习。**

这直接回答了你的问题2：**两者都是，但分工明确**——

- **冷启动种子** = 环境特异 + 因果 + 可迁移（离线模拟积累，固化）
- **在线快速学习** = 用户习惯（前 3-5 轮交互捕获，不固化进种子）

---

## 1. 模拟用户策略

不要模拟"消息"，要模拟"**带意图的任务流**"。一个真实用户 session 是一个**有状态的任务图**。

### 1.1 用户建模：三层结构

```python
@dataclass
class SimulatedUser:
    persona: str           # 用户类型
    habits: List[str]      # 习惯（注入到指令生成）
    error_rate: float      # 犯错概率
    knowledge_gaps: List[str]  # 用户不知道的项目特异知识

@dataclass
class TaskFlow:
    """一个真实用户会连续做的多步任务"""
    goal: str              # 高层目标
    steps: List[TaskStep]  # 有依赖关系的步骤
    
@dataclass
class TaskStep:
    intent: str            # 这一步想干什么
    depends_on: List[int]  # 依赖前面哪些步骤的结果
    expected_pitfall: Optional[str]  # 预期会踩的坑（这是金矿）
```

### 1.2 关键：把"坑"设计成数据源

你上轮失败的原因是 trivial 任务没有坑。**这次要主动在 Educe 真实代码库里挖出真实的坑**。

先做一次人工探查（你自己花2小时跑），列出 Educe 项目里的真实环境特异性：

```yaml
# educe_env_pitfalls.yaml — 这是 ground truth，用来验证种子是否学对了
pitfalls:
  - id: P1
    trigger: "运行测试"
    naive_action: "pytest"
    failure: "ModuleNotFoundError / fixture 未初始化"
    correct_action: "先 <你项目真实的prepare命令> 再 pytest"
    type: environment_specific
    
  - id: P2
    trigger: "修改了 config/settings"
    naive_action: "直接看效果"
    failure: "改动不生效"
    correct_action: "重启 server 进程"
    type: causal
    
  - id: P3
    trigger: "import educe.xxx 失败"
    naive_action: "pip install"
    failure: "装错包 / 已经是本地包"
    correct_action: "检查是否 editable install / PYTHONPATH"
    type: transferable
  # ... 列出 8-15 个真实的坑
```

**这个 yaml 是整个验证的 ground truth。** 没有它你无法量化。

### 1.3 任务流生成器

```python
def generate_task_flow(user: SimulatedUser, pitfall: Pitfall) -> TaskFlow:
    """
    围绕一个真实 pitfall 构造任务流。
    用弱模型生成"自然语言指令"，但任务骨架是你控制的。
    """
    # 骨架固定（保证会触发坑），表达方式随机（模拟不同用户）
    steps = [
        TaskStep(intent="探查项目结构", depends_on=[]),
        TaskStep(intent=pitfall.trigger, depends_on=[0]),  # 触发坑
        TaskStep(intent="验证结果", depends_on=[1]),
    ]
    # 用 Qwen 把 intent 改写成模糊的、带用户习惯的自然语言
    return TaskFlow(goal=pitfall.trigger, steps=steps)
```

**核心技巧：任务骨架由你硬编码（保证科学性），自然语言表达由弱模型生成（保证多样性）。** 不要让弱模型决定任务结构，否则会退化成 trivial 任务。

---

## 2. 冷启动的精确定义

冷启动 = **新用户的第 0 轮，框架就能在 prompt 里注入与当前项目相关的环境/因果教训**。

可量化的冷启动目标：

```
对一个全新的、种子里没有直接见过的任务：
  - 无种子 baseline 成功率 = X%
  - 有种子注入成功率 = Y%
  冷启动有效性 = Y - X，且要求 Y > X 显著（不是噪声）
```

**两种冷启动能力分别验证：**

1. **同项目冷启动**：种子从 Educe 项目 train 任务积累，验证 Educe 项目 held-out 任务 → 验证环境特异经验
2. **跨项目冷启动**：种子从 Educe 积累，验证在另一个 Python 项目（找个小开源库）→ 验证可迁移经验是否过拟合到 Educe

---

## 3. 数据积累 → 提炼 → 固化 三阶段流水线

```
[Stage A: 积累]  模拟用户跑 N sessions → raw 因果账本
        ↓
[Stage B: 提炼]  聚类 + 频率统计 + 反事实验证 → 候选种子
        ↓
[Stage C: 固化]  held-out 验证 → 通过的成为冷启动种子
```

### Stage A: 积累

```python
def run_accumulation(pitfalls, n_sessions_per_pitfall=20, rounds_per_session=4):
    """
    每个 pitfall 跑 ~20 个 session（不同 persona/表达），
    每个 session 3-4 轮（探查→触发→失败→恢复）。
    
    关键：账本要记录失败和成功的对比！
    """
    ledger = CausalLedger()
    for pitfall in pitfalls:
        for persona in PERSONAS:        # 5 种 persona
            for trial in range(4):       # 每个 persona 4 次
                flow = generate_task_flow(persona, pitfall)
                run_session(flow, ledger, retriever=None)  # 冷跑，无注入
    return ledger
```

**规模估算：** 10 pitfalls × 5 personas × 4 trials × 4 rounds ≈ **800 个 action 三元组**。弱模型并发8、0.3s，约 800×0.3/8 ≈ **30秒纯推理**，加上工具执行开销实际约 **1-2 小时**。完全可跑。

### Stage B: 提炼（最关键，决定不过拟合）

不要把 raw 账本直接当种子。要做**因果显著性过滤**：

```python
def distill_seeds(ledger) -> List[CandidateSeed]:
    candidates = []
    # 1. 按 context 聚类（相似情境归并）
    clusters = cluster_by_context(ledger.entries)
    
    for cluster in clusters:
        # 2. 统计：同一 context 下，naive_action 失败率 vs correct_action 成功率
        naive_fail = count_failures(cluster, action_type="naive")
        correct_success = count_success(cluster, action_type="correct")
        
        # 3. 因果显著性门槛（核心过滤）
        support = len(cluster)              # 出现次数
        lift = correct_success_rate - naive_success_rate  # 因果增益
        
        if support >= 5 and lift >= 0.4:   # 阈值可调
            seed = CandidateSeed(
                context_pattern=cluster.context_signature,
                lesson=summarize_lesson(cluster),  # 弱模型总结
                support=support,
                lift=lift,
                type=infer_type(cluster),  # env/causal/transferable
            )
            candidates.append(seed)
    return candidates
```

**关键防过拟合机制：**
- `support >= 5`：偶发的不进种子
- `lift >= 0.4`：没有显著因果增益的不进种子
- 标注 `type`：用户习惯型的直接丢弃（不进冷启动种子）

### Stage C: 固化（held-out 验证）

```python
def validate_seeds(candidates, holdout_pitfalls, holdout_project):
    """
    用从未在积累阶段出现的任务/项目验证种子。
    """
    results = {}
    for seed in candidates:
        # A/B 测试：同一 held-out 任务，有种子 vs 无种子
        baseline = run_eval(holdout_tasks, retriever=None)
        with_seed = run_eval(holdout_tasks, retriever=SeedRetriever([seed]))
        
        results[seed.id] = {
            "same_project_lift": with_seed.educe - baseline.educe,
            "cross_project_lift": with_seed.other - baseline.other,
        }
    # 只保留 same_project_lift 显著为正的
    # cross_project_lift 用来标注 seed 是否真的可迁移
    return [s for s in candidates if results[s.id]["same_project_lift"] > THRESHOLD]
```

---

## 4. 具体执行方案（可直接写代码）

### 4.1 目录结构

```
educe/metabolism/stage1/
├── pitfalls.yaml              # 你手工挖的 ground truth（先做这个！）
├── personas.py                # 5 个 persona 定义
├── task_flow_gen.py           # 任务流生成
├── session_runner.py          # 跑 session，写账本
├── distill.py                 # Stage B 提炼
├── validate.py                # Stage C 验证
├── seeds_output.json          # 最终产出
└── run_all.py                 # 主流程
```

### 4.2 模拟用户脚本骨架

```python
PERSONAS = [
    SimulatedUser("新手", habits=["省略路径", "不说清楚目标"], error_rate=0.4,
                  knowledge_gaps=["不知道要prepare", "不知道要重启"]),
    SimulatedUser("急性子", habits=["跳过探查直接干"], error_rate=0.3, ...),
    SimulatedUser("谨慎型", habits=["总是先看README", "先看文件再改"], error_rate=0.1, ...),
    SimulatedUser("老手", habits=["用特定工具链"], error_rate=0.15, ...),
    SimulatedUser("模糊指令型", habits=["指令含糊"], error_rate=0.35, ...),
]

def run_session(flow, ledger, retriever):
    context = SessionContext(project="educe")
    for step in flow.steps:
        # 1. 用 persona 把 intent 渲染成自然语言指令
        user_msg = render_instruction(step, flow.user)
        # 2. （冷启动测试时）注入种子
        prompt = build_prompt(user_msg, context, 
                              lessons=retriever.retrieve(context) if retriever else [])
        # 3. 弱模型 + 真实工具执行（在 Educe 代码库的隔离副本里）
        action, outcome = agent.act(prompt, tools=real_tools)
        # 4. 记账本
        ledger.record(context.snapshot(), action, outcome)
        # 5. 更新 context（关键：失败要传递到下一步，模拟真实状态）
        context.update(outcome)
```

### 4.3 跑多少 / 何时停

| 阶段 | 规模 | 停止条件 |
|------|------|---------|
| 积累 | 10 pitfalls × 5 persona × 4 trial = 200 sessions | 每个 pitfall 的 correct_action 至少被独立发现 5 次 |
| 提炼 | 自动 | candidates 数量稳定（再跑20 session不新增candidate） |
| 验证 | held-out 3-5 pitfalls + 1 外部项目 | 全部种子跑完 A/B |

**"积累够了"的判定标准（可量化）：**

```python
def is_enough(ledger, pitfalls):
    for p in pitfalls:
        # 每个目标坑的正确解法被至少 5 个不同 session 命中
        if count_distinct_sessions_with_correct(ledger, p) < 5:
            return False
    # candidate 种子集合在最近 50 session 内增量 < 10%
    return candidate_growth_rate() < 0.1
```

### 4.4 最终产出格式（冷启动种子）

```json
{
  "version": "stage1-v1",
  "project": "educe",
  "generated_from": {"sessions": 200, "actions": 800},
  "seeds": [
    {
      "id": "S1",
      "context_pattern": {
        "intent_keywords": ["test", "pytest", "运行测试"],
        "project_signal": "存在 Makefile + tests/ 目录"
      },
      "lesson": "在本项目运行测试前，需先执行 `make prepare` 初始化 fixtures，否则报 fixture 未找到。",
      "type": "environment_specific",
      "evidence": {"support": 12, "lift": 0.78},
      "validation": {
        "same_project_lift": 0.65,
        "cross_project_lift": 0.05,   // 接近0 = 这是Educe特异的，不要乱用到别的项目
        "status": "confirmed"
      }
    }
  ],
  "