from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from deepforge.core.config import DeepForgeConfig
from deepforge.core.orchestrator import Orchestrator
from deepforge.core.message import Message
from deepforge.models.router import ModelClient
from deepforge.agents import ALL_AGENTS
from deepforge.memory.store import MemoryStore
from deepforge.skills.registry import SkillRegistry

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    HAS_WEB_DEPS = True
except ImportError:
    HAS_WEB_DEPS = False


def create_app(config: DeepForgeConfig | None = None) -> Any:
    if not HAS_WEB_DEPS:
        raise ImportError(
            "Web dependencies not installed. Run: pip install deepforge[web]\n"
            "Or: pip install fastapi uvicorn websockets"
        )

    config = config or DeepForgeConfig.load()
    app = FastAPI(title="DeepForge", version="0.1.0")

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

    sessions: dict[str, Orchestrator] = {}
    session_files: dict[str, dict[str, Any]] = {}  # session_id -> {file_id: FileAttachment}

    # 全局SelfEvolver（跨session共享）
    shared_self_evolver = None
    try:
        from deepforge.core.self_evolver import SelfEvolver
        from deepforge.core.activation_engine import DEFAULT_ACTIVATION_SEED
        model_cfg = config.default_model
        shared_client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
        shared_self_evolver = SelfEvolver(shared_client, model_cfg.model, DEFAULT_ACTIVATION_SEED)
    except Exception:
        pass

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

    @app.get("/api/stats")
    async def stats():
        from deepforge.core.observer import Observer
        obs = Observer()
        return obs.get_stats()

    @app.get("/api/evolution")
    async def evolution_stats():
        """进化引擎运行状态——读最新的evo2日志"""
        import glob
        evo_dir = Path(".deepforge/evolution")
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
                except Exception:
                    pass
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
    async def list_tasks():
        from deepforge.core.session_store import SessionStore
        store = SessionStore()
        sessions = store.list_sessions()
        if sessions:
            return {"tasks": sessions}
        from deepforge.core.task_store import TaskStore
        old_store = TaskStore()
        return {"tasks": old_store.list_tasks()}

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        from deepforge.core.session_store import SessionStore
        store = SessionStore()
        turns = store.get_session(task_id)
        if turns:
            return {"session_id": task_id, "turns": turns}
        from deepforge.core.task_store import TaskStore
        old_store = TaskStore()
        data = old_store.load_task(task_id)
        if data:
            return data
        return {"error": "not found"}

    @app.get("/api/providers")
    async def providers():
        from deepforge.models.router import PROVIDER_PRESETS
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
        except Exception:
            pass

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
            os.environ["DEEPFORGE_MODEL"] = model
        if base_url:
            config.default_model.base_url = base_url
            os.environ["DEEPFORGE_BASE_URL"] = base_url
        if api_key:
            config.default_model.api_key = api_key
            os.environ["DEEPFORGE_API_KEY"] = api_key
        elif not config.default_model.api_key:
            for env_key in ["KIMI_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "GLM_API_KEY"]:
                val = os.environ.get(env_key)
                if val:
                    config.default_model.api_key = val
                    break

        if evolution is not None:
            config.evolution.enabled = bool(evolution)
            os.environ["DEEPFORGE_EVOLUTION"] = str(evolution).lower()

        env_path = Path.cwd() / ".env"
        lines = []
        if env_path.exists():
            lines = [l for l in env_path.read_text().strip().split("\n")
                     if l and not l.startswith("DEEPFORGE_")]
        if config.default_model.api_key:
            lines.append(f"DEEPFORGE_API_KEY={config.default_model.api_key}")
        if base_url:
            lines.append(f"DEEPFORGE_BASE_URL={base_url}")
        if model:
            lines.append(f"DEEPFORGE_MODEL={model}")
        lines.append(f"DEEPFORGE_EVOLUTION={str(config.evolution.enabled).lower()}")
        env_path.write_text("\n".join(lines) + "\n")

        sessions.clear()

        return {"status": "ok", "model": config.default_model.model, "evolution": config.evolution.enabled}

    @app.post("/api/upload/{session_id}")
    async def upload_file(session_id: str, file: UploadFile = File(...)):
        from deepforge.core.file_handler import process_file, FileAttachment, MAX_FILE_SIZE, SUPPORTED_EXTENSIONS
        import tempfile, shutil

        if not file.filename:
            return {"error": "没有文件名"}

        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return {"error": f"不支持的文件类型: {ext}", "supported": list(SUPPORTED_EXTENSIONS)}

        upload_dir = Path(".deepforge/uploads") / session_id
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
        from deepforge.core.domain_engine import DomainEngine
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

        from deepforge.core.domain_engine import DomainEngine
        model_cfg = config.default_model
        from deepforge.models.router import ModelClient
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

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        await websocket.accept()

        orchestrator = get_orchestrator(session_id)

        async def send_message(msg: Message):
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
            if msg.content.startswith("__BUILD_PROGRESS__"):
                step = msg.content.replace("__BUILD_PROGRESS__", "")
                await websocket.send_json({"type": "build_progress", "step": step})
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
            except Exception:
                pass

        orchestrator.on_chunk(lambda a, c: asyncio.ensure_future(send_chunk(a, c)))

        try:
            while True:
                data = await websocket.receive_json()
                user_input = data.get("message", "")

                # 处理用户反馈（thumbs up/down）
                if data.get("type") == "feedback":
                    signal = data.get("signal", "")
                    if orchestrator.credibility:
                        orchestrator.credibility.record_feedback(
                            session_id, data.get("message_id", ""), signal)
                    continue

                # 处理方案选择
                if data.get("type") == "plan_select":
                    plan_id = data.get("plan_id", 1)
                    user_note = data.get("user_note", "")
                    plans = orchestrator.context.metadata.get("_pending_plans", [])
                    original = orchestrator.context.metadata.get("_pending_request", "")
                    selected = next((p for p in plans if p["id"] == plan_id), plans[0] if plans else {})
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

                file_ids = data.get("file_ids", [])
                file_content = None
                if file_ids:
                    from deepforge.core.file_handler import format_for_prompt
                    files = session_files.get(session_id, {})
                    attached = [files[fid] for fid in file_ids if fid in files]
                    if attached:
                        file_content = format_for_prompt(attached)

                await websocket.send_json({"type": "status", "content": "thinking"})
                orchestrator.context.metadata["session_id"] = session_id
                try:
                    await orchestrator.run(user_input, file_content=file_content)
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": str(e)})
                await asyncio.sleep(0.05)
                expert_name = orchestrator.context.metadata.get("expert_name", "")
                if expert_name:
                    await websocket.send_json({"type": "expert", "content": expert_name})
                await websocket.send_json({"type": "status", "content": "idle"})

        except WebSocketDisconnect:
            if session_id in sessions:
                del sessions[session_id]
            if session_id in session_files:
                del session_files[session_id]
            import shutil
            upload_dir = Path(".deepforge/uploads") / session_id
            if upload_dir.exists():
                shutil.rmtree(upload_dir, ignore_errors=True)

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


def run_web(host: str = "0.0.0.0", port: int = 7860, config: DeepForgeConfig | None = None):
    if not HAS_WEB_DEPS:
        print("Web dependencies not installed. Run: pip install deepforge[web]")
        print("Or: pip install fastapi uvicorn websockets")
        return

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


# Module-level app for uvicorn CLI: uvicorn deepforge.web.server:app
try:
    from deepforge.core.config import DeepForgeConfig as _Cfg
    app = create_app(_Cfg.load())
except Exception:
    app = None
