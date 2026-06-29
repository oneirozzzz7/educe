# Educe Integration Test Guide

## Quick Start

```bash
# Prerequisite: backend + frontend must be running
./start.sh  # Starts backend(7860) + frontend(3000)

# Set API key for judge scoring
export EDUCE_TEST_API_KEY="your-api-key"

# 运行所有合同
python -m educe.testing

# 运行单个场景
python -m educe.testing --scenario file_reference

# 显示浏览器窗口（调试用）
python -m educe.testing --scenario shell_execution --headed

# 全维度（含截图美观度 judge）
python -m educe.testing --full
```

## 合同（Contracts）

测试以 YAML 合同声明式编写，放在 `educe/testing/contracts/` 下。

| 合同 | 覆盖场景 | 验证维度 | 耗时 |
|------|----------|----------|------|
| `file_reference` | @ 文件引用注入 + 模型直接回答 | UI/逻辑/格式/日志/可观测 | ~7s |
| `shell_execution` | echo → python → 管道命令 | UI/逻辑/日志 | ~18s |
| `multi_turn_dialogue` | 多步任务（写→读→改→验证） | UI/逻辑/格式/日志 | ~23s |
| `progressive_reasoning` | LLM 生成 3 级递进问题 + judge 评分 | 逻辑/格式/日志/judge | ~23s |
| `error_resilience` | 不存在文件/失败命令/特殊字符/并发 | UI/逻辑/日志 | ~25s |

## 什么时候跑什么

| 改了什么 | 跑什么 |
|----------|--------|
| 前端组件（activity-feed/sidebar） | `file_reference` |
| orchestrator 数据流 | `file_reference` + `shell_execution` |
| action 执行逻辑 | `shell_execution` + `multi_turn_dialogue` |
| prompt / 行为规则 | `progressive_reasoning` |
| 错误处理 / 超时 | `error_resilience` |
| 日志系统 | 全部（`python -m educe.testing`） |
| **用户说"全面测试"** | `python -m educe.testing --full` |

## 写新合同

### 合同结构

```yaml
scenario: my_scenario_name
description: "一句话描述"

setup:
  ensure_files:
    - path: "/tmp/test_file.txt"
      content: "文件内容"

steps:
  - name: "step_name"
    description: "这步做什么"
    action:
      type: "action_type"
      # ... action 参数
    verify:
      ui:
        - { has_text: "预期文本", description: "断言描述" }
      logic:
        - { contains_any: ["锚点1", "锚点2"], description: "语义验证" }
      logs:
        - event_exists: "event_name"
```

### Action 类型

| type | 用途 | 关键参数 |
|------|------|----------|
| `send_message` | 发送消息 | `text` |
| `type_and_select` | 输入 + 选择（如 @ 文件） | `input`, `select: "enter"` |
| `auto_confirm_loop` | 等待处理完成，自动点 Confirm | `timeout: 30` |
| `multi_turn_wait` | 等 Idle（不点 Confirm） | `timeout: 15` |
| `wait_for_reply` | 等 AI 回复出现（DOM 级） | `timeout: 15` |
| `click` | 点击元素 | `selector` |
| `click_if_exists` | 有才点 | `selector` |
| `generate_question` | LLM 生成随机问题并发送 | `template` (含 `{seed}`) |
| `screenshot` | 截图保存 | `name` |
| `wait_for_action` | 等 action 行出现 | `min_count`, `timeout` |

### Verify 维度

**ui** — DOM 状态
```yaml
- { has_text: "文本", description: "..." }
- { has_element: ".css-selector", description: "..." }
- { has_markdown: true, description: "..." }
- { no_overflow: true, description: "..." }
- { no_raw_html: true, description: "..." }
- { action_lines_visible: 1, description: "..." }
- { status_idle: true, description: "..." }
- { user_bubble_contains: "文本", description: "..." }
```

**logic** — 语义正确性
```yaml
- { contains_any: ["答案1", "答案2"], description: "..." }
- { not_contains: ["不该出现"], description: "..." }
- { not_empty: true, description: "..." }
- { judge_quality: "评分标准描述", min_score: 6, description: "..." }
```

**format** — 回复格式
```yaml
- { min_length: 10, description: "..." }
- { max_length: 500, description: "..." }
- { has_structure: true, description: "..." }
```

**logs** — 日志完备性（读 `.educe/logs/sessions/` 最新 jsonl）
```yaml
- event_exists: "event_name"
- event_sequence: ["evt1", "evt2", "evt3"]
- { event_field: { path: "data.has_file", equals: true } }
- { field_gt: { event: "model_called", path: "data.prompt_chars", value: 4000 } }
- { no_event_type: { name: "action_executed", action_type: "read_dir" } }
- { action_count_gte: 2, description: "..." }
- { multi_round: 2, description: "..." }
- { has_action_type: "shell", description: "..." }
```

**pipeline** — 前后端数据流
```yaml
- { ws_sent: true, description: "..." }
```

**observability** — 可观测性
```yaml
- { events_visible: true, description: "..." }
```

**aesthetic** — 美观度（需 `--full`）
```yaml
- { judge_prompt: "评分提示...", min_score: 7 }
```

## 随机化问题生成

`progressive_reasoning` 合同使用 `generate_question` action：

```yaml
action:
  type: "generate_question"
  template: |
    生成一个关于 X 的问题。种子={seed}。
    要求：有明确答案，难度 2/3。
  context: {}
```

- `{seed}` 基于当前小时自动生成（每小时变化一次）
- 每次运行产生不同问题，但验证锚点不变量
- 用 `judge_quality` 做语义评分而不是字符串匹配

## 已知问题和 TODO

| 问题 | 状态 | 原因 |
|------|------|------|
| `multi_turn_dialogue` logic verifier 取到 action 行 | 待修 | `.ai-reply` 选择器匹配不够精确 |
| `progressive_reasoning` tier2 模型幻觉 | 产品 bug | 模型没执行脚本而是编造数据 |
| `shell_execution` 管道命令 timing | 偶发 | auto_confirm 退出后结果还没渲染 |
| aesthetic judge 未实现 | TODO | 需要接 Claude-Sonnet 截图评分 |

## 设计原则

1. **不硬编码** — 合同用语义锚点（"回复含 0"）而非固定措辞
2. **每步全维度** — 一个 step 同时验证 UI/逻辑/日志/格式
3. **真实操作** — Playwright 模拟用户点击，不绕过前端
4. **隔离** — 每个场景新 session，互不干扰
5. **渐进难度** — 从基础到进阶，random seed 避免重复
6. **失败即证据** — 断言失败自动截图保存现场
