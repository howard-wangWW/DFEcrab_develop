#!/bin/bash
# 启动知识库API服务 (后台运行)

cd /home/e8900/DFEcrab
source venv/bin/activate

# 检查是否已运行
PID_FILE="/tmp/knowledge_api.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p $OLD_PID > /dev/null 2>&1; then
        echo "⚠️ 知识库API已在运行 (PID: $OLD_PID)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# 创建日志目录
mkdir -p logs/knowledge

# 启动服务
nohup python scripts/knowledge_api.py --host 0.0.0.0 --port 6788 > logs/knowledge/knowledge_api.log 2>&1 &
echo $! > "$PID_FILE"

echo "✅ 知识库API已启动 (PID: $(cat $PID_FILE))"
echo "   http://localhost:6788/knowledge/health"
echo "   http://localhost:6788/docs"
