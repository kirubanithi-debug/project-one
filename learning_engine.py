import os
import json
import re
import logging
from datetime import datetime

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned_memory.json")

class LearningEngine:
    def __init__(self, memory_file=MEMORY_FILE):
        self.memory_file = memory_file
        self.memory = self.load_memory()

    def default_structure(self):
        return {
            "drawing_prefixes": [],      # e.g. ["BISPL-TCM-STR-FD", "STD-RF"]
            "known_projects": [],        # e.g. ["AMARAVATI STATE SECRETARIAT...", "STADIUM ROOF STRUCTURE"]
            "known_clients": [],         # e.g. ["Andhra Pradesh Capital Region...", "URBAN SPORTS DEVELOPMENT"]
            "manual_corrections": {},    # filename/hash -> {field: value}
            "pattern_weights": {},       # pattern -> match_count
            "total_extractions_learned": 0,
            "last_updated": ""
        }

    def load_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Ensure all keys exist
                    default = self.default_structure()
                    for k, v in default.items():
                        if k not in data:
                            data[k] = v
                    return data
            except Exception as e:
                logging.error(f"Error loading learned memory file: {e}")
        return self.default_structure()

    def save_memory(self):
        try:
            self.memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, indent=2, ensure_ascii=False)
            logging.info(f"Learned memory saved. Total patterns: {len(self.memory['drawing_prefixes'])} prefixes, {len(self.memory['known_projects'])} projects.")
        except Exception as e:
            logging.error(f"Error saving learned memory file: {e}")

    def learn_from_record(self, doc_data):
        """
        Learns patterns from a single extracted document record.
        """
        dwg_num = str(doc_data.get("drawing_number", "")).strip()
        proj = str(doc_data.get("project_name", "")).strip()
        client = str(doc_data.get("client_name", "")).strip()

        changed = False

        # 1. Learn Drawing Number Prefixes (e.g. BISPL-TCM-STR-FD-T5)
        if dwg_num:
            prefix_match = re.match(r'^([A-Z0-9]{2,8}(?:\s*-\s*[A-Z0-9]{2,8}){1,4})', dwg_num)
            if prefix_match:
                prefix = prefix_match.group(1).upper()
                if prefix not in self.memory["drawing_prefixes"] and len(prefix) >= 5:
                    self.memory["drawing_prefixes"].append(prefix)
                    changed = True

        # 2. Learn Known Projects
        if proj and len(proj) > 5 and proj not in self.memory["known_projects"]:
            self.memory["known_projects"].append(proj)
            changed = True

        # 3. Learn Known Clients
        if client and len(client) > 5 and client not in self.memory["known_clients"]:
            self.memory["known_clients"].append(client)
            changed = True

        self.memory["total_extractions_learned"] += 1
        if changed:
            self.save_memory()

    def learn_from_batch(self, data_list):
        """
        Learns patterns from a full batch of extractions.
        """
        for row in data_list:
            if row.get("status") in ["Valid", "Suspicious"]:
                self.learn_from_record(row)

    def learn_manual_edit(self, file_name, col_key, new_val):
        """
        Learns from a user's manual correction in the UI table.
        """
        if not file_name or not col_key:
            return

        if file_name not in self.memory["manual_corrections"]:
            self.memory["manual_corrections"][file_name] = {}

        self.memory["manual_corrections"][file_name][col_key] = new_val

        # Also add to known projects/clients/prefixes
        if col_key == "project_name" and new_val and len(new_val) > 5:
            if new_val not in self.memory["known_projects"]:
                self.memory["known_projects"].append(new_val)

        elif col_key == "client_name" and new_val and len(new_val) > 5:
            if new_val not in self.memory["known_clients"]:
                self.memory["known_clients"].append(new_val)

        elif col_key == "drawing_number" and new_val:
            prefix_match = re.match(r'^([A-Z0-9]{2,8}(?:\s*-\s*[A-Z0-9]{2,8}){1,4})', new_val)
            if prefix_match:
                prefix = prefix_match.group(1).upper()
                if prefix not in self.memory["drawing_prefixes"]:
                    self.memory["drawing_prefixes"].append(prefix)

        self.save_memory()
        logging.info(f"Learned user manual edit for '{file_name}': {col_key} = '{new_val}'")

    def apply_learned_knowledge(self, raw_data, text, filename):
        """
        Enhances raw_data using previously learned memory rules.
        """
        # 1. Apply user manual corrections for exact filename if previously edited
        if filename in self.memory["manual_corrections"]:
            corrections = self.memory["manual_corrections"][filename]
            for k, v in corrections.items():
                if v:
                    raw_data[k] = v

        # 2. Check learned drawing prefixes if drawing_number is missing or incomplete
        current_dwg = raw_data.get("drawing_number", "")
        if not current_dwg or current_dwg in ["REV", "Title", "DWG No", "DATE", "SHEET"]:
            for prefix in self.memory["drawing_prefixes"]:
                # Search text for learned prefix
                pat = rf'\b({re.escape(prefix)}(?:\s*-\s*[A-Z0-9\.]+)+)\b'
                match = re.search(pat, text, re.IGNORECASE)
                if match:
                    raw_data["drawing_number"] = re.sub(r"\s+", "", match.group(1))
                    break

        # 3. Check learned project names if project is missing/short
        current_proj = raw_data.get("project_name", "")
        if not current_proj or len(current_proj) < 5:
            for proj in self.memory["known_projects"]:
                # Check key words in project
                keywords = [w for w in proj.split() if len(w) > 3][:3]
                if keywords and all(re.search(rf'\b{re.escape(kw)}\b', text, re.IGNORECASE) for kw in keywords):
                    raw_data["project_name"] = proj
                    break

        # 4. Check learned clients if client is missing/short
        current_client = raw_data.get("client_name", "")
        if not current_client or len(current_client) < 5:
            for client in self.memory["known_clients"]:
                keywords = [w for w in client.split() if len(w) > 3][:3]
                if keywords and all(re.search(rf'\b{re.escape(kw)}\b', text, re.IGNORECASE) for kw in keywords):
                    raw_data["client_name"] = client
                    break

        return raw_data

# Singleton instance
engine = LearningEngine()
