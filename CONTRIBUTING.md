# Contributing to Educe

Thank you for your interest in contributing to Educe! This document provides guidelines and information for contributors.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/oneirozzzz7/educe.git
cd educe

# Install in development mode
pip install -e ".[all]"

# Frontend (optional)
cd web && npm install && cd ..

# Run tests
pytest tests/contract/ -v
```

## Project Structure

```
educe/
├── core/           # Core engine (action loop, orchestrator, etc.)
├── config/         # YAML configs (skills, shell taxonomy, etc.)
├── models/         # Model client (OpenAI-compatible)
├── web/            # FastAPI backend + WebSocket handlers
└── cli/            # CLI entry point

web/
├── src/app/        # Next.js app
├── src/components/ # React components
└── src/lib/        # Shared utilities, state, i18n

tests/
├── contract/       # Contract tests (FakeModel, fast, CI-safe)
└── smoke/          # Smoke tests (real LLM, needs API key)
```

## Code Standards

- Python: Ruff for linting, target Python 3.10+
- TypeScript: strict mode, no `any` where avoidable
- No hardcoded API keys or secrets in source files
- Environment variables for all configuration

## Testing

### Contract Tests (no API key needed)
```bash
pytest tests/contract/ -v
```

### Smoke Tests (requires LLM API)
```bash
EDUCE_BASE_URL=... EDUCE_API_KEY=... EDUCE_MODEL=... pytest tests/smoke/ -v
```

### Descent Curve Verification
```bash
pip install matplotlib scipy
EDUCE_BASE_URL=... EDUCE_API_KEY=... EDUCE_MODEL=... python reproduce_descent.py
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run contract tests (`pytest tests/contract/ -v`)
5. Open a PR with a clear description

## Design Principles

Before contributing, please understand these core principles:

1. **Zero framework judgment** — The framework holds no opinions. All intelligence comes from the model.
2. **Mechanism, not cognition** — Only hardcode physical mechanisms (irreversibility detection), never domain knowledge.
3. **Data over code** — Prefer declarative YAML configs over Python if-else logic.
4. **Experience should compound** — Every feature should contribute to the descent curve (cost decreasing with experience).

## Good First Issues

Look for issues labeled `good first issue` for beginner-friendly tasks.

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 License.
