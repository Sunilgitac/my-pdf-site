import fitz
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid

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

    # 1. Delete the input image immediately
    os.remove(img_path)

    # 2. Tell the server to delete the PDF ONLY AFTER the user downloads it
    background_tasks.add_task(remove_file, pdf_path)

    return FileResponse(pdf_path, filename="converted.pdf")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)