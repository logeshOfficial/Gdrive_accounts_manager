# import os
# from pathlib import Path
# import time
# from googleapiclient.errors import HttpError
# import random
# import time
# from google.oauth2.service_account import Credentials
# from googleapiclient.discovery import build
# from googleapiclient.http import MediaIoBaseDownload
# import streamlit as st

# class DriveManager:
#     def __init__(self, SCOPES):
#         try:
#             # 🔐 Load service account from Streamlit secrets
#             creds = Credentials.from_service_account_info(
#                 st.secrets["google_service_account"],
#                 scopes=SCOPES,
#             )

#             self.service = build("drive", "v3", credentials=creds)
#         except KeyError:
#             st.error("Error ocured while loading Google Drive credentials on secrets. Please contact the administrator.")
#             st.stop()
            
#     def get_child_folder_id(self, service, folder_name, parent_id):
#         query = (
#             f"name='{folder_name}' and "
#             f"mimeType='application/vnd.google-apps.folder' and "
#             f"'{parent_id}' in parents and "
#             f"trashed=false"
#         )

#         result = service.files().list(
#             q=query,
#             fields="files(id, name)"
#         ).execute()

#         if not result["files"]:
#             raise ValueError("Folder not found")

#         return result["files"][0]["id"]


#     def drive_execute(self, request, retries=8):
#         for i in range(retries):
#             try:
#                 time.sleep(0.4)
#                 return request.execute()
#             except HttpError as e:
#                 if e.resp.status in [403, 429, 500, 503]:
#                     wait = (2 ** i) + random.random()
#                     print(f"⏳ Drive retry in {wait:.2f}s")
#                     time.sleep(wait)
#                 else:
#                     raise
#         raise RuntimeError("❌ Drive API failed after retries")

#     def get_or_create_folder(self, folder_name, parent_id=None):
#         """
#         Returns folder ID. Creates folder if it doesn't exist.
#         parent_id: Folder ID in which this folder should be created
#         """
#         query = (
#             f"name='{folder_name}' and "
#             f"mimeType='application/vnd.google-apps.folder' and "
#             f"trashed=false"
#         )

#         if parent_id:
#             query += f" and '{parent_id}' in parents"

#         results = self.drive_execute(self.service.files().list(q=query,
#             spaces="drive",
#             fields="files(id, name)"))

#         if results["files"]:
#             return results["files"][0]["id"]
    
#         metadata = {
#             "name": folder_name,
#             "mimeType": "application/vnd.google-apps.folder"
#         }

#         if parent_id:
#             metadata["parents"] = [parent_id]

#         folder = self.drive_execute(self.service.files().create(body=metadata, fields="id"))
        
#         return folder["id"]

#     def get_or_create_root_folder(self, folder_name):
#         """
#         Returns folder ID if exists, otherwise creates it.
#         """
#         query = (
#             f"name='{folder_name}' "
#             "and mimeType='application/vnd.google-apps.folder' "
#             "and trashed=false"
#         )

#         response = self.drive_execute(
#             self.service.files().list(
#                 q=query,
#                 fields="files(id, name)"
#             )
#         )

#         if response["files"]:
#             return response["files"][0]["id"]

#         # Create folder if not exists
#         folder_metadata = {
#             "name": folder_name,
#             "mimeType": "application/vnd.google-apps.folder"
#         }

#         folder = self.drive_execute(
#             self.service.files().create(
#                 body=folder_metadata,
#                 fields="id"
#             )
#         )

#         return folder["id"]

#     def list_files_in_folder(self, folder_id):
        
#         results = self.drive_execute(self.service.files().list(q=f"'{folder_id}' in parents and trashed=false",
#             spaces='drive',
#             fields="files(id, name, mimeType)"))
        
#         return results.get('files', [])
    
#     def move_files_drive(self, files, dest_dir, drive_dirs):
#         dest_folder_id = drive_dirs[dest_dir]

#         for f in files:
#             try:
#                 new_name = f"{Path(f['name']).stem}_{int(time.time())}{Path(f['name']).suffix}"
#                 file = self.drive_execute(
#                     self.service.files().get(
#                         fileId=f["id"],
#                         fields="parents"
#                     )
#                 )
#                 self.drive_execute(
#                     self.service.files().update(
#                         fileId=f["id"],
#                         addParents=dest_folder_id,
#                         removeParents=",".join(file["parents"]),
#                         body={"name": new_name}
#                     )
#                 )

