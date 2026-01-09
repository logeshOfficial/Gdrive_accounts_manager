import streamlit as st
import config

# 🚦 SAFE CHECK
if not st.session_state.get("drive_ready", False):
    st.switch_page("pages/google_drive_loader.py")
    
st.title("Home")

if st.button("Drive Manager"):
    st.switch_page("pages/google_drive_loader.py")

if st.button("Chat Bot"):
    st.switch_page("pages/chat_bot.py")
