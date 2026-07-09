import logging
logging.basicConfig(level=logging.WARNING, format='%(message)s')

from agent.chat import TechSupportChat, ConversationContext

agent = TechSupportChat()

print('=== Provider 验证 ===')
print('Router model:', agent.router.model)
print('Router base_url:', agent.router.base_url)
print('Generator model:', agent.generator.model)
print('Generator base_url:', agent.generator.client.base_url)
print('Retriever chunks:', agent.retriever.count())
print()

print('=== 端到端测试 ===')
ctx = ConversationContext(session_id='e2e-1', category='')
result = agent.chat(ctx, 'reComputer J4012 supports which JetPack version?')
print()
print('Question type:', result['question_type'])
print('Answer:')
print(result['answer'][:600])
print()
print('Sources:', len(result['sources']))
for s in result['sources'][:3]:
    title = s.get('title', '')[:60]
    score = s.get('score')
    print('  -', title, 'score=', score)
