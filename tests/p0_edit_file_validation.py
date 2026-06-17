"""
P0 Validation: edit_file on real 500+ line open-source code module

Target: pallets/click → click/core.py (~2600 lines)
Task: Add a `deprecated` parameter to the Command class that prints a warning on invoke
Validation: modified file still importable, click.command() still works

Drives Orchestrator directly with auto-confirm, using Qwen3.6 (weak model).
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from educe.core.config import EduceConfig
from educe.core.orchestrator import Orchestrator
from educe.agents import ALL_AGENTS
from educe.models.router import ModelClient

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"

PROJECT_DIR = "/tmp/educe_p0_click"


def setup_orchestrator() -> Orchestrator:
    config = EduceConfig.load()
    client = ModelClient(api_key=config.default_model.api_key,
                         base_url=config.default_model.base_url)
    orchestrator = Orchestrator(config)

    for agent_cls in ALL_AGENTS:
        agent = agent_cls(config=config, model_client=client, knowledge=orchestrator.knowledge)
        orchestrator.register(agent)

    orchestrator.context.metadata["session_id"] = f"p0_edit_{int(time.time())}"
    orchestrator.context.metadata["_project_context_path"] = PROJECT_DIR
    return orchestrator


async def auto_confirm_loop(orchestrator: Orchestrator, user_input: str, max_turns: int = 12) -> str:
    """Send message, auto-confirm pending actions, collect full reply"""
    collected_chunks = []

    def on_chunk(agent_name: str, chunk: str):
        collected_chunks.append(chunk)

    orchestrator.on_chunk(on_chunk)
    await orchestrator.run(user_input)

    for _ in range(max_turns):
        pending = orchestrator.context.metadata.get("_pending_actions")
        if not pending:
            break
        collected_chunks.clear()
        await orchestrator.run("确认")

    reply = "".join(collected_chunks)
    orchestrator._on_chunk.clear()
    return reply


def clone_click():
    """Clone pallets/click to temp dir (gitee mirror for speed)"""
    if Path(PROJECT_DIR).exists():
        # Check if already cloned with core.py
        core_py = Path(PROJECT_DIR) / "src" / "click" / "core.py"
        if core_py.exists():
            lines = len(core_py.read_text().split("\n"))
            print(f"  {GREEN}✓ Already cloned. core.py = {lines} lines{RESET}")
            # Reset any previous modifications
            subprocess.run(["git", "-C", PROJECT_DIR, "checkout", "."], capture_output=True)
            return True
        shutil.rmtree(PROJECT_DIR)

    print(f"  Cloning pallets/click (gitee mirror) to {PROJECT_DIR}...")
    result = subprocess.run(
        ["git", "clone", "--depth=1", "https://gitee.com/mirrors/click.git", PROJECT_DIR],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"  {RED}Clone failed: {result.stderr}{RESET}")
        return False

    core_py = Path(PROJECT_DIR) / "src" / "click" / "core.py"
    if not core_py.exists():
        core_py = Path(PROJECT_DIR) / "click" / "core.py"

    if core_py.exists():
        lines = len(core_py.read_text().split("\n"))
        print(f"  {GREEN}✓ Cloned. core.py = {lines} lines{RESET}")
        return True
    else:
        print(f"  {RED}core.py not found in expected locations{RESET}")
        for p in Path(PROJECT_DIR).rglob("core.py"):
            print(f"    Found: {p}")
        return False


def verify_modification():
    """Check that modified click still works"""
    core_py = Path(PROJECT_DIR) / "src" / "click" / "core.py"
    if not core_py.exists():
        core_py = Path(PROJECT_DIR) / "click" / "core.py"

    if not core_py.exists():
        return False, "core.py not found"

    content = core_py.read_text()

    # Check 1: "deprecated" appears in code (our modification)
    if "deprecated" not in content.lower():
        return False, "No 'deprecated' found in core.py — modification didn't happen"

    # Check 2: Syntax valid (compile check)
    try:
        compile(content, str(core_py), "exec")
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    # Check 3: Actually import and use click
    test_script = f'''
import sys
sys.path.insert(0, "{Path(PROJECT_DIR)}/src")
sys.path.insert(0, "{PROJECT_DIR}")
import click

# Basic smoke test — command still works
@click.command()
@click.option("--name", default="World")
def hello(name):
    click.echo(f"Hello {{name}}")

# Don't invoke, just verify the decorator chain works
assert hello is not None
assert hasattr(hello, "name")
print("IMPORT_OK")

# Try deprecated feature if it exists
try:
    @click.command(deprecated=True)
    def old_cmd():
        pass
    print("DEPRECATED_PARAM_OK")
except TypeError as e:
    print(f"DEPRECATED_PARAM_FAIL: {{e}}")
'''
    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True, text=True, timeout=15
    )

    output = result.stdout.strip()
    if "IMPORT_OK" not in output:
        return False, f"Import failed: stdout={output}, stderr={result.stderr[:200]}"

    if "DEPRECATED_PARAM_OK" in output:
        return True, "Full success: import OK + deprecated param works"
    elif "DEPRECATED_PARAM_FAIL" in output:
        return False, f"Import OK but deprecated param rejected: {output}"
    else:
        return False, f"Partial: {output}"


async def main():
    print(f"\n{BOLD}{'═'*70}")
    print("  P0 VALIDATION: edit_file on 500+ line open-source code module")
    print(f"  Target: pallets/click → core.py | Model: Qwen3.6-35B (weak)")
    print(f"{'═'*70}{RESET}\n")

    # Step 1: Clone
    print(f"{BOLD}[1/4] Cloning project{RESET}")
    if not clone_click():
        print(f"\n{RED}ABORT: Clone failed{RESET}")
        return

    # Determine actual core.py path
    core_py = Path(PROJECT_DIR) / "src" / "click" / "core.py"
    if not core_py.exists():
        core_py = Path(PROJECT_DIR) / "click" / "core.py"

    line_count = len(core_py.read_text().split("\n"))
    rel_path = str(core_py.relative_to(PROJECT_DIR))
    print(f"  Target file: {rel_path} ({line_count} lines)\n")

    # Step 2: Setup orchestrator
    print(f"{BOLD}[2/4] Setting up Orchestrator{RESET}")
    orchestrator = setup_orchestrator()
    print(f"  {GREEN}✓ Ready (project context = {PROJECT_DIR}){RESET}\n")

    # Step 3: Send task
    print(f"{BOLD}[3/4] Sending edit task to Educe (multi-turn, auto-confirm){RESET}")

    task = f"""我需要你修改 {rel_path} 文件（这是 click 框架的核心模块，约{line_count}行）。

