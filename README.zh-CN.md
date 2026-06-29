# Educe

**第一个会承认"我没做到"的 AI 执行助手**

让 AI 不只是告诉你怎么做，而是帮你做完，并诚实地告诉你到底成没成。

---

## 它能做什么

说出你想要的，Educe 帮你执行：

- "帮我写一个待办管理的 Python 脚本" → 创建文件 + 运行验证 + 确认能用
- "用 pandas 处理 data.csv 算每列平均值" → 安装依赖 + 创建数据 + 执行计算
- "搭一个 Flask API 项目" → 多文件创建 + 启动服务 + curl 测试

**和 ChatGPT 的区别**：Educe 真的执行，不只是给你一段代码让你自己跑。

**和 AutoGPT 的区别**：Educe 知道自己的边界——做不到时会说"这个我搞不定，你可能需要换个方案"，而不是假装完成或无限重试。

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/oneirozzzz7/educe.git
cd educe

# 2. 安装
pip install -e ".[web]"

# 3. 配置模型（任选一个）
export EDUCE_API_KEY=your-api-key
export EDUCE_BASE_URL=https://api.deepseek.com/v1
export EDUCE_MODEL=deepseek-chat

# 4. 启动
./start.sh
# 或手动：python -c "from educe.web.server import run_web; run_web()"

# 5. 打开浏览器
# http://localhost:3001 (前端) 或 http://localhost:7860 (API)
```

前端（可选，更好的 UI）：
```bash
cd web && npm install && npm run dev
# 访问 http://localhost:3001
```

## 支持的模型

任何 OpenAI 兼容 API 都可以用：

| 模型 | 推荐场景 | 配置 |
|------|---------|------|
| DeepSeek-V3 | 日常使用，便宜 | `EDUCE_BASE_URL=https://api.deepseek.com/v1` |
| Qwen3 系列 | 中文任务 | 通义千问 API |
| GPT-4o-mini | 快速可靠 | OpenAI API |
| 本地模型(Ollama) | 离线/隐私 | `EDUCE_BASE_URL=http://localhost:11434/v1` |

## 核心机制

### 收敛追踪
每个任务的执行过程被实时追踪。你能看到系统在"学习"——从尝试、失败、到最终成功的完整弧线。

### 诚实退出
当系统发现自己连续多轮无法解决某个问题时，会主动告知你，而不是无限重试浪费你的时间。

### 环境感知
框架自动告知模型运行环境的约束（沙箱限制、端口占用等），让模型一次做对，而不是反复试错。

### 错误恢复
遇到依赖缺失、文件不存在等问题时，模型会自动安装/创建/修复，无需你手动干预。

## 技术架构

```
用户输入 → Orchestrator(行为循环)
              ↓
         模型推理（带环境约束 + 行为规则）
              ↓
         Action 执行（shell/write_file/read_dir）
              ↓
         IterationState 更新（收敛追踪）
              ↓
         结果反馈 → 继续/完成/诚实退出
```

## 开发状态

- [x] 核心执行引擎（ActionLoop + Markdown-native Protocol）
- [x] 收敛系统（IterationState + Prober + 自动 Claim 关闭）
- [x] 环境约束（5 个，消除常见失败模式）
- [x] 诚实退出（停滞检测 + 用户告知）
- [x] Web 前端（收敛可视化 + 确认机制）
- [x] 行为学习（BehaviorManifest）
- [x] 因果账本 + 路径挖掘器（阶段2：分化）
- [x] CompositeSkill 编译（L0-L4 多级形态）
- [x] ReflexRouter 反射弧（阶段3：零 token 执行高频只读情境）
- [ ] 多反射弧协同（阶段4：器官）
- [ ] Electron 桌面应用（一键安装）
- [ ] Windows 支持

## License

[Apache-2.0](LICENSE)
