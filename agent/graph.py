"""LangGraph Agentic RAG 工作流 (Stage 2)

图结构：
    START
      └─ query_rewrite  (LLM 改写 + 代词消解；失败时降级为原 query)
         └─ classify     (复用 QuestionRouter)
            └─ retrieve  (Qdrant 向量检索，多 query 合并去重)
               └─ (条件: qtype ∈ {TROUBLE, COMPAT, HOWTO}) retrieve_historical
                  └─ reflect  (LLM 自评 "文档是否够用？")
                     └─ (条件) generate | query_rewrite (loop, 限 max_rewrites)
                        └─ generate  (AnswerGenerator)
                           └─ END
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

# .env 强制覆盖（与其他模块一致）
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from .config import get_config
from .generator import AnswerGenerator
from .retriever import QdrantRetriever, RetrievedChunk, _expand_query
from .router import QuestionRouter, QuestionType

logger = logging.getLogger(__name__)


# ============================================================
# 状态定义
# ============================================================

def _merge_unique_chunks(existing: list[dict], new: list[RetrievedChunk]) -> list[dict]:
    """合并去重：按 doc_id+chunk_text 前 80 字符去重"""
    seen: set[tuple[str, str]] = set()
    for c in existing:
        seen.add((c.get("doc_id", ""), c.get("chunk_text", "")[:80]))
    for c in new:
        key = (c.doc_id, c.chunk_text[:80])
        if key in seen:
            continue
        seen.add(key)
        existing.append({
            "chunk_text": c.chunk_text,
            "title": c.title,
            "wiki_url": c.wiki_url,
            "category": c.category,
            "doc_id": c.doc_id,
            "score": c.score,
            "image_urls": c.image_urls,
            "resource_urls": c.resource_urls,
        })
    return existing


class AgentState(TypedDict, total=False):
    # ----- 输入 -----
    user_message: str
    history_text: str          # 来自 ConversationContext.history_text()
    category: str              # 来自 ctx.category
    # ----- 中间状态 -----
    rewritten_queries: list[str]
    question_type: str
    wiki_chunks: list[dict]        # RetrievedChunk 序列化的 dict 列表
    historical_chunks: list[dict]
    reflection_score: float
    reflection_reason: str
    rewrite_iterations: int
    # ----- 输出 -----
    answer: str
    sources: list[dict]
    image_urls: list[str]
    resource_urls: list[str]
    needs_followup: bool
    followup_hint: str
    # ----- 错误/降级 -----
    fallback_reason: str


# ============================================================
# 改写 / 反思 LLM 客户端（独立 client，避免污染 generator 的 temperature）
# ============================================================

_REWRITE_PROMPT = """你是一个查询改写器。任务：
1. 解析对话历史中的代词（"它"、"这个"、"上面那个"）→ 替换为具体对象
2. 如果原问题已经清晰、无需改写，原样返回
3. 仅当问题明显是多跳/复合查询（如"A 和 B 是否兼容"）时，拆成多个子问题

只返回一个 JSON 数组，元素是改写后的查询字符串（1-2 个）。
示例：
- 输入："reComputer J401 功耗多少？" → ["reComputer J401 功耗"]
- 输入："那它支持哪个 JetPack？" (历史: reComputer J401) → ["reComputer J401 支持哪个 JetPack 版本"]
- 输入："A 能不能接 B？" → ["A 能不能接 B", "A 的接口规格", "B 的接口规格"]

对话历史：
{history}

用户当前问题：{question}

只返回 JSON 数组，不要其他文字："""


_REFLECT_PROMPT = """你是一个检索质量评估器。判断【检索到的文档】是否足以回答【用户问题】。

评分标准（0-1 浮点数）：
- 1.0: 文档直接包含完整答案（型号/参数/步骤）
- 0.7-0.9: 文档部分相关，能拼出答案
- 0.4-0.6: 文档相关但缺少关键信息
- 0.0-0.3: 文档与问题无关或完全缺失

返回 JSON：
{{"score": 0.0, "reason": "一句话理由", "need_rewrite": true/false}}

用户问题：{question}
问题类型：{qtype}
检索到的文档摘要：
{context_summary}

