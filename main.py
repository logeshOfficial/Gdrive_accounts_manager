import streamlit as st
# ------------------- STREAMLIT UI -------------------
st.set_page_config(page_title="Home", layout="wide")
st.title("Home")

if "drive_creds" not in st.session_state:
    st.info("Please connect Google Drive")
    if st.button("Connect Drive"):
        st.switch_page("pages/load_files_from_gdrive.py")
else:
    st.success("Drive connected")

if st.button("Drive Manager"):
    st.switch_page("pages/load_files_from_gdrive.py")

if st.button("Chat Bot"):
    st.switch_page("pages/chat_bot.py")