任务：给 Command 类添加一个 `deprecated` 参数支持。具体要求：

1. 在 Command.__init__() 中新增参数 `deprecated: bool = False`，保存为 self.deprecated
2. 在 Command.invoke() 方法开头加逻辑：如果 self.deprecated 为 True，打印警告 "DeprecationWarning: Command '{{self.name}}' is deprecated."
3. 在 Command.make_context() 中也加检测：如果 deprecated，用 click.echo() 输出一行警告

请先用 search_in_file 和 read_lines 定位关键位置，然后用 edit_file 做修改。确保不破坏现有代码逻辑。"""

    start_time = time.time()
    reply = await auto_confirm_loop(orchestrator, task, max_turns=15)
    elapsed = time.time() - start_time

    print(f"  {DIM}Elapsed: {elapsed:.1f}s{RESET}")
    print(f"  {DIM}Reply (last 300 chars): ...{reply[-300:]}{RESET}\n")

    # Step 4: Verify
    print(f"{BOLD}[4/4] Verification{RESET}")
    success, detail = verify_modification()

    if success:
        print(f"  {GREEN}✓ PASS: {detail}{RESET}")
        print(f"\n{GREEN}{'═'*70}")
        print(f"  P0 VALIDATED — edit_file works on {line_count}-line code module")
        print(f"{'═'*70}{RESET}\n")
    else:
        print(f"  {RED}✗ FAIL: {detail}{RESET}")
        # Show diff for debugging
        diff = subprocess.run(
            ["git", "-C", PROJECT_DIR, "diff", "--stat"],
            capture_output=True, text=True
        )
        print(f"\n  Git diff stat:\n{diff.stdout}")

        # Show actual changes
        full_diff = subprocess.run(
            ["git", "-C", PROJECT_DIR, "diff"],
            capture_output=True, text=True
        )
        if full_diff.stdout:
            print(f"\n  Changes made (first 1000 chars):\n{full_diff.stdout[:1000]}")
        else:
            print(f"\n  {YELLOW}No changes detected in git — edit_file may not have written to the right path{RESET}")
            # Check .educe/output too
            output_dir = Path(".educe/output")
            if output_dir.exists():
                for f in output_dir.rglob("core.py"):
                    print(f"    Found in output dir: {f}")


if __name__ == "__main__":
    asyncio.run(main())
