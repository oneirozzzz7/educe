"""
CLI 入口：python -m educe.testing

Usage:
    python -m educe.testing                         # 跑所有合同
    python -m educe.testing --scenario file_reference  # 单场景
    python -m educe.testing --full                  # 含美观度 judge
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Educe Integration Test")
    parser.add_argument("--scenario", "-s", help="Run specific scenario")
    parser.add_argument("--full", action="store_true", help="Enable all verifiers (including aesthetic judge)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    args = parser.parse_args()

    from educe.testing.engine.runner import TestEngine, load_config, load_contract, list_contracts

    config = load_config()

    # Launch Playwright
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Navigate to fresh session
        frontend_url = config["endpoints"]["frontend"]
        await page.goto(frontend_url)
        await page.wait_for_timeout(2000)

        # Create new session (click +)
        new_btn = page.get_by_role("button", name="+")
        if await new_btn.count() > 0:
            await new_btn.click()
            await page.wait_for_timeout(2000)

        # Run scenarios
        engine = TestEngine(config, full_mode=args.full, playwright_page=page)

        if args.scenario:
            scenarios = [args.scenario]
        else:
            scenarios = list_contracts()

        for scenario_name in scenarios:
            print(f"\n▶ Running: {scenario_name}...")
            # Create fresh session for each scenario
            await page.goto(frontend_url)
            await page.wait_for_timeout(1500)
            new_btn = page.get_by_role("button", name="+")
            if await new_btn.count() > 0:
                await new_btn.click()
                await page.wait_for_timeout(2000)

            contract = load_contract(scenario_name)
            result = await engine.run_scenario(contract)
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.summary}")

        # Print full report
        engine.print_report()

        await browser.close()

    # Exit code
    all_passed = all(r.passed for r in engine.results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
