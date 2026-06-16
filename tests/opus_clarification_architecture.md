# Opus 4.8 — 澄清机制架构讨论（10轮）


## Round 1 — 开发者

Educe 框架发现了一个根本性的架构缺陷：模型从来不反问用户。

之前我试图用改 prompt 解决（加'歧义大且代价高时反问'的指令），但用户明确说'这不仅仅是改 prompt 这么简单，这是架构的升级'。

深入想想，他说得对。因为：
- prompt 里写'该问就问'，弱模型不一定能准确判断'什么时候该问'
- 反问需要一个新的交互模式（当前只有 action→执行→结果 这条管道）
- 'clarification' 需要被框架感知和追踪（收敛系统需要知道'用户澄清了什么'）
- 反问的质量需要框架层面的约束（不能胡乱问）

请从架构角度分析：把'反问/澄清'从'模型自由决策'提升为'框架管理的能力'，需要什么设计？
不是加一句 prompt，是设计一个机制。

## Round 1 — Opus 4.8

# 把"反问"从行为提升为机制：架构设计分析

你的判断是对的。让我先把核心矛盾点出来，再给设计。

## 一、为什么 prompt 解决不了：本质是状态缺失

当前管道：
```
input → action → execute → result
```

这是一条**单向、无状态分支**的管道。所有"决策"都坍缩成 action。在这个模型里，"反问"无处安放——它不是一个 action（它不执行任何东西），它是 action 之前的一个**控制流分叉**。

prompt 治不好，是因为你在用文本约束去模拟一个本该存在的**状态机分支**。模型每次都要在"自然语言层"重新推导"我现在该不该问"，而框架对这个推导**无感知、无记录、无约束**。

所以核心改动是：**让管道分叉。**

```
input → [decide] ─┬→ action → execute → result
                  └→ clarify → (suspend) → user_response → input'
```

## 二、四个必须新增的架构原语

### 1. Clarify 作为一等公民的"非终止输出"

模型的输出空间需要扩展。当前模型只能产出 `action`。现在它能产出两类：

```
ModelOutput =
  | Action(tool, args)        // 终止性：推进状态
  | Clarification(question, blocked_on)  // 非终止性：暂停状态
```

关键在于 `Clarification` 是**结构化的**，不是一句话。它至少要携带：

```python
Clarification {
    question: str,              # 问什么
    blocked_on: list[str],      # 卡在哪些未知变量上
    hypotheses: list[Option],   # 模型当前的候选解读（关键！）
    cost_if_wrong: Severity,    # 猜错的代价估计
}
```

`hypotheses` 是质量约束的抓手——下面讲。

### 2. 执行的"可挂起性"：Suspend / Resume

反问需要中断执行流并保留现场。这是真正的架构升级点，因为它要求执行引擎支持：

```
suspend(task_state) → 持久化当前上下文、已完成的 action、待澄清点
resume(task_state, user_response) → 把澄清注入上下文，从断点继续
```

如果你的框架现在是"一次 run 跑到底"，这一步会逼你引入**任务的可序列化状态**和**断点续传**。这是最大的工程量，但也是最有价值的——它顺便给你解锁了「长任务」「人在回路审批」等一系列能力。

### 3. Clarification 作为可追踪的状态实体

你提到的"收敛系统需要知道用户澄清了什么"，需要澄清不只是聊天记录里的一条消息，而是**结构化的约束记录**：

```python
ClarificationRecord {
    id: ...
    raised_at: step_n
    blocked_on: ["target_env"]
    resolution: "prod"          # 用户的回答被解析成的值
    resolved_at: step_m
}
```

这样收敛系统能做两件事：
- **去重**：同一个 `blocked_on` 维度不应该问第二次。
- **收敛信号**：每次澄清都是不确定性的下降，可以纳入你的收敛度量。

### 4. Decision Gate：决定"问 vs 猜"的判定层

这是把"该问就问"从模型 prompt 里**剥离出来**的地方。不要让弱模型在自然语言里裸判，给它一个结构化的判定框架：

```
gate(action_candidate) →
    confidence = 模型对解读的置信度
    cost       = 猜错的代价（可由工具元数据提供！）

    if confidence high          → execute
    if cost low                 → execute（猜错也无所谓，结果可纠正）
    if confidence low & cost high → clarify
```

**关键洞察**：`cost` 不该完全靠模型估，应该部分来自**工具自身的声明**。

## 三、工具元数据：把代价从模型推断变成框架已知

这是降低对模型能力依赖的核心手段。在工具定义里声明：

```python
@tool(reversible=False, blast_radius="high", confirm_on_ambiguity=True)
def delete_database(name: str): ...

@tool(reversible=True, blast_radius="low")
def read_file(path: str): ...
```

于是 Decision Gate 的"代价"维度变成框架已知量，模型只需估"歧义/置信度"这个它擅长的部分。弱模型判断负担直接减半。

`delete_database` + 歧义 → 强制走 clarify，不依赖模型自觉。

## 四、反问质量的框架级约束

你担心"不能胡乱问"。约束点：

1. **必须附带 hypotheses**：模型不能只问"你想要什么？"，必须给出"你是指 A 还是 B？"。框架在收到 `Clarification` 时校验 `hypotheses` 非空且 ≥2，否则打回重新生成。这一条约束能逼出 80% 的提问质量。

2. **预算约束**：单任务澄清次数上限（如 ≤3）。超限则强制走最高置信度的 hypothesis 并标注假设，避免无限反问的退化模式。

3. **不可重复**：已 resolved 的 `blocked_on` 维度禁止再问（用上面的 Record 去重）。

4. **必须 actionable**：每个 hypothesis 应可映射到一个具体 action，否则就是空问。

## 五、整体架构图

```
                    ┌─────────────────────────┐
   user input ─────▶│      Context Builder     │◀── ClarificationRecords
                    └────────────┬─────────────┘     (已澄清的约束)
                                 ▼
                          ┌─────────────┐
                          │    Model    │
                          └──────┬──────┘
                                 ▼
                          ┌─────────────┐
                          │ Decision    │◀── Tool Metadata
                          │ Gate        │    (reversible, blast_radius)
                          └──┬───────┬──┘
                  Action     │       │   Clarification
                             ▼       ▼
                      ┌─────────┐  ┌──────────────────┐
                      │ Execute │  │ Validate (hypos? │
                      └────┬────┘  │ budget? dedup?)  │
                           │       └────────┬─────────┘
                           │                ▼
                           │           ┌─────────┐
                           │           │ Suspend │──▶ persist state
                           │           └────┬────┘
                           │                ▼
                           │           ask user → Record
                           │                │
                           ▼                ▼
                        result          Resume ──▶ Context Builder
```

## 六、落地优先级建议

如果要分阶段，按 ROI 排序：

| 阶段 | 内容 | 收益 |
|---|---|---|
| 1 | `Clarification` 输出类型 + hypotheses 校验 | 立刻能问，且问得有结构 |
| 2 | 工具元数据（reversible/blast_radius） | Decision Gate 不再靠模型裸判 |
| 3 | ClarificationRecord + 去重/收敛接入 | 满足收敛系统的可观测性诉求 |
| 4 | Suspend/Resume | 最重，但解锁长任务能力 |

**MVP

## Round 2 — 开发者

你提出了很好的架构方向。追问：

当前 Educe 的行为循环是：用户输入 → 模型推理 → 输出 action(s) → 执行 → 结果反馈 → 继续

如果加入'澄清'能力，循环变成什么？有几种可能：
A) 模型输出一个特殊 action type 'clarify'（和 shell/write_file 同级）
B) 框架在模型推理前做一个'歧义检测'层（预判是否需要澄清）
C) 模型回复中包含问题文本，框架识别并暂停执行等待用户回答

