"""Streamlit 会话状态管理"""
import uuid
import streamlit as st
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChatMessage:
    role: str          # "user" | "assistant"
    content: str
    sources: list[dict] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    resource_urls: list[str] = field(default_factory=list)
    question_type: str = ""
    timestamp: str = ""


def init_session_state():
    """初始化 Streamlit 会话状态"""
    defaults = {
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "category": "",
        "feedback_given": set(),
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def reset_session():
    """重置会话状态"""
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.category = ""
    st.session_state.feedback_given = set()


def add_user_message(content: str):
    st.session_state.messages.append(ChatMessage(role="user", content=content))


def add_assistant_message(
    content: str,
    sources: list[dict] = None,
    image_urls: list[str] = None,
    resource_urls: list[str] = None,
    question_type: str = "",
):
    from datetime import datetime
    st.session_state.messages.append(ChatMessage(
        role="assistant",
        content=content,
        sources=sources or [],
        image_urls=image_urls or [],
        resource_urls=resource_urls or [],
        question_type=question_type,
        timestamp=datetime.now().strftime("%H:%M"),
    ))
