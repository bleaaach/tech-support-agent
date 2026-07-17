"""独立灌库脚本：解析 Jetson Wiki → embed（按 config 选择的 provider）→ 写入 QdrantLocal。

设计：灌库时 **不启动 uvicorn**，避免 QdrantLocal 单实例文件锁冲突。
完成后由 start_services.sh 启动 uvicorn 进行检索。
"""
import os
os.environ.setdefault("QDRANT_FALLBACK_LOCAL", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import sys
import time
import shutil
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("index_local")

# 让 pipeline 包能 import
sys.path.insert(0, str(Path(__file__).parent))

from pipeline.parser import parse_all_docs
from pipeline.embedder import get_embedder
from pipeline.indexer import QdrantIndexer
from agent.config import get_config


def main():
    t0 = time.time()
    cfg = get_config()
    qcfg = cfg["qdrant"]

    # ---- 1. 解析文档 ----
    wiki_root = Path(cfg["jetson_docs_path"])
    if not wiki_root.exists():
        log.error(f"Wiki root not found: {wiki_root}")
        sys.exit(1)

    chunk_cfg = cfg.get("chunking", {})
    log.info(f"Parsing docs from: {wiki_root}")
    chunks = parse_all_docs(
        wiki_root,
        chunk_size=chunk_cfg.get("chunk_size", 600),
        overlap=chunk_cfg.get("chunk_overlap", 150),
    )
    log.info(f"Parsed {len(chunks)} chunks in {time.time() - t0:.1f}s")

    if not chunks:
        log.error("No chunks parsed. Aborting.")
        sys.exit(1)

    # ---- 2. Embedding（按 config 选 provider）----
    emb_cfg = cfg.get("embedding", {})
    emb_provider = emb_cfg.get("provider", "siliconflow")
    if emb_provider == "siliconflow":
        sf = emb_cfg.get("siliconflow", {})
        emb = get_embedder(
            provider="siliconflow",
            api_key=sf.get("api_key", "") or os.environ.get("SILICONFLOW_API_KEY", ""),
            model=sf.get("model", "BAAI/bge-m3"),
            batch_size=sf.get("batch_size", 64),
            dimensions=1024,
        )
    elif emb_provider == "openai":
        emb = get_embedder(
            provider="openai",
            api_key=emb_cfg.get("api_key", "") or os.environ.get("OPENAI_API_KEY", ""),
            model=emb_cfg.get("openai_model", "text-embedding-3-small"),
            dimensions=emb_cfg.get("openai_dimensions", 1024),
        )
    else:
        emb = get_embedder(
            provider="local",
            model=emb_cfg.get("local_model", "BAAI/bge-m3"),
            batch_size=emb_cfg.get("local_batch_size", 8),
        )
    log.info(f"Embedding provider={emb_provider} dim={emb.dim}")

    texts = [c.chunk_text for c in chunks]
    log.info(f"Embedding {len(texts)} chunks...")
    t_emb = time.time()
    embeddings = list(emb.embed_batch(texts, batch_size=64))
    log.info(f"Generated {len(embeddings)} embeddings in {time.time() - t_emb:.1f}s")

    # 检查 embedding 是否有效（全 0 表示降级失败）
    zero_count = sum(1 for e in embeddings if all(abs(v) < 1e-6 for v in e))
    if zero_count > 0:
        log.warning(f"{zero_count}/{len(embeddings)} embeddings are zero vectors (provider failed?)")

    # ---- 3. 入库 ----
    local_path = str(Path(__file__).parent / "data" / "qdrant_local")
    # 清空旧数据以便重新灌库
    if "--fresh" in sys.argv and Path(local_path).exists():
        log.info(f"--fresh: removing old storage at {local_path}")
        shutil.rmtree(local_path)

    Path(local_path).mkdir(parents=True, exist_ok=True)

    idx = QdrantIndexer(
        collection_name=qcfg.get("collection_name", "jetson_wiki"),
        vector_size=emb.dim,
        local_path=local_path,
    )
    recreate = "--fresh" in sys.argv
    t_idx = time.time()
    n = idx.index_chunks(chunks, embeddings, batch_size=100, recreate=recreate)
    log.info(f"Indexed {n} chunks in {time.time() - t_idx:.1f}s")

    # ---- 4. 保存 index.json ----
    index_path = Path(cfg.get("index_file", "./data/index.json"))
    idx.save_index_json(chunks, index_path)

    elapsed = time.time() - t0
    info = idx.get_collection_info()
    log.info("=" * 60)
    log.info(f"Pipeline complete in {elapsed:.1f}s")
    log.info(f"Total chunks: {len(chunks)}")
    log.info(f"Collection: {info}")
    log.info(f"index.json: {index_path}")
    log.info(f"QdrantLocal storage: {local_path}")
    log.info("=" * 60)
    log.info("Next: run './start_services.sh' to start the API + UI")


if __name__ == "__main__":
    main()