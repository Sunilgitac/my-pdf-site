import fitz
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import subprocess
import logging
from typing import List
from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa
import shutil

import os
import shutil

# Check if LibreOffice is in the path
# If the variable is set, it will prioritize that path
libre_path = os.getenv('LIBREOFFICE_PATH', 'libreoffice')

if not shutil.which(libre_path):
    # This matches the error you are seeing
    raise Exception(f"LibreOffice not found at {libre_path}")

# Setup logging to see what's happening in your Railway logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-suite")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to log every incoming request path
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

def remove_file(path: str):
    if os.path.exists(path):
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)

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

        background_tasks.add_task(remove_file, img_path)
        background_tasks.add_task(remove_file, pdf_path)
        return FileResponse(pdf_path, filename="converted.pdf")
    except Exception as e:
        logger.error(f"JPG conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/merge-pdf")
async def merge_pdf(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    try:
        merger = PdfWriter()
        for file in files:
            merger.append(file.file)
        
        output_path = f"merged_{uuid.uuid4()}.pdf"
        with open(output_path, "wb") as f:
            merger.write(f)
        merger.close()
        
        background_tasks.add_task(remove_file, output_path)
        return FileResponse(output_path, filename="merged_document.pdf")
    except Exception as e:
        logger.error(f"Merge error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/split-pdf")
async def split_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        reader = PdfReader(file.file)
        writer = PdfWriter()
        if len(reader.pages) > 0:
            writer.add_page(reader.pages[0])
        
        output_path = f"split_{uuid.uuid4()}.pdf"
        with open(output_path, "wb") as f:
            writer.write(f)
            
        background_tasks.add_task(remove_file, output_path)
        return FileResponse(output_path, filename="split_page_1.pdf")
    except Exception as e:
        logger.error(f"Split error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/convert-office")
async def convert_office(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    # Sanitize filename to avoid shell issues
    safe_filename = "".join([c for c in file.filename if c.isalnum() or c in "._-"])
    input_path = f"input_{unique_id}_{safe_filename}"
    output_dir = f"out_{unique_id}"
    os.makedirs(output_dir, exist_ok=True)

    try:
        content = await file.read()
        with open(input_path, "wb") as f:
            f.write(content)

        logger.info(f"Starting LibreOffice conversion for {input_path}")
        
        # Verify LibreOffice exists in the environment
        if not shutil.which('libreoffice'):
            raise Exception("LibreOffice is not installed in the system path.")

        result = subprocess.run([
            'libreoffice', '--headless', '--convert-to', 'pdf', 
            '--outdir', output_dir, input_path
        ], capture_output=True, text=True, check=True)
        
        logger.info(f"LibreOffice Output: {result.stdout}")

        base_name = os.path.splitext(safe_filename)[0]
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        
        if not os.path.exists(pdf_path):
            # Sometimes LibreOffice names files differently if there are spaces
            generated_files = os.listdir(output_dir)
            if generated_files:
                pdf_path = os.path.join(output_dir, generated_files[0])
            else:
                raise Exception("PDF was not generated by LibreOffice.")

        background_tasks.add_task(remove_file, input_path)
        background_tasks.add_task(remove_file, output_dir)

        return FileResponse(pdf_path, filename=f"{base_name}.pdf")
    except subprocess.CalledProcessError as e:
        logger.error(f"LibreOffice failed: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"LibreOffice error: {e.stderr}")
    except Exception as e:
        logger.error(f"Office conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/html-to-pdf")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    pdf_path = f"html_out_{unique_id}.pdf"
    
    try:
        content = await file.read()
        with open(pdf_path, "wb") as f:
            pisa_status = pisa.CreatePDF(content, dest=f)

        if pisa_status.err:
            raise Exception("PISA HTML conversion failed")

        background_tasks.add_task(remove_file, pdf_path)
        return FileResponse(pdf_path, filename="converted_html.pdf")
    except Exception as e:
        logger.error(f"HTML conversion error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
