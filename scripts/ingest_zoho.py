#!/usr/bin/env python3
"""
Standalone zoho historical replies → Qdrant ingest.
直接调 Siliconflow API，不 import pipeline 模块（规避 Python 3.8 type hint 兼容问题）。
"""
import json, logging, os, sys, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("zoho_ingest")

SILICONFLOW_URL = "https://api.siliconflow.cn/v1/embeddings"
SF_MODEL = "BAAI/bge-m3"
VECTOR_DIM = 1024


def _sf_embed(texts, api_key, batch_size=64):
    """调 Siliconflow embed 接口，返回 list[list[float]]。"""
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = {"model": SF_MODEL, "input": batch}
        for attempt in range(3):
            try:
                import requests as _req
                resp = _req.post(
                    SILICONFLOW_URL,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload, timeout=60,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    vecs = [item["embedding"] for item in data["data"]]
                    results.extend(vecs)
                    break
                elif resp.status_code == 429:
                    log.warning(f"Rate limited, sleeping 10s...")
                    time.sleep(10)
                    continue
                else:
                    log.error(f"Embed API error {resp.status_code}: {resp.text[:200]}")
                    break
            except Exception as e:
                log.warning(f"Embed attempt {attempt+1} failed: {e}")
                time.sleep(2)
        else:
            log.error(f"All attempts failed for batch {i}, padding with zeros")
            results.extend([[0.0] * VECTOR_DIM for _ in batch])
    return results


def main():
    import argparse
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/historical_replies.jsonl")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    _dotenv = root / ".env"
    if _dotenv.exists():
        for line in open(_dotenv):
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    api_key = args.api_key or os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        log.error("No SILICONFLOW_API_KEY found. Set env or pass --api-key")
        sys.exit(1)

    in_path = root / args.input
    if not in_path.exists():
        log.error(f"Not found: {in_path}")
        sys.exit(1)

    # Load
    replies = []
    with open(in_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                replies.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning(f"Skip malformed: {e}")
    log.info(f"Loaded {len(replies)} replies")

    # Embed
    log.info(f"Embedding {len(replies)} replies (batch={args.batch_size})...")
    texts = [r["content"] for r in replies]
    vectors = _sf_embed(texts, api_key, batch_size=args.batch_size)
    log.info(f"Got {len(vectors)} vectors, dim={len(vectors[0]) if vectors else 0}")

    # Qdrant
    qhost = os.environ.get("QDRANT_HOST", "localhost")
    qport = int(os.environ.get("QDRANT_PORT", "6333"))
    collection = "zoho_historical"

    log.info(f"Connecting Qdrant {qhost}:{qport}...")
    client = QdrantClient(host=qhost, port=qport)

    if args.recreate:
        try:
            client.delete_collection(collection)
            log.info(f"Deleted '{collection}'")
        except Exception:
            pass

    try:
        client.get_collection(collection)
        log.info(f"Collection '{collection}' exists (keeping)")
    except Exception:
        log.info(f"Creating '{collection}' dim={VECTOR_DIM}...")
        client.create_collection(
            collection_name=collection,
            vectors_config={"default": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE)},
        )

    # Build points
    points = []
    for idx, (r, vec) in enumerate(zip(replies, vectors)):
        if len(vec) != VECTOR_DIM:
            continue
        payload = {
            "doc_id": r.get("id", f"hist_{idx}"),
            "chunk_text": r.get("content", ""),
            "title": r.get("ticket_subject", "")[:200],
            "wiki_url": "",
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
        pid = abs(hash(r.get("id", f"hist_{idx}"))) % (2**31)
        points.append(PointStruct(id=pid, vector=vec, payload=payload))

    log.info(f"Upserting {len(points)} points...")
    for j in range(0, len(points), args.batch_size):
        batch_pts = points[j:j + args.batch_size]
        client.upsert(collection_name=collection, points=batch_pts)
        log.info(f"  {j + len(batch_pts)}/{len(points)}")

    log.info(f"✅ Done! Collection '{collection}' has {len(points)} points")


if __name__ == "__main__":
    main()
