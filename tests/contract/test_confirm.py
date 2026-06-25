"""契约测试：不可逆暂停（confirm gate）。

守护的核心契约：
1. rm -rf 等不可逆命令触发 action_confirm_request
2. 在用户确认前，request_complete 不应发出
"""
import json
import pytest
from tests.conftest import collect_until


@pytest.mark.asyncio
async def test_irreversible_triggers_confirm(ws_irreversible):
    """rm -rf 触发 action_confirm_request，不自动执行。"""
    await ws_irreversible.send(json.dumps({"message": "do it"}))
    # 等 confirm 事件（不等 request_complete，因为它不应出现）
    events = await collect_until(ws_irreversible, "action_confirm_request", timeout=15)

    types = [e.get("type") for e in events]
    assert "action_confirm_request" in types, \
        f"rm -rf 必须触发 confirm，实际事件: {types}"
    assert "request_complete" not in types, \
        "未确认前不应发出 request_complete"

    confirm_evt = next(e for e in events if e.get("type") == "action_confirm_request")
    actions = confirm_evt.get("actions", [])
    assert len(actions) > 0
    assert "rm -rf" in actions[0].get("params", "")
