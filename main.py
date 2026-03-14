import fitz
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
import subprocess
from typing import List
from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# This function deletes the file after it is sent
def remove_file(path: str):
    if os.path.exists(path):
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            import shutil
            shutil.rmtree(path)

# --- EXISTING: JPG TO PDF ---
@app.post("/convert/jpg-to-pdf")
async def convert_image(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    img_path = f"input_{unique_id}.jpg"
    pdf_path = f"output_{unique_id}.pdf"

    with open(img_path, "wb") as f:
        f.write(await file.read())

    doc = fitz.open() 
    img = fitz.open(img_path)
    rect = img[0].rect
    pdfbytes = img.convert_to_pdf()
    img.close()

    img_pdf = fitz.open("pdf", pdfbytes)
    page = doc.new_page(width=rect.width, height=rect.height)
    page.show_pdf_page(rect, img_pdf, 0)
    doc.save(pdf_path)
    doc.close()

    os.remove(img_path)
    background_tasks.add_task(remove_file, pdf_path)

    return FileResponse(pdf_path, filename="converted.pdf")

# --- EXISTING: MERGE PDF ---
@app.post("/merge-pdf")
async def merge_pdf(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    merger = PdfWriter()
    
    for file in files:
        merger.append(file.file)
    
    output_path = f"merged_{uuid.uuid4()}.pdf"
    
    with open(output_path, "wb") as f:
        merger.write(f)
    merger.close()
    
    background_tasks.add_task(remove_file, output_path)
    return FileResponse(output_path, filename="merged_document.pdf")

# --- EXISTING: SPLIT PDF ---
@app.post("/split-pdf")
async def split_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    reader = PdfReader(file.file)
    writer = PdfWriter()
    
    if len(reader.pages) > 0:
        writer.add_page(reader.pages[0])
    
    output_path = f"split_{uuid.uuid4()}.pdf"
    
    with open(output_path, "wb") as f:
        writer.write(f)
        
    background_tasks.add_task(remove_file, output_path)
    return FileResponse(output_path, filename="split_page_1.pdf")

# --- NEW: UNIVERSAL OFFICE TO PDF (Word, Excel, PPT) ---
@app.post("/convert-office")
async def convert_office(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    input_path = f"input_{unique_id}_{file.filename}"
    output_dir = f"out_{unique_id}"
    os.makedirs(output_dir, exist_ok=True)

    with open(input_path, "wb") as f:
        f.write(await file.read())

    try:
        # Executes LibreOffice headless conversion
        subprocess.run([
            'libreoffice', '--headless', '--convert-to', 'pdf', 
            '--outdir', output_dir, input_path
        ], check=True)
        
        base_name = os.path.splitext(file.filename)[0]
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        
        background_tasks.add_task(remove_file, input_path)
        background_tasks.add_task(remove_file, output_dir)

        return FileResponse(pdf_path, filename=f"{base_name}.pdf")
    except Exception as e:
        return {"error": str(e)}

# --- NEW: HTML TO PDF ---
@app.post("/html-to-pdf")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    unique_id = str(uuid.uuid4())
    pdf_path = f"html_out_{unique_id}.pdf"
    
    content = await file.read()
    with open(pdf_path, "wb") as f:
        pisa_status = pisa.CreatePDF(content, dest=f)

    if pisa_status.err:
        return {"error": "HTML conversion failed"}

    background_tasks.add_task(remove_file, pdf_path)
    return FileResponse(pdf_path, filename="converted_html.pdf")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)