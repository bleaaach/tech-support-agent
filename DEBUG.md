## Seeed Tech Support Agent - 本地调试

### 快速启动

```powershell
# PowerShell
cd D:/tech-support-agent
./start.ps1
```

或 CMD：

```cmd
cd /d D:\tech-support-agent
start.bat
```

### 分步调试

#### 1. 启动 Qdrant

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

确认 Qdrant 状态：

```bash
curl http://localhost:6333/healthz
# 返回: {"title":"qdrant - vector search engine","version":"1.x.x",...}
```

#### 2. 构建索引（一次性）

```bash
cd D:/tech-support-agent
python -m pipeline.main
```

预期输出：
```
[INFO] Parsing docs from: D:/wiki-documents/knowledge-base/jetson/docs
[INFO] Parsed XXX chunks from docs
[INFO] Generating embeddings...
Embedding: 100%|████████████████████| XXX/XXX
[INFO] Indexed XXX chunks to Qdrant
[INFO] Saved index.json: D:/tech-support-agent/data/index.json
```

#### 3. 启动 FastAPI Agent

```bash
python -m agent.main
```

或带 reload：

```bash
uvicorn agent.main:app --host 0.0.0.0 --port 8000 --reload
```

测试 chat 接口：
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "reComputer J401 supports which JetPack version?",
    "category": "reComputer_Jetson_Series/reComputer_J401B"
  }'
```

#### 4. 启动 Streamlit UI

```bash
streamlit run ui/app.py --server.port 8501
```

访问 http://localhost:8501

### 健康检查

```bash
curl http://localhost:8000/health
```

返回：
```json
{"status": "healthy", "chunks_indexed": 1234}
```

### 查看 Qdrant 数据

打开 http://localhost:6333/dashboard 看 Collection `jetson_wiki` 中的数据。

### 常见问题

#### Q: Pipeline 报错 "No chunks parsed"

检查 Wiki 路径：
```bash
ls D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson
```

修改 `config.yaml` 中的 `jetson_docs_path` 字段。

#### Q: Qdrant 连接失败

```bash
docker ps | grep qdrant    # 确认容器运行
docker logs qdrant         # 查看日志
```

#### Q: OpenAI API 调用失败

1. 检查 `.env` 中的 `OPENAI_API_KEY`
2. 确认网络可访问 `api.openai.com`
3. 检查用量额度

#### Q: Embedding 维度不匹配

确保 `config.yaml` 中 `qdrant.vector_size` 与 `embedder.model` 的输出维度一致：
- `text-embedding-3-small` → 1536
- `text-embedding-3-large` → 3072

#### Q: 重置数据

```bash
# 删除 Qdrant collection（重新构建时会自动重建）
curl -X DELETE http://localhost:6333/collections/jetson_wiki

# 删除本地 index.json
rm D:/tech-support-agent/data/index.json

# 重新构建
python -m pipeline.main
```

### 测试场景

#### 1. 参数查询
```
Q: reComputer J401 的内存有多大？
预期：列出 RAM 规格，文档来源指向 reComputer J401B 页面
```

#### 2. 兼容性问题
```
Q: J401 能用 Orin NX 还是只能用 Orin Nano？
预期：列表展示兼容的 Module 型号
```

#### 3. 故障排查
```
Q: 设备刷机失败，停留在 force recovery mode 怎么办？
预期：分步骤排查指引 + 追问建议
```

#### 4. 操作指引
```
Q: 怎么用 SDK Manager 刷 JetPack 6？
预期：分步骤操作指引
```

#### 5. 转接
```
Q: 多少钱一台？找谁买？
预期：礼貌转销售
```

### 调试技巧

#### 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### 直接测试检索

```python
from agent.retriever import QdrantRetriever
r = QdrantRetriever.from_config()
chunks = r.retrieve("J401 JetPack")
for c in chunks:
    print(c.title, c.score, c.wiki_url)
```

#### 跳过邮件模板

调用 API 时加 `raw=True`：
```json
{"message": "...", "raw": true}
```
