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

@app.post("/convert/html-to-pdf")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(400, "File must be HTML")
    if not LO_BINARY:
        raise HTTPException(503, "Conversion engine unavailable")

    uid = str(uuid.uuid4())
    input_path = f"temp_{uid}.html"
    output_dir = f"out_{uid}"
    os.makedirs(output_dir, exist_ok=True)

    try:
        # 1. Save uploaded HTML to a temporary file
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        # 2. Use LibreOffice (which is already working for you) to convert HTML -> PDF
        subprocess.run(
            [LO_BINARY, "--headless", "--convert-to", "pdf", "--outdir", output_dir, input_path],
            check=True, 
            timeout=60
        )

        # 3. Locate the result
        generated = [f for f in os.listdir(output_dir) if f.lower().endswith(".pdf")]
        if not generated:
            raise RuntimeError("LibreOffice failed to produce a PDF")
        
        pdf_path = os.path.join(output_dir, generated[0])
        
        # 4. Final output path to survive directory cleanup
        final_pdf = f"final_{uid}.pdf"
        shutil.move(pdf_path, final_pdf)

        background_tasks.add_task(cleanup, input_path)
        background_tasks.add_task(cleanup, output_dir)
        background_tasks.add_task(cleanup, final_pdf)

        return FileResponse(final_pdf, filename="converted.pdf", media_type="application/pdf")

    except Exception as e:
        cleanup(input_path)
        cleanup(output_dir)
        logger.exception("HTML to PDF via LibreOffice failed")
        raise HTTPException(500, f"Conversion failed: {str(e)}")

# Keep your other working endpoints (JPG-to-PDF, Merge, etc.) below
@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    pdf_path = f"out_{uid}.pdf"
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
        background_tasks.add_task(cleanup, pdf_path)
        return FileResponse(pdf_path, filename="converted.pdf", media_type="application/pdf")
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/merge-pdf")
async def merge_pdfs(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
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
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)