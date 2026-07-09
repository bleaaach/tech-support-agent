# NVIDIA Jetson 技术支持 Agent — 技术架构选型报告

> 文档版本：v1.0
> 日期：2026-07-07
> 目的：对比 2026 年最新的 RAG / Agent 架构，选出最适合 Seeed Studio Jetson Wiki 知识库的方案

---

## 一、现状分析

### 1.1 现有基础设施

| 组件 | 技术栈 | 状态 |
|------|--------|------|
| Wiki 本体 | Docusaurus v3 | ✅ 已运行 |
| 文档格式 | MD/MDX，含 frontmatter 元数据 | ✅ 结构化 |
| 搜索 | Typesense（全文索引） | ✅ 已有 |
| 多语言 | en/zh-CN/ja/es/pt-BR | ✅ 已支持 |
| 部署 | GitHub Pages | ✅ 已有 |
| 图片资源 | 外链 URL（`files.seeedstudio.com`） | ✅ 已标注 |
| 资源下载 | PDF 原理图/Datasheet/3D 文件 | ✅ 已标注 |
| 文档规模 | 171 篇 Jetson 文档 | ✅ 确定 |

### 1.2 知识库特征

```
文档类型分布：
├── FAQ 类（troubleshooting / how-to）     ~21 篇   ← 最高优先，处理用户直接提问
├── 产品指南类（getting started）         ~60 篇   ← 常用，中等
├── 硬件接口类（hardware interfaces）      ~40 篇   ← 含图片/原理图
├── 应用案例类（application）              ~50 篇   ← 较低频

关键技术特点：
1. 硬件文档 → 需要能引用图片和原理图
2. 多跳问题 → "刷机失败" 可能需要跨多篇文档定位原因
3. 步骤式操作 → 用户需要清晰的分步指引
4. 资源下载 → 用户需要快速获取 Datasheet/Schematic
5. 多语言 → 英文为主，但有中文等多语言文档
```

---

## 二、2026 年 RAG 技术全景图

### 2.1 演进路线

```
2023 年：Naive RAG（检索 → 生成，单轮）
   ↓
2024 年：Advanced RAG（分块优化 + 混合检索 + Rerank）
   ↓
2025 年：GraphRAG（离线构建知识图谱 + 全局搜索）
   ↓
2026 年（当前主流）：
   ├── Agentic RAG（自主多步推理 + 自我纠错）
   ├── SAG（SQL 动态超图谱，2026 新提出）
   ├── Hybrid RAG（向量 + BM25 + 知识图谱 三路融合）
   └── Multi-Modal RAG（支持图片/图纸理解）
```

### 2.2 各技术范式详解

#### 范式 A：Naive RAG（单轮检索）
```
用户问题 → 向量检索 Top-K → 拼 context → LLM 生成回答
```
**适用场景**：文档库小、问题简单、无多跳需求
**缺点**：复杂问题召回不足，无法迭代搜索，幻觉率高

---

#### 范式 B：Advanced RAG（高级 RAG）⭐ 推荐 MVP 阶段

```
用户问题 → Query 改写 → 向量检索 + BM25 混合 → Rerank → 生成
                ↑  synonym / HyDE
```

**关键组件**：
- **Query 改写**：HyDE（生成假设答案来检索）、同义词扩展
- **混合检索**：向量相似度 + BM25 关键词，RRF 融合
- **Rerank**：Cross-Encoder 重排，提高相关性
- **Parent Document Retriever**：小块精匹配，大块给 LLM

**代表实现**：
- `ahmet-ozel/agentic-rag-customer-support`（Qdrant + 多 LLM 后端 + MCP）
- `RAGFlow`（深度文档解析，适合 PDF 表格/布局）
- Dify（可视化 RAG 编排）

**优点**：成熟稳定，MVP 快速交付
**缺点**：多跳推理能力有限
**适合**：Jetson FAQ 类直接问题

---

#### 范式 C：Agentic RAG（自主 Agent 推理）⭐ 推荐生产阶段

