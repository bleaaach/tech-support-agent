import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
d = json.load(open(r'D:\tech-support-agent\chat_resp3.json','r',encoding='utf-8'))
print('session_id:', d.get('session_id'))
print('sources count:', len(d.get('sources',[])))
for s in d.get('sources',[])[:5]:
    score = s.get('score', 0)
    src = s.get('source', '')
    hdg = s.get('heading', '')[:60]
    print('  - score=%.3f | %s | %s' % (score, src, hdg))
print('---')
print('answer (first 800 chars):')
print(d.get('answer','')[:800])
