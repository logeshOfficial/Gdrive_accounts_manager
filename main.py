import streamlit as st
from utils.drive_login import get_drive_service
import os
import time

st.set_page_config(page_title="Accounts Manager", layout="wide")
st.title("📂 Accounts Manager - Home")

INPUTDOCS = os.getenv("INPUTDOCS", "InputDocs")

service = get_drive_service()  # Single login check
drive_manager = st.session_state.drive_manager

# Initialize folders once
if "initialized" not in st.session_state:
    st.session_state.initialized = False

if not st.session_state.initialized:
    from drive_manager import DriveManager
    drive_manager = st.session_state.drive_manager
    with st.spinner("⚙️ Initializing workspace..."):
        root_folder_id = drive_manager.get_or_create_root_folder(service, INPUTDOCS)
        DRIVE_DIRS = {}
        for folder in ["scanned_docs", "invalid_docs", "output"]:
            DRIVE_DIRS[folder] = drive_manager.get_or_create_folder(service, folder, parent_id=root_folder_id)
            time.sleep(0.2)
        st.session_state.root_folder_id = root_folder_id
        st.session_state.DRIVE_DIRS = DRIVE_DIRS
        st.session_state.initialized = True
    st.success("✅ Initialization complete")

# Navigation buttons
st.divider()
st.subheader("Quick Links")
col1, col2 = st.columns(2)
with col1:
    if st.button("Drive Manager"):
        st.switch_page("load_files_from_gdrive")
with col2:
    if st.button("Invoice Assistant"):
        st.switch_page("chat_bot")
