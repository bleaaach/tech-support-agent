"""Pipeline 入口：一键构建索引"""
import argparse
import logging
import os
import time
from pathlib import Path

from tqdm import tqdm

from .config import get_config
from .parser import parse_all_docs
from .embedder import get_embedder
from .indexer import QdrantIndexer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run():
    t0 = time.time()
    cfg = get_config()

    # ---- 1. 解析文档 ----
    wiki_root = Path(cfg["jetson_docs_path"])
    if not wiki_root.exists():
        log.error(f"Wiki root not found: {wiki_root}")
        log.info("Falling back to: D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson")
        wiki_root = Path("D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson")
        if not wiki_root.exists():
            log.info("Second fallback: D:/wiki-documents/sites/en/docs")
            wiki_root = Path("D:/wiki-documents/sites/en/docs")

    chunk_cfg = cfg.get("chunking", {})
    chunk_size = chunk_cfg.get("chunk_size", 500)
    overlap = chunk_cfg.get("chunk_overlap", 100)

    log.info(f"Parsing docs from: {wiki_root}")
    chunks = parse_all_docs(wiki_root, chunk_size=chunk_size, overlap=overlap)
    log.info(f"Parsed {len(chunks)} chunks from docs")

    if not chunks:
        log.error("No chunks parsed. Check wiki root path.")
        return

    # ---- 2. 生成 Embedding ----
    emb_cfg = cfg.get("embedding", {})
    emb_provider = emb_cfg.get("provider", "local")
    if emb_provider == "local":
        emb_model = emb_cfg.get("local_model", "BAAI/bge-m3")
        emb_dims = 0
        emb_batch = emb_cfg.get("local_batch_size", 16)
        emb_api_key = ""
    elif emb_provider == "siliconflow":
        sf_cfg = emb_cfg.get("siliconflow", {})
        emb_model = sf_cfg.get("model", "BAAI/bge-m3")
        emb_dims = 1024
        emb_batch = sf_cfg.get("batch_size", 1000)
        emb_api_key = sf_cfg.get("api_key", "") or os.environ.get("SILICONFLOW_API_KEY", "")
    else:
        emb_model = emb_cfg.get("openai_model", "text-embedding-3-small")
        emb_dims = emb_cfg.get("openai_dimensions", 1024)
        emb_batch = 1000
        emb_api_key = ""
    embedder = get_embedder(
        provider=emb_provider,
        api_key=emb_api_key,
        model=emb_model,
        batch_size=emb_batch,
        dimensions=emb_dims,
    )
    log.info(f"Embedding provider={emb_provider} model={emb_model}")

    texts = [c.chunk_text for c in chunks]
    log.info("Generating embeddings...")
    embeddings = list(tqdm(embedder.embed_batch(texts), total=len(texts), desc="Embedding"))

    # ---- 3. 入库 Qdrant ----
    qdrant_cfg = cfg["qdrant"]
    indexer = QdrantIndexer(
        host=qdrant_cfg["host"],
        port=qdrant_cfg["port"],
        collection_name=qdrant_cfg.get("collection_name", "jetson_wiki"),
        vector_size=qdrant_cfg.get("vector_size", 1536),
    )

    log.info("Indexing to Qdrant...")
    indexed = indexer.index_chunks(chunks, embeddings, batch_size=100, recreate=True)
    log.info(f"Indexed {indexed} chunks to Qdrant")

    # ---- 4. 保存 index.json ----
    index_path = Path(cfg.get("index_file", "D:/tech-support-agent/data/index.json"))
    indexer.save_index_json(chunks, index_path)

    elapsed = time.time() - t0
    log.info(f"Pipeline complete in {elapsed:.1f}s")
    log.info(f"Total chunks: {len(chunks)}")
    log.info(f"Qdrant collection: {qdrant_cfg.get('collection_name', 'jetson_wiki')}")
    log.info(f"index.json: {index_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Jetson Wiki index")
    parser.add_argument("--recreate", action="store_true", help="Recreate Qdrant collection")
    args = parser.parse_args()
    run()
