# AGENTS.md - Tech Support Agent 开发指引

## 本地部署（推荐，不再用 docker）

```bash
./deploy-local.sh setup   # 首次：装依赖（CPU-only torch）
./deploy-local.sh start   # 启动 FastAPI (8000) + Streamlit (8501)
./deploy-local.sh stop
./deploy-local.sh status
./deploy-local.sh logs [fastapi|streamlit]
./deploy-local.sh restart
```

**关键点**：
- 用 `uv` 管理 venv，Python 3.11
- 8000/8501 端口被占 → 检查是不是 docker tech-agent 残留：`docker stop tech-agent && docker rm -f tech-agent`
- 依赖装不动 → 看 `requirements.txt` 里的 `--extra-index-url https://download.pytorch.org/whl/cpu` 必须保留

## Docker 部署（已弃用，遗留路径）

旧脚本 `deploy.sh` 还在但别用：镜像构建 OOM、sentence-transformers 拉 CUDA 依赖超时。需要 docker 时只跑辅助服务：
```bash
docker compose up -d qdrant postgres sag   # 三个辅助容器
# tech-agent 用 ./deploy-local.sh start 本地起
```

## 项目结构

- `agent/` - FastAPI 后端
- `ui/` - Streamlit 前端 (`ui/app.py`)
- `pipeline/` - 数据处理
- `.venv/` - Python 3.11 虚拟环境（gitignore）
- `.run/` - PID 文件
- `logs/` - 服务日志

## 环境变量

`.env` 必填 `OPENAI_API_KEY`（脚本会检查）。**不要提交 .env 到 git**。

## 常见坑

- **sentence-transformers 拉 CUDA 工具链超时** → 必须用 `--extra-index-url https://download.pytorch.org/whl/cpu`，单装 torch 别用 `unsafe-best-match`
- **8000 端口占用** → 优先查 docker 容器
- **streamlit 启动慢** → 首次加载要 10-15 秒正常
- **API 不通但 curl 返回 000** → 用 `./deploy-local.sh logs fastapi` 看实际错误