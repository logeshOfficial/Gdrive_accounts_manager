import streamlit as st
import time
import os
import gc
import tempfile
import json
from random import randint
from drive_manager import DriveManager
from invoice_processor import InvoiceProcessor
from googleapiclient.http import MediaFileUpload
import config
from utils.drive_login import get_drive_service
service = get_drive_service()
drive_manager = st.session_state.drive_manager

# ------------------ PAGE CONFIG ------------------
st.set_page_config(page_title="Invoice Processor", layout="wide")
st.title("🗂 Invoice Processing - Google Drive")

# ------------------ INIT PROCESSOR ------------------
invoice_processor = InvoiceProcessor()
STATE_FILE = "/tmp/processing_state.json"

if "processed_ids" not in st.session_state:
    st.session_state.processed_ids = set()

if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, "r") as f:
            st.session_state.processed_ids = set(json.load(f))
    except Exception:
        st.warning("⚠️ Previous state corrupted, starting fresh.")

# ------------------ LOAD DRIVE FILES ------------------
def get_pending_files():
    root_folder_id = st.session_state.root_folder_id
    all_files = drive_manager.list_files_in_folder(service, root_folder_id)
    # Only unprocessed files
    return [f for f in all_files if f["id"] not in st.session_state.processed_ids]

# ------------------ PROCESSING ------------------
def start_processing():
    DRIVE_DIRS = st.session_state.DRIVE_DIRS
    output_id = DRIVE_DIRS["output"]

    files_to_process = get_pending_files()
    total_files = len(files_to_process)
    if total_files == 0:
        st.warning("No new files to process.")
        return

    st.info(f"📄 Found {total_files} new files. Starting processing...")

    progress = st.progress(0)
    status = st.empty()

    batch_size = 20
    MAX_GEMINI_DOCS = 5

    valid_file_paths = []
    not_valid_file_paths = []
    batch_wise_filtered_data = []

    start_time = time.time()

    for i in range(0, total_files, batch_size):
        batch = files_to_process[i:i+batch_size]
        status.info(f"Processing files {i+1} → {min(i+batch_size, total_files)} of {total_files}")

        # Extract invoice text
        batch_extracted = invoice_processor.extractor(service, batch)

        batch_data = []
        file_mapping = []
        filtered_batch_data = []

        for item in batch_extracted:
            batch_data.append(item["lines"])
            file_mapping.append({"id": item["id"], "name": item["name"]})

        KEYWORDS = ["total", "amount due", "grand total", "invoice total"]

        # Filter files with total amounts
        for idx, text in enumerate(batch_data):
            has_total = any(
                any(k in line.lower() for k in KEYWORDS)
                and not "0.00" in line.lower()
                for line in text
            )
            if not has_total:
                continue
            filtered_batch_data.append({"text": text, "file": file_mapping[idx]})

        # Send to LLM in small chunks
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
                except Exception as e:
                    wait = 10 + attempt*5
                    status.warning(f"⏳ LLM rate limit, retrying in {wait}s...")
                    time.sleep(wait)
            else:
                st.error("❌ LLM failed after retries")
                continue

            # Parse JSON
            json_output = response.output_text
            if '```json' in json_output:
                json_output = json_output.split('```json')[-1].split('```')[0].strip()
            elif '```' in json_output:
                json_output = json_output.split('```')[-1].strip()

            parsed_chunk = invoice_processor.safe_json_load(json_output)
            for k, entry in enumerate(parsed_chunk):
                entry["_file"] = chunk[k]["file"]
            parsed_data.extend(parsed_chunk)

            time.sleep(randint(2, 5))

        # Validate invoices
        filtered_data = []
        for entry in parsed_data:
            value = entry.get("total_amount", "")
            total = "".join(c for c in value if c.isdigit() or c == ".")
            if invoice_processor.is_valid_invoice(total):
                entry["total_amount"] = total
                filtered_data.append(entry)
                valid_file_paths.append(entry["_file"])
            else:
                not_valid_file_paths.append(entry["_file"])

        batch_wise_filtered_data.append(filtered_data)

        # Move files in Drive
        drive_manager.move_files_drive(service, valid_file_paths, "scanned_docs", DRIVE_DIRS)
        drive_manager.move_files_drive(service, not_valid_file_paths, "invalid_docs", DRIVE_DIRS)

        # Update processed IDs and state file
        for f in valid_file_paths + not_valid_file_paths:
            st.session_state.processed_ids.add(f["id"])
        tmp_state = STATE_FILE + ".tmp"
        with open(tmp_state, "w") as f:
            json.dump(list(st.session_state.processed_ids), f)
        os.replace(tmp_state, STATE_FILE)

        # Update progress bar
        progress.progress(min((i+batch_size)/total_files, 1.0))

        # Cleanup
        batch_extracted.clear()
        batch_data.clear()
        file_mapping.clear()
        valid_file_paths.clear()
        not_valid_file_paths.clear()
        gc.collect()

    status.success("✅ Batch processing complete!")

    # ------------------ SAVE TO EXCEL ------------------
    st.info("📥 Saving invoices to Excel in Drive...")
    for batch in batch_wise_filtered_data:
        for invoice in batch:
            formatted_date = invoice_processor.format_date(invoice.get("invoice_date", ""))
            invoice["invoice_date"] = formatted_date

            year, month = invoice_processor.extract_year_month(formatted_date)
            if year and month:
                invoice_processor.year_month_data[year][month].append(invoice)
                    
    for year, months in invoice_processor.year_month_data.items():
        fname = f"invoices_{year}.xlsx"
        tmp_dir = tempfile.mkdtemp()
        local_file = os.path.join(tmp_dir, fname)

        # Download existing if exists
        existing = drive_manager.drive_execute(
            service.files().list(
                q=f"name='{fname}' and '{DRIVE_DIRS['output']}' in parents and trashed=false",
                fields="files(id)"
            )
        )["files"]

        if existing:
            drive_manager.download_drive_file(service, existing[0]["id"], local_file)

        # Write Excel
        import pandas as pd

        if os.path.exists(local_file):
            with pd.ExcelWriter(local_file, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                for month, data in months.items():
                    df = pd.DataFrame(data)
                    if month in writer.book.sheetnames:
                        startrow = writer.sheets[month].max_row
                        df.to_excel(writer, sheet_name=month, index=False, header=False, startrow=startrow)
                    else:
                        df.to_excel(writer, sheet_name=month, index=False)
                    del df
        else:
            with pd.ExcelWriter(local_file, engine="openpyxl", mode="w") as writer:
                for month, data in months.items():
                    df = pd.DataFrame(data)
                    df.to_excel(writer, sheet_name=month, index=False)
                    del df

        # Upload to Drive
        media = MediaFileUpload(local_file, resumable=False)
        if existing:
            drive_manager.drive_execute(service.files().update(fileId=existing[0]["id"], media_body=media))
        else:
            drive_manager.drive_execute(service.files().create(body={"name": fname, "parents":[DRIVE_DIRS['output']]}, media_body=media))

        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    st.success(f"✅ All invoices processed in {time.time()-start_time:.2f}s!")
