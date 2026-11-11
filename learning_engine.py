import os
import json
import re
import logging
from datetime import datetime

# Machine Learning & NLP imports with graceful fallbacks
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned_memory.json")

class LearningEngine:
    def __init__(self, memory_file=MEMORY_FILE):
        self.memory_file = memory_file
        self.memory = self.load_memory()

    def default_structure(self):
        return {
            "drawing_prefixes": [
                "BISPL-TCM-STR-FD-T5",
                "STD-RF",
                "WPP-PIPE",
                "WEPP-PIPE"
            ],
            "known_projects": [
                "AMARAVATI STATE SECRETARIAT & HEADS OF DEPARTMENT OFFICE BUILDINGS (TOWER TCM) AMARAVATI, ANDHRA PRADESH, INDIA",
                "STADIUM ROOF STRUCTURE",
                "WATER PURIFICATION PLANT"
            ],
            "known_clients": [
                "Andhra Pradesh Capital Region Development Authority",
                "URBAN SPORTS DEVELOPMENT",
                "MUNICIPAL WATER UTILITIES"
            ],
            "known_personnel": [
                "E.W.", "R.J.", "T.S.", "D.K.", "A.S.", "M.M.", "DK", "AS", "MM"
            ],
            "learned_label_aliases": {
                "revision": ["REVO", "REV 0", "REV.", "REV NO", "REVISION"],
                "sheet_number": ["SHEET NC", "SHEET NG", "SHT NO", "SH NO", "SHEET NO", "SHT"],
                "total_sheets": ["OF \\d+ SHEETS", "TOTAL SHEETS", "OF \\d+"],
                "drawn_by": ["DRAW BY", "DRAWN BY", "DRN", "DRWN", "DES BY"],
                "checked_by": ["CHECK BY", "CHECKED BY", "CHKD", "CHK"],
                "approved_by": ["APP BY", "APPROVED BY", "APPD", "APP"],
                "weight": ["WT.", "TOTAL WT.", "WEIGHT", "KA", "MASS"]
            },
            "ocr_typo_corrections": {
                "MUNIGIRAL": "MUNICIPAL",
                "WARTER": "WATER",
                "PURIFIGATION": "PURIFICATION",
                "KA": "KG"
            },
            "manual_corrections": {},
            "pattern_weights": {},
            "total_extractions_learned": 0,
            "last_updated": ""
        }

    def load_memory(self):
        default = self.default_structure()
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge default keys if missing
                    for k, v in default.items():
                        if k not in data:
                            data[k] = v
                    return data
            except Exception as e:
                logging.error(f"Error loading learned memory file: {e}")
        return default

    def save_memory(self):
        try:
            self.memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2, ensure_ascii=False)
            logging.info(
                f"Learned memory saved. Prefixes: {len(self.memory.get('drawing_prefixes', []))}, "
                f"Projects: {len(self.memory.get('known_projects', []))}, "
                f"Clients: {len(self.memory.get('known_clients', []))}, "
                f"Typos: {len(self.memory.get('ocr_typo_corrections', {}))}."
            )
        except Exception as e:
            logging.error(f"Error saving learned memory file: {e}")

    # =========================================================================
    # ML & SIMILARITY MATCHING
    # =========================================================================

    def match_entity_ml(self, query_text, candidate_list, threshold=0.55):
        """
        Uses TF-IDF Character n-gram Vectorization and RapidFuzz Token Set Ratio
        to find the closest known canonical entity (Project, Client, etc.)
        even in the presence of severe OCR typos or character dropping.
        """
        if not candidate_list or not query_text or len(query_text.strip()) < 3:
            return None, 0.0

        clean_query = query_text.strip()
        best_match = None
        best_score = 0.0

        # 1. RapidFuzz Token Set Ratio (fastest and resilient to word permutations)
        if RAPIDFUZZ_AVAILABLE:
            for cand in candidate_list:
                score = fuzz.token_set_ratio(clean_query, cand) / 100.0
                if score > best_score:
                    best_score = score
                    best_match = cand

        # 2. Scikit-learn TF-IDF Char n-gram Cosine Similarity
        if SKLEARN_AVAILABLE and len(candidate_list) > 0:
            try:
                vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
                X = vec.fit_transform(candidate_list + [clean_query])
                sims = cosine_similarity(X[-1:], X[:-1])[0]
                tfidf_idx = int(sims.argmax())
                tfidf_score = float(sims[tfidf_idx])
                
                # Combine scores (giving weight to whichever captured the similarity better)
                if tfidf_score > best_score:
                    best_score = tfidf_score
                    best_match = candidate_list[tfidf_idx]
            except Exception as e:
                logging.debug(f"TF-IDF similarity calculation exception: {e}")

        # Check threshold
        if best_score >= threshold:
            return best_match, best_score
        return None, best_score

    def match_project_ml(self, text):
        """Searches document text for any known project using ML similarity."""
        known = self.memory.get("known_projects", [])
        if not known:
            return None, 0.0

        # Apply typo correction dictionary first
        corr_text = self.apply_typo_corrections(text)

        # Check line by line
        lines = [l.strip() for l in corr_text.split("\n") if len(l.strip()) > 5]
        best_match, max_score = None, 0.0
        for line in lines:
            clean_l = re.sub(r'^(?:PROJECT(?:\s*NAME)?|JOB|WORK)[:\.\s]*', '', line, flags=re.IGNORECASE).strip()
            clean_l = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', clean_l).strip()
            match, score = self.match_entity_ml(clean_l, known, threshold=0.55)
            if score > max_score:
                max_score = score
                best_match = match

        return best_match, max_score

    def match_client_ml(self, text):
        """Searches document text for any known client using ML similarity."""
        known = self.memory.get("known_clients", [])
        if not known:
            return None, 0.0

        corr_text = self.apply_typo_corrections(text)
        lines = [l.strip() for l in corr_text.split("\n") if len(l.strip()) > 4]
        best_match, max_score = None, 0.0
        for line in lines:
            clean_l = re.sub(r'^(?:CLIENT|CUSTOMER|OWNER|EMPLOYER)[:\.\s]*', '', line, flags=re.IGNORECASE).strip()
            clean_l = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', clean_l).strip()
            match, score = self.match_entity_ml(clean_l, known, threshold=0.55)
            if score > max_score:
                max_score = score
                best_match = match

        return best_match, max_score

    def apply_typo_corrections(self, text):
        """Applies learned word-level OCR typo replacements."""
        typos = self.memory.get("ocr_typo_corrections", {})
        if not typos or not text:
            return text
        result = text
        for typo, correct in typos.items():
            if typo and correct and typo != correct:
                result = re.sub(rf'\b{re.escape(typo)}\b', correct, result, flags=re.IGNORECASE)
        return result

    # =========================================================================
    # ACTIVE LEARNING & FEEDBACK
    # =========================================================================

    def learn_from_record(self, doc_data):
        """
        Learns drawing prefixes, projects, clients, and personnel
        automatically from high-confidence extracted document records.
        """
        dwg_num = str(doc_data.get("drawing_number", "")).strip()
        proj = str(doc_data.get("project_name", "")).strip()
        client = str(doc_data.get("client_name", "")).strip()
        drawn = str(doc_data.get("drawn_by", "")).strip()
        chkd = str(doc_data.get("checked_by", "")).strip()
        appd = str(doc_data.get("approved_by", "")).strip()

        changed = False

        # 1. Learn Drawing Number Prefix
        if dwg_num and len(dwg_num) >= 5:
            prefix_match = re.match(r'^([A-Z0-9]{2,8}(?:\s*-\s*[A-Z0-9]{1,8})+?)(?:-\d{3,}|$)', dwg_num)
            if not prefix_match:
                prefix_match = re.match(r'^([A-Z]{2,8}(?:\s*-\s*[A-Z]{2,8})+)', dwg_num)
            if prefix_match:
                prefix = prefix_match.group(1).upper()
                if prefix not in self.memory["drawing_prefixes"] and len(prefix) >= 4:
                    self.memory["drawing_prefixes"].append(prefix)
                    changed = True

        # 2. Learn Known Project (only if not already similar to known project)
        if proj and len(proj) > 5:
            clean_proj = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', proj).strip()
            existing_match, score = self.match_entity_ml(clean_proj, self.memory["known_projects"], threshold=0.80)
            if not existing_match and clean_proj not in self.memory["known_projects"]:
                self.memory["known_projects"].append(clean_proj)
                changed = True

        # 3. Learn Known Client (only if not already similar to known client)
        if client and len(client) > 5:
            clean_client = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', client).strip()
            existing_match, score = self.match_entity_ml(clean_client, self.memory["known_clients"], threshold=0.80)
            if not existing_match and clean_client not in self.memory["known_clients"]:
                self.memory["known_clients"].append(clean_client)
                changed = True

        # 4. Learn Known Personnel
        personnel = self.memory.setdefault("known_personnel", [])
        for person in [drawn, chkd, appd]:
            p_clean = person.strip(" .\t-")
            if p_clean and len(p_clean) <= 6 and p_clean not in personnel:
                personnel.append(p_clean)
                changed = True

        self.memory["total_extractions_learned"] = self.memory.get("total_extractions_learned", 0) + 1
        if changed:
            self.save_memory()

    def learn_manual_edit(self, file_name, col_key, new_val, raw_text=""):
        """
        Learns from a user's manual correction in the UI table.
        Discovers:
        - Label anchors in raw_text preceding the field (e.g. DRAW BY: -> drawn_by).
        - OCR word typos between raw_text and new_val (e.g. MUNIGIRAL -> MUNICIPAL).
        - Canonical projects, clients, prefixes, personnel.
        """
        if not file_name or not col_key:
            return {}

        insights = {
            "file": file_name,
            "field": col_key,
            "value": new_val,
            "learned_patterns": []
        }

        # 1. Save to manual corrections history
        corrections = self.memory.setdefault("manual_corrections", {})
        if file_name not in corrections:
            corrections[file_name] = {}
        corrections[file_name][col_key] = new_val

        # 2. Field-specific ML pattern discovery
        if col_key == "client_name" and new_val and len(new_val) > 4:
            if new_val not in self.memory["known_clients"]:
                self.memory["known_clients"].append(new_val)
                insights["learned_patterns"].append(f"Added client: {new_val}")

            # Check raw text for OCR typos near 'CLIENT'
            if raw_text:
                client_lines = [l for l in raw_text.split("\n") if re.search(r'client|customer|owner', l, re.IGNORECASE)]
                if client_lines:
                    raw_line = client_lines[0]
                    # Find words in raw line not in correct text
                    raw_words = re.findall(r'\b[A-Za-z]{4,}\b', raw_line)
                    correct_words = re.findall(r'\b[A-Za-z]{4,}\b', new_val)
                    for rw in raw_words:
                        if rw.upper() not in ["CLIENT", "CUSTOMER", "OWNER", "NAME"]:
                            # Match against correct words using Rapidfuzz
                            if RAPIDFUZZ_AVAILABLE:
                                for cw in correct_words:
                                    sim = fuzz.ratio(rw.upper(), cw.upper())
                                    if 60 <= sim < 100:
                                        self.memory.setdefault("ocr_typo_corrections", {})[rw.upper()] = cw.upper()
                                        insights["learned_patterns"].append(f"Learned OCR typo: '{rw.upper()}' -> '{cw.upper()}'")

        elif col_key == "project_name" and new_val and len(new_val) > 4:
            if new_val not in self.memory["known_projects"]:
                self.memory["known_projects"].append(new_val)
                insights["learned_patterns"].append(f"Added project: {new_val}")

            if raw_text:
                proj_lines = [l for l in raw_text.split("\n") if re.search(r'project|job|work', l, re.IGNORECASE)]
                if proj_lines:
                    raw_line = proj_lines[0]
                    raw_words = re.findall(r'\b[A-Za-z]{4,}\b', raw_line)
                    correct_words = re.findall(r'\b[A-Za-z]{4,}\b', new_val)
                    for rw in raw_words:
                        if rw.upper() not in ["PROJECT", "NAME", "JOB", "WORK"]:
                            if RAPIDFUZZ_AVAILABLE:
                                for cw in correct_words:
                                    sim = fuzz.ratio(rw.upper(), cw.upper())
                                    if 60 <= sim < 100:
                                        self.memory.setdefault("ocr_typo_corrections", {})[rw.upper()] = cw.upper()
                                        insights["learned_patterns"].append(f"Learned OCR typo: '{rw.upper()}' -> '{cw.upper()}'")

        elif col_key == "drawing_number" and new_val:
            prefix_match = re.match(r'^([A-Z0-9]{2,8}(?:\s*-\s*[A-Z0-9]{1,8})+?)(?:-\d{3,}|$)', new_val)
            if not prefix_match:
                prefix_match = re.match(r'^([A-Z]{2,8}(?:\s*-\s*[A-Z]{2,8})+)', new_val)
            if prefix_match:
                prefix = prefix_match.group(1).upper()
                if prefix not in self.memory["drawing_prefixes"] and len(prefix) >= 4:
                    self.memory["drawing_prefixes"].append(prefix)
                    insights["learned_patterns"].append(f"Added drawing prefix: {prefix}")

        elif col_key in ["drawn_by", "checked_by", "approved_by"] and new_val:
            personnel = self.memory.setdefault("known_personnel", [])
            val_clean = new_val.strip(" .\t-")
            if val_clean and val_clean not in personnel:
                personnel.append(val_clean)
                insights["learned_patterns"].append(f"Added personnel: {val_clean}")

            # Discover label anchor in raw text
            if raw_text:
                for line in raw_text.split("\n"):
                    if re.search(rf'\b{re.escape(val_clean)}\b', line, re.IGNORECASE):
                        anchor_m = re.search(r'([A-Za-z\s]+)[:\.\s]+' + re.escape(val_clean), line, re.IGNORECASE)
                        if anchor_m:
                            label = anchor_m.group(1).strip().upper()
                            aliases = self.memory.setdefault("learned_label_aliases", {}).setdefault(col_key, [])
                            if label and len(label) < 15 and label not in aliases:
                                aliases.append(label)
                                insights["learned_patterns"].append(f"Learned label anchor for {col_key}: '{label}'")

        elif col_key == "sheet_number" and new_val:
            if raw_text:
                sheet_m = re.search(rf'([A-Za-z\s]+)[:\.\s]+{re.escape(str(new_val))}\b', raw_text)
                if sheet_m:
                    label = sheet_m.group(1).strip().upper()
                    aliases = self.memory.setdefault("learned_label_aliases", {}).setdefault("sheet_number", [])
                    if label and "SHEET" in label and label not in aliases:
                        aliases.append(label)
                        insights["learned_patterns"].append(f"Learned sheet label: '{label}'")

        elif col_key == "revision" and new_val:
            if raw_text:
                rev_m = re.search(r'(REV(?:ISION)?[A-Z0-9\-_:\s]*' + re.escape(str(new_val)) + r')', raw_text, re.IGNORECASE)
                if rev_m:
                    aliases = self.memory.setdefault("learned_label_aliases", {}).setdefault("revision", [])
                    token = rev_m.group(1).strip().upper()
                    if token and token not in aliases:
                        aliases.append(token)
                        insights["learned_patterns"].append(f"Learned revision format: '{token}'")

        self.memory["total_extractions_learned"] = self.memory.get("total_extractions_learned", 0) + 1
        self.save_memory()
        logging.info(f"Learned manual edit for '{file_name}': {col_key} = '{new_val}'. Insights: {insights['learned_patterns']}")
        return insights

    # =========================================================================
    # APPLY LEARNED KNOWLEDGE TO EXTRACTION
    # =========================================================================

    def apply_learned_knowledge(self, raw_data, text, filename):
        """
        Enhances raw_data using previously learned ML patterns, TF-IDF vectorization,
        learned label aliases, and OCR typo corrections.
        """
        # 1. Exact Manual Correction fallback if previously edited
        if filename in self.memory.get("manual_corrections", {}):
            corrections = self.memory["manual_corrections"][filename]
            for k, v in corrections.items():
                if v:
                    raw_data[k] = v

        # Apply typo correction dictionary to text
        corr_text = self.apply_typo_corrections(text)

        # 2. ML Project Name Matching
        curr_proj = raw_data.get("project_name", "")
        if not curr_proj or len(curr_proj) < 5 or curr_proj.upper() in ["AMARAVATI", "PROJECT"]:
            proj_match, score = self.match_project_ml(corr_text)
            if proj_match and score >= 0.55:
                raw_data["project_name"] = proj_match
                logging.info(f"ML Project Matched: '{proj_match}' (score: {score:.2f})")

        # 3. ML Client Name Matching
        curr_client = raw_data.get("client_name", "")
        if not curr_client or len(curr_client) < 5 or curr_client.startswith("."):
            client_match, score = self.match_client_ml(corr_text)
            if client_match and score >= 0.55:
                raw_data["client_name"] = client_match
                logging.info(f"ML Client Matched: '{client_match}' (score: {score:.2f})")

        # 4. Learned Drawing Number Prefixes & OCR Typo Repair
        curr_dwg = raw_data.get("drawing_number", "")
        prefixes = self.memory.get("drawing_prefixes", [])
        
        # If current dwg is empty or generic header
        if not curr_dwg or curr_dwg in ["REV", "Title", "DWG No", "DATE", "SHEET", "DWG"]:
            for prefix in prefixes:
                pat = rf'\b({re.escape(prefix)}(?:[\s\-_]+[A-Z0-9\.]+)+)\b'
                match = re.search(pat, corr_text, re.IGNORECASE)
                if match:
                    raw_dwg = re.sub(r"\s+", "", match.group(1))
                    # Repair digit typos: 'O' surrounded by digits -> '0'
                    raw_dwg = re.sub(r'(?<=\d)[O|o](?=\d)', '0', raw_dwg)
                    raw_dwg = re.sub(r'(?<=\d)[O|o]$', '0', raw_dwg)
                    raw_data["drawing_number"] = raw_dwg
                    break

        # 5. Learned Revision Aliases & Merged Formats (e.g. REVO -> 0)
        curr_rev = raw_data.get("revision", "")
        if not curr_rev or len(curr_rev) > 2 or curr_rev in ["DR", "SH", "WT"]:
            rev_merge = re.search(r'\bREV\s*([0-9A-Z])(?:\)|\]|\s|$)', corr_text, re.IGNORECASE)
            if rev_merge:
                char = rev_merge.group(1).upper()
                raw_data["revision"] = "0" if char == "O" else char
            else:
                rev_aliases = self.memory.get("learned_label_aliases", {}).get("revision", [])
                for alias in rev_aliases:
                    if alias in corr_text:
                        rev_match = re.search(rf'{re.escape(alias)}[:\s\-]*([A-Za-z0-9]+)', corr_text, re.IGNORECASE)
                        if rev_match and len(rev_match.group(1)) <= 2:
                            raw_data["revision"] = rev_match.group(1).upper()
                            break

        # 6. Learned Sheet Number Aliases (e.g. SHEET NC 1, SHEET NG 1)
        curr_sheet = raw_data.get("sheet_number", "")
        if not curr_sheet:
            sheet_aliases = self.memory.get("learned_label_aliases", {}).get("sheet_number", ["SHEET NC", "SHEET NG", "SHT NO"])
            for alias in sheet_aliases:
                sheet_match = re.search(rf'\b{re.escape(alias)}[:\s\-]*([0-9]+)\b', corr_text, re.IGNORECASE)
                if sheet_match:
                    raw_data["sheet_number"] = str(int(sheet_match.group(1)))
                    break

        # 7. Learned Personnel (Drawn By, Checked By, Approved By)
        personnel = self.memory.get("known_personnel", [])
        aliases_map = self.memory.get("learned_label_aliases", {})
        
        for p_field in ["drawn_by", "checked_by", "approved_by"]:
            if not raw_data.get(p_field):
                field_aliases = aliases_map.get(p_field, [])
                for alias in field_aliases:
                    p_match = re.search(rf'\b{re.escape(alias)}[:\.\s]+([A-Za-z\.\s]{{2,8}})(?:\n|$|\s{{2,}})', corr_text, re.IGNORECASE)
                    if p_match:
                        raw_data[p_field] = p_match.group(1).strip(" .\t-")
                        break

        # 8. Clean Drawing Title of OCR artifacts (e.g. trailing 'oTe3', 'ores', 'OTs')
        curr_title = raw_data.get("drawing_title", "")
        if curr_title:
            m_noise = re.search(r'\s+([a-zA-Z0-9]{2,6})$', curr_title)
            if m_noise:
                token = m_noise.group(1)
                if not token.isupper() or (any(c.isdigit() for c in token) and any(c.isalpha() for c in token)):
                    curr_title = curr_title[:m_noise.start()].strip()
            clean_title = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', curr_title).strip()
            raw_data["drawing_title"] = clean_title

        return raw_data

# Singleton instance
engine = LearningEngine()
