"""多轮对话管理（Stage 2: 委托给 LangGraph 工作流）

- ConversationContext / Message 保持不变（FastAPI main.py 在用）
- TechSupportChat.chat() 改为 graph.invoke() 包装
- _text_search / _suggest_followup 保留为兼容性占位
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Optional

# 确保环境变量已加载（.env 文件）
# 使用 os.environ[...] = v 强制覆盖，避免 shell 中残留旧变量导致 .env 失效
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

from .agents.diagnose_agent import DiagnoseAgent
from .agents.websearch_agent import WebSearchAgent
from .generator import AnswerGenerator
from .retriever import QdrantRetriever, RetrievedChunk
from .router import QuestionRouter, QuestionType
from .sag_retriever import SAGRetriever

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str          # "user" | "assistant"
    content: str
    timestamp: str = ""
    sources: List[Dict] = field(default_factory=list)
    question_type: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%H:%M")


@dataclass
class ConversationContext:
    """单个会话的上下文"""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    category: str = ""       # 当前选中的产品分类
    last_question_type: QuestionType = QuestionType.GENERAL

    def history_text(self, last_n: int = 6) -> str:
        """返回最近 N 条对话的文本（用于传给 LLM）"""
        recent = self.messages[-last_n:] if len(self.messages) > last_n else self.messages
        lines = []
        for m in recent:
            role = "用户" if m.role == "user" else "助理"
            lines.append(f"{role}：{m.content}")
        return "\n".join(lines)

    def add_user(self, content: str) -> None:
        self.messages.append(Message(role="user", content=content))

    def add_assistant(self, content: str, sources: Optional[List[Dict]] = None, question_type: str = "") -> None:
        self.messages.append(Message(
            role="assistant",
            content=content,
            sources=sources or [],
            question_type=question_type,
        ))


class TechSupportChat:
    """技术支持 Agent（多轮对话）。

    Stage 2 改动：内部不再直接调用 retriever/generator，
    而是把 user_message + history + category 喂给 LangGraph 工作流，
    由 graph.py 中的 query_rewrite → classify → retrieve →
    [retrieve_historical] → reflect → generate 编排。
    """

    def __init__(
        self,
        retriever: QdrantRetriever | None = None,
        router: QuestionRouter | None = None,
        generator: AnswerGenerator | None = None,
        embedder: Any = None,
        sag_retriever: SAGRetriever | None = None,
        diagnose_agent: DiagnoseAgent | None = None,
        websearch_agent: WebSearchAgent | None = None,
    ):
        self.retriever = retriever if retriever is not None else QdrantRetriever.from_config()
        self.router = router if router is not None else QuestionRouter.from_config()
        self.generator = generator if generator is not None else AnswerGenerator.from_config()
        self.sag_retriever = sag_retriever
        self.embedder = embedder
        # Phase 3 子 Agent（按 agents.*.enabled 决定，None = disabled）
        self.diagnose_agent = diagnose_agent
        self.websearch_agent = websearch_agent
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from .graph import build_graph, LANGGRAPH_AVAILABLE
            if not LANGGRAPH_AVAILABLE:
                raise RuntimeError("langgraph not installed, cannot use graph pipeline")
            self._graph = build_graph(
                retriever=self.retriever,
                router=self.router,
                generator=self.generator,
                sag_retriever=self.sag_retriever,
                diagnose_agent=self.diagnose_agent,
                websearch_agent=self.websearch_agent,
            )
        return self._graph

    def _fallback_chat(self, ctx: ConversationContext, user_message: str) -> Dict[str, Any]:
        """降级路径：不走 LangGraph，直接 retriever + generator（Qdrant + LLM）。"""
        qtype = self.router.classify(user_message, ctx.history_text(last_n=6))
        try:
            hits = self.retriever.retrieve(user_message, category_filter=ctx.category or None)
            qv = hits[: self.retriever.top_k]
        except Exception:
            qv = []
        chunks = list(qv)
        result = self.generator.generate(
            question=user_message,
            chunks=chunks,
            history=ctx.history_text(last_n=6),
            qtype=qtype,
            historical_replies=[],
        )
        ctx.last_question_type = qtype
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "question_type": qtype.value,
            "image_urls": result.get("image_urls", []),
            "resource_urls": result.get("resource_urls", []),
            "needs_followup": False,
            "followup_hint": "",
            "fallback_reason": "langgraph_unavailable",
        }

    def chat(
        self,
        ctx: ConversationContext,
        user_message: str,
        embed_query: bool = True,  # 保留参数位（向后兼容）
    ) -> Dict[str, Any]:
        """处理一条用户消息，返回 dict（保持与 Stage 1 兼容的字段集）。

        字段：
            answer, sources, question_type, image_urls, resource_urls,
            needs_followup, followup_hint, fallback_reason (新增)
        """
        ctx.add_user(user_message)
        try:
            graph = self._get_graph()
        except RuntimeError as e:
            if "langgraph" in str(e):
                logger.warning(f"langgraph unavailable, using fallback: {e}")
                result = self._fallback_chat(ctx, user_message)
                ctx.add_assistant(
                    content=result["answer"],
                    sources=result["sources"],
                    question_type=result["question_type"],
                )
                return result
            raise

        initial_state = {
            "user_message": user_message,
            "history_text": ctx.history_text(last_n=6),
            "category": ctx.category,
            "rewrite_iterations": 0,
        }
        try:
            final_state = graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"graph.invoke failed: {e}", exc_info=True)
            # 极端降级：返回错误提示，保持 API 兼容
            err_answer = "抱歉，处理您的问题时遇到内部错误，请稍后重试。"
            ctx.add_assistant(content=err_answer, sources=[], question_type="general")
            return {
                "answer": err_answer,
                "sources": [],
                "question_type": "general",
                "image_urls": [],
                "resource_urls": [],
                "needs_followup": False,
                "followup_hint": "",
                "fallback_reason": f"graph_invoke_failed: {e}",
            }

        answer = final_state.get("answer") or "（无回答）"
        sources = final_state.get("sources") or []
        qtype_str = final_state.get("question_type") or "general"
        try:
            ctx.last_question_type = QuestionType(qtype_str)
        except ValueError:
            ctx.last_question_type = QuestionType.GENERAL

        ctx.add_assistant(
            content=answer,
            sources=sources,
            question_type=qtype_str,
        )

        return {
            "answer": answer,
            "sources": sources,
            "question_type": qtype_str,
            "image_urls": final_state.get("image_urls", []),
            "resource_urls": final_state.get("resource_urls", []),
            "needs_followup": final_state.get("needs_followup", False),
            "followup_hint": final_state.get("followup_hint", ""),
            "fallback_reason": final_state.get("fallback_reason", ""),
        }

    # ---- 占位方法（向后兼容旧调用方）----
    def _text_search(self, query: str) -> list[RetrievedChunk]:
        """Stage 1 的文本降级检索。Stage 2 已不需要，保留仅为签名兼容。"""
        return []

    def _suggest_followup(self, chunks: list[RetrievedChunk]) -> str:
        """Stage 1 的追问建议。Stage 2 由 graph 内 _FOLLOWUP_HINTS 接管。"""
        return "请问当前设备的状态指示灯是什么情况？（电源灯、网络灯）"
