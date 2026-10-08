import os
import extractor
import pdf_processor
import title_block
import ocr_engine

def test_drawings():
    folder = r"C:\Users\ISDD\OneDrive - Vijendrakumar\GAD TCM PROJECT\SHIPMENT\FAB DRAWINGS\BISPL-NCC-TCM-FD-TR-133 FAB DRAWINGS\DRAWING\PDF"
    if not os.path.exists(folder):
        print(f"Folder does not exist: {folder}")
        return
        
    files = [f for f in os.listdir(folder) if f.endswith(".pdf")]
    print(f"Found {len(files)} PDF files.")
    
    for filename in sorted(files):
        path = os.path.join(folder, filename)
        is_scanned = pdf_processor.is_scanned_pdf(path)
        text = pdf_processor.extract_text_from_pdf(path)
        
        # Calculate fake hash
        fake_hash = "hash_" + filename
        data = extractor.process_extracted_document(path, text, fake_hash)
        
        print(f"File: {filename}")
        print(f"  Dwg No:   '{data.get('drawing_number')}'")
        print(f"  Title:    '{data.get('drawing_title')}'")
        print(f"  Rev:      '{data.get('revision')}'")
        print(f"  Qty:      '{data.get('quantity')}'")
        print(f"  Sheet:    '{data.get('sheet_number')}'")
        print(f"  Total Sh: '{data.get('total_sheets')}'")
        print("-" * 50)

if __name__ == "__main__":
    test_drawings()
