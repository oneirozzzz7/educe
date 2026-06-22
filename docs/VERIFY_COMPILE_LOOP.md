# Verify-Compile Loop 设计规格

*2026-06-20 · Session 5 深度讨论成果 · Opus 4.8 × 4 轮*

---

## 核心命题

> **学习 ≠ 获取信息。学习 = 在当前环境中确认"哪条信息是真的"。**

Educe 进化的不是智力（那是模型的事），是**对自己所处世界的确定性**。

---

## 一、架构概览

```
                    ┌─────────────────────────────────┐
   新问题 ─────────▶│  Planner（LLM）                  │
                    │  生成"假设链"，不是"答案"         │◀── 注入：策略先验(L3)
                    └──────────────┬──────────────────┘    + 已有 skill(L2)
                                   │                         + 环境记忆(L1)
                                   ▼
                    ┌─────────────────────────────────┐
                    │  Executor + Verifier             │
                    │  逐假设执行，每步必须有验证点     │
                    └──────────────┬──────────────────┘
                                   │
                      ┌────────────┴────────────┐
                  验证通过                    验证失败
                      │                          │
                      ▼                          ▼
              ┌───────────────┐        ┌──────────────────┐
              │ 收集成功 trace │        │ 失败归因分类      │
              └───────┬───────┘        └────────┬─────────┘
                      │                         │
                      ▼              环境缺失→修复重试
              ┌───────────────┐      认知错误→搜索+重规划
              │ Compiler       │      不可恢复→停下问人
              │ trace→skill    │
              │ (抽象+参数化)  │
              └───────┬───────┘
                      │
                      ▼
              更新 L1/L2/L3 ────────────────────▶（回流到下次 Planner）
```

---

## 二、三层学习

| 层 | 内容 | 消除 | 持久化 |
|---|---|---|---|
| L1 环境记忆 | "这台机器装了什么，账号长什么样" | 重复探测 | .educe/env_facts.json |
| L2 技能库 | "这类问题用这条验证链解决" | 重复试错 | .educe/skills/ (已有) |
| L3 策略先验 | "面对X类问题先验证Y" | 重复犯错 | system prompt 注入 |

---

## 三、失败归因分类

| 失败类型 | 信号 | 应对 | 自动化程度 |
|---------|------|------|-----------|
| 环境缺失 | `command not found` / `No module` | 安装依赖重试 | 全自动 |
| 配置/权限 | `AccessDenied` / `Permission` | 需信息或用户介入 | 半自动 |
| 认知错误 | 方案本身错了 | 搜索/重规划 | 需搜索能力 |
| 不可恢复 | 余额不足/硬件限制 | 停下告知用户 | 全自动（止损） |

---

## 四、当前已实现（Session 5）

- [x] 失败反思注入（stderr → 引导模型分析+分类+调整）
- [x] 成功/失败验证信号（✓/✗ 前缀）
- [x] 器官系统（偏好层：verbosity + code_lang）
- [x] OrganRegistry（多器官并存）

---

## 五、执行状态（Session 6 更新）

### 已完成
| 任务 | 状态 | 验证 |
|------|------|------|
| 失败分类器 | ✅ | 8/8 单元测试 + E2E(tabulate 安装重试) |
| 环境缺失自动修复 | ✅ | pip install → 重试 → 成功 |
| 成功轨迹自动编译 | ✅ | fib.py 自动注册到 SkillRegistry |
| 失败反思注入 | ✅ | buggy.py 修复 E2E |
| 复利记忆注入 | ✅ | scar 预警 E2E（clarify 死循环） |
| web_search（shell curl） | ❌ 搁置 | 不可靠，需接真 API |

### 下次 Session 执行清单（优先级排序）

| 优先级 | 任务 | 验收标准 |
|--------|------|---------|
| **P0 稳定化** | except:pass → log+决定 | grep 全部裸 except，改为具体异常+日志+降级。0 个裸 except 残留 |
| **P0 稳定化** | 主路径 smoke test | 输入"写 /tmp/test.py 打印 hello 并运行" → 断言 exit 0 + 文件存在 |
| **P0 稳定化** | 非核心模块失败隔离 | 手动让 VerbosityOrgan init 抛异常 → 主路径仍正常 |
| **P1** | 记忆自动写入 | 失败反思→自动写入 scar / 成功事实→自动写入 fact / 用户纠正→convention |
| **P1** | 冲突仲裁 | 新记忆和旧记忆矛盾→标记 disputed→呈现用户→裁决 |
| **P1** | Verify-on-Read | 注入记忆时检查 anchor（文件在？变了？）→ confirmed++ 或 challenged++ |
| **P2** | orchestrator.py 拆分 | shell/file executors 抽出 → orchestrator < 2000 行 |
| **P2** | 器官降级为数据 | VerbosityOrgan → ProjectMemoryStore 里的 type=convention 条目 |
| **P2** | web_search 接真 API | Tavily/Serper key 配置 → 结构化搜索结果 |

---

## 六、设计判据（决策时用）

1. **它产生的是"假设"还是"已验证的知识"？** 只缓存后者。
2. **它学到的东西有没有"失效条件"？** 没有失效条件的知识是定时炸弹。
3. **它是在收敛到具体环境，还是在复制 LLM 已有的能力？** 后者让 LLM 现场算。

---

## 七、工具观（第一性原理）

> 工具不是名词（资产清单），是动词（撬动关系）。

有机体的三个核心能力：
- **识别**：什么可以成为工具（affordance 感知）
- **制造**：把成功的撬动沉淀为可复用杠杆
- **弃用**：让失效工具死亡（新陈代谢）

Educe 的核心机制是**在任意情境下把世界的某一部分识别为杠杆、建立借力关系、沉淀有效关系、淘汰失效关系的代谢循环**。

---

## 八、记忆自动写入方案（下次 Session 执行）

### 写入来源与触发条件

| 来源 | 触发条件 | 记忆类型 | 初始 confidence |
|------|---------|----------|----------------|
| 失败反思 | shell exit≠0 且分类为认知错误 | scar | 0.90 |
| 用户纠正 | 用户对结果说"不对/应该是X" | convention | 0.95 |
| 重复成功模式 | 同类操作成功 ≥3 次 | fact | 0.70 |
| 环境发现 | 首次探测到环境信息（已装软件/路径） | fact | 0.50 |

### 写入格式

```python
# 在 action_loop 的 turn_end 时：
if had_failure and classification.kind == "cognitive":
    memory_store.add(MemoryEntry(
        id=gen_id(),
        type="scar",
        content=f"执行 {cmd} 时因 {error_reason} 失败，正确做法是 {fix_description}",
        anchor={"type": "file", "ref": relevant_file},
        confidence=0.90,
        provenance={"born": trace_id},
    ))
```

### 防爆炸机制

- 凝结阈值：单次观察不写入，重复出现 ≥N 次才凝结为记忆
- 去重：写入前检查是否已有相似内容（content 相似度）
- 容量上限：总记忆条数上限（如 200），超出时淘汰最低 confidence 的

### Verify-on-Read（验证闭环）

```python
# 注入记忆时：
for mem in active_memories:
    if mem.anchor and mem.anchor["type"] == "file":
        path = Path(mem.anchor["ref"])
        if not path.exists():
            mem.provenance["challenged"].append(trace_id)
            if len(mem.provenance["challenged"]) >= 3:
                soft_delete(mem)
        else:
            mem.provenance["confirmed"].append(trace_id)
            mem.verified_at = time.time()
```

---

*下次 session 从记忆自动写入开始。把"手写 5 条记忆"升级为"系统自动沉淀"。*
