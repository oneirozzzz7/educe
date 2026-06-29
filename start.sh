#!/bin/bash
# Educe — one-command startup
# Usage: ./start.sh

set -e

echo "Starting Educe..."
echo ""

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "Error: Python not found. Install Python 3.10+:"
    echo "  brew install python3"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
echo "  Python: $($PYTHON --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "Error: Node.js not found. Install it:"
    echo "  brew install node"
    exit 1
fi
echo "  Node: $(node --version)"

# Install backend deps if needed
if ! $PYTHON -c "import fastapi" 2>/dev/null; then
    echo "  Installing backend dependencies..."
    $PYTHON -m pip install -e ".[web]" -q
fi

# Install frontend deps if needed
if [ ! -d "web/node_modules" ]; then
    echo "  Installing frontend dependencies..."
    (cd web && npm install --silent)
fi

# Check model config
if [ -z "$EDUCE_API_KEY" ] && [ ! -f .env ]; then
    echo ""
    echo "Warning: No model configured. Create a .env file:"
    echo ""
    echo "  echo 'EDUCE_API_KEY=your-key' > .env"
    echo "  echo 'EDUCE_BASE_URL=https://api.deepseek.com/v1' >> .env"
    echo "  echo 'EDUCE_MODEL=deepseek-chat' >> .env"
    echo ""
    echo "  Then re-run ./start.sh"
    exit 1
fi

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "  Model: ${EDUCE_MODEL:-not specified}"
echo ""

# Start backend
echo "Starting backend (port 7860)..."
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
    echo "Error: Backend failed to start."
    exit 1
fi
echo "  Backend ready (PID: $BACKEND_PID)"

# Start frontend
echo "Starting frontend (port 3001)..."
(cd web && npx next dev -p 3001 > /dev/null 2>&1) &
FRONTEND_PID=$!

sleep 3
echo "  Frontend ready (PID: $FRONTEND_PID)"

echo ""
echo "Educe is running!"
echo ""
echo "  Open: http://localhost:3001"
echo "  Press Ctrl+C to stop"
echo ""

if command -v open &> /dev/null; then
    open "http://localhost:3001"
elif command -v xdg-open &> /dev/null; then
    xdg-open "http://localhost:3001"
fi

# Cleanup on exit
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait $BACKEND_PID
