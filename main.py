import fitz
import os
import io
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
    paths = ["/usr/bin/soffice", "/usr/bin/libreoffice", "/usr/lib/libreoffice/program/soffice"]
    for path in paths:
        if os.path.exists(path): return path
    return shutil.which("soffice") or shutil.which("libreoffice")

LO_BINARY = get_lo_binary()
app = FastAPI(title="PDF Suite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Functions ---
def cleanup(path: str):
    try:
        if os.path.isfile(path): os.remove(path)
        elif os.path.isdir(path): shutil.rmtree(path, ignore_errors=True)
    except Exception as e: logger.warning(f"Cleanup failed: {e}")

def convert_to_pdf_helper(input_path: str, output_dir: str):
    command = [LO_BINARY, "--headless", "--convert-to", "pdf", "--outdir", output_dir, input_path]
    subprocess.run(command, capture_output=True, text=True, check=True)

# --- API Routes ---
@app.get("/health")
async def health():
    return {"status": "ok", "libreoffice": LO_BINARY or "missing"}

@app.post("/convert/office-to-pdf")
async def convert_office_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not LO_BINARY: raise HTTPException(status_code=503, detail="PDF engine missing")
    uid = str(uuid.uuid4())
    in_path = f"in_{uid}_{file.filename}"
    out_dir = f"out_{uid}"
    os.makedirs(out_dir, exist_ok=True)
    with open(in_path, "wb") as f: f.write(await file.read())
    try:
        convert_to_pdf_helper(in_path, out_dir)
        generated_files = [f for f in os.listdir(out_dir) if f.lower().endswith(".pdf")]
        if not generated_files: raise Exception("No PDF generated")
        out_path = os.path.join(out_dir, generated_files[0])
        background_tasks.add_task(cleanup, in_path)
        background_tasks.add_task(cleanup, out_dir)
        return FileResponse(out_path, media_type="application/pdf")
    except Exception as e:
        cleanup(in_path); cleanup(out_dir)
        raise HTTPException(status_code=500, detail=str(e))

# Placeholder routes for other buttons to prevent 404s
# --- Functional Routes ---

@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    pdf_path = f"out_{uid}.pdf"
    
    # 1. Get the extension to handle jpg, jpeg, or png
    ext = os.path.splitext(file.filename)[1].lower().replace('.', '')
    if ext == 'jpg': ext = 'jpeg'
    
    try:
        # 2. Open image from bytes
        img_data = await file.read()
        img_doc = fitz.open(stream=img_data, filetype=ext)
        
        # 3. Convert image to PDF format
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()
        
        # 4. Save to temporary file
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
            
        background_tasks.add_task(cleanup, pdf_path)
        return FileResponse(pdf_path, media_type="application/pdf")
        
    except Exception as e:
        logger.error(f"JPG conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Image conversion failed: {str(e)}")
# --- Updated Functional Merge Route ---
@app.post("/merge-pdf")
async def merge_pdfs(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    uid = str(uuid.uuid4())
    out = f"merged_{uid}.pdf"
    
    writer = PdfWriter()
    for f in files:
        # Read the file contents into memory
        content = await f.read()
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages:
            writer.add_page(page)
    
    with open(out, "wb") as f:
        writer.write(f)
        
    background_tasks.add_task(cleanup, out)
    return FileResponse(out, media_type="application/pdf")

@app.post("/split-pdf")
async def split_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    out_path = f"split_{uid}.pdf"
    
    pdf_doc = fitz.open(stream=await file.read(), filetype="pdf")
    # Example: extract just the first page
    new_doc = fitz.open()
    new_doc.insert_pdf(pdf_doc, from_page=0, to_page=0)
    new_doc.save(out_path)
    
    background_tasks.add_task(cleanup, out_path)
    return FileResponse(out_path, media_type="application/pdf")
