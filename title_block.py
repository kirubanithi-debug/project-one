import cv2
import numpy as np
from PIL import Image
import logging

def pil_to_cv(pil_img):
    """Convert PIL Image to OpenCV BGR image"""
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

def cv_to_pil(cv_img):
    """Convert OpenCV image (BGR or Gray) to PIL Image"""
    if len(cv_img.shape) == 2: # Grayscale
        return Image.fromarray(cv_img)
    else: # BGR
        return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))

def preprocess_image_for_ocr(cv_img):
    """
    Applies image processing steps to optimize OCR accuracy:
    - Grayscale conversion
    - Noise removal (Bilateral filter to preserve text edges)
    - Contrast enhancement (CLAHE: Contrast Limited Adaptive Histogram Equalization)
    - Thresholding (Adaptive threshold to create sharp black-and-white text)
    """
    try:
        # 1. Convert to grayscale if it isn't already
        if len(cv_img.shape) == 3:
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = cv_img.copy()

        # 2. Denoise using bilateral filter (removes noise but keeps text boundaries sharp)
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        # 3. Enhance Contrast using CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        contrast_enhanced = clahe.apply(denoised)

        # 4. Adaptive Thresholding to separate text from background
        # Using ADAPTIVE_THRESH_GAUSSIAN_C for smoother thresholds
        binary = cv2.adaptiveThreshold(
            contrast_enhanced, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 15, 8
        )

        return binary
    except Exception as e:
        logging.error(f"Error preprocessing image for OCR: {e}")
        # If preprocessing fails, return the simple grayscale conversion
        if len(cv_img.shape) == 3:
            return cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        return cv_img

def crop_title_block_default(cv_img, height_pct=0.25, width_pct=0.35):
    """
    Crops the standard title block region: bottom-right corner.
    height_pct: percentage of total height from the bottom (e.g. 25%)
    width_pct: percentage of total width from the right (e.g. 35%)
    """
    h, w = cv_img.shape[:2]
    start_y = int(h * (1 - height_pct))
    start_x = int(w * (1 - width_pct))
    
    cropped = cv_img[start_y:h, start_x:w]
    logging.info(f"Default cropped bottom-right title block: size {cropped.shape[1]}x{cropped.shape[0]}")
    return cropped, (start_x, start_y, w, h)

def detect_and_crop_title_block_auto(cv_img):
    """
    Automatically detects the title block rectangle using OpenCV contours.
    Looks for large rectangular shapes near the bottom/right borders.
    Falls back to crop_title_block_default if no valid block is found.
    """
    try:
        h, w = cv_img.shape[:2]
        # 1. Get binary image
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY) if len(cv_img.shape) == 3 else cv_img.copy()
        
        # Blur and threshold to find major borders
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 50, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # 2. Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        candidates = []
        page_area = h * w
        
        for cnt in contours:
            # Approximate contour to find geometric properties
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            
            x, y, rect_w, rect_h = cv2.boundingRect(cnt)
            area = rect_w * rect_h
            
            # Title block heuristics:
            # - Area must be between 1% and 18% of the total page area
            # - Bounding box must be in the lower half or right half of the page
            # - Width is typically greater than height (aspect ratio > 1.2)
            if 0.01 * page_area < area < 0.18 * page_area:
                is_bottom = y + rect_h > h * 0.5
                is_right = x + rect_w > w * 0.5
                aspect_ratio = float(rect_w) / rect_h
                
                if (is_bottom or is_right) and aspect_ratio > 1.1:
                    candidates.append({
                        "contour": cnt,
                        "bbox": (x, y, x + rect_w, y + rect_h),
                        "area": area,
                        "distance_to_corner": (w - (x + rect_w)) + (h - (y + rect_h)) # Lower is closer to bottom-right
                    })
        
        if candidates:
            # Sort candidates: prioritize those closest to bottom-right corner and then by size
            candidates.sort(key=lambda c: (c["distance_to_corner"], -c["area"]))
            best = candidates[0]
            x1, y1, x2, y2 = best["bbox"]
            
            # Buffer the crop slightly (5% margin) to avoid cutting off text borders
            margin_x = int((x2 - x1) * 0.03)
            margin_y = int((y2 - y1) * 0.03)
            crop_x1 = max(0, x1 - margin_x)
            crop_y1 = max(0, y1 - margin_y)
            crop_x2 = min(w, x2 + margin_x)
            crop_y2 = min(h, y2 + margin_y)
            
            cropped = cv_img[crop_y1:crop_y2, crop_x1:crop_x2]
            logging.info(f"Auto-detected title block at bbox [{crop_x1}, {crop_y1}, {crop_x2}, {crop_y2}], size {cropped.shape[1]}x{cropped.shape[0]}")
            return cropped, (crop_x1, crop_y1, crop_x2, crop_y2)
            
    except Exception as e:
        logging.error(f"Error in auto title block detection: {e}. Falling back to default crop.")
    
    # Fallback to standard bottom-right crop if detection fails or finds no candidates
    return crop_title_block_default(cv_img)
