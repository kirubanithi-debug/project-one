import re
import os
import logging
from datetime import datetime
import config
import utils

def validate_value(value, validation_rule):
    """
    Validates an extracted string value against a validation rule.
    Returns (is_valid, reason)
    """
    if not value or value.strip() == "":
        if validation_rule.get("required", False):
            return False, "Required field is missing"
        return True, "" # Optional field is allowed to be empty

    val_type = validation_rule.get("type", "text")
    clean_val = value.strip()

    if val_type == "integer":
        try:
            num_str = re.sub(r"[^\d]", "", clean_val)
            if not num_str:
                return False, "Not an integer"
            int(num_str)
            return True, ""
        except ValueError:
            return False, "Not an integer"

    elif val_type == "numeric":
        try:
            num_str = clean_val.replace(",", "")
            match = re.search(r"[-+]?\d*\.\d+|\d+", num_str)
            if not match:
                return False, "Not a numeric value"
            float(match.group())
            return True, ""
        except ValueError:
            return False, "Not a numeric value"

    elif val_type == "regex":
        pattern = validation_rule.get("pattern", "")
        if pattern:
            if re.match(pattern, clean_val):
                return True, ""
            else:
                return False, f"Failed pattern match ({pattern})"
        return True, ""

    elif val_type == "date":
        # Basic date format check (e.g. DD-MM-YYYY, YYYY/MM/DD, DD.MM.YY etc.)
        date_patterns = [
            r"^\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4}$", # 12/05/2020, 21.02.2026
            r"^\d{4}[\/\.\-]\d{1,2}[\/\.\-]\d{1,2}$", # 2020-05-12
            r"^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}$",    # 12 May 2020, 12-May-20
            r"^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4}$"    # May 12, 2020
        ]
        is_date_match = False
        for pat in date_patterns:
            if re.match(pat, clean_val, re.IGNORECASE):
                is_date_match = True
                break
        if is_date_match:
            return True, ""
        return False, "Invalid date format"

    elif val_type == "text":
        if len(clean_val) > 0:
            return True, ""
        return False, "Empty text"

    return True, ""

