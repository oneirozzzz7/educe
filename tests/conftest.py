"""
Educe 测试基础设施

FakeModelClient: 脚本化模型返回，零 API 成本
create_test_app: 创建可测试的 FastAPI app（注入 fake model）
ws_connect: 异步 WS 客户端 fixture
collect_until: 收集 WS 事件直到指定类型出现
"""
import asyncio
import json
import os
import pytest
import pytest_asyncio
import websockets
from contextlib import asynccontextmanager
from typing import Any

# 测试端口（避免与真实服务冲突）
TEST_PORT = 17860


class FakeModelClient:
    """脚本化模型：按 responses 列表依次返回。"""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_idx = 0
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        self.calls: list[dict] = []

    async def chat(self, messages, model="fake", temperature=0.7, max_tokens=4096, **kw) -> str:
        self.calls.append({"messages": messages[-1:], "model": model})
        if self._call_idx < len(self._responses):
            resp = self._responses[self._call_idx]
            self._call_idx += 1
            return resp
        return ""

    async def chat_with_reasoning(self, messages, model="fake", **kw):
        content = await self.chat(messages, model, **kw)
        return content, ""


async def collect_until(ws, event_type: str, timeout: float = 10) -> list[dict]:
    """收集 WS 事件直到 event_type 出现（含）。"""
    events = []
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            data = json.loads(raw)
            events.append(data)
            if data.get("type") == event_type:
                break
    except (asyncio.TimeoutError, TimeoutError):
        pass
    return events


@asynccontextmanager
async def start_test_server(fake_responses: list[str]):
    """启动测试服务器（fake model 注入），yield WS URL。"""
    from unittest.mock import patch

    call_state = {"idx": 0}
    responses = list(fake_responses)

    async def _fake_chat(self, messages, model="", **kw):
        if call_state["idx"] < len(responses):
            r = responses[call_state["idx"]]
            call_state["idx"] += 1
            return r
        return ""

    with patch("educe.models.router.ModelClient.chat", _fake_chat):
        # 导入并启动
        from educe.web.server import create_app
        from educe.core.config import EduceConfig
        import uvicorn

        config = EduceConfig.load()
        app = create_app(config)

        server_config = uvicorn.Config(app, host="127.0.0.1", port=TEST_PORT, log_level="error")
        server = uvicorn.Server(server_config)

        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.5)

        try:
            yield f"ws://127.0.0.1:{TEST_PORT}/ws/test_session"
        finally:
            server.should_exit = True
            await task


@pytest_asyncio.fixture
async def ws_simple():
    """最简单的 fixture：纯文字回复场景"""
    async with start_test_server(["你好，我是 Educe 测试回复。"]) as url:
        async with websockets.connect(url, ping_interval=None) as ws:
            # Drain initial events (zero_state, etc)
            try:
                for _ in range(5):
                    await asyncio.wait_for(ws.recv(), timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            yield ws


@pytest_asyncio.fixture
async def ws_multi_round():
    """多轮 action 后回复的场景"""
    responses = [
        '```read_file\n/tmp/conftest_test_file.txt\n```',
        '这是一个测试文件，内容分析完毕。',
    ]
    # 确保测试文件存在
    os.makedirs("/tmp", exist_ok=True)
    with open("/tmp/conftest_test_file.txt", "w") as f:
        f.write("test content for contract testing")

    async with start_test_server(responses) as url:
        async with websockets.connect(url, ping_interval=None) as ws:
            try:
                for _ in range(5):
                    await asyncio.wait_for(ws.recv(), timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            yield ws


@pytest_asyncio.fixture
async def ws_shell():
    """shell 执行场景"""
    responses = [
        '```shell\necho contract_test_pass\n```',
        '命令执行完毕。',
    ]
    async with start_test_server(responses) as url:
        async with websockets.connect(url, ping_interval=None) as ws:
            try:
                for _ in range(5):
                    await asyncio.wait_for(ws.recv(), timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            yield ws


@pytest_asyncio.fixture
async def ws_artifact():
    """write_file 产出 artifact 场景"""
    responses = [
        '```write_file\n{"path": "/tmp/contract_artifact.txt", "content": "artifact content"}\n```',
        '文件已创建。',
    ]
    async with start_test_server(responses) as url:
        async with websockets.connect(url, ping_interval=None) as ws:
            try:
                for _ in range(5):
                    await asyncio.wait_for(ws.recv(), timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            yield ws


@pytest_asyncio.fixture
async def ws_irreversible():
    """不可逆命令场景"""
    responses = [
        '```shell\nrm -rf /tmp/contract_dangerous_dir\n```',
    ]
    async with start_test_server(responses) as url:
        async with websockets.connect(url, ping_interval=None) as ws:
            try:
                for _ in range(5):
                    await asyncio.wait_for(ws.recv(), timeout=1)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            yield ws
