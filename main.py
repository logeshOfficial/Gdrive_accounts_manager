import streamlit as st
from oauth_utils import start_oauth, finish_oauth

if "drive_creds" not in st.session_state:
    start_oauth()
    creds = finish_oauth()

    if creds:
        st.success("✅ Google Drive connected")
        st.switch_page("pages/load_files_from_gdrive.py")
else:
    st.success("Already logged in")
    
#SAFE CHECK
if not st.session_state.get("drive_ready", False):
    st.switch_page("pages/load_files_from_gdrive.py")
    
st.title("Home")

if st.button("Drive Manager"):
    st.switch_page("pages/load_files_from_gdrive.py")

if st.button("Chat Bot"):
    st.switch_page("pages/chat_bot.py")
