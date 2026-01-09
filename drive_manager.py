import os
from pathlib import Path
import time
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import random
import time
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

class DriveManager:
    def __init__(self, SCOPES, TOKEN_FILE):
        self.SCOPES = SCOPES
        self.TOKEN_FILE = TOKEN_FILE

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

    def login_to_google_drive(self, force_relogin=False):
        creds = None

        if os.path.exists(self.TOKEN_FILE) and not force_relogin:
            try:
                creds = Credentials.from_authorized_user_file(self.TOKEN_FILE, self.SCOPES)
            except Exception as e:
                print("⚠️ Corrupted token.json detected. Re-authenticating...")
                os.remove(self.TOKEN_FILE)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # 🔒 SAVE TOKEN
            tmp_token = self.TOKEN_FILE + ".tmp"
            with open(tmp_token, "w") as token:
                token.write(creds.to_json())
            os.replace(tmp_token, self.TOKEN_FILE)
            
        return creds

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