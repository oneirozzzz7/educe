#!/bin/bash
# Educe 一键启动脚本
# 用法：./start.sh

set -e

echo "🚀 启动 Educe..."
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "❌ 未找到 Python。请先安装 Python 3.10+："
    echo "   brew install python3"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
echo "✓ Python: $($PYTHON --version)"

# 检查依赖
if ! $PYTHON -c "import fastapi" 2>/dev/null; then
    echo "📦 安装依赖..."
    $PYTHON -m pip install -e ".[web]" -q
fi

# 检查模型配置
if [ -z "$DEEPFORGE_API_KEY" ] && [ ! -f .env ]; then
    echo ""
    echo "⚠️  未配置模型。请设置环境变量或创建 .env 文件："
    echo ""
    echo "   方式1（DeepSeek，推荐）："
    echo "   export DEEPFORGE_API_KEY=your-key"
    echo "   export DEEPFORGE_BASE_URL=https://api.deepseek.com/v1"
    echo "   export DEEPFORGE_MODEL=deepseek-chat"
    echo ""
    echo "   方式2：创建 .env 文件"
    echo "   echo 'DEEPFORGE_API_KEY=your-key' > .env"
    echo "   echo 'DEEPFORGE_BASE_URL=https://api.deepseek.com/v1' >> .env"
    echo "   echo 'DEEPFORGE_MODEL=deepseek-chat' >> .env"
    echo ""
    echo "   然后重新运行 ./start.sh"
    exit 1
fi

# 加载 .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "✓ 模型: ${DEEPFORGE_MODEL:-未指定}"
echo ""

# 启动后端
echo "🔧 启动后端 (port 7860)..."
$PYTHON -c "
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('DEEPFORGE_API_KEY', '${DEEPFORGE_API_KEY:-}')
os.environ.setdefault('DEEPFORGE_BASE_URL', '${DEEPFORGE_BASE_URL:-}')
os.environ.setdefault('DEEPFORGE_MODEL', '${DEEPFORGE_MODEL:-}')
from deepforge.web.server import run_web
run_web(port=7860)
" &
BACKEND_PID=$!

sleep 2

# 检查后端是否启动成功
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ 后端启动失败。检查日志。"
    exit 1
fi

echo "✓ 后端已启动 (PID: $BACKEND_PID)"

# 打开浏览器
echo ""
echo "✅ Educe 已就绪！"
echo ""
echo "   打开浏览器访问: http://localhost:7860"
echo "   （如果安装了前端: http://localhost:3001）"
echo ""
echo "   按 Ctrl+C 停止"

# 尝试自动打开浏览器
if command -v open &> /dev/null; then
    open "http://localhost:7860"
elif command -v xdg-open &> /dev/null; then
    xdg-open "http://localhost:7860"
fi

# 等待退出
wait $BACKEND_PID
