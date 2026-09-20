#!/bin/bash
# stop_microservices.sh - 停止所有微服务

echo "🛑 Stopping DFEcrab Microservices..."

# 停止 Manager Agent Service
if [ -f /tmp/manager_agent.pid ]; then
    PID=$(cat /tmp/manager_agent.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "👔 Stopping Manager Agent Service (PID: $PID)..."
        kill $PID 2>/dev/null || true
        sleep 1
        kill -9 $PID 2>/dev/null || true
        echo "✅ Manager Agent Service stopped"
    else
        echo "👔 Manager Agent Service not running"
    fi
    rm -f /tmp/manager_agent.pid
fi

# 也尝试通过端口杀死进程
for port in 50050; do
    PID=$(lsof -ti:$port 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo "🔍 Killing process on port $port (PID: $PID)..."
        kill -9 $PID 2>/dev/null || true
    fi
done

echo ""
echo "✅ All services stopped"
