"""Qdrant 检索器"""
from __future__ import annotations
import logging
import os
import re
from pathlib import Path
from dataclasses import dataclass

# 确保环境变量已加载（.env 文件）
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from qdrant_client import QdrantClient

from .config import get_config

logger = logging.getLogger(__name__)

# 关键词扩展映射
_KEYWORD_SYNONYMS = {
    "cad": "CAD STP STEP DXF 3D model mechanical drawing schematic",
    "stl": "STL OBJ 3D print model file",
    "obj": "OBJ STL 3D model file",
    "3d model": "3D model STP STEP DXF STL OBJ CAD mechanical",
    "3d file": "3D file STP STEP DXF STL OBJ CAD mechanical",
    "schematic": "schematic PDF circuit diagram",
    "datasheet": "datasheet PDF specification",
    "dimension": "dimension drawing measurement",
    "super": "reComputer Super J4012 J4011 J3011 J3010",  # 新增
    "j4012": "J4012 reComputer Super Orin NX 16GB",  # 新增
    "eth1": "eth1 second ethernet port network interface RJ45",  # 新增
}


def _expand_query(query: str) -> str:
    """扩展查询词，增加同义词以提高召回率"""
    expanded_terms = []
    query_lower = query.lower()
    
    # 检查查询中是否包含关键词，并添加对应扩展
    for keyword, expansion in _KEYWORD_SYNONYMS.items():
        if keyword in query_lower:
            expanded_terms.append(expansion)
    
    if expanded_terms:
        # 将原始查询与扩展词合并
        return f"{query} {' '.join(expanded_terms)}"
    return query


@dataclass
class RetrievedChunk:
    chunk_text: str
    title: str
    wiki_url: str
    category: str
    doc_id: str
    score: float
    image_urls: list[str]
    resource_urls: list[str]


