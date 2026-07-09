"""直接验证 RAG-2 是否真把历史回复注入到 prompt。
不通过 LLM, 直接打印 generator 构造的 user_msg."""
from agent.generator import _build_user_message
from agent.retriever import RetrievedChunk
from agent.router import QuestionType

# 模拟 retrieve_historical 的输出
hist_chunks = [
    RetrievedChunk(
        chunk_text="Please check the DC jack with a multimeter first. The expected voltage is 12V/2A. Also try to reflash the firmware using NVIDIA SDK Manager.",
        title="J4012 power on issue",
        category="historical_reply",
        doc_id="12345_2", score=0.78, wiki_url="",
        image_urls=[], resource_urls=[],
    ),
]

user_msg = _build_user_message(
    question="My reComputer J4012 won't boot, LED is off",
    history="",
    qtype=QuestionType.TROUBLESHOOTING,
    context="[wiki doc 1]\nHow to troubleshoot power issues on Jetson Orin...",
    historical_replies=hist_chunks,
)

print(user_msg)
print()
print("=" * 60)
print("Has '历史回复' block:", "历史回复" in user_msg)
print("Has 'few-shot' block:", "few-shot" in user_msg.lower() or "样例" in user_msg)
print("Has historical ticket:", "工单=12345_2" in user_msg)
print("Has '历史回复' style hint:", "历史回复" in user_msg)
