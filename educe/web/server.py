from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from educe.core.config import EduceConfig
from educe.core.orchestrator import Orchestrator
from educe.core.message import Message
from educe.models.router import ModelClient
from educe.agents import ALL_AGENTS
from educe.memory.store import MemoryStore
from educe.skills.registry import SkillRegistry

log = logging.getLogger("educe.web.server")

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Request
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    HAS_WEB_DEPS = True
except ImportError:
    HAS_WEB_DEPS = False


def create_app(config: EduceConfig | None = None) -> Any:
    if not HAS_WEB_DEPS:
        raise ImportError(
            "Web dependencies not installed. Run: pip install educe[web]\n"
            "Or: pip install fastapi uvicorn websockets"
        )

    config = config or EduceConfig.load()
    app = FastAPI(title="Educe", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).parent / "static"
    templates_dir = Path(__file__).parent / "templates"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Preview output — each session writes to .educe/output/{session_id}/
    preview_root = Path(".educe/output")
    preview_root.mkdir(parents=True, exist_ok=True)
    app.mount("/preview", StaticFiles(directory=str(preview_root), html=True), name="preview")

    sessions: dict[str, Orchestrator] = {}
    session_files: dict[str, dict[str, Any]] = {}  # session_id -> {file_id: FileAttachment}
    session_locks: dict[str, asyncio.Lock] = {}     # per-session serialization
    session_tasks: dict[str, asyncio.Task] = {}     # current running task per session

    # 全局SelfEvolver（跨session共享）
    shared_self_evolver = None
    try:
        from educe.core.self_evolver import SelfEvolver
        from educe.core.activation_engine import DEFAULT_ACTIVATION_SEED
        model_cfg = config.default_model
        shared_client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
        shared_self_evolver = SelfEvolver(shared_client, model_cfg.model, DEFAULT_ACTIVATION_SEED)
    except Exception as e:
        logging.getLogger("educe.server").warning("SelfEvolver init skipped: %s", e)

    def get_orchestrator(session_id: str) -> Orchestrator:
        if session_id not in sessions:
            model_cfg = config.default_model
            client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
            orchestrator = Orchestrator(config)
            orchestrator.self_evolver = shared_self_evolver
            memory_store = MemoryStore(config.memory.storage_dir)
            skill_registry = SkillRegistry(config.skills.skill_dir, config.skills.community_dir)

            for agent_cls in ALL_AGENTS:
                agent = agent_cls(config=config, model_client=client, knowledge=orchestrator.knowledge)
                if hasattr(agent, 'memory_store'):
                    agent.memory_store = memory_store
                if hasattr(agent, 'skill_registry'):
                    agent.skill_registry = skill_registry
                orchestrator.register(agent)

            # Initialize structured session logger
            from educe.core.logging import SessionLogger
            session_logger = SessionLogger(
                session_id=session_id,
                model=model_cfg.model,
                config={"base_url": model_cfg.base_url, "max_tokens": model_cfg.max_tokens},
            )
            orchestrator.session_logger = session_logger

            # Load or create SessionState — single source of truth
            from educe.core.session_state import SessionState
            state = SessionState.load_or_create(session_id)
            orchestrator.state = state
            # Bridge: sync state → context.artifacts for agent compatibility
            if state.code_files:
                orchestrator.context.artifacts["code_files"] = state.code_files
                orchestrator.context.artifacts["engineer_output"] = "agentic build"
                orchestrator.context.artifacts["output_dir"] = state.output_dir
            # Restore conversation history from events
            if state.events:
                from educe.core.conversation import Turn
                for evt in state.events:
                    if evt.get("type") == "user_input":
                        orchestrator.conversation.turns.append(
                            Turn(role="user", content=evt["content"][:2000],
                                 timestamp=evt.get("ts", 0)))
                    elif evt.get("type") == "ai_reply":
                        orchestrator.conversation.turns.append(
                            Turn(role="assistant", content=evt["content"][:2000],
                                 timestamp=evt.get("ts", 0)))

            sessions[session_id] = orchestrator
        return sessions[session_id]

    @app.get("/")
    async def index():
        html_path = templates_dir / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
        return HTMLResponse("<h1>DeepForge Web UI</h1><p>Template not found</p>")

    @app.get("/api/status")
    async def status():
        return {
            "status": "ready",
            "model": config.default_model.model,
            "base_url": config.default_model.base_url,
            "agents": list(config.agents.keys()),
            "has_api_key": bool(config.default_model.api_key),
            "evolution": config.evolution.enabled,
        }

    @app.get("/api/health")
    async def health():
        module_health = {}
        for sid, orch in sessions.items():
            if hasattr(orch, '_module_health'):
                module_health[sid] = orch._module_health
                break
        return {
            "status": "ok" if not any(
                v.startswith("disabled") for h in module_health.values() for v in h.values()
            ) else "degraded",
            "sessions_active": len(sessions),
            "modules": module_health,
        }

    @app.get("/api/tools")
    async def list_tools():
        from educe.core.tool_registry import ToolRegistry
        registry = ToolRegistry()
        registry.load_from_config(Path(".educe/tools.json"))
        return {"tools": [{"name": t.name, "description": t.description, "type": t.type} for t in registry.list_all()]}

    @app.post("/api/tools")
    async def register_tool(request: Request):
        data = await request.json()
        tools_path = Path(".educe/tools.json")
        existing = []
        if tools_path.exists():
            try:
                existing = json.loads(tools_path.read_text())
                if isinstance(existing, dict):
                    existing = existing.get("tools", [])
            except Exception:
                existing = []
        existing.append(data)
        tools_path.parent.mkdir(parents=True, exist_ok=True)
        tools_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
        return {"status": "ok", "total": len(existing)}

    @app.get("/api/knowledge")
    async def get_knowledge():
        from educe.core.unified_store import UnifiedKnowledgeStore
        try:
            store = UnifiedKnowledgeStore(Path(".educe/unified"))
            return {"entries": store._catalog}
        except Exception:
            return {"entries": []}

    @app.delete("/api/knowledge/{entry_id}")
    async def delete_knowledge(entry_id: str):
        from educe.core.unified_store import UnifiedKnowledgeStore
        try:
            store = UnifiedKnowledgeStore(Path(".educe/unified"))
            path = store.entries_dir / f"{entry_id}.json"
            if path.exists():
                path.unlink()
            store._catalog = [e for e in store._catalog if e["id"] != entry_id]
            store._save_catalog()
            store._invalidate_compiled()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/api/stats")
    async def stats():
        from educe.core.observer import Observer
        obs = Observer()
        return obs.get_stats()

    @app.get("/api/evolution")
    async def evolution_stats():
        """进化引擎运行状态——读最新的evo2日志"""
        import glob
        evo_dir = Path(".educe/evolution")
        if not evo_dir.exists():
            return {"status": "not_started", "rounds": 0}
        logs = sorted(evo_dir.glob("evo2_*.jsonl"), reverse=True)
        if not logs:
            return {"status": "not_started", "rounds": 0}
        entries = []
        with open(logs[0]) as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except Exception as e:
                    log.debug("suppressed: %s", e)
        passes = sum(1 for e in entries if e.get("event") == "detect_pass")
        fails = sum(1 for e in entries if e.get("event") in ("detect_fail", "detect_timeout", "detect_error"))
        deposits = sum(1 for e in entries if e.get("event") == "deposited")
        return {
            "status": "running" if entries else "idle",
            "log_file": str(logs[0]),
            "total_events": len(entries),
            "passes": passes,
            "fails": fails,
            "pass_rate": round(passes / max(passes + fails, 1) * 100, 1),
            "deposits": deposits,
            "recent": entries[-5:] if entries else [],
        }

    @app.get("/api/tasks")
    async def list_tasks(limit: int = 20, offset: int = 0):
        # Merge both sources: new SessionState + old SessionStore
        from educe.core.session_state import SessionState
        from educe.core.session_store import SessionStore
        state_sessions = SessionState.list_all(limit=100, offset=0)
        store = SessionStore()
        old_sessions, _ = store.list_sessions(limit=100, offset=0)
        # Merge: state takes priority for same id prefix, then append old
        seen_ids = {s["id"][:16] for s in state_sessions}
        merged = list(state_sessions)
        for s in old_sessions:
            if s["id"][:16] not in seen_ids:
                merged.append(s)
                seen_ids.add(s["id"][:16])
        # Sort by updated_at desc
        merged.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        total = len(merged)
        return {"tasks": merged[offset:offset + limit], "total": total, "offset": offset, "limit": limit}

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        from educe.core.session_state import SessionState
        state = SessionState.load(task_id)
        if state:
            return {
                "session_id": state.session_id,
                "events": state.events,
                "versions": state.versions,
                "current_version": state.current_version,
                "phase": state.phase,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
            }
        # Fallback to old stores
        from educe.core.session_store import SessionStore
        store = SessionStore()
        turns = store.get_session(task_id)
        if turns:
            for turn in turns:
                if turn.get("type") == "code":
                    try:
                        work_dir = Path(".educe/output") / task_id[:16]
                        if work_dir.exists():
                            html_files = sorted(work_dir.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
                            main_html = next((f for f in html_files if f.name != "index.html"), None) or (html_files[0] if html_files else None)
                            if main_html:
                                content = main_html.read_text(encoding="utf-8", errors="ignore")
                                turn["response"] = "```filepath:{}\n{}\n```".format(main_html.name, content)
                    except Exception as e:
                        log.debug("suppressed: %s", e)
            return {"session_id": task_id, "turns": turns}
        from educe.core.task_store import TaskStore
        old_store = TaskStore()
        data = old_store.load_task(task_id)
        if data:
            return data
        return {"error": "not found"}

    @app.get("/api/providers")
    async def providers():
        from educe.models.router import PROVIDER_PRESETS
        return {"providers": PROVIDER_PRESETS}

    @app.get("/api/models")
    async def list_models():
        """返回当前平台可用的模型列表"""
        known_models = []
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=config.default_model.api_key,
                base_url=config.default_model.base_url,
            )
            resp = await client.models.list()
            known_models = sorted(set(m.id for m in resp.data))
        except Exception as e:
            log.debug("suppressed: %s", e)

        if len(known_models) <= 1:
            known_models = [
                config.default_model.model,
                "Kimi-K2-0905-jcloud",
                "DeepSeek-V3-0324-cloud-provider-iaas",
                "DeepSeek-R1-cloud-provider-iaas",
                "DeepSeek-V4-Flash",
                "GLM-5.1",
                "Chatrhino-750B",
                "gpt-4o-0806",
                "gpt-4.1",
                "qwen-plus",
                "deepseek-chat",
                "moonshot-v1-8k",
                "glm-4-flash",
            ]
            known_models = sorted(set(known_models))

        return {"models": known_models}

    @app.post("/api/settings")
    async def update_settings(body: dict):
        import os
        from pathlib import Path

        model = body.get("model", "")
        api_key = body.get("api_key", "")
        base_url = body.get("base_url", "")
        evolution = body.get("evolution")

        if model:
            config.default_model.model = model
            os.environ["EDUCE_MODEL"] = model
        if base_url:
            config.default_model.base_url = base_url
            os.environ["EDUCE_BASE_URL"] = base_url
        if api_key:
            config.default_model.api_key = api_key
            os.environ["EDUCE_API_KEY"] = api_key
        elif not config.default_model.api_key:
            for env_key in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "GLM_API_KEY"]:
                val = os.environ.get(env_key)
                if val:
                    config.default_model.api_key = val
                    break

        if evolution is not None:
            config.evolution.enabled = bool(evolution)
            os.environ["EDUCE_EVOLUTION"] = str(evolution).lower()

        env_path = Path.cwd() / ".env"
        lines = []
        if env_path.exists():
            lines = [l for l in env_path.read_text().strip().split("\n")
                     if l and not l.startswith("EDUCE_")]
        if config.default_model.api_key:
            lines.append(f"EDUCE_API_KEY={config.default_model.api_key}")
        if base_url:
            lines.append(f"EDUCE_BASE_URL={base_url}")
        if model:
            lines.append(f"EDUCE_MODEL={model}")
        lines.append(f"EDUCE_EVOLUTION={str(config.evolution.enabled).lower()}")
        env_path.write_text("\n".join(lines) + "\n")

        sessions.clear()

        return {"status": "ok", "model": config.default_model.model, "evolution": config.evolution.enabled}

    @app.post("/api/upload/{session_id}")
    async def upload_file(session_id: str, file: UploadFile = File(...)):
        from educe.core.file_handler import process_file, FileAttachment, MAX_FILE_SIZE, SUPPORTED_EXTENSIONS
        import tempfile, shutil

        if not file.filename:
            return {"error": "没有文件名"}

        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return {"error": f"不支持的文件类型: {ext}", "supported": list(SUPPORTED_EXTENSIONS)}

        upload_dir = Path(".educe/uploads") / session_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        dest = upload_dir / file.filename
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return {"error": f"文件过大({len(content) // 1024 // 1024}MB > 10MB)"}

        dest.write_bytes(content)

        attachment = process_file(dest)

        if session_id not in session_files:
            session_files[session_id] = {}
        session_files[session_id][attachment.id] = attachment

        return {"status": "ok", "file": attachment.to_dict()}

    @app.delete("/api/upload/{session_id}/{file_id}")
    async def delete_file(session_id: str, file_id: str):
        files = session_files.get(session_id, {})
        if file_id in files:
            del files[file_id]
            return {"status": "ok"}
        return {"error": "not found"}

    @app.get("/api/upload/{session_id}")
    async def list_files(session_id: str):
        files = session_files.get(session_id, {})
        return {"files": [f.to_dict() for f in files.values()]}

    @app.get("/api/domains")
    async def list_domains():
        from educe.core.domain_engine import DomainEngine
        engine = DomainEngine()
        return {"domains": engine.list_domains()}

    @app.post("/api/domains/digest/{session_id}/{file_id}")
    async def digest_domain(session_id: str, file_id: str):
        """把已上传的文件消化为领域知识——傻瓜式，任何文件都行"""
        files = session_files.get(session_id, {})
        attachment = files.get(file_id)
        if not attachment:
            return {"error": "文件未找到"}
        if not attachment.text_content:
            return {"error": "该文件无法提取文本内容"}

        from educe.core.domain_engine import DomainEngine
        model_cfg = config.default_model
        from educe.models.router import ModelClient
        client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
        engine = DomainEngine()

        try:
            dk = await engine.digest(
                attachment.text_content, attachment.name,
                client, model_cfg.model, model_cfg.max_tokens
            )
            return {
                "status": "ok",
                "domain": dk.domain,
                "concepts": len(dk.concepts),
                "chains": len(dk.chains),
                "pitfalls": len(dk.pitfalls),
            }
        except Exception as e:
            return {"error": str(e)[:200]}

    @app.get("/api/download/{session_id}")
    async def download_zip(session_id: str):
        """Download all output files for a session as a zip archive."""
        import zipfile
        import io
        from fastapi.responses import StreamingResponse

        output_dir = Path(".educe/output") / session_id[:16]
        if not output_dir.exists():
            return {"error": "Session output not found"}

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(output_dir))
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=educe-{session_id[:8]}.zip"},
        )

    @app.post("/api/run/{session_id}")
    async def run_file(session_id: str):
        """Execute the main output file for a session and return stdout/stderr."""
        import subprocess

        output_dir = Path(".educe/output") / session_id[:16]
        if not output_dir.exists():
            return {"success": False, "output": "Session output not found"}

        # Find the main executable file
        candidates = list(output_dir.glob("*.py")) + list(output_dir.glob("*.js")) + list(output_dir.glob("*.sh"))
        if not candidates:
            return {"success": False, "output": "No executable file found"}

        target = candidates[0]
        ext = target.suffix

        if ext == ".py":
            cmd = ["python3", target.name]
        elif ext == ".js":
            cmd = ["node", target.name]
        elif ext == ".sh":
            cmd = ["bash", target.name]
        else:
            return {"success": False, "output": f"Unsupported file type: {ext}"}

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15, cwd=str(output_dir)
            )
            output = result.stdout + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
            return {
                "success": result.returncode == 0,
                "output": output[:5000],
                "file": target.name,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "执行超时 (15s)"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    @app.get("/api/versions/{session_id}")
    async def list_versions(session_id: str):
        versions_dir = Path(".educe/output") / session_id[:16] / "versions"
        if not versions_dir.exists():
            return {"versions": []}
        version_files: dict[int, list[str]] = {}
        for f in sorted(versions_dir.iterdir()):
            if f.is_file() and f.name.startswith("v"):
                parts = f.name.split("_", 1)
                if len(parts) == 2:
                    try:
                        vnum = int(parts[0][1:])
                        fname = parts[1]
                        version_files.setdefault(vnum, []).append(fname)
                    except ValueError:
                        pass
        versions = [{"version": v, "files": fs} for v, fs in sorted(version_files.items())]
        return {"versions": versions}

    @app.get("/api/versions/{session_id}/{version}")
    async def get_version(session_id: str, version: int):
        versions_dir = Path(".educe/output") / session_id[:16] / "versions"
        files = {}
        for f in sorted(versions_dir.iterdir()):
            if f.is_file() and f.name.startswith("v{}_".format(version)):
                fname = f.name.split("_", 1)[1]
                files[fname] = f.read_text(encoding="utf-8", errors="ignore")
        if not files:
            return {"error": "version not found"}
        return {"version": version, "files": files}

    @app.get("/api/convergence/{session_id}")
    async def get_convergence(session_id: str):
        from educe.core.iteration_state import StateLog, IterationState
        log_path = Path(f".educe/convergence/{session_id[:16]}.jsonl")
        if not log_path.exists():
            return {"curve": [], "claims": [], "convergence": 0, "has_edits": False}
        log = StateLog(log_path)
        log.load()
        latest = log.latest()
        if not latest:
            return {"curve": [], "claims": [], "convergence": 0, "has_edits": False}
        claims = []
        has_edits = False
        for cid, c in latest.claims.items():
            claims.append({"id": cid, "text": c.text[:80], "status": c.status.value})
            if "修改" in c.text or "file created" in c.text or "edit" in c.text.lower():
                has_edits = True
        return {
            "curve": log.convergence_curve(),
            "claims": claims,
            "convergence": latest.convergence_metric(),
            "revisions": len(log.convergence_curve()),
            "has_edits": has_edits,
        }

    # ═══════════════════════════════════════
    #  日志系统 API（前端透明可查）
    # ═══════════════════════════════════════

    @app.get("/api/logs/sessions")
    async def list_log_sessions(limit: int = 20, offset: int = 0):
        index_path = Path(".educe/logs/index.jsonl")
        if not index_path.exists():
            return {"sessions": [], "total": 0}
        lines = index_path.read_text(encoding="utf-8").strip().split("\n")
        lines = [l for l in lines if l.strip()]
        lines.reverse()
        total = len(lines)
        page = lines[offset:offset + limit]
        sessions = []
        for line in page:
            try:
                sessions.append(json.loads(line))
            except Exception:
                pass
        return {"sessions": sessions, "total": total}

    @app.get("/api/logs/sessions/{session_id}/events")
    async def get_session_events(session_id: str, limit: int = 100, offset: int = 0, type_filter: str = ""):
        import glob
        pattern = f".educe/logs/sessions/*/{session_id[:16]}/events.jsonl"
        matches = glob.glob(pattern)
        if not matches:
            return {"events": [], "total": 0}
        events_path = Path(matches[0])
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        lines = [l for l in lines if l.strip()]
        events = []
        for line in lines:
            try:
                evt = json.loads(line)
                if type_filter and evt.get("type") not in type_filter.split(","):
                    continue
                events.append(evt)
            except Exception:
                pass
        total = len(events)
        page = events[offset:offset + limit]
        return {"events": page, "total": total}

    @app.get("/api/logs/trace/{trace_id}")
    async def get_trace(trace_id: str):
        import glob
        patterns = glob.glob(".educe/logs/sessions/*/*/trace.jsonl")
        for trace_path in patterns:
            try:
                for line in Path(trace_path).read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("trace_id") == trace_id:
                        return entry
            except Exception:
                continue
        return {"error": "trace not found"}

    @app.post("/api/feedback")
    async def submit_feedback(request: Request):
        import json as _json
        body = await request.json()
        feedback_dir = Path(".educe/feedback")
        feedback_dir.mkdir(parents=True, exist_ok=True)
        feedback_file = feedback_dir / "feedback.jsonl"
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(body, ensure_ascii=False) + "\n")
        return {"status": "ok"}

    @app.get("/api/evolution/status")
    async def evolution_status():
        """返回所有器官的当前状态（从活跃 orchestrator 读取实时内存状态）"""
        for orch in sessions.values():
            if hasattr(orch, 'organ_registry') and orch.organ_registry:
                return {"organs": orch.organ_registry.list_status()}

        from educe.core.organ_verbosity import ConfidenceStore
        store = ConfidenceStore()
        organs = []
        for pid, ps in store._states.items():
            organs.append({
                "id": pid,
                "family": pid.split(":")[0] if ":" in pid else pid,
                "state": ps.state,
                "confidence": round(ps.confidence, 3),
                "observe_count": ps.observe_count,
                "confirm_count": ps.confirm_count,
                "hint": None,
                "last_updated": ps.last_updated,
            })
        return {"organs": organs}

    @app.post("/api/evolution/revert/{organ_id}")
    async def evolution_revert(organ_id: str):
        """手动撤销一个器官"""
        for orch in sessions.values():
            if hasattr(orch, 'organ_registry') and orch.organ_registry:
                organ = orch.organ_registry.get(organ_id)
                if organ:
                    await organ.revert()
                    return {"status": "ok", "organ_id": organ_id, "new_state": "idle"}

        return {"status": "error", "message": f"Organ '{organ_id}' not found"}

    # ═══ Memory conflict resolution ═══

    @app.get("/api/memory/conflicts")
    async def memory_conflicts():
        """列出所有待仲裁的记忆冲突"""
        from educe.core.project_memory import ProjectMemoryStore
        store = ProjectMemoryStore()
        disputed = store.get_disputed()
        return {"conflicts": [e.to_dict() for e in disputed]}

    @app.post("/api/memory/resolve")
    async def memory_resolve(request: Request):
        """仲裁记忆冲突：保留 winner，归档 losers"""
        data = await request.json()
        winner_id = data.get("winner_id", "")
        loser_ids = data.get("loser_ids", [])
        if not winner_id:
            return {"status": "error", "message": "winner_id required"}
        from educe.core.project_memory import ProjectMemoryStore
        store = ProjectMemoryStore()
        store.resolve_conflict(winner_id, loser_ids)
        return {"status": "ok", "winner": winner_id, "archived": loser_ids}

    @app.get("/api/memory")
    async def memory_list():
        """列出所有活跃记忆"""
        from educe.core.project_memory import ProjectMemoryStore
        store = ProjectMemoryStore()
        active = store.get_active()
        return {"memories": [e.to_dict() for e in active], "total": len(store.get_all())}

    @app.get("/api/credentials")
    async def list_credentials():
        """列出凭据（不含 value）"""
        from educe.core.credential_store import CredentialStore
        store = CredentialStore()
        return {"credentials": store.get_public_list()}

    @app.post("/api/credentials")
    async def add_credential(request: Request):
        """添加/更新凭据"""
        data = await request.json()
        name = data.get("name", "").strip()
        value = data.get("value", "")
        note = data.get("note", "")
        if not name or not value:
            return {"status": "error", "message": "name and value required"}
        from educe.core.credential_store import CredentialStore
        store = CredentialStore()
        store.add(name, value, note)
        return {"status": "ok", "name": name}

    @app.delete("/api/credentials/{name}")
    async def delete_credential(name: str):
        """删除凭据"""
        from educe.core.credential_store import CredentialStore
        store = CredentialStore()
        if store.remove(name):
            return {"status": "ok"}
        return {"status": "error", "message": "not found"}

    @app.get("/api/files")
    async def list_project_files(q: str = "", limit: int = 20):
        """列出项目文件（供 @ 选择器模糊搜索，常读文件置顶）"""
        import os
        import educe
        project_path = Path(educe.__file__).parent.parent

        # 常读文件置顶
        frequent = []
        try:
            from educe.core.reference_memory import get_frequent_file_paths
            frequent = get_frequent_file_paths()
        except Exception as e:
            log.debug("suppressed: %s", e)

        results = []
        exclude = {".git", "node_modules", "__pycache__", ".educe", ".next", "venv", "env", ".playwright-mcp"}
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in exclude]
            for f in files:
                if f.startswith(".") and f != ".env":
                    continue
                rel = os.path.relpath(os.path.join(root, f), project_path)
                if q and q.lower() not in rel.lower():
                    continue
                results.append(rel)
                if len(results) >= limit * 2:
                    break
            if len(results) >= limit * 2:
                break

        # 常读文件置顶
        if frequent:
            freq_set = set(frequent)
            top = [f for f in results if f in freq_set]
            rest = [f for f in results if f not in freq_set]
            results = top + rest

        return {"files": results[:limit], "frequent": frequent}

    @app.get("/api/ls")
    async def list_directory(path: str = "/"):
        """列出指定目录的文件和文件夹（供 @ 绝对路径补全）"""
        import os
        target = Path(path)
        if not target.exists():
            return {"exists": False, "entries": [], "error": "path not found"}
        if not target.is_dir():
            return {"exists": True, "is_file": True, "entries": [], "path": str(target)}
        try:
            entries = []
            for entry in sorted(target.iterdir()):
                name = entry.name
                if name.startswith(".") and name not in (".env",):
                    continue
                entries.append({
                    "name": name,
                    "is_dir": entry.is_dir(),
                    "path": str(entry),
                })
            return {"exists": True, "entries": entries[:50]}
        except PermissionError:
            return {"exists": True, "entries": [], "error": "permission denied"}

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        await websocket.accept()

        orchestrator = get_orchestrator(session_id)

        # Push initial state to frontend on connect (supports refresh recovery)
        if hasattr(orchestrator, 'state') and orchestrator.state.events:
            try:
                await websocket.send_json({"type": "state_sync", **orchestrator.state.to_snapshot()})
            except Exception as e:
                log.debug("suppressed: %s", e)

        ws_closed = {"value": False}

        async def send_message(msg: Message):
            if ws_closed["value"]:
                return
            try:
                await _send_message_inner(msg)
            except Exception:
                ws_closed["value"] = True

        async def _send_message_inner(msg: Message):
            if msg.content == "__PIPELINE_START__":
                await websocket.send_json({"type": "status", "content": "pipeline_start"})
                return
            if msg.content == "__PLAN_PROPOSAL__":
                await websocket.send_json({
                    "type": "plan_proposal",
                    "plans": msg.data.get("plans", []),
                    "original_request": msg.data.get("original_request", ""),
                })
                return
            if msg.content.startswith("__DECISION_REQUEST__"):
                import json as _json
                orchestrator.context.metadata["_pending_request"] = orchestrator.context.user_request
                try:
                    decisions = _json.loads(msg.content.replace("__DECISION_REQUEST__", ""))
                except Exception:
                    decisions = []
                await websocket.send_json({
                    "type": "decision_request",
                    "decisions": decisions,
                })
                return
            if msg.content.startswith("__BUILD_PROGRESS__"):
                step = msg.content.replace("__BUILD_PROGRESS__", "")
                await websocket.send_json({"type": "build_progress", "step": step})
                return
            if msg.content.startswith("__ACTION_CONFIRM__"):
                import json as _json
                try:
                    actions = _json.loads(msg.content.replace("__ACTION_CONFIRM__", ""))
                    await websocket.send_json({
                        "type": "action_confirm_request",
                        "actions": actions,
                    })
                except Exception as e:
                    log.debug("suppressed: %s", e)
                return
            if msg.content.startswith("__TOOL_EVENT__"):
                import json as _json
                try:
                    evt = _json.loads(msg.content.replace("__TOOL_EVENT__", ""))
                    if evt.get("type") in ("tool_start", "tool_chunk", "tool_end", "tool_cancel",
                                           "evolution_propose", "evolution_crystallize", "reflex_bubble",
                                           "error"):
                        await websocket.send_json(evt)
                    else:
                        evt["type"] = "tool_event"
                        await websocket.send_json(evt)
                except Exception as e:
                    log.debug("suppressed: %s", e)
                return
            summary = _extract_summary(msg.sender, msg.content, msg.type.value)
            await websocket.send_json({
                "type": "agent_message",
                "sender": msg.sender,
                "summary": summary,
                "content": msg.content,
                "msg_type": msg.type.value,
                "timestamp": msg.timestamp,
                "has_files": "```filepath:" in msg.content or "<!DOCTYPE" in msg.content,
            })

        orchestrator.on_message(lambda msg: asyncio.ensure_future(send_message(msg)))

        accumulated_chunks = {"text": ""}

        async def send_chunk(agent_name: str, chunk: str):
            try:
                await websocket.send_json({"type": "chunk", "sender": agent_name, "content": chunk})
                # 检测Builder的STEP标记
                accumulated_chunks["text"] += chunk
                import re
                step_match = re.search(r'<!-- STEP: (.+?) -->', accumulated_chunks["text"])
                if step_match:
                    step_desc = step_match.group(1)
                    await websocket.send_json({"type": "build_progress", "step": step_desc})
                    accumulated_chunks["text"] = accumulated_chunks["text"].split(step_match.group(0))[-1]
            except Exception as e:
                import logging
                logging.getLogger("educe.ws").warning("send_chunk failed: %s", str(e)[:80])

        orchestrator.on_chunk(lambda a, c: asyncio.ensure_future(send_chunk(a, c)))

        # 自动启用结构化日志推送（只推送 5 类有用事件）
        _PUSH_EVENT_TYPES = {"lifecycle", "llm_call", "tool_call", "memory"}
        if orchestrator.session_logger:
            async def _auto_debug_push(event_dict):
                if event_dict.get("type") not in _PUSH_EVENT_TYPES:
                    return
                try:
                    await websocket.send_json({"type": "debug_event", "event": event_dict})
                except Exception:
                    pass
            orchestrator.session_logger._debug_hook = _auto_debug_push

        # 零状态检测：新 session 自动推送项目环境摘要
        if not orchestrator.conversation.turns:
            try:
                import os as _os_zero
                cwd = _os_zero.getcwd()
                entries = sorted(_os_zero.listdir(cwd))
                visible = [e for e in entries if not e.startswith(".")][:20]
                hidden_count = len([e for e in entries if e.startswith(".")])
                has_git = ".git" in entries
                has_package = any(f in entries for f in ["package.json", "pyproject.toml", "Cargo.toml", "go.mod"])
                has_readme = any(f.lower().startswith("readme") for f in entries)

                suggestions = []
                if has_readme:
                    suggestions.append("读取 README 了解项目")
                if has_package:
                    suggestions.append("分析项目结构和依赖")
                suggestions.append("帮我写代码 / 做工具")

                await websocket.send_json({
                    "type": "zero_state",
                    "cwd": cwd,
                    "files": visible,
                    "file_count": len(entries),
                    "hidden_count": hidden_count,
                    "has_git": has_git,
                    "has_package": has_package,
                    "suggestions": suggestions,
                })
            except Exception as e:
                log.debug("zero_state detection failed: %s", e)

        try:
            while True:
                data = await websocket.receive_json()
                user_input = data.get("message", "")

                # 调试订阅：实时推送日志事件到前端
                if data.get("type") == "debug_subscribe":
                    _debug_level = data.get("level", "events")
                    async def _debug_hook(event_dict):
                        try:
                            await websocket.send_json({"type": "debug_event", "event": event_dict})
                        except Exception:
                            pass
                    if orchestrator.session_logger:
                        orchestrator.session_logger._debug_hook = _debug_hook
                    log.info("session %s: debug subscribed (level=%s)", session_id[:8], _debug_level)
                    continue

                if data.get("type") == "debug_unsubscribe":
                    if orchestrator.session_logger:
                        orchestrator.session_logger._debug_hook = None
                    continue

                # 处理用户反馈（thumbs up/down）
                if data.get("type") == "feedback":
                    signal = data.get("signal", "")
                    if orchestrator.credibility:
                        orchestrator.credibility.record_feedback(
                            session_id, data.get("message_id", ""), signal)
                    continue

                # 处理工具取消请求
                if data.get("type") == "tool_cancel":
                    tool_id = data.get("id", "")
                    if tool_id and hasattr(orchestrator, "streaming_registry"):
                        cancelled = await orchestrator.streaming_registry.cancel(tool_id)
                        if cancelled:
                            await websocket.send_json({
                                "type": "tool_end", "id": tool_id,
                                "result": {"exit_code": -1, "cancelled": True,
                                           "reason": data.get("reason", "user")},
                            })
                    continue

                # 处理校准回流（PROPOSE 卡片的用户响应）
                if data.get("type") == "calibrate":
                    action = data.get("action", "")
                    event_id = data.get("event_id", "")
                    if action and hasattr(orchestrator, "verbosity_organ") and orchestrator.verbosity_organ:
                        result_event = await orchestrator.verbosity_organ.handle_calibrate(action, event_id)
                        if result_event:
                            await websocket.send_json({
                                "type": "evolution_crystallize",
                                "event_id": result_event.event_id,
                                "organ": result_event.organ.to_dict(),
                                "phrase": result_event.phrase,
                                "confidence": result_event.confidence,
                            })
                    continue

                # Switch session — load a different session's state into the orchestrator
                if data.get("type") == "switch_session":
                    target_id = data.get("session_id", "")
                    if target_id:
                        from educe.core.session_state import SessionState
                        target_state = SessionState.load(target_id)
                        if target_state:
                            orchestrator.state = target_state
                            orchestrator.context.artifacts.clear()
                            orchestrator.context.metadata.clear()
                            orchestrator.conversation.turns.clear()
                            # Bridge state → artifacts
                            if target_state.code_files:
                                orchestrator.context.artifacts["code_files"] = target_state.code_files
                                orchestrator.context.artifacts["engineer_output"] = "agentic build"
                                orchestrator.context.artifacts["output_dir"] = target_state.output_dir
                            orchestrator.context.metadata["session_id"] = target_id
                            # Restore conversation from events
                            from educe.core.conversation import Turn
                            for evt in target_state.events:
                                if evt.get("type") == "user_input":
                                    orchestrator.conversation.turns.append(
                                        Turn(role="user", content=evt["content"][:2000],
                                             timestamp=evt.get("ts", 0)))
                                elif evt.get("type") == "ai_reply":
                                    orchestrator.conversation.turns.append(
                                        Turn(role="assistant", content=evt["content"][:2000],
                                             timestamp=evt.get("ts", 0)))
                    continue

                # Reset context — "新任务" button clears orchestrator state
                if data.get("type") == "reset_context":
                    import shutil
                    output_dir = Path(".educe/output") / session_id[:16]
                    if output_dir.exists():
                        shutil.rmtree(output_dir, ignore_errors=True)
                    orchestrator.context.artifacts.clear()
                    orchestrator.context.metadata.clear()
                    orchestrator.context.conversation_history.clear()
                    orchestrator.conversation.turns.clear()
                    # Reset SessionState
                    from educe.core.session_state import SessionState
                    orchestrator.state = SessionState(session_id=session_id)
                    orchestrator.state.save()
                    continue

                # 处理 action 确认/取消
                if data.get("type") == "action_confirm_response":
                    decision = data.get("decision", "confirm")
                    note = data.get("note", "")
                    pending = orchestrator.context.metadata.get("_pending_actions")
                    if pending:
                        # 用户动作写入 conversation（模型能看到）
                        confirm_text = f"[用户确认] {decision}"
                        if note:
                            confirm_text += f"，补充：{note}"
                        orchestrator.conversation.add_user(confirm_text)

                        if decision == "cancel":
                            orchestrator.context.metadata.pop("_pending_actions", None)
                            orchestrator.context.metadata.pop("_pending_user_input", None)
                            # 写入 conversation + events
                            orchestrator.conversation.add_assistant("好的，已取消。")
                            if hasattr(orchestrator, 'state'):
                                orchestrator.state.add_user_confirm("cancel")
                                orchestrator.state.add_ai_reply("好的，已取消。")
                            # 实时推送给前端
                            await websocket.send_json({"type": "tool_event", "event": "transcript", "phase": "action", "role": "system", "content": "已取消", "elapsed": 0})
                            await websocket.send_json({"type": "status", "content": "idle"})

                        elif decision == "confirm":
                            if hasattr(orchestrator, 'state'):
                                orchestrator.state.add_user_confirm("confirm", note)
                            await websocket.send_json({"type": "status", "content": "thinking"})

                            original = orchestrator.context.metadata.get("_pending_user_input", "")
                            if note:
                                # 有补充 → 合并需求重新走 action loop
                                original = f"{original}。补充：{note}"
                                orchestrator.context.metadata.pop("_pending_actions", None)
                                orchestrator.context.metadata.pop("_pending_user_input", None)
                                try:
                                    await orchestrator.run(original)
                                except Exception as e:
                                    await websocket.send_json({"type": "error", "content": str(e)})
                            else:
                                # 无补充 → 直接执行 pending actions
                                from educe.core.action_executor import ParsedAction
                                actions = orchestrator.context.metadata.pop("_pending_actions", [])
                                orchestrator.context.metadata.pop("_pending_user_input", None)
                                transcript = orchestrator.context.metadata.get("_transcript")
                                if not transcript:
                                    from educe.core.transcript import TaskTranscript
                                    transcript = TaskTranscript(original)
                                    orchestrator.context.metadata["_transcript"] = transcript

                                non_build = [p for p in actions if p["type"] != "build"]
                                build_acts = [p for p in actions if p["type"] == "build"]

                                for p in non_build:
                                    a = ParsedAction(type=p["type"], params=p["params"], name=p.get("name", ""))
                                    result = await orchestrator._execute_action(a, original, transcript)
                                    result_text = result.get("output", "")
                                    orchestrator.conversation.add_assistant(f"[系统] {result_text}")
                                    if hasattr(orchestrator, 'state'):
                                        orchestrator.state.add_action_executed(a.type, result_text, result.get("success", False))
                                    orchestrator._update_iteration_state(a, result, session_id)
                                    # 推送 action_detail 事件（与主循环一致）
                                    _action_summary = orchestrator._build_action_summary(a, result)
                                    if _action_summary:
                                        import json as _json_ws_cfm
                                        await websocket.send_json({
                                            "type": "tool_event",
                                            "event": "action_detail",
                                            "action_type": a.type,
                                            "name": a.type if a.type != "use_tool" else (a.name or a.type),
                                            "summary": _action_summary.get("command", "") or _action_summary["label"],
                                            "label": _action_summary["label"],
                                            "command": _action_summary.get("command", ""),
                                            "output_preview": _action_summary.get("output_preview", ""),
                                            "success": result.get("success", False),
                                            "elapsed_ms": _action_summary.get("elapsed_ms", 0),
                                            "retried": _action_summary.get("retried", False),
                                        })
                                    # 非流式工具推送 action_result
                                    if a.type in ("read_dir", "read_file", "read_lines", "search_in_file") and result_text:
                                        await websocket.send_json({
                                            "type": "tool_event",
                                            "event": "action_result",
                                            "action_type": a.type,
                                            "name": a.type,
                                            "summary": a.params.strip()[:60],
                                            "output": result_text[:2000],
                                            "success": result.get("success", False),
                                        })
                                    # transcript 侧栏摘要
                                    await websocket.send_json({
                                        "type": "tool_event", "event": "transcript",
                                        "phase": "action", "role": "system",
                                        "content": f"{'✅' if result.get('success') else '❌'} {a.type}: {result_text[:80]}",
                                        "elapsed": 0,
                                    })

                                for p in build_acts:
                                    a = ParsedAction(type=p["type"], params=p["params"], name=p.get("name", ""))
                                    await orchestrator._execute_action(a, original, transcript)
                                    if hasattr(orchestrator, 'state'):
                                        orchestrator.state.add_action_executed(a.type, "构建完成", True)

                                # Push build_complete event directly to frontend
                                if hasattr(orchestrator, 'state') and orchestrator.state.code_files:
                                    from pathlib import Path as _PBC
                                    await websocket.send_json({
                                        "type": "tool_event",
                                        "event": "build_complete",
                                        "success": True,
                                        "files": [_PBC(f).name for f in orchestrator.state.code_files],
                                    })

                            if hasattr(orchestrator, 'state'):
                                orchestrator.state.save()
                                try:
                                    await websocket.send_json({"type": "state_sync", **orchestrator.state.to_snapshot()})
                                except Exception as e:
                                    log.debug("suppressed: %s", e)
                            await asyncio.sleep(0.05)
                            await websocket.send_json({"type": "status", "content": "idle"})
                    continue

                # 处理决策选择（协作式构建）
                if data.get("type") == "decision_response":
                    user_decisions = data.get("decisions", [])
                    if user_decisions:
                        orchestrator.context.metadata["_user_decisions"] = user_decisions
                    else:
                        orchestrator.context.metadata["_skip_analysis"] = True
                    orchestrator.context.metadata.pop("_pending_decisions", None)
                    await websocket.send_json({"type": "status", "content": "thinking"})
                    orchestrator.context.metadata["session_id"] = session_id
                    original = orchestrator.context.metadata.get("_pending_request",
                              orchestrator.context.user_request)
                    try:
                        await orchestrator.run(original)
                    except Exception as e:
                        await websocket.send_json({"type": "error", "content": str(e)})
                    await asyncio.sleep(0.05)
                    await websocket.send_json({"type": "status", "content": "idle"})
                    continue

                # 处理方案选择
                if data.get("type") == "plan_select":
                    plan_id = data.get("plan_id", 1)
                    user_note = data.get("user_note", "")
                    plans = orchestrator.context.metadata.get("_pending_plans", [])
                    original = orchestrator.context.metadata.get("_pending_request", "")
                    selected = next((p for p in plans if p["id"] == plan_id), plans[0] if plans else {})
                    orchestrator.context.metadata.pop("_pending_plans", None)
                    orchestrator.context.metadata.pop("_pending_request", None)
                    await websocket.send_json({"type": "status", "content": "thinking"})
                    orchestrator.context.metadata["session_id"] = session_id
                    try:
                        await orchestrator.run_with_plan(original, selected, user_note)
                    except Exception as e:
                        await websocket.send_json({"type": "error", "content": str(e)})
                    await asyncio.sleep(0.05)
                    await websocket.send_json({"type": "status", "content": "idle"})
                    continue

                if not user_input:
                    continue

                # Auto-improve loop: user triggers autonomous iteration
                if data.get("type") == "auto_improve" or "持续改进" in user_input or "自动优化" in user_input:
                    from educe.core.task_loop import TaskLoop
                    budget = data.get("budget_minutes", 10)
                    max_iter = data.get("max_iterations", 6)
                    goal = user_input if user_input else "持续改进当前产物"

                    task_loop = TaskLoop(orchestrator)
                    orchestrator.context.metadata["session_id"] = session_id
                    orchestrator.context.metadata["_task_loop_active"] = True

                    await websocket.send_json({"type": "status", "content": "thinking"})
                    await websocket.send_json({
                        "type": "tool_event", "event": "transcript",
                        "phase": "build", "role": "system",
                        "content": "启动自主改进循环 (预算{}分钟, 最多{}轮)".format(budget, max_iter),
                        "elapsed": 0})

                    async def loop_progress(iteration):
                        if ws_closed["value"]:
                            return
                        try:
                            await websocket.send_json({
                                "type": "tool_event", "event": "transcript",
                                "phase": "build", "role": "model",
                                "content": "轮{} [{}] {}".format(
                                    iteration.index, iteration.action, iteration.instruction[:80]),
                                "elapsed": round(iteration.elapsed, 1)})
                        except Exception as e:
                            log.debug("suppressed: %s", e)

                    try:
                        result = await task_loop.run(
                            goal, budget_minutes=budget, max_iterations=max_iter,
                            on_progress=loop_progress)
                        await websocket.send_json({
                            "type": "tool_event", "event": "transcript",
                            "phase": "build", "role": "system",
                            "content": "循环结束: {} ({}轮, {:.0f}s)".format(
                                result.stop_reason, len(result.iterations), result.total_elapsed),
                            "elapsed": round(result.total_elapsed, 1)})
                    except Exception as e:
                        await websocket.send_json({"type": "error", "content": str(e)})

                    orchestrator.context.metadata.pop("_task_loop_active", None)
                    await asyncio.sleep(0.05)
                    await websocket.send_json({"type": "status", "content": "idle"})
                    continue

                file_ids = data.get("file_ids", [])
                file_content = None
                if file_ids:
                    from educe.core.file_handler import format_for_prompt
                    files = session_files.get(session_id, {})
                    attached = [files[fid] for fid in file_ids if fid in files]
                    if attached:
                        file_content = format_for_prompt(attached)

                # @ 引用文件：直接读取项目内文件注入
                referenced_files = data.get("referenced_files", [])
                if referenced_files:
                    ref_parts = []
                    import educe as _educe_pkg
                    project_path = Path(_educe_pkg.__file__).parent.parent
                    for ref_path in referenced_files[:5]:  # 最多5个文件
                        full_path = project_path / ref_path if not Path(ref_path).is_absolute() else Path(ref_path)
                        if full_path.exists() and full_path.is_file():
                            try:
                                content = full_path.read_text(encoding="utf-8", errors="replace")[:8000]
                                ref_parts.append(f"<file path=\"{ref_path}\">\n{content}\n</file>")
                            except Exception as e:
                                log.debug("suppressed: %s", e)
                    if ref_parts:
                        ref_block = "<referenced_files>\n" + "\n".join(ref_parts) + "\n</referenced_files>\n\n"
                        file_content = (file_content or "") + ref_block

                    # 信号通道：记录引用事件到记忆系统（L2 沉淀）
                    try:
                        from educe.core.reference_memory import record_file_reference
                        for ref_path in referenced_files[:5]:
                            record_file_reference(ref_path, context=user_input[:100])
                    except Exception as e:
                        log.debug("suppressed: %s", e)

                # User sent a new message — clear any pending plan/decision state
                orchestrator.context.metadata.pop("_pending_plans", None)
                orchestrator.context.metadata.pop("_pending_request", None)
                orchestrator.context.metadata.pop("_pending_decisions", None)

                # 生命周期事件：ws_received
                import time as _time_ws
                _request_start = _time_ws.time()
                _request_id = f"{session_id[:8]}_{int(_request_start*1000)%100000}"
                sl = orchestrator.session_logger
                if sl:
                    sl.event(type="lifecycle", name="ws_received",
                             summary=user_input[:80],
                             data={"request_id": _request_id, "msg_len": len(user_input),
                                   "has_file": bool(file_content),
                                   "user_message": user_input[:200]})

                await websocket.send_json({"type": "status", "content": "thinking"})
                orchestrator.context.metadata["session_id"] = session_id

                async def _run_and_sync():
                    try:
                        await orchestrator.run(user_input, file_content=file_content)
                    except asyncio.CancelledError:
                        log.info("session %s: task cancelled (superseded by new message)", session_id[:8])
                        if sl:
                            sl.event(type="lifecycle", name="task_cancelled",
                                     summary="superseded by new message",
                                     data={"request_id": _request_id})
                        return
                    except Exception as e:
                        log.error("session %s: orchestrator.run failed: %s", session_id[:8], str(e)[:200])
                        if sl:
                            sl.event(type="lifecycle", name="request_error", status="error",
                                     summary=str(e)[:100],
                                     data={"request_id": _request_id, "error": str(e)[:200]})
                        try:
                            await websocket.send_json({"type": "error", "content": str(e)[:200]})
                            await websocket.send_json({
                                "type": "request_complete",
                                "request_id": _request_id,
                                "wall_ms": round((_time_ws.time() - _request_start) * 1000),
                                "success": False,
                            })
                        except Exception:
                            pass
                        return
                    # 生命周期事件：request_complete
                    _wall_ms = (_time_ws.time() - _request_start) * 1000
                    if sl:
                        sl.event(type="lifecycle", name="request_complete",
                                 duration_ms=_wall_ms,
                                 summary=f"wall={_wall_ms:.0f}ms",
                                 data={"request_id": _request_id, "wall_ms": round(_wall_ms)})
                    # 推送 request_complete WS 事件（前端/测试可靠判断请求完毕）
                    try:
                        await websocket.send_json({
                            "type": "request_complete",
                            "request_id": _request_id,
                            "wall_ms": round(_wall_ms),
                            "success": True,
                        })
                    except Exception:
                        pass
                    if hasattr(orchestrator, 'state'):
                        code_files = orchestrator.context.artifacts.get("code_files", [])
                        if code_files and code_files != orchestrator.state.code_files:
                            orchestrator.state.code_files = code_files
                            orchestrator.state.output_dir = orchestrator.context.artifacts.get("output_dir", "")
                        orchestrator.state.user_request = user_input
                        orchestrator.state.save()
                        try:
                            await websocket.send_json({"type": "state_sync", **orchestrator.state.to_snapshot()})
                        except Exception as e:
                            log.debug("state_sync send failed: %s", e)
                    await asyncio.sleep(0.05)
                    if not orchestrator.context.metadata.get("_pending_decisions") and not orchestrator.context.metadata.get("_pending_plans"):
                        expert_name = orchestrator.context.metadata.get("expert_name", "")
                        if expert_name:
                            await websocket.send_json({"type": "expert", "content": expert_name})
                        await websocket.send_json({"type": "status", "content": "idle"})

                # Cancel-previous: 新消息取消正在进行的旧任务
                lock = session_locks.setdefault(session_id, asyncio.Lock())
                prev_task = session_tasks.get(session_id)
                if prev_task and not prev_task.done():
                    prev_task.cancel()
                    try:
                        await prev_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    log.info("session %s: previous task cancelled", session_id[:8])
                    if sl:
                        sl.event(type="lifecycle", name="task_cancelled",
                                 summary="cancel-previous triggered",
                                 data={"request_id": _request_id, "reason": "new_message"})
                    # 清理残留状态
                    orchestrator.context.metadata.pop("_pending_actions", None)
                    orchestrator.context.metadata.pop("_clarify_pending", None)

                # 生命周期事件：task_created
                if sl:
                    sl.event(type="lifecycle", name="task_created",
                             summary=f"request_id={_request_id}",
                             data={"request_id": _request_id})

                async def _guarded_run():
                    async with lock:
                        await _run_and_sync()

                task = asyncio.create_task(_guarded_run())
                session_tasks[session_id] = task

        except WebSocketDisconnect:
            # Cancel running task on disconnect
            prev_task = session_tasks.pop(session_id, None)
            if prev_task and not prev_task.done():
                prev_task.cancel()
            session_locks.pop(session_id, None)
            # Close session logger (protected — must not lose logs)
            try:
                if orchestrator and orchestrator.session_logger:
                    orchestrator.session_logger.close("completed")
            except Exception as e:
                log.debug("suppressed: %s", e)
            # Clean up stuck building state
            if orchestrator and hasattr(orchestrator, 'state') and orchestrator.state.phase == "building":
                code_files = orchestrator.context.artifacts.get("code_files", [])
                orchestrator.state.add_build_complete(code_files, success=bool(code_files))
                orchestrator.state.save()
            if session_id in sessions:
                del sessions[session_id]
            if session_id in session_files:
                del session_files[session_id]
            import shutil
            upload_dir = Path(".educe/uploads") / session_id
            if upload_dir.exists():
                shutil.rmtree(upload_dir, ignore_errors=True)
        except Exception as e:
            # Catch-all: ensure logger is closed even on unexpected errors
            try:
                if orchestrator and orchestrator.session_logger:
                    orchestrator.session_logger.close("error")
            except Exception as e:
                log.debug("suppressed: %s", e)
            import logging as _log
            _log.getLogger("educe.ws").error("WebSocket handler crash: %s", str(e)[:200])

    return app


