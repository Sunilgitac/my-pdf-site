import fitz
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
from typing import List
from pypdf import PdfReader, PdfWriter

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
        os.remove(path)

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

# --- NEW: MERGE PDF ---
@app.post("/merge-pdf")
async def merge_pdf(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    merger = PdfWriter()
    
    for file in files:
        # pypdf can read the file stream directly
        merger.append(file.file)
    
    output_path = f"merged_{uuid.uuid4()}.pdf"
    
    with open(output_path, "wb") as f:
        merger.write(f)
    merger.close()
    
    background_tasks.add_task(remove_file, output_path)
    return FileResponse(output_path, filename="merged_document.pdf")

# --- NEW: SPLIT PDF (Extracts Page 1) ---
@app.post("/split-pdf")
async def split_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    reader = PdfReader(file.file)
    writer = PdfWriter()
    
    # Adding the first page as a starting feature
    if len(reader.pages) > 0:
        writer.add_page(reader.pages[0])
    
    output_path = f"split_{uuid.uuid4()}.pdf"
    
    with open(output_path, "wb") as f:
        writer.write(f)
        
    background_tasks.add_task(remove_file, output_path)
    return FileResponse(output_path, filename="split_page_1.pdf")

if __name__ == "__main__":
    import uvicorn
    # Note: On Railway, the Procfile handles the port, 
    # but this remains for your local testing.
    uvicorn.run(app, host="127.0.0.1", port=8000)