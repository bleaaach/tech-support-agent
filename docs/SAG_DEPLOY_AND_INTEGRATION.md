# SAG 部署与接入指南

> 给 tech-support-agent 加多跳 RAG 能力
> 文档版本：v1.0  ·  日期：2026-07-08

---

## 1. 部署 SAG（一次性，约 5-10 分钟）

### 前置条件
- Node.js ≥ 20（已有 v22.22）
- Docker Desktop（已有 29.2）

### 一键部署

```powershell
# 1. 进入 SAG 目录（首次部署）
cd D:\SAG

# 2. 运行部署脚本（启动 pgvector + 安装依赖 + 初始化数据库）
powershell -ExecutionPolicy Bypass -File .\deploy_sag.ps1
```

### 启动服务（二选一）

```powershell
# 方式 A：开发模式（API :4173 + Web :5173，热重载）
cd D:\SAG
npm run dev

# 方式 B：生产模式（API :4173，自带 Web 静态文件）
cd D:\SAG
npm run build
npm start
```

### 验证

```powershell
curl http://localhost:4173/health
# 应返回 {"status":"ok",...}

# 打开 Web UI（开发模式）
# 浏览器访问 http://localhost:5173
```

---

## 2. 数据导入

### Web UI 手动导入（最简单）

1. 打开 `http://localhost:5173`
2. 点击左上 **New Project**，命名为 `jetson_wiki`
3. 进入 **Document** tab → **Add Document**
4. 批量上传 `D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson/**/*.md`
5. 等待处理完成（每个文档会做 chunk → event 抽取 → entity 抽取 → 向量化）

### 命令行脚本导入（可选，后续我会写 pipeline/sag_sync.py）

```bash
curl -X POST http://localhost:4173/ingest \
  -H 'Content-Type: application/json' \
  -d '{"sourceId":"jetson_wiki","title":"<标题>","content":"<整篇 md>","extract":true}'
```

---

## 3. 验证检索效果

```powershell
curl -X POST http://localhost:4173/api/search `
  -H 'Content-Type: application/json' `
  -d '{\"query\":\"reComputer J401 supports which JetPack version?\",\"sourceIds\":[\"jetson_wiki\"],\"strategy\":\"multi\",\"searchMode\":\"fast\",\"topK\":5}'
```

返回里 `results[]` 每条会有 `content / eventId / entities / score` 等字段。

---

## 4. 接入 tech-support-agent（下一步要做的事）

预计 1-2 天工时，分 4 步：

| 步骤 | 文件 | 说明 |
|------|------|------|
| ① | `agent/sag_retriever.py`（新） | 封装 SAG HTTP API，返回 `list[RetrievedChunk]`，与现有 QdrantRetriever 接口兼容 |
| ② | `config.yaml` | 加 `sag:` 段 + `retrieval.backend: "qdrant" / "sag" / "hybrid"` |
| ③ | `pipeline/sag_sync.py`（新） | 增量同步 Jetson Wiki 文档到 SAG |
| ④ | `agent/chat.py` | 加 backend 路由；hybrid 模式用 RRF 融合两边结果 |

**核心设计原则**：完全不改 `generator.py` / `main.py` / `email_renderer.py` / `router.py`，零破坏性接入。

详细方案见：`docs/TECH_ARCHITECTURE_REPORT.md` 第六章与第七章。

---

## 5. 配置对照表（SAG `.env` ↔ tech-support-agent `config.yaml`）

| SAG `.env` 字段 | 值 | 对应 tech-support-agent 字段 |
|----------------|----|------------------------------|
| `DATABASE_URL` | postgres://sag_lite:sag_lite_pass@localhost:5433/sag_lite | （独立部署，无需对齐） |
| `EMBEDDING_BASE_URL` | https://api.siliconflow.cn/v1 | `embedding.siliconflow.base_url` |
| `EMBEDDING_MODEL` | BAAI/bge-m3 | `embedding.siliconflow.model` |
| `EMBEDDING_DIMENSIONS` | 1024 | `embedding.openai_dimensions` / `qdrant.vector_size` |
| `LLM_BASE_URL` | http://47.236.182.242/v1 | `openai.base_url` |
| `LLM_MODEL` | deepseek-v4-pro | `openai.llm_model` |
| `HTTP_PORT` | 4173 | （新加）`sag.base_url` |

---

## 6. 故障排查

### Postgres 起不来
```powershell
docker compose ps
docker compose logs postgres
```
检查端口 5433 是否被占用。

### SAG 启动失败：`relation "xxx" does not exist`
```powershell
npm run db:setup
```
重新跑迁移。

### WebUI 打不开
- 开发模式 `http://localhost:5173`
- 生产模式 `http://localhost:4173`

### 检索没结果
- 检查 WebUI Document tab，文档是否处理完（状态变成 ✓）
- 查看 `LOG_LEVEL=debug` 时控制台日志

---

## 7. 端口占用

| 服务 | 端口 | 备注 |
|------|------|------|
| SAG API | 4173 | HTTP API |
| SAG Web | 5173 | 仅 dev 模式 |
| SAG Postgres | 5433 | pgvector，已错开 5432 |
| SAG MCP | 4174 | MCP stdio/http |
| FastAPI（本项目） | 8000 | 不冲突 |
| Streamlit（本项目） | 8501 | 不冲突 |
| Qdrant | 6333 | 不冲突 |