class QdrantRetriever:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "jetson_wiki",
        top_k: int = 5,
        min_score: float = 0.3,
        historical_collection_name: Optional[str] = None,
        historical_top_k: int = 3,
        historical_min_score: float = 0.50,
        local_path: Optional[str] = None,
    ):
        """支持两种模式：
        - 远程模式 (默认): 连接 host:port 上的 Qdrant 服务
        - 本地模式 (local_path 给出路径): 使用 qdrant_client 内置的 QdrantLocal，无需外部服务
        """
        if local_path:
            from qdrant_client.local.qdrant_local import QdrantLocal
            self._local_mode = True
            self.client = QdrantLocal(location=local_path)
            logger.info(f"QdrantRetriever using local mode: path={local_path}")
        else:
            self._local_mode = False
            self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.top_k = top_k
        self.min_score = min_score
        self.historical_collection_name = historical_collection_name
        self.historical_top_k = historical_top_k
        self.historical_min_score = historical_min_score

    @classmethod
    def from_config(cls) -> "QdrantRetriever":
        cfg = get_config()
        qc = cfg["qdrant"]
        rc = cfg.get("retrieval", {})
        # 支持环境变量强制启用本地模式（避免远程 Qdrant 依赖）
        local_path = os.environ.get("QDRANT_LOCAL_PATH") or qc.get("local_path")
        if not local_path and os.environ.get("QDRANT_FALLBACK_LOCAL") == "1":
            default_path = str(Path(__file__).parent.parent / "data" / "qdrant_local")
            Path(default_path).mkdir(parents=True, exist_ok=True)
            local_path = default_path
            logger.warning(f"QDRANT_FALLBACK_LOCAL=1, using local path: {local_path}")
        return cls(
            host=qc["host"],
            port=qc["port"],
            collection_name=qc.get("collection_name", "jetson_wiki"),
            top_k=rc.get("top_k", 5),
            min_score=rc.get("min_score", 0.3),
            historical_collection_name=qc.get("historical_replies_collection"),
            historical_top_k=rc.get("historical_top_k", 3),
            historical_min_score=rc.get("historical_min_score", 0.50),
            local_path=local_path,
        )

    def retrieve(self, query: str, category_filter: Optional[str] = None) -> List[RetrievedChunk]:
        """字符串查询 → 内部 embed → 向量检索。
        兼容两种调用：传 str（自动 embed）或传 list[float]（向量检索）。"""
        if isinstance(query, list):
            return self.retrieve_vector(query, category_filter=category_filter)
        
        # 扩展查询词（CAD → CAD STP STEP DXF 3D model...）
        expanded_query = _expand_query(query)
        if expanded_query != query:
            logger.info(f"Query expanded: '{query}' → '{expanded_query}'")
        try:
            import sys
            project_root = str(Path(__file__).parent.parent)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            from pipeline.embedder import get_embedder
            from agent.config import get_config
            emb_cfg = get_config().get('embedding', {})
            emb_provider = emb_cfg.get('provider', 'local')
            if emb_provider == 'local':
                emb_model = emb_cfg.get('local_model', 'BAAI/bge-m3')
                emb_dims = 0
                emb_batch = emb_cfg.get('local_batch_size', 16)
            elif emb_provider == 'siliconflow':
                sf_cfg = emb_cfg.get('siliconflow', {})
                emb_model = sf_cfg.get('model', 'BAAI/bge-m3')
                emb_dims = 1024
                emb_batch = sf_cfg.get('batch_size', 1000)
                emb_api_key = sf_cfg.get('api_key', '') or os.environ.get('SILICONFLOW_API_KEY', '')
                emb = get_embedder(provider=emb_provider, api_key=emb_api_key, model=emb_model, batch_size=emb_batch, dimensions=emb_dims)
                query_vector = emb.embed([expanded_query])[0]
                return self.retrieve_vector(query_vector, category_filter=category_filter)
            else:
                emb_model = emb_cfg.get('openai_model', 'text-embedding-3-small')
                emb_dims = emb_cfg.get('openai_dimensions', 1024)
                emb_batch = 1000
            emb = get_embedder(provider=emb_provider, model=emb_model, batch_size=emb_batch, dimensions=emb_dims)
            query_vector = emb.embed([expanded_query])[0]
        except Exception as e:
            logger.error(f"embedding failed in retrieve(): {e}")
            return []
        return self.retrieve_vector(query_vector, category_filter=category_filter)

    def retrieve_vector(self, query_vector: List[float], category_filter: Optional[str] = None) -> List[RetrievedChunk]:
        """纯向量检索入口"""
        try:
            response = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=self.top_k,
                score_threshold=self.min_score,
            )
            results = response
        except Exception as e:
            logger.error(f"Qdrant search failed: {e}")
            return []

        chunks = []
        for hit in results:
            payload = hit.payload or {}
            if category_filter and category_filter not in payload.get("category", ""):
                continue
            chunk = RetrievedChunk(
                chunk_text=payload.get("chunk_text", ""),
                title=payload.get("title", ""),
                wiki_url=payload.get("wiki_url", ""),
                category=payload.get("category", ""),
                doc_id=payload.get("doc_id", ""),
                score=hit.score,
                image_urls=payload.get("image_urls", []),
                resource_urls=payload.get("resource_urls", []),
            )
            chunks.append(chunk)

        return chunks

    def count(self) -> int:
        """返回 Collection 中的总点数"""
        try:
            info = self.client.get_collection(self.collection_name)
            return info.points_count or 0
        except Exception:
            return 0

    def retrieve_historical(self, query_vector: List[float]) -> List[RetrievedChunk]:
        """检索历史相似回复 (RAG-2, 方向 B)。

        输入: query_vector (已经是 1024 维向量)
        输出: RetrievedChunk 列表 (复用同一 dataclass, wiki_url 为空)
        """
        if not self.historical_collection_name:
            return []
        try:
            response = self.client.search(
                collection_name=self.historical_collection_name,
                query_vector=query_vector,
                limit=self.historical_top_k,
                score_threshold=self.historical_min_score,
            )
            results = response
        except Exception as e:
            logger.error(f"Historical Qdrant search failed: {e}")
            return []

        chunks: List[RetrievedChunk] = []
        for hit in results:
            payload = hit.payload or {}
            chunk = RetrievedChunk(
                chunk_text=payload.get("chunk_text", ""),
                title=payload.get("title", "") or payload.get("ticket_subject", ""),
                wiki_url=payload.get("wiki_url", ""),
                category=payload.get("category", "historical_reply"),
                doc_id=payload.get("doc_id", ""),
                score=hit.score,
                image_urls=payload.get("image_urls", []),
                resource_urls=payload.get("resource_urls", []),
            )
            chunks.append(chunk)
        return chunks

    def historical_count(self) -> int:
        """返回历史回复 collection 的总点数"""
        if not self.historical_collection_name:
            return 0
        try:
            info = self.client.get_collection(self.historical_collection_name)
            return info.points_count or 0
        except Exception:
            return 0
