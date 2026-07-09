"""
Seeed Studio 技术支持 Agent - 多轮对话 + 邮件模板回复格式
"""
from .chat import TechSupportChat, ConversationContext, Message
from .retriever import QdrantRetriever, RetrievedChunk
from .router import QuestionRouter, QuestionType
from .generator import AnswerGenerator
from .email_renderer import EmailRenderer, render_email

__all__ = [
    "TechSupportChat",
    "ConversationContext",
    "Message",
    "QdrantRetriever",
    "RetrievedChunk",
    "QuestionRouter",
    "QuestionType",
    "AnswerGenerator",
    "EmailRenderer",
    "render_email",
]
