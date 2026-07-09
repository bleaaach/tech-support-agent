# SAG 接入改动汇总

> 日期：2026-07-08
> 目的：把 SAG (SQL-Retrieval Augmented Generation) 作为多跳检索后端接入现有架构
> 范围：并行接入，零破坏性，可一键切换 backend

---

## 一、改动文件清单

| 文件 | 类型 | 状态 | 说明 |
|------|------|------|------|
| `D:/SAG/` | 新目录 | ✅ 已克隆 | SAG 服务端代码 |
| `D:/SAG/.env` | 新文件 | ✅ 已配置 | 复用现有 OpenAI/SiliconFlow key |
| `D:/SAG/docker-compose.yml` | 微调 | ✅ | Postgres 端口 5432 → 5433 |
| `D:/SAG/deploy_sag.ps1` | 新文件 | ✅ | 一键部署脚本（启动 pgvector + npm install + db:setup） |
| `agent/sag_retriever.py` | 新文件 | ✅ | SAG HTTP 客户端 + RRF 融合算法 |
| `pipeline/sag_sync.py` | 新文件 | ✅ | Jetson Wiki → SAG 批量同步脚本（支持增量） |
| `tests/test_sag_retriever.py` | 新文件 | ✅ | 单元测试，**18 个用例全通过** |
| `agent/chat.py` | 修改 | ✅ | 加 backend 路由 + RRF 融合 |
| `config.yaml` | 修改 | ✅ | 加 `sag:` 段 + `retrieval.backend` 字段 |
| `docs/SAG_DEPLOY_AND_INTEGRATION.md` | 新文档 | ✅ | 部署与接入指南 |

**未改动（保持兼容）**：
- `agent/generator.py` —— 入参形状不变
- `agent/main.py` —— HTTP API 不变
- `agent/email_renderer.py` —— 来源展示不变
- `agent/router.py` —— 分类逻辑不变
- `agent/retriever.py` —— Qdrant 检索器原封不动
- `pipeline/build_email_corpus.py` —— 历史邮件语料构建原封不动

---

## 二、关键设计

### 1. 三种 backend 模式

```yaml
retrieval:
  backend: "qdrant"      # 仅 Qdrant（默认，单跳，最快）
  # backend: "sag"       # 仅 SAG（多跳，需要 SAG 服务在线）
  # backend: "hybrid"    # Qdrant + SAG RRF 融合（推荐生产用）
```

切换仅改一行配置，不需要改代码。

### 2. RRF 融合（Reciprocal Rank Fusion）

`SAGRetriever.rrf_fuse()` 函数把两路检索结果按排名融合：

```
RRF_score(d) = sum_i weight_i * 1 / (k + rank_i(d))
```

参数：
- `k = 60`（论文默认）
- `weights = [qdrant_weight, sag_weight]`（默认 0.4 / 0.6）

### 3. 优雅降级

| 场景 | 行为 |
|------|------|
| SAG 不可达 | `retriever.retrieve()` 返回 `[]`，日志 warning，不抛异常 |
| `sag.enabled = false` | SAG 实例化为 enabled 状态，`retrieve()` 立即返回 `[]`，零网络开销 |
| SAG 返回字段缺失 | `_hit_to_chunk()` 内部容错，缺字段用空字符串 |
| `backend = "hybrid"` 但 SAG 不可达 | 自动 fall back 到 Qdrant 单路 |

---

## 三、验证结果

### 单元测试
```
$ python -m tests.test_sag_retriever
Ran 18 tests in 6.160s
OK
```

覆盖：
- RRF 融合（7 个用例）：空输入、单路、双路无重叠、双路重叠、权重、top_n、score 替换
- 接口兼容（5 个用例）：返回类型、disabled、不可达、health
- HTTP mock（3 个用例）：results 解析、health、ingest
- 字段容错（2 个用例）：最少字段、完整字段
- 配置读取（1 个用例）：from_config

### 冒烟测试
```
config backend = qdrant
config sag.enabled = False
backend: qdrant
sag: None
```
默认行为完全保持，与未改动前一致。