AGENT_SUMMARIES = {
    "project_manager": "分析需求，制定计划",
    "product_manager": "设计产品方案",
    "architect": "技术架构设计",
    "engineer": "编码实现",
    "reviewer": "代码审查",
    "crowd_user": "用户体验测试",
    "memory_keeper": "知识沉淀",
}


def _extract_summary(sender: str, content: str, msg_type: str) -> str:
    """提取一行干净的摘要给前端展示，绝不暴露内部协议"""
    if msg_type == "handoff":
        return ""

    import re

    noise = ["移交", "用户原始需求", "技术架构", "产品设计", "```", "---", "|||"]

    if sender == "engineer" or sender == "builder":
        file_count = len(re.findall(r'```filepath:', content))
        if file_count > 0:
            # 提取文件名
            fnames = re.findall(r'```filepath:([^\n]+)', content)
            return f"已生成 {', '.join(fnames)}" if fnames else f"已生成 {file_count} 个文件"
        html_match = re.search(r'<!DOCTYPE', content)
        if html_match:
            return "已生成可运行代码"
        return "编码中..."

    if sender == "reviewer":
        if "不通过" in content:
            return "审查未通过，回退修改"
        if "通过" in content:
            return "审查通过"
        return "代码审查中..."

    if sender == "crowd_user":
        stars = re.findall(r'⭐', content)
        if stars:
            return f"内测完成 ({len(stars)//5}位用户评价)"
        return "用户体验测试完成"

    if sender == "memory_keeper":
        return "知识沉淀完成"

    lines = content.strip().split("\n")
    for line in lines[:15]:
        s = line.strip().lstrip("#").strip()
        if not s or len(s) < 5:
            continue
        if any(n in s for n in noise):
            continue
        if s.startswith("|") or s.startswith("```"):
            continue
        return s[:60]

    return AGENT_SUMMARIES.get(sender, "完成")


def run_web(host: str = "0.0.0.0", port: int = 7860, config: EduceConfig | None = None):
    if not HAS_WEB_DEPS:
        print("Web dependencies not installed. Run: pip install educe[web]")
        print("Or: pip install fastapi uvicorn websockets")
        return

    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(project_root)

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


# Module-level app for uvicorn CLI: uvicorn educe.web.server:app
try:
    from educe.core.config import EduceConfig as _Cfg
    app = create_app(_Cfg.load())
except Exception:
    app = None
