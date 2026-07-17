# 多 Agent 集成方案设计文档

> 文档版本：v1.0（草稿，待 Review）
> 日期：2026-07-13
> 目的：补齐 `docs/TECH_ARCHITECTURE_REPORT.md` 第 95-117 行"范式 C：Agentic RAG"中提出的 4 个子 Agent 中尚未实现的 3 个（图片 Agent / 诊断 Agent / 网络搜索 Agent），同时保留现有 `agent/graph.py` 工作流。

---

## 一、背景与目标

### 1.1 现状盘点（基于代码事实）

| v1.0 文档提出的子 Agent | 当前实现 | 差距 |
|---|---|---|
| Orchestrator（编排器） | LangGraph StateGraph，6 节点线性 + 条件边 | ✅ 形态不同，能力等价 |
| 文档检索 Agent（Wiki） | `node_retrieve` + `QdrantRetriever` + 同义词扩展 | ✅ 完整 |
| 图片/资源 Agent | Parser 预提取 `image_urls` / `resource_urls`，邮件模板展示 | ⚠️ 半成品：链接有，无 VLM |
| 诊断 Agent | ❌ 仅在 prompt 里加"故障排查格式"指令 | ❌ 未实现 |
| 网络搜索 Agent | ❌ 无任何外部搜索调用 | ❌ 未实现 |
| Reasoning Agent（分解 + 迭代 + 验证） | `query_rewrite` + `reflect` 两个节点 | ⚠️ 部分实现，深度受 `max_rewrites=1` 限制 |

### 1.2 目标

1. **补齐诊断 Agent**：从用户日志/错误码中识别 Jetson 故障，路由到对应 Wiki 故障文档
2. **补齐网络搜索 Agent**：Wiki 兜底，DeepSeek Anthropic web_search（Tavily 作为可选后端）
3. **图片 Agent 暂缓 VLM**，仅做"链接展示增强"（邮件里把原理图缩略图直接渲染 base64，前端打开即看）
4. **不改既有 graph.py 行为**：新功能默认 `enabled: false`，零回归

### 1.3 关键约束

- 现有 `agent/graph.py` 已投产（CHANGELOG：7/7 端到端 PASS）
- LLM 客户端栈基于 OpenAI 兼容协议（`from openai import OpenAI`）
- DeepSeek 官网同时提供 OpenAI 兼容（`https://api.deepseek.com`）和 Anthropic 兼容（`https://api.deepseek.com/anthropic`）端点
- 仅 Anthropic 端点支持 `web_search_20260209` server-side tool

---

## 二、整体架构（基于 LangGraph 0.2.50 + Handoffs 模式）

### 2.1 推荐模式：Node + 条件边（最小侵入）