只返回 JSON："""


class _RewriteClient:
    """轻量 LLM 客户端，专门做改写和反思。temperature=0，max_tokens 小。"""

    def __init__(self, model: str, api_key: str, base_url: str | None,
                 max_tokens: int = 200):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.max_tokens = max_tokens

    @classmethod
    def from_config(cls) -> "_RewriteClient":
        cfg = get_config()
        g = cfg.get("graph", {})
        provider = cfg.get("provider", "openai").lower()
        if provider == "deepseek":
            dc = cfg.get("deepseek", {})
            return cls(
                model=g.get("reflection_model") or dc.get("llm_model", "deepseek-chat"),
                api_key=dc.get("api_key", ""),
                base_url=dc.get("base_url", "https://api.deepseek.com/v1"),
                max_tokens=g.get("reflection_max_tokens", 200),
            )
        oc = cfg["openai"]
        return cls(
            model=g.get("reflection_model") or oc.get("llm_model", "glm-5.2"),
            api_key=oc.get("api_key", ""),
            base_url=oc.get("base_url") or None,
            max_tokens=g.get("reflection_max_tokens", 200),
        )

    def rewrite(self, question: str, history: str) -> list[str]:
        """改写 query；失败时返回 [原 question]。"""
        if not question.strip():
            return [question]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个查询改写器，只返回 JSON 数组。"},
                    {"role": "user", "content": _REWRITE_PROMPT.format(
                        history=history or "（无）",
                        question=question,
                    )},
                ],
                temperature=0.0,
                max_tokens=self.max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            queries = json.loads(text)
            if isinstance(queries, list) and queries:
                # 兜底：确保所有元素都是 str 且非空
                qs = [str(q).strip() for q in queries if str(q).strip()]
                return qs[:2] if qs else [question]
            return [question]
        except Exception as e:
            logger.warning(f"query_rewrite failed, using original: {e}")
            return [question]

    def reflect(self, question: str, qtype: str,
                context_summary: str) -> tuple[float, str, bool]:
        """自评检索质量。返回 (score, reason, need_rewrite)。失败时给 (0.5, '', False)。"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是检索质量评估器，只返回 JSON。"},
                    {"role": "user", "content": _REFLECT_PROMPT.format(
                        question=question,
                        qtype=qtype,
                        context_summary=context_summary,
                    )},
                ],
                temperature=0.0,
                max_tokens=self.max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            data = json.loads(text)
            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            reason = str(data.get("reason", "")).strip()
            need_rewrite = bool(data.get("need_rewrite", False))
            return score, reason, need_rewrite
        except Exception as e:
            logger.warning(f"reflect failed, defaulting to score=0.5: {e}")
            return 0.5, "", False


# ============================================================
# 节点实现
# ============================================================

# 历史回复优先触发的 qtype
_HISTORICAL_QTYPES = {
    QuestionType.TROUBLESHOOTING,
    QuestionType.COMPATIBILITY,
    QuestionType.HOWTO,
}


