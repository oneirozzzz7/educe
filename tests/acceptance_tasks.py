"""
激发引擎端到端验收测试集

每个任务有：
- 构建指令（发给 Educe）
- Playwright 验收步骤（钻进 iframe 验证可运行性）
- 通过分（0-N，客观可量化）

用途：对比不同 seed 产出的通过率
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AcceptanceTask:
    """一个带可执行验收标准的构建任务"""
    id: str
    prompt: str  # 发给 Educe 的构建指令
    checks: list[dict]  # Playwright 验收步骤


# ═══ 验收任务集 ═══

TASKS = [
    AcceptanceTask(
        id="counter",
        prompt="帮我写一个计数器应用，要有增加、减少、重置按钮",
        checks=[
            {"type": "element_exists", "selector": "button", "min_count": 3, "desc": "至少有3个按钮"},
            {"type": "text_exists", "text": "0", "desc": "初始显示0"},
            {"type": "click_and_check", "click": "button:has-text('增')", "expect_text": "1", "desc": "点增加后变1"},
            {"type": "click_and_check", "click": "button:has-text('减')", "expect_text": "0", "desc": "点减少后回0"},
        ]
    ),
    AcceptanceTask(
        id="todo",
        prompt="帮我写一个待办事项应用，能添加和删除任务",
        checks=[
            {"type": "element_exists", "selector": "input", "min_count": 1, "desc": "有输入框"},
            {"type": "element_exists", "selector": "button", "min_count": 1, "desc": "有按钮"},
            {"type": "type_and_submit", "input_selector": "input", "text": "测试任务",
             "submit": "button", "expect_text": "测试任务", "desc": "输入后能显示"},
        ]
    ),
    AcceptanceTask(
        id="timer",
        prompt="帮我写一个倒计时器，可以设置秒数，开始后倒数到0",
        checks=[
            {"type": "element_exists", "selector": "input, button", "min_count": 2, "desc": "有输入和按钮"},
            {"type": "text_exists", "text": "0", "desc": "有数字显示"},
        ]
    ),
    AcceptanceTask(
        id="calculator",
        prompt="帮我写一个简单计算器，支持加减乘除",
        checks=[
            {"type": "element_exists", "selector": "button", "min_count": 10, "desc": "至少10个按钮（0-9）"},
            {"type": "click_sequence", "clicks": ["button:has-text('1')", "button:has-text('+')", "button:has-text('2')", "button:has-text('=')"],
             "expect_text": "3", "desc": "1+2=3"},
        ]
    ),
    AcceptanceTask(
        id="color_picker",
        prompt="帮我写一个颜色选择器，点击颜色块可以复制对应的hex值",
        checks=[
            {"type": "element_exists", "selector": "[style*=background], [class*=color]", "min_count": 3, "desc": "至少3个颜色块"},
        ]
    ),
]


async def run_playwright_check(page, iframe, check: dict) -> bool:
    """执行单个验收检查"""
    try:
        if check["type"] == "element_exists":
            elements = await iframe.query_selector_all(check["selector"])
            return len(elements) >= check.get("min_count", 1)

        elif check["type"] == "text_exists":
            content = await iframe.text_content("body")
            return check["text"] in (content or "")

        elif check["type"] == "click_and_check":
            btn = await iframe.query_selector(check["click"])
            if not btn:
                return False
            await btn.click()
            await asyncio.sleep(0.3)
            content = await iframe.text_content("body")
            return check["expect_text"] in (content or "")

        elif check["type"] == "type_and_submit":
            inp = await iframe.query_selector(check["input_selector"])
            if not inp:
                return False
            await inp.fill(check["text"])
            submit = await iframe.query_selector(check["submit"])
            if submit:
                await submit.click()
            else:
                await inp.press("Enter")
            await asyncio.sleep(0.5)
            content = await iframe.text_content("body")
            return check["expect_text"] in (content or "")

        elif check["type"] == "click_sequence":
            for selector in check["clicks"]:
                btn = await iframe.query_selector(selector)
                if not btn:
                    return False
                await btn.click()
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)
            content = await iframe.text_content("body")
            return check["expect_text"] in (content or "")

    except Exception:
        return False
    return False


def get_tasks() -> list[AcceptanceTask]:
    return TASKS
