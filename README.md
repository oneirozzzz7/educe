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

## The Descent Curve

The core claim is falsifiable. Run this to verify:

```bash
pip install matplotlib scipy
EDUCE_BASE_URL=... EDUCE_API_KEY=... EDUCE_MODEL=... python reproduce_descent.py
```

Output: `.educe/descent/descent_curve.png` + `statistics.json`

### What We Found

The episode-injection mechanism produces a **75% cost reduction** when the agent adopts retrieved experience — but adoption is unreliable (26% of runs in our 15-run experiment).

This shows up as a **bimodal distribution**, not a smooth descent curve:

| Condition | Tokens (median) | LLM Calls | Runs |
|-----------|----------------|-----------|------|
| Episode adopted | 2,458 | 2 | 4/15 |
| Episode ignored | 9,725 | 7 | 11/15 |

The aggregate correlation (Spearman ρ = -0.16) is statistically insignificant — because adoption is unreliable, not because the mechanism is weak. When the model *does* follow prior experience, cost drops by 75% with identical correctness (15/15 correct in both modes).

**The bottleneck is adoption reliability, not the underlying gain.** This is our #1 open research problem.

### Interpretation

- The descent *mechanism* works: verified episodes encode optimal action sequences that save 75% of tokens
- The descent *reliability* doesn't: the model treats the episode hint as optional context, not a directive
- Control groups (fin_mortgage, env_python_info) stay flat as expected — confirming the metric has no false positives

Raw data is in `.educe/descent/*/summary.json` after running.

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
- [x] **The Descent Curve** — mechanism verified (75% gain), adoption reliability is open problem
- [x] Frontend i18n (English/Chinese toggle)
- [ ] Episode adoption reliability improvement
- [ ] Desktop app (Electron)

## Known Limitations

1. **Episode adoption rate is 26%** — the model treats retrieved experience as optional. When adopted, cost drops 75%; when ignored, no benefit. This is the primary open research problem. Hypotheses: (a) hint positioning in context, (b) lack of structural enforcement, (c) no confidence metadata on episodes.
2. ConversationTruth WARM tier budget estimation is imprecise
3. State recovery after user confirmation is incomplete
4. Frontend UI is functional but unpolished
5. The Descent Curve has not yet been independently replicated

We list these because honesty is a core value — both in the agent's behavior and in our communication.

## Documentation

- [Vision](docs/VISION.md) — The philosophical foundation (five axioms, evolution metaphor)
- [Architecture](docs/SESSION11_ARCHITECTURE.md) — Technical deep dive
- [Descent Analysis](docs/descent_analysis.md) — Episode adoption trace analysis and open problems
- [Boundary Redesign](docs/BOUNDARY_REDESIGN.md) — Framework as asset container

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)

---

*[中文版 README](README.zh-CN.md)*
