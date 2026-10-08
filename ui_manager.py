import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import config
import pdf_processor
import title_block
import ocr_engine
import extractor
import excel_exporter
import learning_engine
import logger
import utils
from datetime import datetime

class DrawingExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Drawing PDF Auto Data Extraction System v2.0")
        self.root.geometry("1180x750")
        self.root.minsize(980, 640)

        # Application State
        self.input_folder = tk.StringVar(value="")
        self.output_folder = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Desktop"))
        self.current_theme = "dark" # Default theme
        self.all_data = []          # Master list of dicts from extractor.py
        self.filtered_data = []     # List of dicts showing in UI after search/filters
        self.processed_hashes = set() # Set of SHA-256 hashes of processed files
        self.last_clicked_column = "weight" # Default target column to copy
        self.sort_state = {}        # Tracking column sort direction
        
        # Multithreading / Scanning State
        self.is_scanning = False
        self.scan_thread = None
        self.scan_queue = queue.Queue()
        self.cancel_scan = False

        # Build UI layout
        self.setup_styles()
        self.build_ui()
        self.apply_theme(self.current_theme)
        
        # Initialize logs
        logger.setup_logging()
        
        # Periodic Queue checker
        self.root.after(100, self.check_queue)

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')

    def apply_theme(self, theme_name):
        colors = config.THEMES[theme_name]
        self.root.configure(bg=colors["bg"])
        
        # Configure standard widgets globally
        self.style.configure(".",
            background=colors["bg"],
            foreground=colors["fg"],
            font=("Segoe UI", 10),
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"]
        )
        
        # Frames
        self.style.configure("TFrame", background=colors["bg"])
        self.style.configure("Card.TFrame", background=colors["surface"], relief="flat", borderwidth=1)
        self.style.configure("KPI.TFrame", background=colors["surface"], relief="solid", borderwidth=1)
        
        # Standard Buttons
        self.style.configure("TButton",
            background=colors["surface"],
            foreground=colors["fg"],
            bordercolor=colors["border"],
            font=("Segoe UI", 10, "bold"),
            padding=(10, 6)
        )
        self.style.map("TButton",
            background=[("active", colors["primary_hover"]), ("disabled", colors["border"])],
            foreground=[("active", "#ffffff")]
        )
        
        # Primary Action Button Style
        self.style.configure("Action.TButton",
            background=colors["primary"],
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=(12, 6)
        )
        self.style.map("Action.TButton",
            background=[("active", colors["primary_hover"])]
        )

        # Cyan Accent Button Style (Copy Weight Button)
        self.style.configure("Accent.TButton",
            background=colors["accent"],
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=(12, 6)
        )
        self.style.map("Accent.TButton",
            background=[("active", "#0284c7")]
        )

        # Success Export Button Style
        self.style.configure("Success.TButton",
            background=colors["success"],
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padding=(10, 6)
        )
        self.style.map("Success.TButton",
            background=[("active", "#059669")]
        )
        
        # Labels
        self.style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
        self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=colors["primary"])
        self.style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), background=colors["surface"])
        self.style.configure("Stats.TLabel", font=("Segoe UI", 10, "bold"))
        self.style.configure("KPITitle.TLabel", font=("Segoe UI", 9), background=colors["surface"], foreground=colors["text_secondary"])
        self.style.configure("KPIValue.TLabel", font=("Segoe UI", 14, "bold"), background=colors["surface"], foreground=colors["primary"])
        
        # Entries & Comboboxes
        self.style.configure("TEntry",
            fieldbackground=colors["surface"],
            foreground=colors["fg"],
            bordercolor=colors["border"],
            insertcolor=colors["fg"]
        )
        self.style.configure("TMenubutton", background=colors["surface"], foreground=colors["fg"])
        self.style.configure("TProgressbar", thickness=14, troughcolor=colors["surface"], background=colors["primary"])
        
        # Treeview (Table) styling
        self.style.configure("Treeview",
            background=colors["table_bg"],
            fieldbackground=colors["table_bg"],
            foreground=colors["table_fg"],
            rowheight=26,
            font=("Segoe UI", 9)
        )
        self.style.configure("Treeview.Heading",
            background=colors["surface"],
            foreground=colors["fg"],
            bordercolor=colors["border"],
            font=("Segoe UI", 10, "bold")
        )
        self.style.map("Treeview.Heading",
            background=[("active", colors["primary"])],
            foreground=[("active", "#ffffff")]
        )
        self.style.map("Treeview",
            background=[("selected", colors["table_selected"])],
            foreground=[("selected", "#ffffff")]
        )
        
        # Color definitions for tags (Row & Zebra striping)
        if theme_name == "dark":
            self.tree.tag_configure("even", background=colors["table_bg"])
            self.tree.tag_configure("odd", background=colors["table_alt"])
            self.tree.tag_configure("suspicious", background="#451a03", foreground="#fde68a")
            self.tree.tag_configure("missing", background="#4c0519", foreground="#fecdd3")
            self.tree.tag_configure("valid", background=colors["table_bg"])
        else:
            self.tree.tag_configure("even", background=colors["table_bg"])
            self.tree.tag_configure("odd", background=colors["table_alt"])
            self.tree.tag_configure("suspicious", background="#fef3c7", foreground="#92400e")
            self.tree.tag_configure("missing", background="#ffe4e6", foreground="#9f1239")
            self.tree.tag_configure("valid", background=colors["table_bg"])
            
        # Update classic elements
        self.title_label.configure(foreground=colors["primary"])
        self.status_bar.configure(bg=colors["surface"], fg=colors["fg"])

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme(self.current_theme)

    def build_ui(self):
        # 1. Main Container
        self.main_container = ttk.Frame(self.root, padding=12)
        self.main_container.pack(fill="both", expand=True)

        # 2. Top Header Panel with Title & Theme Switcher
        header_frame = ttk.Frame(self.main_container)
        header_frame.pack(fill="x", pady=(0, 10))
        
        self.title_label = ttk.Label(header_frame, text="⚡ Drawing PDF Auto Data Extraction System", style="Title.TLabel")
        self.title_label.pack(side="left")

        right_header = ttk.Frame(header_frame)
        right_header.pack(side="right")
        
        self.ocr_status_label = ttk.Label(right_header, text="OCR: Checking...", font=("Segoe UI", 9, "italic"))
        self.ocr_status_label.pack(side="left", padx=10)
        self.check_ocr_status()

        total_learned = (
            len(learning_engine.engine.memory.get("drawing_prefixes", [])) +
            len(learning_engine.engine.memory.get("known_projects", [])) +
            len(learning_engine.engine.memory.get("known_clients", [])) +
            len(learning_engine.engine.memory.get("manual_corrections", {}))
        )
        self.learning_status_label = ttk.Label(right_header, text=f"🧠 Self-Learning Active ({total_learned} patterns)", font=("Segoe UI", 9, "bold"))
        self.learning_status_label.pack(side="left", padx=10)

        self.theme_btn = ttk.Button(right_header, text="🌙 Toggle Theme", command=self.toggle_theme)
        self.theme_btn.pack(side="right")

        # 3. Live KPI Metric Cards Panel (Summary dashboard)
        kpi_frame = ttk.Frame(self.main_container)
        kpi_frame.pack(fill="x", pady=(0, 10))

        # KPI 1: Total Drawings
        card1 = ttk.Frame(kpi_frame, style="KPI.TFrame", padding=(12, 8))
        card1.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ttk.Label(card1, text="TOTAL DRAWINGS", style="KPITitle.TLabel").pack(anchor="w")
        self.kpi_total_lbl = ttk.Label(card1, text="0", style="KPIValue.TLabel")
        self.kpi_total_lbl.pack(anchor="w")

        # KPI 2: Valid Extractions
        card2 = ttk.Frame(kpi_frame, style="KPI.TFrame", padding=(12, 8))
        card2.pack(side="left", fill="both", expand=True, padx=5)
        ttk.Label(card2, text="VALID RECORDS", style="KPITitle.TLabel").pack(anchor="w")
        self.kpi_valid_lbl = ttk.Label(card2, text="0", style="KPIValue.TLabel")
        self.kpi_valid_lbl.pack(anchor="w")

        # KPI 3: Needs Review
        card3 = ttk.Frame(kpi_frame, style="KPI.TFrame", padding=(12, 8))
        card3.pack(side="left", fill="both", expand=True, padx=5)
        ttk.Label(card3, text="SUSPICIOUS / REVIEW", style="KPITitle.TLabel").pack(anchor="w")
        self.kpi_review_lbl = ttk.Label(card3, text="0", style="KPIValue.TLabel")
        self.kpi_review_lbl.pack(anchor="w")

        # KPI 4: Total Combined Weight
        card4 = ttk.Frame(kpi_frame, style="KPI.TFrame", padding=(12, 8))
        card4.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ttk.Label(card4, text="TOTAL COMBINED WEIGHT", style="KPITitle.TLabel").pack(anchor="w")
        self.kpi_weight_lbl = ttk.Label(card4, text="0.0 kg", style="KPIValue.TLabel")
        self.kpi_weight_lbl.pack(anchor="w")

        # 4. Settings Card (Folder Paths)
        settings_frame = ttk.Frame(self.main_container, style="Card.TFrame", padding=8)
        settings_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(settings_frame, text="Drawings Folder:").grid(row=0, column=0, sticky="w", pady=4, padx=5)
        self.folder_entry = ttk.Entry(settings_frame, textvariable=self.input_folder, width=65)
        self.folder_entry.grid(row=0, column=1, sticky="ew", pady=4, padx=5)
        ttk.Button(settings_frame, text="Browse...", command=self.browse_input_folder).grid(row=0, column=2, pady=4, padx=5)

        ttk.Label(settings_frame, text="Excel Output Folder:").grid(row=1, column=0, sticky="w", pady=4, padx=5)
        self.output_entry = ttk.Entry(settings_frame, textvariable=self.output_folder, width=65)
        self.output_entry.grid(row=1, column=1, sticky="ew", pady=4, padx=5)
        ttk.Button(settings_frame, text="Browse...", command=self.browse_output_folder).grid(row=1, column=2, pady=4, padx=5)

        settings_frame.columnconfigure(1, weight=1)

        # 5. Primary Controls Card
        controls_frame = ttk.Frame(self.main_container, padding=2)
        controls_frame.pack(fill="x", pady=(0, 8))

        # Main Action Buttons
        self.scan_btn = ttk.Button(controls_frame, text="🚀 Scan Folder", style="Action.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left", padx=(0, 8))

        # Prominent "Copy Weight" Button
        self.copy_weight_btn = ttk.Button(controls_frame, text="📋 Copy Weight", style="Accent.TButton", command=self.copy_weight)
        self.copy_weight_btn.pack(side="left", padx=(0, 12))
        
        # Title Block Detection Mode
        ttk.Label(controls_frame, text="Title Block Detection:").pack(side="left", padx=(5, 5))
        self.tb_mode = tk.StringVar(value="default")
        self.tb_menu = ttk.OptionMenu(controls_frame, self.tb_mode, "default", "default", "auto")
        self.tb_menu.pack(side="left", padx=(0, 15))

        # Progress bar
        self.progress_bar = ttk.Progressbar(controls_frame, mode="determinate", length=220)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=8)

        self.progress_label = ttk.Label(controls_frame, text="0/0 Files (0%)", style="Stats.TLabel")
        self.progress_label.pack(side="right", padx=8)

        # 6. Filters Bar
        filters_frame = ttk.Frame(self.main_container, padding=2)
        filters_frame.pack(fill="x", pady=(0, 6))

        ttk.Label(filters_frame, text="🔍 Search:").pack(side="left", padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.apply_filters())
        self.search_entry = ttk.Entry(filters_frame, textvariable=self.search_var, width=28)
        self.search_entry.pack(side="left", padx=(0, 15))

        ttk.Label(filters_frame, text="Revision:").pack(side="left", padx=(0, 5))
        self.rev_filter_var = tk.StringVar(value="All")
        self.rev_filter_menu = ttk.Combobox(filters_frame, textvariable=self.rev_filter_var, width=8, state="readonly")
        self.rev_filter_menu["values"] = ["All"]
        self.rev_filter_menu.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())
        self.rev_filter_menu.pack(side="left")

        # Shortcut Hint Badge
        hint_lbl = ttk.Label(filters_frame, text="💡 Ctrl+W: Copy Weight | Ctrl+C: Copy Selected | Double-click: Edit Cell", font=("Segoe UI", 9, "italic"))
        hint_lbl.pack(side="right", padx=5)

        # 7. Data Preview Table
        table_frame = ttk.Frame(self.main_container)
        table_frame.pack(fill="both", expand=True, pady=(2, 8))

        self.table_cols = ["file_name"] + [f["key"] for f in config.FIELD_DEFINITIONS] + ["status"]
        self.table_headers = ["File Name"] + [f["label"] for f in config.FIELD_DEFINITIONS] + ["Status"]

        self.tree = ttk.Treeview(table_frame, columns=self.table_cols, show="headings", selectmode="extended")
        
        column_widths = {
            "file_name": 360,
            "drawing_number": 260,
            "drawing_title": 270,
            "revision": 70,
            "weight": 90,
            "quantity": 80,
            "sheet_number": 70,
            "total_sheets": 85,
            "project_name": 250,
            "client_name": 250,
            "date": 95,
            "scale": 80,
            "drawn_by": 80,
            "checked_by": 80,
            "approved_by": 80,
            "remark": 200,
            "status": 90
        }
        
        for idx, col_key in enumerate(self.table_cols):
            hdr_text = self.table_headers[idx]
            w = column_widths.get(col_key, 95)
            anchor = "w" if col_key == "file_name" else "center"
            # Enable column sorting on click
            self.tree.heading(col_key, text=hdr_text, anchor=anchor, command=lambda k=col_key: self.sort_column(k))
            self.tree.column(col_key, width=w, minwidth=50, anchor=anchor)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        # Binds
        self.tree.bind("<Double-1>", self.on_table_double_click)
        self.tree.bind("<Alt-MouseWheel>", self.on_alt_mousewheel)
        self.tree.bind("<Alt-Button-4>", lambda e: self.tree.xview_scroll(-1, "units"))
        self.tree.bind("<Alt-Button-5>", lambda e: self.tree.xview_scroll(1, "units"))

        self.tree.bind("<Button-1>", self.on_table_left_click, add="+")
        self.tree.bind("<Button-3>", self.on_table_right_click, add="+")

        # Copy shortcuts
        self.root.bind("<Control-w>", self.copy_weight)
        self.root.bind("<Control-W>", self.copy_weight)
        self.tree.bind("<Control-w>", self.copy_weight)
        self.tree.bind("<Control-W>", self.copy_weight)

        self.tree.bind("<Control-c>", self.copy_selected_rows)
        self.tree.bind("<Control-C>", self.copy_selected_rows)
        self.root.bind("<Control-c>", self.copy_selected_rows)
        self.root.bind("<Control-C>", self.copy_selected_rows)

        self.tree.bind("<Control-Shift-c>", self.copy_selected_rows_full)
        self.tree.bind("<Control-Shift-C>", self.copy_selected_rows_full)
        self.root.bind("<Control-Shift-c>", self.copy_selected_rows_full)
        self.root.bind("<Control-Shift-C>", self.copy_selected_rows_full)

        # 8. Action Bar at Bottom
        action_frame = ttk.Frame(self.main_container)
        action_frame.pack(fill="x", pady=(4, 0))

        self.export_btn = ttk.Button(action_frame, text="📥 Export to Excel", style="Success.TButton", command=self.export_to_excel, state="disabled")
        self.export_btn.pack(side="left", padx=(0, 10))

        self.open_out_btn = ttk.Button(action_frame, text="📂 Open Output Folder", command=self.open_output_folder)
        self.open_out_btn.pack(side="left")

        self.clear_btn = ttk.Button(action_frame, text="🧹 Clear Data", command=self.clear_all_data)
        self.clear_btn.pack(side="right")

        # 9. Status Bar
        self.status_bar = tk.Label(self.root, text="Ready. Load a drawings directory and click 'Scan Folder'.", bd=1, relief="sunken", anchor="w", padx=8, pady=3)
        self.status_bar.pack(side="bottom", fill="x")

    def check_ocr_status(self):
        if ocr_engine.is_ocr_available():
            self.ocr_status_label.configure(text="OCR Engine: Tesseract Available", foreground="#28a745")
        else:
            self.ocr_status_label.configure(text="OCR Engine: Not Installed (Scanned PDF fails)", foreground="#dc3545")

    def browse_input_folder(self):
        dir_selected = filedialog.askdirectory(title="Select Engineering Drawings Folder")
        if dir_selected:
            self.input_folder.set(dir_selected)

    def browse_output_folder(self):
        dir_selected = filedialog.askdirectory(title="Select Excel Output Folder")
        if dir_selected:
            self.output_folder.set(dir_selected)

    def update_revision_filter_menu(self):
        # Gather all distinct revisions in data
        revisions = set()
        for row in self.all_data:
            rev_val = row.get("revision", "")
            if rev_val:
                revisions.add(rev_val)
        
        sorted_revs = sorted(list(revisions))
        self.rev_filter_menu["values"] = ["All"] + sorted_revs

    def post_process_data(self):
        """
        Post-process all_data to default sheet numbers and Sheet 1 quantities.
        Only Sheet 1 (or sheets with the BOM box) should show quantities.
        Sheets > 1 have quantities cleared to empty by extractor.py.
        """
        import re
        import logging
        for row in self.all_data:
            filename = row.get("file_name", "")
            
            # Fix sheet number if missing (e.g. from filename SHT support)
            sheet_num_str = str(row.get("sheet_number", ""))
            if not sheet_num_str or sheet_num_str.strip() == "":
                sheet_match = re.search(r'(?:SHT|SH)[ \t\-_]*(\d+)', filename, re.IGNORECASE)
                if sheet_match:
                    sheet_num_str = str(int(sheet_match.group(1)))
                    row["sheet_number"] = sheet_num_str
                    if "_validation" in row and "sheet_number" in row["_validation"]:
                        row["_validation"]["sheet_number"]["is_valid"] = True
                        row["_validation"]["sheet_number"]["reason"] = ""
            
            # Check sheet number to determine defaulting
            try:
                sheet_num = int(sheet_num_str) if sheet_num_str else 1
            except ValueError:
                sheet_num = 1
                
            qty = str(row.get("quantity", ""))
            
            # If it is Sheet 1 and quantity is blank, default to "1"
            if sheet_num == 1:
                if not qty or qty.strip() == "":
                    row["quantity"] = "1"
                    if "_validation" in row and "quantity" in row["_validation"]:
                        row["_validation"]["quantity"]["is_valid"] = True
                        row["_validation"]["quantity"]["reason"] = ""
            
            # Recalculate row status safely
            if "_validation" in row:
                invalid_fields = []
                missing_required = []
                for field in config.FIELD_DEFINITIONS:
                    k = field["key"]
                    val = str(row.get(k, ""))
                    rule = field["validation"]
                    try:
                        is_valid, reason = extractor.validate_value(val, rule)
                    except Exception as e:
                        logging.error(f"Validation error on field {k} with value {val}: {e}")
                        is_valid, reason = True, ""
                    row["_validation"][k] = {"is_valid": is_valid, "reason": reason}
                    if not is_valid:
                        if not val or val.strip() == "":
                            if rule.get("required", False):
                                missing_required.append(k)
                        else:
                            invalid_fields.append(k)
                if missing_required:
                    row["status"] = "Missing"
                elif invalid_fields:
                    row["status"] = "Suspicious"
                else:
                    row["status"] = "Valid"

    def apply_filters(self):
        search_query = self.search_var.get().lower().strip()
        rev_filter = self.rev_filter_var.get()
        
        self.filtered_data = []
        for row in self.all_data:
            # Match search query against drawing number and drawing title
            dwg_no = row.get("drawing_number", "").lower()
            dwg_title = row.get("drawing_title", "").lower()
            rev_val = row.get("revision", "")
            
            match_search = (search_query in dwg_no) or (search_query in dwg_title) or (not search_query)
            match_rev = (rev_filter == "All") or (rev_filter == rev_val)
            
            if match_search and match_rev:
                self.filtered_data.append(row)
                
        self.refresh_table_view()

    def refresh_table_view(self):
        # Clear Treeview
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        total_weight = 0.0
        count_valid_weights = 0

        # Re-populate with zebra striping and status tags
        for idx, row in enumerate(self.filtered_data):
            row_values = []
            for col in self.table_cols:
                row_values.append(row.get(col, ""))
                
            status = row.get("status", "Valid")
            tag_name = "valid"
            if status == "Suspicious":
                tag_name = "suspicious"
            elif status == "Missing":
                tag_name = "missing"
                
            zebra_tag = "even" if idx % 2 == 0 else "odd"
            
            # Insert item with both status tag and zebra striping tag
            self.tree.insert("", "end", iid=str(idx), values=row_values, tags=(tag_name, zebra_tag))

            # Calculate total combined weight
            wt_str = str(row.get("weight", "")).strip().replace(",", "")
            if wt_str:
                try:
                    wt_val = float(wt_str)
                    total_weight += wt_val
                    count_valid_weights += 1
                except ValueError:
                    pass
            
        # Update live KPI Metric Cards
        total_count = len(self.all_data)
        valid_count = sum(1 for r in self.all_data if r.get("status") == "Valid")
        review_count = sum(1 for r in self.all_data if r.get("status") in ["Suspicious", "Missing"])
        
        self.kpi_total_lbl.configure(text=str(total_count))
        self.kpi_valid_lbl.configure(text=str(valid_count))
        self.kpi_review_lbl.configure(text=str(review_count))
        self.kpi_weight_lbl.configure(text=f"{total_weight:,.2f} kg" if total_weight > 0 else "0.0 kg")
        self.update_learning_badge()
        
        # Toggle export button state
        if self.all_data:
            self.export_btn.configure(state="normal")
        else:
            self.export_btn.configure(state="disabled")

    def update_learning_badge(self):
        if hasattr(self, 'learning_status_label'):
            total_learned = (
                len(learning_engine.engine.memory.get("drawing_prefixes", [])) +
                len(learning_engine.engine.memory.get("known_projects", [])) +
                len(learning_engine.engine.memory.get("known_clients", [])) +
                len(learning_engine.engine.memory.get("manual_corrections", {}))
            )
            self.learning_status_label.configure(text=f"🧠 Self-Learning Active ({total_learned} patterns)")

    def sort_column(self, col_key):
        """Sort treeview content ascending/descending when column header is clicked."""
        reverse = self.sort_state.get(col_key, False)
        
        def get_sort_key(row):
            val = row.get(col_key, "")
            if col_key in ["weight", "quantity", "sheet_number", "total_sheets"]:
                try:
                    return (0, float(str(val).replace(",", "")))
                except ValueError:
                    return (1, str(val))
            return (0, str(val).lower())

        self.filtered_data.sort(key=get_sort_key, reverse=reverse)
        self.sort_state[col_key] = not reverse
        
        # Update header arrow indicator
        for idx, k in enumerate(self.table_cols):
            base_title = self.table_headers[idx]
            if k == col_key:
                arrow = " ▲" if reverse else " ▼"
                self.tree.heading(k, text=base_title + arrow)
            else:
                self.tree.heading(k, text=base_title)
                
        self.refresh_table_view()

    def copy_weight(self, event=None):
        """
        Copies Weight column value(s) directly to clipboard.
        If table rows are selected, copies weights for selected rows.
        If no rows are selected, copies weights for all visible table rows.
        """
        focused_widget = self.root.focus_get()
        if isinstance(focused_widget, (ttk.Entry, tk.Entry)):
            return

        selection = self.tree.selection()
        if selection:
            target_indices = [int(iid) for iid in sorted(selection, key=int)]
            scope_desc = f"{len(target_indices)} selected drawing(s)"
        else:
            target_indices = list(range(len(self.filtered_data)))
            scope_desc = f"all {len(target_indices)} drawing(s)"

        if not target_indices or not self.filtered_data:
            messagebox.showinfo("Copy Weight", "No drawing records available to copy.")
            return

        weights = []
        sum_weight = 0.0
        valid_nums = 0

        for idx in target_indices:
            if idx < len(self.filtered_data):
                wt_str = str(self.filtered_data[idx].get("weight", "")).strip()
                weights.append(wt_str)
                if wt_str:
                    try:
                        sum_weight += float(wt_str.replace(",", ""))
                        valid_nums += 1
                    except ValueError:
                        pass

        text_to_copy = "\n".join(weights)
        self.copy_to_clipboard(text_to_copy)

        sum_str = f" (Total: {sum_weight:,.2f} kg)" if valid_nums > 0 else ""
        msg = f"Copied Weight column for {scope_desc}{sum_str}."
        self.status_bar.configure(text=msg)
        messagebox.showinfo("Weight Copied", f"Successfully copied {len(weights)} weight value(s) to clipboard!\n{sum_str}")

    # Double-click cell editing
    def on_table_double_click(self, event):
        if self.is_scanning:
            return

        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        
        if not row_id or not column_id:
            return

        col_idx = int(column_id.replace("#", "")) - 1
        if col_idx < 0 or col_idx >= len(self.table_cols):
            return

        col_key = self.table_cols[col_idx]
        if col_key in ["file_name", "status"]:
            return

        filtered_index = int(row_id)
        target_item = self.filtered_data[filtered_index]
        master_index = self.all_data.index(target_item)
        
        bbox = self.tree.bbox(row_id, column_id)
        if not bbox:
            return
            
        x, y, w, h = bbox
        
        entry = ttk.Entry(self.tree)
        entry.insert(0, str(target_item.get(col_key, "")))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, tk.END)

        def save_cell_value(event=None):
            new_val = entry.get()
            entry.destroy()
            
            clean_val = extractor.clean_extracted_value(col_key, new_val)
            self.all_data[master_index][col_key] = clean_val

            # Train learning engine from user manual correction
            try:
                fn = target_item.get("file_name", "")
                learning_engine.engine.learn_manual_edit(fn, col_key, clean_val)
            except Exception as ex:
                logging.error(f"Failed to save manual edit learning: {ex}")
            
            re_validated = extractor.process_extracted_document(
                self.all_data[master_index]["file_path"],
                "",
                self.all_data[master_index]["file_hash"]
            )
            for field in config.FIELD_DEFINITIONS:
                key = field["key"]
                if key == col_key:
                    re_validated[key] = clean_val
                else:
                    re_validated[key] = self.all_data[master_index].get(key, "")
                    
            new_validation = {}
            invalid_fields = []
            missing_required = []
            
            for field in config.FIELD_DEFINITIONS:
                k = field["key"]
                val = re_validated[k]
                rule = field["validation"]
                is_valid, reason = extractor.validate_value(val, rule)
                new_validation[k] = {"is_valid": is_valid, "reason": reason}
                
                if not is_valid:
                    if not val or val.strip() == "":
                        if rule.get("required", False):
                            missing_required.append(k)
                    else:
                        invalid_fields.append(k)
            
            re_validated["_validation"] = new_validation
            if missing_required:
                re_validated["status"] = "Missing"
            elif invalid_fields:
                re_validated["status"] = "Suspicious"
            else:
                re_validated["status"] = "Valid"
                
            self.all_data[master_index] = re_validated
            self.update_revision_filter_menu()
            self.apply_filters()

        entry.bind("<Return>", save_cell_value)
        entry.bind("<FocusOut>", save_cell_value)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def on_alt_mousewheel(self, event):
        if event.delta:
            self.tree.xview_scroll(-1 * int(event.delta / 120), "units")
        return "break"

    def copy_to_clipboard(self, text):
        """Helper to copy text directly to clipboard using tkinter's built-in system."""
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self.status_bar.configure(text="Copied to clipboard.")
        except Exception as e:
            import logging
            logging.error(f"Clipboard copy failed: {e}", exc_info=True)
            self.status_bar.configure(text=f"Copy failed: {e}")

    def on_table_left_click(self, event):
        """Focuses the table and records which column cell was left-clicked."""
        self.tree.focus_set()
        column_id = self.tree.identify_column(event.x)
        if column_id:
            try:
                col_idx = int(column_id.replace("#", "")) - 1
                if 0 <= col_idx < len(self.table_cols):
                    self.last_clicked_column = self.table_cols[col_idx]
            except Exception:
                pass

    def copy_selected_rows(self, event=None):
        """Copies either the active column value(s) (e.g. Weight) or full selected rows to the clipboard."""
        focused_widget = self.root.focus_get()
        if isinstance(focused_widget, (ttk.Entry, tk.Entry)):
            return

        selection = self.tree.selection()
        if not selection:
            return

        sorted_selection = sorted(selection, key=int)
        col_to_copy = getattr(self, "last_clicked_column", "weight")
        
        rows_text = []
        for iid in sorted_selection:
            idx = int(iid)
            if idx < len(self.filtered_data):
                row_data = self.filtered_data[idx]
                if col_to_copy:
                    rows_text.append(str(row_data.get(col_to_copy, "")))
                else:
                    row_values = [str(row_data.get(col, "")) for col in self.table_cols]
                    rows_text.append("\t".join(row_values))
                    
        text_to_copy = "\n".join(rows_text)
        self.copy_to_clipboard(text_to_copy)
        
        if col_to_copy:
            try:
                col_idx = self.table_cols.index(col_to_copy)
                col_name = self.table_headers[col_idx]
                self.status_bar.configure(text=f"Copied '{col_name}' value(s) for {len(sorted_selection)} row(s).")
            except Exception:
                self.status_bar.configure(text=f"Copied {len(sorted_selection)} value(s) to clipboard.")
        else:
            self.status_bar.configure(text=f"Copied {len(sorted_selection)} row(s) to clipboard.")

    def copy_selected_rows_full(self, event=None):
        """Copies full selected rows to the clipboard as tab-separated values, ignoring active column selection."""
        focused_widget = self.root.focus_get()
        if isinstance(focused_widget, (ttk.Entry, tk.Entry)):
            return

        selection = self.tree.selection()
        if not selection:
            return

        sorted_selection = sorted(selection, key=int)
        
        rows_text = []
        for iid in sorted_selection:
            idx = int(iid)
            if idx < len(self.filtered_data):
                row_data = self.filtered_data[idx]
                row_values = [str(row_data.get(col, "")) for col in self.table_cols]
                rows_text.append("\t".join(row_values))
                
        text_to_copy = "\n".join(rows_text)
        self.copy_to_clipboard(text_to_copy)
        self.status_bar.configure(text=f"Copied {len(sorted_selection)} full row(s) to clipboard.")

    def copy_selected_column_values(self, col_key):
        """Copies values of a specific column for all selected rows."""
        selection = self.tree.selection()
        if not selection:
            return

        sorted_selection = sorted(selection, key=int)
        vals = []
        for iid in sorted_selection:
            idx = int(iid)
            if idx < len(self.filtered_data):
                row_data = self.filtered_data[idx]
                vals.append(str(row_data.get(col_key, "")))
                
        text_to_copy = "\n".join(vals)
        self.copy_to_clipboard(text_to_copy)
        self.status_bar.configure(text=f"Copied column values for {len(sorted_selection)} row(s).")

    def copy_all_column_values(self, col_key):
        """Copies values of a specific column for all rows in the table."""
        if not self.filtered_data:
            return
            
        vals = [str(row_data.get(col_key, "")) for row_data in self.filtered_data]
        text_to_copy = "\n".join(vals)
        self.copy_to_clipboard(text_to_copy)
        self.status_bar.configure(text=f"Copied column values for all {len(self.filtered_data)} rows.")

    def copy_all_rows(self):
        """Copies all visible rows in the table as tab-separated values."""
        if not self.filtered_data:
            return
            
        rows_text = []
        for row_data in self.filtered_data:
            row_values = [str(row_data.get(col, "")) for col in self.table_cols]
            rows_text.append("\t".join(row_values))
            
        text_to_copy = "\n".join(rows_text)
        self.copy_to_clipboard(text_to_copy)
        self.status_bar.configure(text=f"Copied all {len(self.filtered_data)} rows.")

    def on_table_right_click(self, event):
        """Displays a right-click context menu with copying options for cells/columns/rows."""
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        
        if not row_id:
            return

        current_selection = self.tree.selection()
        if row_id not in current_selection:
            self.tree.selection_clear()
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            current_selection = (row_id,)

        col_idx = int(column_id.replace("#", "")) - 1 if column_id else -1
        if 0 <= col_idx < len(self.table_cols):
            col_key = self.table_cols[col_idx]
            col_name = self.table_headers[col_idx]
            self.last_clicked_column = col_key
            
            filtered_index = int(row_id)
            if filtered_index < len(self.filtered_data):
                target_item = self.filtered_data[filtered_index]
                cell_val = str(target_item.get(col_key, ""))
            else:
                cell_val = ""
        else:
            col_key = None
            cell_val = ""
            col_name = ""

        # Create popup menu
        menu = tk.Menu(self.root, tearoff=0)
        
        # Dedicated Quick-Copy options
        menu.add_command(
            label="⚖️ Copy Weight Column (Ctrl+W)",
            command=self.copy_weight
        )
        menu.add_command(
            label="📦 Copy Quantity Column",
            command=lambda: self.copy_selected_column_values("quantity")
        )
        menu.add_command(
            label="🏷️ Copy Drawing No. Column",
            command=lambda: self.copy_selected_column_values("drawing_number")
        )
        menu.add_separator()
        
        if col_key:
            display_val = cell_val if len(cell_val) < 25 else cell_val[:22] + "..."
            menu.add_command(
                label=f"Copy Cell: '{display_val}'",
                command=lambda: self.copy_to_clipboard(cell_val)
            )
            
            if len(current_selection) > 1:
                menu.add_command(
                    label=f"Copy Column '{col_name}' for Selected Rows",
                    command=lambda: self.copy_selected_column_values(col_key)
                )
            else:
                menu.add_command(
                    label=f"Copy Column '{col_name}' (All Rows)",
                    command=lambda: self.copy_all_column_values(col_key)
                )
            menu.add_separator()

        if len(current_selection) > 1:
            menu.add_command(
                label=f"Copy Selected Rows ({len(current_selection)} rows)",
                command=self.copy_selected_rows_full
            )
        else:
            menu.add_command(
                label="Copy Selected Row",
                command=self.copy_selected_rows_full
            )

        menu.add_command(
            label="Copy All Rows (Table)",
            command=self.copy_all_rows
        )
        
        menu.post(event.x_root, event.y_root)

    # --- Scanning & Processing Engine (Multithreaded) ---
    def start_scan(self):
        if self.is_scanning:
            # Act as cancel button
            self.cancel_scan = True
            self.status_bar.configure(text="Cancelling scan job...")
            return

        raw_folder = self.input_folder.get().strip(' "\'\t\r\n')
        folder = os.path.normpath(raw_folder) if raw_folder else ""
        if folder:
            self.input_folder.set(folder)

        if not folder or not os.path.isdir(folder):
            messagebox.showerror(
                "Invalid Directory",
                f"The directory path could not be found or opened:\n\n'{raw_folder}'\n\nPlease click 'Browse...' to select a valid drawings folder."
            )
            return

        # Fetch pdf files
        files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".pdf")]
        if not files:
            messagebox.showinfo("No Files", "No drawing PDFs found in selected directory.")
            return

        # Configure UI states
        self.is_scanning = True
        self.cancel_scan = False
        self.scan_btn.configure(text="⏹️ Stop Scan", style="TButton")
        self.status_bar.configure(text="Starting scan job...")
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = len(files)
        self.progress_label.configure(text=f"0/{len(files)} Files (0%)")
        self.clear_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        
        # Start background processing thread
        logger.stats.start_session(len(files))
        self.scan_thread = threading.Thread(
            target=self.scan_worker_thread,
            args=(files, self.tb_mode.get()),
            daemon=True
        )
        self.scan_thread.start()

    def scan_worker_thread(self, file_paths, tb_mode):
        start_time = datetime.now()
        processed_count = 0
        
        for idx, file_path in enumerate(file_paths):
            if self.cancel_scan:
                logging.info("Extraction scan canceled by user.")
                break
                
            filename = os.path.basename(file_path)
            self.scan_queue.put({"type": "status", "text": f"Scanning file: {filename}"})
            
            try:
                if self.cancel_scan: break
                # 1. Skip duplicates based on hash
                file_hash = utils.calculate_file_hash(file_path)
                if not file_hash:
                    raise Exception("Could not compute file hash")
                    
                if file_hash in self.processed_hashes:
                    logger.stats.skipped_files.append(filename)
                    logging.info(f"Skipped duplicate file: '{filename}' (hash: {file_hash})")
                    self.scan_queue.put({
                        "type": "progress",
                        "index": idx + 1,
                        "total": len(file_paths),
                        "elapsed": (datetime.now() - start_time).total_seconds()
                    })
                    continue

                if self.cancel_scan: break
                # 2. PDF Parsing Text vs OCR
                is_scanned = pdf_processor.is_scanned_pdf(file_path)
                text = ""
                
                if not is_scanned:
                    # Text-based extraction
                    text = pdf_processor.extract_text_from_pdf(file_path)
                else:
                    # Scanned PDF - perform OCR
                    if not ocr_engine.is_ocr_available():
                        raise Exception("Tesseract OCR is not installed. Scanned drawings cannot be parsed.")
                    
                    if self.cancel_scan: break
                    # Convert first page to PIL image
                    pil_img = pdf_processor.pdf_page_to_image(file_path, page_num=0, dpi=300)
                    if not pil_img:
                        raise Exception("Failed to render PDF page to image for OCR.")
                        
                    if self.cancel_scan: break
                    # Preprocess and Crop title block in OpenCV
                    cv_img = title_block.pil_to_cv(pil_img)
                    if tb_mode == "auto":
                        cropped_cv, _ = title_block.detect_and_crop_title_block_auto(cv_img)
                    else:
                        cropped_cv, _ = title_block.crop_title_block_default(cv_img)
                        
                    if self.cancel_scan: break
                    # Preprocess image
                    enhanced_cv = title_block.preprocess_image_for_ocr(cropped_cv)
                    enhanced_pil = title_block.cv_to_pil(enhanced_cv)
                    
                    if self.cancel_scan: break
                    # Run OCR
                    text = ocr_engine.run_ocr(enhanced_pil)
                
                if self.cancel_scan: break
                # 3. Extract & Validate Document fields
                doc_data = extractor.process_extracted_document(file_path, text, file_hash)
                
                # Update processed hashes and push results
                self.processed_hashes.add(file_hash)
                logger.stats.successful_extractions += 1
                
                self.scan_queue.put({"type": "row", "data": doc_data})
                
            except Exception as e:
                err_msg = str(e)
                logger.stats.failed_files.append((filename, err_msg))
                logging.error(f"Error processing '{filename}': {err_msg}")
                self.scan_queue.put({"type": "error", "file": filename, "msg": err_msg})
                
            # Update Progress status
            self.scan_queue.put({
                "type": "progress",
                "index": idx + 1,
                "total": len(file_paths),
                "elapsed": (datetime.now() - start_time).total_seconds()
            })

        logger.stats.end_session()
        summary_log = logger.stats.generate_summary()
        logging.info(summary_log)
        
        self.scan_queue.put({"type": "finished", "summary": summary_log})

    def check_queue(self):
        """
        Runs on main thread, checking queue to update UI components.
        """
        try:
            while True:
                msg = self.scan_queue.get_nowait()
                msg_type = msg["type"]
                
                if msg_type == "status":
                    self.status_bar.configure(text=msg["text"])
                    
                elif msg_type == "row":
                    self.all_data.append(msg["data"])
                    self.update_revision_filter_menu()
                    self.apply_filters()
                    
                elif msg_type == "error":
                    # We continue on error, but log it to status bar or logs
                    self.status_bar.configure(text=f"Error on {msg['file']}: {msg['msg']}")
                    
                elif msg_type == "progress":
                    idx = msg["index"]
                    total = msg["total"]
                    elapsed = msg["elapsed"]
                    
                    pct = int((idx / total) * 100)
                    self.progress_bar["value"] = idx
                    
                    # Calculate ETA
                    if idx > 0 and idx < total:
                        avg_time = elapsed / idx
                        eta_seconds = int(avg_time * (total - idx))
                        eta_min = eta_seconds // 60
                        eta_sec = eta_seconds % 60
                        eta_str = f" | ETA: {eta_min:02d}:{eta_sec:02d}"
                    else:
                        eta_str = ""
                        
                    self.progress_label.configure(text=f"{idx}/{total} Files ({pct}%){eta_str}")
                    
                elif msg_type == "finished":
                    self.is_scanning = False
                    self.scan_btn.configure(text="🚀 Scan Folder", style="Action.TButton")
                    self.clear_btn.configure(state="normal")
                    import logging
                    try:
                        self.post_process_data()
                    except Exception as ex:
                        logging.error(f"Error in post_process_data: {ex}", exc_info=True)
                    self.apply_filters()
                    
                    if self.cancel_scan:
                        self.status_bar.configure(text="Scan Job Stopped by User.")
                    else:
                        self.status_bar.configure(text="Scan Job Completed.")
                        # Display summary report
                        messagebox.showinfo("Extraction Complete", msg["summary"])
                    
                self.scan_queue.task_done()
        except queue.Empty:
            pass
            
        # Re-register
        self.root.after(100, self.check_queue)

    def export_to_excel(self):
        if not self.all_data:
            return
            
        raw_out = self.output_folder.get().strip(' "\'\t\r\n')
        out_dir = os.path.normpath(raw_out) if raw_out else ""
        if out_dir:
            self.output_folder.set(out_dir)

        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("Error", "Please select a valid Output Excel Folder first.")
            return

        try:
            excel_path = excel_exporter.export_data_to_excel(self.all_data, out_dir)
            messagebox.showinfo("Export Successful", f"Excel sheet generated successfully!\nSaved to:\n{excel_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred while generating Excel sheet:\n{e}")

    def open_output_folder(self):
        raw_out = self.output_folder.get().strip(' "\'\t\r\n')
        out_dir = os.path.normpath(raw_out) if raw_out else ""
        if out_dir and os.path.isdir(out_dir):
            os.startfile(out_dir)
        else:
            messagebox.showerror("Error", "Output directory does not exist or cannot be opened.")

    def clear_all_data(self):
        if messagebox.askyesno("Clear All", "Are you sure you want to clear all extracted records from memory?"):
            self.all_data = []
            self.filtered_data = []
            self.processed_hashes = set()
            self.rev_filter_menu["values"] = ["All"]
            self.rev_filter_var.set("All")
            self.search_var.set("")
            self.refresh_table_view()
            self.progress_bar["value"] = 0
            self.progress_label.configure(text="0/0 Files (0%)")
            self.status_bar.configure(text="Data cleared.")
