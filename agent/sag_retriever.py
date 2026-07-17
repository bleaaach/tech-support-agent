"""SAG (SQL-Retrieval Augmented Generation) HTTP 客户端

封装 SAG HTTP API (/api/search, /ingest)，输出与 QdrantRetriever 接口兼容的
RetrievedChunk 列表，使得现有 chat.py / generator.py / email_renderer.py 几乎无需改动。

SAG 项目地址:    https://github.com/Zleap-AI/SAG
SAG 论文:        https://arxiv.org/abs/2606.15971
SAG 默认端口:    4173 (HTTP API)

为什么引入：
- SAG 把 chunk 拆为 (event, entities)，查询时用 SQL JOIN 动态构建局部超图
- 多跳召回 (MuSiQue Recall@5 = 80%) 显著优于单向量检索
- 增量更新友好（append 即可，无需重建全局图谱）

接入方式：
- hybrid 模式：与 Qdrant 并联，chat.py 用 RRF 融合两边结果
- replace 模式：彻底替换 Qdrant（暂不推荐）
"""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

# 与 retriever.py 一致：先加载 .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

import requests

from .config import get_config
from .retriever import RetrievedChunk

logger = logging.getLogger(__name__)


class SAGRetriever:
    """通过 HTTP 调用 SAG 服务，返回与 QdrantRetriever 兼容的 RetrievedChunk 列表。

    与 QdrantRetriever 的关键差异：
    - SAG 是远程服务调用，不是本地 QdrantClient
    - SAG 内部自动 embed（不需要外部传入向量）
    - SAG 用 event + entity 索引，多跳召回
    - category_filter 在 SAG 中没有等价概念（前缀过滤/产品分类交给上层路由处理）
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4173",
        project_id: str = "jetson_wiki",
        top_k: int = 8,
        search_mode: str = "fast",       # "fast" | "standard"
        strategy: str = "multi",         # "multi" (多跳) | "vector" (单跳)
        timeout: int = 30,
        enabled: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.top_k = top_k
        self.search_mode = search_mode
        self.strategy = strategy
        self.timeout = timeout
        self.enabled = enabled
        self._session = requests.Session()
        self._source_ids: list[str] | None = None

    @classmethod
    def from_config(cls) -> "SAGRetriever":
        cfg = get_config()
        sag = cfg.get("sag", {})
        return cls(
            base_url=sag.get("base_url", "http://localhost:4173"),
            project_id=sag.get("project_id", "jetson_wiki"),
            top_k=sag.get("top_k", 8),
            search_mode=sag.get("search_mode", "fast"),
            strategy=sag.get("strategy", "multi"),
            timeout=sag.get("timeout", 30),
            enabled=sag.get("enabled", True),
        )

    # ---- UUID 解析 ----

    def _resolve_source_ids(self) -> list[str]:
        """把 project_id（可能是名称或 UUID）解析为 UUID 列表。

        SAG API 要求 sourceIds 为 UUID。先用 GET /api/sources 列出所有 source，
        再匹配 project_id（优先匹配 id，其次匹配 name）。
        """
        if self._source_ids is not None:
            return self._source_ids

        try:
            r = self._session.get(f"{self.base_url}/api/sources", timeout=10)
            r.raise_for_status()
            resp = r.json()
            # API 返回 {"sources": [...]} 或直接 [...]
            if isinstance(resp, dict) and "sources" in resp:
                sources = resp["sources"]
            elif isinstance(resp, list):
                sources = resp
            else:
                sources = []
        except Exception as e:
            logger.warning(f"Failed to fetch SAG sources: {e}")
            self._source_ids = []
            return []

        if not isinstance(sources, list):
            logger.warning(f"Unexpected SAG /api/sources response: {sources}")
            self._source_ids = []
            return []

        matched = []
        for s in sources:
            sid = s.get("id", "")
            sname = s.get("name", "")
            # 匹配 id 或 name
            if sid == self.project_id or sname == self.project_id:
                matched.append(sid)

        if not matched:
            logger.warning(
                f"No SAG source matched project_id='{self.project_id}'. "
                f"Available sources: {[(x.get('id'), x.get('name')) for x in sources]}"
            )
            # 如果 project_id 本身是 UUID 格式，直接用它
            import re
            if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", self.project_id, re.I):
                matched = [self.project_id]

        self._source_ids = matched
        logger.debug(f"SAG source IDs resolved: {self._source_ids}")
        return self._source_ids

    # ---- 健康检查 ----

    def health(self) -> bool:
        """检查 SAG 服务是否在线"""
        if not self.enabled:
            return False
        try:
            r = self._session.get(f"{self.base_url}/health", timeout=3)
            return r.ok
        except Exception as e:
            logger.debug(f"SAG health check failed: {e}")
            return False

    # ---- 主入口 ----

    def retrieve(self, query: str, category_filter: str | None = None) -> list[RetrievedChunk]:
        """调 SAG /api/search 返回 RetrievedChunk 列表。

        Args:
            query: 用户查询文本（SAG 服务端自己 embed）
            category_filter: 产品分类过滤（仅打日志，SAG 无对应字段）

        Returns:
            RetrievedChunk 列表，按 score 降序
        """
        if not self.enabled:
            logger.debug("SAG disabled in config, returning empty list")
            return []

        if category_filter:
            logger.debug(f"SAG does not support category filter (got '{category_filter}'), proceeding")

        # SAG API 要求 sourceIds 为 UUID 数组，先解析 sourceId
        source_uuids = self._resolve_source_ids()
        if not source_uuids:
            logger.warning("No valid SAG source IDs found, returning empty")
            return []

        payload = {
            "query": query,
            "sourceIds": source_uuids,
            "strategy": self.strategy,
            "searchMode": self.search_mode,
            "topK": self.top_k,
            "returnTrace": False,
        }

        t0 = time.time()
        try:
            r = self._session.post(
                f"{self.base_url}/api/search",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.ConnectionError:
            logger.warning(f"SAG not reachable at {self.base_url} (query='{query[:40]}...')")
            return []
        except Exception as e:
            logger.error(f"SAG search failed: {e}")
            return []

        latency_ms = int((time.time() - t0) * 1000)
        # SAG API 返回 {"sections": [...]}（新版）或 {"results": [...]}（旧版）
        results = data.get("sections") or data.get("results") or []
        logger.info(f"SAG search: q='{query[:40]}', hits={len(results)}, latency={latency_ms}ms")

        chunks: list[RetrievedChunk] = []
        for hit in results:
            chunks.append(self._hit_to_chunk(hit))
        return chunks

    def retrieve_vector(self, query_vector: list[float], category_filter: str | None = None) -> list[RetrievedChunk]:
        """向量检索入口 —— SAG 不支持外部向量（内部自动 embed）。

        直接调 retrieve()，传入一个 dummy 字符串作为回退。
        对 SAG 而言，应该直接用 retrieve(query)，向量入口仅用于接口兼容。
        """
        logger.warning("SAGRetriever.retrieve_vector() called, falling back to text retrieval")
        return self.retrieve(query="<vector query - not supported>", category_filter=category_filter)

    def count(self) -> int:
        """返回 SAG 项目中已索引的事件数（粗略估算）"""
        if not self.enabled:
            return 0
        try:
            r = self._session.get(
                f"{self.base_url}/api/projects/{self.project_id}",
                timeout=5,
            )
            if r.ok:
                data = r.json()
                return data.get("eventCount", data.get("chunkCount", 0))
        except Exception:
            pass
        return 0

    # ---- Ingest（数据导入） ----

    def ingest(self, title: str, content: str, source_id: str | None = None, extract: bool = True) -> dict[str, Any]:
        """把一个文档导入 SAG（chunk + event + entity + embedding）。

        Args:
            title: 文档标题
            content: 文档全文（Markdown 或纯文本）
            source_id: SAG project id，默认使用 self.project_id
            extract: True = 触发 LLM 抽取 events/entities（耗时）

        Returns:
            SAG API 响应 dict，失败时返回 {"ok": False, "error": ...}
        """
        if not self.enabled:
            return {"ok": False, "error": "SAG disabled"}

        # 解析 sourceId 为 UUID
        source_uuids = self._resolve_source_ids()
        source_id = source_uuids[0] if source_uuids else self.project_id

        payload = {
            "sourceId": source_id,
            "title": title,
            "content": content,
            "extract": extract,
        }
        try:
            r = self._session.post(
                f"{self.base_url}/ingest",
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
            return {"ok": True, **r.json()}
        except Exception as e:
            logger.error(f"SAG ingest failed for '{title}': {e}")
            return {"ok": False, "error": str(e)}

    # ---- 工具方法 ----

    def _hit_to_chunk(self, hit: dict) -> RetrievedChunk:
        """把 SAG 返回的 hit 转成 RetrievedChunk。

        SAG sections 格式（当前版本 /api/search）：
        - chunkId:       chunk UUID
        - documentId:    文档 UUID（用于构建 wiki URL）
        - heading:       章节标题
        - content:       chunk 文本
        - score:         相关度分数
        - sourceId:      来源 UUID

        兼容旧版 /results 格式（event-based）。
        """
        # sections 格式（当前）
        text = hit.get("content") or hit.get("text") or hit.get("event_text") or ""
        heading = hit.get("heading") or ""
        doc_id = str(hit.get("chunkId") or hit.get("eventId") or hit.get("id") or hit.get("documentId") or "")

        # 尝试从 documentId 构建 wiki URL（通过搜索文档获取路径）
        # 暂时用 documentId 作为 doc_id
        document_id = str(hit.get("documentId") or doc_id)

        # title = heading（sections 格式） 或 sourceTitle（旧格式）
        title = hit.get("heading") or hit.get("title") or hit.get("sourceTitle") or ""

        score = float(hit.get("score") or hit.get("relevance") or 0.0)

        # wiki_url: SAG 不直接返回 URL，尝试从 metadata 构建
        wiki_url = hit.get("sourceUrl") or hit.get("url") or hit.get("wikiUrl") or ""

        image_urls = hit.get("imageUrls") or hit.get("image_urls") or []
        resource_urls = hit.get("resourceUrls") or hit.get("resource_urls") or []

        return RetrievedChunk(
            chunk_text=text,
            title=title,
            wiki_url=wiki_url,
            category="sag",
            doc_id=document_id,
            score=score,
            image_urls=image_urls,
            resource_urls=resource_urls,
        )


# ---- RRF 融合（Reciprocal Rank Fusion） ----

def rrf_fuse(
    result_lists: list[list[RetrievedChunk]],
    weights: list[float] | None = None,
    k: int = 60,
    top_n: int = 10,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion —— 把多路检索结果融合。

    Args:
        result_lists: 多路检索结果，例如 [qdrant_chunks, sag_chunks]
        weights: 各路权重，默认等权
        k: RRF 常数（论文默认 60），越大越平滑
        top_n: 最终返回 Top-N

    Returns:
        融合并按 RRF 分数重排的 RetrievedChunk 列表

    算法:
        RRF_score(d) = sum_i weight_i * 1 / (k + rank_i(d))
        其中 rank_i(d) 是文档 d 在第 i 路结果中的排名（1-indexed）
    """
    if not result_lists:
        return []

    if weights is None:
        weights = [1.0] * len(result_lists)
    if len(weights) != len(result_lists):
        raise ValueError("weights length must match result_lists length")

    # doc_id → (rrf_score, chunk)
    scores: dict[str, tuple[float, RetrievedChunk]] = {}

    for chunks, weight in zip(result_lists, weights):
        for rank, chunk in enumerate(chunks, start=1):
            # 用 (doc_id, wiki_url) 作为去重 key
            key = chunk.doc_id or chunk.wiki_url or chunk.chunk_text[:80]
            rrf_score = weight * (1.0 / (k + rank))
            if key in scores:
                old_score, old_chunk = scores[key]
                # 取更高 score + 合并 chunk_text（去重）
                if old_chunk.score < chunk.score:
                    scores[key] = (old_score + rrf_score, chunk)
                else:
                    scores[key] = (old_score + rrf_score, old_chunk)
            else:
                scores[key] = (rrf_score, chunk)

    # 按 RRF 分数降序
    sorted_items = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)

    # 输出 top_n，重置 score 为 RRF 分数便于展示
    fused: list[RetrievedChunk] = []
    for key, (rrf_score, chunk) in sorted_items[:top_n]:
        # 用 RRF 分数替换原 score（不破坏 dataclass 的不可变性，新建一个）
        new_chunk = RetrievedChunk(
            chunk_text=chunk.chunk_text,
            title=chunk.title,
            wiki_url=chunk.wiki_url,
            category=chunk.category,
            doc_id=chunk.doc_id,
            score=round(rrf_score, 4),
            image_urls=chunk.image_urls,
            resource_urls=chunk.resource_urls,
        )
        fused.append(new_chunk)

    return fused