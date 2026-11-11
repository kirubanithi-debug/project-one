import os
import sys
import unittest
import learning_engine
import extractor

class TestMLLearningSystem(unittest.TestCase):
    def setUp(self):
        self.engine = learning_engine.engine

    def test_ml_entity_matching(self):
        # 1. Test Project matching despite OCR typos
        noisy_project = "WATER PURIFIGATION PLANT"
        matched_proj, score = self.engine.match_project_ml(f"PROJECT: {noisy_project}")
        self.assertEqual(matched_proj, "WATER PURIFICATION PLANT")
        self.assertGreaterEqual(score, 0.55)

        # 2. Test Client matching despite severe OCR typos
        noisy_client = "MUNIGIRAL WARTER UTILITIES"
        matched_client, score = self.engine.match_client_ml(f"CLIENT. {noisy_client}")
        self.assertEqual(matched_client, "MUNICIPAL WATER UTILITIES")
        self.assertGreaterEqual(score, 0.55)

    def test_line_disentanglement(self):
        # Test multi-field line concatenation
        compound_text = (
            "DRG NO: WPP-PIPE-508-0 WT: 345 kg\n"
            "REVO) OF 4 SHEETS\n"
            "SCALE 1:25 DRAWN BY: DK"
        )
        disentangled = extractor.disentangle_compound_lines(compound_text)
        lines = [l.strip() for l in disentangled.split("\n") if l.strip()]
        
        # Verify drawing number and weight are separated
        has_dwg = any("DRG NO:" in l for l in lines)
        has_wt = any("WT: 345 kg" in l for l in lines)
        has_rev = any("REVO" in l for l in lines)
        has_sheets = any("OF 4 SHEETS" in l for l in lines)
        has_scale = any("SCALE 1:25" in l for l in lines)
        has_drawn = any("DRAWN BY: DK" in l for l in lines)

        self.assertTrue(has_dwg)
        self.assertTrue(has_wt)
        self.assertTrue(has_rev)
        self.assertTrue(has_sheets)
        self.assertTrue(has_scale)
        self.assertTrue(has_drawn)

    def test_active_learning_from_user_edit(self):
        raw_ocr_sample = (
            "PROJECT: STADIUM ROOF\n"
            "DRG NO: STD-RF-9999-D\n"
            "DRAW BY: ALEX.M\n"
            "SHEET NG 5"
        )
        # Simulate user manual edit: User corrects drawn_by to 'ALEX.M'
        insights = self.engine.learn_manual_edit("test_dwg.pdf", "drawn_by", "ALEX.M", raw_ocr_sample)
        
        # Verify that DRAW BY was discovered and learned as an anchor
        aliases = self.engine.memory.get("learned_label_aliases", {}).get("drawn_by", [])
        self.assertIn("DRAW BY", aliases)

        # Verify that ALEX.M was added to known personnel
        personnel = self.engine.memory.get("known_personnel", [])
        self.assertIn("ALEX.M", personnel)

    def test_drawing_prefix_mining(self):
        # Simulate user editing drawing number
        self.engine.learn_manual_edit("bridge_01.pdf", "drawing_number", "BRG-SPAN-2026-X1")
        prefixes = self.engine.memory.get("drawing_prefixes", [])
        self.assertIn("BRG-SPAN", prefixes)

if __name__ == "__main__":
    unittest.main()
