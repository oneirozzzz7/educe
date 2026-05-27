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
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

    def get_orchestrator(session_id: str) -> Orchestrator:
        if session_id not in sessions:
            model_cfg = config.default_model
            client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)
            orchestrator = Orchestrator(config)
            memory_store = MemoryStore(config.memory.storage_dir)
            skill_registry = SkillRegistry(config.skills.skill_dir, config.skills.community_dir)

            for agent_cls in ALL_AGENTS:
                agent = agent_cls(config=config, model_client=client)
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
            "agents": list(config.agents.keys()),
            "has_api_key": bool(config.default_model.api_key),
        }

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        await websocket.accept()

        orchestrator = get_orchestrator(session_id)

        async def send_message(msg: Message):
            summary = _extract_summary(msg.sender, msg.content, msg.type.value)
            await websocket.send_json({
                "type": "agent_message",
                "sender": msg.sender,
                "summary": summary,
                "content": msg.content,
                "msg_type": msg.type.value,
                "timestamp": msg.timestamp,
                "has_files": "```filepath:" in msg.content or "code_files" in str(msg.data),
            })

        orchestrator.on_message(lambda msg: asyncio.ensure_future(send_message(msg)))

        try:
            while True:
                data = await websocket.receive_json()
                user_input = data.get("message", "")

                if not user_input:
                    continue

                await websocket.send_json({"type": "status", "content": "processing"})

                try:
                    await orchestrator.run_pipeline(user_input)
                    await websocket.send_json({"type": "status", "content": "done"})
                except Exception as e:
                    await websocket.send_json({"type": "error", "content": str(e)})

        except WebSocketDisconnect:
            if session_id in sessions:
                del sessions[session_id]

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
    """从Agent输出中提取一行关键摘要，不暴露全部内容"""
    if msg_type == "handoff":
        return ""

    lines = content.strip().split("\n")
    first_meaningful = ""
    for line in lines[:10]:
        stripped = line.strip().strip("#").strip()
        if stripped and len(stripped) > 4 and not stripped.startswith("```") and not stripped.startswith("|"):
            first_meaningful = stripped[:80]
            break

    base = AGENT_SUMMARIES.get(sender, "处理中")

    if sender == "engineer":
        import re
        file_count = len(re.findall(r'```filepath:', content))
        if file_count > 0:
            return f"生成了 {file_count} 个文件"
        return first_meaningful or "编码中..."

    if sender == "reviewer":
        if "通过" in content and "不通过" not in content:
            return "✅ 审查通过"
        elif "不通过" in content:
            return "❌ 审查不通过，需要修改"
        return first_meaningful or base

    if sender == "crowd_user":
        import re
        stars = re.findall(r'⭐', content)
        return f"内测完成 ({len(stars)//4 if stars else '?'}位用户评价)" if stars else first_meaningful or base

    return first_meaningful or base


def run_web(host: str = "0.0.0.0", port: int = 7860, config: DeepForgeConfig | None = None):
    if not HAS_WEB_DEPS:
        print("Web dependencies not installed. Run: pip install deepforge[web]")
        print("Or: pip install fastapi uvicorn websockets")
        return

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)
