@echo off
REM Seeed Tech Support Agent - Windows 启动脚本

set PROJECT_ROOT=D:\tech-support-agent
cd /d %PROJECT_ROOT%

echo =========================================
echo Seeed Tech Support Agent 启动
echo =========================================

REM ---- 1. 启动 Qdrant (Docker) ----
echo [1/4] 启动 Qdrant...
docker ps -a --filter "name=qdrant" --format "{{.Names}}" | findstr "qdrant" >nul
if %errorlevel% == 0 (
    docker ps --filter "name=qdrant" --format "{{.Names}}" | findstr "qdrant" >nul
    if %errorlevel% == 0 (
        echo   Qdrant 已在运行
    ) else (
        docker start qdrant >nul
        echo   Qdrant 已启动
    )
) else (
    docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
    echo   Qdrant 容器已创建并启动
)
timeout /t 2 >nul

REM ---- 2. 构建索引 ----
echo [2/4] 构建 Wiki 向量索引...
if exist data\index.json (
    echo   index.json 已存在，跳过
) else (
    call python -m pipeline.main
    if not %errorlevel% == 0 (
        echo   Pipeline 失败
        exit /b 1
    )
)

REM ---- 3. 启动 FastAPI Agent ----
echo [3/4] 启动 FastAPI Agent...
start "FastAPI" /B python -m agent.main
echo   FastAPI 已在后台启动（http://localhost:8000）
timeout /t 3 >nul

REM ---- 4. 启动 Streamlit UI ----
echo [4/4] 启动 Streamlit UI...
echo.
echo 服务地址：
echo   - FastAPI:  http://localhost:8000
echo   - Streamlit: http://localhost:8501
echo   - Qdrant:   http://localhost:6333/dashboard
echo.

streamlit run ui\app.py --server.port 8501
