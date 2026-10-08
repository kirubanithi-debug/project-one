import os
import json
import logging
from datetime import datetime

# Setup paths and environment
import config
import pdf_processor
import title_block
import ocr_engine
import extractor
import excel_exporter
import logger
import utils

def run_headless_test():
    print("=== STARTING HEADLESS INTEGRATION TEST ===")
    
    # 1. Initialize Logging
    log_file = logger.setup_logging()
    print(f"Logging initialized at: {log_file}")
    
    # 2. Paths
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_drawings")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_output")
    os.makedirs(output_dir, exist_ok=True)
    
    text_pdf_path = os.path.join(test_dir, "drawing_9004_text.pdf")
    scanned_pdf_path = os.path.join(test_dir, "drawing_508_scanned.pdf")
    copy_pdf_path = os.path.join(test_dir, "drawing_9004_text_copy.pdf")
    
    # 3. Test File Hashing and Duplication
    hash_1 = utils.calculate_file_hash(text_pdf_path)
    hash_copy = utils.calculate_file_hash(copy_pdf_path)
    print(f"Original file hash: {hash_1}")
    print(f"Copy file hash:     {hash_copy}")
    if hash_1 == hash_copy:
        print("SUCCESS: File hashes match for duplicates!")
    else:
        print("FAIL: File hashes do not match!")
        
    # 4. Check PDF classification
    is_scanned_text = pdf_processor.is_scanned_pdf(text_pdf_path)
    is_scanned_scanned = pdf_processor.is_scanned_pdf(scanned_pdf_path)
    print(f"Classification for text PDF:    Scanned = {is_scanned_text} (Expected: False)")
    print(f"Classification for scanned PDF: Scanned = {is_scanned_scanned} (Expected: True)")
    
    # 5. Extract Text from Text PDF
    extracted_text = pdf_processor.extract_text_from_pdf(text_pdf_path)
    print("\n--- Extracted Text Content from Text PDF ---")
    print(extracted_text.strip())
    print("-------------------------------------------\n")
    
    # 6. Parse Fields and Validate
    results = []
    
    # Process text drawing
    doc_data = extractor.process_extracted_document(text_pdf_path, extracted_text, hash_1)
    results.append(doc_data)
    
    print("\n--- Extracted Fields & Validation Status ---")
    print(f"Status: {doc_data['status']}")
    print(f"Drawing No:  {doc_data['drawing_number']} (Valid: {doc_data['_validation']['drawing_number']['is_valid']})")
    print(f"Title:       {doc_data['drawing_title']} (Valid: {doc_data['_validation']['drawing_title']['is_valid']})")
    print(f"Revision:    {doc_data['revision']} (Valid: {doc_data['_validation']['revision']['is_valid']})")
    print(f"Weight:      {doc_data['weight']} (Valid: {doc_data['_validation']['weight']['is_valid']})")
    print(f"Quantity:    {doc_data['quantity']} (Valid: {doc_data['_validation']['quantity']['is_valid']})")
    print(f"Sheet No:    {doc_data['sheet_number']} (Valid: {doc_data['_validation']['sheet_number']['is_valid']})")
    print(f"Total Sheets: {doc_data['total_sheets']} (Valid: {doc_data['_validation']['total_sheets']['is_valid']})")
    print(f"Project:     {doc_data['project_name']} (Valid: {doc_data['_validation']['project_name']['is_valid']})")
    print(f"Client:      {doc_data['client_name']} (Valid: {doc_data['_validation']['client_name']['is_valid']})")
    print(f"Date:        {doc_data['date']} (Valid: {doc_data['_validation']['date']['is_valid']})")
    print(f"Scale:       {doc_data['scale']} (Valid: {doc_data['_validation']['scale']['is_valid']})")
    print(f"Drawn By:    {doc_data['drawn_by']} (Valid: {doc_data['_validation']['drawn_by']['is_valid']})")
    print(f"Checked By:  {doc_data['checked_by']} (Valid: {doc_data['_validation']['checked_by']['is_valid']})")
    print(f"Approved By: {doc_data['approved_by']} (Valid: {doc_data['_validation']['approved_by']['is_valid']})")
    
    # 7. Excel Export
    print("\nTesting Excel Export...")
    excel_path = excel_exporter.export_data_to_excel(results, output_dir)
    print(f"SUCCESS: Excel output generated at: {excel_path}")
    
    # 8. Check Tesseract availability
    tess_available = ocr_engine.is_ocr_available()
    print(f"\nTesseract OCR Available: {tess_available}")
    if tess_available:
        print("Tesseract is available! Testing scanned image OCR...")
        scanned_img = pdf_processor.pdf_page_to_image(scanned_pdf_path, 0)
        cv_img = title_block.pil_to_cv(scanned_img)
        cropped, _ = title_block.crop_title_block_default(cv_img)
        enhanced = title_block.preprocess_image_for_ocr(cropped)
        enhanced_pil = title_block.cv_to_pil(enhanced)
        ocr_text = ocr_engine.run_ocr(enhanced_pil)
        
        print("\n--- Extracted OCR Text Content ---")
        print(ocr_text.strip())
        print("----------------------------------\n")
        
        scanned_data = extractor.process_extracted_document(scanned_pdf_path, ocr_text, hash_copy)
        print(f"Scanned Status: {scanned_data['status']}")
        print(f"Drawing No (Scanned): {scanned_data['drawing_number']}")
        results.append(scanned_data)
        excel_path = excel_exporter.export_data_to_excel(results, output_dir)
        print(f"SUCCESS: Updated Excel with scanned PDF data at: {excel_path}")
    else:
        print("Tesseract not available. Skipping scanned drawing OCR test.")
        
    print("\n=== HEADLESS INTEGRATION TEST COMPLETE ===")

if __name__ == "__main__":
    run_headless_test()
