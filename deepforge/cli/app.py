from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from deepforge.core.config import DeepForgeConfig
from deepforge.core.orchestrator import Orchestrator
from deepforge.models.router import ModelClient, ModelRouter, PROVIDER_PRESETS
from deepforge.agents import ALL_AGENTS
from deepforge.memory.store import MemoryStore
from deepforge.skills.registry import SkillRegistry

console = Console()

BANNER = r"""
[bold cyan]
  ____                   _____
 |  _ \  ___  ___ _ __  |  ___|__  _ __ __ _  ___
 | | | |/ _ \/ _ \ '_ \ | |_ / _ \| '__/ _` |/ _ \
 | |_| |  __/  __/ |_) ||  _| (_) | | | (_| |  __/
 |____/ \___|\___| .__/ |_|  \___/|_|  \__, |\___|
                 |_|                    |___/
[/bold cyan]
[dim]Multi-agent harness · Make weak LLMs do strong work[/dim]
[dim]v0.1.0 · https://github.com/deepforge-ai/deepforge[/dim]
"""


def create_orchestrator(config: DeepForgeConfig) -> Orchestrator:
    model_cfg = config.default_model
    client = ModelClient(api_key=model_cfg.api_key, base_url=model_cfg.base_url)

    orchestrator = Orchestrator(config)

    memory_store = MemoryStore(config.memory.storage_dir)
    skill_registry = SkillRegistry(config.skills.skill_dir, config.skills.community_dir)

    for agent_cls in ALL_AGENTS:
        agent = agent_cls(config=config, model_client=client)
        if hasattr(agent, 'memory_store'):
            agent.memory_store = memory_store
        if hasattr(agent, 'skill_registry'):
            agent.skill_registry = skill_registry
        orchestrator.register(agent)

    return orchestrator


def show_banner():
    console.print(BANNER)


def show_status(config: DeepForgeConfig):
    table = Table(box=box.ROUNDED, title="⚙️ 当前配置", title_style="bold")
    table.add_column("项目", style="cyan")
    table.add_column("值", style="green")

    table.add_row("模型", config.default_model.model)
    table.add_row("API地址", config.default_model.base_url)
    table.add_row("API Key", "✅ 已配置" if config.default_model.api_key else "❌ 未配置")
    table.add_row("语言", config.language)

    enabled_agents = [name for name, cfg in config.agents.items() if cfg.enabled]
    table.add_row("启用的Agent", f"{len(enabled_agents)}个")

    console.print(table)


