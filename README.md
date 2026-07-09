# Seeed Studio Tech Support Agent

> 基于 Jetson Wiki 文档的 AI 技术支持助手 — Agentic RAG + 多轮对话 + 邮件模板回复

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.50-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.11-red.svg)](https://qdrant.tech)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Seeed Studio 技术支持团队的内部 AI 助手，基于 [Jetson Wiki](https://wiki.seeedstudio.com) 171 篇文档构建。客户在工单/邮件里问的 Jetson 相关问题，Agent 自动检索文档、按问题类型路由、生成符合邮件格式的专业回复。

---

## ✨ 核心特性

| 能力 | 说明 |
|---|---|
| **Agentic RAG (LangGraph)** | 6 节点工作流：query_rewrite → classify → retrieve → [historical] → reflect → generate，支持多跳查询和自我反思 |
| **多轮对话状态** | 完整的会话上下文管理（`ConversationContext`），代词自动消解 |
| **历史工单 RAG** | 基于 ZOHO 历史相似工单回复做 Few-shot 增强（RAG-2） |
| **问题智能分类** | 6 类问题路由：`param_query` / `compatibility` / `troubleshooting` / `howto` / `general` / `transfer` |
| **邮件模板回复** | 标准化邮件格式输出（可关闭 `raw=true` 拿纯文本） |
| **多模态就绪** | 检索结果自动附带图片链接 / 资源链接，Stage 3 计划接入 GPT-4o 原理图理解 |
| **极低成本** | 月均 $5-8 即可运行（GPT-4o-mini 推理 + BGE-M3 Embedding） |

---

## 🏗️ 架构

```
用户问题
  │
  ▼
┌──────────────┐
│ query_rewrite│  ← LLM 改写 + 代词消解
└──────┬───────┘
       ▼
┌──────────────┐
│   classify   │  ← 6 类问题路由
└──────┬───────┘
       ▼
┌──────────────┐
│   retrieve   │  ← Qdrant 向量检索 (RAG-1: wiki)
└──────┬───────┘
       ▼  (条件: qtype ∈ {TROUBLE, COMPAT, HOWTO})
┌──────────────┐
│  historical  │  ← ZOHO 历史工单 (RAG-2)
└──────┬───────┘
       ▼
┌──────────────┐
│   reflect    │  ← LLM 自评 "文档够用吗？"
└──────┬───────┘
       ▼ (score ≥ 阈值 OR 已达 max_rewrites)
┌──────────────┐
│   generate   │  ← LLM 生成 + 邮件模板渲染
└──────┬───────┘
       ▼
     回答
```

详见 [`docs/TECH_ARCHITECTURE_REPORT.md`](docs/TECH_ARCHITECTURE_REPORT.md)。

---

## 🚀 快速开始

### 1. 环境准备

要求：Python 3.11+、Docker（跑 Qdrant）、可访问 OpenAI 兼容端点 / SiliconFlow

```bash
git clone https://github.com/bleaaach/tech-support-agent.git
cd tech-support-agent
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY / SILICONFLOW_API_KEY
```

### 2. 启动 Qdrant 向量数据库

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

### 3. 构建索引（一次性，约 10-20 分钟）

```bash
# 解析 Wiki 文档 + 生成 index.json
python -m pipeline.main

# 导入到 Qdrant
python -m pipeline.indexer
```

### 4. 启动 Agent 服务

```bash
python -m agent.main
# FastAPI 跑在 http://localhost:8000
# API 文档： http://localhost:8000/docs
```

### 5. 启动 Web UI

```bash
streamlit run ui/app.py --server.port 8501
# 浏览器打开 http://localhost:8501
```

---

## 🧪 测试

```bash
# 单元测试（无需真实 API，mock LLM）
python tests/test_graph.py

# 端到端回归（7 case 覆盖各 qtype + 代词消解）
python tests/regression_graph.py
```

最新一次回归：**14/14 单元测试 PASS，7/7 端到端 PASS**。

---

## 📂 项目结构

```
tech-support-agent/
├── config.yaml              # 主配置（LLM、Qdrant、retrieval、graph）
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量模板
├── README.md
├── LICENSE
│
├── pipeline/               # 文档解析 + 向量索引
│   ├── parser.py           # Wiki 文档解析
│   ├── embedder.py         # Embedding（local / OpenAI / SiliconFlow）
│   ├── indexer.py          # Qdrant 入库
│   ├── ingest_historical_replies.py  # 历史工单入库
│   ├── build_email_corpus.py         # Few-shot 样例构建
│   └── main.py             # 一键构建入口
│
├── agent/                  # FastAPI Agent 服务
│   ├── main.py             # FastAPI 入口（/chat, /history, /reset, /health）
│   ├── graph.py            # ⭐ LangGraph 工作流（Stage 2）
│   ├── chat.py             # 多轮对话管理（委托给 graph）
│   ├── router.py           # 问题分类
│   ├── retriever.py        # Qdrant 检索（含关键词扩展）
│   ├── generator.py        # LLM 回答生成
│   ├── email_renderer.py   # 邮件模板
│   └── templates/          # Jinja2 邮件模板
│
├── ui/                     # Streamlit Web UI
│   └── app.py
│
├── tests/                  # 测试
│   ├── test_graph.py       # LangGraph 节点/路由单测（14 个）
│   ├── regression_graph.py # 端到端回归（7 case）
│   └── test_prompt_injection.py
│
├── data/                   # 索引/语料（.gitignore，不入仓）
│   ├── index.json
│   ├── few_shot_examples.json
│   └── qa_pairs.jsonl
│
├── docs/                   # 文档
│   └── TECH_ARCHITECTURE_REPORT.md
│
└── cleaned_ZOHO-email_units/  # ZOHO 工单原始数据
```

---

## 🔧 技术栈

| 组件 | 技术 | 用途 |
|---|---|---|
| Agent 编排 | **LangGraph 0.2.50** | Stage 2 Agentic RAG 工作流 |
| LLM 框架 | LangChain Core 0.3.86 | LLM 抽象 |
| LLM 推理 | OpenAI 兼容端点（GLM-5.2 / DeepSeek-V4 / GPT-5.5 等） | query_rewrite / classify / reflect / generate |
| Embedding | BGE-M3 (1024 维) via SiliconFlow | 文档向量化 |
| 向量库 | Qdrant 1.11 | 文档 + 历史工单检索 |
| Agent API | FastAPI 0.115 | /chat, /history, /reset |
| 邮件模板 | Jinja2 3.1 | 标准化邮件格式输出 |
| 前端 | Streamlit 1.38 | Web UI |

---

## 📈 演进路线

| Stage | 状态 | 说明 |
|---|---|---|
| **Stage 1 (MVP)** | ✅ 已完成 | 基础 RAG + FastAPI + Streamlit + 邮件模板 + 多轮对话 + 历史工单 RAG |
| **Stage 2 (Agentic)** | ✅ 已完成 | LangGraph 6 节点工作流：query rewrite + reflect + 多跳检索 + 条件路由 |
| **Stage 3 (多模态)** | 🔜 计划中 | GPT-4o 原理图理解、图片 OCR、邮件模板引擎升级 |

---

## 🤝 内部使用

本项目是 Seeed Studio 技术支持团队内部工具。如需内部访问：
- Wiki 源文档路径：`D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson`
- ZOHO 工单历史：`cleaned_ZOHO-email_units/`
- 线上部署：参考 [`start.ps1`](start.ps1)

---

## 📝 License

[MIT](LICENSE)
