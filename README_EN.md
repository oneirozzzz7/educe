# DeepForge 🔥

**Make weak LLMs do strong work through multi-agent collaboration**

[中文](./README.md) | English

---

DeepForge enables open-source/affordable LLMs (DeepSeek, Qwen, GLM, Kimi, etc.) to accomplish complex tasks—previously only achievable by flagship models like Claude or GPT-4—through a 7-agent collaborative pipeline. It evolves and gets stronger with every use.

## Key Features

- 🧠 **7-Agent Pipeline**: Project Manager → Product Manager → Architect → Engineer → Reviewer → Crowd Users → Memory Keeper
- 🔀 **Multi-Model Support**: DeepSeek / Qwen / GLM / Kimi / Ollama (local) / OpenRouter — unified interface
- 📈 **Self-Evolving**: Memory system auto-distills knowledge; Skill system makes experience reusable across projects
- 💻 **Dual Interface**: CLI (developers) + Web UI (non-technical users), powered by the same engine
- ⚡ **Ultra-Lightweight**: Zero external service dependencies, `pip install` and go
- 🎭 **Crowd Testing**: Innovative multi-persona simulated user testing — from beginners to power users

## Quick Start

### Installation

```bash
# Basic (CLI only)
pip install -e .

# Full (with Web UI)
pip install -e ".[web]"
```

### Configuration

```bash
# Option 1: Environment variable (fastest)
export DEEPSEEK_API_KEY=your-api-key

# Option 2: Config file
deepforge init
# Edit the generated deepforge.yaml
```

### Usage

```bash
# CLI interactive mode (recommended for developers)
deepforge chat

# Web UI (recommended for non-technical users)
deepforge web
# Open http://localhost:7860 in your browser

# One-shot task (non-interactive)
deepforge run "Build me a Pomodoro timer web app"

# Short alias
df chat
df web
```

## Agent Team

| Agent | Role | Responsibility |
|-------|------|----------------|
| 🎯 | Project Manager | Understand user intent, orchestrate workflow, break down tasks |
| 📋 | Product Manager | Analyze requirements, write PRD, define acceptance criteria |
| 🏗️ | Architect | Technology selection, system design, task decomposition |
| 💻 | Engineer | Full implementation, write tests, ensure code runs |
| 🔍 | Reviewer | Code review, security audit, quality control |
| 👥 | Crowd Users | Multi-persona simulated testing, diverse feedback |
| 🧠 | Memory Keeper | Knowledge distillation, skill evolution, documentation |

## Supported Models

| Provider | Example Model | Env Variable | Notes |
|----------|---------------|--------------|-------|
| DeepSeek | deepseek-chat | `DEEPSEEK_API_KEY` | Recommended, cost-effective |
| Qwen | qwen-plus | `QWEN_API_KEY` | Alibaba Cloud |
| GLM | glm-4-flash | `GLM_API_KEY` | Generous free tier |
| Moonshot/Kimi | moonshot-v1-8k | `KIMI_API_KEY` | Long context |
| Ollama | qwen2.5:7b | None (local) | Fully free & offline |
| OpenRouter | Any model | `OPENROUTER_API_KEY` | Aggregator |

Compatible with any OpenAI-compatible API endpoint.

## Project Structure

```
deepforge/
├── core/               # Core engine
│   ├── agent.py        # Base agent class
│   ├── config.py       # Configuration (YAML + env vars)
│   ├── message.py      # Message protocol & task model
│   └── orchestrator.py # Orchestrator (pipeline + free routing)
├── agents/             # 7 agent implementations
├── models/             # Model router (multi-model adapter)
├── memory/             # Memory system (JSON persistence)
├── skills/             # Skill registry (builtin + user + community)
├── tools/              # Toolbox (file I/O, shell, search)
├── cli/                # CLI interface (Rich-powered)
└── web/                # Web UI (FastAPI + WebSocket)
```

## Evolution Mechanism

DeepForge's core differentiator — **it gets stronger with use**:

```
1st use   → Complete task → Memory Agent distills knowledge
2nd use   → Retrieve relevant memory → Faster & better results
Nth use   → Accumulated Skill templates → Near one-click completion
Community → Shared Skills → Everyone benefits
```

1. **Memory Distillation**: Auto-extracts reusable knowledge after each project
2. **Skill Generation**: Recurring workflows become Skill templates
3. **Community Sharing**: User-contributed Skills benefit the entire community
4. **Prompt Self-Optimization**: Auto-tunes agent prompts based on success/failure signals

## Comparison

| Feature | DeepForge | MetaGPT | CrewAI | OpenCode |
|---------|-----------|---------|--------|----------|
| Weak-model optimization | ✅ Core design | ❌ | ❌ | ❌ |
| Crowd user testing | ✅ | ❌ | ❌ | ❌ |
| Memory evolution | ✅ | Partial | ❌ | ❌ |
| Chinese model native support | ✅ | Partial | ❌ | ❌ |
| Web UI | ✅ | ❌ | ❌ | ❌ |
| Lightweight | ✅ | ❌ (heavy) | ✅ | ✅ |

## Roadmap

- [x] Core engine + 7 Agents
- [x] CLI + Web dual interface
- [x] Memory system + Skill registry
- [ ] Auto-rollback on review failure
- [ ] More built-in Skill templates
- [ ] Community Skill marketplace
- [ ] Multi-turn iterative refinement
- [ ] Visual workflow editor

## License

Apache 2.0
