
import gc
import re
import tempfile
import time
import pandas as pd
import streamlit as st
from random import randint
import os
import json
from drive_manager import DriveManager
from invoice_processor import InvoiceProcessor
from google.api_core.exceptions import ResourceExhausted
from googleapiclient.http import MediaFileUpload
import config

if "initiate_invoice_processor" not in st.session_state:
    invoice_processor = InvoiceProcessor()
    st.session_state.initiate_invoice_processor = True
    
def start_processing():
    
    st.success("🟢 System ready")
    st.info("📄 Processing invoices from Google Drive. Kindly please wait until the progress complete \n Note: *** Don't refresh the page.***")


    all_files = drive_manager.list_files_in_folder(
        root_folder_id
    )

    # ================= Main Processing Loop =================
    start_time = time.time()

    batch_size = 20
    filepaths = []
    batch_data =[]
    batch_wise_filtered_data = []
    filtered_batch_data = []
    valid_file_paths = []
    not_valid_file_paths = []

    MAX_GEMINI_DOCS = 5 

    st.info(f"Total files to process: {len(all_files)}")
    # ================= Process Selected Folder =================
    filepaths = [f for f in all_files]

    progress = st.progress(0)
    status = st.empty()

    total_files = len(filepaths)
    processed_files = 0

    if not filepaths:
        st.warning("No files found in the selected folder.")
    else:
        st.info(f"{len(filepaths)} files found. Processing...")

    try:
        for i in range(0, len(filepaths), batch_size):
            parsed_data = []
            batch = filepaths[i:i+batch_size]
            status.info(
                f"Processing files {i + 1} → {min(i + batch_size, total_files)} of {total_files}"
            )
            
            st.info("Batch_len: ",len(filepaths[i:i+batch_size]))
            batch_extracted  = invoice_processor.extractor(service, filepaths[i:i+batch_size])
            
            batch_data = []
            file_path_mapping = []

            for item in batch_extracted:
                batch_data.append(item["lines"])
                
                file_path_mapping.append({
                    "id": item["id"],
                    "name": item["name"]
                })

            KEYWORDS = ["total", "amount due", "grand total", "invoice total"]

            for idx, text in enumerate(batch_data):  
                has_total = any(
                    any(k in line.lower() for k in KEYWORDS)
                    and not re.search(r'0\.00|zero', line.lower())
                    for line in text
                    )           
            
                if not has_total:
                    continue            
                
                filtered_batch_data.append({
                    "text": text,
                    "file": file_path_mapping[idx]   
                })   
                
            try:
                for j in range(0, len(filtered_batch_data), MAX_GEMINI_DOCS):
                    chunk = filtered_batch_data[j:j + MAX_GEMINI_DOCS]
                    
                    chunk_texts = [item["text"] for item in chunk]
                    
                    
                    for attempt in range(5):
                        try:
                            # response = invoice_processor.model.generate_content(
                            #     config.prompt + json.dumps(chunk_texts)
                            # )
                            response = invoice_processor.client.responses.create(
                            model=invoice_processor.OPENAI_MODEL,
                            input=config.prompt + json.dumps(chunk_texts)
                            # temperature=0,
                            # max_output_tokens=800
                            )
                            break
                        
                        except ResourceExhausted as e:
                            wait = 10 + attempt * 5
                            print(f"⏳ LLM model rate limit. Retrying in {wait}s")
                            time.sleep(wait)
                    else:
                        raise RuntimeError("❌ LLM failed after retries")

                    # st.info(response.output_text)
                    
                    json_output = response.output_text            
                            
                    if '```json' in json_output:
                        json_output = json_output.split('```json')[-1].split('```')[0].strip()
                    elif '```' in json_output:
                        json_output = json_output.split('```')[-1].strip()
                    
                    parsed_chunk = invoice_processor.safe_json_load(json_output)

                    for k, entry in enumerate(parsed_chunk):
                        entry["_file"] = chunk[k]["file"]

                    parsed_data.extend(parsed_chunk)
                    
                    time.sleep(randint(3, 7))
                            
                filtered_data = []
                
                for idx, entry in enumerate(parsed_data):
                    value = entry.get("total_amount", "")
                    total = re.sub(r'[^\d.]', '', value.replace(",", "").replace("$", "").replace("₹", "").strip())

                    if invoice_processor.is_valid_invoice(total):
                        entry["total_amount"] = total
                        filtered_data.append(entry)
                        valid_file_paths.append(entry["_file"])
                    else:
                        not_valid_file_paths.append(entry["_file"])
            
                batch_wise_filtered_data.append(filtered_data)
                
            except Exception as e:
                print(f"❌ Failed to parse or extract batch: {e}")
                with open("failed_batch.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(filtered_batch_data, indent=2))
                continue
            
            filtered_batch_data.clear()
            time.sleep(randint(3, 7))
            
            # Move processed files in Drive        
            drive_manager.move_files_drive(
                service,
                valid_file_paths,
                dest_dir="scanned_docs",
                drive_dirs=DRIVE_DIRS
            )

            drive_manager.move_files_drive(
                service,
                not_valid_file_paths,
                dest_dir="invalid_docs",
                drive_dirs=DRIVE_DIRS
            )
            
            processed_files += len(batch)
            progress.progress(min(processed_files / total_files, 1.0))

            # for f in valid_file_paths + not_valid_file_paths:
            #     processed_ids.add(f["id"])

            # tmp_state = STATE_FILE + ".tmp"

            # with open(tmp_state, "w", encoding="utf-8") as f:
            #     json.dump(list(processed_ids), f)

            # os.replace(tmp_state, STATE_FILE)

            batch_extracted.clear()
            batch_data.clear()
            file_path_mapping.clear()
            gc.collect()
            valid_file_paths.clear()
            not_valid_file_paths.clear()
                    
    except Exception as e:
        print("❌Error:", str(e))

    finally:
        for batch in batch_wise_filtered_data:
            for invoice in batch:
                formatted_date = invoice_processor.format_date(invoice.get("invoice_date", ""))
                invoice["invoice_date"] = formatted_date

                year, month = invoice_processor.extract_year_month(formatted_date)
                if year and month:
                    invoice_processor.year_month_data[year][month].append(invoice)
                    
        # ===================== EXCEL =====================
        for year, months in invoice_processor.year_month_data.items():
            fname = f"invoices_{year}.xlsx"
            tmp_dir = tempfile.mkdtemp()
            local = os.path.join(tmp_dir, fname)

            existing = drive_manager.drive_execute(
                service.files().list(
                    q=f"name='{fname}' and '{output_id}' in parents and trashed=false",
                    fields="files(id)"
                )
            )["files"]

            if existing:
                drive_manager.download_drive_file(service, existing[0]["id"], local)

            if os.path.exists(local):
                with pd.ExcelWriter(
                    local,
                    engine="openpyxl",
                    mode="a",
                    if_sheet_exists="overlay"
                ) as writer:
                    for month, data in months.items():
                        df = pd.DataFrame(data)

                        if month in writer.book.sheetnames:
                            startrow = writer.sheets[month].max_row
                            df.to_excel(
                                writer,
                                sheet_name=month,
                                index=False,
                                header=False,
                                startrow=startrow
                            )
                        else:
                            df.to_excel(writer, sheet_name=month, index=False)

                        del df
                        gc.collect()
                        time.sleep(1)
            else:
                with pd.ExcelWriter(local, engine="openpyxl", mode="w") as writer:
                    for month, data in months.items():
                        df = pd.DataFrame(data)
                        df.to_excel(writer, sheet_name=month, index=False)
                        del df
                        gc.collect()
                
            media = MediaFileUpload(local, resumable=False)
            if existing:
                drive_manager.drive_execute(service.files().update(fileId=existing[0]["id"], media_body=media))
            else:
                drive_manager.drive_execute(service.files().create(body={"name": fname, "parents": [output_id]}, media_body=media))

            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            
        status.info("✅ Processing complete!")
        st.success(f"✅ Completed in {time.time()-start_time:.2f}s")

        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"Loop execution time: {elapsed_time:.2f}s")

