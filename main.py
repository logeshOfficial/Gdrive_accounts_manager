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
