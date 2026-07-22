#!/usr/bin/env python3
"""
Qdrant 向量索引重建脚本（raw HTTP，绕过 qdrant_client 兼容性问题）
- 扫描所有 wiki 文档（中英文）
- 用 SiliconFlow BAAI/bge-m3 向量化
- 写入 jetson_wiki collection（dense）
- 支持断点续传
"""
from __future__ import annotations
import json
import os
import time
import hashlib
import re
import logging
import argparse
from pathlib import Path

import requests

# .env 加载
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from pipeline.parser import WikiChunk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# Qdrant raw HTTP helper（直接 REST，绕过 qdrant_client）
# ============================================================

class QdrantHTTP:
    """直接用 requests 与 Qdrant REST API 通信"""

    def __init__(self, host: str = "localhost", port: int = 6333):
        self.base = f"http://{host}:{port}"

    def create_collection(self, name: str, size: int = 1024, recreate: bool = True):
        """创建 collection（默认会先删）"""
        if recreate:
            r = requests.delete(f"{self.base}/collections/{name}", timeout=10)
            logger.info(f"Delete {name}: {r.status_code}")
        payload = {"vectors": {"size": size, "distance": "Cosine"}}
        r = requests.put(
            f"{self.base}/collections/{name}",
            json=payload,
            timeout=30,
        )
        logger.info(f"Create {name}: {r.status_code} - {r.text[:200]}")
        return r.ok

    def upsert_points(self, name: str, points: list[dict], wait: bool = True):
        """批量 upsert points（Qdrant 1.7+ 格式）

        Point 格式：
        {
            "id": <int|str|UUID>,
            "vector": [float, ...],   # dense vector
            "payload": {...}
        }
        """
        payload = {"points": points}
        r = requests.put(
            f"{self.base}/collections/{name}/points",
            json=payload,
            params={"wait": "true"} if wait else {},
            timeout=120,
        )
        return r

    def count(self, name: str) -> int:
        """获取 collection 中的点数"""
        try:
            r = requests.get(f"{self.base}/collections/{name}", timeout=10)
            return r.json().get("result", {}).get("points_count", 0)
        except Exception:
            return -1


# ============================================================
# SiliconFlow Embedding
# ============================================================