def _make_nodes(retriever: QdrantRetriever,
                router: QuestionRouter,
                generator: AnswerGenerator,
                rewrite_client: _RewriteClient,
                graph_cfg: dict):
    """工厂：闭包绑定依赖，返回 6 个节点函数。"""

    cfg_max_rewrites = int(graph_cfg.get("max_rewrites", 2))
    cfg_threshold = float(graph_cfg.get("reflection_threshold", 0.7))
    cfg_enable_rewrite = bool(graph_cfg.get("enable_query_rewrite", True))
    cfg_enable_reflect = bool(graph_cfg.get("enable_reflection", True))
    cfg_enable_historical = bool(graph_cfg.get("enable_historical", True))

    # ---------- embedder 懒加载（与 chat.py 同款） ----------
    _EMBEDDER = None

    def _get_embedder():
        nonlocal _EMBEDDER
        if _EMBEDDER is None:
            from pipeline.embedder import get_embedder
            emb_cfg = get_config().get("embedding", {})
            emb_provider = emb_cfg.get("provider", "local")
            if emb_provider == "local":
                _EMBEDDER = get_embedder(
                    provider=emb_provider,
                    model=emb_cfg.get("local_model", "BAAI/bge-m3"),
                    batch_size=emb_cfg.get("local_batch_size", 16),
                    dimensions=0,
                )
            elif emb_provider == "siliconflow":
                sf = emb_cfg.get("siliconflow", {})
                _EMBEDDER = get_embedder(
                    provider=emb_provider,
                    api_key=sf.get("api_key", "") or os.environ.get("SILICONFLOW_API_KEY", ""),
                    model=sf.get("model", "BAAI/bge-m3"),
                    batch_size=sf.get("batch_size", 1000),
                    dimensions=1024,
                )
            else:
                _EMBEDDER = get_embedder(
                    provider=emb_provider,
                    model=emb_cfg.get("openai_model", "text-embedding-3-small"),
                    batch_size=1000,
                    dimensions=emb_cfg.get("openai_dimensions", 1024),
                )
        return _EMBEDDER

    def _embed(q: str) -> list[float]:
        emb = _get_embedder()
        return emb.embed([_expand_query(q)])[0]

    # ---------- 节点 1: query_rewrite ----------
    def node_query_rewrite(state: AgentState) -> dict:
        if not cfg_enable_rewrite:
            return {"rewritten_queries": [state["user_message"]], "rewrite_iterations": 0}
        qs = rewrite_client.rewrite(state["user_message"], state.get("history_text", ""))
        logger.info(f"[query_rewrite] {state['user_message']!r} -> {qs}")
        return {
            "rewritten_queries": qs,
            "rewrite_iterations": state.get("rewrite_iterations", 0) + 1,
        }

    # ---------- 节点 2: classify ----------
    def node_classify(state: AgentState) -> dict:
        qtype = router.classify(
            question=state["user_message"],
            history=state.get("history_text", ""),
        )
        logger.info(f"[classify] qtype={qtype.value}")
        return {"question_type": qtype.value}

    # ---------- 节点 3: retrieve ----------
    def node_retrieve(state: AgentState) -> dict:
        queries = state.get("rewritten_queries") or [state["user_message"]]
        category = state.get("category") or None
        merged: list[RetrievedChunk] = []
        try:
            for q in queries:
                qv = _embed(q)
                hits = retriever.retrieve_vector(qv, category_filter=category)
                merged.extend(hits)
            # 按 score 降序，截断到 top_k * 2 防止过大
            merged.sort(key=lambda c: c.score, reverse=True)
            merged = merged[: max(retriever.top_k * 2, 10)]
            wiki_dicts: list[dict] = []
            for c in merged:
                wiki_dicts.append({
                    "chunk_text": c.chunk_text,
                    "title": c.title,
                    "wiki_url": c.wiki_url,
                    "category": c.category,
                    "doc_id": c.doc_id,
                    "score": c.score,
                    "image_urls": c.image_urls,
                    "resource_urls": c.resource_urls,
                })
            logger.info(f"[retrieve] {len(wiki_dicts)} chunks from {len(queries)} queries")
            return {"wiki_chunks": wiki_dicts}
        except Exception as e:
            logger.error(f"[retrieve] failed: {e}")
            return {"wiki_chunks": [], "fallback_reason": f"retrieve_failed: {e}"}

    # ---------- 节点 4: retrieve_historical ----------
    def node_retrieve_historical(state: AgentState) -> dict:
        if not cfg_enable_historical:
            return {"historical_chunks": []}
        if not getattr(retriever, "historical_collection_name", None):
            return {"historical_chunks": []}
        try:
            qtype = QuestionType(state.get("question_type", "general"))
            if qtype not in _HISTORICAL_QTYPES:
                logger.info(f"[historical] skip, qtype={qtype.value} not in trigger set")
                return {"historical_chunks": []}
            qv = _embed(state["user_message"])
            hits = retriever.retrieve_historical(qv)
            dicts = [{
                "chunk_text": c.chunk_text,
                "title": c.title,
                "wiki_url": c.wiki_url,
                "category": c.category,
                "doc_id": c.doc_id,
                "score": c.score,
                "image_urls": c.image_urls,
                "resource_urls": c.resource_urls,
            } for c in hits]
            logger.info(f"[historical] {len(dicts)} historical replies")
            return {"historical_chunks": dicts}
        except Exception as e:
            logger.error(f"[historical] failed: {e}")
            return {"historical_chunks": []}

    # ---------- 节点 5: reflect ----------
    def node_reflect(state: AgentState) -> dict:
        if not cfg_enable_reflect:
            return {"reflection_score": 1.0, "reflection_reason": "reflection disabled", "need_rewrite_fallback": False}
        wiki = state.get("wiki_chunks", [])
        # 构造上下文摘要（前 3 条，各 200 字）
        summary_lines = []
        for i, c in enumerate(wiki[:3], 1):
            text = (c.get("chunk_text") or "").strip()[:200]
            summary_lines.append(f"[{i}] {c.get('title','')}: {text}")
        summary = "\n".join(summary_lines) or "（无检索结果）"
        score, reason, need_rewrite = rewrite_client.reflect(
            question=state["user_message"],
            qtype=state.get("question_type", "general"),
            context_summary=summary,
        )
        logger.info(f"[reflect] score={score:.2f} need_rewrite={need_rewrite} reason={reason!r}")
        return {"reflection_score": score, "reflection_reason": reason}

    # ---------- 节点 6: generate ----------
    _FOLLOWUP_HINTS = [
        "请问当前设备的状态指示灯是什么情况？（电源灯、网络灯）",
        "请问您遇到问题的具体表现是什么？（报错信息、现象描述）",
        "请问已经尝试过哪些排查步骤了？",
    ]

    def node_generate(state: AgentState) -> dict:
        # 把 dict 还原为 RetrievedChunk 供 generator 使用
        wiki_objs = [RetrievedChunk(**c) for c in state.get("wiki_chunks", [])]
        hist_objs = [RetrievedChunk(**c) for c in state.get("historical_chunks", [])]
        try:
            qtype = QuestionType(state.get("question_type", "general"))
        except ValueError:
            qtype = QuestionType.GENERAL
        try:
            result = generator.generate(
                question=state["user_message"],
                chunks=wiki_objs,
                history=state.get("history_text", ""),
                qtype=qtype,
                historical_replies=hist_objs,
            )
        except Exception as e:
            logger.error(f"[generate] failed: {e}")
            return {
                "answer": "抱歉，生成回答时遇到问题，请稍后重试。",
                "sources": [],
                "image_urls": [],
                "resource_urls": [],
                "needs_followup": False,
                "followup_hint": "",
                "fallback_reason": f"generate_failed: {e}",
            }
        needs_followup = qtype == QuestionType.TROUBLESHOOTING and len(wiki_objs) > 0
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "image_urls": result["image_urls"],
            "resource_urls": result["resource_urls"],
            "needs_followup": needs_followup,
            "followup_hint": _FOLLOWUP_HINTS[0] if needs_followup else "",
        }

    # ---------- 条件边 ----------
    def route_after_classify(state: AgentState) -> str:
        """classify 后：所有路径都进 retrieve，retrieve 之后历史分支由 retrieve 内部判断。"""
        return "retrieve"

    def route_after_retrieve(state: AgentState) -> str:
        """retrieve 后：决定是否走 historical。"""
        if not cfg_enable_historical:
            return "reflect"
        if not getattr(retriever, "historical_collection_name", None):
            return "reflect"
        try:
            qtype = QuestionType(state.get("question_type", "general"))
        except ValueError:
            qtype = QuestionType.GENERAL
        return "retrieve_historical" if qtype in _HISTORICAL_QTYPES else "reflect"

    def route_after_reflect(state: AgentState) -> str:
        """reflect 后：score 够 OR 已达 max_rewrites → generate；否则 → query_rewrite。"""
        if not cfg_enable_reflect:
            return "generate"
        score = float(state.get("reflection_score", 0.0))
        iterations = int(state.get("rewrite_iterations", 0))
        if score >= cfg_threshold:
            return "generate"
        if iterations >= cfg_max_rewrites:
            logger.info(f"[reflect→generate] max_rewrites={iterations} reached, force generate")
            return "generate"
        return "query_rewrite"

    return {
        "node_query_rewrite": node_query_rewrite,
        "node_classify": node_classify,
        "node_retrieve": node_retrieve,
        "node_retrieve_historical": node_retrieve_historical,
        "node_reflect": node_reflect,
        "node_generate": node_generate,
        "route_after_classify": route_after_classify,
        "route_after_retrieve": route_after_retrieve,
        "route_after_reflect": route_after_reflect,
    }