```
用户问题
    ↓
┌─────────────────────────────┐
│   Orchestrator（编排器）     │
│  分析问题 → 决定下一步行动    │
└──────────┬──────────────────┘
           ├──→ 文档检索 Agent（Wiki）
           ├──→ 图片/资源 Agent（提取原理图链接）
           ├──→ 诊断 Agent（根据日志/错误码分析）
           └──→ 网络搜索 Agent（外部信息补充）
                    ↓
           ┌──────────────────┐
           │  Reasoning Agent │
           │  分解子问题 → 迭代 │
           │  验证答案完整性    │
           └──────────┬─────────┘
                      ↓
                最终回答（含引用）
```

**代表实现**：
- `Bitmovin Multi-Agent System`（Google ADK + Vertex AI Search）
- `sumatosoft/agentic-rag`（企业级 Agentic RAG 指南）
- `Protocol-H`（分层 Agentic RAG + 自主错误恢复）

**核心框架对比**：

| 框架 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **LangGraph** | 企业级生产系统 | 图控制精细、可观测、checkpoints | 学习曲线陡 |
| **CrewAI** | 快速原型验证 | 角色化设计、直观 | 灵活性低 |
| **AutoGen Core** | 多租户/受监管环境 | 事件驱动、隔离性好 | 复杂度高 |
| **LlamaIndex Agents** | 检索为主 | 与向量库集成深 | 偏检索而非复杂编排 |
| **Google ADK** | 团队协作 | 多 Agent 协同成熟 | Google 云绑定 |

**优点**：多跳推理、自我纠错、可解释性强
**缺点**：延迟高、成本高、复杂度高
**适合**：复杂技术支持、多文档关联分析

---

#### 范式 D：SAG（SQL 动态超图谱）🆕 2026 新范式

```
原理：文档入库时提取"事件+实体"，查询时用 SQL JOIN 动态构建局部知识图谱

存储层：PostgreSQL（实体/事件表）+ pgvector（向量）+ tsvector（全文）
检索层：Recall → Expand → Rerank（三阶段）

特点：
- 无需预建全局知识图谱
- H=1 默认一跳扩展，避免噪声爆炸
- 支持 5 亿级数据，延迟 < 2 秒
- 多跳推理（MuSiQue 基准）优于 HippoRAG 2
```

**论文**：arXiv:2606.15971（2026-06 刚挂出）
**GitHub**：`Zleap-AI/SAG`（Stars 快速上升中）

**优点**：增量更新友好、延迟低、多跳能力强
**缺点**：太新（2026-06）、生态不成熟、缺少中文资料
**适合**：未来规模化扩展，当前不推荐作为首选

---

#### 范式 E：GraphRAG（知识图谱 RAG）

```
文档 → LLM 实体抽取 → 离线构建知识图谱 → 查询时全局图搜索 + 局部检索
```

**代表**：Microsoft GraphRAG、NebulaGraph + LangChain
**优点**：全局理解能力强（适合"总结 XXX 的发展趋势"类问题）
**缺点**：图谱维护成本高、增量更新麻烦、不适合高频更新的知识库
**不适合**：Jetson Wiki（FAQ 频繁更新，静态图谱负担重）

---

#### 范式 F：Multi-Modal RAG（多模态 RAG）

```
文本 Chunk → Embedding → 存储
图片  →  VLM（GPT-4V / LLaVA） → 生成描述 → 向量存储
                              ↓
用户上传图片/截图 → VLM 理解 → 检索相关文档 → 生成回答
```

**代表**：`RAG-Anything`（HKUDS）、GPT-4V 多模态检索
**优点**：能理解截图、原理图、硬件图片
**缺点**：成本高、延迟高、需要 VLM 模型
**适合**：需要理解硬件图片/错误截图的场景

---

## 三、针对 Jetson 知识库的方案设计

### 3.1 方案 A：渐进式演进（推荐）

