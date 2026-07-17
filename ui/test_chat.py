"""Test page for chat styling"""
import streamlit as st

st.set_page_config(page_title="Chat Test")

st.markdown("""
<style>
/* Test: Check if dark mode CSS is applied */
[data-theme="dark"] .stApp { 
    background: #0e1117 !important; 
}

/* Test: Chat bubble styling */
[data-testid="stChatMessage"] {
    background: transparent !important;
}

[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div {
    background: #1a56db !important;
    color: white !important;
    border-radius: 16px 16px 4px 16px;
}

[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) > div {
    background: #1e2530 !important;
    color: #e5e7eb !important;
    border-radius: 16px 16px 16px 4px;
    border: 1px solid #374151;
}
</style>
""", unsafe_allow_html=True)

st.title("Chat Style Test")
st.write("Toggle dark mode in settings (top right) and check if chat bubbles change color.")

with st.chat_message("user"):
    st.markdown("This is a user message - should be blue")

with st.chat_message("assistant"):
    st.markdown("This is an assistant message - should be dark gray")

# Test buttons
st.button("Test Button")
