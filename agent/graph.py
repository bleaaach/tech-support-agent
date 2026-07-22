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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

# .env 强制覆盖（与其他模块一致）
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    END = START = None  # type: ignore
    StateGraph = None   # type: ignore
from openai import OpenAI

from .agents.diagnose_agent import DiagnoseAgent
from .agents.websearch_agent import WebSearchAgent
from .config import get_config
from .generator import AnswerGenerator
from .retriever import QdrantRetriever, RetrievedChunk, _expand_query
from .router import QuestionRouter, QuestionType
from .sag_retriever import SAGRetriever, rrf_fuse

logger = logging.getLogger(__name__)

def _safe_strip_prefix(text: str, prefix: str) -> str:
    """Python 3.8 兼容的 removeprefix"""
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def _strip_json_fence(text: str) -> str:
    """去掉 ```json ... ``` 或 ``` ... ``` 包裹，兼容 Python 3.8"""
    text = text.strip()
    # 去掉前缀 ```json 或 ```
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
            break
    # 去掉后缀 ```
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    return text.strip()


# ============================================================
# 状态定义
# ============================================================

def _safe_init_agents(agents_cfg: dict) -> tuple:
    """按 config 构造 DiagnoseAgent / WebSearchAgent 实例（异常时回退为 None）。

    任何 agent 构造失败不应阻塞 graph 构建，仅记录 warning。
    """
    diagnose_agent = None
    websearch_agent = None

    diag_cfg = agents_cfg.get("diagnose", {}) or {}
    if diag_cfg.get("enabled", False):
        try:
            diagnose_agent = DiagnoseAgent.from_config(diag_cfg)
            logger.info(f"[graph] DiagnoseAgent enabled: trigger_qtypes={diagnose_agent.trigger_qtypes}")
        except Exception as e:
            logger.warning(f"[graph] DiagnoseAgent init failed, disabled: {e}")

    ws_cfg = agents_cfg.get("websearch", {}) or {}
    if ws_cfg.get("enabled", False):
        try:
            websearch_agent = WebSearchAgent.from_config(ws_cfg)
            avail, reason = websearch_agent.available()
            logger.info(f"[graph] WebSearchAgent enabled: available={avail}, reason={reason}")
        except Exception as e:
            logger.warning(f"[graph] WebSearchAgent init failed, disabled: {e}")

    return diagnose_agent, websearch_agent

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
    rewritten_queries: List[str]
    cited_urls: List[str]      # 用户消息中引用的 wiki URL（待 fetch）
    cited_wiki_chunks: List[Dict]  # fetch 到的 wiki 内容，prepend 到 wiki_chunks
    question_type: str
    wiki_chunks: List[Dict]        # RetrievedChunk 序列化的 dict 列表
    historical_chunks: List[Dict]
    # ----- Phase 3: 子 Agent 注入 -----
    diagnostic_chunks: List[Dict]  # DiagnoseAgent 输出，最高优先级 prepend
    websearch_chunks: List[Dict]   # WebSearchAgent 输出，refine 阶段注入
    reflection_score: float
    reflection_reason: str
    rewrite_iterations: int
    # ----- 输出 -----
    answer: str
    sources: List[Dict]
    grouped_sources: List[Dict]    # 按产品分组的参考文档
    source_stats: Dict[str, Any]   # 去重统计
    image_urls: List[str]
    resource_urls: List[str]
    needs_followup: bool
    followup_hint: str
    # ----- 错误/降级 -----
    fallback_reason: str


# ============================================================
# 改写 / 反思 LLM 客户端（独立 client，避免污染 generator 的 temperature）
# ============================================================

