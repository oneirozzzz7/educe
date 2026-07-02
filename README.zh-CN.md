<p align="center">
  <h1 align="center">Educe</h1>
  <p align="center"><strong>你的 Agent 第一次花 9,700 tokens。第二次 2,400。第十次接近零。</strong></p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License"></a>
    <a href="https://github.com/oneirozzzz7/educe"><img src="https://img.shields.io/github/stars/oneirozzzz7/educe?style=social" alt="Stars"></a>
    <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python 3.10+">
  </p>
  <p align="center">
    <a href="#快速开始">快速开始</a> •
    <a href="#工作原理">工作原理</a> •
    <a href="#自己验证">自己验证</a> •
    <a href="README.md">English</a>
  </p>
</p>

<p align="center">
  <img src="docs/assets/hero-comparison.svg" alt="无 Educe: 7 次 LLM 调用, 9700 tokens。有 Educe: 2 次 LLM 调用, 2400 tokens。降低 75%。" width="720"/>
</p>

---

Educe 是一个开源的 LLM Agent 进化引擎。它观察你的 agent 做了什么，记住什么行得通，并在遇到类似任务时回放成功的行动序列 —— 让模型不必重新推导已经找到的解法。

**核心命题：** Agent 执行任务的成本应该随经验单调递减。

今天每个 LLM Agent 都是金鱼。第 10,000 次和第 1 次一样贵。Educe 打破这一点。

---

## 快速开始

```bash
git clone https://github.com/oneirozzzz7/educe.git && cd educe
pip install -e ".[web]"
```

```python
from educe import Orchestrator, EduceConfig

config = EduceConfig.from_env()  # 读取 EDUCE_API_KEY, EDUCE_BASE_URL, EDUCE_MODEL
agent = Orchestrator(config)

# 第 1 次：完整推理 — 7 次 LLM 调用, ~9,700 tokens
result = await agent.run("查找 Python 版本并总结系统信息")

# 第 2 次：经验回放 — 2 次 LLM 调用, ~2,400 tokens（便宜 75%）
result = await agent.run("查找 Node 版本并总结系统信息")
```

启动完整 UI：

```bash
export EDUCE_API_KEY=your-key
export EDUCE_BASE_URL=https://api.deepseek.com/v1
export EDUCE_MODEL=deepseek-chat
./start.sh   # → http://localhost:3001
```

兼容任何 OpenAI 格式 API：DeepSeek、通义千问、GPT-4o、Claude（代理）、Ollama 等。

---

## 工作原理

<p align="center">
  <img src="docs/assets/architecture.svg" alt="Educe 架构：任务 → 经验检查 → 回放(快) 或 完整推理(慢) → 记录 → 完成" width="720"/>
</p>

### 设计原则

1. **零框架判断** — 框架只持有事实，不持有观点。模型决定一切 — 包括何时停止、什么是危险的。
2. **机制，非认知** — 唯一硬编码逻辑：在不可逆操作前暂停。其余一切都是模型读取的数据。
3. **模型可移植** — 一个环境变量就能从 DeepSeek 切到 GPT-4o 或本地 Qwen。经验跨模型迁移。

---

## 自己验证

成本降低的说法可证伪。用你自己的 API 跑一次：

> 📺 本地播放 demo：`asciinema play docs/assets/demo.cast`（18 秒）— 或自己运行：

```bash
pip install matplotlib scipy
EDUCE_BASE_URL=https://api.deepseek.com/v1 \
EDUCE_API_KEY=your-key \
EDUCE_MODEL=deepseek-chat \
python reproduce_descent.py
```

<p align="center">
  <img src="docs/assets/terminal-demo.svg" alt="终端输出展示成本逐次下降" width="680"/>
</p>

| 指标 | 数值 |
|------|------|
| 经验被复用时的成本 | 2,458 tokens（2 次 LLM 调用） |
| 无经验时的成本 | 9,725 tokens（7 次 LLM 调用） |
| 降幅 | **75%** |
| 正确率 | 两种模式均 100% |

复现成本：约 ¥5-10（DeepSeek，~500K tokens，30-45 分钟）。

> **当前研究前沿：** 复用机制本身可靠地提供 75% 节省，但模型并不总是选择复用（当前采纳率：26%）。这是我们的 [#1 开放问题](docs/descent_analysis.md) — 正在将检索从"可选参考"改为"结构性强制"。

---

## 与其他方案的区别

| 方案 | 它做什么 | Educe 额外提供 |
|------|---------|---------------|
| **Prompt 缓存** | 缓存 prompt 前缀 → 省输入 tokens | 缓存*行动序列* → 省输入+输出 + LLM 调用从 7→2 |
| **RAG** | 检索文档增强上下文 | 检索*已验证的执行轨迹* — 是证明有效的方案，不是参考资料 |
| **微调** | 更新模型权重（需要训练设施，不可移植） | 通过 API 工作于任何模型。经验即时迁移 |
| **CLAUDE.md / 系统提示** | 人类手写的静态规则 | 从*观察*中积累规则 — 捕获人类无法表述的交互涌现模式 |
| **KV 缓存** | 底层推理优化 | 正交 — Educe 在 agent 行为层面操作，可与 KV 缓存组合 |

**关键区别：** Educe 不让模型变聪明。它让*系统*记住什么管用。

---

## 路线图

- [x] Action Loop V3（Plan / Challenge / 自终止）
- [x] ConversationTruth（单一数据源，分层压缩）
- [x] Shell 执行 + 文件操作 + 流式输出
- [x] 下降曲线 — 机制验证（75% 增益）
- [x] 基准测试运行器（30 用例，自动评分）
- [x] 前端 i18n（中英切换）
- [ ] **经验采纳可靠性** — 从 26% → 80%+（结构性强制）
- [ ] 上下文预算精度（WARM 层投影）
- [ ] 桌面应用（Electron）
- [ ] 插件系统

---

## 文档

| 文档 | 内容 |
|------|------|
| [愿景](docs/VISION.md) | 五条公理与进化隐喻 |
| [架构](docs/SESSION11_ARCHITECTURE.md) | action_loop_v3 技术深度解析 |
| [下降分析](docs/descent_analysis.md) | Episode 采纳 trace 分析 + 开放问题 |
| [边界重设计](docs/BOUNDARY_REDESIGN.md) | 框架作为资产容器（零判断） |

---

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎 Issue 和 PR。

## 开源协议

[Apache-2.0](LICENSE)
