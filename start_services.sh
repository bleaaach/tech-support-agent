#!/bin/bash
# 启动 Tech Support Agent 所有服务

# 加载环境变量
if [ -f .env ]; then
    echo "🔧 加载环境变量..."
    export $(cat .env | grep -v '^#' | xargs)
    echo "✅ 环境变量加载完成"
else
    echo "❌ .env 文件不存在！"
    exit 1
fi

# 检查关键环境变量
echo ""
echo "📋 环境变量检查："
echo "  OPENAI_API_KEY: ${OPENAI_API_KEY:0:20}..."
echo "  OPENAI_BASE_URL: $OPENAI_BASE_URL"
echo "  OPENAI_LLM_MODEL: $OPENAI_LLM_MODEL"
echo ""

# 启动 FastAPI 后端
echo "🚀 启动 FastAPI 后端（端口 8000）..."
python -m agent.main &
BACKEND_PID=$!
echo "  PID: $BACKEND_PID"

# 等待后端启动
sleep 3

# 启动 Streamlit 前端
echo "🚀 启动 Streamlit 前端（端口 8501）..."
streamlit run ui/app.py --server.port 8501 &
FRONTEND_PID=$!
echo "  PID: $FRONTEND_PID"

echo ""
echo "✅ 所有服务已启动！"
echo ""
echo "📍 访问地址："
echo "  - Web UI: http://localhost:8501"
echo "  - API: http://localhost:8000"
echo "  - API 文档: http://localhost:8000/docs"
echo ""
echo "⏹️  停止服务："
echo "  kill $BACKEND_PID $FRONTEND_PID"
echo ""

# 等待用户中断
wait
