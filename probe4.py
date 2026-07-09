import sys
sys.stdout.reconfigure(encoding='utf-8')
import inspect
from qdrant_client import QdrantClient
print(inspect.signature(QdrantClient.query_points))
print('---')
# 实际调用，只用 named params
from agent.retriever import QdrantRetriever
import agent.retriever as ar
r = QdrantRetriever()
# 模拟 embed
from agent.chat import _get_local_embedder
e = _get_local_embedder()
v = e.embed(['Jetson 技术支持'])[0]
print('vector type:', type(v).__name__, 'len:', len(v), 'sample:', v[:4])
print('---')
resp = r.client.query_points(
    collection_name='jetson_wiki',
    query=v,
    limit=3,
    with_payload=True,
)
print('resp type:', type(resp).__name__)
print('hits:', len(resp.points))
for p in resp.points:
    print('  score=%.3f | %s' % (p.score, p.payload.get('title', '')[:50]))
