import os
import json
import re
import logging
import math
import threading
from datetime import datetime

# Machine Learning & NLP imports with graceful fallbacks
try:
    import numpy as np
    from scipy.sparse import hstack, csr_matrix
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics.pairwise import cosine_similarity
    import joblib
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "learned_memory.json")
MODEL_FILE = os.path.join(BASE_DIR, "learned_models.joblib")


# =============================================================================
# DOMAIN FEATURE & CANDIDATE EXTRACTION HELPERS
# =============================================================================

def _extract_series_prefix(dwg_num):
    """Extracts a clean drawing series prefix (avoiding polluting memory with full part numbers)."""
    if not dwg_num:
        return ""
    dwg_upper = dwg_num.strip().upper()
    # Strip trailing level/member codes like -L06-LP1013, -L07-DC1003, -2026-X1, -9004-C, -508-0
    m = re.match(r'^([A-Z]{2,8}(?:-[A-Z0-9]{2,8})+?)(?:-(?:L\d+|[A-Z]{1,4}\d{3,}|\d{3,}))', dwg_upper)
    if m:
        return m.group(1)
    # Fallback: first 2-3 segments if purely alphabetic/short prefix
    parts = [p for p in dwg_upper.split("-") if p]
    if len(parts) >= 3 and re.search(r'\d{3,}', parts[-1]):
        return "-".join(parts[:2])
    if len(parts) >= 2 and not re.search(r'\d{3,}', parts[1]):
        return "-".join(parts[:2])
    return ""


def pair_stacked_table_lines(text):
    """
    Detects column-stacked BOM/weight summary blocks (common in CAD/Tekla PDFs)
    where consecutive label lines (e.g. 'TOTAL WT. FOR BOLT & STUD ASSEMBLY',
    'TOTAL WT. FOR 1 ASSEMBLY', 'TOTAL WT. FOR 2 ASSEMBLIES') are followed
    immediately by consecutive numeric values ('0.00', '2.0', '4.1').
    Returns a list of synthetic paired strings like 'TOTAL WT. FOR 2 ASSEMBLIES 4.1'.
    """
    if not text:
        return []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    paired = []
    i = 0
    while i < len(lines):
        if re.search(r'^TOTAL\s*(?:WT\.?|FOR)\b', lines[i], re.IGNORECASE) and not re.search(r'\d+\.\d+\s*$', lines[i]):
            label_block = [lines[i]]
            j = i + 1
            while j < len(lines) and len(label_block) < 6:
                if re.search(r'^TOTAL\s*(?:WT\.?|FOR)\b', lines[j], re.IGNORECASE) and not re.search(r'\d+\.\d+\s*$', lines[j]):
                    label_block.append(lines[j])
                    j += 1
                else:
                    break
            if len(label_block) >= 2 and j + len(label_block) <= len(lines):
                val_block = lines[j:j + len(label_block)]
                if all(re.match(r'^\d+(?:[\.,]\d+)?(?:\s*(?:kg|KG|ka|KA|t|T|ton|TON))?$', v) for v in val_block):
                    for lbl, val in zip(label_block, val_block):
                        paired.append(f"{lbl} {val}")
                    i = j + len(label_block)
                    continue
        i += 1
    return paired


def _mask_number_in_context(prev_line, cur_line, next_line, num_str):
    """Masks the target numeric candidate as <NUM> inside its 3-line local context."""
    masked_cur = re.sub(rf'(?<![\d\.]){re.escape(num_str)}(?![\d\.])', '<NUM>', cur_line, count=1)
    parts = []
    if prev_line:
        parts.append(f"PREV: {prev_line}")
    parts.append(f"CUR: {masked_cur}")
    if next_line:
        parts.append(f"NEXT: {next_line}")
    return " || ".join(parts)


