import os
import io
import fitz # PyMuPDF
from PIL import Image, ImageDraw

def create_text_pdf(output_path):
    doc = fitz.open()
    page = doc.new_page(width=842, height=595) # A4 Landscape (in points)
    
    # Draw title block outer frame
    page.draw_rect(fitz.Rect(540, 440, 832, 585), color=(0, 0, 0), width=1.5)
    page.draw_line(fitz.Point(540, 480), fitz.Point(832, 480), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(540, 520), fitz.Point(832, 520), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(686, 480), fitz.Point(686, 585), color=(0, 0, 0), width=1)
    
    # Text annotations in the title block
    page.insert_text((550, 455), "PROJECT: STADIUM ROOF STRUCTURE", fontsize=8)
    page.insert_text((550, 470), "CLIENT: URBAN SPORTS DEVELOPMENT", fontsize=8)
    
    page.insert_text((550, 495), "DRG NO: STD-RF-9004-C", fontsize=9)
    page.insert_text((550, 510), "TITLE: STEEL TRUSS NODES", fontsize=9)
    
    page.insert_text((550, 535), "REV: C", fontsize=8)
    page.insert_text((550, 550), "SCALE: 1:10", fontsize=8)
    page.insert_text((550, 565), "SHEET NO: 3", fontsize=8)
    
    page.insert_text((696, 495), "WT: 850.5 kg", fontsize=8)
    page.insert_text((696, 510), "QTY: 12", fontsize=8)
    
    page.insert_text((696, 535), "OF 6 SHEETS", fontsize=8)
    page.insert_text((696, 550), "DRAWN BY: E.W.", fontsize=7)
    page.insert_text((696, 562), "CHECKED BY: R.J.", fontsize=7)
    page.insert_text((696, 574), "APPROVED BY: T.S.", fontsize=7)
    
    page.insert_text((550, 580), "DATE: 15-06-2026", fontsize=7)
    
    doc.save(output_path)
    doc.close()
    print(f"Created text-based PDF: {output_path}")

def create_scanned_pdf(output_path):
    # Render drawing onto image (representing scanned paper drawing)
    img_w, img_h = 1684, 1190 # High resolution A4 Landscape
    img = Image.new("RGB", (img_w, img_h), "#ffffff")
    draw = ImageDraw.Draw(img)
    
    # Draw drawing frame border
    draw.rectangle([(20, 20), (img_w - 20, img_h - 20)], outline="#000000", width=4)
    
    # Title Block box in bottom right (A4 width 1684, height 1190)
    tb_w = 584
    tb_h = 290
    tb_x = img_w - 20 - tb_w
    tb_y = img_h - 20 - tb_h
    
    draw.rectangle([(tb_x, tb_y), (img_w - 20, img_h - 20)], outline="#000000", width=3)
    
    # Lines inside title block
    draw.line([(tb_x, tb_y + 80), (img_w - 20, tb_y + 80)], fill="#000000", width=2)
    draw.line([(tb_x, tb_y + 160), (img_w - 20, tb_y + 160)], fill="#000000", width=2)
    draw.line([(tb_x + 300, tb_y + 80), (tb_x + 300, img_h - 20)], fill="#000000", width=2)
    
    # We will draw standard textual details into the title block using drawing operations
    # To keep it portable and avoid font errors, we will just use default PIL rendering
    draw.text((tb_x + 20, tb_y + 20), "PROJECT: WATER PURIFICATION PLANT", fill="#000000")
    draw.text((tb_x + 20, tb_y + 45), "CLIENT: MUNICIPAL WATER UTILITIES", fill="#000000")
    
    draw.text((tb_x + 20, tb_y + 95), "DRG NO: WPP-PIPE-508-0", fill="#000000")
    draw.text((tb_x + 20, tb_y + 125), "TITLE: INLET MANIFOLD DETAIL", fill="#000000")
    
    draw.text((tb_x + 20, tb_y + 175), "REV: 0", fill="#000000")
    draw.text((tb_x + 20, tb_y + 205), "SCALE: 1:25", fill="#000000")
    draw.text((tb_x + 20, tb_y + 235), "SHEET NO: 1", fill="#000000")
    
    draw.text((tb_x + 320, tb_y + 95), "WT: 345 kg", fill="#000000")
    draw.text((tb_x + 320, tb_y + 125), "QTY: 3", fill="#000000")
    
    draw.text((tb_x + 320, tb_y + 175), "OF 4 SHEETS", fill="#000000")
    draw.text((tb_x + 320, tb_y + 205), "DRAWN BY: D.K.", fill="#000000")
    draw.text((tb_x + 320, tb_y + 225), "CHECKED BY: A.S.", fill="#000000")
    draw.text((tb_x + 320, tb_y + 245), "APPROVED BY: M.N.", fill="#000000")
    
    draw.text((tb_x + 20, tb_y + 265), "DATE: 20-07-2026", fill="#000000")
    
    # Save PIL image to PDF using PyMuPDF (saves PDF with drawing embedded as image)
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=95)
    img_bytes = img_byte_arr.getvalue()
    
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_image(fitz.Rect(0, 0, 842, 595), stream=img_bytes)
    doc.save(output_path)
    doc.close()
    print(f"Created scanned (image-only) PDF: {output_path}")

def main():
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_drawings")
    os.makedirs(test_dir, exist_ok=True)
    
    create_text_pdf(os.path.join(test_dir, "drawing_9004_text.pdf"))
    create_scanned_pdf(os.path.join(test_dir, "drawing_508_scanned.pdf"))
    
    # Create a duplicate to test deduplication
    import shutil
    shutil.copy2(
        os.path.join(test_dir, "drawing_9004_text.pdf"),
        os.path.join(test_dir, "drawing_9004_text_copy.pdf")
    )
    print("Created duplicate PDF file for deduplication testing.")

if __name__ == "__main__":
    main()
