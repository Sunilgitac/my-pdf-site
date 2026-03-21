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

# --- Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pdf-suite")

def get_lo_binary():
    paths = ["/usr/bin/soffice", "/usr/bin/libreoffice"]
    for path in paths:
        if os.path.exists(path): return path
    return shutil.which("soffice")

LO_BINARY = get_lo_binary()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def cleanup(path: str):
    if os.path.exists(path):
        if os.path.isfile(path): os.remove(path)
        else: shutil.rmtree(path, ignore_errors=True)


# --- UPDATED: PDF TO OFFICE CONVERSION LOGIC ---

async def pdf_to_office_logic(file: UploadFile, target_ext: str, background_tasks: BackgroundTasks):
    uid = str(uuid.uuid4())
    in_path = f"in_{uid}.pdf"
    out_dir = f"out_{uid}"
    os.makedirs(out_dir, exist_ok=True)
    
    # Write the uploaded PDF to disk
    with open(in_path, "wb") as f:
        f.write(await file.read())
    
    # Mapping extensions to specific LibreOffice Export Filters
    # This prevents the "no export filter" error
    filters = {
        "docx": "MS Word 2007 XML",
        "xlsx": "Calc MS Excel 2007 XML",
        "pptx": "Impress MS PowerPoint 2007 XML"
    }
    
    filter_name = filters.get(target_ext)
    
    try:
        # 1. We force '--infilter=writer_pdf_import' so it treats the PDF as text
        # 2. We use 'extension:filter_name' to specify the exact output format
        cmd = [
            LO_BINARY,
            "--headless",
            "--infilter=writer_pdf_import", 
            "--convert-to", f"{target_ext}:{filter_name}",
            "--outdir", out_dir,
            in_path
        ]
        
        logger.info(f"Executing: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"LibreOffice Error: {result.stderr}")
            raise Exception(f"LibreOffice failed: {result.stderr}")

        # Locate the resulting file in the output directory
        generated_files = os.listdir(out_dir)
        if not generated_files:
            raise Exception("LibreOffice did not produce an output file.")
            
        out_path = os.path.join(out_dir, generated_files[0])
        
        # Schedule cleanup
        background_tasks.add_task(cleanup, in_path)
        background_tasks.add_task(cleanup, out_dir)
        
        return FileResponse(
            out_path, 
            filename=f"converted_{uid}.{target_ext}",
            media_type="application/octet-stream"
        )
        
    except Exception as e:
        logger.error(f"Conversion failed: {str(e)}")
        cleanup(in_path)
        cleanup(out_dir)
        raise HTTPException(status_code=500, detail=f"Internal Conversion Error: {str(e)}")

# --- ROUTES ---

@app.post("/pdf-to-word")
async def pdf_to_word(bt: BackgroundTasks, file: UploadFile = File(...)):
    return await pdf_to_office_logic(file, "docx", bt)

@app.post("/pdf-to-excel")
async def pdf_to_excel(bt: BackgroundTasks, file: UploadFile = File(...)):
    return await pdf_to_office_logic(file, "xlsx", bt)

@app.post("/pdf-to-ppt")
async def pdf_to_ppt(bt: BackgroundTasks, file: UploadFile = File(...)):
    return await pdf_to_office_logic(file, "pptx", bt)


@app.post("/pdf-to-jpg")
async def pdf_to_jpg(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    in_path = f"temp_{uid}.pdf"
    out_path = f"img_{uid}.jpg"
    with open(in_path, "wb") as f: f.write(await file.read())
    try:
        doc = fitz.open(in_path)
        page = doc.load_page(0) # Convert first page
        pix = page.get_pixmap()
        pix.save(out_path)
        doc.close()
        background_tasks.add_task(cleanup, in_path)
        background_tasks.add_task(cleanup, out_path)
        return FileResponse(out_path, media_type="image/jpeg")
    except Exception as e:
        cleanup(in_path)
        raise HTTPException(status_code=500, detail=str(e))

# --- REMAINING EXISTING CODE (Unchanged) ---
@app.post("/merge-pdf")
async def merge_pdf(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    merger = PdfWriter()
    for file in files: merger.append(file.file)
    out_path = f"merged_{uuid.uuid4()}.pdf"
    with open(out_path, "wb") as f: merger.write(f)
    merger.close()
    background_tasks.add_task(cleanup, out_path)
    return FileResponse(out_path)

@app.post("/convert/office-to-pdf")
async def office_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    in_path = f"off_{uid}_{file.filename}"
    out_dir = f"out_off_{uid}"
    os.makedirs(out_dir, exist_ok=True)
    with open(in_path, "wb") as f: f.write(await file.read())
    subprocess.run([LO_BINARY, "--headless", "--convert-to", "pdf", "--outdir", out_dir, in_path])
    res = os.path.join(out_dir, os.listdir(out_dir)[0])
    background_tasks.add_task(cleanup, in_path); background_tasks.add_task(cleanup, out_dir)
    return FileResponse(res)

@app.post("/convert/jpg-to-pdf")
async def jpg_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    uid = str(uuid.uuid4())
    img_path = f"img_{uid}.jpg"
    pdf_path = f"pdf_{uid}.pdf"
    with open(img_path, "wb") as f: f.write(await file.read())
    doc = fitz.open(); img = fitz.open(img_path)
    pdfbytes = img.convert_to_pdf()
    img.close(); img_pdf = fitz.open("pdf", pdfbytes)
    page = doc.new_page(width=img_pdf[0].rect.width, height=img_pdf[0].rect.height)
    page.show_pdf_page(img_pdf[0].rect, img_pdf, 0)
    doc.save(pdf_path); doc.close(); img_pdf.close()
    background_tasks.add_task(cleanup, img_path); background_tasks.add_task(cleanup, pdf_path)
    return FileResponse(pdf_path)