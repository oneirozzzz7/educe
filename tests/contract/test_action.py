"""契约测试：action 执行输出路径。

守护的核心契约：
1. shell action 的 tool_chunk 输出在 request_complete 之前到达
2. write_file 触发 artifact_produced 事件
"""
import json
import pytest
from tests.conftest import collect_until


@pytest.mark.asyncio
async def test_shell_tool_chunk_before_complete(ws_shell):
    """shell 执行：tool_chunk 包含输出且在 request_complete 之前。"""
    await ws_shell.send(json.dumps({"message": "run echo"}))
    events = await collect_until(ws_shell, "request_complete", timeout=15)

    types = [e.get("type") for e in events]
    tool_chunks = [e for e in events if e.get("type") == "tool_chunk"]

    assert "request_complete" in types
    complete_idx = types.index("request_complete")

    assert len(tool_chunks) > 0, "shell 必须产生 tool_chunk 输出"
    for tc in tool_chunks:
        assert events.index(tc) < complete_idx, "tool_chunk 必须在 request_complete 之前"

    output = "".join(tc.get("data", "") for tc in tool_chunks)
    assert "contract_test_pass" in output, f"shell 输出应包含 echo 内容，实际: {output[:100]}"


@pytest.mark.asyncio
async def test_artifact_produced_on_write_file(ws_artifact):
    """write_file 触发 artifact_produced 事件。"""
    await ws_artifact.send(json.dumps({"message": "create file"}))
    events = await collect_until(ws_artifact, "request_complete", timeout=15)

    types = [e.get("type") for e in events]
    artifact_events = [e for e in events
                       if e.get("type") == "tool_event" and e.get("event") == "artifact_produced"]

    assert len(artifact_events) > 0, "write_file 必须触发 artifact_produced 事件"

    art = artifact_events[0]
    assert art.get("filename") == "contract_artifact.txt"
    assert art.get("size", 0) > 0

    if "request_complete" in types:
        complete_idx = types.index("request_complete")
        assert events.index(artifact_events[0]) < complete_idx, \
            "artifact_produced 必须在 request_complete 之前"
