# Changelog

所有对项目可见的变更都记录在此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Stage 2: Agentic RAG (LangGraph) - 2026-07-08

#### Added
- **LangGraph 工作流** (`agent/graph.py`)：6 节点 StateGraph
  - `query_rewrite` 节点：LLM 改写 + 代词消解 + 多跳查询拆分
  - `classify` 节点：复用 QuestionRouter，6 类问题分类
  - `retrieve` 节点：Qdrant 向量检索，支持多 query 合并去重
  - `retrieve_historical` 节点：条件触发（仅 TROUBLE/COMPAT/HOWTO），检索 ZOHO 历史工单
  - `reflect` 节点：LLM 自评"文档够用吗？"，score < 阈值触发重写循环
  - `generate` 节点：LLM 回答生成 + 邮件模板渲染
- **3 个条件边**：
  - `classify → retrieve`（恒定）
  - `retrieve → [retrieve_historical | reflect]`（按 qtype）
  - `reflect → [generate | query_rewrite]`（按 score + max_rewrites 限制）
- **图配置项** (`config.yaml → graph`)：
  - `max_rewrites`: 反思循环最大重写次数（默认 2）
  - `reflection_threshold`: 文档够用阈值（默认 0.7）
  - `enable_query_rewrite` / `enable_reflection` / `enable_historical`: 节点开关
- **测试**：
  - `tests/test_graph.py`：14 个单元测试（mock LLM），覆盖节点降级、路由条件边、图编译、chat 容错
  - `tests/regression_graph.py`：7 个端到端 case，覆盖各 qtype + 代词消解
- **依赖**：`langgraph==0.2.50`（自动升级 langchain-core 到 0.3.86）

#### Changed
- `agent/chat.py` 重构：`TechSupportChat.chat()` 改为 `graph.invoke()` 包装
  - 保留 `ConversationContext / Message` API 不变（FastAPI 路由不变）
  - 新增 `fallback_reason` 字段：异常时记录降级原因
  - `_text_search` / `_suggest_followup` 改为占位（向后兼容）

#### Verified
- 静态自检：图编译 + 6 节点 + FastAPI 路由全部保留
- 单元测试：**14/14 PASS**
- 端到端回归：**7/7 PASS**
- 代词消解 T7：'它支持哪些外设接口？' → 'reComputer J4012 支持哪些外设接口？' ✅
- Lints 干净

## [0.1.0] - Stage 1 MVP - 2026-07-07

### Added
- 基础 RAG：Qdrant 向量库 + OpenAI Embedding
- FastAPI Agent：检索 + 生成 + 邮件模板
- Streamlit Web UI
- 多轮对话状态管理
- 历史工单 RAG (RAG-2)
- Few-shot 样例注入
- 关键词扩展（CAD / STL / schematic 等）
- 6 类问题路由（param_query / compatibility / troubleshooting / howto / general / transfer）
- 21 篇 FAQ 结构化