哪种方案最适合弱模型？考虑：弱模型的判断力有限，如果让它自己决定何时 clarify 可能经常误判。

## Round 2 — Opus 4.8

# 三方案对比：弱模型视角

先给结论：**A 作为骨架，但必须用 B 的思想去约束 A 的触发。C 直接排除。**

下面讲为什么。

## 先排除 C

C（识别回复中的问题文本）有一个致命问题：它把"是否澄清"的判断完全交给了**自然语言的歧义**——框架要靠正则/分类去猜"模型这句话是在问我，还是在自言自语推理"。

弱模型尤其爱在 reasoning 里写"我不确定用户是指 prod 还是 dev……"这种话。C 会疯狂误触发。它把控制流建立在最不可靠的信号上。直接淘汰。

## A vs B：不是二选一，是分工

很多人把 A 和 B 对立起来，其实它们管的是**不同的东西**：

- **A 管的是"表达机制"**：澄清如何被框架感知、追踪、挂起。这是上一轮讲的架构原语，**必须有**。
- **B 管的是"触发判断"**：什么时候该澄清。这是你这一轮真正在问的——而它正是弱模型的软肋。

所以真正的问题不是"选 A 还是选 B"，而是：

> **clarify 这个 action 的"触发判断"，要放多少在模型身上？**

## 弱模型的核心问题：判断力不可靠，但方向是**双向**的

注意一个容易被忽略的点。弱模型误判不只是"该问的时候不问"，还有反方向：

```
误判类型 1（漏问）：歧义大却硬猜 → 做错事
误判类型 2（滥问）：本该自己决定却反问 → 退化成"什么都问用户"
```

**类型 2 在弱模型上更危险。** 因为一旦你给了它 clarify 这个"逃生舱口"，弱模型会发现"问用户"比"自己想清楚"更省力、更安全，于是把决策成本甩给用户。你会得到一个永远在问"你确定吗？""你是指 A 还是 B？"的助手。

所以纯 A（让模型自由输出 clarify action）对弱模型是灾难——它解决了机制，但放大了判断缺陷。

## 推荐方案：A 的机制 + B 的"门控"，但 B 不做语义预判

关键设计：**B 层不要去"预判用户意图是否模糊"**（那又回到了依赖模型/分类器的语义理解，不可靠）。B 层只做**结构性门控**——基于框架已知的硬信号。

```
用户输入 → 模型推理 → 输出 action(s)
                          │
                          ▼
                  ┌──────────────────┐
                  │  Gate（B 层）     │
                  │  只看硬信号：       │
                  │  - 这个 action 的   │
                  │    工具是否 high-risk│
                  │  - 必填参数是否缺失/ │
                  │    被模型标记为 guess│
                  │  - 是否已问过        │
                  └────────┬─────────┘
            ┌──────────────┼──────────────┐
        非高危            高危且无澄清记录    已澄清
            │              │                │
          执行         拦截→要求模型      执行
                       重新输出 clarify
                       （携带 hypotheses）
```

### 核心机制：分裂为两种触发路径

**路径 1：模型主动 clarify（A）—— 但默认不信任**

模型可以输出 `clarify` action，但 Gate 对它做**质量校验**而非放行：
- 必须有 ≥2 个 hypotheses
- 每个 hypothesis 必须可映射到具体 action
- `blocked_on` 维度没问过

不满足 → 打回，强制模型要么补全要么直接执行最高置信度选项。

这样即使弱模型滥用 clarify，框架也会过滤掉"空问"。

**路径 2：框架强制 clarify（B）—— 不信任模型的"漏问"**

当模型输出一个高危 action 时（`reversible=False` / `blast_radius=high`，来自工具元数据），即便模型自己很自信、没要求澄清，**Gate 也可以拦截**并反推模型：

```
你即将执行 delete_database(name=?)，
该操作不可逆。请确认 name 的值是用户明确指定的，
还是你的推断？如果是推断，输出 clarify。
```

**这是对弱模型最关键的补偿**：把"该问没问"（类型 1 误判）的检测，从模型的判断力转移到**框架的硬规则**上。模型不需要判断"这个操作危不危险"——框架已经知道了。

## 为什么这个组合最适合弱模型

| 误判类型 | 谁来兜底 | 靠什么信号 |
|---|---|---|
| 滥问（类型 2） | Gate 质量校验 | hypotheses 数量、可执行性、去重 |
| 漏问（类型 1） | Gate 强制拦截 | 工具元数据（框架已知，不靠模型） |

核心思想一句话：

> **能让框架用硬信号判断的，绝不交给弱模型的语义判断。模型只负责"在被框架圈定的范围内，把候选解读说清楚"。**

模型擅长"列出 prod/dev 两种可能"（生成），不擅长"判断现在该不该停下来问"（决策）。所以把**决策权部分收归框架**，把**生成权留给模型**。

## 关于 args 缺失的一个具体技巧

让模型在输出 action 时，对每个**推断出来的**（而非用户明示的）参数打标：

```json
{
  "tool": "deploy",
  "args": {
    "env": {"value": "prod", "source": "inferred"},
    "version": {"value": "1.2.0", "source": "explicit"}
  }
}
```

Gate 规则就变得极简、确定：

```
if tool.high_risk and any(arg.source == "inferred"):
    强制 clarify
```

这比让模型整体判断"我该不该问"容易得多——它只需对每个参数标注来源，这是弱模型也能可靠做到的**局部、原子**判断。

## 修正后的循环

```
用户输入
   ↓
模型推理 → 输出 action(s)（参数带 source 标注）
   ↓
Gate：
   ├─ clarify action? → 校验质量 → 通过则挂起问用户 / 不通过打回
   ├─ high_risk + inferred args? → 强制转 clarify
   └─ 否则 → 执行
   ↓
（澄清路径）挂起 → 用户回答 → 写入 ClarificationRecord → 回灌上下文 → 重新推理
   ↓
执行 → 结果反馈 → 继续
```

---

**一句话总结**：选 A 的机制（clarify 作为一等 action），但用 B 的门控思想把"何时触发"的判断尽量从模型剥离到框架硬规则上。弱模型的判断力不可靠，所以让它**生成候选**而非**做决策**，决策交给基于工具元数据和参数来源标注的确定性 Gate。

要不要我接着把 Gate 的判定规则写成一份可落地的伪代码 + 工具元数据 schema？

## Round 3 — 开发者

如果采用你建议的方案，'澄清'和收敛系统（IterationState）的关系是什么？

可能的关系：
- 澄清产生新的 VERIFIED claim（'用户确认了 X'）
- 澄清减少搜索空间（从多种可能收窄到用户明确的方向）
- 收敛停滞可以触发主动澄清（'你连续3轮没进展，不如问问用户？'）

怎么把这两个机制优雅地连接？

## Round 3 — Opus 4.8

# 澄清 × 收敛：两个机制的耦合设计

你列的三条关系，本质是**三个不同方向的因果流**。先把它们分清，再讲怎么连接——因为它们的耦合点不同，混在一起会设计乱。

```
关系 1：澄清 → 收敛   （澄清作为收敛的输入/驱动）
关系 2：收敛 → 澄清   （收敛状态作为澄清的触发器）
关系 3：澄清 ↔ claim  （澄清的产物如何进入知识状态）
```

我认为正确的连接方式是：**让澄清成为 IterationState 上的一种 "claim 来源"，从而自动获得 1 和 2，而不是为澄清单独造一套机制。**

下面展开。

## 核心主张：澄清不是独立子系统，是一种特殊的 claim 来源

最优雅的连接，是**不把澄清当成平行于收敛的东西**，而是把它折叠进你已有的 claim 体系。

你现有的 claim 大概有这样的来源谱系：

```
claim.source ∈ {
    inferred,    # 模型推断（低可信）
    observed,    # 工具执行结果（中-高可信）
    verified,    # 经过验证（高可信）
}
```

