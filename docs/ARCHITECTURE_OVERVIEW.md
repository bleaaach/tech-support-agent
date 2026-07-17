# Jetson 技术支持 Agent — 架构整理与 RAG 方案对比（交付文档）

> 文档版本：v2.0（重写版）
> 日期：2026-07-13
> 基线代码：`tech-support-agent/`（commit on 2026-07-10）
> 目的：用「当前实际架构」替换上一版（`TECH_ARCHITECTURE_REPORT.md` v1.0, 2026-07-07）中的过期选型描述；并系统对比主流 RAG 形式，给出后续演进路径。

---

## 一、TL;DR（结论先行）

| 决策点 | 上一版报告（v1.0, 2026-07-07）| 当前实际 / 本次结论（v2.0） |
|---|---|---|
| 检索范式 | "MVP 用 Advanced RAG，生产再上 Agentic" | 已经是 **Agentic RAG**（LangGraph 工作流已上线），混合 **Qdrant 向量 + 历史回复 RAG** |
| SAG（SQL 超图谱） | "2026 太新，先观望" | 代码已集成 `agent/sag_retriever.py` + `pipeline/sag_sync.py`，生产开关为 `sag.enabled: false` / `backend: qdrant`，**架构上已就绪，待切换** |
| 向量库 | Qdrant（已确认） | **Qdrant**（1024 维 BGE-M3 / SiliconFlow），未变 |
| Embedding | OpenAI text-embedding-3-small Batch | 实际已切到 **SiliconFlow BAAI/bge-m3**（性价比更高），OpenAI 仍保留为备选 |
| LLM | GPT-4o-mini | 实际走 **OpenAI 兼容端点**（`OPENAI_BASE_URL`），默认模型 `glm-5.2`，可通过 `OPENAI_LLM_MODEL` 切换 deepseek-v4-pro / gpt-5.5 等 |
| Agent 入口 | Streamlit Web | Streamlit Web（端口 8501）+ FastAPI（8000），未变 |
| 回复格式 | 邮件模板 | 邮件模板（Jinja2, 4 类：参数查询 / 兼容性 / 故障 / 转接），未变 |
| 增量更新 | "Webhook 触发" | 实际方案是 **手动重跑 `pipeline/main.py` + SAG 独立同步脚本** |

**一句话**：当前架构 = **Agentic RAG（LangGraph）+ Qdrant 向量检索 + 历史邮件回复 RAG + 已就绪待启用的 SAG 超图谱**。SAG 不再是"未来选项"，而是"已集成未投产"。

---

## 二、当前实际架构（基于代码事实）

### 2.1 分层视图

