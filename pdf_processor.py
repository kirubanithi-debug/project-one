import os
import logging
import fitz  # PyMuPDF
import pdfplumber
from PIL import Image
import numpy as np

def is_scanned_pdf(file_path):
    """
    Check if a PDF file is scanned or contains selectable text.
    If the total extracted character count is less than 20 characters,
    we classify it as scanned.
    """
    try:
        # Check using PyMuPDF (fast)
        doc = fitz.open(file_path)
        total_text = ""
        # Check first 3 pages (drawings are usually 1 page, but check up to 3)
        for i in range(min(len(doc), 3)):
            total_text += doc[i].get_text()
        
        doc.close()
        
        char_count = len(total_text.strip())
        is_scanned = char_count < 20
        logging.info(f"PDF classification for '{os.path.basename(file_path)}': character count = {char_count}, Scanned = {is_scanned}")
        return is_scanned
    except Exception as e:
        logging.error(f"Error checking if PDF is scanned '{file_path}': {e}")
        return True # Default to scanned (OCR) if check fails

def extract_text_from_pdf(file_path):
    """
    Extracts selectable text from a text-based PDF using PyMuPDF.
    If PyMuPDF returns very little text, tries pdfplumber.
    """
    text_content = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            text_content += page.get_text() + "\n"
        doc.close()
        
        # Fallback to pdfplumber if text is empty or very short
        if len(text_content.strip()) < 20:
            logging.info(f"PyMuPDF extracted minimal text from {os.path.basename(file_path)}. Retrying with pdfplumber.")
            text_content = ""
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_content += page_text + "\n"
                        
        return text_content
    except Exception as e:
        logging.error(f"Error extracting text from PDF '{file_path}': {e}")
        return ""

def pdf_page_to_image(file_path, page_num=0, dpi=300):
    """
    Renders a PDF page to a high-resolution PIL Image for OCR.
    DPI defaults to 300 (zoom factor of 300/72 = 4.16) for high accuracy.
    """
    try:
        doc = fitz.open(file_path)
        if page_num >= len(doc):
            logging.error(f"Page number {page_num} is out of bounds for {file_path}")
            doc.close()
            return None
        
        page = doc[page_num]
        
        # Calculate scale based on desired DPI (default PDF unit size is 72 points/inch)
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        # Convert fitz pixmap to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        
        logging.info(f"Rendered page {page_num} of '{os.path.basename(file_path)}' to {pix.width}x{pix.height} image.")
        return img
    except Exception as e:
        logging.error(f"Error rendering PDF page to image '{file_path}': {e}")
        return None
