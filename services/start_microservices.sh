#!/bin/bash
# start_microservices.sh - 启动所有微服务

set -e

echo "🚀 Starting DFEcrab Microservices..."
echo ""

# 检查 Python 环境
if ! command -v ./venv/bin/python3 &> /dev/null; then
    echo "❌ Python3 not found"
    exit 1
fi

# 检查依赖
echo "📦 Checking dependencies..."
./venv/bin/python3 -c "import fastapi" 2>/dev/null || { echo "❌ fastapi not installed"; exit 1; }
./venv/bin/python3 -c "import httpx" 2>/dev/null || { echo "❌ httpx not installed"; exit 1; }
./venv/bin/python3 -c "import uvicorn" 2>/dev/null || { echo "❌ uvicorn not installed"; exit 1; }
echo "✅ Dependencies OK"
echo ""

# 创建日志目录
mkdir -p services/agent_service/logs
mkdir -p logs

# 停止旧服务
echo "🛑 Stopping old services..."
./services/stop_microservices.sh 2>/dev/null || true
sleep 2
echo ""

# 启动 Manager Agent Service（带自动重启机制）
echo "👔 Starting Manager Agent Service..."
# 注意：Manager Agent 启动时会从 config/gateway.yaml 统一读取配置
(
    while true; do
        ./venv/bin/python3 services/manager_agent/manager_agent_grpc.py
        echo "⚠️ Manager Agent crashed, restarting in 2 seconds..."
        sleep 2
    done
) > logs/manager_agent.log 2>&1 &
MANAGER_PID=$!
echo "$MANAGER_PID" > /tmp/manager_agent.pid
echo "✅ Manager Agent Service started (PID: $MANAGER_PID)"

echo "=========================================="
echo "✅ All services started!"
echo "=========================================="
echo ""
echo "Service Status:"
echo "  🌐 Gateway (if running):     http://localhost:6789"
echo "  👔 Manager Agent:            http://localhost:50050"
echo ""
echo "Health Checks:"
echo "  curl http://localhost:50050/health"
echo ""
echo "Logs:"
echo "  tail -f logs/manager_agent.log"
echo ""
echo "PIDs:"
echo "  Manager Agent:        $MANAGER_PID"
echo ""
echo "Stop all services: ./services/stop_microservices.sh"
echo "=========================================="