def clean_extracted_value(key, value):
    """
    Apply field-specific cleaning to extracted raw strings.
    Converts common OCR typos (e.g. letter 'O' instead of digit '0').
    """
    if not value:
        return ""
    
    clean = str(value).strip()
    
    # Remove leading/trailing delimiters common in drawings
    clean = re.sub(r"^[\s\-_=:;|]+|[\s\-_=:;|]+$", "", clean)
    
    if key == "revision":
        # OCR typo: convert single or double 'O' / 'o' to '0' / '00'
        if clean.upper() in ["O", "OO"]:
            clean = "0" if clean.upper() == "O" else "00"
        clean = re.sub(r"[^A-Za-z0-9]", "", clean)
        if len(clean) > 2:
            clean = clean[:2]
            
    elif key == "drawing_number":
        clean = re.sub(r"\s+", "", clean)
        # Fix OCR typos where letter 'O' occurs between numbers, e.g. 5O08 -> 5008
        clean = re.sub(r'(?<=\d)[O|o](?=\d)', '0', clean)
        clean = re.sub(r'(?<=\d)[O|o]$', '0', clean)
        # Reject generic notes or label headers misidentified as drawing numbers
        if any(w in clean.upper() for w in ["U.N.O", "UNO", "UNLESS", "NOTED", "TITLE", "DATE", "SCALE", "SHEET", "REVISION"]):
            clean = ""
            
    elif key == "quantity":
        # OCR typo: 'Ooms' or 'O' -> '1' or '01'
        clean_upper = clean.upper()
        if "OOMS" in clean_upper or clean_upper in ["O", "OO"]:
            return "1"
        digits = re.findall(r"\d+", clean)
        clean = digits[0] if digits else ""
        
    elif key == "weight":
        # Handle 'ka' OCR typo for 'kg' or clean numerical match
        clean_clean = clean.replace(",", ".")
        matches = re.findall(r"\d+(?:\.\d+)?", clean_clean)
        clean = matches[0] if matches else ""
        
    elif key == "sheet_number" or key == "total_sheets":
        digits = re.findall(r"\d+", clean)
        clean = digits[0] if digits else ""
        
    elif key in ["drawing_title", "project_name", "client_name"]:
        # Strip trailing repeated label text
        clean = re.sub(r"\s+(?:Title|Project Name|Client|Date|Scale|Sheet Size)\s*$", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip()
        
    return clean

def extract_fields_from_text(text):
    """
    Applies regex patterns to extract target fields from raw text.
    Includes advanced multi-line layout scanning and OCR typo tolerance.
    """
    extracted_data = {}
    normalized_text = re.sub(r"\s+", " ", text)
    
    # 1. Standard Regex Matching
    for field in config.FIELD_DEFINITIONS:
        key = field["key"]
        patterns = field["regex"]
        extracted_val = ""
        found = False
        
        # Only allow searching normalized text for weight, project, client, and remark
        allow_normalized = key in ["weight", "project_name", "client_name", "remark"]
        
        for pat in patterns:
            # Multi-line search on original text
            match = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if match:
                extracted_val = match.group(1) if match.groups() else match.group(0)
                found = True
                break
            
            # Fallback search on normalized single-line text (only if allowed)
            if allow_normalized:
                match = re.search(pat, normalized_text, re.IGNORECASE)
                if match:
                    extracted_val = match.group(1) if match.groups() else match.group(0)
                    found = True
                    break
                
        clean_val = clean_extracted_value(key, extracted_val)
        extracted_data[key] = clean_val

    # 2. Advanced Multi-line Layout-Aware Fallbacks
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    # Line scan for quantity if missing
    if not extracted_data.get("quantity"):
        for line in lines:
            qty_match = re.search(r'\b(\d+)\s*(?:QTY|OFF|OFFS|NOS|NO|SETS?|REQUIRED)\b', line, re.IGNORECASE)
            if qty_match:
                extracted_data["quantity"] = clean_extracted_value("quantity", qty_match.group(1))
                break

    # Parse numeric quantity
    qty_num = 1
    try:
        if extracted_data.get("quantity"):
            qty_num = int(extracted_data["quantity"])
    except ValueError:
        qty_num = 1

    # Total Weight calculation/extraction when Quantity > 1
    if qty_num > 1:
        # Search for total weight matching total assemblies (e.g. TOTAL WT. FOR 3 ASSEMBLIES)
        tot_wt_match = re.search(rf'(\d+(?:[\.,]\d+)?)\s*(?:KG|kg|ka|KA)?\s*TOTAL\s*WT\.\s*FOR\s*{qty_num}\s*ASSEMBLI', text, re.IGNORECASE)
        if tot_wt_match:
            extracted_data["weight"] = clean_extracted_value("weight", tot_wt_match.group(1))
        else:
            tot_wt_match2 = re.search(rf'TOTAL\s*WT\.\s*FOR\s*{qty_num}\s*ASSEMBLIES?\s*(\d+(?:[\.,]\d+)?)', text, re.IGNORECASE)
            if tot_wt_match2:
                extracted_data["weight"] = clean_extracted_value("weight", tot_wt_match2.group(1))

    # Line scan for weight if still missing
    if not extracted_data.get("weight"):
        for line in lines:
            wt_match = re.search(r'\b(\d+(?:[\.,]\d+)?)\s*(?:KG|kg|ka|KA|T|TON)\b', line, re.IGNORECASE)
            if wt_match:
                extracted_data["weight"] = clean_extracted_value("weight", wt_match.group(1))
                break

    # Final Total Weight verification: If single assembly weight was extracted and Qty > 1,
    # calculate total weight = Unit Weight * Quantity if total weight is not explicitly higher.
    curr_wt_str = extracted_data.get("weight", "")
    if curr_wt_str and qty_num > 1:
        try:
            curr_wt_val = float(curr_wt_str.replace(",", ""))
            # Check if there is a higher total weight number in text matching Qty * Unit Weight
            expected_tot = round(curr_wt_val * qty_num, 2)
            # Look for expected_tot in text (allowing small decimal rounding)
            expected_pattern = rf'\b({int(expected_tot)}|{expected_tot:.1f}|{expected_tot:.2f})\b'
            tot_in_text = re.search(expected_pattern, text)
            if tot_in_text:
                extracted_data["weight"] = str(tot_in_text.group(1))
            else:
                # If unit weight was extracted (e.g. 50.7 for 1 assembly), convert to total weight for all Qty assemblies
                # check if 'FOR 1 ASSEMBLY' was near curr_wt_str
                if re.search(rf'{re.escape(curr_wt_str)}.{0,30}1\s*ASSEMBLY|1\s*ASSEMBLY.{0,30}{re.escape(curr_wt_str)}', text, re.IGNORECASE):
                    extracted_data["weight"] = f"{expected_tot:.1f}" if expected_tot.is_integer() or round(expected_tot,1) == expected_tot else f"{expected_tot:.2f}"
        except ValueError:
            pass

    dwg_num = extracted_data.get("drawing_number", "")
    if "BISPL" in text or "BISPL" in dwg_num or "TCM" in text or "STD" in text or "WEPP" in text:
        # Resolve drawing number if missed or mis-extracted
        if not dwg_num or dwg_num in ["REV", "Title", "DWG No", "DATE", "SHEET"]:
            dwg_match = re.search(r'\b([A-Z0-9]{3,10}(?:\s*-\s*[A-Z0-9\.]+)+)\b', text, re.IGNORECASE)
            if dwg_match:
                dwg_num = dwg_match.group(1)
                extracted_data["drawing_number"] = clean_extracted_value("drawing_number", dwg_num)
        
        # Scan lines to align values that are offset due to column-wise layouts
        for idx, line in enumerate(lines):
            if dwg_num and (line == dwg_num or re.sub(r"\s+", "", line) == dwg_num):
                # 1. Forward Alignment (fields below drawing number)
                if idx + 1 < len(lines) and len(lines[idx+1]) <= 2:
                    extracted_data["revision"] = clean_extracted_value("revision", lines[idx+1])
                if idx + 2 < len(lines) and re.match(r'^\d{2}[\.\/\-]\d{2}[\.\/\-]\d{4}$', lines[idx+2]):
                    extracted_data["date"] = clean_extracted_value("date", lines[idx+2])
                if idx + 3 < len(lines) and lines[idx+3] not in ["1:10", "1:15", "1:20", "JMJ", "JP", "JSE"]:
                    if not extracted_data.get("drawing_title"):
                        extracted_data["drawing_title"] = clean_extracted_value("drawing_title", lines[idx+3])

                # 2. Backward/Reversed Alignment (fields above drawing number)
                date_offset = -1
                for offset in range(1, 9):
                    if idx - offset >= 0:
                        potential_date = lines[idx - offset]
                        if re.match(r'^\d{2}[\.\/\-]\d{2}[\.\/\-]\d{4}$', potential_date):
                            date_offset = offset
                            break
                            
                if date_offset != -1:
                    date_idx = idx - date_offset
                    if date_idx - 1 >= 0 and len(lines[date_idx - 1]) <= 2:
                        extracted_data["revision"] = clean_extracted_value("revision", lines[date_idx - 1])
                    extracted_data["date"] = clean_extracted_value("date", lines[date_idx])
                    
                    if date_idx + 1 < len(lines) and re.match(r'^\d+:\d+$', lines[date_idx + 1]):
                        extracted_data["scale"] = lines[date_idx + 1]
                    
                    if date_idx + 2 < len(lines):
                        extracted_data["drawn_by"] = lines[date_idx + 2]
                    if date_idx + 3 < len(lines):
                        extracted_data["checked_by"] = lines[date_idx + 3]
                    if date_idx + 4 < len(lines):
                        extracted_data["approved_by"] = lines[date_idx + 4]
                    
                    if idx - 1 >= 0 and not extracted_data.get("drawing_title"):
                        extracted_data["drawing_title"] = clean_extracted_value("drawing_title", lines[idx - 1])
                else:
                    # Simple backward fallback: Title is directly above
                    if idx - 1 >= 0 and len(lines[idx - 1]) > 5 and not extracted_data.get("drawing_title"):
                        if not any(w in lines[idx-1] for w in ["DRWN", "CHKD", "APPD", "SCALE", "DATE"]):
                            extracted_data["drawing_title"] = clean_extracted_value("drawing_title", lines[idx - 1])
            
            # Scale and Sign-off Initials
            if re.match(r'^\d+:\d+$', line) or line.lower() == 'nts':
                extracted_data["scale"] = line
                if idx + 3 < len(lines):
                    if all(re.match(r'^[A-Z\.\s]{2,5}$', lines[idx+i]) for i in [1, 2, 3]):
                        extracted_data["drawn_by"] = lines[idx+1]
                        extracted_data["checked_by"] = lines[idx+2]
                        extracted_data["approved_by"] = lines[idx+3]
            
            # Sheet info alignment
            sheet_match = re.search(r'(?:SHT|SH)\s*[-_]?\s*(\d+)\s*OF\s*(\d+)', line, re.IGNORECASE)
            if sheet_match:
                extracted_data["sheet_number"] = clean_extracted_value("sheet_number", sheet_match.group(1))
                extracted_data["total_sheets"] = clean_extracted_value("total_sheets", sheet_match.group(2))
                    
            # Quantity Fallbacks
            qty_match = re.search(r'(\d+)\s*QTY\s+([A-Za-z0-9\s]+)\s+REQUIRED', line, re.IGNORECASE)
            if qty_match:
                extracted_data["quantity"] = clean_extracted_value("quantity", qty_match.group(1))
            else:
                req_match = re.search(r'No\.?[ \t]*(?:Req\'d|Reqd|Required)[ \t\-_:]*([0-9]+)', line, re.IGNORECASE)
                if req_match:
                    extracted_data["quantity"] = clean_extracted_value("quantity", req_match.group(1))

            # Revision Remark Fallback
            if not extracted_data.get("remark"):
                if re.search(r'^(?:ISSUED|REVISED|APPROVED|HOLD)\s+FOR\s+[A-Za-z\s]+|^[A-Z0-9\-]+\s+DECREASED|^WELD\s+MODIFIED', line, re.IGNORECASE):
                    extracted_data["remark"] = line

        # Project name fallback
        if not extracted_data.get("project_name") or len(extracted_data["project_name"]) < 5 or "PMC" in extracted_data["project_name"]:
            proj_match = re.search(r'AMARAVATI\s+STATE\s+SECRETARIAT[A-Z0-9\s&\(\),\-]+', text, re.IGNORECASE)
            if proj_match:
                extracted_data["project_name"] = clean_extracted_value("project_name", proj_match.group(0))
                
        # Client name fallback
        if not extracted_data.get("client_name") or len(extracted_data["client_name"]) < 5:
            client_match = re.search(r'Andhra\s+Pradesh\s+Capital\s*Region\s+Development\s+Authority', text, re.IGNORECASE)
            if client_match:
                extracted_data["client_name"] = 'Andhra Pradesh Capital Region Development Authority'

    return extracted_data

import learning_engine

def process_extracted_document(file_path, text, file_hash):
    """
    Wraps raw text extraction, cleans the fields, performs validation,
    applies learned memory patterns, and returns structured results.
    Includes robust filename fallback rules.
    """
    filename = os.path.basename(file_path)
    raw_data = extract_fields_from_text(text)
    
    # Apply self-learned knowledge and past user corrections
    raw_data = learning_engine.engine.apply_learned_knowledge(raw_data, text, filename)
    
    # Match revision in filename: e.g., "- Rev 0", "_RevA", "Rev.1"
    if not raw_data.get("revision") or len(raw_data.get("revision", "")) > 2 or raw_data["revision"] in ["DR", "SH", "WT"]:
        rev_fn_match = re.search(r'[\s\-_]Rev(?:ision)?[ \t\._]*([A-Z0-9]+)', filename, re.IGNORECASE)
        if rev_fn_match:
            raw_data["revision"] = clean_extracted_value("revision", rev_fn_match.group(1))
            
    # Match sheet details in filename: e.g., "SHT-01 OF 03", "SH 01 OF 04", "SH01"
    if not raw_data.get("sheet_number") or not raw_data.get("total_sheets"):
        sheet_fn_match = re.search(r'(?:SHT|SH)[ \t\-_]*(\d+)[ \t]*OF[ \t]*(\d+)', filename, re.IGNORECASE)
        if sheet_fn_match:
            if not raw_data.get("sheet_number"):
                raw_data["sheet_number"] = clean_extracted_value("sheet_number", sheet_fn_match.group(1))
            if not raw_data.get("total_sheets"):
                raw_data["total_sheets"] = clean_extracted_value("total_sheets", sheet_fn_match.group(2))
        else:
            sheet_single_match = re.search(r'(?:SHT|SH)[ \t\-_]*(\d+)', filename, re.IGNORECASE)
            if sheet_single_match and not raw_data.get("sheet_number"):
                raw_data["sheet_number"] = clean_extracted_value("sheet_number", sheet_single_match.group(1))

    # Match drawing number in filename
    dwg_in_fn = ""
    dwg_fn_match = re.search(r'\b(BISPL-[A-Z0-9\-\.]+)\b', filename, re.IGNORECASE)
    if dwg_fn_match:
        dwg_in_fn = clean_extracted_value("drawing_number", dwg_fn_match.group(1))
    else:
        # General fallback: grab prefix up to 'SH' or 'Rev' or '-'
        prefix_match = re.split(r'\s+(?:SHT|SH)\s+|\s+Rev\s+|\s+-+Rev\s+|_Rev', filename, flags=re.IGNORECASE)
        if prefix_match and len(prefix_match[0]) > 8:
            dwg_in_fn = clean_extracted_value("drawing_number", prefix_match[0])

    # If extracted drawing number is empty, generic, or just a substring/prefix of the one in the filename,
    # use the filename one because it represents the complete drawing number.
    current_dwg = raw_data.get("drawing_number", "")
    if not current_dwg or current_dwg in ["REV", "Title", "DWG No", "DATE", "SHEET"] or (dwg_in_fn and current_dwg in dwg_in_fn and len(current_dwg) < len(dwg_in_fn)):
        raw_data["drawing_number"] = dwg_in_fn
                
    # 4. Multi-sheet Handling:
    # Preserves extracted weights and quantities if present. Only leaves empty if not found.
    # We do NOT erase non-empty extracted weight/quantity values!
    sheet_num_str = raw_data.get("sheet_number", "")
    try:
        sheet_num = int(sheet_num_str) if sheet_num_str else 1
    except ValueError:
        sheet_num = 1

    # Run validation and build fields metadata
    row_data = {
        "file_name": filename,
        "file_path": file_path,
        "file_hash": file_hash,
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    validation_status = {}
    invalid_fields = []
    missing_required = []
    
    for field in config.FIELD_DEFINITIONS:
        key = field["key"]
        value = raw_data.get(key, "")
        rule = field["validation"]
        
        is_valid, reason = validate_value(value, rule)
        
        row_data[key] = value
        validation_status[key] = {
            "is_valid": is_valid,
            "reason": reason
        }
        
        if not is_valid:
            if not value or value.strip() == "":
                if rule.get("required", False):
                    missing_required.append(key)
            else:
                invalid_fields.append(key)

    # Determine overall status
    if missing_required:
        row_status = "Missing"
    elif invalid_fields:
        row_status = "Suspicious"
    else:
        row_status = "Valid"
        
    row_data["status"] = row_status
    row_data["_validation"] = validation_status
    
    # Self-learn from extracted data
    try:
        learning_engine.engine.learn_from_record(row_data)
    except Exception as e:
        import logging
        logging.error(f"Error in self-learning step: {e}")
        
    return row_data
