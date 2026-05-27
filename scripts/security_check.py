#!/usr/bin/env python3
"""
DeepForge 安全检查脚本
在git commit前运行，检测代码中是否包含敏感信息

用法:
    python scripts/security_check.py          # 检查所有待提交文件
    python scripts/security_check.py --all    # 检查所有文件
"""

import re
import sys
import subprocess
from pathlib import Path

SENSITIVE_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', 'API Key (sk-xxx)'),
    (r'pk-[a-f0-9\-]{30,}', 'Private Key (pk-xxx)'),
    (r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID格式密钥'),
    (r'Bearer\s+[a-zA-Z0-9\-_.]{20,}', 'Bearer Token'),
    (r'api[_-]?key\s*[=:]\s*["\'][^"\']{10,}["\']', '硬编码API Key'),
    (r'password\s*[=:]\s*["\'][^"\']+["\']', '硬编码密码'),
    (r'(gpt-proxy|model-api|cloud-provider)\.jd\.com', 'JD内网地址'),
    (r'YANXI_API_KEY', '言犀API Key引用'),
    (r'[A-Za-z0-9+/]{40,}={0,2}', '可能的Base64编码密钥（长度>40）'),
]

SAFE_PATTERNS = [
    r'your-api-key',
    r'sk-xxx',
    r'pk-xxx',
    r'example',
    r'placeholder',
    r'DEEPSEEK_API_KEY',
    r'QWEN_API_KEY',
    r'GLM_API_KEY',
    r'KIMI_API_KEY',
    r'OPENROUTER_API_KEY',
    r'DEEPFORGE_API_KEY',
    r'os\.environ',
]

SKIP_EXTENSIONS = {'.pyc', '.pyo', '.so', '.dylib', '.png', '.jpg', '.gif', '.ico', '.woff', '.ttf'}
SKIP_DIRS = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.deepforge'}
SKIP_FILES = {'security_check.py', 'pre-commit'}


def is_safe_context(line: str) -> bool:
    for safe in SAFE_PATTERNS:
        if re.search(safe, line):
            return True
    return False


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    if filepath.suffix in SKIP_EXTENSIONS:
        return []
    if any(d in filepath.parts for d in SKIP_DIRS):
        return []
    if filepath.name in SKIP_FILES:
        return []

    issues = []
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []

    for line_num, line in enumerate(content.split('\n'), 1):
        if is_safe_context(line):
            continue
        for pattern, desc in SENSITIVE_PATTERNS:
            if re.search(pattern, line):
                issues.append((line_num, desc, line.strip()[:80]))
                break

    return issues


def get_staged_files() -> list[Path]:
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
            capture_output=True, text=True, check=True
        )
        return [Path(f) for f in result.stdout.strip().split('\n') if f]
    except subprocess.CalledProcessError:
        return []


def main():
    check_all = '--all' in sys.argv
    root = Path(__file__).parent.parent

    if check_all:
        files = [p for p in root.rglob('*') if p.is_file()]
        print(f"🔍 全量安全扫描: {len(files)} 个文件...")
    else:
        files = get_staged_files()
        if not files:
            print("✅ 无待提交文件")
            return 0
        files = [root / f for f in files]
        print(f"🔍 扫描待提交文件: {len(files)} 个...")

    total_issues = 0
    for filepath in files:
        if not filepath.exists():
            continue
        issues = check_file(filepath)
        if issues:
            total_issues += len(issues)
            print(f"\n❌ {filepath.relative_to(root)}")
            for line_num, desc, preview in issues:
                print(f"   L{line_num}: [{desc}] {preview}")

    if total_issues > 0:
        print(f"\n🚫 发现 {total_issues} 个安全风险！请修复后再提交。")
        print("   提示: 使用环境变量替代硬编码密钥")
        return 1
    else:
        print("✅ 安全检查通过，未发现敏感信息。")
        return 0


if __name__ == '__main__':
    sys.exit(main())
