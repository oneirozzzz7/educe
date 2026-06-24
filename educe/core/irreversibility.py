"""Irreversibility Gate — 框架唯一的硬逻辑。

不可逆动作前暂停。不判断"危不危险"，只判断"做了能否撤回"。

两层定义：
1. 系统级不可逆（物理事实）：文件批量删除、进程 kill、对外写入
2. 用户声明的边界（来自 AssetStore，未来扩展）
"""

import re

# 物理不可逆模式 — 仅覆盖"做了就无法撤回"的操作
_IRREVERSIBLE_SHELL_PATTERNS = [
    # rm 带 -r/-f 或多文件（单个 rm file.txt 是可逆的，用 trash 或 backup 可恢复，
    # 但 rm -rf 或 rm -r dir/ 是真正不可逆的）
    re.compile(r"rm\s+.*(-r|-f|--force|--recursive)"),
    # 数据库破坏性 DDL
    re.compile(r"(?i)\b(drop|truncate)\s+(table|database|schema|index)\b"),
    # kill/pkill 进程
    re.compile(r"^\s*(kill|pkill|killall)\s+"),
    # 格式化/覆写磁盘
    re.compile(r"^\s*(mkfs|dd\s+.*of=|format)\b"),
    # git 不可逆操作
    re.compile(r"git\s+(push\s+.*--force|reset\s+--hard|clean\s+-f)"),
]


def is_irreversible_shell(cmd: str) -> bool:
    """判断 shell 命令是否物理不可逆。"""
    cmd = cmd.strip()
    return any(p.search(cmd) for p in _IRREVERSIBLE_SHELL_PATTERNS)


def is_irreversible(action) -> bool:
    """判断一个 action 是否不可逆，需要暂停确认。

    仅基于物理事实，不做主观判断。
    """
    if action.type == "shell":
        import json
        cmd = action.params.strip()
        try:
            parsed = json.loads(cmd)
            cmd = parsed.get("cmd") or parsed.get("command") or cmd
        except (ValueError, TypeError, AttributeError):
            pass
        return is_irreversible_shell(cmd)

    # 未来扩展：用户声明的边界资产
    return False
