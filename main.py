# import streamlit as st
# # ------------------- STREAMLIT UI -------------------
# st.set_page_config(page_title="Home", layout="wide")
# st.title("Home")

# if "drive_creds" not in st.session_state:
#     st.info("Please connect Google Drive")
#     if st.button("Connect Drive"):
#         st.switch_page("pages/load_files_from_gdrive.py")
# else:
#     st.success("Drive connected")

# if st.button("Drive Manager"):
#     st.switch_page("pages/load_files_from_gdrive.py")

# if st.button("Chat Bot"):
#     st.switch_page("pages/chat_bot.py")

import streamlit as st
from drive_manager import DriveManager
import time
import os

# ------------------ CONFIG ------------------
st.set_page_config(page_title="Accounts Manager", layout="wide")
st.title("Accounts Manager - Home")

# Google Drive OAuth
SCOPES = ['https://www.googleapis.com/auth/drive']
INPUTDOCS = os.getenv("INPUTDOCS", "InputDocs")

# Initialize DriveManager
if "drive_manager" not in st.session_state:
    st.session_state.drive_manager = DriveManager(SCOPES)

drive_manager = st.session_state.drive_manager

# ------------------ OAUTH ------------------
def connect_drive():
    creds = drive_manager.login_to_google_drive()
    if creds:
        st.session_state.drive_creds = creds
        st.success("✅ Drive connected")
    else:
        st.warning("⚠️ Drive login failed")

if "drive_creds" not in st.session_state:
    st.info("Please login to Google Drive")
    if st.button("🔐 Connect Drive"):
        connect_drive()
    st.stop()  # Stop here until login completes

# ------------------ DRIVE READY ------------------
st.success("✅ Drive connected")

service = drive_manager.build_drive_service(st.session_state.drive_creds)

# ------------------ INITIALIZE FOLDERS ------------------
if "initialized" not in st.session_state:
    st.session_state.initialized = False

if not st.session_state.initialized:
    with st.spinner("Initializing workspace..."):
        root_folder_id = drive_manager.get_or_create_root_folder(service, INPUTDOCS)
        DRIVE_DIRS = {}
        for folder in ["scanned_docs", "invalid_docs", "output"]:
            DRIVE_DIRS[folder] = drive_manager.get_or_create_folder(service, folder, parent_id=root_folder_id)
            time.sleep(0.3)  # Smooth UX
        st.session_state.root_folder_id = root_folder_id
        st.session_state.DRIVE_DIRS = DRIVE_DIRS
        st.session_state.initialized = True
    st.success("✅ Initialization complete")

# ------------------ PROCESSING ------------------
def start_processing():
    st.info("🟢 Processing invoices...")
    # Add your processing logic here, e.g., start_processing() from your original script
    time.sleep(2)
    st.success("✅ Processing complete!")

if st.button("▶ Start Processing"):
    start_processing()

# ------------------ NAVIGATION ------------------
st.divider()
st.subheader("Quick Links")
col1, col2 = st.columns(2)
with col1:
    if st.button("Drive Manager"):
        st.experimental_set_query_params(page="load_files_from_gdrive")
with col2:
    if st.button("Chat Bot"):
        st.experimental_set_query_params(page="chat_bot")
