from pathlib import Path
import time
from google_auth_oauthlib.flow import Flow
from googleapiclient.errors import HttpError
import random
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import streamlit as st

class DriveManager:
    def __init__(self, SCOPES):
        self.SCOPES = SCOPES
        self.REDIRECT_URI = st.secrets["google_oauth"]["redirect_uri"]

    def drive_execute(self, request, retries=5):
        for i in range(retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status in [403, 429, 500, 503]:
                    wait = (2 ** i) + random.random()
                    print(f"⏳ Drive retry in {wait:.2f}s")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("❌ Drive API failed after retries")

    def get_or_create_folder(self,service, folder_name, parent_id=None):
        """
        Returns folder ID. Creates folder if it doesn't exist.
        parent_id: Folder ID in which this folder should be created
        """
        query = (
            f"name='{folder_name}' and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )

        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.drive_execute(service.files().list(q=query,
            spaces="drive",
            fields="files(id, name)"))

        if results["files"]:
            return results["files"][0]["id"]
    
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }

        if parent_id:
            metadata["parents"] = [parent_id]

        folder = self.drive_execute(service.files().create(body=metadata, fields="id"))
        
        return folder["id"]

    def login_to_google_drive(self):
        flow = Flow.from_client_config(
        {
            "web": {
                "client_id": st.secrets["google_oauth"]["client_id"],
                "client_secret": st.secrets["google_oauth"]["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.REDIRECT_URI],
            }
        },
        scopes=self.SCOPES,
        redirect_uri=self.REDIRECT_URI,
        )

        # 🔹 STEP 1: Redirect user to Google
        if "code" not in st.query_params:
            auth_url, state = flow.authorization_url(
                access_type="offline",
                prompt="consent",
                include_granted_scopes="true",
            )
            st.session_state.oauth_state = state
            st.link_button("🔐 Login with Google", auth_url)
            st.stop()

        # 🔹 STEP 2: Google redirects back
        if st.session_state.get("oauth_state") != st.query_params.get("state"):
            st.error("OAuth state mismatch. Please retry login.")
            st.stop()

        flow.fetch_token(code=st.query_params["code"])
        return flow.credentials
    
    def build_drive_service(self,creds):
        return build('drive', 'v3', credentials=creds)

    def get_or_create_root_folder(self, service, folder_name):
        """
        Returns folder ID if exists, otherwise creates it.
        """
        query = (
            f"name='{folder_name}' "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )

        response = self.drive_execute(
            service.files().list(
                q=query,
                fields="files(id, name)"
            )
        )

        if response["files"]:
            return response["files"][0]["id"]

        # Create folder if not exists
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }

        folder = self.drive_execute(
            service.files().create(
                body=folder_metadata,
                fields="id"
            )
        )

        return folder["id"]


    def list_drive_folders(self,service):
        results = self.drive_execute(service.files().list(q="mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces='drive',
            fields="files(id, name)"))
        folders = results.get('files', [])
        return folders

    def list_files_in_folder(self,service, folder_id):
        
        results = self.drive_execute(service.files().list(q=f"'{folder_id}' in parents and trashed=false",
            spaces='drive',
            fields="files(id, name, mimeType)"))
        
        return results.get('files', [])
    
    def move_files_drive(self, service, files, dest_dir, drive_dirs):
        dest_folder_id = drive_dirs[dest_dir]

        for f in files:
            try:
                new_name = f"{Path(f['name']).stem}_{int(time.time())}{Path(f['name']).suffix}"
                file = self.drive_execute(
                    service.files().get(
                        fileId=f["id"],
                        fields="parents"
                    )
                )
                self.drive_execute(
                    service.files().update(
                        fileId=f["id"],
                        addParents=dest_folder_id,
                        removeParents=",".join(file["parents"]),
                        body={"name": new_name}
                    )
                )

                print(f"📁 Drive moved: {new_name}")
                
            except Exception as e:
                print(f"❌ Failed to move {f['name']}: {e}")

    def download_drive_file(self, service, file_id, local_path):
        request = service.files().get_media(fileId=file_id)

        with open(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
                
    def resolve_folder_id(self, service, folder_name, parent_id=None):
        query = (
            f"name='{folder_name}' and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )

        if parent_id:
            query += f" and '{parent_id}' in parents"

        result = self.drive_execute(service.files().list(q=query,
            fields="files(id, name)"))

        files = result.get("files", [])
        if not files:
            raise ValueError(f"❌ Folder not found in Drive: {folder_name}")

        return files[0]["id"]