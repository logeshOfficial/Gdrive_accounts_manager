import streamlit as st
from drive_manager import DriveManager

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service():
    if "drive_manager" not in st.session_state:
        st.session_state.drive_manager = DriveManager(SCOPES)
    drive_manager = st.session_state.drive_manager

    if "drive_creds" not in st.session_state:
        st.info("🔐 Please connect Google Drive")
        if st.button("Connect Drive"):
            creds = drive_manager.login_to_google_drive()
            if creds:
                st.session_state.drive_creds = creds
                st.success("✅ Drive connected")
                st.experimental_rerun()
        st.stop()  # Stop until login completes

    return drive_manager.build_drive_service(st.session_state.drive_creds)