### 模块加载
```
OK: <class 'agent.chat.TechSupportChat'>
    <class 'agent.sag_retriever.SAGRetriever'>
    <function rrf_fuse at 0x...>
```

---

## 四、上线步骤（待 Docker Desktop 启动后）

### 步骤 1：手动启动 Docker Desktop
打开 Docker Desktop 图标 → 等待底部状态变绿。

### 步骤 2：跑部署脚本
```powershell
cd D:\SAG
powershell -ExecutionPolicy Bypass -File .\deploy_sag.ps1
```
预计 3-5 分钟（npm install 占大头）。

### 步骤 3：启动 SAG 服务
```powershell
cd D:\SAG
npm run dev          # 开发模式（API :4173 + Web :5173）
```

### 步骤 4：检查健康
```powershell
cd D:\tech-support-agent
python -m pipeline.sag_sync --check
```
应输出 `✓ SAG 健康`。

### 步骤 5：导入 171 篇文档
```powershell
python -m pipeline.sag_sync --full
```
预计 5-15 分钟（SAG 会做 chunk + event 抽取 + embedding，每篇约 2-5 秒）。

### 步骤 6：开启 SAG（hybrid 模式）
编辑 `config.yaml`：
```yaml
sag:
  enabled: true          # ← 改这里
retrieval:
  backend: "hybrid"      # ← 改这里
```

### 步骤 7：重启 FastAPI
```powershell
# 停掉旧进程，启动新的
uvicorn agent.main:app --reload --port 8000
```

### 步骤 8：A/B 测试
准备 20 条测试问题，分别在 qdrant / hybrid 模式下对比：
- 召回率（Hit@3 / Recall@5）
- 延迟（latency_ms）
- 答案质量（人工判断）

---

## 五、故障排查

### 部署失败
```powershell
docker compose ps                 # 容器状态
docker compose logs postgres      # Postgres 日志
```

### SAG 启动失败
```powershell
cd D:\SAG
cat .env                          # 检查配置
npm run typecheck                 # 编译检查
```

### 检索没结果
- 检查 WebUI Document tab，文档是否处理完
- 用 `--check` 参数验证 SAG 健康
- 临时把 `search_mode` 改成 `"standard"`（更慢但更准）

### chat.py 报 backend 错误
确认 `config.yaml` 的 `retrieval.backend` 是 `"qdrant"` / `"sag"` / `"hybrid"` 之一。

---

## 六、性能与成本

### SAG 服务资源占用（参考）
- PostgreSQL (pgvector): ~200 MB 内存
- Node API + Web: ~150 MB 内存
- 磁盘：171 篇文档 ≈ 50 MB（含 chunk + event + entity + vector）

### Embedding 成本
- SAG 用 SiliconFlow bge-m3（与你现有 Qdrant 索引一致）：~$0.001/1M tokens
- 171 篇文档一次性导入 ≈ $0.0005

### 查询延迟
- SAG /api/search：~500-1500ms（论文报告 < 2s）
- RRF 融合：~5ms（纯内存操作）
- Hybrid 模式总延迟：max(Qdrant, SAG) + 5ms ≈ 1.5s

### 收益
- 多跳问题召回率：MuSiQue 上 SAG Recall@5 = 80%，Qdrant 单向量 ~50%（估算）
- 对 Jetson Wiki 的"刷机失败"类跨多文档问题，hybrid 模式预计能显著提升回答质量

---

## 七、下一步

1. **A/B 测试**：准备 20-50 条真实工单问题对比 qdrant vs hybrid
2. **完整 FAQ 模板化**：Stage 2 任务，把 21 篇 FAQ 转成结构化问答对导入 SAG
3. **飞书机器人接入**：MCP 模式下 SAG 可直接作为工具供飞书机器人调用
4. **多模态**：Stage 3，原理图图片理解（独立路径，不影响 SAG）

---

*文档由 Cursor AI Agent 生成，基于 2026-07-08 SAG v0.1.0 接入实现*