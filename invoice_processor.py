import os
import io
import json
import re
from dateutil import parser
import tempfile
import fitz  # PyMuPDF
import easyocr
from googleapiclient.http import MediaIoBaseDownload
from collections import defaultdict
import ai_models
from dotenv import load_dotenv
# import google.generativeai as genai
import streamlit as st

load_dotenv()

class InvoiceProcessor:
    def __init__(self):
        self.client_info = ai_models.initiate_huggingface_model(st.secrets["api_key "])
        self.client = self.client_info["client"]
        self.OPENAI_MODEL = st.secrets["model"]

        self.reader = None

        self.year_month_data = defaultdict(lambda: defaultdict(list))
    
    @st.cache_resource
    def get_easyocr_reader():
        import easyocr
        return easyocr.Reader(['en'], gpu=False)
    
    # def get_ocr_reader(self):
    #     if self.reader is None:
    #         import easyocr
    #         self.reader = easyocr.Reader(['en'], gpu=False)
    #     return self.reader
    
    # ================= LLM Call =================
    def safe_json_load(self, text):
        try:
            return json.loads(text)
        except:
            match = re.search(r'\[.*\]', text, re.S)
            if match:
                return json.loads(match.group())
            raise
        
    # ================= Invoice Extraction Logic =================
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
            if not total or float(total) == 0.0:
                return False
            
            return True
        
        except Exception as e:
            print("is_not_valid(expection): ", str(e))
            print("Exception: ", str(e))
            return False

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
                for page in doc:
                    text += page.get_text()

            elif ext in [".png", ".jpg", ".jpeg"]:
                fh = io.BytesIO()
                request = service.files().get_media(fileId=f['id'])
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(fh.getvalue())
                    temp_path = tmp.name

                self.reader = self.get_easyocr_reader()
                text = "\n".join(self.reader.readtext(temp_path, detail=0, paragraph=True))
                os.remove(temp_path)

            else:
                continue

            results.append({
                "id": f["id"],
                "name": f["name"],
                "lines": [l.strip() for l in text.splitlines() if l.strip()]
            })

        return results