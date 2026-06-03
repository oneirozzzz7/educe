"""
对比实验：Claude 直接生成 vs Educe 框架（StepBuilder + Qwen）
5 个不同类型任务，自动化评估
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TASKS = [
    {
        "id": "dashboard",
        "prompt": "做一个销售数据仪表盘，显示柱状图、饼图和折线图，数据用随机生成",
        "checks": [
            ("canvas/svg元素", ["canvas", "svg", "Canvas", "SVG"]),
            ("图表绘制", ["bindChart", "bindDrawChart", "bindcreateChart", "bindchart", "binddrawChart", "bindcreate"]),
            ("随机数据", ["Math.random", "random", "Random"]),
            ("柱状图", ["bar", "Bar", "柱", "fillRect"]),
            ("饼图", ["pie", "Pie", "饼", "arc"]),
            ("折线图", ["lineTo", "moveTo", "折线"]),
            ("布局容器", ["grid", "flex", "Grid", "Flex"]),
        ],
    },
    {
        "id": "markdown",
        "prompt": "做一个实时Markdown编辑器，左边输入右边实时预览，支持标题、列表、代码块、粗体斜体",
        "checks": [
            ("双栏布局", ["flex", "grid", "split", "left", "right"]),
            ("textarea", ["textarea", "contenteditable"]),
            ("实时监听", ["input", "keyup", "oninput", "addEventListener"]),
            ("标题解析", ["###", "h1", "h2", "h3", "replace"]),
            ("粗体", ["bold", "**", "strong", "<b>"]),
            ("代码块", ["code", "pre", "`"]),
            ("列表", ["<li>", "<ul>", "<ol>", "list"]),
        ],
    },
    {
        "id": "todo",
        "prompt": "做一个待办事项应用，支持添加、完成、删除、分类筛选，数据保存到localStorage",
        "checks": [
            ("localStorage", ["localStorage", "setItem", "getItem"]),
            ("添加功能", ["add", "push", "append", "新增"]),
            ("删除功能", ["delete", "remove", "splice", "删除"]),
            ("完成切换", ["toggle", "complete", "done", "checked"]),
            ("筛选", ["filter", "Filter", "筛选", "category", "all"]),
            ("事件绑定", ["addEventListener", "onclick", "click"]),
            ("JSON序列化", ["JSON.stringify", "JSON.parse"]),
        ],
    },
    {
        "id": "breakout",
        "prompt": "做一个弹球游戏，球有重力和弹性碰撞，挡板用鼠标控制，有砖块可以打碎，有计分",
        "checks": [
            ("游戏循环", ["requestAnimationFrame", "setInterval", "gameLoop"]),
            ("Canvas", ["canvas", "Canvas", "getContext"]),
            ("鼠标控制", ["mousemove", "clientX", "mouse"]),
            ("球物理", ["velocity", "speed", "dx", "dy", "ball"]),
            ("砖块数组", ["brick", "Brick", "block", "Block"]),
            ("碰撞检测", ["collid", "intersect", "hit", "bounce"]),
            ("计分", ["score", "Score", "point"]),
        ],
    },
    {
        "id": "apitester",
        "prompt": "做一个REST API测试工具，能输入URL和方法(GET/POST/PUT/DELETE)，显示响应状态码、头信息和body，支持添加自定义header",
        "checks": [
            ("HTTP方法选择", ["GET", "POST", "PUT", "DELETE", "select", "method"]),
            ("URL输入", ["url", "URL", "input", "endpoint"]),
            ("fetch调用", ["fetch", "XMLHttpRequest", "axios"]),
            ("状态码显示", ["status", "statusCode", "statusText"]),
            ("header显示", ["headers", "Headers", "header"]),
            ("JSON格式化", ["JSON.stringify", "JSON.parse", "pretty", "format"]),
            ("自定义header", ["addHeader", "custom", "header-key", "key.*value"]),
        ],
    },
]


def evaluate_html(content: str, checks: list) -> dict:
    results = {}
    for name, keywords in checks:
        found = any(kw in content for kw in keywords)
        results[name] = found
    score = sum(1 for v in results.values() if v)
    return {"score": score, "total": len(checks), "details": results}


async def run_educe_task(task: dict, output_dir: Path) -> dict:
    """Run task through Educe framework (StepBuilder)"""
    from deepforge.core.config import DeepForgeConfig
    from deepforge.core.step_builder import StepBuilder
    from deepforge.models.router import ModelClient

    config = DeepForgeConfig.load()
    client = ModelClient(api_key=config.default_model.api_key, base_url=config.default_model.base_url)

    build_system = (
        "你是一个编程助手。输出完整、可直接运行的代码。\n"
        "优先输出单个HTML文件（内嵌CSS和JS），除非任务明确需要其他格式。\n"
        "代码不截断、不省略、不用TODO占位。用```filepath:文件名 格式包裹输出。"
    )

    async def call_model(prompt: str) -> str:
        return await client.chat(
            messages=[
                {"role": "system", "content": build_system},
                {"role": "user", "content": prompt},
            ],
            model=config.default_model.model,
            temperature=0.3,
            max_tokens=32768,
            enable_thinking=True,
        )

    sb = StepBuilder(max_steps=4, max_fix_per_step=2)

    t0 = time.time()
    steps = await sb.plan_steps(task["prompt"], call_model)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = await sb.build_incremental(
        steps=steps, call_model_fn=call_model, output_dir=output_dir,
        original_request=task["prompt"],
        on_progress=lambda m: print(f"    [{task['id']}] {m}"),
    )
    elapsed = time.time() - t0

    # Get the main HTML file
    html_content = ""
    if files:
        main_file = next((f for f in files if f.endswith(".html")), list(files.keys())[0])
        html_content = files[main_file]

    return {
        "files": list(files.keys()),
        "size": len(html_content),
        "elapsed": round(elapsed, 1),
        "steps_planned": len(steps),
        "steps": steps,
        "content": html_content,
    }


async def run_experiment(task_idx: int = None):
    """Run comparison experiment for one or all tasks"""
    tasks_to_run = [TASKS[task_idx]] if task_idx is not None else TASKS

    print("=" * 60)
    print("  EDUCE FRAMEWORK EVALUATION")
    print("=" * 60)

    results = []
    for task in tasks_to_run:
        print(f"\n{'─' * 50}")
        print(f"  Task: {task['id']} — {task['prompt'][:40]}...")
        print(f"{'─' * 50}")

        output_dir = Path(f".deepforge/output/eval-educe-{task['id']}")
        result = await run_educe_task(task, output_dir)

        # Evaluate
        eval_result = evaluate_html(result["content"], task["checks"])
        result["eval"] = eval_result

        print(f"  Steps: {result['steps_planned']}")
        for s in result["steps"]:
            print(f"    - {s[:50]}")
        print(f"  Output: {result['size']/1024:.1f} KB, {result['elapsed']}s")
        print(f"  Score: {eval_result['score']}/{eval_result['total']}")
        for name, passed in eval_result["details"].items():
            print(f"    {'✓' if passed else '✗'} {name}")

        results.append({"task": task["id"], **result, "eval": eval_result})

    # Summary
    print(f"\n{'═' * 60}")
    print("  SUMMARY")
    print(f"{'═' * 60}")
    for r in results:
        e = r["eval"]
        print(f"  {r['task']:12s} | {e['score']}/{e['total']} | {r['size']/1024:.1f}KB | {r['elapsed']}s")

    return results


if __name__ == "__main__":
    import sys
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(run_experiment(idx))