if st.button("Chat Bot"):
    st.cache_data.clear()
    st.switch_page("pages/chat_bot.py")
        
st.title("Accounts Manager - Google Drive")

if "init_progress" not in st.session_state:
    st.session_state.init_progress = 0

if "drive_manager" not in st.session_state:
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    with st.spinner("🔐 Logging into Google Drive..."):
        st.session_state.drive_manager = DriveManager(SCOPES)
    st.success("✅ Logged in successfully")
    
drive_manager = st.session_state.drive_manager

if "drive_dirs" not in st.session_state:
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    PROJECT_ROOT = "Invoice_Processing"
    INPUTDOCS = st.secrets["INPUTDOCS"]
    st.subheader("🚀 Initializing workspace")
    progress = st.progress(0)
    status = st.empty()
    
    # Step 1: Root folder
    status.info("📁 Checking root folder...")
    project_id = drive_manager.get_or_create_folder(PROJECT_ROOT)
    
    progress.progress(25)
    st.info(f"Processing files from folder: {INPUTDOCS}")
        
    st.session_state.drive_dirs = {
        "project_id": project_id,
        "scanned_docs": drive_manager.get_or_create_folder("scanned_docs", project_id),
        "invalid_docs": drive_manager.get_or_create_folder("invalid_docs", project_id),
        "output": drive_manager.get_or_create_folder("output", project_id),
    }
    progress.progress(100)
    status.success("✅ Initialization complete")
    time.sleep(1)
    
    service = drive_manager.service
    root_folder_id = project_id
    DRIVE_DIRS = st.session_state.drive_dirs
    output_id = st.session_state.drive_dirs["output"]
    
    start_processing()
    
st.session_state["drive_ready"] = True

    