```
阶段 1（MVP，1-2周）→ 阶段 2（增强，2-3周）→ 阶段 3（生产，1个月+）

Stage 1: Advanced RAG（MVP）
├── Pipeline: 解析 171 篇文档 → index.json + 向量
├── 检索:  Qdrant（混合检索：向量 + BM25）
├── Agent: 单 Agent（分类路由 → 检索 → 生成）
├── 多轮对话: LangChain Memory（会话历史，支持追问）
├── 回复格式: 邮件模板引擎（参数查询/兼容性问题/故障排查/转接）
└── 前端:  Streamlit 内部工具页面

Stage 2: Agentic RAG（增强）
├── 接入 Wiki 实时数据（Webhook 触发增量索引）
├── 添加 Multi-Agent 编排（FAQ Agent / 图片 Agent / 诊断 Agent）
├── 交互式故障排查（多轮提问 → 逐步缩小范围）
├── 支持飞书/Lark 机器人接入
└── 前端:  Streamlit Web 页面（专注 AI 对话，不动现有 Wiki）

Stage 3: 生产级
├── 图片理解（VLM 解读原理图/截图）
├── SAG 架构（若规模扩大，替换为 SQL 动态图谱）
└── 知识图谱（FAQ 关联图谱）
```

### 3.2 方案 B：一步到位（高风险）

```
直接构建 Agentic RAG + Multi-Modal
├── Google ADK 多 Agent 系统
├── Qdrant + GraphRAG 混合
├── VLM 图片理解
└── 飞书/Lark 机器人（专注 Web 对话，不做浮窗）
工期：6-8 周
风险：团队学习曲线高，依赖多
```

---

## 四、详细技术架构（推荐方案 A Stage 1）

```
┌─────────────────────────────────────────────────────────────┐
│                      前端层                                  │
│  Streamlit Web 页面（专注 AI 对话，不动现有 Wiki）            │
│  ├─ 分类导航（侧边栏）       ├─ AI 对话按钮                │
│  └─ Streamlit Web 页面      └─ 不做浮窗，专注 Web 端对话体验  │
│  └─ 文档卡片列表             └─ 内联引用标注                 │
└────────────────────────┬──────────────────────────────────┘
                         │ HTTP/REST
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Agent 层                          │
│  ├─ /chat          ← 对话接口                               │
│  ├─ /search        ← 搜索接口                               │
│  ├─ /faq           ← FAQ 精确匹配                           │
│  └─ /upload_image  ← 图片理解接口（Stage 3）               │
│                                                             │
│  ┌─────────────────────────────────────────────┐           │
│  │           Orchestrator（编排器）              │           │
│  │  ├─ Intent Classification（问题分类）         │           │
│  │  ├─ FAQ 精确匹配（关键词+向量）               │           │
│  │  ├─ Wiki 检索（混合检索）                    │           │
│  │  ├─ Memory（会话历史，支持多轮追问）          │           │
│  │  ├─ Response Generator（含引用+图片链接）     │           │
│  │  └─ Email Renderer（邮件模板，结构化回复）    │           │
│  └─────────────────────────────────────────────┘           │
└────────────────────────┬──────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────────┐
│   Qdrant    │  │  index.json │  │  飞书/Lark API  │
│  (向量库)   │  │ (元数据索引) │  │  (Stage 2)     │
└─────────────┘  └─────────────┘  └─────────────────┘

Pipeline（Python 脚本，每日/按需运行）：
  171 篇 Wiki MD/MDX 文件
        ↓  [extract_index.py]
  ├─ 解析 frontmatter（title/description/slug/keywords）
  ├─ 提取图片 URL（正则匹配 img src）
  ├─ 提取 Resources 链接（PDF/Schematic/Datasheet）
  ├─ 语义分块（500 字/块，100 字 overlap）
  ├─ 生成向量（BGE-M3 / OpenAI text-embedding-3-small）
  └─ 写入 Qdrant + 更新 index.json
```

---

## 五、关键技术选型

### 5.1 核心组件对比

| 组件 | 选项 A（推荐云端） | 选项 B（保守） | 选项 C（前沿） |
|------|-------------|-------------|-------------|
| **向量库** | Qdrant（混合检索强） | ChromaDB（轻量 MVP） | pgvector（与 SAG 共用 SQL） |
| **Embedding** | **OpenAI text-embedding-3-small**（$0.02/1M，批量 $0.01） | BGE-M3 本地（零成本，需 GPU） | Voyage AI（$0.06/1M） |
| **LLM** | GPT-4o-mini（文本）+ GPT-4o（图片） | Claude 3.5 Sonnet | Qwen2.5（本地） |
| **Agent 框架** | LangGraph（精细控制） | LlamaIndex（检索为主） | Google ADK（多 Agent 协同） |
| **前端** | Streamlit（MVP）→ Docusaurus 插件 | 独立页面 | 飞书机器人 |
| **部署** | Docker Compose | 本地 Python | K8s（未来） |
| **图片理解** | GPT-4o 多模态（Stage 3） | GPT-4o API | LLaVA 本地 |
| **增量更新** | Webhook → 触发 Pipeline | 每日定时重建 | SAG 实时写入 |

