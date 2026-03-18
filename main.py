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
@app.post("/convert/jpg-to-pdf")
async def convert_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    img_path = f"input_{unique_id}.jpg"
    pdf_path = f"output_{unique_id}.pdf"

    try:
        with open(img_path, "wb") as f:
            f.write(await file.read())

        doc = fitz.open() 
        img = fitz.open(img_path)
        pdfbytes = img.convert_to_pdf()
        img.close()

        img_pdf = fitz.open("pdf", pdfbytes)
        page = doc.new_page(width=img_pdf[0].rect.width, height=img_pdf[0].rect.height)
        page.show_pdf_page(img_pdf[0].rect, img_pdf, 0)
        doc.save(pdf_path)
        doc.close()

        #background_tasks.add_task(remove_file, img_path)
        #background_tasks.add_task(remove_file, pdf_path)
        return FileResponse(pdf_path, filename="converted.pdf")
    except Exception as e:
        logger.error(f"JPG conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/merge-pdf")
async def merge_pdf(): return {"error": "Not implemented"}

@app.post("/split-pdf")
async def split_pdf(): return {"error": "Not implemented"}