借鉴 [LangChain 官方 handoff 教程](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs-customer-support) 和 [gym-support 官方示例](https://github.com/langchain-ai/pipecat-langgraph-example)：

```
START
  ↓
query_rewrite        ← 现有，不变
  ↓
extract_urls         ← 现有，不变
  ↓
classify             ← 现有，qtype 决定后续路由
  ↓
retrieve (Wiki)      ← 现有
  ↓
retrieve_historical  ← 现有
  ↓
[条件] qtype=TROUBLE 且消息含日志/错误码 → diagnose_agent 节点（新）
  └─ 输出：诊断线索 chunks，prepend 到 wiki_chunks
  ↓
[条件] reflect 兜底 或 wiki_chunks 为空 → websearch_agent 节点（新）
  └─ 输出：网页 chunks，prepend 到 wiki_chunks
  ↓
reflect              ← 现有
  ↓
(条件分支) generate | query_rewrite  ← 现有，不变
  ↓
generate             ← 现有，不变
  ↓
END
```

**为什么不选 Subagent-as-Tool 模式（LangChain 2026 推荐）**：

| 维度 | Subagent-as-Tool | Node + 条件边（本方案）|
|---|---|---|
| 改动量 | 大：supervisor + 4 个子 agent 全重写 | 小：在现有图里插 2 个节点 |
| 调试 | 需要重新设计 state schema | 现有 state schema 不变 |
| 风险 | 投产中功能回归 | 零回归（默认 disabled）|
| 适配度 | 适合从零设计的多 agent | 适合既有 LangGraph 工作流增量加 Agent |

参考 [LangGraph 迁移指南](https://docs.langchain.com/oss/python/migrate/langgraph-supervisor) 和 [Supervisor Pattern 2026](https://myengineeringpath.dev/genai-engineer/langgraph-multi-agent/)。我们走 Node + 条件边，等 3 个 Agent 都跑稳了，下一次重构再统一升级到 Supervisor。

---

## 三、诊断 Agent 设计（`agent/agents/diagnose_agent.py`）

### 3.1 输入输出契约

```python
class DiagnoseInput(TypedDict):
    user_message: str       # 原始用户消息（可能含日志/错误码）
    history_text: str       # 对话历史
    qtype: str              # 来自 classify 节点

class DiagnoseOutput(TypedDict):
    matched_error_codes: list[dict]   # [{"code": "MC_ERR", "raw": "MC_ERR 0x... ", "confidence": 0.95}]
    matched_docs: list[dict]          # [{"doc_id": "...", "title": "...", "wiki_url": "...", "score": 0.9}]
    diagnostic_chunks: list[dict]     # 注入到 wiki_chunks 的结构化 chunks
    fallback_hint: str                # 若无可匹配错误码，提示用户补充日志
```

### 3.2 工作流

```
用户消息（可能含日志/错误码）
  ↓
[1] Regex 扫描 Jetson 已知错误码（data/error_codes.yaml）
  ↓
[2] 每个匹配的 code → 路由到对应 Wiki 故障文档路径
  ↓
[3] Qdrant 向量检索 top-3 匹配文档
  ↓
[4] 构造 diagnostic_chunks（prepend 到 wiki_chunks）
  - chunk_text: "错误码 MC_ERR（来源：dmesg）\n可能原因：...\n排查步骤：..."
  - title: "[Diagnose] MC_ERR"
  - wiki_url: 实际匹配的文档 URL
  - score: 1.0（诊断线索优先级最高）
  ↓
[5] 若无匹配 → 返回 fallback_hint（不报错，正常降级）
```

### 3.3 Jetson 错误码 YAML（`data/error_codes.yaml`）

```yaml
# Jetson 已知错误码 → Wiki 故障文档路径
# 优先级按历史工单出现频率排序
error_codes:
  - code: "MC_ERR"
    pattern: "MC_ERR\\s+(0x[0-9a-fA-F]+|\\d+)"
    description: "Memory Controller Error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/How_to_Troubleshoot_Memory_Errors.md"
    severity: "critical"
    
  - code: "tegra_xusb"
    pattern: "tegra[-_]xusb.*(?:disconnect|fail|error)"
    description: "USB controller / xHCI error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/USB_Device_Not_Recognized.md"
    severity: "warning"
    
  - code: "nvhost"
    pattern: "nvhost(?:_channel)?.*(?:err|fail|timeout)"
    description: "Host1x / NVHOST engine error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/NVHOST_Channel_Fault.md"
    severity: "warning"
    
  - code: "CAM_ERR_IOCTL"
    pattern: "CAM_ERR_IOCTL|Camera.*ioctl.*fail"
    description: "Camera IOCTL failure"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/Camera_Initialization_Failed.md"
    severity: "warning"
    
  - code: "jetson_clocks"
    pattern: "jetson_clocks.*(?:fail|denied|permission)"
    description: "jetson_clocks permission/scaling error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/jetson_clocks_Permission_Denied.md"
    severity: "info"
    
  - code: "bootloader"
    pattern: "bootloader.*(?:fail|timeout|crc)|RCM.*(?:fail|error)"
    description: "Bootloader / RCM mode error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/Bootloader_Brick_Recovery.md"
    severity: "critical"
    
  - code: "I2C"
    pattern: "i2c.*(?:timeout|nack|fail)|tegra_i2c.*err"
    description: "I2C bus error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/I2C_Bus_Troubleshooting.md"
    severity: "warning"
    
  - code: "GPU_FAULT"
    pattern: "GPU\\s+(?:fault|hang)|nvrm_gpu.*err"
    description: "GPU fault / hang"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/GPU_Hang_Recovery.md"
    severity: "critical"
    
  - code: "ETH"
    pattern: "eth\\d.*(?:link.?down|no.?carrier)|eqos.*err"
    description: "Ethernet link/carrier error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/Ethernet_Not_Working.md"
    severity: "info"
    
  - code: "FLASH"
    pattern: "flash.*(?:fail|error|crc)|tegraflash.*fail"
    description: "Flash / tegraflash error"
    suggested_docs:
      - "Edge/NVIDIA_Jetson/FAQs/Flash_Failure_Recovery.md"
    severity: "critical"
```

> 实施时先用这 10 个跑通机制，后续根据历史工单 `data/historical_replies.jsonl` 频次统计增量补充。

### 3.4 触发条件（默认保守）

```yaml
agents:
  diagnose:
    enabled: true
    trigger_qtypes: ["troubleshooting"]     # 仅故障类问题触发
    trigger_on_error_code_match: true      # 消息含已知错误码才触发
    max_matched_docs: 3
    error_codes_db: "data/error_codes.yaml"
```

若用户消息没匹配到任何错误码，diagnose 节点返回空 diagnostic_chunks，对 graph 无副作用（其他节点继续执行）。

### 3.5 降级与回滚

- `enabled: false` → 节点不挂入 graph，等价于不存在
- YAML 解析失败 → 节点捕获异常，记录日志，返回空 diagnostic_chunks
- Qdrant 检索失败 → 跳过文档检索，仅返回错误码提示信息

---

## 四、网络搜索 Agent 设计（`agent/agents/websearch_agent.py`）

### 4.1 输入输出契约

```python
class WebSearchInput(TypedDict):
    query: str                              # 来自 query_rewrite 的最终 query
    num_results: int                        # 默认 3
    allowed_domains: list[str] | None      # 可选域名白名单（如 seeedstudio.com）

class WebSearchOutput(TypedDict):
    websearch_chunks: list[dict]            # 转成 RetrievedChunk 格式注入 wiki_chunks
    provider_used: str                      # "tavily"
    search_latency_ms: int
    fallback_reason: str                    # 若不可用
```

### 4.2 实现决策（v1.0 修正）

**原方案（已废弃）**：DeepSeek Anthropic 端点 `web_search_20260209` server tool，LLM 自主决定调用。

**实测发现**：本项目使用的 AI 网关（`47.236.182.242/v1`）仅做协议转换，**不真正执行 server-side tool**——把 tool 定义透传给 LLM，LLM 返回 `tool_use`，但**没有 tool_result 回填**。已通过 curl 实测确认。

**调整后方案**：

- **websearch_agent**：单纯执行 [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)，不调 LLM 决策
- **是否触发搜索的决策**：由 `graph.py` 的 `reflect` 节点或上游条件边决定（wiki_chunks 为空 / reflect_score 低）
- **若需要 LLM 决策搜索策略**：可把 Tavily 注册为 LangChain function tool（`tools=[{"type":"function", "function":{"name":"tavily_search"}}]`），由 graph 中的 LLM 节点决定何时调用——这是 Phase 3 接 graph.py 时考虑的方向

```python
# Tavily 后端选择理由：
# - AI 原生、内置内容提取、citation-ready
# - 与 LangChain 集成最丝滑
# - 免费 1k/月，超出 $8/1k
# - 备选 Serper 便宜但需自己 fetch 内容
```

### 4.3 单后端架构（Tavily only）

```
WebSearchAgent.run(query)
  ↓
[1] 检查 enabled + TAVILY_API_KEY
  ↓
[2] POST https://api.tavily.com/search
  ├─ 最多返回 max_results 个结果
  ├─ allowed_domains 限定域名
  └─ search_depth="basic"（fast 模式，不调 LLM）
  ↓
[3] 解析结果 → 构造 websearch_chunks
  - chunk_text: "[来源: tavily]\n**title**\nURL\n\n<网页正文 2000 字>"
  - title: 网页 title
  - wiki_url: 实际 URL
  - category: "websearch"
  - score: Tavily 返回的相关度
  - image_urls/resource_urls: 空
  ↓
[4] 返回 websearch_chunks，调用方 prepend 到 wiki_chunks
```

### 4.4 Tavily 客户端实现

```python
import requests

def tavily_search(query: str, max_results: int = 3, domains: list[str], api_key: str):
    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": True,
    }
    if domains:
        payload["include_domains"] = domains
    resp = requests.post(
        "https://api.tavily.com/search",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    return [{
        "title": r["title"],
        "url": r["url"],
        "content": (r.get("raw_content") or r.get("content") or "")[:2000],
        "score": r.get("score", 0.7),
    } for r in resp.json().get("results", [])[:max_results]]
```

### 4.5 触发条件（默认保守）

```yaml
agents:
  websearch:
    enabled: false                        # 默认关闭，避免每个问题都搜
    trigger_on_empty_wiki_chunks: true    # Wiki 没命中才搜
    trigger_on_reflect_score_below: 0.4   # 反思评分低兜底
    max_results: 3
    allowed_domains:                       # 仅搜这些域名（避免无关结果）
      - "wiki.seeedstudio.com"
      - "seeedstudio.com"
      - "developer.nvidia.com"
      - "forums.developer.nvidia.com"
    tavily:
      api_key: "${TAVILY_API_KEY}"        # 需用户单独申请
      base_url: "https://api.tavily.com"
      search_depth: "basic"               # fast 模式
```

### 4.6 降级与回滚

- `enabled: false` → 节点不挂入 graph
- `TAVILY_API_KEY` 未配置 → 返回空 websearch_chunks + fallback_reason，不影响主流程
- API 429/超时/网络错 → 节点捕获异常，返回空（不阻塞）

### 4.7 未来扩展：LLM 决策 + Tavily 执行（Phase 3 可选）

若希望 LLM 自主决定是否搜，可把 Tavily 注册为 graph.py 中的 function tool：

```python
# 在 graph.py 中（Phase 3 实施）
from langchain_core.tools import tool

@tool
def tavily_search_tool(query: str) -> str:
    """通过 Tavily 搜索 Jetson 相关技术信息。"""
    from .agents.websearch_agent import WebSearchAgent
    agent = WebSearchAgent.from_config({...})
    out = agent.run(query)
    return "\n\n".join(c["chunk_text"] for c in out.websearch_chunks) or "未找到结果"

# 在 reflect 节点的 prompt 里把 tool 注册给 LLM
reflect_llm = base_llm.bind_tools([tavily_search_tool])
```

这是后续可选项，**v1.0 不实现**，先做"reflect 节点判分后条件触发 websearch_agent"的最小路径。

---

## 五、图片 Agent 设计（最低优先级，Phase 3 实现）

### 5.1 现状评估

- 解析阶段已提取 `image_urls` / `resource_urls`，存进 Qdrant payload
- `EmailRenderer` 在邮件模板里展示链接（最多 3 张）
- Streamlit UI 在 expander 里展示链接列表
- **缺**：用户看不到图片，点了链接才看到；VLM 解读原理图（Stage 3）未实现

### 5.2 最小改进（Phase 3a，前端工作）

`agent/email_renderer.py` 改造：
- 邮件体里把前 1 张图直接 inline 渲染（base64 download → markdown image）
- 解析图片尺寸，太大的（>2MB）跳过

`ui/app.py` 改造：
- expander 里把图直接渲染为缩略图（`st.image`），不用点链接

### 5.3 VLM 解读（Phase 3b，按需启动）

**触发条件**（写在文档里，不实现）：
- 用户开始上传截图（错误日志截图、原理图）
- 客服反馈"AI 答不出截图里的错误码"
- 月活问题中包含图片的比例 > 10%

**实现方案**（届时再写）：
- `agent/main.py` 加 `/upload_image` 接口（v1.0 文档第四节架构图已列）
- 用 GPT-4o 多模态或 Qwen2.5-VL 解读
- 解析后的文本注入 `wiki_chunks`

---

## 六、graph.py 改动方案

### 6.1 改动原则

- **最小侵入**：保留现有所有节点签名
- **向后兼容**：新节点默认 `enabled: false`，挂载时条件边全 `OFF`
- **不影响测试**：`tests/test_graph.py` 14 个用例不需改

### 6.2 具体改动点（伪代码）

#### 6.2.1 `_make_nodes` 工厂函数扩展

```python
def _make_nodes(retriever, router, generator, rewrite_client, graph_cfg, sag_retriever, 
                diagnose_agent=None, websearch_agent=None):
    # ... 现有代码 ...
    
    # ---------- 节点 7: diagnose_agent ----------
    def node_diagnose(state: AgentState) -> dict:
        if diagnose_agent is None or not diagnose_agent.enabled:
            return {"diagnostic_chunks": []}
        if state.get("question_type") not in diagnose_agent.trigger_qtypes:
            return {"diagnostic_chunks": []}
        try:
            out = diagnose_agent.run(
                user_message=state["user_message"],
                qtype=state.get("question_type", "general"),
            )
            logger.info(f"[diagnose] matched {len(out['matched_error_codes'])} codes, "
                       f"{len(out['diagnostic_chunks'])} chunks")
            return {"diagnostic_chunks": out["diagnostic_chunks"]}
        except Exception as e:
            logger.error(f"[diagnose] failed: {e}")
            return {"diagnostic_chunks": []}
    
    # ---------- 节点 8: websearch_agent ----------
    def node_websearch(state: AgentState) -> dict:
        if websearch_agent is None or not websearch_agent.enabled:
            return {"websearch_chunks": []}
        # 触发条件判断
        wiki = state.get("wiki_chunks", [])
        trigger_empty = (len(wiki) == 0) and websearch_agent.config["trigger_on_empty_wiki_chunks"]
        # reflect 评分需要 reflect 节点已跑，但我们要 prepend 到 wiki_chunks，所以放在 reflect 之前
        # 简化版：仅根据 wiki_chunks 空 / 长度判断
        if not trigger_empty:
            return {"websearch_chunks": []}
        try:
            queries = state.get("rewritten_queries") or [state["user_message"]]
            all_chunks = []
            for q in queries:
                out = websearch_agent.run(query=q, max_results=websearch_agent.config["max_results"])
                all_chunks.extend(out["websearch_chunks"])
            logger.info(f"[websearch] provider={websearch_agent.provider_used}, "
                       f"got {len(all_chunks)} chunks")
            return {"websearch_chunks": all_chunks}
        except Exception as e:
            logger.warning(f"[websearch] failed (non-fatal): {e}")
            return {"websearch_chunks": []}
    
    # ---------- 修改 node_retrieve: prepend diagnostic + websearch ----------
    def node_retrieve(state):
        # ... 现有逻辑 ...
        merged_chunks = ...
        # prepend diagnostic_chunks（最高优先级）
        diag = state.get("diagnostic_chunks", [])
        if diag:
            merged_chunks = diag + merged_chunks
        # prepend websearch_chunks（次高优先级，在 diagnostic 之后）
        ws = state.get("websearch_chunks", [])
        if ws:
            merged_chunks = ws + merged_chunks
        # ... 现有代码 ...
```

#### 6.2.2 `AgentState` 扩展

```python
class AgentState(TypedDict, total=False):
    # ... 现有字段 ...
    # 新增
    diagnostic_chunks: list[dict]     # 来自 diagnose_agent
    websearch_chunks: list[dict]      # 来自 websearch_agent
    websearch_provider: str           # 调试用
```

#### 6.2.3 `build_graph` 工厂扩展

```python
def build_graph(retriever=None, router=None, generator=None, rewrite_client=None,
                sag_retriever=None, diagnose_agent=None, websearch_agent=None):
    # ... 现有代码 ...
    
    # 构造新 agent（如果 enabled）
    cfg = get_config()
    if diagnose_agent is None:
        diag_cfg = cfg.get("agents", {}).get("diagnose", {})
        if diag_cfg.get("enabled", False):
            from .agents.diagnose_agent import DiagnoseAgent
            diagnose_agent = DiagnoseAgent(diag_cfg)
    
    if websearch_agent is None:
        ws_cfg = cfg.get("agents", {}).get("websearch", {})
        if ws_cfg.get("enabled", False):
            from .agents.websearch_agent import WebSearchAgent
            websearch_agent = WebSearchAgent(ws_cfg)
    
    nodes = _make_nodes(retriever, router, generator, rewrite_client, cfg,
                       sag_retriever, diagnose_agent, websearch_agent)
    
    g = StateGraph(AgentState)
    # ... 现有节点添加 ...
    g.add_node("diagnose_agent", nodes["node_diagnose"])
    g.add_node("websearch_agent", nodes["node_websearch"])
    
    # 边：放在 retrieve_historical 之前
    g.add_edge("retrieve_historical", "diagnose_agent")
    g.add_edge("diagnose_agent", "websearch_agent")
    g.add_edge("websearch_agent", "reflect")
    
    return g.compile()
```

#### 6.2.4 `TechSupportChat.__init__` 透传

```python
class TechSupportChat:
    def __init__(self, ..., diagnose_agent=None, websearch_agent=None):
        # ... 现有 ...
        self.diagnose_agent = diagnose_agent
        self.websearch_agent = websearch_agent
    
    def _get_graph(self):
        if self._graph is None:
            self._graph = build_graph(
                ..., 
                diagnose_agent=self.diagnose_agent,
                websearch_agent=self.websearch_agent,
            )
```

---

## 七、配置改动（`config.yaml`）

```yaml
# 追加在文件末尾
agents:
  # ===== 诊断 Agent =====
  diagnose:
    enabled: false                        # 默认关闭，配置后启用
    trigger_qtypes: ["troubleshooting"]
    trigger_on_error_code_match: true
    max_matched_docs: 3
    error_codes_db: "data/error_codes.yaml"
    
  # ===== 网络搜索 Agent =====
  websearch:
    enabled: false                        # 默认关闭，配置后启用
    provider: "deepseek"                  # deepseek | tavily | auto
    trigger_on_empty_wiki_chunks: true
    trigger_on_reflect_score_below: 0.4
    max_results: 3
    allowed_domains:                       # 仅搜这些域名（避免无关结果）
      - "wiki.seeedstudio.com"
      - "seeedstudio.com"
      - "developer.nvidia.com"
      - "forums.developer.nvidia.com"
    deepseek:
      api_key: "${DEEPSEEK_API_KEY}"      # 复用现有 key
      base_url: "https://api.deepseek.com/anthropic"
      model: "deepseek-v4-flash"          # 搜索用 flash 即可
      max_uses: 3                         # 每次最多调几次搜索
    tavily:
      api_key: "${TAVILY_API_KEY}"        # 需用户单独申请
      base_url: "https://api.tavily.com"
      search_depth: "basic"               # fast 模式
```

---

## 八、文件结构

新增/修改的文件：

```
tech-support-agent/
├── agent/
│   ├── agents/                           ← 新增目录
│   │   ├── __init__.py                   ← 新增
│   │   ├── diagnose_agent.py             ← 新增（约 200 行）
│   │   └── websearch_agent.py            ← 新增（约 250 行，含双后端）
│   ├── graph.py                          ← 修改（+50 行）
│   └── chat.py                           ← 修改（+10 行）
├── data/
│   └── error_codes.yaml                  ← 新增（约 80 行）
├── config.yaml                           ← 修改（+30 行）
├── docs/
│   └── MULTI_AGENT_INTEGRATION_PLAN.md   ← 本文档
└── tests/
    ├── test_diagnose_agent.py            ← 新增（约 100 行）
    └── test_websearch_agent.py           ← 新增（约 100 行）
```

---

## 九、测试策略

### 9.1 单元测试（mock LLM / mock API）

#### `tests/test_diagnose_agent.py`
- `test_regex_match_mc_err()`：MC_ERR 错误码匹配
- `test_regex_no_match()`：无关消息不匹配
- `test_yaml_load()`：YAML 配置加载
- `test_qdrant_retrieve_mock()`：mock Qdrant 检索返回
- `test_disabled_noop()`：enabled=false 时返回空
- `test_qtype_filter()`：仅 troubleshooting 触发

#### `tests/test_websearch_agent.py`
- `test_provider_deepseek_mock()`：mock anthropic client
- `test_provider_tavily_mock()`：mock requests.post
- `test_provider_auto_fallback()`：deepseek 不可用降级到 tavily
- `test_disabled_noop()`：enabled=false 时返回空
- `test_empty_results_noop()`：搜索无结果时优雅降级

### 9.2 集成测试（`tests/regression_graph.py` 扩展）

- `T8_diagnose_agent_in_graph()`：诊断 Agent 启用后，错误码命中 → diagnostic_chunks prepend
- `T9_websearch_agent_in_graph()`：websearch 启用后，wiki_chunks 为空 → 自动触发搜索
- `T10_agents_disabled_unchanged()`：全部 enabled=false 时，graph 行为与原版一致

### 9.3 端到端验证（手动）

- 真实工单："dmesg 显示 MC_ERR 0x14" → 验证诊断节点触发 + 邮件回复含 MC_ERR 排查文档
- 真实工单："reComputer 新型号 J999 JetPack 版本" → 验证 websearch 触发 + 邮件含 NVIDIA 官方网页链接
- 回归测试：随机抽 10 条历史工单，对比启用前/后的邮件回复质量

---

## 十、风险评估与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 默认 enabled=true 误开启 | 中 | 高（每条问题都触发） | 默认 `enabled: false`，必须显式开启 |
| DeepSeek 429 限速（v4-flash 2500 并发）| 低 | 中 | `agent` 捕获异常，返回空 chunks，不阻塞 |
| Tavily 免费额度耗尽 | 中 | 低 | 触发频率低（仅 wiki 空时），监控额度 |
| 错误码 YAML 误匹配（高误报）| 中 | 中 | `confidence` 字段加权；人工 review 10 个错误码基线 |
| graph.py 改动引入回归 | 中 | 高 | 默认 disabled + 14 个原单测不需改 + 新增 T10 回归测试 |
| Anthropic SDK 与现有 openai SDK 冲突 | 低 | 中 | 用 `from anthropic import Anthropic` 隔离命名空间 |
| 网络搜索结果质量低 | 中 | 低 | 限定域名白名单（`allowed_domains`）+ 顶层 3 条 |
| 诊断 Agent 误判为故障文档 | 低 | 中 | `trigger_qtypes=["troubleshooting"]` 限定范围 |

---

## 十一、实施步骤（分批）

### 11.1 Phase 1（立即，零风险）

- ✅ 写本文档
- ⏳ User review 本文档
- ⏳ User 确认后，落地代码骨架

### 11.2 Phase 2（1-2 天，低风险）

1. 创建 `agent/agents/__init__.py`
2. 写 `data/error_codes.yaml`（10 个错误码）
3. 写 `agent/agents/diagnose_agent.py` + 单元测试
4. 写 `agent/agents/websearch_agent.py`（双后端）+ 单元测试
5. **不接 graph.py**（先 standalone 验证）

### 11.3 Phase 3（2-3 天，中风险）

1. 修改 `agent/graph.py`：新增 2 个节点 + 3 条边
2. 修改 `agent/chat.py`：透传 agent
3. 修改 `config.yaml`：新增 `agents:` 节
4. 跑 `tests/regression_graph.py` 全部 PASS
5. **默认 `enabled: false`**，人工跑通

### 11.4 Phase 4（按需，高价值）

1. 配置 `agents.websearch.enabled: true` + provider=deepseek
2. 用 5 条真实工单验证 websearch 触发
3. 抽 30 条工单做 A/B 对比（websearch on/off）
4. 根据结果决定是否启用 diagnose Agent

### 11.5 Phase 5（未来，按需）

1. 图片 Agent inline 渲染（前端）
2. VLM 解读原理图（GPT-4o）
3. 飞书机器人（IM 内对话）

---

## 十二、回滚方案

如果 Phase 3/4 上线后出问题，回滚只需：

```bash
# 1. 改 config.yaml
agents:
  diagnose:
    enabled: false
  websearch:
    enabled: false

# 2. 重启 agent.main
python -m agent.main

# 即可恢复原版 graph 行为
```

新代码保留在 `agent/agents/`，不删。后续修复 bug 后重新开启。

---

## 十三、参考文档

- [LangGraph Handoffs 官方教程](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs-customer-support)
- [LangGraph 0.2.50 子图文档](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangGraph Supervisor Pattern 2026](https://myengineeringpath.dev/genai-engineer/langgraph-multi-agent/)
- [DeepSeek Anthropic API 文档](https://api-docs.deepseek.com/guides/anthropic_api)
- [DeepSeek web_search 实测](https://musaab.io/posts/2026/deepseek-search/)
- [Tavily vs Serper 对比](https://fastcrw.com/alternatives/tavily-vs-serper)
- [PrAtHaM-0707/Agentic-Support-AI](https://github.com/PrAtHaM-0707/Agentic-Support-AI) — 多 Agent 参考实现

---

*文档作者：Cursor AI Agent*
*下次 review：User review 通过后启动 Phase 2*