@click.group(invoke_without_command=True)
@click.option("--config", "-c", default=None, help="配置文件路径")
@click.pass_context
def main(ctx, config):
    """DeepForge - 用弱模型做强活的多Agent框架"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config

    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)


@main.command()
@click.option("--config", "-c", default=None, help="配置文件路径")
def chat(config):
    """交互式对话模式"""
    cfg = DeepForgeConfig.load(config)
    show_banner()
    show_status(cfg)

    if not cfg.default_model.api_key:
        console.print("\n[yellow]⚠ 未配置API Key，请通过以下方式之一配置：[/yellow]")
        console.print("  1. 设置环境变量: export DEEPSEEK_API_KEY=your-key")
        console.print("  2. 创建配置文件: deepforge init")
        console.print("  3. 命令行指定: deepforge chat --config path/to/config.yaml\n")
        return

    orchestrator = create_orchestrator(cfg)

    console.print("\n[bold green]✅ DeepForge 已就绪！[/bold green]")
    console.print("[dim]输入你想要创建的东西，DeepForge会帮你完成。[/dim]")
    console.print("[dim]输入 /help 查看帮助，/quit 退出[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]🔥 你[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见！[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]再见！[/dim]")
            break

        if user_input.lower() == "/help":
            _show_help()
            continue

        if user_input.lower() == "/status":
            show_status(cfg)
            continue

        if user_input.lower() == "/agents":
            _show_agents(orchestrator)
            continue

        if user_input.lower() == "/memory":
            _show_memory(cfg)
            continue

        console.print(f"\n[bold]🚀 开始处理: {user_input[:50]}{'...' if len(user_input) > 50 else ''}[/bold]\n")

        try:
            if user_input.startswith("/iter "):
                real_input = user_input[6:].strip()
                console.print("[yellow]🔄 迭代模式：审查不通过将自动回退修改[/yellow]\n")
                asyncio.run(orchestrator.run_iterative_pipeline(real_input))
            else:
                asyncio.run(orchestrator.run_pipeline(user_input))
        except Exception as e:
            console.print(f"\n[red]❌ 发生错误: {e}[/red]")
            console.print("[dim]请检查API Key和网络连接[/dim]")

        console.print("\n[green]✅ 处理完成！[/green]\n")


@main.command()
@click.option("--provider", "-p", default="deepseek", help="模型提供商")
def init(provider):
    """初始化DeepForge配置"""
    from pathlib import Path
    import shutil

    config_dir = Path.cwd() / ".deepforge"
    config_dir.mkdir(exist_ok=True)

    template = Path(__file__).parent.parent / "templates" / "deepforge.example.yaml"
    target = Path.cwd() / "deepforge.yaml"

    if template.exists():
        shutil.copy(template, target)
        console.print(f"[green]✅ 配置文件已创建: {target}[/green]")
    else:
        cfg = DeepForgeConfig()
        if provider in PROVIDER_PRESETS:
            preset = PROVIDER_PRESETS[provider]
            cfg.default_model.base_url = preset["base_url"]
            cfg.default_model.model = preset["model"]
        cfg.save(target)
        console.print(f"[green]✅ 配置文件已创建: {target}[/green]")

    console.print(f"[dim]请编辑配置文件填入API Key[/dim]")


@main.command()
@click.argument("prompt", nargs=-1)
@click.option("--config", "-c", default=None, help="配置文件路径")
def run(prompt, config):
    """直接运行一次性任务（非交互模式）"""
    user_input = " ".join(prompt)
    if not user_input:
        console.print("[red]请提供任务描述[/red]")
        return

    cfg = DeepForgeConfig.load(config)
    if not cfg.default_model.api_key:
        console.print("[red]未配置API Key[/red]")
        return

    orchestrator = create_orchestrator(cfg)
    console.print(f"\n[bold]🚀 执行任务: {user_input}[/bold]\n")
    asyncio.run(orchestrator.run_pipeline(user_input))
    console.print("\n[green]✅ 完成！[/green]")


@main.command()
@click.option("--host", "-h", default="0.0.0.0", help="监听地址")
@click.option("--port", "-p", default=7860, help="监听端口")
@click.option("--config", "-c", default=None, help="配置文件路径")
def web(host, port, config):
    """启动Web界面（适合非技术用户）"""
    cfg = DeepForgeConfig.load(config)
    console.print(f"\n[bold cyan]🌐 DeepForge Web UI[/bold cyan]")
    console.print(f"[dim]访问 http://localhost:{port} 开始使用[/dim]\n")

    from deepforge.web.server import run_web
    run_web(host=host, port=port, config=cfg)


def _show_help():
    help_text = """
## DeepForge 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/status` | 显示当前配置状态 |
| `/agents` | 显示所有Agent状态 |
| `/memory` | 显示记忆库统计 |
| `/iter <需求>` | 迭代模式（审查不通过自动回退修改） |
| `/quit` | 退出 |

## 使用示例

直接输入你想做的事情即可：
- "帮我做一个番茄钟网页应用"
- "创建一个Python命令行工具，批量重命名文件"
- "做一个Chrome扩展，屏蔽广告"
"""
    console.print(Panel(Markdown(help_text), title="📖 帮助", border_style="blue"))


def _show_agents(orchestrator: Orchestrator):
    table = Table(box=box.ROUNDED, title="🤖 Agent 列表")
    table.add_column("图标", width=4)
    table.add_column("名称", style="cyan")
    table.add_column("角色", style="green")
    table.add_column("状态", style="yellow")

    icons = {"project_manager": "🎯", "product_manager": "📋", "architect": "🏗️",
             "engineer": "💻", "reviewer": "🔍", "crowd_user": "👥", "memory_keeper": "🧠"}

    for name, agent in orchestrator.agents.items():
        table.add_row(icons.get(name, "🤖"), name, agent.role, "✅ 就绪")

    console.print(table)


def _show_memory(config: DeepForgeConfig):
    store = MemoryStore(config.memory.storage_dir)
    stats = store.stats()

    table = Table(box=box.ROUNDED, title="🧠 记忆库统计")
    table.add_column("类别", style="cyan")
    table.add_column("数量", style="green")

    for cat, count in stats.get("categories", {}).items():
        table.add_row(cat, str(count))
    table.add_row("总计", str(stats.get("total", 0)), style="bold")

    console.print(table)


if __name__ == "__main__":
    main()
