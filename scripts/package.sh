#!/bin/bash
# DFEcrab 打包脚本
# 将运行环境、技能打包为可分发版本

set -e

VERSION=${1:-"1.0.0"}
PACKAGE_NAME="dfecrab-${VERSION}"
OUTPUT_DIR="./dist/${PACKAGE_NAME}"

echo "========================================"
echo "DFEcrab 打包脚本"
echo "版本: ${VERSION}"
echo "========================================"

# 创建输出目录
mkdir -p "${OUTPUT_DIR}"

# 复制必要文件
echo "📦 复制运行时文件..."
mkdir -p "${OUTPUT_DIR}/runtime"

# Python 运行时（精简版）
pip freeze > "${OUTPUT_DIR}/runtime/requirements.txt"

# 复制已安装的包（wheel 格式）
mkdir -p "${OUTPUT_DIR}/runtime/packages"
pip download -r "${OUTPUT_DIR}/runtime/requirements.txt" -d "${OUTPUT_DIR}/runtime/packages" --no-deps || true

# 复制配置
echo "📋 复制配置文件..."
cp -r ./agents "${OUTPUT_DIR}/"
cp -r ./config "${OUTPUT_DIR}/" 2>/dev/null || true
cp -r ./data/shared_memory "${OUTPUT_DIR}/" 2>/dev/null || true

# 复制技能
echo "🎯 复制技能..."
mkdir -p "${OUTPUT_DIR}/skills"
cp -r ./skills/* "${OUTPUT_DIR}/skills/"

# 复制启动脚本
echo "🚀 复制启动脚本..."
cp ./dfecrab "${OUTPUT_DIR}/" 2>/dev/null || true
cp ./scripts/start_gateway_grpc.py "${OUTPUT_DIR}/scripts/" 2>/dev/null || true

# 复制文档
echo "📚 复制文档..."
mkdir -p "${OUTPUT_DIR}/docs"
cp -r ./docs/* "${OUTPUT_DIR}/docs/"

# 创建 README
cat > "${OUTPUT_DIR}/README.md" << 'EOF'
# DFEcrab 运行环境包

这是一个完整的 DFEcrab 运行环境，解压后即可运行。

## 包含内容

- Python 运行时环境
- 预安装的依赖包
- 所有内置技能
- 默认配置

## 快速开始

```bash
# 1. 安装依赖
pip install -r runtime/requirements.txt

# 2. 启动服务（gRPC版本）
python scripts/start_gateway_grpc.py

# 3. 访问服务
# HTTP接口: http://localhost:6789
# WebSocket: ws://localhost:6789/ws
```

## 目录结构

```
dfecrab/
├── runtime/          # Python 运行时和依赖
│   ├── requirements.txt
│   └── packages/
├── skills/           # 所有技能
├── agents/           # Agent配置文件
├── data/             # 数据存储
├── config/           # 全局配置
├── scripts/          # 启动脚本
└── docs/             # 文档
```

## 注意事项

- 首次运行需要配置 LLM 模型（修改 config/dfecrab.json）
- Agent私有记忆存储在 agents/{agent_id}/memory.json
- 全局共享记忆存储在 data/shared_memory/
- 日志输出到 logs/ 目录（自动保留最近7天）
EOF

# 创建压缩包
echo "📦 创建压缩包..."
cd ./dist
tar -czvf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}"
rm -rf "${PACKAGE_NAME}"

echo "========================================"
echo "✅ 打包完成！"
echo "📦 输出文件: ./dist/${PACKAGE_NAME}.tar.gz"
echo "========================================"
ls -lh "./dist/${PACKAGE_NAME}.tar.gz"