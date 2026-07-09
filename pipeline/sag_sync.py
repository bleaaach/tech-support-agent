"""SAG 数据同步脚本 —— 把 Jetson Wiki 文档批量导入 SAG 服务

功能：
1. 扫描 D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson 下的所有 .md / .mdx
2. 逐个调用 SAG /ingest 接口（chunk + event 抽取 + entity 抽取 + embedding）
3. 记录已同步状态到 data/sag_sync_state.json（增量同步）
4. 支持 --force 全量重传 和 --file 单文件调试

用法：
    # 全量同步（首次或重建）
    python -m pipeline.sag_sync --full

    # 增量同步（默认，只传新文件/已修改文件）
    python -m pipeline.sag_sync

    # 单文件测试
    python -m pipeline.sag_sync --file "D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson/reComputer_J4012/getting_started.md"

    # 检查 SAG 是否就绪（不传数据）
    python -m pipeline.sag_sync --check
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from agent.config import get_config
from agent.sag_retriever import SAGRetriever

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("sag_sync")

# SAG 同步状态：data/sag_sync_state.json
_STATE_FILE = _PROJECT_ROOT / "data" / "sag_sync_state.json"


def _load_state() -> dict[str, str]:
    """加载同步状态（{file_path: sha256_hash}）"""
    if not _STATE_FILE.exists():
        return {}
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Failed to load state file, treating as empty: {e}")
        return {}


def _save_state(state: dict[str, str]) -> None:
    """保存同步状态"""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _hash_file(path: Path) -> str:
    """SHA256 文件指纹"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # 短哈希足够


def _strip_frontmatter(content: str) -> tuple[str, dict]:
    """提取 YAML frontmatter 里的 title，剥离 frontmatter 块"""
    if not content.startswith("---"):
        return content, {}
    end = content.find("\n---", 3)
    if end == -1:
        return content, {}
    fm_block = content[3:end].strip()
    body = content[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return body, fm


def _collect_wiki_files(wiki_root: Path) -> list[Path]:
    """递归扫描 wiki_root 下所有 .md / .mdx"""
    if not wiki_root.exists():
        log.error(f"Wiki root not found: {wiki_root}")
        return []
    files = []
    for ext in ("**/*.md", "**/*.mdx"):
        files.extend(wiki_root.glob(ext))
    files = sorted(set(files))
    log.info(f"Found {len(files)} markdown files under {wiki_root}")
    return files


def _ingest_one(retriever: SAGRetriever, path: Path, force_extract: bool = True) -> dict:
    """导入单个文档到 SAG"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"read failed: {e}"}

    body, fm = _strip_frontmatter(raw)
    title = fm.get("title") or path.stem.replace("_", " ")

    # 限制单文件大小，避免 LLM extract 超时 / 成本过高
    if len(body) > 20000:
        log.warning(f"  {path.name}: body is {len(body)} chars, truncating to 20000")
        body = body[:20000]

    return retriever.ingest(
        title=title,
        content=body,
        extract=force_extract,
    )


def run_full(wiki_root: Path, force: bool = False) -> None:
    """全量同步"""
    retriever = SAGRetriever.from_config()

    if not retriever.health():
        log.error(f"SAG 不可达: {retriever.base_url}/health")
        log.error("请确认 SAG 服务已启动 (D:/SAG → npm run dev 或 npm start)")
        sys.exit(1)

    log.info(f"SAG 健康检查通过 ({retriever.base_url})")

    files = _collect_wiki_files(wiki_root)
    if not files:
        sys.exit(1)

    state = {} if force else _load_state()

    ok_count = 0
    skip_count = 0
    fail_count = 0
    t_start = time.time()

    for i, path in enumerate(files, 1):
        file_hash = _hash_file(path)
        rel = str(path.relative_to(wiki_root))

        if not force and state.get(rel) == file_hash:
            skip_count += 1
            log.debug(f"[{i}/{len(files)}] SKIP (unchanged): {rel}")
            continue

        log.info(f"[{i}/{len(files)}] INGEST: {rel}")
        result = _ingest_one(retriever, path)
        if result.get("ok"):
            ok_count += 1
            state[rel] = file_hash
            elapsed = int(time.time() - t_start)
            log.info(f"  ✓ ok ({elapsed}s elapsed, {ok_count} ok / {fail_count} fail)")
        else:
            fail_count += 1
            log.error(f"  ✗ fail: {result.get('error')}")

        # 每 10 个文件保存一次 state，防止中途中断丢失进度
        if i % 10 == 0:
            _save_state(state)

    _save_state(state)

    elapsed = int(time.time() - t_start)
    log.info("=" * 50)
    log.info(f"同步完成 (耗时 {elapsed}s)")
    log.info(f"  成功: {ok_count}")
    log.info(f"  跳过: {skip_count}")
    log.info(f"  失败: {fail_count}")
    log.info(f"  总计: {len(files)}")
    log.info("=" * 50)
    log.info(f"同步状态已保存到 {_STATE_FILE}")


def run_single(file_path: Path) -> None:
    """单文件导入"""
    retriever = SAGRetriever.from_config()
    if not retriever.health():
        log.error(f"SAG 不可达: {retriever.base_url}")
        sys.exit(1)
    if not file_path.exists():
        log.error(f"文件不存在: {file_path}")
        sys.exit(1)

    log.info(f"导入单文件: {file_path}")
    result = _ingest_one(retriever, file_path)
    if result.get("ok"):
        log.info(f"✓ 成功: {result}")
    else:
        log.error(f"✗ 失败: {result.get('error')}")


def run_check() -> None:
    """健康检查"""
    retriever = SAGRetriever.from_config()
    log.info(f"SAG base_url: {retriever.base_url}")
    log.info(f"SAG enabled:  {retriever.enabled}")
    if retriever.health():
        log.info("✓ SAG 健康")
        count = retriever.count()
        log.info(f"  项目事件数: {count}")
    else:
        log.error("✗ SAG 不可达")
        log.error("  请确认:")
        log.error("    1. Docker Desktop 已启动")
        log.error("    2. D:/SAG → docker compose up -d")
        log.error("    3. D:/SAG → npm run dev   (或 npm start)")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jetson Wiki → SAG 数据同步")
    parser.add_argument("--full", action="store_true", help="强制全量重传（忽略已有状态）")
    parser.add_argument("--file", type=str, help="单文件导入（调试用）")
    parser.add_argument("--check", action="store_true", help="只检查 SAG 健康，不传数据")
    args = parser.parse_args()

    cfg = get_config()
    wiki_root = Path(cfg.get("jetson_docs_path", "D:/wiki-documents/sites/en/docs/Edge/NVIDIA_Jetson"))

    if args.check:
        run_check()
    elif args.file:
        run_single(Path(args.file))
    else:
        run_full(wiki_root, force=args.full)


if __name__ == "__main__":
    main()