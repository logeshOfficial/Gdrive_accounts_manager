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
            scopes=self.SCOPES,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob"
        )

        auth_url, _ = flow.authorization_url(prompt="consent")
        st.info("🔐 Please authorize the app with Google Drive:")
        st.write(f"[Click here to authenticate]({auth_url})")
        auth_code = st.text_input("Enter the authorization code here:")
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

# ---------------- INVOICE PROCESSOR ----------------
class InvoiceProcessor:
    def __init__(self):
        self.client = ai_models.initiate_huggingface_model(st.secrets["api_key"])
        self.OPENAI_MODEL = st.secrets["model"]
        self.reader = None
        self.year_month_data = defaultdict(lambda: defaultdict(list))

    def safe_json_load(self, text):
        try:
            return json.loads(text)
        except:
            match = re.search(r'\[.*\]', text, re.S)
            if match:
                return json.loads(match.group())
            raise

    def extract_year_month(self, date_str):
        try:
            dt = parser.parse(date_str, dayfirst=True)
            return dt.year, dt.strftime("%B")
        except:
            return None, None

    def format_date(self, invoice_date):
        if not invoice_date:
            return ""
        try:
            dt = parser.parse(invoice_date, dayfirst=True)
            return dt.strftime("%b %d %Y")
        except:
            return invoice_date

    def is_valid_invoice(self, total):
        try:
            if total is None: return False
            total = re.sub(r"[^\d.]", "", str(total))
            return float(total) > 0 if total else False
        except:
            return False

    def create_and_upload_excel(self, drive_manager, output_folder_id, year, months_data):
        filename = f"invoices_{year}.xlsx"
        tmp_dir = tempfile.mkdtemp()
        local_path = os.path.join(tmp_dir, filename)

        # WRITE EXCEL
        with pd.ExcelWriter(local_path, engine="openpyxl", mode="w") as writer:
            sheets_written = False
            for month, invoices in months_data.items():
                if not invoices: continue
                df = pd.DataFrame(invoices)
                df.to_excel(writer, sheet_name=month, index=False)
                sheets_written = True
            if not sheets_written:
                raise RuntimeError("No valid invoice data to write")

        time.sleep(1)
        if not os.path.exists(local_path) or os.path.getsize(local_path) == 0:
            raise RuntimeError("Excel file not created correctly")

        # CHECK EXISTING FILE
        result = drive_manager.drive_execute(
            drive_manager.service.files().list(
                q=f"name='{filename}' and '{output_folder_id}' in parents and trashed=false",
                fields="files(id)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            )
        )
        existing = result.get("files", [])
        media = MediaFileUpload(local_path,
                                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                resumable=True)

        # UPLOAD
        if existing:
            request = drive_manager.service.files().update(
                fileId=existing[0]["id"],
                media_body=media,
                supportsAllDrives=True
            )
        else:
            request = drive_manager.service.files().create(
                body={"name": filename, "parents": [output_folder_id],
                      "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                media_body=media,
                supportsAllDrives=True
            )
        drive_manager.drive_execute(request)

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def extractor(self, service, files):
        results = []
        for f in files:
            ext = os.path.splitext(f['name'])[1].lower()
            text = ""
            if ext == ".pdf":
                fh = io.BytesIO()
                request = service.files().get_media(fileId=f['id'])
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                doc = fitz.open(stream=fh.getvalue(), filetype="pdf")
                for page in doc: text += page.get_text()
            else:
                continue
            results.append({"id": f["id"], "name": f["name"], "lines": [l.strip() for l in text.splitlines() if l.strip()]})
        return results

# ---------------- STREAMLIT APP ----------------
st.title("Accounts Manager - Google Drive")
PARENT_FOLDER = st.secrets["PARENT_FOLDER"]
INPUT_DOCS = st.secrets["INPUT_DOCS"]

SCOPES = ["https://www.googleapis.com/auth/drive"]

# Login / initialize Drive
if "drive_manager" not in st.session_state:
    with st.spinner("🔐 Logging into Google Drive..."):
        st.session_state.drive_manager = DriveManager(SCOPES)
    st.success("✅ Logged in successfully")

drive_manager = st.session_state.drive_manager

# Initialize folders
root_folder_id = drive_manager.get_or_create_folder(PARENT_FOLDER)
input_docs_folder_id = drive_manager.get_or_create_folder(INPUT_DOCS, parent_id=root_folder_id)
st.session_state.drive_dirs = {
    "project_id": root_folder_id,
    "scanned_docs": drive_manager.get_or_create_folder("scanned_docs", root_folder_id),
    "invalid_docs": drive_manager.get_or_create_folder("invalid_docs", root_folder_id),
    "output": drive_manager.get_or_create_folder("output", root_folder_id)
}
output_id = st.session_state.drive_dirs["output"]

# Start processing
def start_processing():
    st.success("🟢 System ready")
    st.info("📄 Processing invoices from Google Drive. Don't refresh the page.")
    invoice_processor = InvoiceProcessor()
    all_files = drive_manager.list_files_in_folder(input_docs_folder_id)
    st.info(f"all_files: {all_files}")

    batch_size = 20
    MAX_GEMINI_DOCS = 5
    batch_wise_filtered_data = []

    progress = st.progress(0)
    total_files = len(all_files)
    processed_files = 0
    filtered_batch_data = []

    if not all_files:
        st.warning("No files found in the selected folder.")
        return

    for i in range(0, len(all_files), batch_size):
        batch = all_files[i:i+batch_size]
        st.info(f"Processing batch {i+1}-{min(i+batch_size,total_files)}")
        batch_extracted = invoice_processor.extractor(drive_manager.service, batch)
        filtered_batch_data.clear()

        # Filter valid invoices
        for item in batch_extracted:
            text = item["lines"]
            if any(k in line.lower() for line in text for k in ["total", "amount due", "grand total", "invoice total"]):
                filtered_batch_data.append({"text": text, "file": {"id": item["id"], "name": item["name"]}})

        # LLM processing
        parsed_data = []
        for j in range(0, len(filtered_batch_data), MAX_GEMINI_DOCS):
            chunk = filtered_batch_data[j:j+MAX_GEMINI_DOCS]
            chunk_texts = [item["text"] for item in chunk]

            for attempt in range(5):
                try:
                    response = invoice_processor.client.responses.create(
                        model=invoice_processor.OPENAI_MODEL,
                        input=config.prompt + json.dumps(chunk_texts)
                    )
                    break
                except Exception:
                    time.sleep(5 + attempt * 5)
            else:
                st.error("❌ LLM failed after retries")
                continue

            json_output = response.output_text
            if '```json' in json_output:
                json_output = json_output.split('```json')[-1].split('```')[0].strip()
            elif '```' in json_output:
                json_output = json_output.split('```')[-1].strip()

            parsed_chunk = invoice_processor.safe_json_load(json_output)
            for k, entry in enumerate(parsed_chunk):
                entry["_file"] = chunk[k]["file"]
            parsed_data.extend(parsed_chunk)

        # Filter valid invoices & move files
        valid_file_paths, not_valid_file_paths = [], []
        filtered_data = []
        for entry in parsed_data:
            total = re.sub(r'[^\d.]', '', str(entry.get("total_amount", "")).replace(",", "").strip())
            if invoice_processor.is_valid_invoice(total):
                entry["total_amount"] = total
                filtered_data.append(entry)
                valid_file_paths.append(entry["_file"])
            else:
                not_valid_file_paths.append(entry["_file"])

        batch_wise_filtered_data.append(filtered_data)
        drive_manager.move_files_drive(valid_file_paths, "scanned_docs", st.session_state.drive_dirs)
        drive_manager.move_files_drive(not_valid_file_paths, "invalid_docs", st.session_state.drive_dirs)

        processed_files += len(batch)
        progress.progress(min(processed_files / total_files, 1.0))
        gc.collect()

    # Prepare Excel
    for batch in batch_wise_filtered_data:
        for invoice in batch:
            formatted_date = invoice_processor.format_date(invoice.get("invoice_date", ""))
            invoice["invoice_date"] = formatted_date
            year, month = invoice_processor.extract_year_month(formatted_date)
            if year and month:
                invoice_processor.year_month_data[year][month].append(invoice)

    st.info(f"Year-Month Data: {invoice_processor.year_month_data}")

    for year, months in invoice_processor.year_month_data.items():
        try:
            invoice_processor.create_and_upload_excel(
                drive_manager=drive_manager,
                output_folder_id=output_id,
                year=year,
                months_data=months
            )
            st.success(f"✅ Excel uploaded for {year}")
        except Exception as e:
            st.error(f"❌ Failed Excel for {year}: {e}")

st.button("Start Invoice Processing", on_click=start_processing)
