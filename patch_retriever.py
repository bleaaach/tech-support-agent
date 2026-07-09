"""一次性修补：retriever.py 改成 absolute import + 自管 embed"""
import re
p = r'D:\tech-support-agent\agent\retriever.py'
src = open(p, 'r', encoding='utf-8').read()
old = (
    "        try:\n"
    "            from .chat import _get_local_embedder\n"
    "            emb = _get_local_embedder()\n"
    "            query_vector = emb.embed([query])[0]\n"
)
new = (
    "        try:\n"
    "            from pipeline.embedder import LocalBGEM3Embedder\n"
    "            from agent.config import get_config\n"
    "            emb_cfg = get_config().get('embedding', {})\n"
    "            emb = LocalBGEM3Embedder(\n"
    "                model=emb_cfg.get('local_model', 'BAAI/bge-m3'),\n"
    "                batch_size=emb_cfg.get('local_batch_size', 16),\n"
    "            )\n"
    "            query_vector = emb.embed([query])[0]\n"
)
assert old in src, 'old block not found'
src = src.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(src)
print('patched')