### 5.2 推荐技术栈（当前阶段）

```
MVP 阶段（1-2 周）：
  Pipeline:     Python 3.10+ / python-frontmatter / BeautifulSoup
  向量库:        Qdrant（Docker 1 行启动，支持混合检索）
  Embedding:    OpenAI text-embedding-3-small（Batch API $0.01/1M tokens）
  LLM:          GPT-4o-mini（文本）+ GPT-4o（图片理解，Stage 3）
  对话状态:      LangChain Memory（会话历史）+ 邮件模板引擎（Jinja2）
  前端:          Streamlit（快速验证）
  数据库:        index.json（纯文件，零依赖）

生产阶段（按需升级）：
  + LangGraph（Orchestrator 编排，多轮状态机）
  + Rerank 模型（bge-reranker-v2-m3）
  + 邮件模板引擎（结构化邮件格式，按问题类型套用模板）
  + 飞书/Lark 机器人
  + GPT-4o 多模态（原理图理解）
```

### 5.3 云端成本估算

**Embedding（一次性索引构建）**

| 方案 | 模型 | 单次成本 | 说明 |
|------|------|---------|------|
| 云端标准 | text-embedding-3-small | **$0.02 / 1M tokens** | 每百万 tokens $0.02 |
| 云端批量 | text-embedding-3-small（Batch API） | **$0.01 / 1M tokens** | 夜间重建，延迟 24h，**推荐** |
| 本地 | BGE-M3（GPU） | **~$0.001 / 1M tokens** | 需 GPU，零云成本 |

> **171 篇 Jetson 文档估算**：约 **50 万 tokens**（每篇平均 ~3000 tokens）
> - 云端 Batch：$0.01 × 0.5M = **$0.005 一次性**
> - 本地 BGE-M3：$0.001 × 0.5M = **$0.0005 一次性**
> - **结论**：Embedding 成本极低，云端 vs 本地差异可以忽略

**LLM 推理（日常使用）**

| 模型 | 输入 | 输出 | 适用场景 |
|------|------|------|---------|
| GPT-4o-mini | $0.15 / 1M tokens | $0.60 / 1M tokens | 日常问答（推荐 MVP） |
| GPT-4o | $2.50 / 1M tokens | $10 / 1M tokens | 高质量回答 |
| GPT-4o（图片） | $2.50 / 1M tokens | $10 / 1M tokens | 原理图理解（Stage 3） |

> **日常使用估算**（假设 1000 次/天对话，每次 500 input + 200 output tokens）：
> - GPT-4o-mini：1000 × 700 tokens × $0.15/1M ≈ **$0.105 / 天 ≈ $3.15 / 月**
> - GPT-4o：1000 × 700 tokens × $2.50/1M ≈ **$1.75 / 天 ≈ $52.5 / 月**
> - **推荐**：日常用 GPT-4o-mini，原理图分析用 GPT-4o

**图片理解成本（Stage 3 原理图分析）**

| 图片类型 | Token 消耗 | GPT-4o 成本/张 |
|---------|-----------|--------------|
| 缩略图（低分辨率） | ~85 tokens | ~$0.0002 |
| 标准原理图（1024×1024） | ~765 tokens | ~$0.002 |
| 大幅面 PDF 截图 | ~1500 tokens | ~$0.004 |

> **每月估算**（假设 500 次图片分析/月）：
> - 500 × 765 tokens × $2.50/1M = **~$1 / 月**

**月均总成本估算**

| 阶段 | Embedding | LLM 推理 | 图片理解 | 合计/月 |
|------|----------|---------|---------|--------|
| Stage 1 MVP | $0.005（一次性） | ~$3（GPT-4o-mini） | — | **~$3-5** |
| Stage 3 多模态 | $0.005（一次性） | ~$3 + $1 | ~$1 | **~$5-8** |