澄清做的事，就是新增一个来源，且它的可信度是**最高的**：

```
    user_confirmed,   # 用户亲口确认（最高可信，不可被模型推翻）
```

一旦这样建模，你列的关系 1 和关系 3 **自动成立**，不需要额外机制：

```python
ClarificationRecord(blocked_on="target_env", resolution="prod")
        ↓ 转化为
Claim(
    content="target_env == prod",
    source=USER_CONFIRMED,
    confidence=1.0,
    immutable=True,        # 关键：模型后续不能"重新推断"覆盖它
)
```

这个 immutable 标记很重要——它防止弱模型在后续轮次里"忘了用户说过 prod，又自己推断成 dev"。**用户的澄清是收敛过程中的锚点（anchor），不可漂移。**

## 关系 1 落地：澄清是收敛空间的"切割"，不是"填充"

你说"澄清减少搜索空间"，这点要建模得更精确，否则收敛度量会算错。

区分两种 claim 对收敛的贡献：

- **inferred claim**：增加了一个"可能正确"的命题 → 收敛度**乐观估计**上升，但不确定。
- **user_confirmed claim**：**消除了一整个分支** → 收敛度**确定性**上升。

如果你的收敛度量是基于"未决变量数 / 假设分支数"之类的，澄清的效果应该是：

```
收敛前：target_env ∈ {prod, dev, staging}   → 不确定性贡献 = log(3)
澄清后：target_env = prod (confirmed)        → 不确定性贡献 = 0（坍缩）
```

也就是说，**澄清是对状态空间的"维度消除"，应该比普通 claim 带来更陡的收敛跳变**。这会让你的收敛曲线在澄清点出现明显台阶——这恰好是你想要的可观测信号。

## 关系 2 落地：收敛停滞触发澄清——但要防止"逃逸式提问"

这是最危险的连接点，也是上一轮我担心的"弱模型把澄清当逃生舱"的复发场景。

朴素实现是错的：

```python
# ❌ 危险
if no_progress_for_n_rounds:
    ask_user("我卡住了，你能帮忙吗？")
```

这会让框架在每次停滞时把问题甩回用户，且问得很空。停滞触发澄清必须满足**两个条件**，且问题必须**结构化**：

```python
# ✓ 正确
if stalled(n_rounds) and has_unresolved_branch():
    branch = pick_highest_leverage_branch()   # 关键：选哪个维度问
    clarify(
        question=branch.to_question(),
        hypotheses=branch.options,        # 来自停滞期间反复横跳的候选
        reason="convergence_stall",
    )
```

两个设计要点：

**(a) 停滞要能区分"卡在歧义" vs "卡在能力"**

收敛停滞有两种根因：
- 模型在几个解读之间**反复横跳**（A→B→A→B）→ 这是歧义，**该问**。
- 模型在**重复同一个失败动作**（试 X，失败，再试 X）→ 这是能力/环境问题，问用户也没用，**不该问**（该换策略或报错）。

IterationState 应该能区分这两种停滞模式。判据很直接：

```python
if oscillating_between_hypotheses(history):   # 横跳 → 歧义
    trigger_clarify()
elif repeating_failed_action(history):        # 死循环 → 非歧义
    trigger_replan_or_abort()
```

**这是收敛系统反哺澄清质量的关键**：停滞期间的 history 本身就**提供了 hypotheses**。模型在 A 和 B 之间横跳了 3 轮 → 那就直接问"你是要 A 还是 B"。澄清的候选不需要弱模型现场编，**用历史轨迹里它已经横跳过的选项填进去**。这对弱模型是巨大的减负。

**(b) 触发权在框架，不在模型**

注意这条路径里，clarify 是 **Gate/收敛系统发起的**，不是模型自由输出的。这呼应上一轮的结论：把"何时问"的决策从弱模型剥离。模型的横跳行为是"症状"，框架观测到症状后"开处方"。

## 三者连接后的统一图景

```
                    ┌─────────────────── IterationState ───────────────────┐
                    │                                                        │
                    │   claims: [                                            │
                    │     {env=prod, source=USER_CONFIRMED, immutable}  ◀──┐ │
                    │     {file exists, source=OBSERVED}                  │ │
                    │     {target is X, source=INFERRED}                  │ │
                    │   ]                                                 │ │
                    │   convergence: 0.7                                  │ │
                    │   stall_detector: {oscillating? repeating?}         │ │
                    └──────┬──────────────────────────────┬───────────────┘ │
                           │                              │                  │
              关系2：停滞触发                  关系1：claim驱动收敛           │
                           │                              ▲                  │
                           ▼                              │                  │
                    ┌─────────────┐                       │                  │
                    │  Clarify    │── 用户回答 ──▶ Record ─┘ 关系3：转为     │
                    │  (Gate发起   │                         USER_CONFIRMED  │
                    │   或模型发起) │                         claim ─────────┘
                    └─────────────┘
                           ▲
                           │ hypotheses 来自停滞期的横跳历史
                           └──────────────────────────────
```

## 一个容易漏掉但很优雅的闭环：澄清的"预期收益"

既然澄清和收敛在同一个状态系统里，你可以让 Gate 在决定是否发起澄清时，估算

## Round 4 — 开发者

用户强调'反问要是胡乱问那也没有意义'。如何从架构层保证反问质量？

可能的质量维度：
- 不重复问已经明确的事
- 问题要封闭式（带选项），不是开放式
- 一次最多问 2-3 个关键问题
- 问题必须是'答案会实质性改变执行路径'的
- 不能在执行到一半才来问（应该在开头就判断）

这些约束应该在哪一层实现？模型层？框架层？还是两者配合？

## Round 4 — Opus 4.8

# 反问质量：一个"模型几乎不可信"的约束分配问题

先给总原则，再逐条落位。

## 总原则：质量约束应尽量下沉到框架，模型只承担"不可形式化"的那一小块

判断一个约束放哪一层，问一个问题：

> **这个约束能不能用框架已知的结构化信息来校验/强制？**

- 能 → 框架层（硬规则，确定性，不依赖模型自觉）
- 不能（本质是语义/世界知识）→ 模型层，但框架要给它**结构化的脚手架**降低难度

弱模型的特点是：**语义判断不可靠，但局部结构化标注可靠**。所以策略是把每个质量约束**拆解成"框架可校验的结构" + "模型只填空"**。

下面逐条过你列的五个维度。

## 逐条落位

### 1. 不重复问已明确的事 —— 纯框架层

这条**完全不该碰模型**。模型记不住、会忘、会重复，这是它的固有缺陷。

用上一轮的 `ClarificationRecord` + USER_CONFIRMED claim 做硬去重：

```python
def gate_dedup(clarification):
    for record in resolved_records:
        if clarification.blocked_on ⊆ record.resolved_dimensions:
            REJECT("已澄清过 {dim}，值为 {value}")
```

更进一步：**已 resolved 的维度，在 Context Builder 阶段就作为 immutable claim 注入**，模型连"想问"的机会都没有——因为它的上下文里已经写明"env=prod (用户已确认)"。

> 落位：**100% 框架层。** 这是框架记忆替代模型记忆的典型场景。

### 2. 封闭式（带选项）—— 框架定形式，模型填内容

这是经典的"结构 vs 内容"分工：

- **"必须封闭式"这个约束本身** → 框架层强制：`hypotheses` 字段非空且 ≥2，否则打回。
- **选项的具体内容（prod/dev/staging）** → 模型层生成（这是世界知识，框架不知道）。

```python
def gate_closed_form(clarification):
    if len(clarification.hypotheses) < 2:
        REJECT_AND_REGENERATE("必须提供≥2个候选选项")
    if clarification.question_is_open_ended():   # 这个难判，见下
        ...
```

