"""Embedding 生成器：本地 BGE-M3（默认，离线）或 OpenAI 在线。"""
import time
import logging
import os
from typing import Protocol, Iterator, List, Optional

logger = logging.getLogger(__name__)


class EmbeddingModel(Protocol):
    """Embedding 模型接口"""
    def embed(self, texts: List[str]) -> List[List[float]]: ...
    def embed_batch(self, texts: List[str], batch_size: int = 32) -> Iterator[List[float]]: ...


class LocalBGEM3Embedder:
    """本地 sentence-transformers 加载的 BGE-M3（默认方案，离线可用）"""

    def __init__(self, model: str = "BAAI/bge-m3", batch_size: int = 16, normalize: bool = True):
        from sentence_transformers import SentenceTransformer
        self.model_name = model
        self.batch_size = batch_size
        self.normalize = normalize
        logger.info(f"Loading local embedding model: {model}")
        self.model = SentenceTransformer(model)
        self.dim = self.model.get_sentence_embedding_dimension()
        logger.info(f"Model loaded. dim={self.dim}, max_seq={self.model.max_seq_length}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vecs = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.tolist()

    def embed_batch(self, texts: List[str], batch_size: Optional[int] = None) -> Iterator[List[float]]:
        total = len(texts)
        bs = batch_size or self.batch_size
        for i in range(0, total, bs):
            batch = texts[i:i + bs]
            try:
                embeddings = self.embed(batch)
                yield from embeddings
            except Exception as e:
                logger.error(f"Batch {i // bs + 1} failed: {e}")
                time.sleep(1)
                try:
                    embeddings = self.embed(batch)
                    yield from embeddings
                except Exception as e2:
                    logger.error(f"Retry failed: {e2}")
                    for _ in batch:
                        yield [0.0] * self.dim


class OpenAIEmbedding:
    """OpenAI Embedding 模型（在线，需 OPENAI_API_KEY）"""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        batch_size: int = 1000,
        dimensions: int = 1536,
    ):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.batch_size = batch_size
        self.dimensions = dimensions
        self.dim = dimensions
        self.model_name = model

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in response.data]

    def embed_batch(self, texts: List[str], batch_size: Optional[int] = None) -> Iterator[List[float]]:
        total = len(texts)
        bs = batch_size or self.batch_size
        for i in range(0, total, bs):
            batch = texts[i:i + bs]
            logger.info(f"Embedding batch {i // bs + 1}, texts {i}-{min(i + bs, total)}/{total}")
            try:
                embeddings = self.embed(batch)
                yield from embeddings
            except Exception as e:
                logger.error(f"Batch {i // bs + 1} failed: {e}")
                time.sleep(2)
                try:
                    embeddings = self.embed(batch)
                    yield from embeddings
                except Exception as e2:
                    logger.error(f"Retry also failed: {e2}")
                    for _ in batch:
                        yield [0.0] * self.dimensions


class SiliconFlowEmbedding:
    """SiliconFlow Embedding（在线，OpenAI 兼容接口，性价比高）"""

    def __init__(
        self,
        api_key: str,
        model: str = "BAAI/bge-m3",
        batch_size: int = 1000,
        dimensions: int = 1024,
    ):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.siliconflow.cn/v1",
        )
        self.model = model
        self.batch_size = batch_size
        self.dimensions = dimensions
        self.dim = dimensions
        self.model_name = model

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def embed_batch(self, texts: List[str], batch_size: Optional[int] = None) -> Iterator[List[float]]:
        total = len(texts)
        bs = batch_size or self.batch_size
        for i in range(0, total, bs):
            batch = texts[i:i + bs]
            logger.info(f"Embedding batch {i // bs + 1}, texts {i}-{min(i + bs, total)}/{total}")
            try:
                embeddings = self.embed(batch)
                yield from embeddings
            except Exception as e:
                logger.error(f"Batch {i // bs + 1} failed: {e}")
                time.sleep(2)
                try:
                    embeddings = self.embed(batch)
                    yield from embeddings
                except Exception as e2:
                    logger.error(f"Retry also failed: {e2}")
                    for _ in batch:
                        yield [0.0] * self.dimensions


def get_embedder(
    provider: str = "local",
    api_key: str = "",
    model: str = "",
    batch_size: int = 0,
    dimensions: int = 0,
) -> EmbeddingModel:
    """
    工厂函数：
      - provider="local"       → 本地 BGE-M3，离线
      - provider="openai"      → 在线 OpenAI text-embedding-3-small
      - provider="siliconflow" → 硅基流动 BAAI/bge-m3，性价比高
    """
    if provider == "openai":
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        if not model:
            model = "text-embedding-3-small"
        bs = batch_size or 1000
        dims = dimensions or 1024
        return OpenAIEmbedding(api_key=api_key, model=model, batch_size=bs, dimensions=dims)

    if provider == "siliconflow":
        if not api_key:
            api_key = os.environ.get("SILICONFLOW_API_KEY", "")
        if not model:
            model = "BAAI/bge-m3"
        bs = batch_size or 1000
        dims = dimensions or 1024
        return SiliconFlowEmbedding(api_key=api_key, model=model, batch_size=bs, dimensions=dims)

    # default: local
    m = model or "BAAI/bge-m3"
    bs = batch_size or 16
    return LocalBGEM3Embedder(model=m, batch_size=bs)