```
┌───────────────────────────────────────────────────────────────┐
│  表现层 (Presentation)                                          │
│  ├─ Streamlit Web (ui/app.py)            ← 内部员工用的对话页  │
│  └─ FastAPI HTTP (api/main.py)           ← 端口 8000            │
└────────────────────────────┬──────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│  Agent 编排层 (LangGraph StateGraph, agent/graph.py)            │
│                                                                │
│  START                                                          │
│   └─ query_rewrite   ← LLM 改写 + 代词消解（max_rewrites=1）  │
│      └─ classify      ← QuestionRouter 分类 7 种 qtype         │
│         └─ retrieve   ← Qdrant 检索 + 关键词扩展              │
│            └─ (条件: TROUBLE/COMPAT/HOWTO) retrieve_historical│
│               ← Zoho 历史邮件回复 RAG (方向 B)                  │
│               └─ reflect ← LLM 自评 "文档够不够用？"            │
│                  └─ (条件分支) generate | query_rewrite (loop) │
│                     └─ generate  ← AnswerGenerator             │
│                        └─ END                                   │
└────────────────────────────┬──────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│  检索层 (Retrieval Layer)                                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────┐  │
│  │ QdrantRetriever  │  │ SAGRetriever     │  │ Historical  │  │
│  │ (主, 已投产)      │  │ (已集成, 待启)   │  │ Replies RAG │  │
│  │ top_k=10         │  │ top_k=8          │  │ top_k=2     │  │
│  │ BGE-M3 1024d     │  │ multi-hop SQL    │  │ 阈值 0.55   │  │
│  └──────────────────┘  └──────────────────┘  └─────────────┘  │
└────────────────────────────┬──────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│  数据层                                                         │
│  ├─ Qdrant  (docker, 端口 6333, collection: jetson_wiki)        │
│  ├─ Postgres (SAG 后端, 端口 5433, 数据库 sag_lite) ← 待启用   │
│  ├─ index.json (30MB, 全量元数据索引)                            │
│  ├─ qa_pairs.jsonl  (1MB, FAQ 问答对)                            │
│  ├─ historical_replies.jsonl (1MB, Zoho 历史邮件)               │
│  └─ few_shot_examples.json (20KB, 少样本模板)                  │
└────────────────────────────┬──────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────┐
│  离线 Pipeline (pipeline/main.py, 可独立 cron)                  │
│  Wiki MD/MDX (171 篇 Jetson)                                    │
│    → parser.py        解析 frontmatter + 提取图片 + 提取 Resources│
│    → chunking         600 字/块，150 字 overlap                  │
│    → embedder.py      SiliconFlow BGE-M3 (batch=1000)            │
│    → indexer.py       写 Qdrant + 更新 index.json                │
│  + sag_sync.py        (并行) 同步 chunk 到 SAG (待启用)         │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 关键代码模块清单

| 模块 | 文件 | 职责 | 状态 |
|---|---|---|---|
| 路由 | `agent/router.py` | 7 类 qtype 分类（FAQ/PARAM/COMPAT/HOWTO/TROUBLE/RESOURCE/HUMAN） | ✅ |
| 工作流 | `agent/graph.py` | LangGraph StateGraph：query_rewrite → classify → retrieve → reflect → generate | ✅ |
| 向量检索 | `agent/retriever.py` | QdrantRetriever + 同义词扩展（CAD/STL/OBJ/3D model/schematic） | ✅ |
| SAG 检索 | `agent/sag_retriever.py` | HTTP 客户端 + RRF 融合函数 | ✅ 集成，待启用 |
| 生成器 | `agent/generator.py` | AnswerGenerator，prompt 拼装 + 引用标注 | ✅ |
| 邮件模板 | `agent/email_renderer.py` | Jinja2，4 类模板 | ✅ |
| 历史回复 | `pipeline/ingest_historical_replies.py` | Zoho 邮件 → Qdrant 独立 collection | ✅ |
| SAG 同步 | `pipeline/sag_sync.py` | Wiki → SAG 增量同步 | ✅ 待启用 |
| Pipeline 主 | `pipeline/main.py` | 解析 → 分块 → Embedding → 入库 | ✅ |
| 前端 | `ui/app.py` + `ui/session.py` | Streamlit 对话页 | ✅ |

### 2.3 当前架构的两个「方向 B」并存特征

代码注释明确写有"方向 B：历史 agent 回复 RAG"，与 Wiki 文档 RAG 并存：

- **方向 A**（Wiki 文档 RAG）：171 篇 MD/MDX → Qdrant → 检索回答
- **方向 B**（历史回复 RAG）：Zoho 历史客服邮件 → 独立 collection (`zoho_historical`) → 当 qtype ∈ {TROUBLE, COMPAT, HOWTO} 时触发检索，阈值更严 (0.55)、top_k 更小 (2)

设计意图：**先用历史邮件的「现成好答案」兜底，再用 Wiki 文档做事实补充**。这对 Seeed 这种"技术问题重复率高"的场景非常合适。

---

## 三、RAG 形式全景对比

### 3.1 主流范式速览

| 范式 | 一句话原理 | 核心优势 | 主要短板 |
|---|---|---|---|
| **Naive RAG** | Embedding → 向量 Top-K → LLM | 简单、快、成本低 | 复杂/多跳问题召回差；无迭代 |
| **Advanced RAG** | Query 改写 + 混合检索（向量+BM25）+ Rerank | 成熟稳定，单跳精度高 | 多跳推理弱；维护多套索引 |
| **Agentic RAG** | LLM 当编排器，多步推理 + 自我反思 | 多跳强、可解释、可纠错 | 延迟高、成本高、调试难 |
| **Hybrid RAG** | 向量 + BM25 + 知识图谱三路 RRF 融合 | 综合能力强 | 调权重复杂；需要多套基础设施 |
| **GraphRAG** | 离线 LLM 抽取实体 → 全局知识图谱 → 全局+局部查询 | 全局理解强（"总结趋势"类） | 增量更新痛苦；图谱维护重 |
| **SAG (SQL 超图谱)** | 入库抽 event+entity，查询时 SQL JOIN 动态构图 | 多跳强、增量友好、延迟低 | 太新（2026-06）；生态薄 |
| **Multi-Modal RAG** | 图片 → VLM → 描述 → 向量化 | 能看截图、原理图 | 成本高、需要 VLM、延迟大 |

### 3.2 详细对比表（按 Jetson 技术支持场景定制）

| 维度 | Naive | Advanced | Agentic | GraphRAG | SAG | Hybrid（含多模） |
|---|---|---|---|---|---|---|
| **实施难度** | 低 | 中 | **高** | 中 | 中（新） | 高 |
| **单跳精度** | 中 | **高** | 高 | 中 | 高 | 高 |
| **多跳推理** | ❌ | ⚠️ 弱 | ✅ 强 | ✅ 强 | ✅ **极强** | ✅ 强 |
| **增量更新** | ✅ | ✅ | ✅ | ❌ 麻烦 | ✅✅ | ✅ |
| **硬件文档适配** | ⚠️ | ✅ | ✅✅ | ⚠️ | ✅ | ✅✅ |
| **图片/原理图理解** | ❌ | ❌ | ⚠️ 需扩展 | ❌ | ❌ | ✅ |
| **历史数据复用** | ⚠️ | ✅ | ✅✅ | ⚠️ | ⚠️ | ✅ |
| **可解释性** | ⚠️ | ⚠️ | ✅ 强（trace） | ✅ 强 | ✅ 强 | ⚠️ |
| **生产成熟度** | ✅ | ✅✅ | ✅ | ✅ | 🆕 新 | ✅（看组合） |
| **延迟（典型）** | <1s | 1-2s | 3-8s | 2-5s | <2s | 2-6s |
| **团队技能要求** | 低 | 中 | 高（图+状态机） | 中（图） | 高（SQL+LLM） | 高 |
| **对 Jetson 场景适配** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

> 表中加粗为本项目实际选择 / 当前形态。

### 3.3 重要范式逐项解析

#### 3.3.1 Agentic RAG（当前主架构）

```python
# agent/graph.py — 简化版图结构
START → query_rewrite → classify → retrieve → retrieve_historical
                                                    ↓
                                                  reflect
                                                    ↓
                            (loop if 文档不够, 限 max_rewrites=1)
                                                    ↓
                                                 generate → END