def extract_weight_candidates(text, qty_num=1):
    """
    Extracts candidate weight numbers from document text along with
    rich domain + layout features for ML ranking.
    """
    if not text:
        return []

    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
    paired_lines = pair_stacked_table_lines(text)
    all_lines = [(l, i, len(raw_lines), False) for i, l in enumerate(raw_lines)]
    for idx_p, pl in enumerate(paired_lines):
        all_lines.append((pl, len(raw_lines) + idx_p, len(raw_lines) + len(paired_lines), True))

    candidates = []
    seen_keys = set()

    # Pre-scan unit weights (e.g., FOR 1 ASSEMBLY or WEIGHT/ONE) so we can detect qty * unit_wt consistency
    unit_wt_vals = []
    for l, _, _, _ in all_lines:
        if re.search(r'\b(?:FOR\s*1\s*ASSEMBLY|TOTAL\s*FOR\s*1\s*ASSEMBLY|WEIGHT\s*/\s*ONE)\b', l, re.IGNORECASE):
            for num_m in re.finditer(r'\b(\d+(?:[\.,]\d+)?)\b', l):
                try:
                    v = float(num_m.group(1).replace(",", ""))
                    if v > 0 and num_m.group(1) != "1":
                        unit_wt_vals.append(v)
                except ValueError:
                    pass

    weight_kw_re = re.compile(r'\b(?:WT|WEIGHT|MASS|KG|KA|TON|TOTAL\s*WT|ASSEMBL(?:Y|IES))\b', re.IGNORECASE)

    for line_idx, (line, orig_idx, total_cnt, is_paired) in enumerate(all_lines):
        prev_line = raw_lines[orig_idx - 1] if (not is_paired and orig_idx > 0) else ""
        next_line = raw_lines[orig_idx + 1] if (not is_paired and orig_idx + 1 < len(raw_lines)) else ""

        # Check if line or immediate neighbors have weight relevance
        has_kw_cur = bool(weight_kw_re.search(line))
        has_kw_adj = bool(weight_kw_re.search(prev_line) or weight_kw_re.search(next_line))

        # Skip obvious date/scale/drawing-number lines unless weight keywords are present
        if not has_kw_cur and not has_kw_adj:
            continue

        # Exclude dates like 15-06-2026 or 20.07.2026
        cleaned_for_nums = re.sub(r'\b\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4}\b', ' ', line)
        # Exclude scale like 1:10
        cleaned_for_nums = re.sub(r'\b\d+:\d+\b', ' ', cleaned_for_nums)
        # Exclude plate sizes like PLT10*140
        cleaned_for_nums = re.sub(r'\b[A-Z]+\d+\*\d+\b', ' ', cleaned_for_nums, flags=re.IGNORECASE)

        for m in re.finditer(r'(?<![A-Za-z0-9\.\-])(\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z0-9\.\-]|:\d)', cleaned_for_nums):
            raw_num = m.group(1)
            val_clean = raw_num.replace(",", "")
            try:
                val_float = float(val_clean)
            except ValueError:
                continue

            # Skip the 'N' inside "FOR N ASSEMBLIES" or "FOR 1 ASSEMBLY"
            after_slice = cleaned_for_nums[m.end():m.end() + 20]
            before_slice = cleaned_for_nums[max(0, m.start() - 20):m.start()]
            if re.match(r'^\s*ASSEMBL(?:Y|IES)\b', after_slice, re.IGNORECASE) and re.search(r'\bFOR\s*$', before_slice, re.IGNORECASE):
                continue
            if re.match(r'^\s*(?:NUMBER\.?\s*REQ|QTY\s|NOS\b|SHEETS?\b)', after_slice, re.IGNORECASE):
                continue
            if re.search(r'\b(?:SHEET|SHT|SH|OF|REV)\s*$', before_slice, re.IGNORECASE):
                continue

            # Compute 14 engineered features
            has_total_wt_for_qty = 0.0
            if qty_num > 1 and re.search(rf'\bTOTAL\s*WT\.?\s*FOR\s*{qty_num}\s*ASSEMBLIES?\b', line, re.IGNORECASE):
                has_total_wt_for_qty = 1.0
            elif qty_num > 1 and prev_line and re.search(rf'\bTOTAL\s*WT\.?\s*FOR\s*{qty_num}\s*ASSEMBLIES?\b', prev_line, re.IGNORECASE):
                has_total_wt_for_qty = 0.8

            has_total_wt_for_all = 1.0 if re.search(r'\bTOTAL\s*WT\.?\s*FOR\s*ALL\s*ASSEMBLIES?\b', line, re.IGNORECASE) else 0.0
            has_for_1_asm = 1.0 if re.search(r'\b(?:TOTAL\s*(?:WT\.?)?\s*FOR\s*1\s*ASSEMBLY|WT\.?\s*FOR\s*1\s*ASSEMBLY)\b', line, re.IGNORECASE) else 0.0
            has_bolt_stud = 1.0 if re.search(r'\b(?:BOLT|STUD)\b', line, re.IGNORECASE) else 0.0
            has_weight_one = 1.0 if re.search(r'\bWEIGHT\s*/\s*ONE\b', line, re.IGNORECASE) else 0.0
            has_area_or_len = 1.0 if re.search(r'\b(?:AREA|LENGTH|SIZE|GRADE|MARK)\b', line, re.IGNORECASE) and not re.search(r'TOTAL\s*WT', line, re.IGNORECASE) else 0.0
            has_kg_unit = 1.0 if re.search(r'\b(?:KG|KA|TON|T)\b', line, re.IGNORECASE) else 0.0
            is_zero = 1.0 if val_float == 0.0 else 0.0
            has_decimal = 1.0 if "." in val_clean else 0.0

            matches_unit_times_qty = 0.0
            if qty_num > 1 and val_float > 0:
                for uw in unit_wt_vals:
                    prod = uw * qty_num
                    if abs(val_float - prod) <= max(0.5, 0.05 * prod):
                        matches_unit_times_qty = 1.0
                        break

            is_same_line_label = 1.0 if has_kw_cur else 0.0
            val_after_label = 1.0 if re.search(r'\b(?:WT|WEIGHT|MASS|ASSEMBL(?:Y|IES))\b', before_slice + line[:m.start()], re.IGNORECASE) else 0.0
            log_val = math.log1p(max(0.0, val_float))
            rel_pos = orig_idx / max(1, total_cnt)

            # Avoid duplicate identical (value, context_line) entries
            dedup_key = (val_clean, line)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            context_str = _mask_number_in_context(prev_line, line, next_line, raw_num)
            feats = [
                has_total_wt_for_qty,
                has_total_wt_for_all,
                has_for_1_asm,
                has_bolt_stud,
                has_weight_one,
                has_area_or_len,
                has_kg_unit,
                is_zero,
                has_decimal,
                matches_unit_times_qty,
                is_same_line_label,
                val_after_label,
                log_val,
                rel_pos,
            ]
            candidates.append({
                "value": val_clean,
                "float_val": val_float,
                "line": line,
                "context": context_str,
                "features": feats,
                "is_total_for_qty": bool(has_total_wt_for_qty >= 0.8 or has_total_wt_for_all > 0.5),
                "is_for_1_asm": bool(has_for_1_asm > 0.5),
                "is_paired": is_paired,
            })

    return candidates


def extract_quantity_candidates(text):
    """
    Extracts candidate integer quantity values from document text along with
    domain + layout features for ML ranking.
    """
    if not text:
        return []

    raw_lines = [l.strip() for l in text.split("\n") if l.strip()]
    candidates = []
    seen_keys = set()

    # Check which N appears in "TOTAL WT. FOR N ASSEMBLIES"
    asm_wt_counts = set()
    for m in re.finditer(r'TOTAL\s*WT\.?\s*FOR\s*(\d+)\s*ASSEMBLIES?\b', text, re.IGNORECASE):
        try:
            asm_wt_counts.add(int(m.group(1)))
        except ValueError:
            pass

    qty_kw_re = re.compile(r'\b(?:QTY|QUANTITY|REQUIRED|REQ\'?D|NUMBER|NO\.?\s*OFF|NOS|SETS?|MATERIAL\s*LIST|ASSEMBL(?:Y|IES)|SHEET|SHT)\b', re.IGNORECASE)

    for idx, line in enumerate(raw_lines):
        prev_line = raw_lines[idx - 1] if idx > 0 else ""
        next_line = raw_lines[idx + 1] if idx + 1 < len(raw_lines) else ""
        if not qty_kw_re.search(line) and not qty_kw_re.search(prev_line):
            continue

        # Strip dates, scales, decimals, part marks like 06CP1384 or PLT10*140
        cleaned = re.sub(r'\b\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4}\b', ' ', line)
        cleaned = re.sub(r'\b\d+:\d+\b', ' ', cleaned)
        cleaned = re.sub(r'\b\d+\.\d+\b', ' ', cleaned)
        cleaned = re.sub(r'\b[A-Z]+\d+\*\d+\b', ' ', cleaned, flags=re.IGNORECASE)

        for m in re.finditer(r'(?<![A-Za-z0-9\.\-])(\d{1,4})(?![A-Za-z0-9\.\-])', cleaned):
            num_str = m.group(1)
            try:
                val_int = int(num_str)
            except ValueError:
                continue
            if val_int <= 0 or val_int > 10000:
                continue

            before = cleaned[:m.start()]
            after = cleaned[m.end():]

            has_number_req = 1.0 if re.search(r'\bNUMBER\.?\s*(?:REQ\'?D|REQUIRED)\b', after, re.IGNORECASE) or re.search(r'\bNUMBER\.?\s*(?:REQ\'?D|REQUIRED)[:\s]*$', before, re.IGNORECASE) else 0.0
            has_explicit_qty = 1.0 if (re.search(r'\b(?:QTY|QUANTITY|NO\.?\s*OFF|NO\.?\s*(?:REQ\'?D|REQUIRED))[:\s\-]*$', before, re.IGNORECASE) or re.search(r'^\s*(?:QTY\b.*REQUIRED|QTY\s*(?:REQ\'?D|REQUIRED)|(?:NOS|OFFS?|SETS?)\s*(?:REQ\'?D|REQUIRED))', after, re.IGNORECASE)) else 0.0
            is_mat_list_hdr = 1.0 if re.search(r'\bMATERIAL\s+LIST\b', line, re.IGNORECASE) else 0.0
            is_weight_line = 1.0 if re.search(r'\b(?:TOTAL\s*WT|WT\.?|WEIGHT|KG|KA|MASS)\b', line, re.IGNORECASE) or (re.search(r'\b1\s*ASSEMBLY\b', line, re.IGNORECASE) and not has_explicit_qty and not has_number_req) else 0.0
            is_sheet_line = 1.0 if re.search(r'\b(?:SHEET|SHT|SH|OF\s+\d+\s+SHEETS?)\b', line, re.IGNORECASE) else 0.0
            is_item_row = 1.0 if re.search(r'\b(?:PLT|E350|E250|ISMC|ISMB|GRADE|LENGTH|AREA)\b', line, re.IGNORECASE) else 0.0
            matches_tot_wt_asm = 1.0 if (val_int > 1 and val_int in asm_wt_counts) else 0.0
            is_gt_1 = 1.0 if val_int > 1 else 0.0

            dedup_key = (str(val_int), line)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            context_str = _mask_number_in_context(prev_line, line, next_line, num_str)
            feats = [
                has_number_req,
                has_explicit_qty,
                is_mat_list_hdr,
                is_weight_line,
                is_sheet_line,
                is_item_row,
                matches_tot_wt_asm,
                is_gt_1,
            ]
            candidates.append({
                "value": str(val_int),
                "int_val": val_int,
                "line": line,
                "context": context_str,
                "features": feats,
            })

    return candidates