注意"问题文本是否开放式"本身难以用规则判定。**技巧：不要去校验 question 文本，而是校验结构。** 如果框架强制要求每个 hypothesis 必须存在且可映射到 action（见第 4 条），那么问题自然就是封闭的——你甚至可以**让框架用 hypotheses 自动渲染问题模板**：

```
"检测到 {blocked_on} 不明确，你是指：
  [1] {hypotheses[0].label}  → 将执行 {hypotheses[0].action}
  [2] {hypotheses[1].label}  → 将执行 {hypotheses[1].action}"
```

这样模型**根本不负责"问得封不封闭"**，它只负责产出 hypotheses 列表，封闭式是框架渲染的结果。**最优雅的约束是让违反它变得不可能。**

> 落位：**框架定形式（强），模型填选项内容。** 问题文本由框架渲染，绕开"开放式判定"难题。

### 3. 一次最多 2-3 个 —— 纯框架层

数量上限是纯计数，模型不该参与：

```python
MAX_QUESTIONS_PER_TURN = 3
MAX_CLARIFICATIONS_PER_TASK = 3   # 任务级预算

def gate_budget(clarification, state):
    if len(clarification.questions) > MAX_QUESTIONS_PER_TURN:
        TRUNCATE_TO_TOP_K(by=leverage)   # 按"杠杆"排序保留前K
    if state.clarification_count >= MAX_CLARIFICATIONS_PER_TASK:
        FORCE_BEST_GUESS(annotate="预算耗尽，采用最高置信假设")
```

注意"保留哪 K 个"需要排序依据——这引出第 4 条的杠杆概念。

> 落位：**100% 框架层。** 计数和预算是确定性逻辑。

### 4. 答案必须实质改变执行路径 —— 这是质量的真正核心，框架主导 + 模型提供原子标注

这是五条里**最重要也最难**的一条。"问了等于没问"的根源就是违反它——问一个无论怎么答都不改变行为的问题。

关键洞察：**"是否改变执行路径"不该让模型整体判断，而要分解成每个 hypothesis 对应的 action 是否不同。**

```python
def gate_actionable(clarification):
    actions = [h.resulting_action for h in clarification.hypotheses]
    
    # 硬约束 1：每个假设必须能映射到具体 action
    if any(a is None for a in actions):
        REJECT("假设 {h} 无对应 action，是空问")
    
    # 硬约束 2：不同假设导向的 action 必须实质不同
    if all_actions_equivalent(actions):
        REJECT("所有选项导向相同执行路径，此问无意义")
```

`all_actions_equivalent` 是可以框架化判定的——比较 tool 名 + 关键 args。如果"问你要 A 还是 B"，但 A 和 B 最后都执行 `deploy(env=prod)`，框架直接判定为无效问题。

**这一条把"问得有没有意义"从一个模糊的语义判断，转化成了一个确定性的 action 差异比较。** 这是整个质量体系的支点。

模型的职责被压缩到最小：为每个 hypothesis **标注它会导向哪个 action**（局部、原子，弱模型可靠）。是否"实质改变路径"由框架比较 action 得出。

> 落位：**框架判定（比较 action 差异），模型只标注每个假设的 resulting_action。**

### 5. 不能执行到一半才问 —— 框架层强制时机

这条要拆成两个子问题：

**(a) 时机约束**：澄清应在 action 执行**前**由 Gate 拦截，而不是执行中。这天然由架构保证——上一轮的循环里，Gate 在 execute 之前。只要架构是 `decide → gate → execute`，就不存在"执行到一半才问"。

但有个例外要处理：**多步任务中，第 3 步才暴露的歧义**。"在开头就判断"对多步任务不现实——有些歧义只有执行了前几步才会显现（比如读了文件才发现有两个候选目标）。

所以这条要修正为：

> 不是"必须在任务开头问"，而是"必须在**触发歧义的那个 action 执行前**问，不能在它执行后亡羊补牢"。

**(b) 不可逆操作前的强制检查点**：对 `reversible=False` 的 action，Gate 在执行前**必须**做澄清门控（即使模型自信）。这是上一轮讲的工具元数据强制拦截。

```python
def gate_timing(action, state):
    if action.tool.reversible

## Round 5 — 开发者

对比 Claude Code（我正在用的工具）的行为：
- Claude Code 面对模糊需求会先问
- 但它的'问'不是一个 action，而是直接文字回复中包含问题
- 用户回答后它记住答案继续执行

Educe 的差异点：
- Educe 有收敛系统（可以追踪'用户澄清'作为知识）
- Educe 目标是非工程师（问题要更简单直白）
- Educe 用弱模型（判断力有限，不能全靠模型自己决定何时问）

在这些差异下，Educe 的'澄清'机制应该比 Claude Code 更结构化还是更自由？

## Round 5 — Opus 4.8

# 应该更结构化——但要分清"对谁结构化"

直接结论：**对框架内部更结构化，对用户更简单。** 这两件事不矛盾，恰恰是 Educe 三个差异点共同推出的唯一自洽方向。

先说为什么不能学 Claude Code 的自由模式，再说"结构化"具体结构在哪、自由留在哪。

## Claude Code 的自由能成立，靠的是 Educe 没有的三个前提

Claude Code 的"问题混在文字回复里"之所以能 work，依赖三个隐含前提：

```
1. 强模型 → 判断"何时问/问得好不好"本身可靠，不需要外部门控
2. 工程师用户 → 能读懂开放式问题，能消化"我在 prod 和 staging 之间犹豫"这种表述
3. 无显式收敛系统 → 答案靠模型自己记在上下文里，不需要结构化沉淀
```

Educe 的三个差异点，**逐一否定了这三个前提**：

| Claude Code 前提 | Educe 现实 | 推论 |
|---|---|---|
| 强模型自判断 | 弱模型判断不可靠 | 自由触发会漏问+滥问，**需要框架门控** → 更结构化 |
| 工程师用户 | 非工程师 | 开放式问题答不上来，**需要封闭式选项** → 更结构化 |
| 无收敛系统 | 有 IterationState | 答案要进 claim、要去重、要驱动收敛，**需要结构化记录** → 更结构化 |

**三个差异点全部指向"更结构化"，没有一个指向"更自由"。** 这不是巧合——Educe 的设计前提整体上就是"在更弱的判断力和更弱的用户下做事"，结构化是补偿手段。

## 但"结构化"必须分两个面，否则会做错

这里有个极易踩的坑：**把"对框架结构化"误解成"对用户结构化"**，结果给非工程师用户抛出一堆 JSON 风格的、带 `hypothesis_id` 的、像填表一样的问题。那就违背了"目标是非工程师"。

正确的拆分：

```
        ┌─────────────────────────────────────────┐
        │  框架内部：高度结构化（机器消费）            │
        │                                           │
        │  clarify {                                │
        │    blocked_on: "target_env",              │
        │    hypotheses: [                          │
        │      {label, resulting_action, ...},      │
        │      {label, resulting_action, ...}       │
        │    ],                                     │
        │    source_of_options: "stall_history",    │
        │  }                                        │
        └──────────────────┬────────────────────────┘
                           │ 框架渲染层（翻译）
                           ▼
        ┌─────────────────────────────────────────┐
        │  对用户：极简、口语、封闭（人消费）          │
        │                                           │
        │  "你想把它部署到正式环境还是测试环境？"       │
        │   ① 正式环境   ② 测试环境                  │
        └─────────────────────────────────────────┘
