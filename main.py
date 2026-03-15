import fitz
import os
import uuid
import shutil
import logging
import subprocess
from typing import List
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader, PdfWriter

import os
import shutil
import subprocess

import os
import shutil

def get_lo_binary():
    # In Debian/Ubuntu images, it is usually here:
    debian_path = "/usr/bin/libreoffice"
    if os.path.exists(debian_path):
        return debian_path
    
    # Fallback to standard path search
    return shutil.which("soffice") or shutil.which("libreoffice")

# Update your existing code to use this
LO_BINARY = get_lo_binary()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-suite")

app = FastAPI(title="PDF Suite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def cleanup(path: str):
    try:
        if os.path.isfile(path): os.remove(path)
        elif os.path.isdir(path): shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Cleanup failed: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "libreoffice": LO_BINARY or "missing"}
@app.get("/debug-env")
async def debug_env():
    import subprocess
    # Run 'which' command
    try:
        path = subprocess.check_output(["which", "libreoffice"], text=True).strip()
        return {"which_libreoffice": path}
    except:
        return {"error": "libreoffice not in PATH"}


# PDF Tools
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
async def convert_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not LO_BINARY: raise HTTPException(503, "PDF engine missing")
    uid = str(uuid.uuid4())
    in_path = f"in_{uid}_{file.filename}"
    out_dir = f"out_{uid}"
    os.makedirs(out_dir, exist_ok=True)
    with open(in_path, "wb") as f: f.write(await file.read())
    subprocess.run([LO_BINARY, "--headless", "--convert-to", "pdf", "--outdir", out_dir, in_path], check=True)
    pdf_file = [f for f in os.listdir(out_dir) if f.endswith(".pdf")][0]
    out_path = os.path.join(out_dir, pdf_file)
    background_tasks.add_task(cleanup, in_path)
    background_tasks.add_task(cleanup, out_dir)
    return FileResponse(out_path, media_type="application/pdf")