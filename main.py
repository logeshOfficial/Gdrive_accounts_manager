import streamlit as st
import os
import time
from drive_manager import DriveManager
from pages.load_files_from_gdrive import start_processing as invoice_processing

# ------------------ CONFIG ------------------
st.set_page_config(page_title="Accounts Manager", layout="wide")
st.title("📂 Accounts Manager - Home")

SCOPES = ['https://www.googleapis.com/auth/drive']
INPUTDOCS = os.getenv("INPUTDOCS", "InputDocs")  # Default root folder

# ------------------ INITIALIZE DRIVE MANAGER ------------------
if "drive_manager" not in st.session_state:
    try:
        st.session_state.drive_manager = DriveManager(SCOPES)
    except KeyError:
        st.error("Google OAuth secrets not found. Add them in Streamlit app settings.")
        st.stop()

drive_manager = st.session_state.drive_manager

# ------------------ DRIVE LOGIN ------------------
def connect_drive():
    creds = drive_manager.login_to_google_drive()
    if creds:
        st.session_state.drive_creds = creds
        st.success("✅ Drive connected")
        st.rerun()  # Refresh the UI after login
    else:
        st.warning("⚠️ Drive login failed. Try again.")

if "drive_creds" not in st.session_state:
    st.info("🔐 Please connect your Google Drive to continue")
    if st.button("Connect Drive"):
        connect_drive()
    st.stop()  # Stop here until login completes

# ------------------ DRIVE READY ------------------
st.success("✅ Google Drive is ready")
service = drive_manager.build_drive_service(st.session_state.drive_creds)

# ------------------ INITIALIZE FOLDERS ------------------
if "initialized" not in st.session_state or not st.session_state.initialized:
    with st.spinner("⚙️ Initializing workspace..."):
        root_folder_id = drive_manager.get_or_create_root_folder(service, INPUTDOCS)
        DRIVE_DIRS = {}
        for folder in ["scanned_docs", "invalid_docs", "output"]:
            DRIVE_DIRS[folder] = drive_manager.get_or_create_folder(service, folder, parent_id=root_folder_id)
            time.sleep(0.3)  # Smooth UX
        st.session_state.root_folder_id = root_folder_id
        st.session_state.DRIVE_DIRS = DRIVE_DIRS
        st.session_state.initialized = True
    st.success("✅ Initialization complete")

# ------------------ START PROCESSING ------------------
def start_processing():
    with st.spinner("🟢 Processing invoices, please wait..."):
        invoice_processing()
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
        st.switch_page("load_files_from_gdrive")  # Switch to Drive Manager page

with col2:
    if st.button("Chat Bot"):
        st.switch_page("chat_bot")  # Switch to Chat Bot page
