# DeepForge 🔥

**用弱模型做强活的多Agent框架**

[English](./README_EN.md) | 中文

---

DeepForge 让 DeepSeek、Qwen、GLM、Kimi 等开源/国产模型，通过 7 个专业 Agent 协作，完成原本只有旗舰模型（如 Claude、GPT-4）才能做好的复杂工作。越用越强，自我进化。

## 核心特性

- 🧠 **7 Agent 协作流水线**: 项目经理 → 产品经理 → 架构师 → 工程师 → 审查专家 → 群像用户 → 记忆守护者
- 🔀 **多模型统一接入**: DeepSeek / Qwen / GLM / Kimi / Ollama 本地模型 / OpenRouter
- 📈 **越用越强**: 记忆系统自动沉淀知识，Skill 系统让每次项目经验可复用，社区贡献形成网络效应
- 💻 **双界面**: CLI（开发者/工程师） + Web UI（小白/产品经理），同一套引擎
- ⚡ **极致轻量**: 核心零外部服务依赖，`pip install` 即用
- 🎭 **群像内测**: 独创多角色模拟用户内测机制，从小白到极客多视角评审产品

## 快速开始

### 安装

```bash
# 基础安装（CLI模式）
pip install -e .

# 完整安装（含Web UI）
pip install -e ".[web]"
```

### 配置

```bash
# 方式1: 环境变量（最快上手）
export DEEPSEEK_API_KEY=your-api-key

# 方式2: 初始化配置文件
deepforge init
# 编辑生成的 deepforge.yaml 填入 API Key
```

### 使用

```bash
# CLI 交互模式（开发者推荐）
deepforge chat

# Web UI（小白/产品经理推荐）
deepforge web
# 浏览器访问 http://localhost:7860

# 一次性任务（非交互）
deepforge run "帮我做一个番茄钟网页应用"

# 快捷别名
df chat
df web
```

## Agent 团队

| Agent | 角色 | 职责 |
|-------|------|------|
| 🎯 | 项目经理 | 深度理解用户意图，统筹全局，任务拆解与调度 |
| 📋 | 产品经理 | 需求分析，输出PRD，定义功能优先级与验收标准 |
| 🏗️ | 架构师 | 技术选型，系统架构设计，编码任务拆分 |
| 💻 | 工程师 | 完整编码实现，编写测试，确保代码可运行 |
| 🔍 | 审查专家 | Code Review，安全检查，质量把控 |
| 👥 | 群像用户 | 模拟多种用户角色内测，提出多视角改进建议 |
| 🧠 | 记忆守护者 | 知识沉淀，技能提炼，让框架越用越强 |

## 支持的模型

| 提供商 | 模型示例 | 环境变量 | 备注 |
|--------|----------|----------|------|
| DeepSeek | deepseek-chat | `DEEPSEEK_API_KEY` | 推荐，性价比高 |
| 通义千问 | qwen-plus | `QWEN_API_KEY` | 阿里云 |
| 智谱GLM | glm-4-flash | `GLM_API_KEY` | 免费额度多 |
| Moonshot/Kimi | moonshot-v1-8k | `KIMI_API_KEY` | 长上下文 |
| Ollama | qwen2.5:7b | 无需（本地） | 完全免费离线 |
| OpenRouter | 任意模型 | `OPENROUTER_API_KEY` | 聚合平台 |

支持任何 OpenAI 兼容 API 的模型服务。

## 项目结构

```
deepforge/
├── core/               # 核心引擎
│   ├── agent.py        # Agent 基类
│   ├── config.py       # 配置系统（YAML + 环境变量）
│   ├── message.py      # 消息协议 & 任务模型
│   └── orchestrator.py # 调度器（pipeline + 自由路由）
├── agents/             # 7 个 Agent 实现
├── models/             # 模型路由器（多模型适配）
├── memory/             # 记忆系统（JSON持久化）
├── skills/             # 技能注册表（内置 + 用户 + 社区）
├── tools/              # 工具箱（文件读写/命令执行/搜索）
├── cli/                # CLI 终端界面（Rich美化）
└── web/                # Web UI（FastAPI + WebSocket）
```

## 进化机制

DeepForge 的核心差异化——**越用越强**：

```
第1次使用 → 完成任务 → 记忆Agent沉淀知识
第2次使用 → 检索相关记忆 → 更快更好地完成
第N次使用 → 积累的Skill模板 → 接近一键完成
社区贡献   → Skill共享 → 所有人受益
```

1. **记忆沉淀**: 每次项目完成后自动提炼可复用知识（模式、经验、坑点）
2. **技能生成**: 重复的工作流自动提炼为 Skill 模板
3. **社区共享**: 用户贡献的 Skill 可被全社区复用
4. **Prompt自优化**: 基于成功/失败反馈，自动优化各 Agent 的 prompt

## 与其他框架的对比

| 特性 | DeepForge | MetaGPT | CrewAI | OpenCode |
|------|-----------|---------|--------|----------|
| 弱模型优化 | ✅ 核心设计 | ❌ | ❌ | ❌ |
| 群像用户测试 | ✅ | ❌ | ❌ | ❌ |
| 记忆进化 | ✅ | 部分 | ❌ | ❌ |
| 中国模型原生支持 | ✅ | 部分 | ❌ | ❌ |
| Web UI | ✅ | ❌ | ❌ | ❌ |
| 轻量级 | ✅ | ❌（重） | ✅ | ✅ |

## 开发计划

- [x] 核心引擎 + 7 Agent
- [x] CLI + Web 双界面
- [x] 记忆系统 + Skill 注册表
- [ ] 审查不通过自动回退修改
- [ ] 更多内置 Skill 模板
- [ ] 社区 Skill 市场
- [ ] 多轮对话迭代优化
- [ ] 可视化工作流编辑器

## License

Apache 2.0
