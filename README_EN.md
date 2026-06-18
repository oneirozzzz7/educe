# Educe

**A runtime compiler from deliberation to reflex — making AI behavior cost decrease monotonically with experience.**

[中文](./README.md) | English

---

Educe gives any LLM (DeepSeek, Qwen, Kimi, etc.) an external learning pathway beyond frozen weights. Repeated successful behaviors are compiled from expensive LLM deliberation into zero-cost reflexes. The system gets cheaper and faster with every use — not by changing the model, but by accumulating verified behavioral shortcuts.

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
export EDUCE_API_KEY=your-api-key
export EDUCE_BASE_URL=https://api.deepseek.com/v1
export EDUCE_MODEL=deepseek-chat

# Option 2: Use start.sh (auto-loads .env)
./start.sh
```

### Usage

```bash
# One-command start (backend + frontend)
./start.sh
# Open http://localhost:3001 in your browser
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
educe/
├── core/               # Core engine
│   ├── orchestrator.py # Behavior loop + reflex router
│   ├── metabolism/     # Causal ledger, path miner, skill compiler
│   ├── agent.py        # Base agent class
│   └── config.py       # Configuration (YAML + env vars)
├── config/             # Declarative knowledge (shell taxonomy, resource delta)
├── models/             # Model router (multi-model adapter)
├── tools/              # Toolbox (file I/O, shell, search)
└── web/                # Web UI (FastAPI + Next.js)
```

## Evolution Mechanism

Educe's core differentiator — **behavior cost decreases monotonically with experience**:

```
Experience (causal ledger) → Patterns (path mining) → Skills (compilation) → Reflexes (zero-cost execution)
```

1. **Causal Ledger**: Every action-outcome pair is recorded with context signatures
2. **Path Mining**: Recurring multi-step sequences are discovered across sessions
3. **Skill Compilation**: Stable paths are compiled into L0→L4 composite skills
4. **Reflex Takeover**: L3+ skills bypass the LLM entirely for verified scenarios

## Comparison

| Feature | Educe | Claude Code | LangChain | AutoGen |
|---------|-------|-------------|-----------|---------|
| Cost decreases with use | ✅ Core design | ❌ (flat) | ❌ | ❌ |
| Zero-token reflex execution | ✅ L3+ | ❌ | ❌ | ❌ |
| Model-agnostic | ✅ | ❌ (Anthropic) | ✅ | ✅ |
| Self-evolving skills | ✅ | ❌ | ❌ | ❌ |
| Honest convergence tracking | ✅ | ❌ | ❌ | ❌ |

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
