"""把 data/historical_replies.jsonl embedding 入库到新的 Qdrant collection。

输入: data/historical_replies.jsonl (来自 build_email_corpus.py 输出)
输出: Qdrant collection (默认 zoho_historical)

每条记录:
- id: ticket_id_reply_index
- content (原文清洗后): 用于 embedding + 检索
- ticket_number, ticket_subject, agent_name 等: payload
- doc_id: id 同值, 方便 Retriever 重用

用法:
  python -m pipeline.ingest_historical_replies
  python -m pipeline.ingest_historical_replies --recreate   # 重建 collection
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _get_qdrant_cfg(cfg: dict) -> tuple[str, int, str, int]:
    qc = cfg["qdrant"]
    return (
        qc.get("host", "localhost"),
        int(qc.get("port", 6333)),
        qc.get("historical_replies_collection", "zoho_historical"),
        int(qc.get("vector_size", 1024)),
    )


def _get_embedder(cfg: dict):
    """同 pipeline/main.py 一样的 embedder 选择逻辑"""
    from .embedder import get_embedder

    emb_cfg = cfg.get("embedding", {})
    emb_provider = emb_cfg.get("provider", "local")
    if emb_provider == "local":
        return get_embedder(
            provider=emb_provider,
            model=emb_cfg.get("local_model", "BAAI/bge-m3"),
            batch_size=emb_cfg.get("local_batch_size", 16),
            dimensions=0,
        )
    if emb_provider == "siliconflow":
        sf_cfg = emb_cfg.get("siliconflow", {})
        return get_embedder(
            provider=emb_provider,
            api_key=sf_cfg.get("api_key", "") or os.environ.get("SILICONFLOW_API_KEY", ""),
            model=sf_cfg.get("model", "BAAI/bge-m3"),
            batch_size=sf_cfg.get("batch_size", 1000),
            dimensions=1024,
        )
    # openai
    return get_embedder(
        provider=emb_provider,
        api_key=emb_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", ""),
        model=emb_cfg.get("openai_model", "text-embedding-3-small"),
        batch_size=emb_cfg.get("embedding_batch_size", 1000),
        dimensions=emb_cfg.get("openai_dimensions", 1024),
    )


def load_historical_replies(path: Path) -> list[dict]:
    log.info(f"Loading historical replies from {path}")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning(f"Skip malformed line: {e}")
    log.info(f"Loaded {len(out)} historical replies")
    return out


def _ensure_collection(client: QdrantClient, name: str, vector_size: int, recreate: bool) -> None:
    exists = False
    try:
        client.get_collection(name)
        exists = True
    except Exception:
        exists = False
    if exists and recreate:
        log.info(f"Deleting existing collection: {name}")
        client.delete_collection(name)
        exists = False
    if not exists:
        log.info(f"Creating collection: {name} (dim={vector_size})")
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def ingest(
    input_path: str = "data/historical_replies.jsonl",
    recreate: bool = False,
    batch_size: int = 64,
) -> None:
    from .config import get_config

    cfg = get_config()
    host, port, collection, vector_size = _get_qdrant_cfg(cfg)
    project_root = Path(__file__).parent.parent
    in_p = project_root / input_path
    if not in_p.exists():
        log.error(f"Input file not found: {in_p}. Run pipeline.build_email_corpus first.")
        sys.exit(1)

    replies = load_historical_replies(in_p)
    if not replies:
        log.warning("No replies to ingest, exit.")
        return

    embedder = _get_embedder(cfg)
    log.info(f"Embedding provider={type(embedder).__name__}, model={getattr(embedder, 'model_name', '?')}")

    # 1) 逐批 embed (避免 OOM)
    log.info(f"Generating embeddings for {len(replies)} replies (batch_size={batch_size})...")
    all_vectors: list[list[float]] = []
    for i in range(0, len(replies), batch_size):
        batch_texts = [r["content"] for r in replies[i:i + batch_size]]
        vecs = embedder.embed(batch_texts)
        all_vectors.extend(vecs)
        log.info(f"  embedded {min(i + batch_size, len(replies))}/{len(replies)}")

    # 2) 入库
    client = QdrantClient(host=host, port=port)
    _ensure_collection(client, collection, vector_size, recreate=recreate)

    points: list[PointStruct] = []
    skipped_dim = 0
    for idx, (r, vec) in enumerate(zip(replies, all_vectors)):
        if len(vec) != vector_size:
            skipped_dim += 1
            continue
        payload = {
            "doc_id": r.get("id", f"hist_{idx}"),  # 给 Retriever 用
            "chunk_text": r.get("content", ""),
            "title": r.get("ticket_subject", "")[:200],
            "wiki_url": "",  # 历史回复无 wiki url, retriever 兼容空字符串
            "category": "historical_reply",
            "ticket_id": r.get("ticket_id", ""),
            "ticket_number": r.get("ticket_number", ""),
            "ticket_subject": r.get("ticket_subject", ""),
            "ticket_assignee": r.get("ticket_assignee", ""),
            "ticket_status": r.get("ticket_status", ""),
            "agent_name": r.get("agent_name", ""),
            "image_urls": [],
            "resource_urls": [],
        }
        # point id 用 hash 避免重复
        pid = abs(hash(r.get("id", f"hist_{idx}"))) % (2**31)
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    if skipped_dim:
        log.warning(f"Skipped {skipped_dim} points due to dim mismatch (expected {vector_size})")

    upserted = 0
    for j in range(0, len(points), batch_size):
        client.upsert(collection_name=collection, points=points[j:j + batch_size])
        upserted += len(points[j:j + batch_size])
        log.info(f"  upserted {upserted}/{len(points)}")

    log.info("=" * 60)
    log.info(f"Collection '{collection}' total points: {len(points)}")
    log.info("Done.")


def main():
    parser = argparse.ArgumentParser(description="Ingest historical agent replies into Qdrant")
    parser.add_argument("--input", default="data/historical_replies.jsonl", help="path to historical_replies.jsonl")
    parser.add_argument("--recreate", action="store_true", help="delete & recreate collection")
    parser.add_argument("--batch-size", type=int, default=64, help="embedding + upsert batch size")
    args = parser.parse_args()
    ingest(input_path=args.input, recreate=args.recreate, batch_size=args.batch_size)


if __name__ == "__main__":
    main()