def _sf_embed(texts: list[str], api_key: str, batch_size: int = 32) -> list[list[float]]:
    """用 SiliconFlow BAAI/bge-m3 向量化"""
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = {"model": "BAAI/bge-m3", "input": batch}
        resp = requests.post(
            "https://api.siliconflow.cn/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"SiliconFlow error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        for item in data["data"]:
            results.append(item["embedding"])
    return results


# ============================================================
# Wiki 文档解析（与 ingest_all_jetson.py 相同的策略）
# ============================================================

def _extract_frontmatter(content: str) -> dict:
    props = {}
    in_yaml = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("---"):
            if not in_yaml:
                in_yaml = True
            else:
                break
            continue
        if in_yaml and ":" in stripped and not stripped.startswith("-"):
            k, v = stripped.split(":", 1)
            props[k.strip()] = v.strip().strip("\"'")
    return props


def _extract_title(content: str, filename: str) -> str:
    fm = _extract_frontmatter(content)
    if fm.get("title"):
        return fm["title"][:80]
    for line in content.split("\n"):
        s = line.strip()
        if s.startswith("# "):
            t = s[2:].strip()
            if t and not t.startswith("{"):
                return t[:80]
    return filename.replace("cn_", "").replace("_", " ").replace(".md", "").strip()[:80]


def _parse_wiki_doc(path: Path, lang: str) -> list[WikiChunk]:
    try:
        content = path.read_text("utf-8", errors="replace")
    except Exception:
        return []
    if len(content) < 100:
        return []

    title = _extract_title(content, path.name)
    fm = _extract_frontmatter(content)
    image_urls = re.findall(r"https?://files\.seeedstudio\.com/wiki/[^\s\"'\)]+", content)
    resource_urls = re.findall(
        r"https?://[^\s\"'\)]+\.(?:pdf|PDF|zip|ZIP|tar\.gz)[^\s\"'\)]*", content
    )

    # 简单分块（按标题分）
    chunks = []
    current = ""
    current_heading = title
    chunk_size = 600
    chunk_overlap = 150
    lines = content.split("\n")
    for line in lines:
        s = line.strip()
        if s.startswith("---") or s.startswith("!["):
            continue
        if s.startswith("# ") and len(s) < 100:
            if current:
                chunks.append((current_heading, current))
            current = s[2:].strip() + "\n"
            current_heading = s[2:].strip()[:80] or title
        else:
            current += line + "\n"
        if len(current) >= chunk_size:
            chunks.append((current_heading, current))
            overlap_text = current[-chunk_overlap:]
            current = overlap_text
    if current:
        chunks.append((current_heading, current))
    if not chunks:
        chunks = [(title, content[:3000])]

    doc_id = hashlib.md5(str(path).encode()).hexdigest()[:16]
    slug = fm.get("slug", path.stem)
    wiki_url = fm.get("url", f"wiki://{slug}")

    result = []
    for idx, (heading, text) in enumerate(chunks):
        chunk = WikiChunk(
            doc_id=doc_id,
            title=title,
            description=fm.get("description", ""),
            slug=slug,
            keywords=",".join(fm.get("keywords", [])),
            category=f"wiki_{lang}",
            chunk_text=text.strip()[:3000],
            chunk_index=idx,
            total_chunks=len(chunks),
            image_urls=list(set(image_urls)),
            resource_urls=list(set(resource_urls)),
            wiki_url=wiki_url,
            last_update_date="",
            last_update_author="",
        )
        result.append(chunk)
    return result


def scan_all_docs() -> list[tuple[WikiChunk, str]]:
    """扫描所有 wiki 文档（中英文）"""
    docs = []
    scan_paths = [
        ("/home/seeed/wiki-documents/sites/zh-CN/docs/Edge/NVIDIA_Jetson", "zh-CN"),
        ("/home/seeed/wiki-documents/sites/zh-CN/docs/FAQ/Jetson", "zh-CN"),
        ("/home/seeed/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson", "en"),
        ("/home/seeed/wiki-documents/sites/en/docs/FAQ/Jetson", "en"),
    ]
    seen_paths = set()
    for base, lang in scan_paths:
        base_path = Path(base)
        if not base_path.exists():
            logger.warning(f"Path not found: {base}")
            continue
        for md in base_path.rglob("*.md"):
            if md in seen_paths:
                continue
            if md.stat().st_size < 100:
                continue
            seen_paths.add(md)
            chunks = _parse_wiki_doc(md, lang)
            for chunk in chunks:
                docs.append((chunk, str(md)))
            if len(docs) % 500 == 0:
                logger.info(f"  Parsed {len(docs)} chunks...")
    return docs


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Qdrant 向量索引重建")
    parser.add_argument("--recreate", action="store_true", help="删除并重建 collection")
    parser.add_argument("--batch-size", type=int, default=32, help="embedding batch size")
    parser.add_argument("--limit", type=int, default=0, help="限制处理的 chunk 数")
    parser.add_argument("--dry-run", action="store_true", help="只解析不写入")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Qdrant 向量索引重建（raw HTTP）")
    logger.info("=" * 60)

    api_key = os.environ.get("SILICONFLOW_API_KEY", "")
    if not api_key:
        logger.error("SILICONFLOW_API_KEY not set")
        return

    qd = QdrantHTTP(host="localhost", port=6333)
    logger.info(f"Qdrant at {qd.base}")

    # Parse
    logger.info("扫描 wiki 文档...")
    all_chunks = scan_all_docs()
    if args.limit > 0:
        all_chunks = all_chunks[:args.limit]
        logger.info(f"Limited to {args.limit} chunks")

    # 去重
    seen = set()
    unique_chunks = []
    for chunk, path in all_chunks:
        key = (chunk.doc_id, chunk.chunk_index)
        if key not in seen:
            seen.add(key)
            unique_chunks.append(chunk)
    logger.info(f"Unique chunks: {len(unique_chunks)}")

    if args.dry_run:
        return

    # 创建 collection
    qd.create_collection("jetson_wiki", size=1024, recreate=args.recreate)
    # zoho_historical 用空 collection（暂不导入历史回复）
    qd.create_collection("zoho_historical", size=1024, recreate=False)

    # 批量向量化 + 写入
    batch_size = args.batch_size
    total = len(unique_chunks)
    indexed = 0
    errors = 0
    failed_chunks = []

    logger.info(f"开始向量化导入 ({batch_size}/batch, {total} chunks)...")

    for i in range(0, total, batch_size):
        batch = unique_chunks[i:i + batch_size]
        texts = [c.chunk_text[:1500] for c in batch]

        # 1. 向量化
        try:
            embeddings = _sf_embed(texts, api_key, batch_size=batch_size)
        except Exception as e:
            logger.error(f"Embedding batch {i//batch_size} failed: {e}")
            errors += len(batch)
            failed_chunks.extend(batch)
            continue

        # 2. 构造 points
        points = []
        for j, (chunk, emb) in enumerate(zip(batch, embeddings)):
            # 用 doc_id + chunk_index 哈希作为唯一 ID（hex string，UUID-compatible）
            pid = hashlib.md5(
                f"{chunk.doc_id}_{chunk.chunk_index}".encode()
            ).hexdigest()
            points.append({
                "id": pid,
                "vector": emb,
                "payload": {
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
                },
            })

        # 3. 写入（用 raw HTTP）
        r = qd.upsert_points("jetson_wiki", points, wait=True)
        if r.status_code == 200:
            indexed += len(points)
        else:
            errors += len(points)
            failed_chunks.extend(batch)
            if errors <= 100:
                logger.warning(f"Upsert failed: {r.status_code} {r.text[:300]}")

        pct = (i + len(batch)) / total * 100
        elapsed = "" if not hasattr(main, "_start") else f" ETA: {(time.time()-main._start) * (total-i-len(batch)) / max(indexed, 1) / 60:.0f}min"
        logger.info(f"  [{pct:.1f}%] {indexed}/{total} indexed ({errors} errors){elapsed}")
        if i == 0 and not hasattr(main, "_start"):
            main._start = time.time()

    logger.info("=" * 60)
    logger.info(f"完成: {indexed}/{total} chunks indexed, {errors} errors")
    cnt = qd.count("jetson_wiki")
    logger.info(f"Qdrant jetson_wiki: {cnt} points")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
