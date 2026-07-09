"""Streamlit Web UI - 技术支持 Agent 对话界面"""
from pathlib import Path
import streamlit as st
import requests
import time
import uuid
from datetime import datetime

# Load custom CSS
css_path = Path(__file__).parent / "styles.css"
if css_path.exists():
    css_content = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)

# ---- Config ----
API_BASE = "http://localhost:8000"

# ---- Page Config ----
st.set_page_config(
    page_title="Seeed Tech Support",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Custom CSS ----
st.markdown("""
<style>
.stApp { background: #f8fafc; }
.chat-bubble-user {
    background: #1a56db; color: white; border-radius: 16px 16px 4px 16px;
    padding: 12px 16px; margin: 6px 0; max-width: 75%;
    margin-left: auto; font-size: 15px; line-height: 1.5;
}
.chat-bubble-assistant {
    background: white; color: #1f2937; border-radius: 16px 16px 16px 4px;
    padding: 12px 16px; margin: 6px 0; max-width: 75%;
    border: 1px solid #e5e7eb; font-size: 15px; line-height: 1.5;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.source-tag {
    display: inline-block; background: #eff6ff; color: #1d4ed8;
    border-radius: 6px; padding: 2px 10px; font-size: 12px;
    margin: 2px 4px 2px 0; border: 1px solid #bfdbfe;
}
.stButton>button {
    background: #1a56db; color: white; border: none; border-radius: 8px;
    padding: 0.5rem 1.5rem; font-weight: 600;
}
.stButton>button:hover { background: #1e40af; }
.question-type-badge {
    display: inline-block; background: #f0fdf4; color: #15803d;
    border: 1px solid #bbf7d0; border-radius: 20px;
    padding: 2px 12px; font-size: 11px; font-weight: 600;
    margin-bottom: 4px;
}
.email-section {
    background: white; border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 20px; margin: 8px 0;
}
.category-chip {
    background: #f8fafc; border: 1px solid #cbd5e1;
    border-radius: 20px; padding: 4px 14px; font-size: 13px;
    cursor: pointer; display: inline-block; margin: 4px;
}
.category-chip:hover, .category-chip.active {
    background: #1a56db; color: white; border-color: #1a56db;
}
</style>
""", unsafe_allow_html=True)

# ---- Session State ----
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "category" not in st.session_state:
    st.session_state.category = ""
if "pending_question" not in st.session_state:
    st.session_state.pending_question = ""

# ---- Sidebar: Category Navigator ----
with st.sidebar:
    st.markdown("### 🤖 Jetson 产品分类")
    st.markdown("---")

    categories = [
        ("全部产品", ""),
        ("reComputer J10 系列", "reComputer_Jetson_Series/reComputer_J10"),
        ("reComputer J30/J40 系列", "reComputer_Jetson_Series/reComputer_J30_40"),
        ("reComputer J40 机器人版", "reComputer_Jetson_Series/reComputer_Robotics_J40"),
        ("reComputer J401/J401B", "reComputer_Jetson_Series/reComputer_J401B"),
        ("Carrier Board J101", "Carrier_Boards/J101"),
        ("Carrier Board J401", "Carrier_Boards/J401"),
        ("Carrier Board A203/A205", "Carrier_Boards/A203v2"),
        ("Carrier Board A607/A608/A603", "Carrier_Boards/A607"),
        ("reServer J20/J30/J40", "reServer_Jetson_Series/reServer_Industrial_J30_J40"),
        ("Jetson 开发工具", "Jetson_DevelopTool"),
        ("常见问题 FAQ", "FAQs"),
        ("应用案例", "Application"),
    ]

    for cat_name, cat_path in categories:
        is_active = st.session_state.category == cat_path
        btn_type = "primary" if is_active else "secondary"
        if st.button(f"📁 {cat_name}", use_container_width=True, type=btn_type):
            st.session_state.category = cat_path
            st.rerun()

    st.markdown("---")
    st.caption(f"会话 ID: `{st.session_state.session_id[:8]}...`")
    if st.button("🔄 新建会话", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.category = ""
        st.rerun()


# ---- Main Area ----
st.markdown("## 🤖 Seeed Jetson 技术支持 Agent")
st.markdown("基于 Wiki 文档的智能技术支持，支持多轮对话和邮件格式回复")

# Display messages
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant"):
            # Question type badge
            if msg.get("question_type"):
                type_labels = {
                    "param_query": "📊 参数查询",
                    "compatibility": "🔌 兼容性问题",
                    "troubleshooting": "🔧 故障排查",
                    "howto": "📖 操作指引",
                    "transfer": "📩 转接",
                    "general": "💬 一般问题",
                }
                label = type_labels.get(msg["question_type"], msg["question_type"])
                st.markdown(f"<span class='question-type-badge'>{label}</span>", unsafe_allow_html=True)

            # Main answer (markdown)
            st.markdown(msg["content"])

            # Sources
            if msg.get("sources"):
                with st.expander("📚 参考文档", expanded=False):
                    for s in msg["sources"]:
                        st.markdown(f"- [{s.get('title', '文档')}]({s.get('url', '#')})")

            # Image/Resource URLs
            if msg.get("image_urls") or msg.get("resource_urls"):
                with st.expander("🖼️ 相关图片/资源", expanded=False):
                    for url in (msg.get("image_urls", []) + msg.get("resource_urls", [])):
                        st.markdown(f"- {url}")


# ---- Chat Input ----
if prompt := st.chat_input("输入您的问题...", key="main_input"):
    # 1. 显示用户消息
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. 调用 API
    with st.chat_message("assistant"):
        with st.spinner("正在分析问题并检索文档..."):
            try:
                resp = requests.post(
                    f"{API_BASE}/chat",
                    json={
                        "message": prompt,
                        "session_id": st.session_state.session_id,
                        "category": st.session_state.category,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.ConnectionError:
                st.error("⚠️ 无法连接到 Agent 服务。请确保 `python -m agent.main` 正在运行。")
                data = None
            except Exception as e:
                st.error(f"⚠️ 请求失败: {e}")
                data = None

        if data:
            # 渲染 answer（已经是邮件模板格式）
            st.markdown(data["answer"])

            # Sources expander
            if data.get("sources"):
                with st.expander("📚 参考文档", expanded=False):
                    for s in data["sources"]:
                        st.markdown(f"- [{s.get('title', '文档')}]({s.get('url', '#')})")

            # Images/Resources
            img_urls = data.get("image_urls", [])
            res_urls = data.get("resource_urls", [])
            if img_urls or res_urls:
                with st.expander("🖼️ 相关图片/资源", expanded=False):
                    for url in img_urls + res_urls:
                        st.markdown(f"- {url}")

            # Follow-up hint
            if data.get("needs_followup") and data.get("followup_hint"):
                st.info(f"💡 **追问建议**: {data['followup_hint']}")

            # 保存到 session
            st.session_state.messages.append({
                "role": "user",
                "content": prompt,
            })
            st.session_state.messages.append({
                "role": "assistant",
                "content": data["answer"],
                "sources": data.get("sources", []),
                "image_urls": data.get("image_urls", []),
                "resource_urls": data.get("resource_urls", []),
                "question_type": data.get("question_type", ""),
            })

            # 更新 session_id
            st.session_state.session_id = data.get("session_id", st.session_state.session_id)
