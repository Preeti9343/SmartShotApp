import pytesseract
from PIL import Image
import os
import fitz  # PyMuPDF
from nlp_engine import clean_text

# Windows users ke liye agar path alag ho to uncomment karo
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def extract_text_from_pdf(file_path):
    """
    Detect if PDF has text layer.
    Fast extract if text layer exists, otherwise OCR page by page.
    """
    try:
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            page_text = page.get_text()
            if page_text.strip():  # Fast mode
                text += page_text
            else:  # Scanned PDF, run OCR
                pix = page.get_pixmap()
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text += pytesseract.image_to_string(img)
        return clean_text(text)
    except Exception as e:
        print(f"PDF read error ({file_path}): {e}")
        return ""

def extract_text_from_docx(file_path):
    from docx import Document
    try:
        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
        return clean_text(text)
    except:
        return ""

def extract_text_from_txt(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return clean_text(f.read())
    except:
        return ""

def extract_text_from_folder(folder_path, lang="eng", progress_callback=None):
    """
    Extract text from images + PDF + DOCX + TXT.
    progress_callback(index, total) can be passed to update GUI progress.
    """
    supported_images = (".png", ".jpg", ".jpeg", ".bmp", ".tiff")
    extracted_data = []

    all_files = []
    for root_dir, dirs, files in os.walk(folder_path):
        for file in files:
            all_files.append(os.path.join(root_dir, file))

    total_files = len(all_files)
    for idx, full_path in enumerate(all_files, start=1):
        file = os.path.basename(full_path)
        text = ""
        try:
            if file.lower().endswith(supported_images):
                img = Image.open(full_path)
                text = pytesseract.image_to_string(img, lang=lang)
            elif file.lower().endswith(".pdf"):
                text = extract_text_from_pdf(full_path)
            elif file.lower().endswith(".docx"):
                text = extract_text_from_docx(full_path)
            elif file.lower().endswith(".txt"):
                text = extract_text_from_txt(full_path)

            extracted_data.append({
                "filename": file,
                "path": full_path,
                "text": text.strip()
            })

        except Exception as e:
            print(f"Error processing {file}: {e}")

        # Update GUI progress if callback provided
        if progress_callback:
            progress_callback(idx, total_files)

    print(f"✅ Total files processed: {len(extracted_data)}")
    return extracted_data
