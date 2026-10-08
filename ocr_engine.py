import os
import pytesseract
import logging
from PIL import Image
import config

def is_ocr_available():
    """
    Check if Tesseract OCR is installed and the executable path is correct.
    """
    tess_path = config.detect_tesseract_path()
    if tess_path and os.path.exists(tess_path):
        # Update config dynamically in case it was installed after startup
        config.TESSERACT_CMD = tess_path
        pytesseract.pytesseract.tesseract_cmd = tess_path
        return True
    return False

def run_ocr(pil_image):
    """
    Runs Tesseract OCR on a preprocessed PIL image.
    Uses custom configuration parameters optimal for technical document title blocks.
    Tries PSM 6 (uniform block of text) for tabular title blocks, falling back to PSM 3.
    """
    if not is_ocr_available():
        err_msg = "Tesseract OCR is not installed or not found. Please install it to scan scanned PDFs."
        logging.error(err_msg)
        raise FileNotFoundError(err_msg)

    try:
        # Try PSM 6 first (Assumes a single uniform block of text - optimal for tables/title blocks)
        config_psm6 = r'--oem 3 --psm 6'
        text_psm6 = pytesseract.image_to_string(pil_image, config=config_psm6)
        
        # If PSM 6 yielded reasonable text, return it
        if len(text_psm6.strip()) > 30:
            logging.info("Tesseract OCR (PSM 6) completed successfully.")
            return text_psm6
            
        # Fallback to PSM 3 (Fully automatic page segmentation)
        config_psm3 = r'--oem 3 --psm 3'
        text_psm3 = pytesseract.image_to_string(pil_image, config=config_psm3)
        logging.info("Tesseract OCR (PSM 3 fallback) completed successfully.")
        return text_psm3 if len(text_psm3.strip()) > len(text_psm6.strip()) else text_psm6
        
    except Exception as e:
        logging.error(f"Error during Tesseract OCR: {e}")
        raise e

