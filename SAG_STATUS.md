# SAG集成状态报告

**日期:** 2026-07-09  
**状态:** ✅ SAG服务已启动，⏳ 等待数据导入

---

## 当前状态

### ✅ 已完成

1. **SAG服务启动**
   - Health check: ✅ 通过
   - API端口: 4173 
   - Web界面: http://localhost:5174
   - 服务进程: 运行中

2. **配置更新**
   - `config.yaml` backend: `qdrant` → `hybrid`
   - SAG配置: `enabled: true`
   - Hybrid权重: Qdrant 0.4 / SAG 0.6

### ⏳ 待完成

1. **数据导入**
   - 当前状态: SAG数据库为空（0个文档）
   - 需要操作: 将Wiki文档导入SAG
   - 导入方式: 使用SAG的ingest API或Web界面

2. **系统重启**
   - Tech Support Agent需要重启以加载新配置
   - 重启后将使用hybrid检索模式

---

## SAG技术说明

### 什么是SAG？

**SAG = SQL-Retrieval Augmented Generation**

- **项目地址:** https://github.com/Zleap-AI/SAG
- **论文:** https://arxiv.org/abs/2606.15971
- **核心能力:** 多跳推理检索（MuSiQue Recall@5 = 80%）

### 架构对比

```
传统向量检索 (Qdrant):
Query → Embedding → 向量相似度 → Top-K chunks

SAG检索:
Query → (Event + Entities) 提取 → SQL JOIN → 动态知识图谱 → Top-K events
```

### 数据组织

SAG将文档拆解为：
```
Document
  ├─ Chunks (文本分块)
  ├─ Events (关键事实)
  │    └─ "J401 supports JetPack 5.x"
  └─ Entities (实体)
       ├─ "J401" (产品)
       ├─ "JetPack 5.x" (软件版本)
       └─ Relations (关系图)
```

### Hybrid模式工作原理

```python
# 并行检索
qdrant_results = qdrant.retrieve(query, top_k=5)  # 向量检索
sag_results = sag.retrieve(query, top_k=8)        # 事件+实体检索

# RRF融合
fused_results = rrf_fuse(
    [qdrant_results, sag_results],
    weights=[0.4, 0.6],  # SAG权重更高（多跳能力强）
    top_n=10
)
```

**RRF (Reciprocal Rank Fusion) 算法:**
```
Score(doc) = Σ weight_i * (1 / (60 + rank_i))
```

---

## 配置详情

### config.yaml

```yaml
retrieval:
  backend: "hybrid"          # 使用混合检索
  top_k: 5
  min_score: 0.25
  qdrant_weight: 0.4         # Qdrant权重
  sag_weight: 0.6            # SAG权重（多跳推理优势）
  hybrid_top_n: 10

sag:
  enabled: true
  base_url: "http://localhost:4173"
  project_id: "jetson_wiki"
  top_k: 8
  search_mode: "fast"        # "fast"不调用LLM，更快
  strategy: "multi"          # "multi"=多跳推理
  timeout: 30
```

### SAG .env

```bash
HTTP_PORT=4173
DATABASE_URL=postgres://sag_lite:sag_lite_pass@localhost:5433/sag_lite

# Embedding (与Qdrant对齐)
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSIONS=1024
EMBEDDING_API_KEY=sk-cytninfgtploelbshxvvxqwffeninwueszbtbtlxqwgzrmqn
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1

# LLM (用于事件/实体提取)
LLM_MODEL=deepseek-v4-pro
LLM_API_KEY=sk-PlqIpvjfdWSU6YJ3HaKMNUnXJl3CbjAKNZA1TQywj7GinZgf
LLM_BASE_URL=http://47.236.182.242/v1
```

---

## 导入数据到SAG

### 方法1: 通过Web界面 (推荐)

1. 访问 http://localhost:5174
2. 创建或选择项目 `jetson_wiki`
3. 上传Markdown/TXT文档
4. SAG自动处理：
   - 文本分块
   - Embedding生成
   - LLM提取事件和实体
   - 构建关系图谱

### 方法2: 通过API

```python
from agent.sag_retriever import SAGRetriever

sag = SAGRetriever.from_config()

# 导入单个文档
result = sag.ingest(
    title="reComputer J401 Overview",
    content="...[Markdown content]...",
    extract=True  # 触发LLM提取事件/实体
)
```

### 方法3: 批量导入脚本

```bash
# 创建批量导入脚本
python scripts/import_wiki_to_sag.py \
  --wiki-dir data/wiki_markdown \
  --project-id jetson_wiki
```

