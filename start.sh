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

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "❌ 未找到 Node.js。请先安装："
    echo "   brew install node"
    exit 1
fi
echo "✓ Node: $(node --version)"

# 检查后端依赖
if ! $PYTHON -c "import fastapi" 2>/dev/null; then
    echo "📦 安装后端依赖..."
    $PYTHON -m pip install -e ".[web]" -q
fi

# 检查前端依赖
if [ ! -d "web/node_modules" ]; then
    echo "📦 安装前端依赖..."
    (cd web && npm install --silent)
fi

# 检查模型配置
if [ -z "$EDUCE_API_KEY" ] && [ ! -f .env ]; then
    echo ""
    echo "⚠️  未配置模型。请创建 .env 文件："
    echo ""
    echo "   echo 'EDUCE_API_KEY=your-key' > .env"
    echo "   echo 'EDUCE_BASE_URL=https://api.deepseek.com/v1' >> .env"
    echo "   echo 'EDUCE_MODEL=deepseek-chat' >> .env"
    echo ""
    echo "   然后重新运行 ./start.sh"
    exit 1
fi

# 加载 .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "✓ 模型: ${EDUCE_MODEL:-未指定}"
echo ""

# 启动后端
echo "🔧 启动后端 (port 7860)..."
$PYTHON -c "
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('EDUCE_API_KEY', '${EDUCE_API_KEY:-}')
os.environ.setdefault('EDUCE_BASE_URL', '${EDUCE_BASE_URL:-}')
os.environ.setdefault('EDUCE_MODEL', '${EDUCE_MODEL:-}')
from educe.web.server import run_web
run_web(port=7860)
" &
BACKEND_PID=$!

sleep 2

if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ 后端启动失败。"
    exit 1
fi
echo "✓ 后端已启动 (PID: $BACKEND_PID)"

# 启动前端
echo "🎨 启动前端 (port 3001)..."
(cd web && npx next dev -p 3001 > /dev/null 2>&1) &
FRONTEND_PID=$!

sleep 3
echo "✓ 前端已启动 (PID: $FRONTEND_PID)"

# 打开浏览器
echo ""
echo "✅ Educe 已就绪！"
echo ""
echo "   浏览器访问: http://localhost:3001"
echo "   按 Ctrl+C 停止"
echo ""

if command -v open &> /dev/null; then
    open "http://localhost:3001"
elif command -v xdg-open &> /dev/null; then
    xdg-open "http://localhost:3001"
fi

# Ctrl+C 时清理
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait $BACKEND_PID
