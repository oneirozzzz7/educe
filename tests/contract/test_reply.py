"""契约测试：reply chunk 时序。

守护的核心契约：
1. 纯文字回复的 chunk 必须在 request_complete 之前到达客户端
2. 多轮 action 后模型最终回复必须推送给客户端（Session 11 事故）
"""
import json
import pytest
from tests.conftest import collect_until


@pytest.mark.asyncio
async def test_reply_chunks_before_complete(ws_simple):
    """纯文字回复：所有 chunk 在 request_complete 之前到达。"""
    await ws_simple.send(json.dumps({"message": "你好"}))
    events = await collect_until(ws_simple, "request_complete", timeout=15)

    types = [e.get("type") for e in events]
    chunks = [e for e in events if e.get("type") == "chunk"]
    complete_idx = types.index("request_complete")

    assert len(chunks) > 0, "必须收到至少一个 reply chunk"
    for c in chunks:
        assert events.index(c) < complete_idx, \
            f"chunk 出现在 request_complete 之后: {c.get('content', '')[:30]}"

    reply = "".join(c.get("content", "") for c in chunks)
    assert reply.strip() != "", "reply 内容不能为空"


@pytest.mark.asyncio
async def test_reply_content_nonempty(ws_simple):
    """回复内容拼接后有意义（非空白/非 None）。"""
    await ws_simple.send(json.dumps({"message": "介绍一下你自己"}))
    events = await collect_until(ws_simple, "request_complete", timeout=15)

    chunks = [e for e in events if e.get("type") == "chunk"]
    reply = "".join(c.get("content", "") for c in chunks)
    assert len(reply) >= 5, f"回复太短: '{reply}'"


@pytest.mark.asyncio
async def test_multi_round_action_then_reply(ws_multi_round):
    """多轮 action 后模型最终回复 — 守护 Session 11 chunk 丢失事故。"""
    await ws_multi_round.send(json.dumps({"message": "分析这个文件"}))
    events = await collect_until(ws_multi_round, "request_complete", timeout=15)

    types = [e.get("type") for e in events]
    chunks = [e for e in events if e.get("type") == "chunk"]

    assert "request_complete" in types, "请求必须正常完成"
    assert len(chunks) > 0, "多轮 action 后必须有最终回复 chunk"

    reply = "".join(c.get("content", "") for c in chunks)
    assert reply.strip() != "", "最终回复不能为空"
