import os
import re
import getpass

# Application Directory
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Tesseract Executable Detection
def detect_tesseract_path():
    user_name = getpass.getuser()
    standard_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        f"C:\\Users\\{user_name}\\AppData\\Local\\Programs\\Tesseract-OCR\\tesseract.exe",
        r"C:\Users\ISDD\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
    ]
    for path in standard_paths:
        if os.path.exists(path):
            return path
    
    # Try finding in environment PATH
    import shutil
    path_in_env = shutil.which("tesseract")
    if path_in_env:
        return path_in_env
    
    return None

TESSERACT_CMD = detect_tesseract_path()

# Target Fields Definition
FIELD_DEFINITIONS = [
    {
        "key": "drawing_number",
        "label": "Drawing No.",
        "regex": [
            r"DRG[ \t\-_]*NO[ \t\-_:]*([A-Za-z0-9\.]+(?:\s*[\-\/]\s*[A-Za-z0-9\.]+)+)",
            r"DRAWING[ \t\-_]*NO[ \t\-_:]*([A-Za-z0-9\.]+(?:\s*[\-\/]\s*[A-Za-z0-9\.]+)+)",
            r"DWG[ \t\-_]*NO[ \t\-_:]*([A-Za-z0-9\.]+(?:\s*[\-\/]\s*[A-Za-z0-9\.]+)+)",
            r"DWG[ \t\-_:]*([A-Za-z0-9]+(?:\s*[\-\/]\s*[A-Za-z0-9\.]+){2,})",
            r"DRAWING[ \t\-_:]*([A-Za-z0-9]+(?:\s*[\-\/]\s*[A-Za-z0-9\.]+){2,})",
            # Fallbacks: Hyphenated drawing numbers with specific prefixes
            r"\b(BISPL(?:\s*-\s*[A-Z0-9\.]+)+)\b",
            r"\b(TCM(?:\s*-\s*[A-Z0-9\.]+)+)\b",
            r"\b(STD(?:\s*-\s*[A-Z0-9\.]+)+)\b",
            r"\b([A-Za-z0-9]{3,10}(?:\s*-\s*[A-Za-z0-9\.]+){3,})\b"
        ],
        "validation": {
            "type": "regex",
            "pattern": r"^[A-Za-z0-9\-\/\.]{4,50}$",
            "required": True
        },
        "description": "Standard engineering drawing number"
    },
    {
        "key": "drawing_title",
        "label": "Drawing Title",
        "regex": [
            r"TITLE[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\/]+)(?:\n|$)",
            r"DRAWING[ \t]+TITLE[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\/]+)(?:\n|$)",
            r"DESCRIPTION[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\/]+)(?:\n|$)",
            r"SUBJECT[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\/]+)(?:\n|$)",
            # Fallback for Secretariat & structural project drawings
            r"DETAIL[ \t]+OF[ \t]+[A-Za-z0-9 \t,\-\.\(\)\/]+",
            r"DIAGRID[ \t]+COLUMN"
        ],
        "validation": {
            "type": "text",
            "required": True
        },
        "description": "Title or description of the drawing"
    },
    {
        "key": "revision",
        "label": "Revision",
        "regex": [
            r"REV(?:ISION)?[ \t\-_]*NO[ \t\-_:]*\b(?!No\b)(?!NO\b)(?!Date\b)(?!DATE\b)(?!Desc\b)(?!DESC\b)([A-Za-z0-9]+)\b",
            r"REV[ \t\-_:]*\b(?!No\b)(?!NO\b)(?!Date\b)(?!DATE\b)(?!Desc\b)(?!DESC\b)([A-Za-z0-9]+)\b",
            r"REV\s+\b(?!No\b)(?!NO\b)(?!Date\b)(?!DATE\b)(?!Desc\b)(?!DESC\b)([A-Za-z0-9]+)\b",
            r"REV[ \t]*-[ \t]*([A-Za-z0-9]+)"
        ],
        "validation": {
            "type": "regex",
            "pattern": r"^[A-Za-z0-9]$|^[0-9]{2}$",
            "required": True
        },
        "description": "Revision number or character"
    },
    {
        "key": "weight",
        "label": "Weight",
        "regex": [
            # Total weight for all assemblies (e.g. 152.00 TOTAL WT. FOR 3 ASSEMBLIES)
            r"([0-9\.,]+)\s*(?:KG|kg|KA|ka|T|t|TON|ton)?\s*TOTAL\s*WT\.\s*FOR\s*[0-9]+\s*ASSEMBLIES?",
            r"([0-9\.,]+)\s*(?:KG|kg|KA|ka|T|t|TON|ton)?\s*TOTAL\s*WT\.\s*FOR\s*ALL\s*ASSEMBLIES?",
            r"TOTAL\s*WT\.\s*FOR\s*[0-9]+\s*ASSEMBLIES?\s*([0-9\.,]+)",
            r"TOTAL\s*WT\.\s*FOR\s*ALL\s*ASSEMBLIES?\s*([0-9\.,]+)",
            r"([0-9\.,]+)\s*(?:KG|kg|KA|ka)\s*TOTAL\s*(?:WEIGHT|WT)",
            r"TOTAL[ \t]*WEIGHT[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?",
            r"TOTAL[ \t]*WT[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?",
            r"NET[ \t]*WEIGHT[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?",
            # Unit weight for 1 assembly (fallback if total weight for all assemblies is not explicitly listed)
            r"([0-9\.,]+)\s*(?:KG|kg|KA|ka|T|t|TON|ton)?\s*TOTAL\s*WT\.\s*FOR\s*1\s*ASSEMBLY",
            r"([0-9\.,]+)\s*(?:KG|kg|KA|ka|T|t|TON|ton)?\s*WT\.?\s*FOR\s*1\s*ASSEMBLY",
            r"TOTAL\s*WT\.\s*FOR\s*1\s*ASSEMBLY\s*([0-9\.,]+)",
            r"WT[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?",
            r"WEIGHT[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?",
            r"MASS[ \t\-_:]*([0-9\.,]+)[ \t]*(?:kg|KG|ka|KA|t|T|ton|TON)?"
        ],
        "validation": {
            "type": "numeric",
            "required": False
        },
        "description": "Weight of the structure/part in Kg/Ton"
    },
    {
        "key": "quantity",
        "label": "Quantity",
        "regex": [
            r"QTY[ \t\-_:]*([0-9]+)",
            r"QUANTITY[ \t\-_:]*([0-9]+)",
            r"No\.?[ \t]*(?:Req'd|Reqd|Required)[ \t\-_:]*([0-9]+)",
            r"NO[ \t]*OFF[ \t\-_:]*([0-9]+)",
            r"([0-9]+)\s*QTY\s+[A-Za-z0-9\s]+\s+REQUIRED",
            r"([0-9]+)\s*QTY\b",
            r"([0-9]+)\s*OFFS?\b",
            r"([0-9]+)\s*NOS?\b"
        ],
        "validation": {
            "type": "integer",
            "required": False
        },
        "description": "Total quantity of items"
    },
    {
        "key": "sheet_number",
        "label": "Sheet",
        "regex": [
            r"SHEET[ \t\-_]*NO[ \t\-_:]*([0-9]+)",
            r"SHT[ \t\-_]*NO[ \t\-_:]*([0-9]+)",
            r"SH[ \t\-_]*NO[ \t\-_:]*([0-9]+)",
            r"SHEET[ \t\-_:]*([0-9]+)",
            r"SHT[ \t\-_:]*([0-9]+)",
            r"SH[ \t]*([0-9]+)",
            r"SHT[ \t]*([0-9]+)"
        ],
        "validation": {
            "type": "integer",
            "required": False
        },
        "description": "Current sheet number"
    },
    {
        "key": "total_sheets",
        "label": "Total Sheets",
        "regex": [
            r"OF[ \t]*([0-9]+)[ \t]*SHEETS",
            r"TOTAL[ \t\-_]*SHEETS[ \t\-_:]*([0-9]+)",
            r"SHEETS[ \t\-_:]*([0-9]+)",
            r"OF[ \t]*([0-9]+)"
        ],
        "validation": {
            "type": "integer",
            "required": False
        },
        "description": "Total sheets count"
    },
    {
        "key": "project_name",
        "label": "Project",
        "regex": [
            r"PROJECT[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\&]+)(?:\n|$)",
            r"PROJECT\s+NAME[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\&]+)(?:\n|$)",
            r"AMARAVATI\s+STATE\s+SECRETARIAT[A-Z0-9\s&\(\),]+"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Project identifier or description"
    },
    {
        "key": "client_name",
        "label": "Client",
        "regex": [
            r"CLIENT[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\&]+)(?:\n|$)",
            r"CUSTOMER[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)\&]+)(?:\n|$)",
            r"Andhra\s+Pradesh\s+Capital\s*Region\s+Development\s+Authority"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Client or Customer name"
    },
    {
        "key": "date",
        "label": "Date",
        "regex": [
            r"DATE[ \t\-_:]*([0-9A-Za-z\/\.\-]+)",
            r"DRAWN[ \t\-_]*DATE[ \t\-_:]*([0-9A-Za-z\/\.\-]+)",
            r"\b(\d{2}[\.\/\-]\d{2}[\.\/\-]\d{4})\b"
        ],
        "validation": {
            "type": "date",
            "required": False
        },
        "description": "Drawing creation or approval date"
    },
    {
        "key": "scale",
        "label": "Scale",
        "regex": [
            r"SCALE[ \t\-_:]*([0-9]+[ \t]*:[ \t]*[0-9]+|NTS|N\.T\.S\.)"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Drawing scale (e.g. 1:10 or NTS)"
    },
    {
        "key": "drawn_by",
        "label": "Drawn By",
        "regex": [
            r"DRAWN[ \t]*BY[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)",
            r"DRN[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Designer or draftsman initials/name"
    },
    {
        "key": "checked_by",
        "label": "Checked By",
        "regex": [
            r"CHECKED[ \t]*BY[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)",
            r"CHD[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Checker initials/name"
    },
    {
        "key": "approved_by",
        "label": "Approved By",
        "regex": [
            r"APPROVED[ \t]*BY[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)",
            r"APP[ \t\-_:]*([A-Za-z \t\.\-_]+)(?:\n|$)"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Approver initials/name"
    },
    {
        "key": "remark",
        "label": "Remark",
        "regex": [
            r"DESCRIPTION[ \t\-_:]*([A-Za-z0-9 \t,\-\.\(\)]+)(?:\n|$)",
            r"\b(ISSUED\s+FOR\s+[A-Za-z\s]+|REVISED\s+FOR\s+[A-Za-z\s]+|APPROVED\s+FOR\s+[A-Za-z\s]+|WELD\s+MODIFIED|QUANTITY\s+DECREASED|HOLD\s+PART\s+UPDATED|TEMPORARY\s+ELEMENTS\s+ADDED)\b"
        ],
        "validation": {
            "type": "text",
            "required": False
        },
        "description": "Revision description (reason for this revision)"
    }
]

# UI Design Settings (Modern Obsidian/Slate & Crisp Snow Palettes)
THEMES = {
    "dark": {
        "bg": "#0f172a",           # Deep Slate background
        "fg": "#f8fafc",           # Crisp light text
        "primary": "#6366f1",      # Modern Vibrant Indigo
        "primary_hover": "#4f46e5",
        "accent": "#06b6d4",       # Cyan highlight
        "surface": "#1e293b",      # Card surface
        "surface_subtle": "#334155",
        "border": "#334155",       # Soft border
        "text_secondary": "#94a3b8",
        "highlight_error": "#881337",
        "table_bg": "#0f172a",
        "table_alt": "#1e293b",    # Alternating row color
        "table_fg": "#e2e8f0",
        "table_selected": "#3b82f6",
        "success": "#10b981",      # Emerald green
        "warning": "#f59e0b",      # Amber
        "danger": "#ef4444"        # Rose
    },
    "light": {
        "bg": "#f8fafc",           # Light Slate Snow background
        "fg": "#0f172a",           # Slate dark text
        "primary": "#4f46e5",      # Royal Indigo
        "primary_hover": "#4338ca",
        "accent": "#0284c7",       # Ocean Blue
        "surface": "#ffffff",      # White surface
        "surface_subtle": "#f1f5f9",
        "border": "#cbd5e1",       # Light gray border
        "text_secondary": "#64748b",
        "highlight_error": "#ffe4e6",
        "table_bg": "#ffffff",
        "table_alt": "#f8fafc",    # Alternating row color
        "table_fg": "#1e293b",
        "table_selected": "#2563eb",
        "success": "#059669",
        "warning": "#d97706",
        "danger": "#dc2626"
    }
}

