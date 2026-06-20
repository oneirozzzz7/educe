"""
失败分类器 + 环境缺失自动修复 — Verify-Compile Loop P0

设计（Opus 4.8 确认）：
- 规则层：高置信度环境缺失模式（正则匹配）
- 模型层：不确定的失败交给 LLM 分类（保持现有反思注入）
- 自动修复：只修"缺失"，不修"配置/权限"
- 安全边界：不 sudo、不全局、不盲装、映射表兜底
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("educe.failure_classifier")


# ═══ 失败分类 ═══

@dataclass
class FailureClassification:
    kind: str  # "missing_module" | "missing_command" | "permission" | "unknown"
    detail: str = ""
    auto_fixable: bool = False
    fix_command: str | None = None


# 正则规则（高置信度，只匹配能确定的模式）
FAILURE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"No module named '([\w\.]+)'"), "missing_module"),
    (re.compile(r"ModuleNotFoundError:.*'([\w\.]+)'"), "missing_module"),
    (re.compile(r"ImportError:.*No module named '?([\w\.]+)'?"), "missing_module"),
    (re.compile(r"command not found: (\S+)"), "missing_command"),
    (re.compile(r"(\S+): command not found"), "missing_command"),
    (re.compile(r"Permission denied"), "permission"),
    (re.compile(r"EACCES"), "permission"),
]

# 模块名 → pip 包名映射（import 名 ≠ 包名的常见情况）
MODULE_TO_PACKAGE: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "gi": "PyGObject",
    "serial": "pyserial",
    "usb": "pyusb",
    "wx": "wxPython",
    "Crypto": "pycryptodome",
    "jose": "python-jose",
    "jwt": "PyJWT",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "magic": "python-magic",
    "lxml": "lxml",
    "numpy": "numpy",
    "pandas": "pandas",
    "requests": "requests",
    "flask": "flask",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "sympy": "sympy",
    "torch": "torch",
    "tensorflow": "tensorflow",
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
    "scipy": "scipy",
}

# 可安全安装的命令白名单（missing_command 场景）
COMMAND_INSTALL_MAP: dict[str, str] = {
    "jq": "brew install jq",
    "tree": "brew install tree",
    "wget": "brew install wget",
    "htop": "brew install htop",
}


def classify_failure(stderr: str) -> FailureClassification:
    """对 stderr 进行规则分类"""
    for pattern, kind in FAILURE_PATTERNS:
        match = pattern.search(stderr)
        if match:
            detail = match.group(1) if match.lastindex else ""
            if kind == "missing_module":
                top_module = detail.split(".")[0]
                package = MODULE_TO_PACKAGE.get(top_module, top_module)
                if _is_safe_package_name(package):
                    return FailureClassification(
                        kind=kind,
                        detail=top_module,
                        auto_fixable=True,
                        fix_command=f"pip install {package}",
                    )
                else:
                    return FailureClassification(kind=kind, detail=top_module)
            elif kind == "missing_command":
                cmd = detail
                if cmd in COMMAND_INSTALL_MAP:
                    return FailureClassification(
                        kind=kind, detail=cmd,
                        auto_fixable=True,
                        fix_command=COMMAND_INSTALL_MAP[cmd],
                    )
                else:
                    return FailureClassification(kind=kind, detail=cmd)
            elif kind == "permission":
                return FailureClassification(kind=kind, detail="permission denied")

    return FailureClassification(kind="unknown")


def _is_safe_package_name(name: str) -> bool:
    """基础安全检查：包名不含可疑字符"""
    if not name or len(name) > 50:
        return False
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
        return False
    return True


# ═══ 自动修复执行器 ═══

class AutoFixer:
    """环境缺失自动修复器"""

    MAX_FIXES_PER_LOOP = 3

    def __init__(self):
        self._fix_count = 0
        self._fixed_items: set[str] = set()

    def can_fix(self) -> bool:
        return self._fix_count < self.MAX_FIXES_PER_LOOP

    def already_fixed(self, detail: str) -> bool:
        return detail in self._fixed_items

    async def attempt_fix(self, classification: FailureClassification, cwd: str = ".") -> dict:
        """尝试自动修复。返回 {success, output}"""
        if not classification.auto_fixable or not classification.fix_command:
            return {"success": False, "output": "不可自动修复"}

        if self.already_fixed(classification.detail):
            return {"success": False, "output": f"已尝试修复过 {classification.detail}，仍然失败"}

        if not self.can_fix():
            return {"success": False, "output": f"环境修复次数已达上限({self.MAX_FIXES_PER_LOOP})"}

        cmd = classification.fix_command
        log.info("AutoFixer: attempting '%s'", cmd)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode(errors="replace") + stderr.decode(errors="replace")

            self._fix_count += 1
            self._fixed_items.add(classification.detail)

            if proc.returncode == 0:
                log.info("AutoFixer: success '%s'", cmd)
                return {"success": True, "output": f"✓ 已修复: {cmd}\n{output[:200]}"}
            else:
                log.warning("AutoFixer: failed '%s' (exit %d)", cmd, proc.returncode)
                return {"success": False, "output": f"修复失败 (exit {proc.returncode}): {output[:200]}"}

        except asyncio.TimeoutError:
            self._fix_count += 1
            self._fixed_items.add(classification.detail)
            return {"success": False, "output": f"修复超时: {cmd}"}
        except Exception as e:
            return {"success": False, "output": f"修复异常: {e}"}
