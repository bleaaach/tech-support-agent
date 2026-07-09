"""Qdrant 向量入库 + index.json 输出"""
import json
import logging
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.http.exceptions import UnexpectedResponse

from .parser import WikiChunk

logger = logging.getLogger(__name__)


def _chunk_to_dict(chunk: WikiChunk) -> dict[str, Any]:
    return {
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "description": chunk.description,
        "slug": chunk.slug,
        "keywords": chunk.keywords,
        "category": chunk.category,
        "chunk_text": chunk.chunk_text,
        "chunk_index": chunk.chunk_index,
        "total_chunks": chunk.total_chunks,
        "image_urls": chunk.image_urls,
        "resource_urls": chunk.resource_urls,
        "wiki_url": chunk.wiki_url,
        "last_update_date": chunk.last_update_date,
        "last_update_author": chunk.last_update_author,
    }


def _estimate_cost(chunks: list[WikiChunk], price_per_m: float = 0.01) -> float:
    """估算 Embedding 成本（按平均每块 200 tokens 估算）"""
    avg_chars = sum(len(c.chunk_text) for c in chunks) / max(len(chunks), 1)
    avg_tokens = avg_chars / 4
    total_tokens = avg_tokens * len(chunks)
    return total_tokens / 1_000_000 * price_per_m


class QdrantIndexer:
    """Qdrant 向量索引器"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "jetson_wiki",
        vector_size: int = 1536,
    ):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.vector_size = vector_size

    def _ensure_collection(self, recreate: bool = False) -> None:
        """确保 Collection 存在"""
        try:
            self.client.get_collection(self.collection_name)
            if recreate:
                logger.info(f"Deleting existing collection: {self.collection_name}")
                self.client.delete_collection(self.collection_name)
                self._create_collection()
            else:
                logger.info(f"Collection '{self.collection_name}' already exists")
        except (UnexpectedResponse, Exception):
            self._create_collection()

    def _create_collection(self) -> None:
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_size,
                distance=Distance.COSINE,
            ),
        )
        logger.info(f"Created collection: {self.collection_name}")

    def index_chunks(
        self,
        chunks: list[WikiChunk],
        embeddings: list[list[float]],
        batch_size: int = 100,
        recreate: bool = False,
    ) -> int:
        """批量写入 chunks + embeddings，返回写入数量"""
        self._ensure_collection(recreate=recreate)

        points = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            payload = _chunk_to_dict(chunk)
            point = PointStruct(
                id=i + 1,
                vector=embedding,
                payload=payload,
            )
            points.append(point)

        total = 0
        for j in range(0, len(points), batch_size):
            batch = points[j:j + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )
            total += len(batch)
            logger.info(f"Indexed {total}/{len(points)} points")

        return total

    def save_index_json(self, chunks: list[WikiChunk], output_path: Path) -> None:
        """保存 index.json（元数据，不含向量）"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records = [_chunk_to_dict(c) for c in chunks]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved index.json: {output_path} ({len(records)} chunks)")

    def get_collection_info(self) -> dict[str, Any]:
        """获取 Collection 信息"""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": info.status,
            }
        except Exception as e:
            return {"error": str(e)}