_REWRITE_PROMPT = """你是一个查询改写器。任务：
1. 解析对话历史中的代词（"它"、"这个"、"上面那个"）→ 替换为具体对象
2. **识别问题类型并针对性改写**：
   - 如果是"哪个产品/型号支持X"或"A和B哪个更好"或"兼容性/对比"类问题：为每个涉及的产品型号生成**专项查询**（如"A603 GMSL"、"A205 音频"），保留完整产品型号
   - 如果是故障排查/操作类问题：提取核心关键词，简化为1-2个精准查询
   - 如果原问题已经清晰简短，原样返回
   - 如果涉及多个不相关的话题，拆成多个独立查询

只返回一个 JSON 数组，最多4个元素，每个查询不超过30字符。
示例：
- 输入："reComputer J401 功耗多少？" → ["J401 功耗"]
- 输入："那它支持哪个 JetPack？" (历史: reComputer J401) → ["J401 JetPack 版本"]
- 输入："A603 和 A205 都支持 3 路 GMSL 输入和音频接口吗？哪款更适合 Orin NX 16GB？" → ["A603 GMSL 音频", "A205 GMSL 音频", "A603 Orin NX 兼容", "A205 Orin NX 兼容"]
- 输入："J401 上安装 TechNexion 相机驱动后崩溃并出现乱码" → ["J401 TechNexion 相机驱动", "GMSL 板故障排查"]
- 输入："llama.cpp 在 Orin 上编译报错" → ["Orin llama.cpp 编译"]

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


_RERANK_PROMPT = """你是一个检索相关性评估器。评估每个文档片段与用户问题的相关性。

用户问题：{question}

评估以下 {n} 个文档片段，返回 JSON 数组：
{chunk_list}

评分标准：
- 1.0: 直接包含答案（产品型号/规格/参数/步骤）
- 0.7-0.9: 部分相关，能辅助回答
- 0.3-0.6: 弱相关，有背景价值但非核心
- 0.0-0.2: 完全无关

