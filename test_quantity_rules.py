import unittest
import extractor
import config
import ui_manager

class TestQuantityRules(unittest.TestCase):
    def test_assembly_weight_not_extracted_as_quantity(self):
        text_sht_04 = """
        PROJECT: AMARAVATI STATE SECRETARIAT & HEADS OF DEPARTMENT
        CLIENT: Andhra Pradesh Capital Region Development Authority
        DRG NO: BISPL-TCM-STR-FD-T5-L07-DC1003
        TITLE: DIAGRID COLUMN
        REV: 00
        SHT-04 OF 04
        TOTAL WT. FOR 1 ASSEMBLY : 18888.0 kg
        """
        extracted = extractor.extract_fields_from_text(text_sht_04)
        self.assertEqual(extracted.get("weight"), "18888.0")
        self.assertEqual(extracted.get("quantity", ""), "", "Quantity on Sheet 04 should be empty, not 1 from '1 ASSEMBLY'")

    def test_bom_sheet_extracts_true_quantity(self):
        text_sht_03 = """
        PROJECT: AMARAVATI STATE SECRETARIAT & HEADS OF DEPARTMENT
        DRG NO: BISPL-TCM-STR-FD-T5-L07-DC1003
        TITLE: DIAGRID COLUMN
        REV: 00
        SHT-03 OF 04
        8 QTY COLUMN REQUIRED
        """
        extracted = extractor.extract_fields_from_text(text_sht_03)
        self.assertEqual(extracted.get("quantity"), "8")

    def test_bom_sheet_dc1005_extracts_true_quantity(self):
        text_sht_03 = """
        PROJECT: AMARAVATI STATE SECRETARIAT & HEADS OF DEPARTMENT
        DRG NO: BISPL-TCM-STR-FD-T5-L07-DC1005
        TITLE: DIAGRID COLUMN
        REV: 00
        SHT-03 OF 05
        4 QTY DC1005 REQUIRED
        """
        extracted = extractor.extract_fields_from_text(text_sht_03)
        self.assertEqual(extracted.get("quantity"), "4")

    def test_multi_sheet_post_process_cleanup(self):
        class MockApp:
            def __init__(self):
                self.all_data = [
                    {"file_name": "DC1003 SHT-01 OF 04.pdf", "drawing_number": "DC1003", "sheet_number": "1", "total_sheets": "4", "quantity": "", "weight": ""},
                    {"file_name": "DC1003 SHT-02 OF 04.pdf", "drawing_number": "DC1003", "sheet_number": "2", "total_sheets": "4", "quantity": "", "weight": ""},
                    {"file_name": "DC1003 SHT-03 OF 04.pdf", "drawing_number": "DC1003", "sheet_number": "3", "total_sheets": "4", "quantity": "8", "weight": ""},
                    {"file_name": "DC1003 SHT-04 OF 04.pdf", "drawing_number": "DC1003", "sheet_number": "4", "total_sheets": "4", "quantity": "1", "weight": "18888.0"},
                    {"file_name": "DC1005 SHT-01 OF 05.pdf", "drawing_number": "DC1005", "sheet_number": "1", "total_sheets": "5", "quantity": "", "weight": ""},
                    {"file_name": "DC1005 SHT-02 OF 05.pdf", "drawing_number": "DC1005", "sheet_number": "2", "total_sheets": "5", "quantity": "", "weight": ""},
                    {"file_name": "DC1005 SHT-03 OF 05.pdf", "drawing_number": "DC1005", "sheet_number": "3", "total_sheets": "5", "quantity": "4", "weight": ""},
                    {"file_name": "DC1005 SHT-04 OF 05.pdf", "drawing_number": "DC1005", "sheet_number": "4", "total_sheets": "5", "quantity": "1", "weight": "25175.5"},
                    {"file_name": "DC1005 SHT-05 OF 05.pdf", "drawing_number": "DC1005", "sheet_number": "5", "total_sheets": "5", "quantity": "", "weight": ""}
                ]

        app = MockApp()
        ui_manager.DrawingExtractorApp.post_process_data(app)

        qtys = [r["quantity"] for r in app.all_data]
        self.assertEqual(qtys, ["", "", "8", "", "", "", "4", "", ""])
        non_empty = [q for q in qtys if q]
        self.assertEqual(len(non_empty), 2, "There should be exactly 2 quantities in the batch (8 and 4)!")

if __name__ == "__main__":
    unittest.main()
