# Opus 4.8 讨论：context_sig 投影函数设计

> 2026-06-17 Session 3，阶段2 P0 实现前的架构讨论

## 提问摘要

核心矛盾：shell→shell→shell 出现 466 次但语义完全不同。如果 sig 只看 action_type → 噪声爆炸；如果看完整 params → 永远不重复。

数据现状：2043 records / 252 sessions / shell 占 52% / 758 unique params

## Opus 核心回答

### 1. 分层投影（最关键洞察）

**把 task_type 和 user_input 从 sig 中拿出来，作为"挖掘域（scope key）"做预分组。**

两个不同目标被塞进一个签名会同时遭遇桶爆炸和噪声：
- task_type / user_input = 会话级意图（决定"这是什么任务"）
- action 语义 / step_position = 序列级结构（决定"这步在做什么"）

### 2. 最终 sig 结构

```python
@dataclass(frozen=True)
class StepSig:
    verb: str       # "shell.git" | "write_file" | ...  (~25 取值)
    outcome: str    # "ok" | "err"                       (2 取值)
    rdelta: str     # "+file" | "-file" | "read" | "none" (4 取值)
```

### 3. 关键决策

| 维度 | 处理方式 | 理由 |
|------|----------|------|
| task_type | → scope，不进 sig | 同域内序列才有可比性 |
| action_verb | 进 sig（核心） | shell 拆 ~15 子类 |
| outcome | 进 sig | success/failure 后续完全不同 |
| resource_delta | 进 sig | 状态转移信息 |
| **prev_action_type** | **删掉** | n-gram 滑窗已编码前驱信息，加 prev 是冗余维度 |
| **step_position** | **后置处理** | 不进 sig，挖出 pattern 后做位置画像 |

### 4. Shell 子分类

用 head + keyword 规则投影到约 15 个语义子类。验证结果：other < 11%。

### 5. 验证方法

- **指标 A**：shell.other 占比 < 15%
- **指标 B**：归并比 5~30（记录数/唯一 sig 数）
- **指标 C**：support≥3 的 trigram 数在 20~60（用跨 session 数而非出现次数）
- **指标 D**：人工抽查头部桶内 params 同质性

### 6. Support 用 session 数

> 一个 session 内重复的 shell→shell 不应被算成"稳定模式"。这直接掐掉 466 次 shell→shell 噪声的根源。

## 验证结果

| 指标 | 结果 | 目标 | 状态 |
|------|------|------|------|
| A: shell.other | 10.0% | < 15% | ✅ |
| B: Merge Ratio | 28.0 | 5~30 | ✅ |
| C: Unique trigrams | 866 | 200~600 | ⚠️ 偏多（数据丰富） |
| C: Compilable (sup≥3) | 88 | 20~60 | ⚠️ 偏多（调 sup≥5 → 32） |

## 挖掘结果 Top Patterns

| Support | Pattern | 语义 |
|---------|---------|------|
| 29 | mutate→write_file→write_file | 项目脚手架 |
| 24 | read_lines→read_lines | 连续读代码 |
| 21 | write_file→shell.python | 写代码→运行 |
| 16 | search→read_lines→read_lines | 搜索→读代码 |
| 11 | python[err]→write_file→python[ok] | 调试循环 |
