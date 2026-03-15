import fitz
import os
import uuid
import shutil
import logging
import subprocess
from typing import List
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader, PdfWriter

# --- Setup & Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-suite")

def get_lo_binary():
    possible_paths = [
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return shutil.which("soffice") or shutil.which("libreoffice")

LO_BINARY = get_lo_binary()

app = FastAPI(title="PDF Suite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---

def cleanup(path: str):
    try:
        if os.path.isfile(path): os.remove(path)
        elif os.path.isdir(path): shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")

def convert_to_pdf_helper(input_path: str, output_dir: str):
    """Executes LibreOffice headless conversion."""
    command = [
        LO_BINARY, "--headless", "--convert-to", "pdf",
        "--outdir", output_dir, input_path
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)

# --- API Routes ---

@app.get("/health")
async def health():
    return {"status": "ok", "libreoffice": LO_BINARY or "missing"}

@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    pdf_path = f"out_{uid}.pdf"
    content = await file.read()
    
    doc = fitz.open()
    img_doc = fitz.open(stream=content, filetype="jpg")
    pdf_bytes = img_doc.convert_to_pdf()
    img_doc.close()
    
    pdf_doc = fitz.open("pdf", pdf_bytes)
    page = doc.new_page(width=pdf_doc[0].rect.width, height=pdf_doc[0].rect.height)
    page.show_pdf_page(page.rect, pdf_doc, 0)
    doc.save(pdf_path)
    
    background_tasks.add_task(cleanup, pdf_path)
    return FileResponse(pdf_path, media_type="application/pdf")

@app.post("/merge-pdf")
async def merge_pdfs(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    uid = str(uuid.uuid4())
    out = f"merged_{uid}.pdf"
    writer = PdfWriter()
    for f in files:
        reader = PdfReader(f.file)
        for page in reader.pages: writer.add_page(page)
    with open(out, "wb") as f: writer.write(f)
    background_tasks.add_task(cleanup, out)
    return FileResponse(out, media_type="application/pdf")

@app.post("/convert/office-to-pdf")
@app.post("/convert/html-to-pdf")
async def convert_office_or_html(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not LO_BINARY: 
        raise HTTPException(status_code=503, detail="PDF engine missing")
    
    uid = str(uuid.uuid4())
    in_path = f"in_{uid}_{file.filename}"
    out_dir = f"out_{uid}"
    os.makedirs(out_dir, exist_ok=True)
    
    with open(in_path, "wb") as f: 
        f.write(await file.read())
    
    try:
        convert_to_pdf_helper(in_path, out_dir)
        pdf_file = [f for f in os.listdir(out_dir) if f.endswith(".pdf")][0]
        out_path = os.path.join(out_dir, pdf_file)
        
        background_tasks.add_task(cleanup, in_path)
        background_tasks.add_task(cleanup, out_dir)
        return FileResponse(out_path, media_type="application/pdf")
    except Exception as e:
        cleanup(in_path)
        cleanup(out_dir)
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")