只返回 JSON 数组（必须恰好 {n} 个元素，按输入顺序排列 id 0 到 {n_minus_1}）：
[{{"id": 0, "score": 0.0, "reason": "..."}}, ..., {{"id": {n_minus_1}, "score": 0.0, "reason": "..."}}]
只返回 JSON，不要其他文字。"""


# ============================================================
# URL 提取（客户引用的 wiki 直接 fetch 补充上下文）
# ============================================================

_WIKI_URL_RE = re.compile(
    r"https?://(?:wiki\.seeedstudio\.com|seeed\.studio\.com)[^\s<>\"']+",
    re.IGNORECASE,
)


def _fetch_wiki_content(url: str, timeout: int = 15) -> Dict[str, str]:
    """抓取 wiki 页面，返回 {title, content, chunk_text}，失败返回空 dict。"""
    try:
        import requests as _req
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TechSupportAgent/1.0)",
            "Accept": "text/html, application/xhtml+xml",
        }
        r = _req.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if not r.ok:
            return {}
        html = r.text

        # 用简单正则提取 <title> 和主要正文段落
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""

        # 去掉 nav/footer/script/style
        html_clean = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", "", html)
        html_clean = re.sub(r"(?is)<!--.*?-->", "", html_clean)

        # 提取正文段落
        paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html_clean)
        lines = []
        for p in paragraphs:
            text = re.sub(r"<[^>]+>", "", p).strip()
            if len(text) > 30:
                lines.append(text)

        content = "\n".join(lines[:20])  # 最多 20 段
        if len(content) < 100:
            # 降级：取所有可见文本
            texts = re.findall(r"(?is)<(?:div|span|td|li)[^>]*>(.*?)</(?:div|span|td|li)>", html_clean)
            lines = [re.sub(r"<[^>]+>", "", t).strip() for t in texts if len(re.sub(r"<[^>]+>", "", t).strip()) > 30]
            content = "\n".join(lines[:30])

        return {
            "title": title,
            "content": content[:3000],  # 限制长度
            "chunk_text": f"标题：{title}\n内容：{content[:2000]}",
        }
    except Exception as e:
        logger.warning(f"Failed to fetch wiki URL {url}: {e}")
        return {}


def node_extract_urls(state: AgentState) -> dict:
    """提取用户消息中的 wiki.seeedstudio.com URL 并抓取内容，注入 wiki_chunks。"""
    text = state.get("user_message", "") + "\n" + (state.get("history_text", "") or "")
    urls = list(dict.fromkeys(_WIKI_URL_RE.findall(text)))  # 去重保序
    if not urls:
        return {"cited_urls": []}

    logger.info(f"[extract_urls] found {len(urls)} URLs: {urls}")
    fetched_chunks: list[dict] = []
    for url in urls[:3]:  # 最多处理 3 个 URL
        info = _fetch_wiki_content(url)
        if info.get("chunk_text"):
            fetched_chunks.append({
                "chunk_text": info["chunk_text"],
                "title": info.get("title", url.split("/")[-1]),
                "wiki_url": url,
                "category": "cited_wiki",
                "doc_id": f"cited_{hash(url)}",
                "score": 1.0,  # 用户明确引用，给最高分
                "image_urls": [],
                "resource_urls": [],
            })

    if not fetched_chunks:
        return {"cited_urls": []}
    return {"cited_urls": [u for u in urls[:3]], "cited_wiki_chunks": fetched_chunks}


class _RewriteClient:
    """轻量 LLM 客户端，专门做改写和反思。temperature=0，max_tokens 小。"""

    def __init__(self, model: str, api_key: str, base_url: Optional[str],
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
        import os
        model = g.get("reflection_model") or oc.get("llm_model") or os.environ.get("OPENAI_LLM_MODEL", "qwen3.7-plus")
        base_url = oc.get("base_url") or os.environ.get("OPENAI_BASE_URL")
        return cls(
            model=model,
            api_key=oc.get("api_key", ""),
            base_url=base_url,
            max_tokens=g.get("reflection_max_tokens", 200),
        )

    def rewrite(self, question: str, history: str) -> list[str]:
        """改写 query；失败时返回 [原 question]。"""
        if not question.strip():
            return [question]

        # 如果问题过长（>150字符），先做简单截断作为fallback
        fallback_query = question
        if len(question) > 150:
            # 提取前100字符作为基础查询
            fallback_query = question[:100].strip()
            logger.info(f"Long question detected ({len(question)} chars), fallback: '{fallback_query}...'")

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
            max_tokens=300,
        )
            text = (resp.choices[0].message.content or "").strip()
            # 去掉 markdown code fence（LLM 经常输出 ```json ... ``` 导致 json.loads 失败）
            text = _strip_json_fence(text)
            # 处理 ```json ... ``` 或 ``` ... ``` 包裹
            import re
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"^```\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            queries = json.loads(text)
            if isinstance(queries, list) and queries:
                # 兜底：确保所有元素都是 str 且非空
                qs = [str(q).strip() for q in queries if str(q).strip()]
                return qs[:4] if qs else [fallback_query]
            return [fallback_query]
        except Exception as e:
            logger.warning(f"query_rewrite failed, using fallback: {e}")
            return [fallback_query]

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
            # 去掉 markdown code fence（LLM 经常输出 ```json ... ``` 导致 json.loads 失败）
            text = _strip_json_fence(text)
            import re
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"^```\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            reason = str(data.get("reason", "")).strip()
            need_rewrite = bool(data.get("need_rewrite", False))
            return score, reason, need_rewrite
        except Exception as e:
            logger.warning(f"reflect failed, defaulting to score=0.5: {e}")
            return 0.5, "", False

    def rerank(
        self, question: str, chunks: list[RetrievedChunk], top_n: int = 10
    ) -> list[RetrievedChunk]:
        """用 LLM 对 chunks 打相关性分并重排。失败时返回原顺序的前 top_n。"""
        import re

        if not chunks:
            return []
        if len(chunks) == 1:
            return chunks[:top_n]

        # 构造 chunk 列表（最多 20 个，避免 prompt 过长）
        max_rerank = 20
        to_rerank = chunks[:max_rerank]

        def _sanitize(text: str) -> str:
            """去掉破坏 JSON 的字符，保留可读内容"""
            # 去掉 HTML 标签
            text = re.sub(r"<[^>]+>", "", text)
            # 去掉多余空白
            text = re.sub(r"\s+", " ", text)
            # 去掉破坏 JSON 的字符（保留中文、英文、数字、常用标点）
            text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
            return text.strip()[:300]

        chunk_list_lines = []
        for i, c in enumerate(to_rerank):
            text = _sanitize(c.chunk_text or "")
            title = _sanitize(c.title or c.wiki_url or f"文档{i}")
            chunk_list_lines.append(
                f'[{i}] {title}\n{text}'
            )
        chunk_list_str = "\n\n".join(chunk_list_lines)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个检索相关性评估器，只返回 JSON 数组。"},
                    {"role": "user", "content": _RERANK_PROMPT.format(
                        question=question,
                        chunk_list=chunk_list_str,
                        n=len(to_rerank),
                        n_minus_1=len(to_rerank) - 1,
                    )},
                ],
                temperature=0.0,
                max_tokens=600,
            )
            text = (resp.choices[0].message.content or "").strip()
            text = _strip_json_fence(text)
            import re
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"^```\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            try:
                scores = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                # 兜底：尝试提取 JSON 数组
                m = re.search(r"\[.*\]", text, re.DOTALL)
                if m:
                    try:
                        scores = json.loads(m.group(0))
                    except Exception:
                        return chunks[:top_n]
                else:
                    return chunks[:top_n]
            if not isinstance(scores, list):
                return chunks[:top_n]
            # 构建 id → score 映射
            score_map = {item["id"]: float(item.get("score", 0.0)) for item in scores}
            # 按 LLM score 重排
            reranked = sorted(
                to_rerank,
                key=lambda c: score_map.get(to_rerank.index(c), 0.0),
                reverse=True,
            )
            # 合并：前 max_rerank 个按 rerank 排序，其余保持原顺序追加
            rest = chunks[max_rerank:]
            logger.info(
                f"[rerank] {len(to_rerank)} chunks reranked, "
                f"top score={score_map.get(0, 0):.2f}"
            )
            return reranked + rest
        except Exception as e:
            logger.warning(f"rerank failed, keeping original order: {e}")
            return chunks[:top_n]


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
                graph_cfg: dict,
                sag_retriever: SAGRetriever | None = None,
                diagnose_agent: DiagnoseAgent | None = None,
                websearch_agent: WebSearchAgent | None = None):
    """工厂：闭包绑定依赖，返回节点函数集合。"""

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
                    api_key=sf.get('api_key', '') or os.environ.get('SILICONFLOW_API_KEY', ''),
                    model=sf.get('model', 'BAAI/bge-m3'),
                    batch_size=sf.get('batch_size', 64),
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
        qdrant_chunks: list[RetrievedChunk] = []
        sag_chunks: list[RetrievedChunk] = []
        try:
            for q in queries:
                qv = _embed(q)
                hits = retriever.retrieve_vector(qv, category_filter=category)
                qdrant_chunks.extend(hits)
            qdrant_chunks.sort(key=lambda c: c.score, reverse=True)
        except Exception as e:
            logger.error(f"[retrieve/qdrant] failed: {e}")

        # SAG hybrid（如果启用且可用）
        if sag_retriever is not None and sag_retriever.enabled:
            try:
                for q in queries:
                    hits = sag_retriever.retrieve(q, category_filter=category)
                    sag_chunks.extend(hits)
                sag_chunks.sort(key=lambda c: c.score, reverse=True)
            except Exception as e:
                logger.warning(f"[retrieve/sag] failed: {e}")

        # RRF 融合或降级
        if sag_chunks:
            qdrant_w = float(graph_cfg.get("qdrant_weight", 0.4))
            sag_w = float(graph_cfg.get("sag_weight", 0.6))
            top_n = int(graph_cfg.get("hybrid_top_n", 10))
            fused = rrf_fuse([qdrant_chunks, sag_chunks], weights=[qdrant_w, sag_w], top_n=top_n)
            logger.info(f"[retrieve] RRF fused: {len(qdrant_chunks)} Qdrant + {len(sag_chunks)} SAG -> {len(fused)}")
            merged_chunks = fused
        else:
            merged_chunks = qdrant_chunks[: max(retriever.top_k * 2, 10)]
            logger.info(f"[retrieve] Qdrant only: {len(merged_chunks)} chunks")

        # prepend 诊断 chunks（Phase 3，diagnose_agent 启用时）
        diag = state.get("diagnostic_chunks", [])
        if diag:
            logger.info(f"[retrieve] prepending {len(diag)} diagnostic chunks")
            merged_chunks = list(diag) + merged_chunks

        # prepend 客户引用的 wiki 内容（来自 node_extract_urls，优先级最高）
        cited = state.get("cited_wiki_chunks", [])
        if cited:
            logger.info(f"[retrieve] prepending {len(cited)} cited wiki chunks")
            merged_chunks = cited + merged_chunks

        # append websearch 兜底 chunks（Phase 3，websearch_agent 启用时；score 较低，排在最后）
        ws_chunks = state.get("websearch_chunks", [])
        if ws_chunks:
            logger.info(f"[retrieve] appending {len(ws_chunks)} websearch chunks")
            merged_chunks = merged_chunks + list(ws_chunks)

        wiki_dicts: list[dict] = []
        for c in merged_chunks:
            # 支持 dict（cited_wiki_chunks）和 RetrievedChunk（Qdrant/SAG 结果）两种格式
            if isinstance(c, dict):
                wiki_dicts.append({
                    "chunk_text": c.get("chunk_text", ""),
                    "title": c.get("title", ""),
                    "wiki_url": c.get("wiki_url", ""),
                    "category": c.get("category", ""),
                    "doc_id": c.get("doc_id", ""),
                    "score": float(c.get("score", 0.0)),
                    "image_urls": c.get("image_urls", []),
                    "resource_urls": c.get("resource_urls", []),
                })
            else:
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
        # LLM Rerank：在 RRF 之后用 LLM 打分重排（对兼容性问题/长问题效果显著）
        if len(merged_chunks) > 3:
            try:
                from .retriever import RetrievedChunk
                merged_objs = []
                for c in merged_chunks:
                    if isinstance(c, dict):
                        merged_objs.append(RetrievedChunk(**c))
                    else:
                        merged_objs.append(c)
                reranked = rewrite_client.rerank(
                    question=state["user_message"],
                    chunks=merged_objs,
                    top_n=int(graph_cfg.get("rerank_top_n", 10)),
                )
                # 重新序列化为 dict
                wiki_dicts = []
                for c in reranked:
                    if isinstance(c, dict):
                        wiki_dicts.append(c)
                    else:
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
            except Exception as e:
                logger.warning(f"[retrieve/rerank] failed: {e}, keeping RRF order")

        return {"wiki_chunks": wiki_dicts}
    
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
            "sources": result.get("flat_sources") or result.get("sources", []),
            "grouped_sources": result.get("grouped_sources", []),
            "source_stats": result.get("source_stats", {}),
            "image_urls": result.get("image_urls", []),
            "resource_urls": result.get("resource_urls", []),
            "needs_followup": needs_followup,
            "followup_hint": _FOLLOWUP_HINTS[0] if needs_followup else "",
        }

    # ---------- 节点 7: diagnose (Phase 3 子 Agent) ----------
    def node_diagnose(state: AgentState) -> dict:
        """DiagnoseAgent：从用户消息识别错误码，注入 diagnostic_chunks。

        仅当 diagnose_agent 已初始化（enabled=true 且构造成功）时生效。
        否则返回空 dict（不影响主流程）。
        """
        if diagnose_agent is None:
            return {"diagnostic_chunks": []}
        out = diagnose_agent.run(
            state["user_message"],
            qtype=state.get("question_type", "general"),
        )
        if out.matched_error_codes:
            codes_str = ", ".join(m.code for m in out.matched_error_codes)
            logger.info(f"[diagnose] matched codes: {codes_str}")
        return {
            "diagnostic_chunks": out.diagnostic_chunks,
            "fallback_reason": state.get("fallback_reason", "") or out.fallback_reason,
        }

    # ---------- 节点 8: websearch (Phase 3 子 Agent) ----------
    def node_websearch(state: AgentState) -> dict:
        """WebSearchAgent：wiki_chunks 为空或 reflection_score 低时，调 Tavily 兜底。

        仅当 websearch_agent 已初始化（enabled=true 且构造成功）时生效。
        否则返回空 dict。
        """
        if websearch_agent is None:
            return {"websearch_chunks": []}
        wiki_chunks = state.get("wiki_chunks", [])
        reflect_score = state.get("reflection_score")
        should_run, reason = websearch_agent.should_trigger(
            wiki_chunks=wiki_chunks,
            reflect_score=reflect_score,
        )
        if not should_run:
            logger.info(f"[websearch] skip: {reason}")
            return {"websearch_chunks": []}
        queries = state.get("rewritten_queries") or [state["user_message"]]
        query = queries[0]
        ws_out = websearch_agent.run(query)
        if ws_out.websearch_chunks:
            logger.info(
                f"[websearch] injected {len(ws_out.websearch_chunks)} chunks "
                f"(provider={ws_out.provider_used}, latency={ws_out.search_latency_ms}ms)"
            )
        else:
            logger.info(f"[websearch] no chunks: {ws_out.fallback_reason}")
        return {"websearch_chunks": ws_out.websearch_chunks}

    # ---------- 条件边 ----------
    def route_after_classify(state: AgentState) -> str:
        """classify 后：若 diagnose_agent 已启用且 qtype 命中 trigger → diagnose，否则 → retrieve。

        diagnose 默认 disabled（diagnose_agent is None），直接走 retrieve（保持原行为）。
        """
        if diagnose_agent is not None:
            try:
                qtype = QuestionType(state.get("question_type", "general"))
                if qtype.value in diagnose_agent.trigger_qtypes:
                    return "diagnose"
            except (ValueError, AttributeError):
                pass
        return "retrieve"

    def route_after_diagnose(state: AgentState) -> str:
        """diagnose 后：若有诊断 chunks，跳过 retrieve 直接 reflect；否则继续 retrieve。"""
        diag_chunks = state.get("diagnostic_chunks", [])
        if diag_chunks:
            logger.info(f"[diagnose→reflect] {len(diag_chunks)} chunks, skip retrieve")
            return "reflect"
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

    def route_after_historical(state: AgentState) -> str:
        """historical 后：决定是否走 websearch 兜底。

        websearch 默认 disabled（websearch_agent is None），直接 reflect。
        启用后：wiki_chunks 空 OR reflect_score 低 → websearch，否则直接 reflect。
        """
        if websearch_agent is None:
            return "reflect"
        wiki_chunks = state.get("wiki_chunks", [])
        reflect_score = state.get("reflection_score")
        should_run, reason = websearch_agent.should_trigger(
            wiki_chunks=wiki_chunks,
            reflect_score=reflect_score,
        )
        return "websearch" if should_run else "reflect"

    def route_after_websearch(state: AgentState) -> str:
        """websearch 后：合并 websearch_chunks 到 wiki_chunks，再进 reflect。"""
        ws_chunks = state.get("websearch_chunks", [])
        if ws_chunks:
            logger.info(f"[websearch→reflect] {len(ws_chunks)} chunks added to wiki_chunks")
        return "reflect"  # 合并由 wiki_chunks 读取时统一处理

    def route_after_reflect(state: AgentState) -> str:
        """reflect 后：score 够 OR 已达 max_rewrites → generate；否则 → query_rewrite。"""
        if not cfg_enable_reflect:
            return "generate"
        score = float(state.get("reflection_score", 0.0))
        iterations = int(state.get("rewrite_iterations", 0))
        # 先检查迭代次数（防止无限循环）
        if iterations >= cfg_max_rewrites:
            logger.info(f"[reflect→generate] max_rewrites={iterations} reached, force generate")
            return "generate"
        if score >= cfg_threshold:
            return "generate"
        # 只有在 iterations < max_rewrites 且 score < threshold 时才重写
        logger.info(f"[reflect→rewrite] score={score:.2f} < threshold={cfg_threshold}, iteration={iterations+1}/{cfg_max_rewrites}")
        return "query_rewrite"

    return {
        "node_query_rewrite": node_query_rewrite,
        "node_classify": node_classify,
        "node_retrieve": node_retrieve,
        "node_retrieve_historical": node_retrieve_historical,
        "node_reflect": node_reflect,
        "node_generate": node_generate,
        "node_diagnose": node_diagnose,
        "node_websearch": node_websearch,
        "route_after_classify": route_after_classify,
        "route_after_diagnose": route_after_diagnose,
        "route_after_retrieve": route_after_retrieve,
        "route_after_historical": route_after_historical,
        "route_after_websearch": route_after_websearch,
        "route_after_reflect": route_after_reflect,
    }


# ============================================================
# 图编译
# ============================================================

_compiled_graph = None


def build_graph(retriever: QdrantRetriever | None = None,
                router: QuestionRouter | None = None,
                generator: AnswerGenerator | None = None,
                rewrite_client: _RewriteClient | None = None,
                sag_retriever: SAGRetriever | None = None,
                diagnose_agent: DiagnoseAgent | None = None,
                websearch_agent: WebSearchAgent | None = None):
    """构造并编译 LangGraph。返回 compiled graph（可调用 .invoke()）。"""
    cfg = get_config().get("graph", {})
    retriever = retriever or QdrantRetriever.from_config()
    router = router or QuestionRouter.from_config()
    generator = generator or AnswerGenerator.from_config()
    rewrite_client = rewrite_client or _RewriteClient.from_config()
    # SAG: 按配置决定是否启用，优先从 config 读取（允许独立禁用）
    if sag_retriever is None:
        sag_cfg = get_config().get("sag", {})
        if sag_cfg.get("enabled", False):
            try:
                sag_retriever = SAGRetriever.from_config()
                if sag_retriever.health():
                    logger.info(f"SAG hybrid enabled (base_url={sag_retriever.base_url}, "
                                f"project={sag_retriever.project_id})")
                else:
                    logger.warning("SAG enabled but not reachable, disabling hybrid")
                    sag_retriever = None
            except Exception as e:
                logger.warning(f"SAG init failed, disabling hybrid: {e}")
                sag_retriever = None

    # Phase 3 子 Agent：按 agents.*.enabled 决定是否启用（默认 disabled → None）
    agents_cfg = get_config().get("agents", {})
    if diagnose_agent is None:
        diag_cfg = agents_cfg.get("diagnose", {}) or {}
        if diag_cfg.get("enabled", False):
            try:
                diagnose_agent = DiagnoseAgent.from_config(diag_cfg)
                logger.info(f"[build_graph] DiagnoseAgent enabled: trigger_qtypes={diagnose_agent.trigger_qtypes}")
            except Exception as e:
                logger.warning(f"[build_graph] DiagnoseAgent init failed, disabled: {e}")
                diagnose_agent = None
    if websearch_agent is None:
        ws_cfg = agents_cfg.get("websearch", {}) or {}
        if ws_cfg.get("enabled", False):
            try:
                websearch_agent = WebSearchAgent.from_config(ws_cfg)
                avail, reason = websearch_agent.available()
                logger.info(f"[build_graph] WebSearchAgent enabled: available={avail}, reason={reason}")
            except Exception as e:
                logger.warning(f"[build_graph] WebSearchAgent init failed, disabled: {e}")
                websearch_agent = None

    nodes = _make_nodes(retriever, router, generator, rewrite_client, cfg,
                        sag_retriever, diagnose_agent, websearch_agent)

    g = StateGraph(AgentState)
    g.add_node("query_rewrite", nodes["node_query_rewrite"])
    g.add_node("extract_urls", node_extract_urls)
    g.add_node("classify", nodes["node_classify"])
    g.add_node("diagnose", nodes["node_diagnose"])
    g.add_node("retrieve", nodes["node_retrieve"])
    g.add_node("retrieve_historical", nodes["node_retrieve_historical"])
    g.add_node("websearch", nodes["node_websearch"])
    g.add_node("reflect", nodes["node_reflect"])
    g.add_node("generate", nodes["node_generate"])

    g.add_edge(START, "query_rewrite")
    g.add_edge("query_rewrite", "extract_urls")
    g.add_edge("extract_urls", "classify")
    # classify → diagnose 或 retrieve（diagnose 默认 disabled → 永远 retrieve，零回归）
    g.add_conditional_edges("classify", nodes["route_after_classify"],
                            {"diagnose": "diagnose", "retrieve": "retrieve"})
    # diagnose → retrieve 或 reflect（命中错误码 → 跳过 retrieve）
    g.add_conditional_edges("diagnose", nodes["route_after_diagnose"],
                            {"retrieve": "retrieve", "reflect": "reflect"})
    # retrieve → retrieve_historical 或 reflect
    g.add_conditional_edges("retrieve", nodes["route_after_retrieve"],
                            {"retrieve_historical": "retrieve_historical",
                             "reflect": "reflect"})
    # retrieve_historical → websearch 或 reflect（websearch 默认 disabled → 永远 reflect）
    g.add_conditional_edges("retrieve_historical", nodes["route_after_historical"],
                            {"websearch": "websearch", "reflect": "reflect"})
    # websearch → reflect
    g.add_edge("websearch", "reflect")
    # reflect → generate 或 query_rewrite
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
