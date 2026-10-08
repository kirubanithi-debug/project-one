import os
import extractor
import pdf_processor
import ui_manager

class MockApp:
    def __init__(self):
        self.all_data = []

    def post_process_data(self):
        ui_manager.DrawingExtractorApp.post_process_data(self)

def test():
    folder = r"C:\Users\ISDD\OneDrive - Vijendrakumar\GAD TCM PROJECT\SHIPMENT\FAB DRAWINGS\BISPL-NCC-TCM-FD-TR-133 FAB DRAWINGS\DRAWING\PDF"
    if not os.path.exists(folder):
        print("Folder does not exist.")
        return
        
    app = MockApp()
    files = [f for f in os.listdir(folder) if f.endswith(".pdf")]
    for filename in sorted(files):
        path = os.path.join(folder, filename)
        text = pdf_processor.extract_text_from_pdf(path)
        data = extractor.process_extracted_document(path, text, "hash_" + filename)
        app.all_data.append(data)
        
    print("Running post-processing...")
    app.post_process_data()
    print("Post-processing complete!")
    for idx, row in enumerate(app.all_data):
        print(f"Row {idx+1}: {row['file_name']}")
        print(f"  Dwg No: '{row.get('drawing_number')}'")
        print(f"  Title:  '{row.get('drawing_title')}'")
        print(f"  Qty:    '{row.get('quantity')}'")
        print(f"  Sheet:  '{row.get('sheet_number')}'")
        print(f"  Status: '{row.get('status')}'")

if __name__ == "__main__":
    test()
