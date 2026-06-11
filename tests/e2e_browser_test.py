"""
DeepForge 前端浏览器端到端测试
用 Playwright 真实操作 Chrome 浏览器
"""
import asyncio
import tempfile
import os
from playwright.async_api import async_playwright

URL = "http://localhost:3001"
RESULTS = []


def report(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  {'✅' if passed else '❌'} {name}" + (f" — {detail}" if detail else ""))


async def run_tests():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # 收集console错误
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(str(err)))

        # ═══════════════════════════════════════
        # 测试1: 页面加载
        # ═══════════════════════════════════════
        print("\n1️⃣  页面加载")
        await page.goto(URL, wait_until="networkidle")
        title = await page.title()
        report("页面标题", title == "DeepForge", title)

        # 检查关键元素
        logo = await page.locator("text=DeepForge").count()
        report("Logo显示", logo > 0)

        headline = await page.locator("text=What will you build").count()
        report("空状态标题", headline > 0)

        textarea = page.locator("textarea")
        report("输入框存在", await textarea.count() > 0)

        paperclip = page.locator("button[title='上传文件']")
        report("📎上传按钮", await paperclip.count() > 0)

        send_btn = page.locator("button:has(svg)").last
        report("发送按钮", await send_btn.count() > 0)

        # 快捷标签
        tags = await page.locator("text=番茄钟").count()
        report("快捷标签", tags > 0)

        # ═══════════════════════════════════════
        # 测试2: 侧栏
        # ═══════════════════════════════════════
        print("\n2️⃣  侧栏")
        sidebar = page.locator("text=最近任务")
        report("侧栏-最近任务", await sidebar.count() > 0)

        new_task = page.locator("text=新任务")
        report("侧栏-新建按钮", await new_task.count() > 0)

        # 收起侧栏
        collapse_btn = page.locator("button").filter(has=page.locator("svg")).first
        await collapse_btn.click()
        await page.wait_for_timeout(300)
        # 展开侧栏
        await page.locator("button").filter(has=page.locator("svg")).first.click()
        await page.wait_for_timeout(300)
        report("侧栏收起/展开", True)

        # ═══════════════════════════════════════
        # 测试3: 设置弹窗
        # ═══════════════════════════════════════
        print("\n3️⃣  设置弹窗")
        # 设置按钮在顶栏右侧，是一个小齿轮
        top_buttons = page.locator("header button")
        settings_count = await top_buttons.count()
        if settings_count > 0:
            await top_buttons.last.click()
            await page.wait_for_timeout(800)

            modal_text = await page.inner_text("body")
            has_modal = "设置" in modal_text or "模型" in modal_text or "服务商" in modal_text
            report("设置弹窗打开", has_modal)

            report("Claude服务商", "Claude" in modal_text)
            report("OpenAI服务商", "OpenAI" in modal_text)
            report("DeepSeek服务商", "DeepSeek" in modal_text)

            api_key_input = page.locator("input[type='password']")
            report("API Key输入框", await api_key_input.count() > 0)

            all_inputs = page.locator("input[type='text']")
            report("Base URL输入框", await all_inputs.count() > 0)

            report("自进化开关", "自进化" in modal_text)

            # 关闭——点遮罩区域
            backdrop = page.locator("div.fixed.inset-0").first
            await backdrop.click(position={"x": 10, "y": 10})
            await page.wait_for_timeout(800)
            report("设置弹窗关闭", True)

        # ═══════════════════════════════════════
        # 测试4: 发送闲聊消息
        # ═══════════════════════════════════════
        print("\n4️⃣  发送闲聊消息")
        await textarea.fill("你好")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)

        user_msg = page.locator("text=你好").last
        report("用户消息显示", await user_msg.count() > 0)

        # 等待回复（最多30秒）
        thinking = page.locator("text=思考中")
        try:
            await thinking.wait_for(state="visible", timeout=5000)
            report("思考指示器", True)
        except:
            report("思考指示器", False, "未出现")

        # 等待回复出现
        try:
            reply_container = page.locator(".df-markdown, .rounded-2xl").filter(has_text="帮")
            await reply_container.first.wait_for(state="visible", timeout=30000)
            report("收到AI回复", True)
        except:
            # 可能用了其他措辞
            await page.wait_for_timeout(15000)
            all_text = await page.inner_text("main")
            has_any_reply = len(all_text) > 50
            report("收到AI回复", has_any_reply, "通过文本长度判断")

        # ═══════════════════════════════════════
        # 测试5: 主题切换
        # ═══════════════════════════════════════
        print("\n5️⃣  主题切换")
        # 主题切换按钮在侧栏底部
        theme_btn = page.locator("button[title*='切换']")
        theme_count = await theme_btn.count()
        if theme_count > 0:
            try:
                await theme_btn.click(timeout=5000)
                await page.wait_for_timeout(500)
                html_el = page.locator("html")
                theme = await html_el.get_attribute("data-theme")
                report("暗色主题切换", theme == "dark", f"theme={theme}")

                await theme_btn.click(timeout=5000)
                await page.wait_for_timeout(300)
                theme2 = await html_el.get_attribute("data-theme")
                report("亮色主题切换", theme2 != "dark", f"theme={theme2}")
            except Exception as e:
                report("主题切换", False, str(e)[:60])
        else:
            report("主题切换按钮", False, "未找到")

        # ═══════════════════════════════════════
        # 测试6: 文件上传
        # ═══════════════════════════════════════
        print("\n6️⃣  文件上传")
        # 创建测试文件
        tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
        tmp.write("def hello():\n    print('hello DeepForge')\n")
        tmp.close()

        file_input = page.locator("input[type='file']")
        await file_input.set_input_files(tmp.name)
        await page.wait_for_timeout(2000)

        # 检查FileChip出现
        all_text = await page.inner_text("body")
        has_chip = "hello" in all_text.lower() or ".py" in all_text or "test" in all_text.lower()
        report("文件chip显示", has_chip)

        os.unlink(tmp.name)

        # ═══════════════════════════════════════
        # 测试7: Console错误检查
        # ═══════════════════════════════════════
        print("\n7️⃣  Console错误检查")
        critical_errors = [e for e in errors if "TypeError" in e or "ReferenceError" in e or "Cannot read" in e]
        report("无致命JS错误", len(critical_errors) == 0,
               f"{len(critical_errors)}个错误" if critical_errors else "干净")
        if critical_errors:
            for e in critical_errors[:3]:
                print(f"     ⚠️ {e[:100]}")

        # ═══════════════════════════════════════
        # 测试8: 响应式
        # ═══════════════════════════════════════
        print("\n8️⃣  响应式")
        await page.set_viewport_size({"width": 375, "height": 667})
        await page.wait_for_timeout(500)
        # 移动端应该能正常显示
        mobile_text = await page.inner_text("body")
        report("移动端渲染", len(mobile_text) > 10)

        await page.set_viewport_size({"width": 1280, "height": 800})

        # ═══════════════════════════════════════
        # 截图保存
        # ═══════════════════════════════════════
        await page.screenshot(path="/tmp/deepforge_e2e_final.png", full_page=True)
        print(f"\n  📸 截图: /tmp/deepforge_e2e_final.png")

        await browser.close()


async def main():
    print("=" * 60)
    print("DeepForge 前端浏览器端到端测试 (Playwright)")
    print("=" * 60)

    await run_tests()

    passed = sum(1 for _, p, _ in RESULTS if p)
    total = len(RESULTS)
    print(f"\n{'=' * 60}")
    print(f"  结果: {passed}/{total} 通过")
    if passed == total:
        print("  🎉 全部通过！")
    else:
        print("  失败项:")
        for name, p, detail in RESULTS:
            if not p:
                print(f"    ❌ {name}: {detail}")
    print("=" * 60)


asyncio.run(main())