> ✅ **结论：月均 $5-8 即可运行 Jetson Wiki AI 助手**，成本极低，云端完全可行

---

## 六、架构对比总结

| 评价维度 | Naive RAG | Advanced RAG | Agentic RAG | SAG (2026) | GraphRAG |
|---------|-----------|-------------|------------|------------|---------|
| **实施难度** | 低 | 中 | 高 | 中（新） | 中 |
| **多跳推理** | ❌ | ⚠️ 弱 | ✅ 强 | ✅ 强 | ✅ 强 |
| **增量更新** | ✅ | ✅ | ✅ | ✅✅ | ❌ 麻烦 |
| **硬件文档适配** | ⚠️ | ✅ | ✅✅ | ✅ | ⚠️ |
| **图片理解** | ❌ | ❌ | ⚠️ 需扩展 | ❌ | ❌ |
| **生产成熟度** | ✅ | ✅✅ | ✅ | 🆕 新 | ✅ |
| **对 Jetson Wiki 合适度** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐（待观察） | ⭐⭐ |

---

## 七、结论与建议

### 确认决策（用户已拍板）

| 决策点 | 已确认 | 备注 |
|--------|--------|------|
| Embedding | ✅ **云端 OpenAI text-embedding-3-small** | Batch API $0.01/1M，极低成本 |
| Agent 入口 | ✅ **网页端（Streamlit）** | MVP 先验证，再考虑飞书 |
| 图片理解 | ✅ **先显示链接 + GPT-4o 看懂原理图** | Stage 3 实现 |
| 对话模式 | ✅ **多轮有来有回** | 不是一轮问答，是交互式排查 |
| 回复格式 | ✅ **邮件模板格式** | 标准化邮件回复，不是纯文本 |

### 推荐路径：渐进式演进

```
当前 → Stage 1（MVP，1-2周）→ Stage 2（Agentic，2-3周）→ Stage 3（多模态）
      │
      └→ Advanced RAG          Agentic RAG               + GPT-4o 原理图理解
         Qdrant + OpenAI         + LangGraph                 + 原理图链接展示
         GPT-4o-mini             + 多轮对话状态管理             + 邮件模板引擎
         Streamlit 首页           + 邮件格式回复
```

**理由**：
1. **Embedding 成本极低**：171 篇文档一次性索引只需 ~$0.005，云端无负担
2. **月均 $5-8 即可运行**：日常用 GPT-4o-mini，原理图用 GPT-4o，预算友好
3. **多轮对话 + 邮件格式是基本要求**：不是可选功能，是技术支持的标准形式
4. **Agentic RAG 方向正确**：你截图里的方案方向对，分阶段实现降低风险
5. **SAG 太新**：2026-06 才发表，等生态成熟再考虑
6. **图片理解两阶段**：Stage 1 提取并展示链接，Stage 3 用 GPT-4o 解读原理图内容

---

## 八、下一步行动

| 优先级 | 任务 | 负责 | 预计工时 |
|--------|------|------|---------|
| ~~P0~~ | ~~确认 LLM / Embedding / 向量库技术选型~~ | ~~用户决策~~ | ~~已完成~~ |
| ✅ 已确认 | Embedding：OpenAI text-embedding-3-small Batch API | — | — |
| ✅ 已确认 | Agent 入口：网页端 Streamlit | — | — |
| ✅ 已确认 | 图片理解：先链接 + Stage 3 GPT-4o 解读 | — | — |
| P0 | 搭建 Pipeline（extract_index.py）生成 index.json | Agent | 2-4h |
| P1 | 部署 Qdrant，导入向量数据 | Agent | 1h |
| P1 | 开发 FastAPI Agent（检索 + 生成） | Agent | 4-8h |
| P2 | 开发 Streamlit MVP 首页 | Agent | 2-4h |
| P2 | FAQ 结构化转换（21 篇 → 模板） | Agent | 持续 |
| P3 | 接入飞书/Lark 机器人 | Agent | 4-8h |
| P3 | GPT-4o 图片理解（原理图分析） | Agent | 4-8h |

---

*文档由 Cursor AI Agent 生成，基于 2026-07 最新技术调研*
