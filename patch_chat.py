"""Patch agent/chat.py — _get_local_embedder 改成 absolute import"""
p = r'D:\tech-support-agent\agent\chat.py'
src = open(p, 'r', encoding='utf-8').read()
old = (
    "def _get_local_embedder():\n"
    "    \"\"\"懒加载单例：本机 BGE-M3。\"\"\"\n"
    "    global _LOCAL_EMBEDDER\n"
    "    if _LOCAL_EMBEDDER is None:\n"
    "        from ..pipeline.embedder import LocalBGEM3Embedder\n"
    "        from .config import get_config\n"
    "        emb_cfg = get_config().get(\"embedding\", {})\n"
    "        _LOCAL_EMBEDDER = LocalBGEM3Embedder(\n"
    "            model=emb_cfg.get(\"local_model\", \"BAAI/bge-m3\"),\n"
    "            batch_size=emb_cfg.get(\"local_batch_size\", 16),\n"
    "        )\n"
    "    return _LOCAL_EMBEDDER\n"
)
new = (
    "def _get_local_embedder():\n"
    "    \"\"\"懒加载单例：本机 BGE-M3。\"\"\"\n"
    "    global _LOCAL_EMBEDDER\n"
    "    if _LOCAL_EMBEDDER is None:\n"
    "        from pipeline.embedder import LocalBGEM3Embedder\n"
    "        from agent.config import get_config\n"
    "        emb_cfg = get_config().get(\"embedding\", {})\n"
    "        _LOCAL_EMBEDDER = LocalBGEM3Embedder(\n"
    "            model=emb_cfg.get(\"local_model\", \"BAAI/bge-m3\"),\n"
    "            batch_size=emb_cfg.get(\"local_batch_size\", 16),\n"
    "        )\n"
    "    return _LOCAL_EMBEDDER\n"
)
assert old in src, "old block not found"
src = src.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(src)
print("patched")