def _get_bootstrap_training_data():
    """
    Provides realistic seed training samples covering standard CAD text PDFs,
    Tekla material list tables, multi-assembly weights, and noisy OCR layouts
    so all ML classifiers are trained and accurate immediately out-of-the-box.
    """
    # --- 1. Weight Candidate Samples: (context, 14-features, label) ---
    # Features order:
    # [has_total_wt_for_qty, has_total_wt_for_all, has_for_1_asm, has_bolt_stud,
    #  has_weight_one, has_area_or_len, has_kg_unit, is_zero, has_decimal,
    #  matches_unit_times_qty, is_same_line_label, val_after_label, log_val, rel_pos]
    weight_samples = [
        # Positives (True assembly/total weight)
        {"context": "PREV: TOTAL WT. FOR 1 ASSEMBLY 2.0 || CUR: TOTAL WT. FOR 2 ASSEMBLIES <NUM> || NEXT: DRG NO", "features": [1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, math.log1p(4.1), 0.5], "label": 1, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR 3 ASSEMBLIES <NUM> KG", "features": [1, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, math.log1p(152.0), 0.5], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> KG TOTAL WT. FOR 4 ASSEMBLIES", "features": [1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, math.log1p(340.5), 0.5], "label": 1, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR ALL ASSEMBLIES <NUM>", "features": [0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, math.log1p(920.0), 0.6], "label": 1, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR 1 ASSEMBLY : <NUM> kg", "features": [0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 1, 1, math.log1p(18888.0), 0.7], "label": 1, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR 1 ASSEMBLY <NUM>", "features": [0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, math.log1p(25175.5), 0.7], "label": 1, "source": "bootstrap"},
        {"context": "CUR: WT: <NUM> kg", "features": [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, math.log1p(850.5), 0.4], "label": 1, "source": "bootstrap"},
        {"context": "CUR: DRG NO: WPP-PIPE-508-0 WT: <NUM> kg", "features": [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, math.log1p(345.0), 0.3], "label": 1, "source": "bootstrap"},
        {"context": "CUR: NET WEIGHT: <NUM> KG", "features": [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, math.log1p(420.5), 0.5], "label": 1, "source": "bootstrap"},
        {"context": "CUR: TOTAL WEIGHT <NUM> T", "features": [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 1, math.log1p(12.4), 0.5], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> kg TOTAL WT.", "features": [0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 1, 0, math.log1p(65.2), 0.6], "label": 1, "source": "bootstrap"},

        # Negatives (Bolt/stud 0.00, unit weight when multi-qty exists, BOM row dimensions/areas, stray numbers)
        {"context": "CUR: TOTAL WT. FOR BOLT & STUD ASSEMBLY <NUM>", "features": [0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 1, 1, 0.0, 0.4], "label": 0, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR BOLT & STUD ASSEMBLY <NUM>", "features": [0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, math.log1p(1.2), 0.4], "label": 0, "source": "bootstrap"},
        {"context": "PREV: TOTAL WT. FOR BOLT & STUD ASSEMBLY 0.00 || CUR: TOTAL WT. FOR 1 ASSEMBLY <NUM> || NEXT: TOTAL WT. FOR 2 ASSEMBLIES 4.1", "features": [0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1, 1, math.log1p(2.0), 0.45], "label": 0, "source": "bootstrap"},
        {"context": "CUR: 06CP1384 PLT10*140 E350BR 1 185 <NUM> 2.03 2.03", "features": [0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, math.log1p(0.06), 0.3], "label": 0, "source": "bootstrap"},
        {"context": "CUR: 06CP1384 PLT10*140 E350BR 1 <NUM> 0.06 2.03 2.03", "features": [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, math.log1p(185.0), 0.3], "label": 0, "source": "bootstrap"},
        {"context": "CUR: WEIGHT/ONE(kg) <NUM>", "features": [0, 0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 1, math.log1p(2.03), 0.3], "label": 0, "source": "bootstrap"},
        {"context": "CUR: 5 4 3 2 <NUM> || NEXT: MATERIAL LIST", "features": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, math.log1p(8.0), 0.05], "label": 0, "source": "bootstrap"},
        {"context": "CUR: TOTAL FOR 1 ASSEMBLY <NUM> 0.06 2.03", "features": [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, math.log1p(1.0), 0.35], "label": 0, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR 2 ASSEMBLIES <NUM> || NEXT: 0.00", "features": [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 1, 0.0, 0.5], "label": 0, "source": "bootstrap"},
        {"context": "CUR: LENGTH(mm) <NUM>", "features": [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, math.log1p(185.0), 0.25], "label": 0, "source": "bootstrap"},
        {"context": "CUR: AREA(m2) <NUM>", "features": [0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, math.log1p(0.06), 0.25], "label": 0, "source": "bootstrap"},
    ]

    # --- 2. Quantity Candidate Samples: (context, 8-features, label) ---
    # [has_number_req, has_explicit_qty, is_mat_list_hdr, is_weight_line,
    #  is_sheet_line, is_item_row, matches_tot_wt_asm, is_gt_1]
    quantity_samples = [
        # Positives
        {"context": "CUR: MATERIAL LIST FOR ONE ASSEMBLY MK'D T5-L06-LP1013 <NUM> NUMBER. REQUIRED", "features": [1, 0, 1, 0, 0, 0, 1, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: MATERIAL LIST FOR ONE ASSEMBLY MK'D T5-L06-B1001 <NUM> NUMBER. REQUIRED", "features": [1, 0, 1, 0, 0, 0, 0, 0], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> NUMBER REQUIRED", "features": [1, 0, 0, 0, 0, 0, 1, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> QTY COLUMN REQUIRED", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> QTY DC1005 REQUIRED", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: QTY: <NUM>", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: QUANTITY: <NUM>", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: NO. REQ'D: <NUM>", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: <NUM> NOS REQUIRED", "features": [0, 1, 0, 0, 0, 0, 0, 1], "label": 1, "source": "bootstrap"},
        {"context": "CUR: NO OFF: <NUM>", "features": [0, 1, 0, 0, 0, 0, 0, 0], "label": 1, "source": "bootstrap"},

        # Negatives
        {"context": "CUR: TOTAL WT. FOR <NUM> ASSEMBLY : 18888.0 kg", "features": [0, 0, 0, 1, 0, 0, 0, 0], "label": 0, "source": "bootstrap"},
        {"context": "CUR: TOTAL WT. FOR <NUM> ASSEMBLIES 4.1", "features": [0, 0, 0, 1, 0, 0, 0, 1], "label": 0, "source": "bootstrap"},
        {"context": "CUR: TOTAL FOR <NUM> ASSEMBLY 1 0.06 2.03", "features": [0, 0, 0, 1, 0, 0, 0, 0], "label": 0, "source": "bootstrap"},
        {"context": "CUR: 06CP1384 PLT10*140 E350BR <NUM> 185 0.06 2.03", "features": [0, 0, 0, 0, 0, 1, 0, 0], "label": 0, "source": "bootstrap"},
        {"context": "CUR: SHT-0<NUM> OF 04", "features": [0, 0, 0, 0, 1, 0, 0, 0], "label": 0, "source": "bootstrap"},
        {"context": "CUR: SHEET NO: <NUM>", "features": [0, 0, 0, 0, 1, 0, 0, 1], "label": 0, "source": "bootstrap"},
        {"context": "CUR: OF <NUM> SHEETS", "features": [0, 0, 0, 0, 1, 0, 0, 1], "label": 0, "source": "bootstrap"},
        {"context": "CUR: MATERIAL LIST FOR ONE ASSEMBLY MK'D T5-L06-LP1013 <NUM> 2 NUMBER. REQUIRED", "features": [0, 0, 1, 0, 0, 0, 0, 1], "label": 0, "source": "bootstrap"},
    ]

    # --- 3. Line Field Classifier Samples ---
    line_samples = [
        {"text": "DRG NO: BISPL-TCM-STR-FD-T5-L06-LP1013", "field": "drawing_number", "source": "bootstrap"},
        {"text": "DRG NO: STD-RF-9004-C", "field": "drawing_number", "source": "bootstrap"},
        {"text": "DRG NO: WPP-PIPE-508-0", "field": "drawing_number", "source": "bootstrap"},
        {"text": "DWG. NO. BRG-SPAN-2026-X1", "field": "drawing_number", "source": "bootstrap"},
        {"text": "TITLE: DETAIL OF L06-FIN PLATE", "field": "drawing_title", "source": "bootstrap"},
        {"text": "TITLE: STEEL TRUSS NODES", "field": "drawing_title", "source": "bootstrap"},
        {"text": "TITLE INLET MANIFOLD DETAIL", "field": "drawing_title", "source": "bootstrap"},
        {"text": "DIAGRID COLUMN", "field": "drawing_title", "source": "bootstrap"},
        {"text": "DETAIL OF BEAM AT LEVEL 06", "field": "drawing_title", "source": "bootstrap"},
        {"text": "REV: 00", "field": "revision", "source": "bootstrap"},
        {"text": "REV: C", "field": "revision", "source": "bootstrap"},
        {"text": "REVO", "field": "revision", "source": "bootstrap"},
        {"text": "TOTAL WT. FOR 2 ASSEMBLIES 4.1", "field": "weight", "source": "bootstrap"},
        {"text": "TOTAL WT. FOR 1 ASSEMBLY : 18888.0 kg", "field": "weight", "source": "bootstrap"},
        {"text": "WT: 850.5 kg", "field": "weight", "source": "bootstrap"},
        {"text": "WT: 345 kg", "field": "weight", "source": "bootstrap"},
        {"text": "MATERIAL LIST FOR ONE ASSEMBLY MK'D T5-L06-LP1013 2 NUMBER. REQUIRED", "field": "quantity", "source": "bootstrap"},
        {"text": "8 QTY COLUMN REQUIRED", "field": "quantity", "source": "bootstrap"},
        {"text": "QTY: 12", "field": "quantity", "source": "bootstrap"},
        {"text": "SHEET NO: 3", "field": "sheet_number", "source": "bootstrap"},
        {"text": "SHEET NC 1", "field": "sheet_number", "source": "bootstrap"},
        {"text": "SHT-01 OF 04", "field": "sheet_number", "source": "bootstrap"},
        {"text": "OF 6 SHEETS", "field": "total_sheets", "source": "bootstrap"},
        {"text": "OF 4 SHEETS", "field": "total_sheets", "source": "bootstrap"},
        {"text": "PROJECT: STADIUM ROOF STRUCTURE", "field": "project_name", "source": "bootstrap"},
        {"text": "PROJECT: WATER PURIFICATION PLANT", "field": "project_name", "source": "bootstrap"},
        {"text": "AMARAVATI STATE SECRETARIAT & HEADS OF DEPARTMENT", "field": "project_name", "source": "bootstrap"},
        {"text": "CLIENT: URBAN SPORTS DEVELOPMENT", "field": "client_name", "source": "bootstrap"},
        {"text": "CLIENT. MUNICIPAL WATER UTILITIES", "field": "client_name", "source": "bootstrap"},
        {"text": "Andhra Pradesh Capital Region Development Authority", "field": "client_name", "source": "bootstrap"},
        {"text": "DATE: 15-06-2026", "field": "date", "source": "bootstrap"},
        {"text": "DATE: 20-07-2026", "field": "date", "source": "bootstrap"},
        {"text": "SCALE: 1:10", "field": "scale", "source": "bootstrap"},
        {"text": "SCALE 1:25", "field": "scale", "source": "bootstrap"},
        {"text": "DRAWN BY: E.W.", "field": "drawn_by", "source": "bootstrap"},
        {"text": "DRAW BY: ALEX.M", "field": "drawn_by", "source": "bootstrap"},
        {"text": "CHECKED BY: R.J.", "field": "checked_by", "source": "bootstrap"},
        {"text": "CHECKED BY. AS.", "field": "checked_by", "source": "bootstrap"},
        {"text": "APPROVED BY: T.S.", "field": "approved_by", "source": "bootstrap"},
        {"text": "APPROVED BY. MM.", "field": "approved_by", "source": "bootstrap"},
        {"text": "ISSUED FOR FABRICATION", "field": "remark", "source": "bootstrap"},
        {"text": "REVISED FOR APPROVAL", "field": "remark", "source": "bootstrap"},
        {"text": "GENERAL NOTES: ONLY FIGURED DIMENSIONS TO BE FOLLOWED", "field": "OTHER", "source": "bootstrap"},
        {"text": "MARK SIZE GRADE QTY. LENGTH(mm) AREA(m2)", "field": "OTHER", "source": "bootstrap"},
        {"text": "TOTAL WT. FOR BOLT & STUD ASSEMBLY 0.00", "field": "OTHER", "source": "bootstrap"},
    ]

    return {
        "weight_samples": weight_samples,
        "quantity_samples": quantity_samples,
        "line_samples": line_samples,
    }


# =============================================================================
# SCIKIT-LEARN CANDIDATE RANKER & LINE FIELD CLASSIFIER
# =============================================================================

class CandidateRanker:
    """
    Hybrid NLP + Domain-Feature Binary Classifier (TF-IDF + StandardScaler + LogisticRegression)
    that ranks candidate numeric values in a drawing and assigns calibrated probabilities.
    """
    def __init__(self, expected_num_features):
        self.expected_num_features = expected_num_features
        self.text_vec = None
        self.scaler = None
        self.clf = None
        self.is_fitted = False
        self.accuracy = 0.0

    def fit(self, samples):
        if not SKLEARN_AVAILABLE or not samples:
            return 0.0
        contexts = [s["context"] for s in samples]
        X_num = np.array([s["features"] for s in samples], dtype=float)
        y = np.array([int(s["label"]) for s in samples], dtype=int)
        if len(set(y)) < 2:
            return 0.0

        weights = np.array([3.0 if s.get("source") == "manual" else (1.5 if s.get("source") == "auto" else 1.0) for s in samples])

        self.text_vec = FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), max_features=600, sublinear_tf=True, token_pattern=r'(?u)\b[\w<>]+\b')),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), max_features=600, sublinear_tf=True)),
        ])
        X_txt = self.text_vec.fit_transform(contexts)
        self.scaler = StandardScaler(with_mean=False)
        X_num_scaled = self.scaler.fit_transform(csr_matrix(X_num))
        X_all = hstack([X_txt, X_num_scaled])

        self.clf = LogisticRegression(C=2.5, class_weight="balanced", max_iter=500, random_state=42)
        self.clf.fit(X_all, y, sample_weight=weights)
        self.is_fitted = True

        preds = self.clf.predict(X_all)
        self.accuracy = float(np.mean(preds == y))
        return self.accuracy

    def score_candidates(self, candidates):
        if not self.is_fitted or not candidates or not SKLEARN_AVAILABLE:
            return [(c, 0.0) for c in candidates]
        contexts = [c["context"] for c in candidates]
        X_num = np.array([c["features"] for c in candidates], dtype=float)
        X_txt = self.text_vec.transform(contexts)
        X_num_scaled = self.scaler.transform(csr_matrix(X_num))
        X_all = hstack([X_txt, X_num_scaled])
        probs = self.clf.predict_proba(X_all)[:, 1]
        scored = [(c, float(p)) for c, p in zip(candidates, probs)]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored


class LineFieldClassifier:
    """
    Multi-class TF-IDF + LogisticRegression classifier predicting which drawing
    field each text line belongs to.
    """
    def __init__(self):
        self.vec = None
        self.clf = None
        self.is_fitted = False
        self.accuracy = 0.0

    def fit(self, samples):
        if not SKLEARN_AVAILABLE or not samples:
            return 0.0
        texts = [s["text"] for s in samples]
        labels = [s["field"] for s in samples]
        if len(set(labels)) < 2:
            return 0.0

        weights = np.array([2.5 if s.get("source") == "manual" else 1.0 for s in samples])

        self.vec = FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), max_features=1200, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=1500, sublinear_tf=True)),
        ])
        X = self.vec.fit_transform(texts)
        self.clf = LogisticRegression(C=3.0, class_weight="balanced", max_iter=500, random_state=42)
        self.clf.fit(X, labels, sample_weight=weights)
        self.is_fitted = True

        preds = self.clf.predict(X)
        self.accuracy = float(np.mean([p == t for p, t in zip(preds, labels)]))
        return self.accuracy

    def predict_best_line(self, lines, target_field, min_prob=0.45):
        if not self.is_fitted or not lines or not SKLEARN_AVAILABLE:
            return None, 0.0, -1
        classes = list(self.clf.classes_)
        if target_field not in classes:
            return None, 0.0, -1
        col_idx = classes.index(target_field)
        X = self.vec.transform(lines)
        probs = self.clf.predict_proba(X)[:, col_idx]
        best_idx = int(np.argmax(probs))
        best_prob = float(probs[best_idx])
        if best_prob >= min_prob:
            return lines[best_idx], best_prob, best_idx
        return None, best_prob, best_idx