```

**内部结构化是为了校验质量（上一轮那五条门控），用户侧极简是为了非工程师能答。** 中间隔一个渲染层。Claude Code 没有这个分层——它内部和外部是同一坨文字。Educe 必须有。

## 比 Claude Code 更结构化的三个具体地方

### 1. 触发：从"模型自由决定"→"框架门控决定"

Claude Code：模型觉得该问就问。
Educe：clarify 是一等 action，但**触发权部分收归 Gate**（高危拦截、停滞触发、质量校验打回）。

这是最大的结构化差异，直接源于"弱模型判断不可靠"。

### 2. 表达：从"开放式文字"→"封闭式选项"

Claude Code 可以问"你能详细说说你想要的部署策略吗？"——工程师能答。
Educe 不能。非工程师面对开放式问题会卡住或给出无法消费的答案。所以**强制封闭式**（上一轮的 hypotheses ≥2 + 渲染成带编号选项）。

而且选项要用**用户的语言**，不是 `prod/dev`，是"正式环境/测试环境"。这层翻译也是模型的活，但框架强制它必须做。

### 3. 记忆：从"靠上下文"→"靠 ClarificationRecord + immutable claim"

Claude Code 把答案留在对话历史里，靠强模型不忘。
Educe 用弱模型，**不能信任模型记住**，所以答案必须沉淀为 USER_CONFIRMED 的 immutable claim，由 Context Builder 每轮重新注入。这是收敛系统带来的能力，也是必须用的能力。

## 自由该留在哪：选项的"内容生成"

不是所有东西都结构化。有一处必须保持自由——**模型生成 hypotheses 的内容**。

框架不知道"prod/dev/staging"这些选项是什么，不知道用户口语里该叫什么，不知道哪两个解读最可能。这是世界知识和语境理解，**只能靠模型自由生成**。

所以最终分工是：

```
结构化（框架强制）：何时问、问几个、是否封闭、是否去重、是否实质改变路径、答案如何沉淀
自由（模型负责）：  问题的具体内容、选项的具体措辞、用什么大白话表达
```

一句话：**Educe 的澄清 = Claude Code 的"会问"能力 + 一套把"问什么/何时问/怎么记"从模型手里收归框架的结构化外骨骼。模型仍然负责"想出问什么"，但"问得合不合规、记不记得住"由框架兜底。**

## 一个反直觉的好处

更结构化反而让 Educe 的澄清**对非工程师更友好**，而不是更死板：

- 封闭式选项 → 用户点选即可，不用组织语言
- 框架渲染 → 措辞一致、简单，不会出现模型偶尔抽风问得很技术
- 一次最多 2-3 个 → 不会被一连串问题淹没

Claude Code 的自由是为强模型+工程师优化的；Educe 的结构化是为弱模型+非工程师优化的。**两者都对，只是约束条件不同。**

要不要我把这个"内部结构化 schema + 用户侧渲染模板"具体写出来，包括那层翻译规则（怎么把 `env=prod` 渲染成"正式环境"）？

## Round 6 — 开发者

请给出一个具体的实现方案，包括：
1. 数据结构（澄清请求长什么样）
2. 前端交互（用户看到什么、怎么回答）
3. 后端处理（框架怎么把澄清结果注入回模型上下文）
4. 和现有确认机制（action_confirm）的关系
5. 最小可行版本（第一天就能跑通的最简实现）

## Round 6 — Opus 4.8

# Educe 澄清机制：完整实现方案

下面是从数据结构到 MVP 的端到端方案。我会在每层都标注"框架职责 vs 模型职责"，并明确和 `action_confirm` 的边界。

## 1. 数据结构

### 1.1 核心：ClarificationRequest（模型产出 → 框架校验）

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class ClarifyTrigger(str, Enum):
    MODEL_INITIATED = "model_initiated"      # 模型主动发起
    STALL_DETECTED  = "stall_detected"       # 框架因停滞发起
    IRREVERSIBLE    = "irreversible_gate"    # 不可逆操作前强制

@dataclass
class Hypothesis:
    """一个候选解读。这是模型负责生成的最小原子单位。"""
    id: str                          # "h1" / "h2"，框架生成或模型填
    label_internal: str              # 内部语义，如 "env=prod"（机器用）
    label_user: str                  # 用户语言，如 "正式环境"（人用）
    resulting_action: dict           # 选这个会导向的 action（用于质量校验）
                                     # {"tool": "deploy", "args": {"env": "prod"}}
    confidence: float = 0.0          # 模型对这个解读的先验置信

@dataclass
class ClarificationRequest:
    """模型产出此结构，框架校验后才放行给用户。"""
    blocked_on: str                  # 卡在哪个维度，如 "target_env"
    question_user: str               # 用户语言的问题（模型填，或框架渲染）
    hypotheses: list[Hypothesis]     # 候选，框架强制 >= 2
    trigger: ClarifyTrigger
    reason: str = ""                 # 给日志/调试，不展示用户

    # —— 以下由框架填充，模型不碰 ——
    request_id: str = ""
    is_blocking: bool = True         # 是否阻塞后续执行
```

### 1.2 澄清结果与知识沉淀：ClarificationRecord → Claim

```python
@dataclass
class ClarificationRecord:
    """用户回答后的不可变记录。"""
    request_id: str
    blocked_on: str
    chosen_hypothesis_id: str
    resolved_value: str              # "env=prod"（取自 chosen.label_internal）
    raw_user_input: Optional[str] = None   # 用户若没选而是自由输入，存这里
    timestamp: float = 0.0

# 转化为 claim（上一轮定义的 USER_CONFIRMED 来源）
def record_to_claim(rec: ClarificationRecord) -> "Claim":
    return Claim(
        content=rec.resolved_value,          # "env=prod"
        source=ClaimSource.USER_CONFIRMED,
        confidence=1.0,
        immutable=True,                      # 模型后续不能推翻
        origin_id=rec.request_id,
    )
```

### 1.3 停滞检测器（关系2 的数据基础）

```python
@dataclass
class StallDetector:
    history: list[dict] = field(default_factory=list)  # 近 N 轮 action

    def oscillating_hypotheses(self) -> Optional[list[Hypothesis]]:
        """检测 A→B→A→B 横跳。若有，返回横跳的候选 → 直接当 hypotheses。"""
        recent = self.history[-4:]
        signatures = [self._action_sig(a) for a in recent]
        unique = set(signatures)
        if len(recent) >= 4 and len(unique) == 2:
            # 在两个动作间反复横跳 → 歧义，提取出来当选项
            return self._sigs_to_hypotheses(unique)
        return None

    def repeating_failure(self) -> bool:
        """检测试 X→失败→再试 X 死循环。这种不该问用户。"""
        recent = self.history[-3:]
        sigs = [self._action_sig(a) for a in recent]
        return len(recent) >= 3 and len(set(sigs)) == 1 and \
               all(a.get("failed") for a in recent)
```

## 2. 前端交互

### 2.1 用户看到什么

框架把 `ClarificationRequest` 渲染成极简卡片，**只暴露 `label_user`，隐藏所有内部字段**：

```
┌──────────────────────────────────────┐
│ 🤔 想确认一下                          │
│                                        │
│ 你想部署到哪个环境？                    │
│                                        │
│  ┌────────────┐  ┌────────────┐       │
│  │ ① 正式环境  │  │ ② 测试环境  │       │
│  └────────────┘  └────────────┘       │
│                                        │
│  其他？ [____________________] 发送     │
└──────────────────────────────────────┘
```

设计要点：
- **默认是点选**（封闭式），符合非工程师习惯，零打字。
- **保留一个自由输入框兜底**——用户的真实意图可能不在选项里，强制选会逼出错误答案。自由输入走"模型重新解析"路径（见 3.3）。
- 不显示 `env=prod`、`tool=deploy` 等内部信息。
- 一次最多 3 个选项卡片（框架截断保证）。

### 2.2 渲染规则（label_internal → label_user）

这层翻译有两种实现，按可靠性递进：

