# Educe

**A runtime compiler from deliberation to reflex.**

Educe is an open-source evolution engine that gives any LLM a learning path outside its weights. The core thesis: **an agent's cost to perform a task should monotonically decrease with experience.**

<!-- TODO: embed descent_curve.png here once generated -->

Every LLM-based system today pays the same token cost for the 10,000th execution of a task as it did for the 1st. Educe breaks this structural amnesia:

```
experience (causal ledger) → patterns (path mining) → skills (compilation) → reflexes (zero-cost execution)
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/oneirozzzz7/educe.git
cd educe

# Install
pip install -e ".[web]"

# Configure (any OpenAI-compatible API works)
export EDUCE_API_KEY=your-api-key
export EDUCE_BASE_URL=https://api.deepseek.com/v1
export EDUCE_MODEL=deepseek-chat

# Launch
./start.sh
# Opens http://localhost:3001 (UI) and http://localhost:7860 (API)
```

## Reproduce the Descent Curve

The core claim is falsifiable. Run this to verify:

```bash
pip install matplotlib scipy
EDUCE_BASE_URL=... EDUCE_API_KEY=... EDUCE_MODEL=... python reproduce_descent.py
```

Output: `.educe/descent/descent_curve.png` + `statistics.json`

Success criteria:
- **Monotonicity**: Spearman rho < -0.5 (cost negatively correlates with experience)
- **Convergence**: last-3 / first-3 token ratio < 0.5
- **Fidelity**: correctness stays >= 0.7 throughout

## How It Works

### Architecture

```
User message → action_loop_v3
  → ConversationTruth (single source of truth)
  → Plan (model-maintained, pinned slot)
  → Situation (framework-computed objective facts)
  → Challenge (forces model to respond to anomalies)
  → Action execution
  → Feedback → next round (or model self-stops via status: done)
```

### Design Principles

1. **Zero framework judgment** — The framework holds no opinion about "what's right." It holds facts about the user and ensures those facts are presented at irreversible decision points.
2. **Model decides everything** — Including when to stop, what's dangerous, and whether to ask the user.
3. **Mechanism, not cognition** — The only hardcoded logic: pause before irreversible actions. Everything else is data the model reads.

### The Fifth Axiom

> Mechanism and cognition must be separated. The framework is infrastructure; the model is intelligence. When the model improves, the system improves — without changing a line of framework code.

## Supported Models

Any OpenAI-compatible API:

| Model | Use Case |
|-------|----------|
| DeepSeek-V3/R1 | Cost-effective daily use |
| Qwen3 series | Strong multilingual |
| GPT-4o / GPT-4.1 | Reliable general purpose |
| Claude (via proxy) | Best tool use |
| Local (Ollama) | Privacy / offline |

## Project Status

- [x] Action Loop V3 (Plan/Challenge/self-termination)
- [x] ConversationTruth (single data source, tiered compression)
- [x] Irreversibility detection (the only hardcoded judgment)
- [x] Shell execution + file ops + streaming output
- [x] Benchmark runner (30 cases, automated judge scoring)
- [x] Evidence-based acceptance: 0.722 on Kimi-K2
- [x] Contract tests (6/6) + E2E tests (24 scenarios)
- [ ] **The Descent Curve** (experiment in progress)
- [ ] Frontend i18n (English UI)
- [ ] Desktop app (Electron)

## Known Limitations

- ConversationTruth WARM tier budget estimation is imprecise
- State recovery after user confirmation is incomplete
- Frontend UI is functional but unpolished
- The Descent Curve has not yet been independently replicated

We list these because honesty is a core value — both in the agent's behavior and in our communication.

## Documentation

- [Vision](docs/VISION.md) — The philosophical foundation (five axioms, evolution metaphor)
- [Architecture](docs/SESSION11_ARCHITECTURE.md) — Technical deep dive
- [Boundary Redesign](docs/BOUNDARY_REDESIGN.md) — Framework as asset container

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (coming soon).

## License

[Apache-2.0](LICENSE)

---

*[中文版 README](README.zh-CN.md)*
