import sys
sys.stdout.reconfigure(encoding='utf-8')
from agent.retriever import QdrantRetriever
r = QdrantRetriever()
print('count:', r.count())
queries = [
    'Jetson 技术支持 Agent 整体架构',
    'RAG 检索增强生成',
    'BGE-M3 embedding 模型',
    'Qdrant 向量数据库',
    'NVIDIA Jetson',
    '整体架构选型',
]
for q in queries:
    hits = r.retrieve(q)
    print()
    print('=== Q:', q, '  hits=%d' % len(hits))
    for h in hits[:3]:
        print('  score=%.3f | src=%s | %s' % (h.score, h.source, h.heading[:60]))