```python
# 方案A（MVP）：模型生成时直接产出 label_user，框架不翻译
#   优点：简单。缺点：依赖模型措辞质量。
hypothesis.label_user  # 模型直接填好 "正式环境"

# 方案B（增强）：框架维护术语映射表，对常见维度强制翻译
TERM_MAP = {
    "env=prod":    "正式环境",
    "env=dev":     "测试环境",
    "env=staging": "预发布环境",
}
def render_label(internal: str) -> str:
    return TERM_MAP.get(internal, _model_translate(internal))
```

MVP 用方案 A，等高频维度沉淀出来后逐步补 TERM_MAP 提升一致性。

## 3. 后端处理

### 3.1 主循环中的位置

```python
def agent_loop(task, state):
    while not state.done:
        decision = model.decide(state)          # 模型产出 action 或 clarify_request

        # —— Gate 层：澄清门控 ——
        if isinstance(decision, ClarificationRequest):
            verdict = clarify_gate(decision, state)   # 见 3.2
            if verdict.rejected:
                state.inject_feedback(verdict.reason) # 打回，让模型重来
                continue
            record = await present_to_user(decision)  # 前端交互，阻塞等回答
            state.add_claim(record_to_claim(record))  # 关系3：沉淀为 claim
            state.clarification_records.append(record)
            continue

        # —— 框架主动触发澄清（关系2）——
        stall = state.stall_detector
        if stall.repeating_failure():
            state.trigger_replan_or_abort()      # 死循环，不问用户
            continue
        osc = stall.oscillating_h

## Round 7 — 开发者

用这几个真实场景验证你的方案是否能工作：

场景1：'帮我做个管理系统'（极度模糊，应该问）
场景2：'把这个 CSV 算个总和'（清晰，不该问）
场景3：'优化一下我的代码'（需要知道改哪个文件、优化什么）
场景4：'部署到服务器上'（需要知道什么服务器、什么方式）
场景5：'改个 bug'（需要知道什么 bug，但如果给了文件名就不用问）

你的方案在每个场景下会产生什么行为？有没有误判风险？

## Round 7 — Opus 4.8

# 五个场景的行为验证

我会对每个场景模拟跑一遍方案，给出预期行为，**重点暴露误判风险**——因为弱模型下，误判才是真问题。

先建立一个判断框架，否则只是凭感觉说"该问/不该问"。

## 先定义：到底什么时候该问？

我的方案里，"该不该问"不是单点判断，而是过两道关：

```
模型发起 clarify
   │
   ├─ Gate 校验：hypotheses≥2 且 action 实质不同？  ── 否 → 打回（这问没意义）
   │
   └─ 是 → 放行给用户
```

**关键洞察："是否该问"被转化成"是否存在两个导向不同 action 的解读"。** 这正是第 4 条门控（实质改变执行路径）。我用这个标准验证五个场景。

## 场景1：'帮我做个管理系统'

**应该问。我的方案行为：**

模型尝试 decide，但**无法产出任何具体 action**——它甚至不知道第一步该 `create_file` 还是 `ask_framework`。这里有个**方案盲区**：我的 Gate 设计的是"模型发起 clarify 后校验"，但这个场景的问题是**模型根本产不出有意义的 hypotheses**。

"管理系统"的歧义维度太多（什么业务？什么技术栈？谁用？），强行让模型出 2 个 hypothesis，会得到：

```
h1: {label_user: "做个学生管理系统", action: create_project(...)}
h2: {label_user: "做个库存管理系统", action: create_project(...)}
```

这俩 action 的 tool 相同、args 结构相同——**`all_actions_equivalent` 可能误判为"等价"而打回**，导致该问的不问。

**误判风险：真实存在。** 这是"歧义太大无法封闭式枚举"的情况。

**修正：** 我的方案需要补一个前置分支——

```python
class DecisionType:
    ACTION = "action"
    CLARIFY_CLOSED = "clarify_closed"      # 有限歧义，封闭式
    CLARIFY_OPEN   = "clarify_open"        # 歧义过大，开放式范围收窄

# 当模型连 hypotheses 都列不出（维度 > 阈值），降级为"范围收窄式提问"
```

但"范围收窄式开放问题"违背了"非工程师友好+封闭式"原则。**更好的处理：用分层封闭式**，先问最顶层的一个维度：

```
"你想做个什么样的系统？
 ① 管理人/客户（CRM、学员、会员…）
 ② 管理货/库存（进销存、仓库…）
 ③ 管理事/流程（审批、工单…）
 ④ 其他（告诉我）"
```

把"无限开放"切成"顶层封闭+逐层下钻"。**这是方案需要补的能力：多轮渐进式澄清，而非一次问清。** 受 `MAX_CLARIFICATIONS_PER_TASK=3` 预算约束，最多下钻 3 层。

> **结论：方案原版会误判（打回该问的问题）。修正后用"分层封闭式 + 渐进下钻"处理。这是验证暴露出的真实缺陷。**

## 场景2：'把这个 CSV 算个总和'

**不该问。我的方案行为：✅ 正确。**

模型直接产出 action：`read_csv → sum(column)`。没有发起 clarify，主循环直接执行。

**但有一个潜在误判点：哪一列？** 如果 CSV 有多个数值列，"算总和"是有歧义的。这时分两种情况：

```
情况A：只有一个数值列 → 无歧义，直接算。✅
情况B：多个数值列 → 模型可能发起 clarify
```

情况 B 下，Gate 校验：

```python
h1: {label_user: "金额列求和", action: sum(col="amount")}
h2: {label_user: "数量列求和", action: sum(col="qty")}
# action 的 args.col 不同 → all_actions_equivalent = False → 放行 ✅
```

这是个**好信号**：同一个"算总和"任务，框架能根据 action 差异自动区分"无歧义直接做"vs"有歧义该问"，不靠模型语义判断。

**误判风险：低。** 唯一风险是模型在情况 A（单列）下**多此一举发起 clarify**。这时：

```python
# 单列时模型若硬出两个 hypothesis，必然指向同一个 action
h1: {action: sum(col="value")}
h2: {action: sum(col="value")}   # 没有别的列可选
# all_actions_equivalent = True → Gate 打回 ✅
```

**Gate 在这里救了场**——滥问被框架挡掉了。这正是"弱模型滥问，框架兜底"的设计意图生效。

> **结论：✅ 方案工作正常。Gate 既能放行真歧义（多列），又能拦截滥问（单列）。**

## 场景3：'优化一下我的代码'

**需要问（改哪个文件、优化什么）。我的方案行为：⚠️ 部分正确，有顺序陷阱。**

这里有**两个独立的歧义维度**：
- 维度1：哪个文件？（结构化信息，框架可能知道）
- 维度2：优化什么？（性能/可读性/体积——语义，框架不知道）

我的方案风险：**模型可能一次性问两个，或者问错顺序。**

正确行为应该是：

```python
# 维度1 优先用框架信息消解，不问用户
if len(workspace.code_files) == 1:
    target_file = workspace.code_files[0]     # 框架直接确定，不问 ✅
else:
    # 多文件才问，且这是结构化选项，框架能枚举
    clarify(blocked_on="target_file",
            hypotheses=[from each file])      # 选项来自框架，不靠模型编

# 维度2 必须问（语义），但要等维度1确定后
clarify(blocked_on="optimize_goal",
        hypotheses=[性能, 可读性, 体积])
```

**误判风险：两个。**

1. **顺序错乱**：模型可能先问"优化什么"再问"哪个文件"，或一轮塞两个问题。我的方案有 `MAX_QUESTIONS_PER_TURN=3` 但**没有维度依赖排序**。需要补：blocked_on 维度之间的依赖/优先级（结构化维度优先于语义维度）。

2. **"优化什么"的 action 差异难判**："优化性能"和"优化可读性"导向的 action 可能都是 `edit_file(path=X)`，**tool 和主 args 相同**，`all_actions_equivalent` 会误判为等价并打回！

第 2 点是**第 4 条门控的硬伤**：当不同解读导向"同一个工具同一个文件但意图不同"时，action 签名比较失效。

**修正：** action 等价性比较需要纳入一个 `intent` / `strategy` 字段，而不只比 tool+args：

```python
def all_actions_equivalent(actions):
    # 不能只比 tool+args，要比 (tool, key_args, strategy)

