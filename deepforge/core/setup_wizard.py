"""
DeepForge 零配置引导模块
首次使用时自动引导用户完成模型配置，做到真正的傻瓜式操作
"""
from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box

console = Console()

PROVIDERS = [
    {
        "key": "deepseek",
        "name": "DeepSeek",
        "desc": "性价比最高，推荐首选",
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "signup_url": "https://platform.deepseek.com",
        "price": "约 ¥0.001/千token",
    },
    {
        "key": "qwen",
        "name": "通义千问 (Qwen)",
        "desc": "阿里云，国内访问快",
        "env": "QWEN_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "signup_url": "https://dashscope.console.aliyun.com",
        "price": "有免费额度",
    },
    {
        "key": "glm",
        "name": "智谱 GLM",
        "desc": "免费额度多，适合试用",
        "env": "GLM_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "signup_url": "https://open.bigmodel.cn",
        "price": "glm-4-flash 免费",
    },
    {
        "key": "kimi",
        "name": "Moonshot (Kimi)",
        "desc": "长上下文支持好",
        "env": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "signup_url": "https://platform.moonshot.cn",
        "price": "有免费额度",
    },
    {
        "key": "ollama",
        "name": "Ollama (本地)",
        "desc": "完全免费，离线运行，需先安装Ollama",
        "env": "",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "signup_url": "https://ollama.ai",
        "price": "免费（本地GPU）",
    },
]


def detect_existing_config() -> dict | None:
    """检测已有的API Key配置"""
    for p in PROVIDERS:
        if p["env"] and os.environ.get(p["env"]):
            return p
    config_paths = [
        Path.cwd() / "educe.yaml",
        Path.home() / ".educe" / "config.yaml",
    ]
    for path in config_paths:
        if path.exists():
            return {"key": "file", "path": str(path)}
    return None


def run_setup_wizard() -> dict:
    """运行交互式配置引导，返回配置字典"""
    console.print()
    console.print(Panel(
        "[bold cyan]DeepForge 首次配置向导[/bold cyan]\n\n"
        "[dim]只需3步，30秒完成配置。之后不会再弹出。[/dim]",
        border_style="cyan",
        padding=(1, 2),
    ))

    console.print("\n[bold]第1步：配置模型接入[/bold]\n")
    console.print("[dim]DeepForge 支持所有 OpenAI 兼容协议的模型API。[/dim]")
    console.print("[dim]以下是常见的提供商，你也可以选择「自定义」接入任意兼容API。[/dim]\n")

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("#", style="bold", width=3)
    table.add_column("提供商", style="cyan", width=20)
    table.add_column("协议", width=20)
    table.add_column("说明", width=25)

    for i, p in enumerate(PROVIDERS, 1):
        table.add_row(str(i), p["name"], "OpenAI兼容", p["desc"])
    table.add_row(str(len(PROVIDERS) + 1), "自定义API", "OpenAI兼容", "任意兼容OpenAI协议的API")

    console.print(table)

    choice = Prompt.ask(
        "\n选择提供商",
        choices=[str(i) for i in range(1, len(PROVIDERS) + 2)],
        default="1",
    )

    choice_idx = int(choice) - 1
    if choice_idx >= len(PROVIDERS):
        provider = {
            "key": "custom",
            "name": "自定义",
            "desc": "自定义OpenAI兼容API",
            "env": "DEEPFORGE_API_KEY",
            "base_url": "",
            "model": "",
            "signup_url": "",
            "price": "",
        }
        provider["base_url"] = Prompt.ask("API Base URL", default="https://api.example.com/v1")
        provider["model"] = Prompt.ask("模型名称", default="gpt-3.5-turbo")
    else:
        provider = PROVIDERS[choice_idx]

    console.print(f"\n[green]✓[/green] 已选择: [bold]{provider['name']}[/bold]")

    if provider["key"] == "ollama":
        console.print("\n[bold]第2步：确认Ollama已运行[/bold]")
        console.print(f"[dim]请确保已安装并启动 Ollama: {provider['signup_url']}[/dim]")
        console.print(f"[dim]并已下载模型: ollama pull {provider['model']}[/dim]")
        api_key = "ollama"
    else:
        console.print(f"\n[bold]第2步：输入API Key[/bold]")
        console.print(f"[dim]获取地址: {provider['signup_url']}[/dim]")
        api_key = Prompt.ask("API Key", password=True)

        if not api_key.strip():
            console.print("[red]API Key不能为空[/red]")
            return run_setup_wizard()

    console.print(f"\n[bold]第3步：保存配置[/bold]")
    save_to_env = Confirm.ask("保存到环境变量文件(.env)？", default=True)

    config = {
        "provider": provider["key"],
        "model": provider["model"],
        "api_key": api_key.strip(),
        "base_url": provider["base_url"],
    }

    if save_to_env:
        _save_env_file(provider, api_key.strip())

    os.environ["DEEPFORGE_API_KEY"] = config["api_key"]
    os.environ["DEEPFORGE_BASE_URL"] = config["base_url"]
    os.environ["DEEPFORGE_MODEL"] = config["model"]
    if provider["env"]:
        os.environ[provider["env"]] = config["api_key"]

    console.print("\n[bold green]✅ 配置完成！[/bold green]")
    console.print(f"[dim]模型: {config['model']} @ {config['base_url']}[/dim]\n")

    return config


def _save_env_file(provider: dict, api_key: str) -> None:
    """保存到.env文件"""
    env_path = Path.cwd() / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().strip().split("\n")

    new_lines = [l for l in lines if not l.startswith(f"{provider['env']}=") and not l.startswith("DEEPFORGE_")]
    if provider["env"]:
        new_lines.append(f"{provider['env']}={api_key}")
    new_lines.append(f"DEEPFORGE_BASE_URL={provider['base_url']}")
    new_lines.append(f"DEEPFORGE_MODEL={provider['model']}")

    env_path.write_text("\n".join(new_lines) + "\n")
    console.print(f"[dim]已保存到 {env_path}[/dim]")


def ensure_configured() -> bool:
    """确保已配置。未配置则自动启动引导。返回True=已配置"""
    existing = detect_existing_config()
    if existing:
        return True

    console.print("[yellow]⚠ 未检测到模型配置[/yellow]")
    run_setup_wizard()
    return True


def load_env_file() -> None:
    """加载.env文件到环境变量"""
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