# ============================================================
# 图编译
# ============================================================

_compiled_graph = None


def build_graph(retriever: QdrantRetriever | None = None,
                router: QuestionRouter | None = None,
                generator: AnswerGenerator | None = None,
                rewrite_client: _RewriteClient | None = None):
    """构造并编译 LangGraph。返回 compiled graph（可调用 .invoke()）。"""
    cfg = get_config().get("graph", {})
    retriever = retriever or QdrantRetriever.from_config()
    router = router or QuestionRouter.from_config()
    generator = generator or AnswerGenerator.from_config()
    rewrite_client = rewrite_client or _RewriteClient.from_config()

    nodes = _make_nodes(retriever, router, generator, rewrite_client, cfg)

    g = StateGraph(AgentState)
    g.add_node("query_rewrite", nodes["node_query_rewrite"])
    g.add_node("classify", nodes["node_classify"])
    g.add_node("retrieve", nodes["node_retrieve"])
    g.add_node("retrieve_historical", nodes["node_retrieve_historical"])
    g.add_node("reflect", nodes["node_reflect"])
    g.add_node("generate", nodes["node_generate"])

    g.add_edge(START, "query_rewrite")
    g.add_edge("query_rewrite", "classify")
    g.add_conditional_edges("classify", nodes["route_after_classify"],
                            {"retrieve": "retrieve"})
    g.add_conditional_edges("retrieve", nodes["route_after_retrieve"],
                            {"retrieve_historical": "retrieve_historical",
                             "reflect": "reflect"})
    g.add_edge("retrieve_historical", "reflect")
    g.add_conditional_edges("reflect", nodes["route_after_reflect"],
                            {"generate": "generate",
                             "query_rewrite": "query_rewrite"})
    g.add_edge("generate", END)

    return g.compile()


def get_compiled_graph():
    """单例：第一次调用编译并缓存。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def reset_compiled_graph():
    """测试用：重置单例。"""
    global _compiled_graph
    _compiled_graph = None