## Round 8 — 开发者

核心难题：弱模型（Qwen3.6-35B）能否准确判断'何时该问'？

如果不能，那框架层需要做什么来补偿？
- 规则引擎？（检测关键词/任务类型）
- 模板库？（常见歧义场景→预设问题）
- 后置检查？（模型开始执行后，框架检查其假设是否合理）

还是说，应该接受'弱模型有时会误判'，通过其他机制（如收敛停滞→触发澄清）来兜底？

## Round 8 — Opus 4.8

# 弱模型判断不了"何时该问"——但这个问题问错了方向

直接结论：**不要让弱模型判断"何时该问"。这是个判断任务，弱模型的判断不可靠，再多 prompt 工程也补不上。正确做法是把"何时该问"从判断任务改造成可观测的状态信号，让框架来判，模型只负责更简单的"问什么"。**

下面论证为什么，以及具体补偿栈怎么搭。

## 先证明：弱模型确实判断不了"何时该问"

"何时该问"本质是判断 **"我现在的不确定性是否高到值得打断用户"**。这要求模型同时做到：

```
1. 知道自己不知道什么        ← 弱模型校准差，常常自信地错
2. 估计错误解读的代价        ← 需要后果推理，弱模型弱项
3. 权衡"问的打扰" vs "错的代价" ← 多目标权衡，弱模型几乎做不了
```

第 1 点是死穴。弱模型的**置信度和正确率不挂钩**——它在"算 CSV 总和"（该做）和"做管理系统"（该问）上可能给出同样的自信。你在场景验证里已经看到了：让它硬出 hypotheses，它能给你两个伪选项。

**所以：凡是依赖"模型自己意识到该问了"的设计，都会漏问+滥问。** 这条路堵死。

## 转换问题：从"判断"到"信号"

关键转换——**"该不该问"的大部分情况，不需要判断，只需要观测客观信号**：

| 信号 | 是否需要"判断" | 谁来检测 | 对应场景 |
|---|---|---|---|
| 任务无法产出任何具体 action | 否，可观测 | 框架 | 场景1 管理系统 |
| 关键 arg 缺失且无默认 | 否，可观测 | 框架 | 场景4 服务器地址 |
| 同一维度存在多个可枚举候选 | 否，可枚举 | 框架 | 场景2 多列、场景3 多文件 |
| 收敛停滞/横跳 | 否，可观测 | 框架 | 场景3 优化目标反复改 |
| 不可逆 + 高危 | 否，可规则匹配 | 框架 | 场景4 部署 prod |
| **纯语义歧义**（优化"什么"） | **是，需判断** | **只能靠模型** | 场景3 维度2 |

**90% 的"何时该问"是可观测信号，根本不是判断问题。** 只有最后一行（纯语义歧义）真的需要模型判断——而那部分恰恰可以通过其他机制兜底。

所以补偿栈不是"选规则引擎 or 模板 or 后置检查"，而是**这几者按可靠性分层串联，模型判断放在最后兜底位**。

## 补偿栈：四层，按可靠性从高到低

```
┌────────────────────────────────────────────────────┐
│ L1  框架信号检测（最可靠，处理 60%）                   │
│     缺参检测 / 候选枚举 / 高危规则                     │
├────────────────────────────────────────────────────┤
│ L2  模板库（可靠，处理 25%，覆盖高频任务类型）          │
│     任务分类 → 预设必填维度清单                        │
├────────────────────────────────────────────────────┤
│ L3  收敛停滞兜底（可靠，事后补救漏判）                  │
│     横跳/停滞 → 强制澄清，捞回 L1/L2 漏掉的            │
├────────────────────────────────────────────────────┤
│ L4  模型自由发起（最不可靠，只补纯语义歧义）            │
│     必须过 Gate 校验，default 倾向"不问先做"           │
└────────────────────────────────────────────────────┘
```

### L1：框架信号检测——确定性的部分全交给它

不依赖任何模型判断，纯结构检测：

```python
def detect_missing_required_args(action: dict, tool_schema: dict) -> list[str]:
    """场景4：deploy 工具 schema 标了 target 必填，但 action 没给 → 确定要问"""
    return [arg for arg in tool_schema["required"]
            if arg not in action.get("args", {})
            and arg not in resolved_claims]

def enumerate_candidates(blocked_on: str, ctx) -> list[Hypothesis]:
    """场景2/3：从环境枚举候选。多列→列名，多文件→文件名"""
    if blocked_on == "target_file":
        return [h(f) for f in ctx.workspace.code_files]
    if blocked_on == "target_column":
        return [h(c) for c in ctx.csv.numeric_columns]
    return []
```

**这一层是地基。** 缺参、多候选、高危——全是可观测/可枚举的，零判断。场景 2、4 主要靠它，场景 3 的"哪个文件"也靠它。

### L2：模板库——把"该问什么"从知识变成查表

不是"模板化的问题文案"，而是**任务类型 → 必填维度清单**：

```python
TASK_TEMPLATES = {
    "deploy": {
        "required_dims": ["target_env", "deploy_method"],
        "high_risk_dims": ["target_env"],     # prod 触发强制确认
    },
    "optimize_code": {
        "required_dims": ["target_file", "optimize_goal"],
        "dim_order": ["target_file", "optimize_goal"],   # 解决场景3顺序问题
        "semantic_dims": ["optimize_goal"],   # 标注：这维度框架枚举不了，得模型出
    },
    "build_system": {
        "required_dims": ["domain"],          # 顶层维度
        "progressive": True,                  # 场景1：允许逐层下钻
    },
}
```

**任务分类本身也是判断**——但它比"何时该问"简单得多（分类 vs 元认知），弱模型分类的准确率远高于自我校准。而且分类错了有 L3 兜底。

模板的作用：**把"deploy 必须知道环境和方式"这种领域知识固化下来，不靠模型每次自己想起来。** 直接解决场景 4 漏问、场景 3 顺序错乱。

### L3：收敛停滞兜底——捞回前三层漏掉的

前面再严密，纯语义歧义仍会漏（L4 判断不可靠）。停滞检测是**事后安全网**：

```python
def stall_triggered_clarify(state) -> Optional[ClarificationRequest]:
    osc = state.stall_detector.oscillating_hypotheses()
    if osc:
        # 模型在两个 action 间横跳 = 它自己暴露了歧义，比它"主动意识到"可靠得多
        return ClarificationRequest(
            blocked_on="resolved_from_stall",
            hypotheses=osc,                  # 横跳的两个动作直接当选项！
            trigger=ClarifyTrigger.STALL_DETECTED,
        )
    if state.stall_detector.repeating_failure():
        return None    # 死循环是另一回事，触发 replan，不问用户
```

**精妙之处：模型横跳时，它"用脚投票"

## Round 9 — 开发者

回到大局：Educe 定位是'人与模型之间的治理层'。

'澄清'机制在这个定位中扮演什么角色？
- 是'方向盘'的一部分（用户通过回答问题来导航）？
- 是'仪表盘'的一部分（系统通过提问展示它的不确定性）？
- 还是'刹车'的一部分（在错误方向走远之前停下来）？

以及：对于面向所有人（非工程师）的产品，提问的方式应该有什么特殊设计？

## Round 9 — Opus 4.8

# 澄清是三者的交汇点——但本质是"刹车"

直接回答：**澄清同时承担三个角色，但如果只能保留一个，它的本质是刹车。** 方向盘和仪表盘是它顺带产生的好处，而不是它存在的理由。这个判断会决定整个机制的设计取向。