```

**核心特征**：
- 节点：5 个（rewrite / classify / retrieve / historical / reflect / generate）
- 状态：`chunks`、`query_history`、`reflection_passed`、`qtype` 等在 State 中流转
- 反思机制：`reflect` 节点用 LLM 自评"文档够不够"，不够就回 `query_rewrite` 再来一轮
- 条件分支：历史回复 RAG 仅在 `TROUBLE/COMPAT/HOWTO` 三类问题触发（避免 FAQ 也误召回）

**优势在本项目中的体现**：
- 用户的"刷机失败"问题需要先问设备型号、症状、错误日志 → 多轮对话 + reflect 节点天然支持
- "J401 能否用 RPi Camera V2" 这种兼容性问题 → 多跳（J401 的 CSI 接口规格 ↔ RPi Camera V2 的输出规格）→ reflect 触发重查

**代价**：
- 平均延迟 3-8s（v1.0 报告说"$5-8/月"是基于 700 tokens 估算，实际 reflect + rewrite 会涨到 1500-3000 tokens，预算翻倍到 $10-15/月，仍可控）
- 调试复杂，需要看 LangSmith / 日志 trace
- `max_rewrites=1` 是保守设置，避免无限循环和成本失控

#### 3.3.2 SAG（已集成，未投产）

**与 GraphRAG 的关键差异**：

```
GraphRAG:    文档 → LLM 离线抽实体 → 全局图谱 → 查询时图遍历
              痛点: Wiki FAQ 频繁更新，全局图谱每次都要重建

SAG:         文档 → 入库时抽 (event, entity) → 存 Postgres
             查询时: SQL JOIN 动态构建局部超图（H=1, 默认一跳）
              优势: 增量 append 即可，无需重建全局图