#                 print(f"📁 Drive moved: {new_name}")
                
#             except Exception as e:
#                 print(f"❌ Failed to move {f['name']}: {e}")

#     def download_drive_file(self, file_id, local_path):
#         request = self.service.files().get_media(fileId=file_id)

#         with open(local_path, "wb") as fh:
#             downloader = MediaIoBaseDownload(fh, request)
#             done = False
#             while not done:
#                 _, done = downloader.next_chunk()
                
#     def resolve_folder_id(self, folder_name, parent_id=None):
#         query = (
#             f"name='{folder_name}' and "
#             f"mimeType='application/vnd.google-apps.folder' and "
#             f"trashed=false"
#         )

#         if parent_id:
#             query += f" and '{parent_id}' in parents"

#         result = self.drive_execute(self.service.files().list(q=query,
#             fields="files(id, name)"))

#         files = result.get("files", [])
#         if not files:
#             raise ValueError(f"❌ Folder not found in Drive: {folder_name}")

#         return files[0]["id"]

# app.py
import os
import io
import json
import re
import time
import gc
import tempfile
from pathlib import Path
from random import randint
from collections import defaultdict

import pandas as pd
import fitz  # PyMuPDF
import streamlit as st
from dateutil import parser
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

import ai_models
import config
import random

# ---------------- DRIVE MANAGER ----------------
class DriveManager:
    def __init__(self, SCOPES):
        self.SCOPES = SCOPES
        if "oauth_creds" in st.session_state:
            creds = st.session_state.oauth_creds
        else:
            creds = self.authenticate_oauth()
            st.session_state.oauth_creds = creds
        self.service = self.build_service(creds)

    def authenticate_oauth(self):
        client_config = st.secrets["google_oauth"]

        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/drive.file"]
        )

        auth_url, _ = flow.authorization_url(prompt="consent")
        st.write(f"Authorize here: {auth_url}")

        auth_code = st.text_input("Enter the authorization code:")
        if auth_code:
            flow.fetch_token(code=auth_code)
            st.success("✅ Google Drive authentication successful!")
            return flow.credentials
        else:
            st.stop()

    def build_service(self, creds):
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=creds)

    # ---------------- DRIVE METHODS -----------------
    def drive_execute(self, request, retries=8):
        for i in range(retries):
            try:
                time.sleep(0.4)
                return request.execute()
            except HttpError as e:
                if e.resp.status in [403, 429, 500, 503]:
                    wait = (2 ** i) + random.random()
                    print(f"⏳ Drive retry in {wait:.2f}s")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("❌ Drive API failed after retries")

    def get_or_create_folder(self, folder_name, parent_id=None):
        query = (
            f"name='{folder_name}' and "
            f"mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"
        results = self.drive_execute(
            self.service.files().list(q=query, spaces="drive", fields="files(id, name)")
        )
        if results["files"]:
            return results["files"][0]["id"]
        metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]
        folder = self.drive_execute(self.service.files().create(body=metadata, fields="id"))
        return folder["id"]

    def list_files_in_folder(self, folder_id):
        results = self.drive_execute(
            self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields="files(id, name, mimeType)"
            )
        )
        return results.get('files', [])

    def move_files_drive(self, files, dest_dir, drive_dirs):
        dest_folder_id = drive_dirs[dest_dir]
        for f in files:
            try:
                new_name = f"{Path(f['name']).stem}_{int(time.time())}{Path(f['name']).suffix}"
                file = self.drive_execute(self.service.files().get(fileId=f["id"], fields="parents"))
                self.drive_execute(
                    self.service.files().update(
                        fileId=f["id"],
                        addParents=dest_folder_id,
                        removeParents=",".join(file["parents"]),
                        body={"name": new_name}
                    )
                )
            except Exception as e:
                print(f"❌ Failed to move {f['name']}: {e}")

    def download_drive_file(self, file_id, local_path):
        request = self.service.files().get_media(fileId=file_id)
        with open(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
