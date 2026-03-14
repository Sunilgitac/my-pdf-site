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
from weasyprint import HTML

# Logging setup
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

# Log every request
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"← {response.status_code}")
    return response

def cleanup(path: str):
    """Remove file or directory safely"""
    try:
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Cleanup failed for {path}: {e}")

# Find libreoffice binary
LO_BINARY = shutil.which("libreoffice") or shutil.which("soffice")

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "libreoffice": "available" if LO_BINARY else "missing"
    }

@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.content_type.startswith("image/jpeg"):
        raise HTTPException(400, "File must be a JPEG image")

    uid = str(uuid.uuid4())
    pdf_path = f"output_{uid}.pdf"

    try:
        content = await file.read()
        doc = fitz.open()
        img_doc = fitz.open(stream=content, filetype="jpg")
        pdf_bytes = img_doc.convert_to_pdf()
        img_doc.close()

        pdf_doc = fitz.open("pdf", pdf_bytes)
        page = doc.new_page(width=pdf_doc[0].rect.width, height=pdf_doc[0].rect.height)
        page.show_pdf_page(page.rect, pdf_doc, 0)
        doc.save(pdf_path)
        doc.close()
        pdf_doc.close()

        background_tasks.add_task(cleanup, pdf_path)
        return FileResponse(pdf_path, filename="converted.pdf", media_type="application/pdf")
    except Exception as e:
        logger.exception("JPG → PDF failed")
        raise HTTPException(500, f"Conversion failed: {str(e)}")

@app.post("/merge-pdf")
async def merge_pdfs(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    if len(files) < 2:
        raise HTTPException(400, "Please upload at least 2 PDF files")

    uid = str(uuid.uuid4())
    output_path = f"merged_{uid}.pdf"

    try:
        writer = PdfWriter()
        for pdf_file in files:
            reader = PdfReader(pdf_file.file)
            for page in reader.pages:
                writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        background_tasks.add_task(cleanup, output_path)
        return FileResponse(output_path, filename="merged.pdf", media_type="application/pdf")
    except Exception as e:
        cleanup(output_path)
        logger.exception("PDF merge failed")
        raise HTTPException(500, f"Merge failed: {str(e)}")

@app.post("/convert/office-to-pdf")
async def office_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not LO_BINARY:
        raise HTTPException(503, "LibreOffice not available")

    uid = str(uuid.uuid4())
    input_path = f"input_{uid}_{file.filename}"
    output_dir = f"out_{uid}"
    os.makedirs(output_dir, exist_ok=True)

    try:
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        subprocess.run([LO_BINARY, "--headless", "--convert-to", "pdf", "--outdir", output_dir, input_path], check=True, timeout=90)

        generated = [f for f in os.listdir(output_dir) if f.lower().endswith(".pdf")]
        pdf_path = os.path.join(output_dir, generated[0])

        background_tasks.add_task(cleanup, input_path)
        background_tasks.add_task(cleanup, output_dir)

        return FileResponse(pdf_path, filename="converted.pdf", media_type="application/pdf")
    except Exception as e:
        cleanup(input_path)
        cleanup(output_dir)
        raise HTTPException(500, f"Conversion failed: {str(e)}")

@app.post("/convert/html-to-pdf")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(400, "File must be HTML")

    uid = str(uuid.uuid4())
    pdf_path = f"html_{uid}.pdf"

    try:
        content = await file.read()
        # WeasyPrint conversion logic
        HTML(string=content.decode("utf-8")).write_pdf(pdf_path)

        background_tasks.add_task(cleanup, pdf_path)
        return FileResponse(pdf_path, filename="converted.pdf", media_type="application/pdf")
    except Exception as e:
        cleanup(pdf_path)
        logger.exception("HTML → PDF failed")
        raise HTTPException(500, f"Conversion failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)