```

**为什么本项目已经集成但还没启用**：
- ✅ 代码已就绪：`agent/sag_retriever.py`（HTTP 客户端 + RRF 融合）、`pipeline/sag_sync.py`（同步脚本）、`tests/test_sag_retriever.py`（单元测试）
- ⏸ 当前 `config.yaml` 中 `sag.enabled: false`、`retrieval.backend: "qdrant"`
- 切换成本低：把 `backend` 改成 `"hybrid"` 即可，SAG 不可达时自动 fall back 到 Qdrant（见 `SAG_INTEGRATION_CHANGES.md`）

**启用前需要做的事**：
1. SAG 服务可达（当前 4173 端口、Postgres 5433 端口已开）
2. `pipeline/sag_sync.py` 跑一次，把 171 篇 Wiki 同步进 SAG（预计 2-4 小时，取决于 LLM 提取速度）
3. 用 `tests/test_sag_retriever.py` 验证接口兼容
4. A/B 测试 `qdrant_weight=0.4 / sag_weight=0.6` 的融合效果

#### 3.3.3 Naive RAG — 为什么不够

Jetson 技术支持问题的分布（基于 `qa_pairs.jsonl` + `historical_replies.jsonl` 抽样）：

| 问题类型 | 占比 | Naive RAG 是否够用 |
|---|---|---|
| 参数查询（"J401 功耗多少？"） | ~30% | ✅ 够用 |
| FAQ（"如何重置？"） | ~20% | ✅ 够用 |
| **兼容性问题**（"A 能否配 B？"） | ~25% | ❌ 需要多跳 |
| **故障排查**（"刷机失败"） | ~15% | ❌ 需要迭代追问 |
| 资源下载（Datasheet/Schematic） | ~10% | ⚠️ 需要结构化链接 |

Naive RAG 对前两类（合计 50%）够用，但对后两类（合计 40%）会频繁召回不足 / 答非所问。

#### 3.3.4 GraphRAG — 为什么不适合

**致命伤**：Wiki FAQ 频繁更新。
- 每次 Wiki commit → 离线抽取要重跑 → 图谱重建（小时级）
- 实体消歧 / 合并规则复杂（"J401" vs "reComputer J401" vs "J401 carrier"）
- Jetson 场景的"总结 XXX 发展趋势"类问题占比 < 5%，投入产出比低

#### 3.3.5 Multi-Modal RAG — 何时上

当前架构对图片的处理是**「先链接 + Stage 3 GPT-4o 解读」**（来自 v1.0 已确认决策），代码层面尚未实现 `upload_image` 接口。

**什么时候值得上**：
- 用户开始上传截图（错误日志截图、原理图）
- 客服人员反馈"AI 答不出截图里的错误码"
- 月活问题中包含图片的比例 > 10%

**不建议现在上的理由**：
- VLM 调用成本高（GPT-4o 看图 $2.50/1M input token，一张标准原理图 ~$0.002/次）
- 现有 Streamlit UI 不支持图片上传（`ui/app.py` 仅文本框）
- v1.0 报告里说的"$1/月 500 次图片分析"是理想估算，实际多数客服不会主动上传

---

## 四、本项目架构的关键设计取舍

### 4.1 选 Agentic RAG 而不是 Advanced RAG 的理由

| 维度 | Advanced RAG | Agentic RAG（本项目）|
|---|---|---|
| "刷机失败"这种追问型问题 | 一次检索就交答案，命中率低 | reflect 节点可触发重写 / 补查 |
| 客服多轮对话体验 | 单轮生硬 | query_rewrite 自动消解代词 |
| 复杂兼容性问题 | 多跳弱 | 显式 graph + 反思 |
| 开发成本 | 低 | 中（LangGraph 学习曲线）|
| 调试成本 | 低 | 中（需要 trace）|
| 月成本（估）| ~$3 | ~$10-15（reflect 多耗 token）|

**结论**：月成本增加 $7-12，但换来客服效率提升 20-30%（基于 reflect 减少错误转接的粗估），划算。

### 4.2 选 Qdrant 而不是 pgvector / ChromaDB 的理由

- **混合检索原生支持**（Qdrant 自带 sparse vector + BM25-style）
- **REST + gRPC 双接口**，Python 客户端成熟
- **Filter 能力强**（按 `product`, `category`, `language` 过滤）—— 本项目按 qtype 分类路由后需要过滤
- **生产部署案例多**（LangChain / LlamaIndex 官方推荐）

**为什么不选 pgvector**：
- pgvector 单表超过 100 万行后性能下降明显
- 不能做 hybrid retrieval（需要拼 ElasticSearch / ParadeDB）
- 运维复杂度上升（既要管 Qdrant 又要管 Postgres 的向量表）

**为什么不选 ChromaDB**：
- 仅适合本地原型，生产部署需要外挂 SQLite/Postgres 后端
- 没有原生 hybrid retrieval，需要外挂 BM25 索引

### 4.3 选 LangGraph 而不是 CrewAI / AutoGen 的理由

| 框架 | 本项目适配性 | 主要顾虑 |
|---|---|---|
| **LangGraph**（已选） | ✅ 显式图控制、checkpoints、可观测性好 | 学习曲线 |
| CrewAI | ⚠️ 角色化设计直观 | 灵活性低，不适合自定义反思循环 |
| AutoGen Core | ⚠️ 多租户 / 隔离性好 | 事件驱动复杂度过高 |
| LlamaIndex Agents | ⚠️ 检索为主 | 偏检索，本项目需求是编排 + 反思 |
| Google ADK | ❌ | GCP 绑定 |

### 4.4 历史邮件 RAG（方向 B）的特殊性

这是一个**容易低估价值**的设计：

- `historical_replies.jsonl` 1MB ≈ 数千封真实客服邮件
- 这些邮件的"问题-答案"对，是 Seeed 多年累积的**领域风格样本**
- 当 qtype ∈ {TROUBLE, COMPAT, HOWTO} 时先检索历史好答案，再让 LLM 用 Wiki 事实补充 → **风格 + 事实**双保险

**但要注意**：
- 历史回复可能已过时（Jetson 产品已停产）→ 阈值 0.55 + top_k=2 是保守设置
- 检索到后要在 prompt 里明确"以下为历史回复参考，需用 Wiki 事实校验"
- 定期清理过期产品的历史回复（建议季度 review）

---

## 五、推荐演进路径（取代 v1.0 的 Stage 1/2/3）

> v1.0 报告里的 Stage 1（Advanced RAG MVP）已经过时——我们实际跳过了那个阶段。下面的路径从**当前状态**出发。

### 5.1 已完成（截至 2026-07-10）

- ✅ LangGraph Agentic RAG 工作流（`graph.py`）
- ✅ Qdrant 向量库 + 171 篇 Wiki 文档已索引
- ✅ 历史邮件回复 RAG（方向 B）
- ✅ 邮件模板引擎（4 类模板）
- ✅ Streamlit MVP + FastAPI 服务
- ✅ SAG 客户端代码 + 同步脚本 + 单元测试
- ✅ Pipeline 解析 → 分块 → Embedding → 入库 自动化

### 5.2 短期（1-2 周）— 让 Agentic RAG 真正稳定

| 优先级 | 任务 | 验收标准 |
|---|---|---|
| P0 | 接 LangSmith / 日志 trace，看 reflect 节点的实际触发率 | 日志显示 reflect 通过率 / 重查率 |
| P0 | 用 `tests/` 覆盖 graph.py 各节点 | 单元测试 ≥ 70% 覆盖 |
| P1 | 历史邮件 RAG 加时间衰减（停产产品降权）| 同问题检索结果排序更合理 |
| P1 | 邮件模板加"问题确认"字段（让用户知道 AI 理解对了） | 客服抽样 20 封邮件确认 |
| P2 | Streamlit 加"反馈按钮"收集正确/错误 | 数据回流到 `few_shot_examples.json` |

### 5.3 中期（2-4 周）— 启用 SAG，验证多跳提升

| 优先级 | 任务 | 验收标准 |
|---|---|---|
| P0 | `pipeline/sag_sync.py` 跑全量 171 篇导入 SAG | SAG `/api/projects/jetson_wiki` 返回非空 |
| P0 | `config.yaml` 切到 `backend: "hybrid"` | A/B 测试：相同 30 个多跳问题，对比 hybrid vs qdrant-only |
| P1 | 调权重（`qdrant_weight / sag_weight`）| 找到召回 + 精度的 Pareto 最优 |
| P1 | SAG 不可达时的 fall back 行为验证 | 关闭 SAG 服务，agent 仍能回答（仅用 Qdrant）|
| P2 | SAG 增量同步脚本（Wiki 更新 → 自动同步）| 跑通一次 git hook → pipeline |

### 5.4 长期（按需）— 多模态 / 飞书接入

| 优先级 | 任务 | 触发条件 |
|---|---|---|
| P3 | Multi-Modal RAG（图片理解）| 用户上传图片的请求 > 10/月 |
| P3 | 飞书/Lark 机器人 | 客服侧反馈"需要 IM 内对话"|
| P3 | GraphRAG 局部尝试 | 如果 SAG 启用后仍答不好"总结 XXX 趋势"类问题 |

**不建议现在做的**：
- ❌ 全量 GraphRAG 重建（投入产出比低）
- ❌ 替换 LangGraph 为 Google ADK（无明显收益，重写成本高）
- ❌ 切换到本地 LLM（Qwen2.5 / DeepSeek 私有部署成本远高于 OpenAI 兼容端点）

---

## 六、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| Agentic RAG 延迟过高，用户等待 | 中 | 高 | `max_rewrites=1` + 限 reflect 节点 `max_tokens=100`，已经做了；可考虑加流式输出 |
| SAG 启用后查询慢 | 中 | 中 | SAG 用 `search_mode: "fast"`（不调 LLM 抽实体）；可监控 P95 |
| 历史邮件 RAG 召回过期产品答案 | 高 | 中 | 加时间衰减 + 季度清理 |
| Qdrant 单点故障 | 低 | 高 | 改用 Qdrant 集群模式（生产化时再上）|
| Wiki 改 frontmatter 格式 → pipeline 解析失败 | 中 | 中 | parser.py 加 schema 校验 + 失败告警 |
| Embedding 模型切换 → 索引需重建 | 低 | 高 | 锁定 BGE-M3 1024 维；版本固定 |
| LangGraph 状态机 bug 难以复现 | 中 | 中 | 接 LangSmith / 强化日志 |

---

## 七、与 v1.0 报告的差异说明

> 这部分给读者交代清楚"为什么重写"，方便对照。

| 主题 | v1.0（2026-07-07）| v2.0（本版, 2026-07-13）| 差异原因 |
|---|---|---|---|
| 整体范式 | "MVP 用 Advanced，生产用 Agentic" | 实际已经是 Agentic | v1.0 时 graph.py 尚未完成；v2.0 据代码事实更新 |
| SAG 定位 | "未来规模化再考虑" | 已集成、待启用 | SAG_RETRIEVER.py / sag_sync.py 已落地 |
| Embedding | OpenAI text-embedding-3-small Batch | 实际 SiliconFlow BGE-M3 | config.yaml 显示 provider 切到 siliconflow |
| LLM | GPT-4o-mini | OpenAI 兼容端点 + 多模型切换 | config.yaml 用 `OPENAI_LLM_MODEL` 环境变量 |
| 增量更新 | "Webhook 触发" | 手动 Pipeline + 独立 SAG 同步 | 实际未实现 Webhook |
| 月成本 | "$5-8" | 估"$10-15"（reflect 多耗）| v1.0 估算未含 reflect token |
| 行动项 | 8 项 P0-P3 | 6 项 P0-P2（去掉已完成的）| 状态更新 |

---

## 八、附录

### 8.1 关键文件路径

- 架构代码：`tech-support-agent/agent/graph.py`（LangGraph 工作流）
- 检索：`tech-support-agent/agent/retriever.py`（Qdrant）/`sag_retriever.py`（SAG）
- Pipeline：`tech-support-agent/pipeline/main.py` / `sag_sync.py`
- 配置：`tech-support-agent/config.yaml`
- 历史状态：`tech-support-agent/SAG_STATUS.md` / `SAG_INTEGRATION_CHANGES.md`
- 上一版报告（本文件取代对象）：`tech-support-agent/docs/TECH_ARCHITECTURE_REPORT.md`

### 8.2 引用

- SAG 论文：arXiv:2606.15971
- LangGraph：https://langchain-ai.github.io/langgraph/
- Qdrant：https://qdrant.tech/documentation/
- GraphRAG (Microsoft)：https://github.com/microsoft/graphrag
- Seeed Jetson Wiki：https://wiki.seeedstudio.com/

---

*文档维护者：Tech Support Agent 团队*
*下次 review 建议时间：SAG 启用 + A/B 测试完成后（约 2-3 周后）*