下面论证，然后讲非工程师的提问设计。

## 三个角色，澄清各占多少

| 角色 | 澄清如何体现 | 是本质吗 |
|---|---|---|
| **刹车** | 在错误解读导向行动之前停下 | ✅ **是** |
| **方向盘** | 用户通过选项给出方向 | 派生 |
| **仪表盘** | 提问暴露了系统的不确定性 | 副作用 |

**为什么本质是刹车：** 回看你的整个方案设计，所有可靠的触发都是"阻止性"的——

```
缺参检测     → 没有目标，不准走        （刹车）
高危规则     → 部署 prod 前，停        （刹车）
停滞兜底     → 横跳说明走不下去，停      （刹车）
Gate 校验    → 解读没有实质分歧，不准停  （防止误踩刹车）
```

整个机制的可靠部分，全是在控制"停 / 不停"，没有一处在主动规划方向。**方向是用户回答时附带给的，不是澄清主动求取的。** 这是关键区分——澄清不问"你想去哪"（那是方向盘），它问"这个岔路口我不敢替你选，你来定"（那是被迫停车）。

**为什么"方向盘"是派生而非本质：** 真正的方向盘是用户主动输入任务（"帮我做X"）。澄清里的选项不是导航，是**消解二义性**——它把方向限定在"模型已经识别出的 2-3 个解读"内，用户只是在框架划定的小范围里做选择。如果澄清是方向盘，它应该能让用户自由转向；但它恰恰相反，是把方向收窄到可执行的几个候选。

**为什么"仪表盘"是副作用：** 提问确实暴露了不确定性，但这是**结果不是目的**。而且对非工程师，过度暴露不确定性是有害的——见下文。仪表盘的本职（持续展示状态）应该由别的机制承担，澄清只在"不确定性高到必须停车"时才触发，不是常态显示。

## 这个判断对设计的硬性约束

定性为刹车后，几条设计原则被锁死：

**1. 刹车必须默认松开。** 一辆默认踩着刹车的车没法开。对应到方案：**default 必须是"不问，先做"**，只在有明确阻止信号时才踩。这反向解释了为什么前一轮要把 L4（模型自由发起）放在最低优先级、且 Gate 倾向打回——**滥问 = 一脚一脚乱踩刹车，比偶尔漏问更毁体验。**

**2. 踩刹车要有理由，且理由可追溯。** 每次澄清都对应一个具体阻止信号（缺哪个参、触发哪条高危规则、在哪两个动作间横跳）。`ClarificationRecord` 沉淀为 `USER_CONFIRMED` claim 且 `immutable=True`——这正是刹车的语义：**停下来确认过的事，不能再被模型推翻重走。**

**3. 刹车不能太灵敏也不能太迟钝。** 太灵敏=滥问，太迟钝=错误走远才停。你方案里 `MAX_CLARIFICATIONS_PER_TASK=3` 是刹车灵敏度上限，停滞检测是"迟钝兜底"——这套校准本质就是在调刹车的手感。

## 非工程师的提问设计：刹车要让乘客舒服

既然是刹车，对非工程师产品，核心问题变成：**如何让"被打断"这件事不引起焦虑、不需要专业知识就能回应。**

### 原则1：提问不能暴露系统的"不确定"，要表现为"为你着想"

这是刹车 vs 仪表盘的取舍落地。两种措辞：

```
❌ 仪表盘式（暴露不确定）：
   "我无法确定你指的是哪个环境，请明确。"
   → 用户感受：这系统不靠谱 / 我是不是说错了

✅ 刹车式（表现为谨慎）：
   "这一步会影响线上用户，先跟你确认下 👇"
   → 用户感受：它在替我把关
```

**同一个停车动作，框架成"我不行"会掉信任，框架成"我谨慎"会涨信任。** 非工程师对前者的容忍度极低。

### 原则2：选项必须是"后果"，不是"参数"

非工程师不认识参数，只认识后果：

```
❌ 参数语言：    ① env=prod    ② env=staging
❌ 半吊子翻译：  ① 正式环境    ② 预发布环境     ← 仍需要知道这俩区别
✅ 后果语言：    ① 现在就让所有用户看到
                ② 先放个内部预览，确认没问题再公开
```

这对应你方案里 `label_user` 字段——但验证发现 `label_user` 还不够，应该是 **`consequence_user`：描述"选了会发生什么"，而不是"这个选项叫什么"。** 把命名权从"维度"转到"后果"，这是面向非工程师的关键升级。

### 原则3：永远留"我不知道"的出口

非工程师常常**也答不上来**（"我哪知道要哪个环境"）。强迫在两个看不懂的选项里选，比不问还糟。所以那个自由输入框要升级成：

```
┌──────────────────────────────────┐
│  ① 现在就公开发布                  │
│  ② 先内部预览                      │
│                                    │
│  🤷 我不确定，你帮我决定           │  ← 关键第三选项
└──────────────────────────────────┘
```

"我不确定"这个选项的处理：**框架回退到安全默认**（部署场景=选更可逆的那个，即预览/测试），并明确告知"那我先用更稳妥的方式，随时能改"。这把刹车的语义补完整了——**停下来不是为了考用户，是为了在用户也没主意时，由系统兜住一个安全选择。**

### 原则4：一次只踩一脚刹车

非工程师无法并行处理多个决策。对应方案里的 `dim_order` 和渐进下钻——**一次只问一个维度，答完再问下一个**，哪怕慢一点。多选项卡片堆在一起（你原型里 3 个并列）对非工程师都偏多，**2 个后果选项 + 1 个"你决定"是上限。**

## 收束

澄清在治理层里是**刹车系统**：默认松开（不问先做）、有信号才踩（框架检测）、有理由可追溯（沉淀为 immutable claim）、对乘客友好（后果语言+安全兜底+一次一问）。

它顺带提供方向盘（用户选择）和仪表盘（暴露状态）的功能，但**设计时永远优先满足刹车语义**——当"展示不确定性"和"让用户安心"冲

## Round 10 — 开发者

请总结这次讨论的核心结论，给出：
1. '澄清'能力的最终架构设计（一段话描述）
2. 最小可行实现（第一步做什么）
3. 这个能力对 Educe 产品价值的预期影响
4. 最大的风险（可能做错什么）
不超过 300 字。

## Round 10 — Opus 4.8

# 澄清能力：核心结论

**1. 最终架构（一段话）**
澄清是治理层的**刹车系统**：默认松开（不问先做），只在框架检测到客观阻止信号时触发。补偿栈四层按可靠性串联——L1 框架信号（缺参/候选枚举/高危规则）、L2 模板库（任务类型→必填维度清单）、L3 停滞兜底（横跳动作直接当选项捞回漏判）、L4 模型自由发起（最低优先级，必过 Gate）。**弱模型只负责"问什么"，框架负责"何时问"。** 每次澄清沉淀为 immutable claim。

**2. 最小可行实现（第一步）**
先做 **L1 缺参检测 + 高危规则**：从 tool schema 读 required args，缺失则停；维护一张高危操作白名单（部署/删除/不可逆）强制确认。零模型判断、纯结构检测，最可靠，覆盖约 60% 场景。

**3. 产品价值**
对非工程师：把"系统不确定"转译为"系统在替我把关"——同一次打断，措辞决定信任涨跌。选项用**后果语言**（"现在公开发布"而非"env=prod"），永留"你帮我决定"出口并回退安全默认。澄清成为信任的来源，而非可靠性的破绽。

**4. 最大风险**
**滥问**——一脚一脚乱踩刹车比偶尔漏问更毁体验。若 default 倾向"问"、或 Gate 失守放行无实质分歧的提问，非工程师会迅速失去耐心。守住"默认不问、一次一问、最多三次"。
