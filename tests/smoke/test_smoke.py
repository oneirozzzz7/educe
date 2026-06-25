"""冒烟测试：真实 LLM，验证完整链路。

需要真实 API（EDUCE_BASE_URL + EDUCE_API_KEY），push 前运行。
运行方式：pytest tests/smoke/ -v -m smoke
"""
import asyncio
import json
import os
import pytest
import websockets

SMOKE_PORT = 7860
SMOKE_WS_BASE = f"ws://127.0.0.1:{SMOKE_PORT}/ws"

pytestmark = pytest.mark.smoke


def _api_available():
    """检查真实后端是否在运行。"""
    import urllib.request
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{SMOKE_PORT}/api/effects", timeout=3)
        return r.status == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def skip_if_no_api():
    if not _api_available():
        pytest.skip("真实后端未运行（需要先 ./start.sh）")


async def _send_and_collect(message: str, timeout: float = 30) -> list[dict]:
    session_id = f"smoke_{id(message) % 99999}"
    url = f"{SMOKE_WS_BASE}/{session_id}"
    async with websockets.connect(url, ping_interval=None) as ws:
        # Drain initial
        try:
            for _ in range(5):
                await asyncio.wait_for(ws.recv(), timeout=2)
        except (asyncio.TimeoutError, TimeoutError):
            pass

        await ws.send(json.dumps({"message": message}))
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
                if data.get("type") == "request_complete":
                    break
        except (asyncio.TimeoutError, TimeoutError):
            pass
        return events


@pytest.mark.asyncio
async def test_smoke_reply():
    """真实 LLM：发消息能收到非空回复。"""
    events = await _send_and_collect("你好，用一句话回复我")
    chunks = [e for e in events if e.get("type") == "chunk"]
    assert len(chunks) > 0, "必须收到 reply chunk"

    reply = "".join(c.get("content", "") for c in chunks)
    assert len(reply) >= 3, f"回复太短: '{reply}'"

    types = [e.get("type") for e in events]
    assert "request_complete" in types


@pytest.mark.asyncio
async def test_smoke_shell():
    """真实 LLM：shell 命令自动执行，输出到达客户端。"""
    events = await _send_and_collect("执行 echo smoke_test_ok")
    tool_chunks = [e for e in events if e.get("type") == "tool_chunk"]
    output = "".join(tc.get("data", "") for tc in tool_chunks)
    assert "smoke_test_ok" in output, f"shell 输出不包含预期内容: {output[:100]}"


@pytest.mark.asyncio
async def test_smoke_artifact():
    """真实 LLM：写文件产生 artifact 事件。"""
    events = await _send_and_collect(
        "创建文件 /tmp/smoke_test_artifact.txt 内容为 smoke OK")
    artifact_events = [e for e in events
                       if e.get("type") == "tool_event" and e.get("event") == "artifact_produced"]
    assert len(artifact_events) > 0, "write_file 必须产生 artifact_produced 事件"
    assert os.path.exists("/tmp/smoke_test_artifact.txt")
