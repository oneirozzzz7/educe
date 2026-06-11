# Educe Architecture

> Framework that draws out latent capabilities from language models.

## Overview

Educe is a full-stack AI framework (Python backend + Next.js frontend) that orchestrates LLM interactions to build software artifacts through a conversational interface. The core philosophy: **the model already has the knowledge — the framework creates conditions for it to emerge.**

```
┌─────────────────────────────────────────────────────┐
│                   Web Frontend                       │
│            Next.js 15 · WebSocket · React            │
└──────────────────────┬──────────────────────────────┘
                       │ WebSocket (JSON messages)
┌──────────────────────┴──────────────────────────────┐
│                   Web Server                         │
│            FastAPI · /ws/{session_id}                │
├─────────────────────────────────────────────────────┤
│                  Orchestrator                        │
│     Intent → Action → Execute → Respond             │
├──────────┬───────────┬──────────────────────────────┤
│  Builder │  Agents   │    Unified Knowledge Store    │
│  (Agentic│  (Tester, │    (Recall · Evolve · Store)  │
│   Loop)  │  Planner) │                              │
├──────────┴───────────┴──────────────────────────────┤
│              Model Router (multi-provider)           │
│         Claude · DeepSeek · Qwen · Kimi · ...       │
└─────────────────────────────────────────────────────┘
```

## Core Components

### Orchestrator (`core/orchestrator.py` ~1800 LOC)

The brain. Receives user input, decides what to do, executes actions, manages state.

**Key flow:**
1. User sends message → Orchestrator receives via WebSocket
2. Model analyzes intent → outputs action tags (`[BUILD]`, `[MEMORIZE]`, `[RECALL]`, etc.)
3. Actions that need confirmation → `action_confirm_request` sent to frontend
4. User confirms → Orchestrator executes actions
5. For BUILD → delegates to Builder agent → AgenticLoop
6. Results written to SessionState + pushed to frontend

**Design principle:** The model decides behavior, not hardcoded if-else. The orchestrator provides capabilities (tools, knowledge, context) and lets the model choose.

### AgenticLoop (`core/agentic_loop.py` ~480 LOC)

Self-correcting code generation loop. The Builder agent delegates here.

```
Turn 1: Model writes code → Framework saves file → Runs validation
Turn 2: If validation fails → Error fed back → Model fixes
Turn 3: ...repeat until pass or max_turns
```

**Tools available to model:**
- `write_file` — write code to output directory
- `run` — execute commands (python3, node, etc.) for validation
- `think` — internal reasoning (not shown to user)

**Events emitted:** `step_code_content`, `write_file_result`, `run_result`, `done`

### SessionState (`core/session_state.py` ~150 LOC)

Single source of truth for a conversation. Persisted as JSON in `.deepforge/state/`.

```python
@dataclass
class SessionState:
    session_id: str
    phase: str           # idle | building | complete
    events: list[dict]   # unified event stream (all interactions)
    code_files: list[str]
    output_dir: str
    current_version: int
    versions: list[dict]
```

**Event types:** `user_input`, `ai_reply`, `action_confirm`, `user_confirm`, `build_start`, `build_complete`, `transcript`, `error`

### Unified Knowledge Store (`core/unified_store.py` ~490 LOC)

Continuous-spectrum knowledge system. Knowledge evolves from observations → experiences → patterns → templates.

**Recall mechanism:**
1. Get all candidate entries (sorted by maturity × success_rate)
2. Ask model: "which entries are relevant to this task?"
3. Inject selected entries into builder prompt

**Evolution:** `observation → experience → pattern → template` (based on usage count and success rate)

### Builder Agent (`agents/builder.py` ~540 LOC)

Manages the build lifecycle:
1. Assess complexity (simple/complex)
2. Choose strategy (single-pass vs agentic loop)
3. Inject activation seed + domain knowledge
4. Call model → parse output → AgenticLoop execution
5. Version artifacts

### Web Server (`web/server.py` ~985 LOC)

FastAPI + WebSocket server.

**Key endpoints:**
- `WS /ws/{session_id}` — bidirectional message stream
- `GET /api/tasks` — list all sessions
- `GET /api/knowledge` — list knowledge entries
- `DELETE /api/knowledge/{id}` — delete entry
- `POST /api/run/{session_id}` — execute output file
- `GET /api/download/{session_id}` — zip download
- `GET /api/versions/{session_id}` — list versions
- `/preview/` — static file serving for artifacts

## WebSocket Protocol

### Server → Client

| type | description |
|------|-------------|
| `status` | Phase changes: `thinking`, `pipeline_start`, `idle` |
| `chunk` | Streaming text (AI reply or code) |
| `action_confirm_request` | Ask user to confirm actions |
| `tool_event` | Build progress events (transcript, step_code_content, write_file_result, run_result, version_saved) |
| `state_sync` | Full state snapshot (on connect) |
| `agent_message` | Final agent output |
| `build_progress` | Build step updates |
| `error` | Error messages |

### Client → Server

| type | description |
|------|-------------|
| `{message, file_ids}` | User chat message |
| `action_confirm_response` | `{decision: "confirm"|"cancel", note?}` |
| `decision_response` | Plan/approach selection |

## Frontend Architecture

```
web/src/
├── app/page.tsx          # Main page (state machine + event rendering)
├── lib/
│   ├── state.ts          # useReducer state + actions
│   ├── ws.ts             # WebSocket client
│   └── ws-handler.ts     # WS message → Action mapping
└── components/
    ├── settings-modal.tsx
    ├── sidebar.tsx
    └── logo.tsx
```

**State machine phases:** `idle → thinking → building → complete`

**Key patterns:**
- All UI driven by `events[]` array (append-only, rendered sequentially)
- Build artifacts shown as clickable ArtifactCards
- Right panel slides in on card click (iframe for HTML, code+run for scripts)
- BuildProcessLine aggregates transcript events into compact chip flow

## Data Storage

```
.deepforge/
├── state/          # SessionState JSON files (per session)
├── output/         # Build artifacts (per session subdirectory)
│   └── {session_id[:16]}/
│       ├── index.html
│       └── versions/
├── knowledge/      # Unified knowledge store
│   ├── catalog.json
│   ├── entries/
│   └── compiled/
└── uploads/        # Temporary file uploads
```

## Key Design Decisions

1. **Model-driven behavior** — No hardcoded classifiers. The model reads context and outputs action tags. Framework executes them.
2. **Unified event stream** — All interactions are events. Frontend renders them in order. No separate "messages" vs "actions" vs "status".
3. **Activation over injection** — Framework provides minimal prompts that trigger the model's existing knowledge, rather than injecting large templates.
4. **Version everything** — Each build produces a versioned artifact. Users can iterate without losing previous versions.
5. **Confirm before execute** — Destructive/expensive actions require user confirmation. The model proposes, the user decides.