# =============================================================================
# MAIN LEARNING ENGINE
# =============================================================================

class LearningEngine:
    def __init__(self, memory_file=MEMORY_FILE, model_file=MODEL_FILE):
        self._lock = threading.RLock()
        self.memory_file = memory_file
        self.model_file = model_file
        self.memory = self.load_memory()
        self.weight_ranker = CandidateRanker(expected_num_features=14)
        self.quantity_ranker = CandidateRanker(expected_num_features=8)
        self.line_classifier = LineFieldClassifier()
        self._pending_new_samples = 0
        self._load_or_train_models()

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
            "ml_training_data": {
                "weight_samples": [],
                "quantity_samples": [],
                "line_samples": []
            },
            "model_metrics": {
                "weight_accuracy": 0.0,
                "quantity_accuracy": 0.0,
                "line_accuracy": 0.0,
                "total_samples": 0,
                "last_trained": ""
            },
            "total_extractions_learned": 0,
            "last_updated": ""
        }

    def load_memory(self):
        default = self.default_structure()
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                if "ml_training_data" not in data or not isinstance(data["ml_training_data"], dict):
                    data["ml_training_data"] = default["ml_training_data"]
                for sub_k, sub_v in default["ml_training_data"].items():
                    data["ml_training_data"].setdefault(sub_k, sub_v)
                if "model_metrics" not in data or not isinstance(data["model_metrics"], dict):
                    data["model_metrics"] = default["model_metrics"]
                # Compact legacy bloated drawing_prefixes (e.g. 600+ full part numbers)
                cleaned_prefixes = []
                for p in data.get("drawing_prefixes", []):
                    compact = _extract_series_prefix(p) or p
                    if compact not in cleaned_prefixes:
                        cleaned_prefixes.append(compact)
                data["drawing_prefixes"] = cleaned_prefixes
                return data
            except Exception as e:
                logging.error(f"Error loading learned memory file: {e}")
        return default

    def save_memory(self):
        with self._lock:
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

    def _load_or_train_models(self):
        if not SKLEARN_AVAILABLE:
            return
        with self._lock:
            if os.path.exists(self.model_file):
                try:
                    bundle = joblib.load(self.model_file)
                    if isinstance(bundle, dict) and bundle.get("version") == 2:
                        self.weight_ranker = bundle["weight_ranker"]
                        self.quantity_ranker = bundle["quantity_ranker"]
                        self.line_classifier = bundle["line_classifier"]
                        return
                except Exception as e:
                    logging.warning(f"Could not load saved ML models, retraining: {e}")
            self.retrain_models(save_mem=False)

    def retrain_models(self, force=True, save_mem=True):
        """
        Retrains all 3 scikit-learn ML models (Weight Ranker, Quantity Ranker,
        Line Field Classifier) using bootstrap data + learned user/auto samples.
        """
        if not SKLEARN_AVAILABLE:
            return {}

        with self._lock:
            boot = _get_bootstrap_training_data()
            user_data = self.memory.get("ml_training_data", {})

            w_samples = boot["weight_samples"] + user_data.get("weight_samples", [])
            q_samples = boot["quantity_samples"] + user_data.get("quantity_samples", [])
            l_samples = boot["line_samples"] + user_data.get("line_samples", [])

            w_acc = self.weight_ranker.fit(w_samples)
            q_acc = self.quantity_ranker.fit(q_samples)
            l_acc = self.line_classifier.fit(l_samples)

            metrics = {
                "weight_accuracy": round(w_acc * 100, 1),
                "quantity_accuracy": round(q_acc * 100, 1),
                "line_accuracy": round(l_acc * 100, 1),
                "weight_samples": len(w_samples),
                "quantity_samples": len(q_samples),
                "line_samples": len(l_samples),
                "total_samples": len(w_samples) + len(q_samples) + len(l_samples),
                "last_trained": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.memory["model_metrics"] = metrics
            self._pending_new_samples = 0

            try:
                joblib.dump({
                    "version": 2,
                    "weight_ranker": self.weight_ranker,
                    "quantity_ranker": self.quantity_ranker,
                    "line_classifier": self.line_classifier,
                }, self.model_file)
            except Exception as e:
                logging.error(f"Error persisting ML model file: {e}")

            if save_mem:
                self.save_memory()
            return metrics

    def _add_training_sample(self, bucket, sample, max_items=1500):
        """Deduplicates and appends a labeled sample, keeping manual samples prioritized."""
        samples = self.memory.setdefault("ml_training_data", {}).setdefault(bucket, [])
        key_field = "context" if "context" in sample else "text"
        lbl_field = "label" if "label" in sample else "field"
        for existing in samples:
            if existing.get(key_field) == sample.get(key_field) and existing.get(lbl_field) == sample.get(lbl_field):
                if sample.get("source") == "manual":
                    existing["source"] = "manual"
                return False
        samples.append(sample)
        if len(samples) > max_items:
            manual = [s for s in samples if s.get("source") == "manual"]
            others = [s for s in samples if s.get("source") != "manual"]
            keep_others = max(0, max_items - len(manual))
            self.memory["ml_training_data"][bucket] = manual[-max_items:] + others[-keep_others:]
        return True

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

        if RAPIDFUZZ_AVAILABLE:
            for cand in candidate_list:
                score = fuzz.token_set_ratio(clean_query, cand) / 100.0
                if score > best_score:
                    best_score = score
                    best_match = cand

        if SKLEARN_AVAILABLE and len(candidate_list) > 0:
            try:
                vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4))
                X = vec.fit_transform(candidate_list + [clean_query])
                sims = cosine_similarity(X[-1:], X[:-1])[0]
                tfidf_idx = int(sims.argmax())
                tfidf_score = float(sims[tfidf_idx])
                if tfidf_score > best_score:
                    best_score = tfidf_score
                    best_match = candidate_list[tfidf_idx]
            except Exception as e:
                logging.debug(f"TF-IDF similarity calculation exception: {e}")

        if best_score >= threshold:
            return best_match, best_score
        return None, best_score

    def match_project_ml(self, text):
        """Searches document text for any known project using ML similarity."""
        known = self.memory.get("known_projects", [])
        if not known:
            return None, 0.0

        corr_text = self.apply_typo_corrections(text)
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

    def predict_weight_ml(self, text, qty_num=1):
        """Uses WeightMLRanker to score all weight candidates and return (best_val, best_prob, best_candidate)."""
        candidates = extract_weight_candidates(text, qty_num=qty_num)
        if not candidates or not self.weight_ranker.is_fitted:
            return None, 0.0, None
        scored = self.weight_ranker.score_candidates(candidates)
        if not scored:
            return None, 0.0, None
        best_cand, best_prob = scored[0]
        return best_cand["value"], best_prob, best_cand

    def predict_quantity_ml(self, text):
        """Uses QuantityMLRanker to score all quantity candidates and return (best_val, best_prob, best_candidate)."""
        candidates = extract_quantity_candidates(text)
        if not candidates or not self.quantity_ranker.is_fitted:
            return None, 0.0, None
        scored = self.quantity_ranker.score_candidates(candidates)
        if not scored:
            return None, 0.0, None
        best_cand, best_prob = scored[0]
        return best_cand["value"], best_prob, best_cand

    # =========================================================================
    # ACTIVE LEARNING & FEEDBACK
    # =========================================================================

    def learn_from_record(self, doc_data):
        """
        Learns drawing prefixes, projects, clients, personnel, AND harvests
        high-confidence ML training examples from extracted document records.
        """
        with self._lock:
            dwg_num = str(doc_data.get("drawing_number", "")).strip()
            proj = str(doc_data.get("project_name", "")).strip()
            client = str(doc_data.get("client_name", "")).strip()
            drawn = str(doc_data.get("drawn_by", "")).strip()
            chkd = str(doc_data.get("checked_by", "")).strip()
            appd = str(doc_data.get("approved_by", "")).strip()

            changed = False

            # 1. Learn Drawing Number Series Prefix
            if dwg_num and len(dwg_num) >= 5:
                prefix = _extract_series_prefix(dwg_num)
                if prefix and prefix not in self.memory["drawing_prefixes"] and len(prefix) >= 4:
                    self.memory["drawing_prefixes"].append(prefix)
                    changed = True

            # 2. Learn Known Project
            if proj and len(proj) > 5:
                clean_proj = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', proj).strip()
                existing_match, _ = self.match_entity_ml(clean_proj, self.memory["known_projects"], threshold=0.80)
                if not existing_match and clean_proj not in self.memory["known_projects"]:
                    self.memory["known_projects"].append(clean_proj)
                    changed = True

            # 3. Learn Known Client
            if client and len(client) > 5:
                clean_client = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', client).strip()
                existing_match, _ = self.match_entity_ml(clean_client, self.memory["known_clients"], threshold=0.80)
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

            # 5. Harvest ML training samples if Valid & raw_text is present
            raw_text = doc_data.get("raw_text", "")
            if raw_text and doc_data.get("status") == "Valid":
                added = self._harvest_samples_from_record(doc_data, raw_text, source="auto")
                if added > 0:
                    changed = True
                    self._pending_new_samples += added

            self.memory["total_extractions_learned"] = self.memory.get("total_extractions_learned", 0) + 1
            if self._pending_new_samples >= 15:
                self.retrain_models(save_mem=True)
            elif changed:
                self.save_memory()

    def _harvest_samples_from_record(self, doc_data, raw_text, source="auto"):
        added = 0
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

        # Weight candidate samples
        wt_val = str(doc_data.get("weight", "")).strip()
        try:
            qty_num = int(doc_data.get("quantity", "") or 1)
        except ValueError:
            qty_num = 1
        if wt_val:
            try:
                wt_f = float(wt_val.replace(",", ""))
                for c in extract_weight_candidates(raw_text, qty_num=qty_num):
                    lbl = 1 if abs(c["float_val"] - wt_f) <= 0.01 else 0
                    if self._add_training_sample("weight_samples", {
                        "context": c["context"],
                        "features": c["features"],
                        "label": lbl,
                        "source": source,
                    }):
                        added += 1
            except ValueError:
                pass

        # Quantity candidate samples
        qty_val = str(doc_data.get("quantity", "")).strip()
        if qty_val:
            try:
                q_i = int(qty_val)
                for c in extract_quantity_candidates(raw_text):
                    lbl = 1 if c["int_val"] == q_i else 0
                    if self._add_training_sample("quantity_samples", {
                        "context": c["context"],
                        "features": c["features"],
                        "label": lbl,
                        "source": source,
                    }):
                        added += 1
            except ValueError:
                pass

        # Line classifier samples for populated text fields
        for f_key in ["drawing_number", "drawing_title", "weight", "quantity", "project_name", "client_name", "remark"]:
            f_val = str(doc_data.get(f_key, "")).strip()
            if f_val and len(f_val) >= 2:
                for line in lines:
                    if f_val.lower() in line.lower():
                        if self._add_training_sample("line_samples", {"text": line, "field": f_key, "source": source}):
                            added += 1
                        break

        return added

    def learn_manual_edit(self, file_name, col_key, new_val, raw_text=""):
        """
        Learns from a user's manual correction in the UI table.
        Updates rule memory AND immediately trains the scikit-learn ML models
        with active hard-negative mining from raw_text.
        """
        if not file_name or not col_key:
            return {}

        with self._lock:
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

            # 2. Field-specific pattern discovery
            if col_key == "client_name" and new_val and len(new_val) > 4:
                if new_val not in self.memory["known_clients"]:
                    self.memory["known_clients"].append(new_val)
                    insights["learned_patterns"].append(f"Added client: {new_val}")

                if raw_text:
                    client_lines = [l for l in raw_text.split("\n") if re.search(r'client|customer|owner', l, re.IGNORECASE)]
                    if client_lines:
                        raw_line = client_lines[0]
                        raw_words = re.findall(r'\b[A-Za-z]{4,}\b', raw_line)
                        correct_words = re.findall(r'\b[A-Za-z]{4,}\b', new_val)
                        for rw in raw_words:
                            if rw.upper() not in ["CLIENT", "CUSTOMER", "OWNER", "NAME"] and RAPIDFUZZ_AVAILABLE:
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
                            if rw.upper() not in ["PROJECT", "NAME", "JOB", "WORK"] and RAPIDFUZZ_AVAILABLE:
                                for cw in correct_words:
                                    sim = fuzz.ratio(rw.upper(), cw.upper())
                                    if 60 <= sim < 100:
                                        self.memory.setdefault("ocr_typo_corrections", {})[rw.upper()] = cw.upper()
                                        insights["learned_patterns"].append(f"Learned OCR typo: '{rw.upper()}' -> '{cw.upper()}'")

            elif col_key == "drawing_number" and new_val:
                prefix = _extract_series_prefix(new_val)
                if prefix and prefix not in self.memory["drawing_prefixes"] and len(prefix) >= 4:
                    self.memory["drawing_prefixes"].append(prefix)
                    insights["learned_patterns"].append(f"Added drawing prefix: {prefix}")

            elif col_key in ["drawn_by", "checked_by", "approved_by"] and new_val:
                personnel = self.memory.setdefault("known_personnel", [])
                val_clean = new_val.strip(" .\t-")
                if val_clean and val_clean not in personnel:
                    personnel.append(val_clean)
                    insights["learned_patterns"].append(f"Added personnel: {val_clean}")

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

            elif col_key == "sheet_number" and new_val and raw_text:
                sheet_m = re.search(rf'([A-Za-z\s]+)[:\.\s]+{re.escape(str(new_val))}\b', raw_text)
                if sheet_m:
                    label = sheet_m.group(1).strip().upper()
                    aliases = self.memory.setdefault("learned_label_aliases", {}).setdefault("sheet_number", [])
                    if label and "SHEET" in label and label not in aliases:
                        aliases.append(label)
                        insights["learned_patterns"].append(f"Learned sheet label: '{label}'")

            elif col_key == "revision" and new_val and raw_text:
                rev_m = re.search(r'(REV(?:ISION)?[A-Z0-9\-_:\s]*' + re.escape(str(new_val)) + r')', raw_text, re.IGNORECASE)
                if rev_m:
                    aliases = self.memory.setdefault("learned_label_aliases", {}).setdefault("revision", [])
                    token = rev_m.group(1).strip().upper()
                    if token and token not in aliases:
                        aliases.append(token)
                        insights["learned_patterns"].append(f"Learned revision format: '{token}'")

            # 3. Active Supervised ML Training from Manual Correction
            retrained = False
            if raw_text and new_val:
                if col_key == "weight":
                    try:
                        target_wt = float(str(new_val).replace(",", ""))
                        # Check if a quantity hint exists in raw_text
                        q_pred, q_prob, _ = self.predict_quantity_ml(raw_text)
                        q_num = int(q_pred) if (q_pred and q_prob >= 0.65) else 1
                        cands = extract_weight_candidates(raw_text, qty_num=q_num)
                        matched_any = False
                        for c in cands:
                            lbl = 1 if abs(c["float_val"] - target_wt) <= 0.01 else 0
                            if lbl == 1:
                                matched_any = True
                            self._add_training_sample("weight_samples", {
                                "context": c["context"],
                                "features": c["features"],
                                "label": lbl,
                                "source": "manual",
                            })
                        if matched_any:
                            insights["learned_patterns"].append(f"Trained Weight ML Ranker on target={new_val}")
                            retrained = True
                    except ValueError:
                        pass

                elif col_key == "quantity":
                    try:
                        target_q = int(str(new_val).strip())
                        cands = extract_quantity_candidates(raw_text)
                        matched_any = False
                        for c in cands:
                            lbl = 1 if c["int_val"] == target_q else 0
                            if lbl == 1:
                                matched_any = True
                            self._add_training_sample("quantity_samples", {
                                "context": c["context"],
                                "features": c["features"],
                                "label": lbl,
                                "source": "manual",
                            })
                        if matched_any:
                            insights["learned_patterns"].append(f"Trained Quantity ML Ranker on target={new_val}")
                            retrained = True
                    except ValueError:
                        pass

                # Add line sample for LineFieldClassifier across all fields
                for line in raw_text.split("\n"):
                    line_s = line.strip()
                    if line_s and str(new_val).lower() in line_s.lower():
                        self._add_training_sample("line_samples", {"text": line_s, "field": col_key, "source": "manual"})
                        retrained = True
                        break

            self.memory["total_extractions_learned"] = self.memory.get("total_extractions_learned", 0) + 1
            if retrained:
                metrics = self.retrain_models(save_mem=True)
                insights["learned_patterns"].append(
                    f"ML Models Retrained (Wt: {metrics.get('weight_accuracy')}%, Qty: {metrics.get('quantity_accuracy')}%)"
                )
            else:
                self.save_memory()

            logging.info(f"Learned manual edit for '{file_name}': {col_key} = '{new_val}'. Insights: {insights['learned_patterns']}")
            return insights

    # =========================================================================
    # APPLY LEARNED KNOWLEDGE TO EXTRACTION
    # =========================================================================

    def apply_learned_knowledge(self, raw_data, text, filename):
        """
        Enhances raw_data using trained scikit-learn ML models (Weight Ranker,
        Quantity Ranker, Line Field Classifier), TF-IDF similarity, learned label
        aliases, and OCR typo corrections.
        """
        with self._lock:
            # 1. Exact Manual Correction fallback if previously edited
            if filename in self.memory.get("manual_corrections", {}):
                corrections = self.memory["manual_corrections"][filename]
                for k, v in corrections.items():
                    if v:
                        raw_data[k] = v

            corr_text = self.apply_typo_corrections(text)
            lines = [l.strip() for l in corr_text.split("\n") if l.strip()]

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

            # 4. ML Quantity Ranker (recovers missing quantity or fixes weight-derived '1')
            curr_qty = str(raw_data.get("quantity", "")).strip()
            q_ml_val, q_ml_prob, q_cand = self.predict_quantity_ml(corr_text)
            if q_ml_val and q_ml_prob >= 0.72:
                if not curr_qty:
                    raw_data["quantity"] = q_ml_val
                    logging.info(f"ML Quantity Ranker predicted '{q_ml_val}' (prob: {q_ml_prob:.2f})")
                elif curr_qty == "1" and int(q_ml_val) > 1 and q_cand and q_cand["features"][6] > 0.5:
                    # Override stray '1' when ML found a >1 qty backed by TOTAL WT FOR N ASSEMBLIES
                    raw_data["quantity"] = q_ml_val
                    logging.info(f"ML Quantity Ranker upgraded '1' -> '{q_ml_val}' (prob: {q_ml_prob:.2f})")

            # 5. ML Weight Ranker (resolves multi-row / bolt-0.00 / column-stacked weight ambiguity)
            try:
                qty_num = int(raw_data.get("quantity") or 1)
            except ValueError:
                qty_num = 1

            curr_wt = str(raw_data.get("weight", "")).strip()
            w_ml_val, w_ml_prob, w_cand = self.predict_weight_ml(corr_text, qty_num=qty_num)
            if w_ml_val and w_ml_prob >= 0.65:
                try:
                    curr_wt_f = float(curr_wt.replace(",", "")) if curr_wt else 0.0
                except ValueError:
                    curr_wt_f = 0.0

                if not curr_wt or curr_wt_f == 0.0:
                    raw_data["weight"] = w_ml_val
                    logging.info(f"ML Weight Ranker filled missing/zero weight -> '{w_ml_val}' (prob: {w_ml_prob:.2f})")
                elif w_cand and w_cand.get("is_total_for_qty") and abs(w_cand["float_val"] - curr_wt_f) > 0.05 and w_ml_prob >= 0.78:
                    # ML detected explicit TOTAL WT FOR N ASSEMBLIES while regex picked a different number (e.g. unit weight or stray int)
                    raw_data["weight"] = w_ml_val
                    logging.info(f"ML Weight Ranker corrected '{curr_wt}' -> '{w_ml_val}' (prob: {w_ml_prob:.2f})")

            # 6. Learned Drawing Number Prefixes & OCR Typo Repair
            curr_dwg = raw_data.get("drawing_number", "")
            prefixes = self.memory.get("drawing_prefixes", [])
            if not curr_dwg or curr_dwg in ["REV", "Title", "DWG No", "DATE", "SHEET", "DWG"]:
                for prefix in prefixes:
                    pat = rf'\b({re.escape(prefix)}(?:[\s\-_]+[A-Z0-9\.]+)+)\b'
                    match = re.search(pat, corr_text, re.IGNORECASE)
                    if match:
                        raw_dwg = re.sub(r"\s+", "", match.group(1))
                        raw_dwg = re.sub(r'(?<=\d)[O|o](?=\d)', '0', raw_dwg)
                        raw_dwg = re.sub(r'(?<=\d)[O|o]$', '0', raw_dwg)
                        raw_data["drawing_number"] = raw_dwg
                        break

            # 7. Learned Revision Aliases & Merged Formats (e.g. REVO -> 0)
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

            # 8. Learned Sheet Number Aliases (e.g. SHEET NC 1, SHEET NG 1)
            curr_sheet = raw_data.get("sheet_number", "")
            if not curr_sheet:
                sheet_aliases = self.memory.get("learned_label_aliases", {}).get("sheet_number", ["SHEET NC", "SHEET NG", "SHT NO"])
                for alias in sheet_aliases:
                    sheet_match = re.search(rf'\b{re.escape(alias)}[:\s\-]*([0-9]+)\b', corr_text, re.IGNORECASE)
                    if sheet_match:
                        raw_data["sheet_number"] = str(int(sheet_match.group(1)))
                        break

            # 9. Learned Personnel (Drawn By, Checked By, Approved By)
            aliases_map = self.memory.get("learned_label_aliases", {})
            for p_field in ["drawn_by", "checked_by", "approved_by"]:
                if not raw_data.get(p_field):
                    field_aliases = aliases_map.get(p_field, [])
                    for alias in field_aliases:
                        p_match = re.search(rf'\b{re.escape(alias)}[:\.\s]+([A-Za-z\.\s]{{2,8}})(?:\n|$|\s{{2,}})', corr_text, re.IGNORECASE)
                        if p_match:
                            raw_data[p_field] = p_match.group(1).strip(" .\t-")
                            break

            # 10. LineFieldClassifier fallback for missing text fields
            if self.line_classifier.is_fitted and lines:
                if not raw_data.get("drawing_title"):
                    pred_line, prob, _ = self.line_classifier.predict_best_line(lines, "drawing_title", min_prob=0.55)
                    if pred_line:
                        clean_val = re.sub(r'^(?:DRAWING\s*)?TITLE[:\s\-]*', '', pred_line, flags=re.IGNORECASE).strip()
                        if len(clean_val) >= 3:
                            raw_data["drawing_title"] = clean_val

                if not raw_data.get("remark"):
                    pred_line, prob, _ = self.line_classifier.predict_best_line(lines, "remark", min_prob=0.60)
                    if pred_line:
                        clean_val = re.sub(r'^(?:REMARK|DESCRIPTION)[:\s\-]*', '', pred_line, flags=re.IGNORECASE).strip()
                        if len(clean_val) >= 3:
                            raw_data["remark"] = clean_val

            # 11. Clean Drawing Title of OCR artifacts (e.g. trailing 'oTe3', 'ores', 'OTs')
            curr_title = raw_data.get("drawing_title", "")
            if curr_title:
                m_noise = re.search(r'\s+([a-zA-Z0-9]{2,6})$', curr_title)
                if m_noise:
                    token = m_noise.group(1)
                    if not token.isupper() or (any(c.isdigit() for c in token) and any(c.isalpha() for c in token)):
                        curr_title = curr_title[:m_noise.start()].strip()
                clean_title = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', curr_title).strip()
                raw_data["drawing_title"] = clean_title

            # Re-apply manual corrections at the very end so explicit user edits always stick
            if filename in self.memory.get("manual_corrections", {}):
                for k, v in self.memory["manual_corrections"][filename].items():
                    if v:
                        raw_data[k] = v

            return raw_data


# Singleton instance
engine = LearningEngine()