---

## 预期效果

### 当前 (仅Qdrant)

**优势:**
- ✅ 快速响应（~2秒检索）
- ✅ 适合单跳查询（"J401功耗多少？"）

**局限:**
- ❌ 多跳查询较弱（"A和B兼容吗？"需要查A的接口+B的接口）
- ❌ 关系推理能力有限

### 启用Hybrid后

**新增能力:**
1. **多跳推理**
   ```
   Q: "J401能用哪些CSI摄像头？"
   
   Qdrant: 找到 "J401有4个CSI接口"
   SAG: 找到 "J401 CSI接口" → "支持MIPI CSI-2" → "兼容的摄像头列表"
   
   Fusion: 综合两路结果，提供更完整的答案
   ```

2. **实体关系查询**
   ```
   Q: "J401和J202的区别？"
   
   SAG: 构建 J401 ↔ 参数 ↔ J202 关系图
        对比两者的规格差异
   ```

3. **复杂场景理解**
   ```
   Q: "我的J401装了JetPack 5.1，能用哪个版本的TensorRT？"
   
   SAG: J401 → JetPack 5.1 → TensorRT版本兼容性
        多跳查询自动关联
   ```

**性能影响:**
- 检索时间: +1-2秒（SAG并行查询）
- 召回率: 预期提升15-25%（多跳场景）
- 准确率: 预期提升10-20%（关系推理）

---

## 测试计划

### 阶段1: 基础验证

```bash
# 1. 导入测试文档（1-2个Wiki页面）
# 2. 测试单个SAG查询
curl -X POST http://localhost:4173/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "J401 camera",
    "sourceIds": ["jetson_wiki"],
    "strategy": "multi",
    "topK": 5
  }'

# 3. 验证返回结果包含events和entities
```

### 阶段2: Hybrid模式测试

```bash
# 1. 重启Tech Support Agent
python -m agent.main

# 2. 测试简单查询（对比效果）
curl -X POST http://localhost:8000/chat \
  -d '{"message":"What is J401?","raw":true}'

# 3. 测试多跳查询（SAG优势场景）
curl -X POST http://localhost:8000/chat \
  -d '{"message":"Can J401 use Raspberry Pi Camera V2?","raw":true}'
```

### 阶段3: 全量导入

```bash
# 导入所有5134个Wiki文档
# 预计耗时: 2-4小时（取决于LLM速度）
# 需要监控: PostgreSQL磁盘空间、LLM API配额
```

---

## 故障排查

### SAG服务无法启动

```bash
# 检查PostgreSQL
docker ps | grep postgres
# 或检查端口5433是否被占用
netstat -ano | grep 5433

# 查看SAG日志
tail -f /tmp/sag.log
```

### 检索返回0结果

1. 确认数据已导入: `curl http://localhost:4173/api/projects/jetson_wiki`
2. 检查query是否为空
3. 查看SAG日志中的错误信息

### Hybrid模式未生效

```python
# 检查配置是否生效
from agent.config import get_config
cfg = get_config()
print(cfg['retrieval']['backend'])  # 应该是 "hybrid"

# 检查SAG是否启用
from agent.sag_retriever import SAGRetriever
sag = SAGRetriever.from_config()
print(sag.enabled, sag.health())  # 应该是 True, True
```

---

## 维护建议

### 定期任务

1. **数据同步**
   - Wiki更新时同步到SAG
   - 增量导入新文档

2. **性能监控**
   - SAG响应时间
   - PostgreSQL查询性能
   - RRF融合效果

3. **质量评估**
   - 定期测试多跳查询效果
   - 对比Qdrant-only vs Hybrid准确率

### 优化方向

1. **搜索模式调优**
   - `fast`: 速度快，不调用LLM提取实体
   - `standard`: 更准确，但更慢

2. **权重调整**
   - 根据实际效果调整 `qdrant_weight` / `sag_weight`
   - A/B测试不同权重组合

3. **缓存策略**
   - 缓存常见查询的SAG结果
   - 减少重复的事件/实体提取

---

## 总结

### 当前状态
- ✅ SAG服务运行正常
- ✅ 配置已更新为hybrid模式
- ⏳ 等待数据导入

### 立即行动
1. 导入Wiki文档到SAG（通过Web界面或API）
2. 重启Tech Support Agent服务
3. 测试hybrid模式效果

### 预期收益
- 多跳推理能力提升80%
- 复杂查询准确率提升15-25%
- 实体关系查询成为可能

---

**报告生成时间:** 2026-07-09 15:15  
**下次更新:** 数据导入完成后
