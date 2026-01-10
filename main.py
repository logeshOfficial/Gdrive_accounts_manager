import streamlit as st

# 🚦 SAFE CHECK
if not st.session_state.get("drive_ready", False):
    st.switch_page("pages/load_files_from_gdrive.py")
    
st.title("Home")

if st.button("Drive Manager"):
    st.switch_page("pages/load_files_from_gdrive.py")

if st.button("Chat Bot"):
    st.switch_page("pages/chat_bot.py")
